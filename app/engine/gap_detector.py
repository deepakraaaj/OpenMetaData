"""Detect semantic gaps from normalized schema + current knowledge state.

Tuned for real-world schemas: focuses on HIGH-VALUE gaps only.
Column-level meaning gaps are skipped — they produce too much noise on
large schemas (80+ tables). Instead, we ask about tables holistically.
"""
from __future__ import annotations

import re

from app.core.inference_rules import SemanticInferenceRules, load_inference_rules
from app.models.normalized import NormalizedSource
from app.models.state import GapCategory, KnowledgeState, SemanticGap
from app.models.source_attribution import DiscoverySource


# Maximum gaps per category to prevent overwhelming the user
MAX_GAPS_PER_CATEGORY = 25


class GapDetector:
    """Scans normalized metadata and current state to find unresolved gaps."""

    def __init__(self, rules: SemanticInferenceRules | None = None) -> None:
        self.rules = rules or load_inference_rules()

    def detect(self, normalized: NormalizedSource, state: KnowledgeState) -> list[SemanticGap]:
        gaps: list[SemanticGap] = []
        gaps.extend(self._unknown_table_meanings(normalized, state))
        gaps.extend(self._unconfirmed_enums(normalized, state))
        gaps.extend(self._ambiguous_relationships(normalized, state))
        # These are lower-priority — only add if total is manageable
        if len(gaps) < 100:
            gaps.extend(self._potential_sensitivity(normalized, state))
            gaps.extend(self._glossary_gaps(normalized, state))
        return gaps

    def _unknown_table_meanings(
        self, normalized: NormalizedSource, state: KnowledgeState
    ) -> list[SemanticGap]:
        """Only flag TABLE-level meanings that are low confidence.
        Skip column-level — too noisy on real schemas."""
        gaps: list[SemanticGap] = []
        for table in normalized.tables:
            existing = state.tables.get(table.table_name)
            if existing and existing.attribution.source == DiscoverySource.CONFIRMED_BY_USER:
                continue
            if existing and existing.confidence.score >= 0.65:
                continue
            neighbors = self._relationship_neighbors(table.join_candidates)
            important_columns = [
                column.column_name
                for column in table.columns
                if not self._is_low_signal_column(column.column_name)
            ][:5]
            gaps.append(
                SemanticGap(
                    gap_id=f"meaning-{table.table_name}",
                    category=GapCategory.UNKNOWN_BUSINESS_MEANING,
                    target_entity=table.table_name,
                    description=f"Business meaning for table '{table.table_name}' is unconfirmed (confidence: {existing.confidence.score if existing else 'N/A'}).",
                    suggested_question=f"In business terms, what real-world workflow or entity does '{table.table_name}' represent?",
                    metadata={
                        "grain_hint": table.grain_hint or "",
                        "entity_hint": table.entity_hint or "",
                        "neighbor_tables": neighbors,
                        "important_columns": important_columns,
                    },
                    is_blocking=False,
                    priority=1,
                )
            )
        gaps.sort(
            key=lambda gap: (
                -len(gap.metadata.get("neighbor_tables", [])),
                -len(gap.metadata.get("important_columns", [])),
                str(gap.target_entity or ""),
            )
        )
        return gaps[:MAX_GAPS_PER_CATEGORY]

    def _unconfirmed_enums(
        self, normalized: NormalizedSource, state: KnowledgeState
    ) -> list[SemanticGap]:
        gaps: list[SemanticGap] = []
        for table in normalized.tables:
            for col in table.columns:
                if not self._is_meaningful_enum_column(col.column_name, col.enum_values, col.sample_values):
                    continue
                if col.is_foreign_key or col.is_primary_key or col.is_identifier_like:
                    continue
                col_key = f"{table.table_name}.{col.column_name}"
                confirmed_enums = state.enums.get(col_key, [])
                if any(e.attribution.source == DiscoverySource.CONFIRMED_BY_USER for e in confirmed_enums):
                    continue
                values = self._meaningful_distinct_values(col.enum_values or col.sample_values)
                sample_display = ", ".join(values[:5])
                if not sample_display:
                    continue
                gaps.append(
                    SemanticGap(
                        gap_id=f"enum-{col_key}",
                        category=GapCategory.UNCONFIRMED_ENUM_MAPPING,
                        target_entity=table.table_name,
                        target_property=col.column_name,
                        description=f"Status/enum column '{col_key}' has unconfirmed value mappings: [{sample_display}].",
                        suggested_question=f"For '{table.table_name}.{col.column_name}', how should the assistant interpret each allowed value in business terms?",
                        metadata={
                            "observed_values": values[:8],
                            "table_entity_hint": table.entity_hint or "",
                        },
                        is_blocking=False,
                        priority=3,
                    )
                )
        return gaps[:MAX_GAPS_PER_CATEGORY]

    def _ambiguous_relationships(
        self, normalized: NormalizedSource, state: KnowledgeState
    ) -> list[SemanticGap]:
        """Ask disambiguation questions only when one left-column maps to a few plausible targets."""
        gaps: list[SemanticGap] = []
        for table in normalized.tables:
            if not table.join_candidates:
                continue
            existing = state.tables.get(table.table_name)
            if existing and existing.attribution.source == DiscoverySource.CONFIRMED_BY_USER:
                continue
            for column_name, candidates in self._group_join_candidates(table.join_candidates).items():
                if self._is_relationship_noise_column(column_name):
                    continue
                ranked = self._rank_relationship_candidates(column_name, candidates)
                if len(ranked) < 2 or len(ranked) > 5:
                    continue
                if ranked[0][1] >= 3 and len(ranked) > 1 and ranked[0][1] > ranked[1][1]:
                    continue
                candidate_tables = [table_name for table_name, _score, _join in ranked]
                candidate_joins = {table_name: join for table_name, _score, join in ranked}
                gaps.append(
                    SemanticGap(
                        gap_id=f"rel-{table.table_name}-{column_name}",
                        category=GapCategory.AMBIGUOUS_RELATIONSHIP,
                        target_entity=table.table_name,
                        target_property=column_name,
                        description=f"Column '{table.table_name}.{column_name}' may reference one of: {', '.join(candidate_tables)}.",
                        suggested_question=f"Which entity does '{table.table_name}.{column_name}' actually point to in business use?",
                        metadata={
                            "candidate_tables": candidate_tables,
                            "candidate_joins": candidate_joins,
                        },
                        is_blocking=False,
                        priority=2,
                    )
                )
        return gaps[:MAX_GAPS_PER_CATEGORY]

    def _potential_sensitivity(
        self, normalized: NormalizedSource, state: KnowledgeState
    ) -> list[SemanticGap]:
        gaps: list[SemanticGap] = []
        for table in normalized.tables:
            for col in table.columns:
                if not col.sensitivity_hints:
                    continue
                col_key = f"{table.table_name}.{col.column_name}"
                existing = state.tables.get(table.table_name)
                if existing:
                    existing_col = next((c for c in existing.columns if c.column_name == col.column_name), None)
                    if existing_col and existing_col.attribution.source == DiscoverySource.CONFIRMED_BY_USER:
                        continue
                gaps.append(
                    SemanticGap(
                        gap_id=f"sensitivity-{col_key}",
                        category=GapCategory.POTENTIAL_SENSITIVITY,
                        target_entity=table.table_name,
                        target_property=col.column_name,
                        description=f"Column '{col_key}' may contain sensitive data: {', '.join(col.sensitivity_hints)}.",
                        suggested_question=f"Should '{col.column_name}' be treated as sensitive and masked in reports?",
                        is_blocking=False,
                        priority=3,
                    )
                )
        return gaps[:MAX_GAPS_PER_CATEGORY]

    def _relationship_neighbors(self, joins: list[str]) -> list[str]:
        neighbors: list[str] = []
        for join in joins:
            try:
                left, right = join.split("=")
            except ValueError:
                continue
            left_table = left.split(".")[0].strip()
            right_table = right.split(".")[0].strip()
            for table_name in (left_table, right_table):
                if table_name and table_name not in neighbors:
                    neighbors.append(table_name)
        return neighbors[:6]

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
        enum_values: list[str],
        sample_values: list[str],
    ) -> bool:
        name = str(column_name or "").strip().lower()
        if self._is_low_signal_column(name):
            return False
        if name == "id":
            return False

        values = self._meaningful_distinct_values(enum_values or sample_values)
        if len(values) < 2 or len(values) > 8:
            return False

        if all(re.fullmatch(r"[0-9]+", value) for value in values):
            return False

        if any(len(value) > 32 for value in values):
            return False

        boolean_prefixes = self.rules.gap_detection.boolean_prefixes
        has_boolean_prefix = bool(boolean_prefixes) and name.startswith(boolean_prefixes)
        return any(token in name for token in self.rules.gap_detection.enum_name_tokens) or has_boolean_prefix

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

    def _glossary_gaps(
        self, normalized: NormalizedSource, state: KnowledgeState
    ) -> list[SemanticGap]:
        gaps: list[SemanticGap] = []
        for table in normalized.tables:
            entity = table.entity_hint or table.table_name
            if entity.lower() in {k.lower() for k in state.glossary}:
                continue
            gaps.append(
                SemanticGap(
                    gap_id=f"glossary-{table.table_name}",
                    category=GapCategory.GLOSSARY_TERM_MISSING,
                    target_entity=table.table_name,
                    description=f"No glossary entry for entity '{entity}' (table: {table.table_name}).",
                    suggested_question=f"What business term do your users use to refer to '{entity}'?",
                    is_blocking=False,
                    priority=3,
                )
            )
        return gaps[:MAX_GAPS_PER_CATEGORY]
