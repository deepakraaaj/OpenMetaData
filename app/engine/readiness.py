"""Recompute readiness state after each knowledge state update."""
from __future__ import annotations

from app.engine.decision_policy import AIDecisionPolicyPass
from app.models.semantic import TableReviewStatus
from app.models.state import KnowledgeState, ReadinessState


class ReadinessComputer:
    """Calculates readiness percentage from current gap state."""

    def compute(self, state: KnowledgeState) -> ReadinessState:
        gaps = state.unresolved_gaps
        total = len(gaps)
        blocking = sum(1 for g in gaps if g.is_blocking)
        policy = AIDecisionPolicyPass()
        latest_decisions = policy.latest_decisions(state)
        publish_blockers = sum(1 for record in latest_decisions.values() if record.publish_blocker)
        warning_ack_required = sum(1 for record in latest_decisions.values() if record.needs_acknowledgement)
        review_debt_count = len(state.review_debt)

        if total == 0:
            return ReadinessState(
                is_ready=publish_blockers == 0,
                continue_ready=True,
                publish_ready=publish_blockers == 0,
                readiness_percentage=100.0,
                blocking_gaps_count=0,
                publish_blockers_count=publish_blockers,
                warning_ack_required_count=warning_ack_required,
                review_debt_count=review_debt_count,
                total_gaps_count=0,
                readiness_notes=["All review items that require immediate attention have been handled."],
                continue_notes=["Onboarding can continue with the current semantic bundle."],
                publish_notes=(
                    ["Bundle is publish-ready."]
                    if publish_blockers == 0
                    else [f"{publish_blockers} publish blocker(s) still need confirmation."]
                ),
            )

        # Weight blocking gaps more heavily
        active_tables = [
            table for table in state.tables.values() if table.selected and table.review_status != TableReviewStatus.skipped
        ]
        continue_ready = len(active_tables) > 0
        publish_ready = continue_ready and publish_blockers == 0
        if not active_tables:
            pct = 0.0
        else:
            confirmed_tables = sum(1 for t in active_tables if t.review_status == TableReviewStatus.confirmed)
            base_pct = (confirmed_tables / len(active_tables)) * 45
            review_penalty = min(total * 3.0, 30.0)
            blocker_penalty = min(publish_blockers * 12.0, 35.0)
            debt_penalty = min(review_debt_count * 1.5, 20.0)
            pct = max(0.0, min(100.0, round(100.0 - review_penalty - blocker_penalty - debt_penalty + base_pct, 1)))

        notes: list[str] = []
        continue_notes: list[str] = []
        publish_notes: list[str] = []
        if continue_ready:
            continue_notes.append("Onboarding can continue with AI-decided defaults and deferred review.")
        else:
            continue_notes.append("No selected tables are currently available for onboarding outputs.")
        if blocking > 0:
            notes.append(f"{blocking} active review item(s) are still waiting for human input.")
        if review_debt_count > 0:
            notes.append(f"{review_debt_count} item(s) were accepted provisionally and can be reviewed later.")
        if publish_blockers > 0:
            publish_notes.append(f"{publish_blockers} publish blocker(s) still need confirmation before publish.")
        if warning_ack_required > 0:
            publish_notes.append(f"{warning_ack_required} high-risk item(s) need acknowledgement before publish.")
        if publish_blockers == 0 and continue_ready:
            publish_notes.append("No publish blockers remain.")

        return ReadinessState(
            is_ready=publish_ready,
            continue_ready=continue_ready,
            publish_ready=publish_ready,
            readiness_percentage=pct,
            blocking_gaps_count=blocking,
            publish_blockers_count=publish_blockers,
            warning_ack_required_count=warning_ack_required,
            review_debt_count=review_debt_count,
            total_gaps_count=total,
            readiness_notes=notes,
            continue_notes=continue_notes,
            publish_notes=publish_notes,
        )
