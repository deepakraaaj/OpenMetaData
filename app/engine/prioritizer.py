"""Prioritize semantic gaps by business impact."""
from __future__ import annotations

from app.models.state import SemanticGap


class GapPrioritizer:
    """Sorts gaps and returns the highest-priority unresolved gap."""

    def prioritize(self, gaps: list[SemanticGap]) -> list[SemanticGap]:
        """Sort gaps: blocking first, then by priority, then alphabetically by gap_id."""
        return sorted(
            gaps,
            key=lambda g: (
                0 if g.is_blocking else 1,
                g.priority,
                g.gap_id,
            ),
        )

    def next_gap(self, gaps: list[SemanticGap]) -> SemanticGap | None:
        """Return the single highest-priority gap, or None if all resolved."""
        prioritized = self.prioritize(gaps)
        return prioritized[0] if prioritized else None
