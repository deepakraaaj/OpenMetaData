"""Interpret user answers and apply mutations to KnowledgeState."""
from __future__ import annotations

from datetime import datetime, timezone

from app.models.common import ConfidenceLabel, NamedConfidence, SensitivityLabel
from app.models.semantic import EnumMapping, GlossaryTerm
from app.models.source_attribution import DiscoverySource, SourceAttribution
from app.models.state import GapCategory, KnowledgeState, SemanticGap


def _user_attribution() -> SourceAttribution:
    return SourceAttribution(
        source=DiscoverySource.CONFIRMED_BY_USER,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


def _high_confidence() -> NamedConfidence:
    return NamedConfidence(
        label=ConfidenceLabel.high,
        score=0.95,
        rationale=["confirmed by user"],
    )


class AnswerInterpreter:
    """Translates user answers into concrete KnowledgeState mutations."""

    def apply(self, state: KnowledgeState, gap: SemanticGap, answer: str) -> KnowledgeState:
        handler = self._handlers.get(gap.category, self._apply_generic)
        handler(self, state, gap, answer)

        # Remove the resolved gap
        state.unresolved_gaps = [g for g in state.unresolved_gaps if g.gap_id != gap.gap_id]
        return state

    def _apply_business_meaning(self, state: KnowledgeState, gap: SemanticGap, answer: str) -> None:
        table = state.tables.get(gap.target_entity or "")
        if not table:
            return

        if gap.target_property:
            # Column-level meaning
            for col in table.columns:
                if col.column_name == gap.target_property:
                    col.business_meaning = answer
                    col.attribution = _user_attribution()
                    col.confidence = _high_confidence()
                    break
        else:
            # Table-level meaning
            table.business_meaning = answer
            table.attribution = _user_attribution()
            table.confidence = _high_confidence()

    def _apply_enum_mapping(self, state: KnowledgeState, gap: SemanticGap, answer: str) -> None:
        col_key = f"{gap.target_entity}.{gap.target_property}"
        # Parse answer like "0=Pending, 1=Active, 2=Closed"
        mappings: list[EnumMapping] = []
        for pair in answer.split(","):
            pair = pair.strip()
            if "=" in pair:
                db_val, label = pair.split("=", 1)
                mappings.append(
                    EnumMapping(
                        database_value=db_val.strip(),
                        business_label=label.strip(),
                        attribution=_user_attribution(),
                    )
                )
            elif pair:
                mappings.append(
                    EnumMapping(
                        database_value=pair,
                        business_label=pair,
                        attribution=_user_attribution(),
                    )
                )
        if mappings:
            state.enums[col_key] = mappings

    def _apply_primary_key(self, state: KnowledgeState, gap: SemanticGap, answer: str) -> None:
        table = state.tables.get(gap.target_entity or "")
        if not table:
            return
        pk_col = answer.strip()
        if pk_col not in table.important_columns:
            table.important_columns.insert(0, pk_col)
        table.attribution = _user_attribution()
        table.confidence = _high_confidence()

    def _apply_relationship(self, state: KnowledgeState, gap: SemanticGap, answer: str) -> None:
        table = state.tables.get(gap.target_entity or "")
        if not table:
            return
        normalized_answer = answer.strip()
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
                table.attribution = _user_attribution()
                return

        is_valid = choice_key in {"yes", "true", "yes, this is valid", "1"}
        if is_valid and gap.target_property and gap.target_property not in table.valid_joins:
            table.valid_joins.append(gap.target_property)
        elif gap.target_property and gap.target_property in table.valid_joins:
            table.valid_joins.remove(gap.target_property)
        table.attribution = _user_attribution()

    def _apply_sensitivity(self, state: KnowledgeState, gap: SemanticGap, answer: str) -> None:
        table = state.tables.get(gap.target_entity or "")
        if not table:
            return
        is_sensitive = answer.strip().lower() in {"yes", "true", "yes, mask this column", "1"}
        for col in table.columns:
            if col.column_name == gap.target_property:
                col.sensitive = SensitivityLabel.sensitive if is_sensitive else SensitivityLabel.none
                col.displayable = not is_sensitive
                col.attribution = _user_attribution()
                break

    def _apply_glossary(self, state: KnowledgeState, gap: SemanticGap, answer: str) -> None:
        entity = gap.target_entity or ""
        state.glossary[entity] = GlossaryTerm(
            term=answer.strip(),
            meaning=f"User-defined business term for {entity}.",
            related_tables=[entity],
            attribution=_user_attribution(),
        )

    def _apply_generic(self, state: KnowledgeState, gap: SemanticGap, answer: str) -> None:
        pass  # No-op for unknown gap types

    _handlers = {
        GapCategory.UNKNOWN_BUSINESS_MEANING: _apply_business_meaning,
        GapCategory.UNCONFIRMED_ENUM_MAPPING: _apply_enum_mapping,
        GapCategory.MISSING_PRIMARY_KEY: _apply_primary_key,
        GapCategory.AMBIGUOUS_RELATIONSHIP: _apply_relationship,
        GapCategory.RELATIONSHIP_ROLE_UNCLEAR: _apply_relationship,
        GapCategory.POTENTIAL_SENSITIVITY: _apply_sensitivity,
        GapCategory.GLOSSARY_TERM_MISSING: _apply_glossary,
    }
