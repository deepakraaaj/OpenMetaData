"""Recompute readiness state after each knowledge state update."""
from __future__ import annotations

from app.models.state import KnowledgeState, ReadinessState


class ReadinessComputer:
    """Calculates readiness percentage from current gap state."""

    def compute(self, state: KnowledgeState) -> ReadinessState:
        gaps = state.unresolved_gaps
        total = len(gaps)
        blocking = sum(1 for g in gaps if g.is_blocking)

        if total == 0:
            return ReadinessState(
                is_ready=True,
                readiness_percentage=100.0,
                blocking_gaps_count=0,
                total_gaps_count=0,
                readiness_notes=["All semantic gaps have been resolved."],
            )

        # Weight blocking gaps more heavily
        table_count = len(state.tables)
        if table_count == 0:
            pct = 0.0
        else:
            # Base: ratio of tables that have user-confirmed meaning
            confirmed_tables = sum(
                1 for t in state.tables.values()
                if t.attribution.source == "confirmed_by_user"
            )
            base_pct = (confirmed_tables / table_count) * 50  # up to 50% from confirmations

            # Bonus: ratio of non-blocking gaps resolved (assume initial total was larger)
            non_blocking = total - blocking
            gap_penalty = (blocking * 10) + (non_blocking * 2)
            gap_pct = max(0.0, 50.0 - gap_penalty)

            pct = min(round(base_pct + gap_pct, 1), 99.9)  # Never 100% while gaps remain

        notes: list[str] = []
        if blocking > 0:
            notes.append(f"{blocking} blocking gap(s) must be resolved before export.")
        if total > 5:
            notes.append(f"{total} total gaps remaining — focus on high-priority items first.")

        return ReadinessState(
            is_ready=blocking == 0 and pct >= 80.0,
            readiness_percentage=pct,
            blocking_gaps_count=blocking,
            total_gaps_count=total,
            readiness_notes=notes,
        )
