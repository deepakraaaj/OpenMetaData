"""Detect semantic gaps from normalized schema + current knowledge state."""
from __future__ import annotations

from app.models.normalized import NormalizedSource
from app.models.state import GapCategory, KnowledgeState, SemanticGap
from app.models.source_attribution import DiscoverySource


class GapDetector:
    """Scans normalized metadata and current state to find unresolved gaps."""

    def detect(self, normalized: NormalizedSource, state: KnowledgeState) -> list[SemanticGap]:
        gaps: list[SemanticGap] = []
        gaps.extend(self._missing_primary_keys(normalized, state))
        gaps.extend(self._unknown_business_meanings(normalized, state))
        gaps.extend(self._unconfirmed_enums(normalized, state))
        gaps.extend(self._ambiguous_relationships(normalized, state))
        gaps.extend(self._potential_sensitivity(normalized, state))
        gaps.extend(self._glossary_gaps(normalized, state))
        return gaps

    def _missing_primary_keys(
        self, normalized: NormalizedSource, state: KnowledgeState
    ) -> list[SemanticGap]:
        gaps: list[SemanticGap] = []
        for table in normalized.tables:
            if table.primary_key:
                continue
            # Check if user already confirmed a PK
            existing = state.tables.get(table.table_name)
            if existing and any("primary key" in (r or "").lower() for r in (existing.confidence.rationale or [])):
                continue
            gaps.append(
                SemanticGap(
                    gap_id=f"pk-{table.table_name}",
                    category=GapCategory.MISSING_PRIMARY_KEY,
                    target_entity=table.table_name,
                    description=f"No primary key defined for table '{table.table_name}'.",
                    suggested_question=f"Which column uniquely identifies each row in '{table.table_name}'?",
                    is_blocking=True,
                    priority=1,
                )
            )
        return gaps

    def _unknown_business_meanings(
        self, normalized: NormalizedSource, state: KnowledgeState
    ) -> list[SemanticGap]:
        gaps: list[SemanticGap] = []
        for table in normalized.tables:
            existing = state.tables.get(table.table_name)
            # Table-level meaning
            if existing and existing.attribution.source == DiscoverySource.CONFIRMED_BY_USER:
                continue
            if existing and existing.confidence.score >= 0.65:
                continue
            gaps.append(
                SemanticGap(
                    gap_id=f"meaning-{table.table_name}",
                    category=GapCategory.UNKNOWN_BUSINESS_MEANING,
                    target_entity=table.table_name,
                    description=f"Business meaning for table '{table.table_name}' is unconfirmed (confidence: {existing.confidence.score if existing else 'N/A'}).",
                    suggested_question=f"What does the table '{table.table_name}' represent in your business?",
                    is_blocking=False,
                    priority=2,
                )
            )
            # Column-level meanings (only low confidence ones)
            for col in table.columns:
                col_key = f"{table.table_name}.{col.column_name}"
                existing_col = None
                if existing:
                    existing_col = next((c for c in existing.columns if c.column_name == col.column_name), None)
                if existing_col and existing_col.attribution.source == DiscoverySource.CONFIRMED_BY_USER:
                    continue
                if existing_col and existing_col.confidence.score >= 0.65:
                    continue
                if col.is_primary_key or col.is_foreign_key:
                    continue  # These are usually self-explanatory
                gaps.append(
                    SemanticGap(
                        gap_id=f"col-meaning-{col_key}",
                        category=GapCategory.UNKNOWN_BUSINESS_MEANING,
                        target_entity=table.table_name,
                        target_property=col.column_name,
                        description=f"Business meaning for column '{col_key}' is unclear.",
                        suggested_question=f"What does '{col.column_name}' mean in the context of '{table.table_name}'?",
                        is_blocking=False,
                        priority=3,
                    )
                )
        return gaps

    def _unconfirmed_enums(
        self, normalized: NormalizedSource, state: KnowledgeState
    ) -> list[SemanticGap]:
        gaps: list[SemanticGap] = []
        for table in normalized.tables:
            for col in table.columns:
                if not col.is_status_like and not col.enum_values:
                    continue
                col_key = f"{table.table_name}.{col.column_name}"
                confirmed_enums = state.enums.get(col_key, [])
                if any(e.attribution.source == DiscoverySource.CONFIRMED_BY_USER for e in confirmed_enums):
                    continue
                sample_display = ", ".join(col.enum_values[:5] or col.sample_values[:5])
                gaps.append(
                    SemanticGap(
                        gap_id=f"enum-{col_key}",
                        category=GapCategory.UNCONFIRMED_ENUM_MAPPING,
                        target_entity=table.table_name,
                        target_property=col.column_name,
                        description=f"Status/enum column '{col_key}' has unconfirmed value mappings: [{sample_display}].",
                        suggested_question=f"What do the values [{sample_display}] mean for '{col.column_name}' in '{table.table_name}'?",
                        is_blocking=False,
                        priority=2,
                    )
                )
        return gaps

    def _ambiguous_relationships(
        self, normalized: NormalizedSource, state: KnowledgeState
    ) -> list[SemanticGap]:
        gaps: list[SemanticGap] = []
        for table in normalized.tables:
            for join in table.join_candidates[:3]:
                gap_id = f"rel-{table.table_name}-{join.replace('=', '_').replace('.', '_')}"
                # Check if already resolved
                already_resolved = any(g.gap_id == gap_id for g in state.unresolved_gaps if False)
                existing = state.tables.get(table.table_name)
                if existing and join in existing.valid_joins:
                    # Already in state — check if user confirmed
                    if existing.attribution.source == DiscoverySource.CONFIRMED_BY_USER:
                        continue
                gaps.append(
                    SemanticGap(
                        gap_id=gap_id,
                        category=GapCategory.AMBIGUOUS_RELATIONSHIP,
                        target_entity=table.table_name,
                        target_property=join,
                        description=f"Join '{join}' is inferred but not validated for business reporting.",
                        suggested_question=f"Is the relationship '{join}' valid for business queries?",
                        is_blocking=True,
                        priority=1,
                    )
                )
        return gaps

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
        return gaps

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
        return gaps
