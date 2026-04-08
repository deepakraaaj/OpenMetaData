"""Prioritize semantic gaps by business impact."""
from __future__ import annotations

from app.models.state import GapCategory
from app.models.state import SemanticGap


_CATEGORY_RANK = {
    GapCategory.UNKNOWN_BUSINESS_MEANING: 0,
    GapCategory.AMBIGUOUS_RELATIONSHIP: 1,
    GapCategory.RELATIONSHIP_ROLE_UNCLEAR: 1,
    GapCategory.UNCONFIRMED_ENUM_MAPPING: 2,
    GapCategory.POTENTIAL_SENSITIVITY: 3,
    GapCategory.GLOSSARY_TERM_MISSING: 4,
    GapCategory.MISSING_PRIMARY_KEY: 5,
    GapCategory.OTHER: 6,
}


class GapPrioritizer:
    """Sorts gaps and returns the highest-priority unresolved gap."""

    def prioritize(self, gaps: list[SemanticGap]) -> list[SemanticGap]:
        """Sort gaps: blocking first, then by priority, then alphabetically by gap_id."""
        return sorted(
            gaps,
            key=lambda g: (
                0 if g.is_blocking else 1,
                g.priority,
                _CATEGORY_RANK.get(g.category, 99),
                -len(g.metadata.get("neighbor_tables", [])) if isinstance(g.metadata, dict) else 0,
                g.gap_id,
            ),
        )

    def next_gap(self, gaps: list[SemanticGap]) -> SemanticGap | None:
        """Return the single highest-priority gap, or None if all resolved."""
        prioritized = self.prioritize(gaps)
        return prioritized[0] if prioritized else None
