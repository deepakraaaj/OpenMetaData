"""Detect semantic gaps from normalized schema + current knowledge state.

Question generation is confirmation-first:
- form a best guess from metadata
- show concise evidence
- ask only for medium/low-confidence, important gaps
- prefer constrained choices over free text
"""
from __future__ import annotations

from collections import defaultdict
import re

from app.core.inference_rules import SemanticInferenceRules, load_inference_rules
from app.models.normalized import NormalizedColumn, NormalizedSource, NormalizedTable
from app.models.questionnaire import QuestionAction, QuestionOption
from app.models.review import TableRole
from app.models.semantic import TableReviewStatus
from app.models.state import GapCategory, KnowledgeState, SemanticGap
from app.models.source_attribution import DiscoverySource
from app.utils.enum_candidates import (
    has_business_enum_signal,
    is_declared_enum_type,
    is_enum_candidate,
)
from app.utils.text import snake_to_words, unique_non_empty


MAX_GAPS_PER_CATEGORY = 25

_GENERIC_MEANING_PREFIXES = (
    "Business attribute for ",
    "Reference to a related ",
    "Primary records for ",
    "Detailed records associated with ",
    "Historical event records for ",
    "Timestamp used for audit",
)


class GapDetector:
    """Scans normalized metadata and current state to find high-value unresolved gaps."""

    def __init__(self, rules: SemanticInferenceRules | None = None) -> None:
        self.rules = rules or load_inference_rules()

    def detect(self, normalized: NormalizedSource, state: KnowledgeState) -> list[SemanticGap]:
        gaps: list[SemanticGap] = []
        gaps.extend(self._unknown_table_meanings(normalized, state))
        gaps.extend(self._unconfirmed_enums(normalized, state))
        gaps.extend(self._ambiguous_relationships(normalized, state))
        if len(gaps) < 100:
            gaps.extend(self._potential_sensitivity(normalized, state))
            gaps.extend(self._glossary_gaps(normalized, state))
        return gaps

    def _unknown_table_meanings(
        self, normalized: NormalizedSource, state: KnowledgeState
    ) -> list[SemanticGap]:
        gaps: list[SemanticGap] = []
        covered_tables = self._pattern_covered_tables(state)
        for table in normalized.tables:
            existing = state.tables.get(table.table_name)
            if self._is_skipped_table(existing):
                continue
            if existing and existing.attribution.source == DiscoverySource.CONFIRMED_BY_USER:
                continue
            if existing and existing.role in {TableRole.log_event, TableRole.history_audit, TableRole.config_system} and not existing.selected:
                continue
            if existing and not existing.requires_review and existing.confidence.score >= 0.72:
                continue
            if existing and table.table_name in covered_tables and existing.role != TableRole.unknown:
                continue

            confidence = self._score(existing.confidence.score if existing else 0.35)
            impact = self._table_impact_score(table)
            business_relevance = self._table_business_relevance(table, existing)
            naming_strength = self._table_naming_strength(table, existing)
            best_guess = self._table_best_guess(table, existing)
            generic_guess = self._looks_generic_meaning(best_guess)
            ambiguity = self._score(
                max(
                    0.2,
                    1.0 - confidence + (0.16 if generic_guess else 0.0) - (0.14 if naming_strength >= 0.75 else 0.0),
                )
            )
            priority_score = self._priority_score(impact, ambiguity, business_relevance)

            if confidence >= 0.84 and naming_strength >= 0.74:
                continue
            if naming_strength >= 0.78 and impact <= 0.42 and business_relevance <= 0.5:
                continue
            if priority_score < 0.18:
                continue

            evidence = self._table_evidence(table, existing)
            options = self._table_candidate_options(table, existing, best_guess)
            decision_prompt = f"Which interpretation is closest for `{table.table_name}`?"
            gaps.append(
                SemanticGap(
                    gap_id=f"meaning-{table.table_name}",
                    category=GapCategory.UNKNOWN_BUSINESS_MEANING,
                    target_entity=table.table_name,
                    description=f"Business meaning for table '{table.table_name}' is unconfirmed.",
                    suggested_question=decision_prompt,
                    question_type="meaning_confirmation",
                    best_guess=best_guess,
                    confidence=confidence,
                    evidence=evidence,
                    candidate_options=options,
                    decision_prompt=decision_prompt,
                    actions=self._default_actions(),
                    impact_score=impact,
                    ambiguity_score=ambiguity,
                    business_relevance=business_relevance,
                    priority_score=priority_score,
                    allow_free_text=True,
                    free_text_placeholder="Describe the real business entity or workflow only if none of the options fit.",
                    metadata={
                        "grain_hint": table.grain_hint or "",
                        "entity_hint": table.entity_hint or "",
                        "neighbor_tables": self._relationship_neighbors(table.join_candidates, table.table_name),
                        "important_columns": self._important_columns(table),
                        "naming_strength": naming_strength,
                    },
                    is_blocking=False,
                    priority=self._priority_bucket(priority_score),
                )
            )
        gaps.sort(key=lambda gap: (-gap.priority_score, gap.gap_id))
        return gaps[:MAX_GAPS_PER_CATEGORY]

    def _unconfirmed_enums(
        self, normalized: NormalizedSource, state: KnowledgeState
    ) -> list[SemanticGap]:
        gaps: list[SemanticGap] = []
        covered_tables = self._pattern_covered_tables(state)
        table_map = {table.table_name: table for table in normalized.tables}
        for table in normalized.tables:
            existing = state.tables.get(table.table_name)
            if self._is_skipped_table(existing):
                continue
            if existing and existing.attribution.source == DiscoverySource.CONFIRMED_BY_USER:
                continue
            if existing and (not existing.selected or (table.table_name in covered_tables and not existing.requires_review)):
                continue

            table_impact = self._table_impact_score(table)
            table_relevance = self._table_business_relevance(table, existing)
            for col in table.columns:
                lookup_tables = self._enum_lookup_tables(table, col.column_name, table_map)
                if not self._is_meaningful_enum_column(
                    col.column_name,
                    col.technical_type,
                    col.enum_values,
                    col.sample_values,
                    lookup_tables=lookup_tables,
                    is_foreign_key=col.is_foreign_key,
                ):
                    continue
                if col.is_primary_key or col.is_identifier_like:
                    continue
                if col.is_foreign_key and not lookup_tables and not self._has_enum_signal(col.column_name):
                    continue

                col_key = f"{table.table_name}.{col.column_name}"
                confirmed_enums = state.enums.get(col_key, [])
                if any(e.attribution.source == DiscoverySource.CONFIRMED_BY_USER for e in confirmed_enums):
                    continue
                if self._enum_pattern_already_confirmed(existing, col.column_name):
                    continue

                values = self._meaningful_distinct_values(col.enum_values or col.sample_values)
                if not values:
                    continue

                confidence = self._enum_confidence(existing, col.column_name)
                ambiguity = self._enum_ambiguity(col.column_name, values)
                impact = self._score(min(1.0, table_impact + (0.08 if col.is_status_like else 0.02)))
                business_relevance = self._score(min(1.0, table_relevance + (0.1 if col.is_status_like else 0.0)))
                priority_score = self._priority_score(impact, ambiguity, business_relevance)
                if priority_score < 0.2:
                    continue

                lookup_labels = self._lookup_label_candidates(table_map, lookup_tables, values)
                best_guess, options = self._enum_guess_and_options(
                    col.column_name,
                    values,
                    lookup_tables=lookup_tables,
                    lookup_labels=lookup_labels,
                )
                evidence = unique_non_empty(
                    [
                        f"column name suggests {self._enum_name_signal(col.column_name)}",
                        f"observed values: {', '.join(values[:6])}",
                        f"related lookup tables: {', '.join(lookup_tables[:3])}" if lookup_tables else "",
                        f"lookup labels seen elsewhere: {', '.join(lookup_labels[:6])}" if lookup_labels else "",
                    ]
                    + self._column_rationale(existing, col.column_name)
                )[:4]
                decision_prompt = f"What kind of business meaning does `{col_key}` represent?"
                gaps.append(
                    SemanticGap(
                        gap_id=f"enum-{col_key}",
                        category=GapCategory.UNCONFIRMED_ENUM_MAPPING,
                        target_entity=table.table_name,
                        target_property=col.column_name,
                        description=f"Column '{col_key}' has unconfirmed business value interpretation.",
                        suggested_question=decision_prompt,
                        question_type="pattern_confirmation",
                        best_guess=best_guess,
                        confidence=confidence,
                        evidence=evidence,
                        candidate_options=options,
                        decision_prompt=decision_prompt,
                        actions=self._default_actions(),
                        impact_score=impact,
                        ambiguity_score=ambiguity,
                        business_relevance=business_relevance,
                        priority_score=priority_score,
                        allow_free_text=True,
                        free_text_placeholder=(
                            "Optional: rename values or describe the exact mapping if the default interpretation is incomplete."
                        ),
                        metadata={
                            "observed_values": values[:8],
                            "table_entity_hint": table.entity_hint or "",
                            "lookup_tables": lookup_tables,
                            "auto_labels": self._default_enum_labels(
                                values,
                                column_name=col.column_name,
                                lookup_labels=lookup_labels,
                            ),
                        },
                        is_blocking=False,
                        priority=self._priority_bucket(priority_score),
                    )
                )
        gaps.sort(key=lambda gap: (-gap.priority_score, gap.gap_id))
        return gaps[:MAX_GAPS_PER_CATEGORY]

    def _ambiguous_relationships(
        self, normalized: NormalizedSource, state: KnowledgeState
    ) -> list[SemanticGap]:
        gaps: list[SemanticGap] = []
        covered_tables = self._pattern_covered_tables(state)
        for table in normalized.tables:
            existing = state.tables.get(table.table_name)
            if self._is_skipped_table(existing):
                continue
            if not table.join_candidates:
                continue
            if existing and existing.attribution.source == DiscoverySource.CONFIRMED_BY_USER:
                continue
            if existing and not existing.selected:
                continue
            if existing and table.table_name in covered_tables and not existing.requires_review:
                continue

            table_impact = self._table_impact_score(table)
            table_relevance = self._table_business_relevance(table, existing)
            for column_name, candidates in self._group_join_candidates(table.join_candidates).items():
                if self._is_relationship_noise_column(column_name):
                    continue

                ranked = self._rank_relationship_candidates(column_name, candidates)
                if len(ranked) < 2 or len(ranked) > 5:
                    continue
                top_score = ranked[0][1]
                second_score = ranked[1][1]
                if top_score >= 3 and top_score > second_score + 1:
                    continue

                candidate_tables = [table_name for table_name, _score, _join in ranked]
                candidate_joins = {table_name: join for table_name, _score, join in ranked}
                confidence = self._score(0.42 + min(top_score * 0.09, 0.22))
                ambiguity = self._score(0.45 + min((len(ranked) - 1) * 0.12, 0.24) + (0.12 if top_score == second_score else 0.0))
                impact = self._score(min(1.0, table_impact + 0.08))
                business_relevance = self._score(min(1.0, table_relevance + 0.08))
                priority_score = self._priority_score(impact, ambiguity, business_relevance)
                if priority_score < 0.18:
                    continue

                best_guess = candidate_tables[0]
                evidence = unique_non_empty(
                    [
                        f"column name `{column_name}` overlaps with `{candidate_tables[0]}`",
                        f"candidate joins: {', '.join(candidate_tables)}",
                        f"closest inferred join: {candidate_joins[candidate_tables[0]]}",
                    ]
                )[:4]
                options = [
                    self._option(
                        value=table_name,
                        label=snake_to_words(table_name),
                        description=candidate_joins.get(table_name),
                        is_best_guess=index == 0,
                    )
                    for index, table_name in enumerate(candidate_tables)
                ]
                options.append(
                    self._option(
                        value="__other__",
                        label="Something else",
                        description="None of these tables is the real business target.",
                        is_fallback=True,
                    )
                )
                decision_prompt = f"Which entity does `{table.table_name}.{column_name}` most likely reference?"
                gaps.append(
                    SemanticGap(
                        gap_id=f"rel-{table.table_name}-{column_name}",
                        category=GapCategory.AMBIGUOUS_RELATIONSHIP,
                        target_entity=table.table_name,
                        target_property=column_name,
                        description=f"Column '{table.table_name}.{column_name}' may reference one of several entities.",
                        suggested_question=decision_prompt,
                        question_type="role_confirmation",
                        best_guess=best_guess,
                        confidence=confidence,
                        evidence=evidence,
                        candidate_options=options,
                        decision_prompt=decision_prompt,
                        actions=self._default_actions(),
                        impact_score=impact,
                        ambiguity_score=ambiguity,
                        business_relevance=business_relevance,
                        priority_score=priority_score,
                        allow_free_text=True,
                        free_text_placeholder="If none of the options is right, enter the real target table or entity.",
                        metadata={
                            "candidate_tables": candidate_tables,
                            "candidate_joins": candidate_joins,
                        },
                        is_blocking=False,
                        priority=self._priority_bucket(priority_score),
                    )
                )
        gaps.sort(key=lambda gap: (-gap.priority_score, gap.gap_id))
        return gaps[:MAX_GAPS_PER_CATEGORY]

    def _potential_sensitivity(
        self, normalized: NormalizedSource, state: KnowledgeState
    ) -> list[SemanticGap]:
        gaps: list[SemanticGap] = []
        for table in normalized.tables:
            existing = state.tables.get(table.table_name)
            if self._is_skipped_table(existing):
                continue

            table_impact = self._table_impact_score(table)
            table_relevance = self._table_business_relevance(table, existing)
            for col in table.columns:
                if not col.sensitivity_hints:
                    continue
                col_key = f"{table.table_name}.{col.column_name}"
                if existing:
                    existing_col = next((c for c in existing.columns if c.column_name == col.column_name), None)
                    if existing_col and existing_col.attribution.source == DiscoverySource.CONFIRMED_BY_USER:
                        continue

                impact = self._score(min(1.0, table_impact + 0.04))
                ambiguity = 0.42
                business_relevance = self._score(min(1.0, table_relevance + 0.04))
                priority_score = self._priority_score(impact, ambiguity, business_relevance)
                if priority_score < 0.16:
                    continue

                evidence = unique_non_empty(
                    [
                        f"sensitivity hints: {', '.join(col.sensitivity_hints[:4])}",
                        f"column name: {col.column_name}",
                    ]
                )[:3]
                options = [
                    self._option("mask", "Mask this column", "Hide it in chatbot answers and reports.", is_best_guess=True),
                    self._option("display", "Allow display", "Safe to show in normal business workflows."),
                    self._option("__other__", "Something else", "Use custom handling or role-based restrictions.", is_fallback=True),
                ]
                decision_prompt = f"How should `{col_key}` be handled in user-facing outputs?"
                gaps.append(
                    SemanticGap(
                        gap_id=f"sensitivity-{col_key}",
                        category=GapCategory.POTENTIAL_SENSITIVITY,
                        target_entity=table.table_name,
                        target_property=col.column_name,
                        description=f"Column '{col_key}' may contain sensitive data.",
                        suggested_question=decision_prompt,
                        question_type="ignore_confirmation",
                        best_guess="Mask this column",
                        confidence=0.58,
                        evidence=evidence,
                        candidate_options=options,
                        decision_prompt=decision_prompt,
                        actions=self._default_actions(),
                        impact_score=impact,
                        ambiguity_score=ambiguity,
                        business_relevance=business_relevance,
                        priority_score=priority_score,
                        allow_free_text=True,
                        free_text_placeholder="Optional: describe a more specific masking rule or exception.",
                        metadata={"sensitivity_hints": list(col.sensitivity_hints[:6])},
                        is_blocking=False,
                        priority=self._priority_bucket(priority_score),
                    )
                )
        gaps.sort(key=lambda gap: (-gap.priority_score, gap.gap_id))
        return gaps[:MAX_GAPS_PER_CATEGORY]

    def _glossary_gaps(
        self, normalized: NormalizedSource, state: KnowledgeState
    ) -> list[SemanticGap]:
        gaps: list[SemanticGap] = []
        glossary_terms = {key.lower() for key in state.glossary}
        for table in normalized.tables:
            existing = state.tables.get(table.table_name)
            if self._is_skipped_table(existing):
                continue
            if existing and existing.attribution.source == DiscoverySource.CONFIRMED_BY_USER:
                continue

            term = str(table.entity_hint or snake_to_words(table.table_name)).strip()
            if not term or term.lower() in glossary_terms:
                continue

            impact = self._table_impact_score(table)
            business_relevance = self._table_business_relevance(table, existing)
            ambiguity = self._score(max(0.25, 0.78 - (existing.confidence.score if existing else 0.35)))
            priority_score = self._priority_score(impact, ambiguity, business_relevance)
            if priority_score < 0.16:
                continue

            decision_prompt = f"What term should users see for `{table.table_name}`?"
            options = [
                self._option(term, term, "Use the inferred entity label.", is_best_guess=True),
                self._option(snake_to_words(table.table_name), snake_to_words(table.table_name), "Use the table name in plain words."),
                self._option("__other__", "Something else", "Use a different business label.", is_fallback=True),
            ]
            evidence = unique_non_empty(
                [
                    f"entity hint: {table.entity_hint}" if table.entity_hint else "",
                    f"business meaning guess: {existing.business_meaning}" if existing and existing.business_meaning else "",
                    f"important columns: {', '.join(self._important_columns(table)[:4])}",
                ]
            )[:4]
            gaps.append(
                SemanticGap(
                    gap_id=f"glossary-{table.table_name}",
                    category=GapCategory.GLOSSARY_TERM_MISSING,
                    target_entity=table.table_name,
                    description=f"No glossary entry exists yet for '{term}'.",
                    suggested_question=decision_prompt,
                    question_type="domain_confirmation",
                    best_guess=term,
                    confidence=self._score(existing.confidence.score if existing else 0.4),
                    evidence=evidence,
                    candidate_options=options,
                    decision_prompt=decision_prompt,
                    actions=self._default_actions(),
                    impact_score=impact,
                    ambiguity_score=ambiguity,
                    business_relevance=business_relevance,
                    priority_score=priority_score,
                    allow_free_text=True,
                    free_text_placeholder="Enter the business term users actually say in dashboards or SOPs.",
                    is_blocking=False,
                    priority=self._priority_bucket(priority_score),
                )
            )
        gaps.sort(key=lambda gap: (-gap.priority_score, gap.gap_id))
        return gaps[:MAX_GAPS_PER_CATEGORY]

    def _meaningful_distinct_values(self, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for raw in values:
            value = str(raw or "").strip()
            lowered = value.lower()
            if not value or lowered in seen:
                continue
            if lowered in {"<bytes>", "null", "none", "nan"}:
                continue
            seen.add(lowered)
            cleaned.append(value)
        return cleaned

    def _important_columns(self, table: NormalizedTable) -> list[str]:
        return [
            column.column_name
            for column in table.columns
            if not self._is_low_signal_column(column.column_name)
        ][:6]

    def _is_low_signal_column(self, column_name: str) -> bool:
        name = str(column_name or "").strip().lower()
        rules = self.rules.gap_detection
        if not name:
            return True
        if name in rules.audit_column_names:
            return True
        if name.endswith("_id") or (rules.audit_column_suffixes and name.endswith(rules.audit_column_suffixes)):
            return True
        if any(token in name for token in rules.temporal_name_tokens):
            return True
        return False

    def _is_relationship_noise_column(self, column_name: str) -> bool:
        name = str(column_name or "").strip().lower()
        rules = self.rules.gap_detection
        if not name:
            return True
        if name in rules.audit_column_names:
            return True
        if rules.audit_column_suffixes and name.endswith(rules.audit_column_suffixes):
            return True
        return any(token in name for token in rules.temporal_name_tokens)

    def _is_meaningful_enum_column(
        self,
        column_name: str,
        technical_type: str,
        enum_values: list[str],
        sample_values: list[str],
        *,
        lookup_tables: list[str] | None = None,
        is_foreign_key: bool = False,
    ) -> bool:
        name = str(column_name or "").strip().lower()
        lookup_backed = bool(lookup_tables)
        if self._is_low_signal_column(name) and not (
            self._has_enum_signal(name) or lookup_backed or is_declared_enum_type(technical_type)
        ):
            return False
        return is_enum_candidate(
            column_name=column_name,
            technical_type=technical_type,
            values=enum_values or sample_values,
            extra_name_tokens=self.rules.gap_detection.enum_name_tokens,
            is_foreign_key=is_foreign_key,
            lookup_backed=lookup_backed,
        )

    def _has_enum_signal(self, column_name: str) -> bool:
        name = str(column_name or "").strip().lower()
        if not name:
            return False
        return has_business_enum_signal(name, self.rules.gap_detection.enum_name_tokens)

    def _enum_lookup_tables(
        self,
        table: NormalizedTable,
        column_name: str,
        table_map: dict[str, NormalizedTable],
    ) -> list[str]:
        target = str(column_name or "").strip()
        if not target:
            return []
        matches: list[str] = []
        prefix = f"{table.table_name}.{target}="
        for join in table.join_candidates:
            if not join.startswith(prefix):
                continue
            try:
                _left, right = join.split("=", 1)
            except ValueError:
                continue
            candidate_table = right.split(".")[0].strip()
            if not candidate_table or candidate_table in matches:
                continue
            if candidate_table in table_map and self._is_lookup_like_table(table_map[candidate_table]):
                matches.append(candidate_table)
        return matches[:3]

    def _is_lookup_like_table(self, table: NormalizedTable) -> bool:
        name = str(table.table_name or "").strip().lower()
        if not name:
            return False
        if name.endswith("_master"):
            return True
        if any(token in name for token in ("status", "state", "type", "category", "reason", "mode", "priority")):
            return True
        non_id_columns = [column for column in table.columns if column.column_name.lower() != "id"]
        return len(non_id_columns) <= 6 and any(column.sample_values or column.enum_values for column in non_id_columns)

    def _lookup_label_candidates(
        self,
        table_map: dict[str, NormalizedTable],
        lookup_tables: list[str],
        observed_values: list[str],
    ) -> list[str]:
        label_values: list[str] = []
        observed_count = len(observed_values)
        for table_name in lookup_tables:
            table = table_map.get(table_name)
            if table is None:
                continue
            candidates = self._lookup_table_label_samples(table)
            if observed_count and candidates and len(candidates) < min(observed_count, 2):
                continue
            for value in candidates:
                if value not in label_values:
                    label_values.append(value)
        return label_values[:8]

    def _lookup_table_label_samples(self, table: NormalizedTable) -> list[str]:
        preferred_columns = (
            "display_name",
            "display_type",
            "label",
            "name",
            "title",
            "type",
            "status",
            "state",
            "category",
            "reason",
            "mode",
            "code",
        )
        ordered_columns: list[NormalizedColumn] = []
        by_name = {column.column_name.lower(): column for column in table.columns}
        for candidate in preferred_columns:
            column = by_name.get(candidate)
            if column is not None and column not in ordered_columns:
                ordered_columns.append(column)
        for column in table.columns:
            if column in ordered_columns:
                continue
            if column.is_primary_key or column.is_identifier_like:
                continue
            technical_type = str(column.technical_type or "").lower()
            if any(token in technical_type for token in ("char", "text")):
                ordered_columns.append(column)

        values: list[str] = []
        for column in ordered_columns:
            for raw_value in list(column.enum_values or []) + list(column.sample_values or []):
                value = str(raw_value or "").strip()
                if not value or re.fullmatch(r"[0-9]+", value):
                    continue
                if value not in values:
                    values.append(value)
            if values:
                break
        return values[:8]

    def _enum_pattern_already_confirmed(self, existing: object, column_name: str) -> bool:
        if existing is None:
            return False
        for column in getattr(existing, "columns", []):
            if column.column_name != column_name:
                continue
            if (
                getattr(getattr(column, "attribution", None), "source", None) == DiscoverySource.CONFIRMED_BY_USER
                and str(getattr(column, "business_meaning", "") or "").strip()
            ):
                return True
        return False

    def _group_join_candidates(self, joins: list[str]) -> dict[str, list[str]]:
        grouped: dict[str, list[str]] = {}
        for join in joins:
            try:
                left, _right = join.split("=")
            except ValueError:
                continue
            parts = left.split(".")
            if len(parts) != 2:
                continue
            grouped.setdefault(parts[1].strip(), []).append(join)
        return grouped

    def _rank_relationship_candidates(self, column_name: str, joins: list[str]) -> list[tuple[str, int, str]]:
        base = str(column_name or "").strip().lower()
        if base.endswith("_id"):
            base = base[:-3]
        base_tokens = [token for token in base.split("_") if token and token not in {"id"}]

        ranked: list[tuple[str, int, str]] = []
        seen_tables: set[str] = set()
        for join in joins:
            try:
                _left, right = join.split("=")
            except ValueError:
                continue
            right_table = right.split(".")[0].strip()
            if not right_table or right_table in seen_tables:
                continue
            seen_tables.add(right_table)
            table_tokens = [token for token in right_table.lower().split("_") if token]
            score = 0
            if right_table.lower() == base:
                score += 4
            if base and base in right_table.lower():
                score += 2
            score += sum(1 for token in base_tokens if token in table_tokens)
            ranked.append((right_table, score, join))

        ranked.sort(key=lambda item: (-item[1], item[0]))
        if any(score > 0 for _table, score, _join in ranked):
            ranked = [item for item in ranked if item[1] > 0]
        return ranked

    def _relationship_neighbors(self, joins: list[str], table_name: str) -> list[str]:
        neighbors: list[str] = []
        for join in joins:
            try:
                left, right = join.split("=")
            except ValueError:
                continue
            left_table = left.split(".")[0].strip()
            right_table = right.split(".")[0].strip()
            for related in (left_table, right_table):
                if not related or related == table_name or related in neighbors:
                    continue
                neighbors.append(related)
        return neighbors[:6]

    def _table_impact_score(self, table: NormalizedTable) -> float:
        row_count = table.row_count or 0
        join_count = len(table.join_candidates)
        business_columns = len(self._important_columns(table))
        status_count = sum(1 for column in table.columns if column.is_status_like)
        return self._score(
            min(
                1.0,
                0.14
                + min(join_count * 0.08, 0.28)
                + min(business_columns * 0.04, 0.2)
                + (0.14 if row_count >= 10_000 else 0.1 if row_count >= 1_000 else 0.06 if row_count >= 100 else 0.0)
                + (0.08 if status_count else 0.0),
            )
        )

    def _table_business_relevance(self, table: NormalizedTable, existing: object) -> float:
        name = table.table_name.lower()
        score = 0.5
        if existing is not None and getattr(existing, "selected", True):
            score += 0.12
        if table.join_candidates:
            score += 0.1
        if table.entity_hint:
            score += 0.08
        if any(token in name for token in ("transaction", "trip", "task", "dispatch", "order", "shipment", "inspection", "location", "fence")):
            score += 0.12
        if any(token in name for token in ("log", "audit", "history", "setting", "config", "temp", "cache")):
            score -= 0.2
        return self._score(score)

    def _table_naming_strength(self, table: NormalizedTable, existing: object) -> float:
        name = table.table_name.lower()
        score = 0.35
        if table.entity_hint:
            score += 0.16
        if existing is not None and getattr(existing, "confidence", None):
            score += min(getattr(existing.confidence, "score", 0.0), 0.3)
        if any(token in name for token in ("mapping", "history", "log", "detail", "config", "setting", "template", "master")):
            score += 0.16
        if {"location", "fence"} <= set(name.split("_")):
            score += 0.18
        geo_columns = {column.column_name.lower() for column in table.columns}
        if {"latitude", "longitude"} <= geo_columns or "perimeter" in geo_columns:
            score += 0.16
        return self._score(score)

    def _table_best_guess(self, table: NormalizedTable, existing: object) -> str:
        name = table.table_name.lower()
        columns = {column.column_name.lower() for column in table.columns}
        if {"location", "fence"} <= set(name.split("_")) or (
            "location" in name and ("fence" in name or {"latitude", "longitude"} <= columns or "perimeter" in columns)
        ):
            return "Geofence or area boundary around a location."
        if any(name.endswith(suffix) for suffix in self.rules.table_meaning.mapping_suffixes):
            return f"Relationship mapping between {snake_to_words(name)} entities."
        if any(name.endswith(suffix) for suffix in self.rules.table_meaning.history_suffixes):
            return f"History or event records for {snake_to_words(name)}."
        if any(name.endswith(suffix) for suffix in self.rules.table_meaning.detail_suffixes):
            return f"Detail rows attached to {snake_to_words(name)}."
        if any(token in name for token in ("config", "setting", "template", "master")):
            return f"Configuration or reference records for {snake_to_words(name)}."
        existing_meaning = str(getattr(existing, "business_meaning", "") or "").strip()
        if existing_meaning and not self._looks_generic_meaning(existing_meaning):
            return existing_meaning
        if table.entity_hint:
            return f"{table.entity_hint} records."
        if existing_meaning:
            return existing_meaning
        return f"Operational records for {snake_to_words(table.table_name)}."

    def _table_candidate_options(
        self,
        table: NormalizedTable,
        existing: object,
        best_guess: str,
    ) -> list[QuestionOption]:
        name = table.table_name.lower()
        options: list[QuestionOption] = [
            self._option(best_guess, best_guess, "Current system best guess.", is_best_guess=True)
        ]
        heuristics = [
            (
                "Operational workflow or transaction records.",
                "The table stores one business event or workflow item per row.",
            ),
            (
                "Configuration or reference setup records.",
                "The table defines setup values, templates, or defaults.",
            ),
            (
                "Relationship mapping between entities.",
                "The table mainly links two or more business objects.",
            ),
            (
                "History or audit trail records.",
                "The table stores changes, logs, or historical snapshots.",
            ),
        ]
        if "location" in name and ("fence" in name or "perimeter" in name):
            heuristics.insert(
                1,
                (
                    "Geofence or area boundary around a location.",
                    "Rows define bounded geographic areas tied to a location.",
                ),
            )
        entity_hint = getattr(existing, "likely_entity", None) or table.entity_hint
        if entity_hint:
            heuristics.insert(1, (f"{entity_hint} records.", "Use the inferred entity label as-is."))

        seen: set[str] = {best_guess.lower()}
        for label, description in heuristics:
            lowered = label.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            options.append(self._option(label, label, description))
            if len(options) >= 4:
                break
        options.append(
            self._option(
                "__other__",
                "Something else",
                "None of these interpretations matches the real business meaning.",
                is_fallback=True,
            )
        )
        return options

    def _table_evidence(self, table: NormalizedTable, existing: object) -> list[str]:
        evidence = [
            f"name tokens: {', '.join(part for part in table.table_name.split('_') if part) or table.table_name}",
            f"important columns: {', '.join(self._important_columns(table)[:5])}" if self._important_columns(table) else "",
            f"grain hint: {table.grain_hint}" if table.grain_hint else "",
            f"related tables: {', '.join(self._relationship_neighbors(table.join_candidates, table.table_name)[:4])}"
            if table.join_candidates
            else "",
        ]
        if existing is not None and getattr(existing, "confidence", None):
            evidence.append(
                f"inference confidence: {round(getattr(existing.confidence, 'score', 0.0), 2)}"
            )
            rationale = [str(item).strip() for item in getattr(existing.confidence, "rationale", []) if str(item).strip()]
            if rationale:
                evidence.append(f"inference signals: {', '.join(rationale[:2])}")
        return unique_non_empty(evidence)[:5]

    def _enum_guess_and_options(
        self,
        column_name: str,
        values: list[str],
        *,
        lookup_tables: list[str] | None = None,
        lookup_labels: list[str] | None = None,
    ) -> tuple[str, list[QuestionOption]]:
        name = column_name.lower()
        all_numeric = all(re.fullmatch(r"[0-9]+", value) for value in values)
        lookup_tables = list(lookup_tables or [])
        lookup_labels = list(lookup_labels or [])
        if any(token in name for token in ("priority", "severity", "criticality")):
            best_guess = "Priority or severity level."
        elif any(token in name for token in ("type", "category", "reason", "class")):
            best_guess = "Type or category classification."
        elif name.startswith(self.rules.gap_detection.boolean_prefixes) or set(v.lower() for v in values) <= {"0", "1", "y", "n", "yes", "no", "true", "false"}:
            best_guess = "Boolean or enable/disable flag."
        elif any(token in name for token in ("status", "state", "phase", "stage")):
            best_guess = "Workflow or lifecycle status."
        elif lookup_tables:
            best_guess = f"Reference-data driven code from {lookup_tables[0]}."
        elif all_numeric:
            best_guess = "Workflow or lifecycle status code."
        else:
            best_guess = "Type or status code used in business workflows."

        status_description = "Treat values like business states."
        default_labels = self._default_enum_labels(
            values,
            column_name=column_name,
            lookup_labels=lookup_labels,
        )
        if default_labels:
            status_description = f"{status_description} Likely labels: {', '.join(default_labels[:4])}"
        elif lookup_tables:
            status_description = f"{status_description} Validate against related lookup table(s): {', '.join(lookup_tables[:2])}."
        elif all_numeric:
            status_description = f"{status_description} Exact labels are still unknown for raw codes: {', '.join(values[:4])}."

        options = [
            self._option(
                "status_pattern",
                "Workflow or lifecycle status",
                status_description,
                is_best_guess="status" in best_guess.lower() or "workflow" in best_guess.lower(),
            ),
            self._option(
                "priority_pattern",
                "Priority or severity",
                "Treat values as urgency or severity levels.",
                is_best_guess="priority" in best_guess.lower() or "severity" in best_guess.lower(),
            ),
            self._option(
                "type_pattern",
                "Type or category",
                "Treat values as classifications or categories.",
                is_best_guess="type" in best_guess.lower() or "category" in best_guess.lower(),
            ),
            self._option(
                "flag_pattern",
                "Boolean or active flag",
                "Treat values as yes/no, enabled/disabled, or active/inactive.",
                is_best_guess="flag" in best_guess.lower() or "boolean" in best_guess.lower(),
            ),
            self._option(
                "__other__",
                "Something else",
                "The column has a different business meaning.",
                is_fallback=True,
            ),
        ]
        if not any(option.is_best_guess for option in options):
            options[0].is_best_guess = True
        return best_guess, options

    def _default_enum_labels(
        self,
        values: list[str],
        *,
        column_name: str | None = None,
        lookup_labels: list[str] | None = None,
    ) -> list[str]:
        if lookup_labels:
            return unique_non_empty(lookup_labels)[:8]

        labels: list[str] = []
        name = str(column_name or "").strip().lower()
        for value in values:
            cleaned = str(value).strip()
            if not cleaned:
                continue
            if re.fullmatch(r"[0-9]+", cleaned):
                if name.startswith(self.rules.gap_detection.boolean_prefixes):
                    labels.extend(["No", "Yes"])
                continue
            else:
                labels.append(cleaned.replace("_", " ").title())
        return unique_non_empty(labels)[:8]

    def _enum_name_signal(self, column_name: str) -> str:
        lowered = column_name.lower()
        if any(token in lowered for token in ("status", "state", "phase", "stage")):
            return "workflow state"
        if any(token in lowered for token in ("priority", "severity")):
            return "priority"
        if any(token in lowered for token in ("type", "category", "reason")):
            return "classification"
        return "compact coded attribute"

    def _enum_confidence(self, existing: object, column_name: str) -> float:
        if existing is None:
            return 0.42
        for column in getattr(existing, "columns", []):
            if column.column_name == column_name:
                return self._score(getattr(column.confidence, "score", 0.42))
        return 0.42

    def _enum_ambiguity(self, column_name: str, values: list[str]) -> float:
        lowered = column_name.lower()
        all_numeric = all(re.fullmatch(r"[0-9]+", value) for value in values)
        if all_numeric:
            return 0.92
        if any(len(value) <= 2 for value in values):
            return 0.82
        if any(token in lowered for token in ("status", "state", "phase", "stage")):
            return 0.36
        return 0.58

    def _column_rationale(self, existing: object, column_name: str) -> list[str]:
        if existing is None:
            return []
        for column in getattr(existing, "columns", []):
            if column.column_name != column_name:
                continue
            confidence = getattr(column, "confidence", None)
            if confidence is None:
                return []
            return [str(item).strip() for item in getattr(confidence, "rationale", []) if str(item).strip()][:2]
        return []

    def _is_skipped_table(self, existing: object) -> bool:
        if existing is None:
            return False
        if getattr(existing, "selected", True) is False:
            return True
        return getattr(existing, "review_status", None) == TableReviewStatus.skipped

    def _looks_generic_meaning(self, text: str) -> bool:
        cleaned = str(text or "").strip()
        if not cleaned:
            return True
        return cleaned.startswith(_GENERIC_MEANING_PREFIXES)

    def _priority_score(self, impact_score: float, ambiguity_score: float, business_relevance: float) -> float:
        return round(impact_score * ambiguity_score * business_relevance, 4)

    def _priority_bucket(self, priority_score: float) -> int:
        if priority_score >= 0.36:
            return 1
        if priority_score >= 0.2:
            return 2
        return 3

    def _pattern_covered_tables(self, state: KnowledgeState) -> set[str]:
        covered: set[str] = set()
        for group in state.domain_groups:
            if len(group.tables) >= 4 and not group.requires_review and group.confidence.score >= 0.72:
                covered.update(group.tables)

        grouped_by_role: dict[TableRole, list[str]] = defaultdict(list)
        for table in state.tables.values():
            grouped_by_role[table.role].append(table.table_name)
        for role, tables in grouped_by_role.items():
            if len(tables) < 2:
                continue
            members = [state.tables[name] for name in tables if name in state.tables]
            avg_confidence = sum(table.confidence.score for table in members) / max(len(members), 1)
            if role in {TableRole.lookup_master, TableRole.mapping_bridge} and avg_confidence >= 0.72:
                covered.update(tables)
            if role in {TableRole.log_event, TableRole.history_audit, TableRole.config_system} and avg_confidence >= 0.66:
                covered.update(tables)
        return covered

    def _default_actions(self) -> list[QuestionAction]:
        return [
            QuestionAction(value="confirm", label="Confirm"),
            QuestionAction(value="change", label="Change"),
            QuestionAction(value="skip", label="Skip"),
        ]

    def _option(
        self,
        value: str,
        label: str,
        description: str | None = None,
        *,
        is_best_guess: bool = False,
        is_fallback: bool = False,
    ) -> QuestionOption:
        return QuestionOption(
            value=value,
            label=label,
            description=description,
            is_best_guess=is_best_guess,
            is_fallback=is_fallback,
        )

    def _score(self, value: float) -> float:
        return round(min(max(value, 0.0), 1.0), 2)
