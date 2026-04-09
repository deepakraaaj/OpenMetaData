"""Interpret user answers and apply mutations to KnowledgeState."""
from __future__ import annotations

from datetime import datetime, timezone
import re

from app.models.common import ConfidenceLabel, NamedConfidence, SensitivityLabel
from app.models.decision import DecisionActor
from app.models.semantic import EnumMapping, GlossaryTerm
from app.models.source_attribution import DiscoverySource, SourceAttribution
from app.models.state import GapCategory, KnowledgeState, SemanticGap

_CONFIRM_SENTINELS = {"confirm", "__confirm__"}
_SKIP_SENTINELS = {"skip", "__skip__"}


def _named_confidence(score: float, rationale: str) -> NamedConfidence:
    clamped = max(0.0, min(float(score), 1.0))
    if clamped >= 0.8:
        label = ConfidenceLabel.high
    elif clamped >= 0.55:
        label = ConfidenceLabel.medium
    else:
        label = ConfidenceLabel.low
    return NamedConfidence(label=label, score=clamped, rationale=[rationale])


def _attribution_for(actor: DecisionActor, reviewer: str | None = None) -> SourceAttribution:
    source = (
        DiscoverySource.CONFIRMED_BY_USER
        if actor in {DecisionActor.user_confirmed, DecisionActor.user_overridden}
        else DiscoverySource.INFERRED_BY_SYSTEM
    )
    return SourceAttribution(
        source=source,
        user=reviewer,
        timestamp=datetime.now(timezone.utc).isoformat(),
        tooling_notes=f"Applied via {actor.value}.",
    )


def _confidence_for(actor: DecisionActor, gap: SemanticGap) -> NamedConfidence:
    if actor in {DecisionActor.user_confirmed, DecisionActor.user_overridden}:
        return NamedConfidence(
            label=ConfidenceLabel.high,
            score=0.95,
            rationale=["confirmed by user"],
        )
    return _named_confidence(gap.confidence or 0.7, f"resolved by {actor.value}")


