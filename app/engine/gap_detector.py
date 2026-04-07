"""Detect semantic gaps from normalized schema + current knowledge state.

Tuned for real-world schemas: focuses on HIGH-VALUE gaps only.
Column-level meaning gaps are skipped — they produce too much noise on
large schemas (80+ tables). Instead, we ask about tables holistically.
"""
from __future__ import annotations

from app.models.normalized import NormalizedSource
from app.models.state import GapCategory, KnowledgeState, SemanticGap
from app.models.source_attribution import DiscoverySource


# Maximum gaps per category to prevent overwhelming the user
MAX_GAPS_PER_CATEGORY = 25


class GapDetector:
    """Scans normalized metadata and current state to find unresolved gaps."""

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
        return gaps[:MAX_GAPS_PER_CATEGORY]

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
                if not sample_display:
                    continue  # No values to show, skip
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
        return gaps[:MAX_GAPS_PER_CATEGORY]

    def _ambiguous_relationships(
        self, normalized: NormalizedSource, state: KnowledgeState
    ) -> list[SemanticGap]:
        """Only flag the FIRST candidate join per table to avoid explosion."""
        gaps: list[SemanticGap] = []
        for table in normalized.tables:
            if not table.join_candidates:
                continue
            # Only check the first join candidate — not all 3
            join = table.join_candidates[0]
            gap_id = f"rel-{table.table_name}-{join.replace('=', '_').replace('.', '_')}"
            existing = state.tables.get(table.table_name)
            if existing and existing.attribution.source == DiscoverySource.CONFIRMED_BY_USER:
                continue
            gaps.append(
                SemanticGap(
                    gap_id=gap_id,
                    category=GapCategory.AMBIGUOUS_RELATIONSHIP,
                    target_entity=table.table_name,
                    target_property=join,
                    description=f"Join '{join}' is inferred but not validated for business reporting.",
                    suggested_question=f"Is the relationship '{join}' valid for business queries?",
                    is_blocking=False,  # Changed: don't block on relationships
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
