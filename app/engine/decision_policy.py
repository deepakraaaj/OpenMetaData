from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.engine.answer_interpreter import AnswerInterpreter
from app.models.decision import (
    DecisionActor,
    DecisionRecord,
    DecisionStatus,
    ReviewDebtItem,
    ReviewMode,
    RiskLevel,
)
from app.models.review import TableRole
from app.models.semantic import SemanticTable, TableReviewStatus
from app.models.state import GapCategory, KnowledgeState, SemanticGap


_HIGH_CONFIDENCE = 0.8
_MEDIUM_CONFIDENCE = 0.55
_HIGH_RISK_TOKENS = {
    "access",
    "account",
    "company",
    "email",
    "org",
    "organization",
    "permission",
    "pii",
    "scope",
    "sensitive",
    "ssn",
    "tenant",
    "token",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(frozen=True)
class DecisionBlueprint:
    item_key: str
    item_type: str
    title: str
    target_entity: str | None
    target_property: str | None
    decision_actor: DecisionActor
    decision_status: DecisionStatus
    confidence: float | None
    risk_level: RiskLevel
    evidence_refs: list[str]
    policy_reason: str
    applied_value: Any
    suggested_value: Any
    provisional: bool
    review_debt: bool
    needs_human_review: bool
    publish_blocker: bool
    needs_acknowledgement: bool
    metadata: dict[str, Any]


class AIDecisionPolicyPass:
    LOW_RISK_GAPS = {
        GapCategory.UNKNOWN_BUSINESS_MEANING,
        GapCategory.UNCONFIRMED_ENUM_MAPPING,
        GapCategory.GLOSSARY_TERM_MISSING,
    }
    MEDIUM_RISK_GAPS = {
        GapCategory.AMBIGUOUS_RELATIONSHIP,
        GapCategory.RELATIONSHIP_ROLE_UNCLEAR,
    }
    HIGH_RISK_GAPS = {
        GapCategory.POTENTIAL_SENSITIVITY,
        GapCategory.MISSING_PRIMARY_KEY,
    }
    HUMAN_ACTORS = {DecisionActor.user_confirmed, DecisionActor.user_overridden}

    def __init__(self) -> None:
        self.answer_interpreter = AnswerInterpreter()

    def latest_decisions(self, state: KnowledgeState) -> dict[str, DecisionRecord]:
        latest: dict[str, DecisionRecord] = {}
        for record in state.decision_history:
            if record.overridden_by:
                continue
            latest[record.item_key] = record
        return latest

    def register_decision(self, state: KnowledgeState, blueprint: DecisionBlueprint, *, review_mode: ReviewMode) -> DecisionRecord:
        latest = self.latest_decisions(state)
        existing = latest.get(blueprint.item_key)
        if existing is not None and self._same_decision(existing, blueprint, review_mode):
            return existing

        record = DecisionRecord(
            decision_id=f"decision_{uuid4().hex}",
            item_key=blueprint.item_key,
            item_type=blueprint.item_type,
            title=blueprint.title,
            target_entity=blueprint.target_entity,
            target_property=blueprint.target_property,
            decision_actor=blueprint.decision_actor,
            review_mode=review_mode,
            decision_status=blueprint.decision_status,
            confidence=blueprint.confidence,
            risk_level=blueprint.risk_level,
            evidence_refs=list(blueprint.evidence_refs),
            policy_reason=blueprint.policy_reason,
            applied_value=blueprint.applied_value,
            suggested_value=blueprint.suggested_value,
            provisional=blueprint.provisional,
            review_debt=blueprint.review_debt,
            needs_human_review=blueprint.needs_human_review,
            publish_blocker=blueprint.publish_blocker,
            needs_acknowledgement=blueprint.needs_acknowledgement,
            supersedes=existing.decision_id if existing is not None else None,
            timestamp=_utc_now(),
            metadata=dict(blueprint.metadata),
        )
        if existing is not None:
            existing.overridden_by = record.decision_id
        state.decision_history.append(record)
        return record

    def apply(self, state: KnowledgeState) -> KnowledgeState:
        latest = self.latest_decisions(state)

        for table in state.tables.values():
            self._apply_table_policy(state, table, latest)

        remaining_gaps: list[SemanticGap] = []
        for gap in list(state.unresolved_gaps):
            current = latest.get(self._gap_item_key(gap))
            if current is not None and current.decision_actor in self.HUMAN_ACTORS:
                self._apply_gap_resolution(state, gap, current, keep_for_review=False)
                continue

            blueprint = self._gap_blueprint(state, gap)
            record = self.register_decision(state, blueprint, review_mode=state.review_mode)
            self._apply_gap_resolution(state, gap, record, keep_for_review=record.needs_human_review)
            if record.needs_human_review:
                gap.decision_status = record.decision_status
                gap.risk_level = record.risk_level
                gap.policy_reason = record.policy_reason
                gap.review_debt = record.review_debt
                gap.publish_blocker = record.publish_blocker
                gap.needs_acknowledgement = record.needs_acknowledgement
                gap.is_blocking = record.publish_blocker
                remaining_gaps.append(gap)

        state.unresolved_gaps = remaining_gaps
        state.review_debt = self._review_debt_items(state)
        return state

    def apply_scope_ai_defaults(
        self,
        state: KnowledgeState,
        *,
        domain_name: str | None = None,
        table_name: str | None = None,
    ) -> KnowledgeState:
        latest = self.latest_decisions(state)
        target_tables = {
            table.table_name
            for table in state.tables.values()
            if (domain_name is None or table.domain == domain_name)
            and (table_name is None or table.table_name == table_name)
        }
        if not target_tables:
            return state

        for table in state.tables.values():
            if table.table_name not in target_tables:
                continue
            blueprint = self._table_blueprint(table, ReviewMode.full_ai)
            record = self.register_decision(state, blueprint, review_mode=state.review_mode)
            self._apply_table_record(table, record)

        for gap in list(state.unresolved_gaps):
            if gap.target_entity not in target_tables:
                continue
            blueprint = self._gap_blueprint(state, gap, mode_override=ReviewMode.full_ai)
            record = self.register_decision(state, blueprint, review_mode=state.review_mode)
            keep_for_review = record.publish_blocker or record.needs_acknowledgement
            self._apply_gap_resolution(state, gap, record, keep_for_review=keep_for_review)

        state.unresolved_gaps = [
            gap
            for gap in state.unresolved_gaps
            if gap.target_entity not in target_tables or gap.publish_blocker or gap.needs_acknowledgement
        ]
        state.review_debt = self._review_debt_items(state)
        return state

    def record_gap_decision(
        self,
        state: KnowledgeState,
        gap: SemanticGap,
        answer: str,
        *,
        actor: DecisionActor,
        reviewer: str | None = None,
    ) -> DecisionRecord | None:
        if str(answer or "").strip().lower() == "__skip__":
            return None

        applied_value = gap.best_guess if str(answer or "").strip().lower() in {"confirm", "__confirm__"} else answer
        actor_status = DecisionStatus.user_confirmed if actor == DecisionActor.user_confirmed else DecisionStatus.user_overridden
        blueprint = DecisionBlueprint(
            item_key=self._gap_item_key(gap),
            item_type="gap_resolution",
            title=gap.decision_prompt or gap.description,
            target_entity=gap.target_entity,
            target_property=gap.target_property,
            decision_actor=actor,
            decision_status=actor_status,
            confidence=1.0 if actor in self.HUMAN_ACTORS else gap.confidence,
            risk_level=self._classify_gap_risk(gap),
            evidence_refs=list(gap.evidence),
            policy_reason="Explicit human decision overrides automated policy.",
            applied_value=applied_value,
            suggested_value=gap.best_guess,
            provisional=False,
            review_debt=False,
            needs_human_review=False,
            publish_blocker=False,
            needs_acknowledgement=False,
            metadata={"reviewer": reviewer} if reviewer else {},
        )
        return self.register_decision(state, blueprint, review_mode=state.review_mode)

    def record_table_decision(
        self,
        state: KnowledgeState,
        table: SemanticTable,
        *,
        selected: bool,
        reviewer: str | None = None,
    ) -> DecisionRecord:
        suggested = "selected" if table.recommended_selected else "excluded"
        applied = "selected" if selected else "excluded"
        actor = DecisionActor.user_confirmed if applied == suggested else DecisionActor.user_overridden
        status = DecisionStatus.user_confirmed if actor == DecisionActor.user_confirmed else DecisionStatus.user_overridden
        blueprint = DecisionBlueprint(
            item_key=self._table_item_key(table.table_name),
            item_type="table_selection",
            title=f"Selection scope for {table.table_name}",
            target_entity=table.table_name,
            target_property=None,
            decision_actor=actor,
            decision_status=status,
            confidence=1.0,
            risk_level=self._classify_table_risk(table),
            evidence_refs=list(table.evidence_refs),
            policy_reason="Explicit human selection overrides automated scope policy.",
            applied_value=applied,
            suggested_value=suggested,
            provisional=False,
            review_debt=False,
            needs_human_review=False,
            publish_blocker=False,
            needs_acknowledgement=False,
            metadata={"reviewer": reviewer} if reviewer else {},
        )
        record = self.register_decision(state, blueprint, review_mode=state.review_mode)
        self._apply_table_record(table, record)
        return record

    def _review_debt_items(self, state: KnowledgeState) -> list[ReviewDebtItem]:
        items: list[ReviewDebtItem] = []
        table_map = state.tables
        for record in self.latest_decisions(state).values():
            if not (record.review_debt or record.publish_blocker or record.needs_human_review):
                continue
            table = table_map.get(record.target_entity or "")
            items.append(
                ReviewDebtItem(
                    decision_id=record.decision_id,
                    item_key=record.item_key,
                    item_type=record.item_type,
                    title=record.title,
                    target_entity=record.target_entity,
                    target_property=record.target_property,
                    decision_actor=record.decision_actor,
                    review_mode=record.review_mode,
                    decision_status=record.decision_status,
                    confidence=record.confidence,
                    risk_level=record.risk_level,
                    policy_reason=record.policy_reason,
                    evidence_refs=list(record.evidence_refs),
                    domain=table.domain if table is not None else None,
                    table_name=table.table_name if table is not None else record.target_entity,
                    review_debt=record.review_debt,
                    needs_human_review=record.needs_human_review,
                    publish_blocker=record.publish_blocker,
                    needs_acknowledgement=record.needs_acknowledgement,
                    timestamp=record.timestamp,
                    metadata=dict(record.metadata),
                )
            )
        return sorted(
            items,
            key=lambda item: (
                item.publish_blocker is False,
                item.needs_human_review is False,
                item.table_name or "",
                item.title.lower(),
            ),
        )

    def _apply_gap_resolution(
        self,
        state: KnowledgeState,
        gap: SemanticGap,
        record: DecisionRecord,
        *,
        keep_for_review: bool,
    ) -> None:
        if record.applied_value in (None, "", []):
            return
        self.answer_interpreter.apply(
            state,
            gap,
            self._stringify_answer(record.applied_value),
            actor=record.decision_actor,
            reviewer=str(record.metadata.get("reviewer") or "") or None,
            retain_gap=True,
        )
        gap.decision_status = record.decision_status
        gap.risk_level = record.risk_level
        gap.policy_reason = record.policy_reason
        gap.review_debt = record.review_debt
        gap.publish_blocker = record.publish_blocker
        gap.needs_acknowledgement = record.needs_acknowledgement
        gap.is_blocking = keep_for_review and record.publish_blocker

    def _apply_table_policy(
        self,
        state: KnowledgeState,
        table: SemanticTable,
        latest: dict[str, DecisionRecord],
    ) -> None:
        current = latest.get(self._table_item_key(table.table_name))
        if current is not None and current.decision_actor in self.HUMAN_ACTORS:
            self._apply_table_record(table, current)
            return

        blueprint = self._table_blueprint(table, state.review_mode)
        record = self.register_decision(state, blueprint, review_mode=state.review_mode)
        self._apply_table_record(table, record)

    def _apply_table_record(self, table: SemanticTable, record: DecisionRecord) -> None:
        selected = str(record.applied_value or "").strip().lower() == "selected"
        table.selected = selected
        table.needs_review = record.needs_human_review
        table.requires_review = record.needs_human_review or record.publish_blocker or record.needs_acknowledgement
        table.decision_id = record.decision_id
        table.decision_status = record.decision_status
        table.decision_actor = record.decision_actor
        table.risk_level = record.risk_level
        table.policy_reason = record.policy_reason
        table.evidence_refs = list(record.evidence_refs)
        table.review_debt = record.review_debt
        table.publish_blocker = record.publish_blocker
        table.needs_acknowledgement = record.needs_acknowledgement
        if record.decision_actor in self.HUMAN_ACTORS:
            table.review_status = TableReviewStatus.confirmed if selected else TableReviewStatus.skipped
        elif table.review_status != TableReviewStatus.pending:
            table.review_status = TableReviewStatus.pending

    def _table_blueprint(self, table: SemanticTable, mode: ReviewMode) -> DecisionBlueprint:
        confidence = table.confidence.score
        risk = self._classify_table_risk(table)
        suggested = "selected" if table.recommended_selected else "excluded"
        decision = self._evaluate_policy(risk=risk, confidence=confidence, mode=mode, suggested_value=suggested)
        return DecisionBlueprint(
            item_key=self._table_item_key(table.table_name),
            item_type="table_selection",
            title=f"Selection scope for {table.table_name}",
            target_entity=table.table_name,
            target_property=None,
            decision_actor=decision.decision_actor,
            decision_status=decision.decision_status,
            confidence=confidence,
            risk_level=risk,
            evidence_refs=self._table_evidence(table),
            policy_reason=decision.policy_reason,
            applied_value=decision.applied_value,
            suggested_value=suggested,
            provisional=decision.provisional,
            review_debt=decision.review_debt,
            needs_human_review=decision.needs_human_review,
            publish_blocker=decision.publish_blocker,
            needs_acknowledgement=decision.needs_acknowledgement,
            metadata={},
        )

    def _gap_blueprint(
        self,
        state: KnowledgeState,
        gap: SemanticGap,
        *,
        mode_override: ReviewMode | None = None,
    ) -> DecisionBlueprint:
        confidence = gap.confidence if gap.confidence is not None else self._fallback_gap_confidence(state, gap)
        risk = self._classify_gap_risk(gap)
        suggested = self._recommended_gap_answer(gap)
        decision = self._evaluate_policy(
            risk=risk,
            confidence=confidence,
            mode=mode_override or state.review_mode,
            suggested_value=suggested,
        )
        return DecisionBlueprint(
            item_key=self._gap_item_key(gap),
            item_type="gap_resolution",
            title=gap.decision_prompt or gap.description,
            target_entity=gap.target_entity,
            target_property=gap.target_property,
            decision_actor=decision.decision_actor,
            decision_status=decision.decision_status,
            confidence=confidence,
            risk_level=risk,
            evidence_refs=list(gap.evidence),
            policy_reason=decision.policy_reason,
            applied_value=decision.applied_value,
            suggested_value=suggested,
            provisional=decision.provisional,
            review_debt=decision.review_debt,
            needs_human_review=decision.needs_human_review,
            publish_blocker=decision.publish_blocker,
            needs_acknowledgement=decision.needs_acknowledgement,
            metadata={"gap_category": gap.category.value},
        )

    def _evaluate_policy(
        self,
        *,
        risk: RiskLevel,
        confidence: float | None,
        mode: ReviewMode,
        suggested_value: Any,
    ) -> DecisionBlueprint:
        score = confidence if confidence is not None else 0.5
        is_high = score >= _HIGH_CONFIDENCE
        is_medium = score >= _MEDIUM_CONFIDENCE

        if risk == RiskLevel.low and is_high:
            return self._decision(DecisionActor.ai_auto, DecisionStatus.auto_accepted, "Low risk and high confidence: auto-accepted.", review_debt=False, needs_human_review=False, publish_blocker=False, needs_acknowledgement=False, provisional=False, applied_value=suggested_value)
        if risk == RiskLevel.low and is_medium:
            return self._decision(DecisionActor.ai_auto, DecisionStatus.deferred_review, "Low risk with medium confidence: auto-applied and added to review debt.", review_debt=True, needs_human_review=False, publish_blocker=False, needs_acknowledgement=False, provisional=False, applied_value=suggested_value)
        if risk == RiskLevel.medium and is_high:
            return self._decision(DecisionActor.ai_auto, DecisionStatus.deferred_review, "Medium risk with high confidence: auto-applied with review debt.", review_debt=True, needs_human_review=False, publish_blocker=False, needs_acknowledgement=False, provisional=False, applied_value=suggested_value)
        if risk == RiskLevel.medium and is_medium and mode == ReviewMode.full_ai:
            return self._decision(DecisionActor.ai_auto, DecisionStatus.deferred_review, "Full AI mode auto-applies medium-risk, medium-confidence decisions.", review_debt=True, needs_human_review=False, publish_blocker=False, needs_acknowledgement=False, provisional=False, applied_value=suggested_value)
        if risk == RiskLevel.high and not is_high:
            return self._decision(DecisionActor.rule_default, DecisionStatus.publish_blocked, "High risk without high confidence: continue onboarding, but keep blocked for publish.", review_debt=True, needs_human_review=True, publish_blocker=True, needs_acknowledgement=False, provisional=False, applied_value=None)
        if risk == RiskLevel.high and is_high:
            return self._decision(DecisionActor.rule_default, DecisionStatus.warning_ack_required, "High risk with high confidence: prefill recommendation and require acknowledgement before publish.", review_debt=True, needs_human_review=True, publish_blocker=True, needs_acknowledgement=True, provisional=True, applied_value=suggested_value)
        return self._decision(DecisionActor.rule_default, DecisionStatus.deferred_review, "Confidence is not high enough for silent automation in the current mode.", review_debt=True, needs_human_review=mode != ReviewMode.full_ai, publish_blocker=False, needs_acknowledgement=False, provisional=mode != ReviewMode.full_ai, applied_value=suggested_value)

    def _decision(
        self,
        decision_actor: DecisionActor,
        decision_status: DecisionStatus,
        policy_reason: str,
        *,
        review_debt: bool,
        needs_human_review: bool,
        publish_blocker: bool,
        needs_acknowledgement: bool,
        provisional: bool,
        applied_value: Any,
    ) -> DecisionBlueprint:
        return DecisionBlueprint(
            item_key="",
            item_type="",
            title="",
            target_entity=None,
            target_property=None,
            decision_actor=decision_actor,
            decision_status=decision_status,
            confidence=None,
            risk_level=RiskLevel.medium,
            evidence_refs=[],
            policy_reason=policy_reason,
            applied_value=applied_value,
            suggested_value=applied_value,
            provisional=provisional,
            review_debt=review_debt,
            needs_human_review=needs_human_review,
            publish_blocker=publish_blocker,
            needs_acknowledgement=needs_acknowledgement,
            metadata={},
        )

    def _same_decision(self, existing: DecisionRecord, blueprint: DecisionBlueprint, review_mode: ReviewMode) -> bool:
        return (
            existing.review_mode == review_mode
            and existing.decision_actor == blueprint.decision_actor
            and existing.decision_status == blueprint.decision_status
            and existing.risk_level == blueprint.risk_level
            and existing.applied_value == blueprint.applied_value
            and existing.suggested_value == blueprint.suggested_value
            and existing.review_debt == blueprint.review_debt
            and existing.needs_human_review == blueprint.needs_human_review
            and existing.publish_blocker == blueprint.publish_blocker
            and existing.needs_acknowledgement == blueprint.needs_acknowledgement
            and existing.policy_reason == blueprint.policy_reason
        )

    def _gap_item_key(self, gap: SemanticGap) -> str:
        return f"gap:{gap.gap_id}"

    def _table_item_key(self, table_name: str) -> str:
        return f"table_selection:{table_name}"

    def _classify_gap_risk(self, gap: SemanticGap) -> RiskLevel:
        if gap.category in self.HIGH_RISK_GAPS:
            return RiskLevel.high
        if gap.category in self.MEDIUM_RISK_GAPS:
            if self._contains_high_risk_token(gap.target_property or "") or self._contains_high_risk_token(gap.target_entity or ""):
                return RiskLevel.high
            return RiskLevel.medium
        if gap.category in self.LOW_RISK_GAPS:
            if self._contains_high_risk_token(gap.target_property or ""):
                return RiskLevel.high
            return RiskLevel.low
        return RiskLevel.medium

    def _classify_table_risk(self, table: SemanticTable) -> RiskLevel:
        if table.role in {TableRole.log_event, TableRole.history_audit, TableRole.config_system}:
            return RiskLevel.low
        tokens = " ".join(
            [
                table.table_name,
                table.domain or "",
                table.likely_entity or "",
                " ".join(table.important_columns[:6]),
                " ".join(table.sensitivity_notes[:4]),
            ]
        )
        if self._contains_high_risk_token(tokens):
            return RiskLevel.high
        return RiskLevel.medium

    def _recommended_gap_answer(self, gap: SemanticGap) -> Any:
        for option in gap.candidate_options:
            if option.is_best_guess:
                return option.value or option.label
        if gap.best_guess not in (None, "", []):
            return gap.best_guess
        if gap.candidate_options:
            option = gap.candidate_options[0]
            return option.value or option.label
        return None

    def _fallback_gap_confidence(self, state: KnowledgeState, gap: SemanticGap) -> float:
        table = state.tables.get(gap.target_entity or "")
        if table is not None:
            return table.confidence.score
        return 0.5

    def _table_evidence(self, table: SemanticTable) -> list[str]:
        evidence = [
            table.selection_reason or "",
            table.reason_for_classification or "",
            table.review_reason or "",
            f"related tables: {', '.join(table.related_tables[:4])}" if table.related_tables else "",
        ]
        return [item for item in evidence if item]

    def _contains_high_risk_token(self, value: str) -> bool:
        lowered = str(value or "").lower()
        return any(token in lowered for token in _HIGH_RISK_TOKENS)

    def _stringify_answer(self, value: Any) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, list):
            return ",".join(str(item) for item in value)
        if isinstance(value, dict):
            return ",".join(f"{key}={item}" for key, item in value.items())
        return str(value)