class AnswerInterpreter:
    """Translates user answers into concrete KnowledgeState mutations."""

    def apply(
        self,
        state: KnowledgeState,
        gap: SemanticGap,
        answer: str,
        *,
        actor: DecisionActor = DecisionActor.user_confirmed,
        reviewer: str | None = None,
        retain_gap: bool = False,
    ) -> KnowledgeState:
        normalized = str(answer or "").strip().lower()
        if normalized in _SKIP_SENTINELS:
            if not retain_gap:
                state.unresolved_gaps = [g for g in state.unresolved_gaps if g.gap_id != gap.gap_id]
            return state

        handler = self._handlers.get(gap.category, self._apply_generic)
        resolved_answer = self._resolve_answer(gap, answer)
        handler(self, state, gap, resolved_answer, actor=actor, reviewer=reviewer)

        # Remove the resolved gap
        if not retain_gap:
            state.unresolved_gaps = [g for g in state.unresolved_gaps if g.gap_id != gap.gap_id]
        return state

    def _apply_business_meaning(
        self,
        state: KnowledgeState,
        gap: SemanticGap,
        answer: str,
        *,
        actor: DecisionActor,
        reviewer: str | None,
    ) -> None:
        table = state.tables.get(gap.target_entity or "")
        if not table:
            return
        final_answer = str(gap.best_guess or answer).strip() if str(answer).strip().lower() in _CONFIRM_SENTINELS else str(answer).strip()
        if not final_answer:
            return

        if gap.target_property:
            # Column-level meaning
            for col in table.columns:
                if col.column_name == gap.target_property:
                    col.business_meaning = final_answer
                    col.attribution = _attribution_for(actor, reviewer)
                    col.confidence = _confidence_for(actor, gap)
                    break
        else:
            # Table-level meaning
            table.business_meaning = final_answer
            table.attribution = _attribution_for(actor, reviewer)
            table.confidence = _confidence_for(actor, gap)

    def _apply_enum_mapping(
        self,
        state: KnowledgeState,
        gap: SemanticGap,
        answer: str,
        *,
        actor: DecisionActor,
        reviewer: str | None,
    ) -> None:
        col_key = f"{gap.target_entity}.{gap.target_property}"
        mappings: list[EnumMapping] = []
        normalized = str(answer).strip().lower()
        observed_values = [str(value).strip() for value in gap.metadata.get("observed_values", []) if str(value).strip()]
        auto_labels = [str(value).strip() for value in gap.metadata.get("auto_labels", []) if str(value).strip()]
        pattern_choice = normalized in _CONFIRM_SENTINELS or normalized in {
            "status_pattern",
            "priority_pattern",
            "type_pattern",
            "flag_pattern",
        }

        if pattern_choice:
            self._apply_enum_pattern_meaning(
                state,
                gap,
                normalized,
                actor=actor,
                reviewer=reviewer,
            )
            labels = auto_labels or [value.replace("_", " ").title() for value in observed_values]
            if self._labels_are_meaningful(observed_values, labels):
                for index, value in enumerate(observed_values):
                    label = labels[index] if index < len(labels) else value
                    mappings.append(
                        EnumMapping(
                            database_value=value,
                            business_label=label,
                            attribution=_attribution_for(actor, reviewer),
                        )
                    )
            if mappings:
                state.enums[col_key] = mappings
            return

        # Parse answer like "0=Pending, 1=Active, 2=Closed"
        for pair in str(answer).split(","):
            pair = pair.strip()
            if "=" in pair:
                db_val, label = pair.split("=", 1)
                mappings.append(
                    EnumMapping(
                        database_value=db_val.strip(),
                        business_label=label.strip(),
                        attribution=_attribution_for(actor, reviewer),
                    )
                )
            elif pair:
                mappings.append(
                    EnumMapping(
                        database_value=pair,
                        business_label=pair,
                        attribution=_attribution_for(actor, reviewer),
                    )
                )
        if mappings:
            state.enums[col_key] = mappings

    def _apply_enum_pattern_meaning(
        self,
        state: KnowledgeState,
        gap: SemanticGap,
        normalized_answer: str,
        *,
        actor: DecisionActor,
        reviewer: str | None,
    ) -> None:
        table = state.tables.get(gap.target_entity or "")
        if not table or not gap.target_property:
            return

        choice = normalized_answer if normalized_answer not in _CONFIRM_SENTINELS else str(gap.best_guess or "").strip().lower()
        meaning = ""
        if choice in {"status_pattern"} or "workflow" in choice or "status" in choice:
            meaning = "Lifecycle or workflow status for the record."
        elif choice == "priority_pattern" or "priority" in choice or "severity" in choice:
            meaning = "Priority or severity level for the record."
        elif choice == "type_pattern" or "type" in choice or "category" in choice:
            meaning = "Classification or category for the record."
        elif choice == "flag_pattern" or "flag" in choice or "boolean" in choice:
            meaning = "Boolean or enable/disable flag for the record."
        if not meaning:
            return

        for col in table.columns:
            if col.column_name != gap.target_property:
                continue
            col.business_meaning = meaning
            col.attribution = _attribution_for(actor, reviewer)
            col.confidence = _confidence_for(actor, gap)
            break

    def _labels_are_meaningful(self, observed_values: list[str], labels: list[str]) -> bool:
        if not observed_values or not labels:
            return False
        for index, raw_value in enumerate(observed_values):
            label = labels[index] if index < len(labels) else raw_value
            if not str(label).strip():
                continue
            if self._normalized_token(raw_value) != self._normalized_token(label):
                return True
            if raw_value.strip() != label.strip():
                return True
        return False

    @staticmethod
    def _normalized_token(value: str) -> str:
        return re.sub(r"[^a-z0-9]", "", str(value or "").strip().lower())

    def _apply_primary_key(
        self,
        state: KnowledgeState,
        gap: SemanticGap,
        answer: str,
        *,
        actor: DecisionActor,
        reviewer: str | None,
    ) -> None:
        table = state.tables.get(gap.target_entity or "")
        if not table:
            return
        pk_col = answer.strip()
        if pk_col.lower() in _CONFIRM_SENTINELS and gap.best_guess:
            pk_col = str(gap.best_guess).strip()
        if pk_col not in table.important_columns:
            table.important_columns.insert(0, pk_col)
        table.attribution = _attribution_for(actor, reviewer)
        table.confidence = _confidence_for(actor, gap)

    def _apply_relationship(
        self,
        state: KnowledgeState,
        gap: SemanticGap,
        answer: str,
        *,
        actor: DecisionActor,
        reviewer: str | None,
    ) -> None:
        table = state.tables.get(gap.target_entity or "")
        if not table:
            return
        normalized_answer = answer.strip()
        if normalized_answer.lower() in _CONFIRM_SENTINELS and gap.best_guess:
            normalized_answer = str(gap.best_guess).strip()
        choice_key = normalized_answer.lower()
        candidate_joins = gap.metadata.get("candidate_joins") if isinstance(gap.metadata, dict) else None
        if isinstance(candidate_joins, dict) and candidate_joins:
            selected_join = None
            for table_name, join in candidate_joins.items():
                if str(table_name).strip().lower() == choice_key:
                    selected_join = str(join)
                    break
            for join in candidate_joins.values():
                join_value = str(join)
                if join_value in table.valid_joins:
                    table.valid_joins.remove(join_value)
            if selected_join:
                table.valid_joins.append(selected_join)
                table.attribution = _attribution_for(actor, reviewer)
                return

        is_valid = choice_key in {"yes", "true", "yes, this is valid", "1"}
        if is_valid and gap.target_property and gap.target_property not in table.valid_joins:
            table.valid_joins.append(gap.target_property)
        elif gap.target_property and gap.target_property in table.valid_joins:
            table.valid_joins.remove(gap.target_property)
        table.attribution = _attribution_for(actor, reviewer)

    def _apply_sensitivity(
        self,
        state: KnowledgeState,
        gap: SemanticGap,
        answer: str,
        *,
        actor: DecisionActor,
        reviewer: str | None,
    ) -> None:
        table = state.tables.get(gap.target_entity or "")
        if not table:
            return
        normalized = answer.strip().lower()
        if normalized in _CONFIRM_SENTINELS:
            normalized = str(gap.best_guess or "mask").strip().lower()
        is_sensitive = normalized in {
            "yes",
            "true",
            "yes, mask this column",
            "1",
            "mask",
            "mask this column",
        }
        for col in table.columns:
            if col.column_name == gap.target_property:
                col.sensitive = SensitivityLabel.sensitive if is_sensitive else SensitivityLabel.none
                col.displayable = not is_sensitive
                col.attribution = _attribution_for(actor, reviewer)
                col.confidence = _confidence_for(actor, gap)
                break

    def _apply_glossary(
        self,
        state: KnowledgeState,
        gap: SemanticGap,
        answer: str,
        *,
        actor: DecisionActor,
        reviewer: str | None,
    ) -> None:
        entity = gap.target_entity or ""
        final_answer = str(gap.best_guess or answer).strip() if str(answer).strip().lower() in _CONFIRM_SENTINELS else answer.strip()
        if not final_answer:
            return
        state.glossary[entity] = GlossaryTerm(
            term=final_answer,
            meaning=f"User-defined business term for {entity}.",
            related_tables=[entity],
            attribution=_attribution_for(actor, reviewer),
        )

    def _apply_generic(
        self,
        state: KnowledgeState,
        gap: SemanticGap,
        answer: str,
        *,
        actor: DecisionActor,
        reviewer: str | None,
    ) -> None:
        del state
        del gap
        del answer
        del actor
        del reviewer
        pass  # No-op for unknown gap types

    def _resolve_answer(self, gap: SemanticGap, answer: str) -> str:
        raw = str(answer or "").strip()
        lowered = raw.lower()
        if lowered in _CONFIRM_SENTINELS or lowered in _SKIP_SENTINELS:
            return raw
        for option in gap.candidate_options:
            option_value = str(option.value or "").strip()
            option_label = str(option.label or "").strip()
            if lowered == option_value.lower() or lowered == option_label.lower():
                return option_value or option_label
        return raw

    _handlers = {
        GapCategory.UNKNOWN_BUSINESS_MEANING: _apply_business_meaning,
        GapCategory.UNCONFIRMED_ENUM_MAPPING: _apply_enum_mapping,
        GapCategory.MISSING_PRIMARY_KEY: _apply_primary_key,
        GapCategory.AMBIGUOUS_RELATIONSHIP: _apply_relationship,
        GapCategory.RELATIONSHIP_ROLE_UNCLEAR: _apply_relationship,
        GapCategory.POTENTIAL_SENSITIVITY: _apply_sensitivity,
        GapCategory.GLOSSARY_TERM_MISSING: _apply_glossary,
    }
