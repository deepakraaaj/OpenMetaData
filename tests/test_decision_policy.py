from app.engine.decision_policy import AIDecisionPolicyPass
from app.engine.readiness import ReadinessComputer
from app.models.common import ConfidenceLabel, NamedConfidence
from app.models.decision import ReviewMode
from app.models.questionnaire import QuestionOption
from app.models.semantic import SemanticColumn, SemanticTable
from app.models.state import GapCategory, KnowledgeState, SemanticGap


def test_low_risk_medium_confidence_gap_is_auto_applied_and_tracked_as_review_debt() -> None:
    state = KnowledgeState(
        source_name="demo",
        review_mode=ReviewMode.guided,
        tables={
            "orders": SemanticTable(
                table_name="orders",
                confidence=NamedConfidence(label=ConfidenceLabel.medium, score=0.66),
            )
        },
        unresolved_gaps=[
            SemanticGap(
                gap_id="meaning-orders",
                category=GapCategory.UNKNOWN_BUSINESS_MEANING,
                target_entity="orders",
                description="Meaning is not fully confirmed.",
                decision_prompt="What does orders represent?",
                best_guess="Operational order records.",
                confidence=0.66,
                evidence=["table name suggests business transactions"],
            )
        ],
    )

    updated = AIDecisionPolicyPass().apply(state)

    assert updated.unresolved_gaps == []
    assert updated.tables["orders"].business_meaning == "Operational order records."
    gap_debt = next(item for item in updated.review_debt if item.item_key == "gap:meaning-orders")
    assert gap_debt.decision_status.value == "deferred_review"
    assert gap_debt.decision_actor.value == "ai_auto"


def test_medium_risk_medium_confidence_gap_is_mode_sensitive() -> None:
    guided_state = KnowledgeState(
        source_name="demo",
        review_mode=ReviewMode.guided,
        tables={
            "orders": SemanticTable(
                table_name="orders",
                confidence=NamedConfidence(label=ConfidenceLabel.medium, score=0.62),
            )
        },
        unresolved_gaps=[
            SemanticGap(
                gap_id="relationship-orders-user",
                category=GapCategory.AMBIGUOUS_RELATIONSHIP,
                target_entity="orders",
                target_property="user_id",
                description="orders.user_id could join to multiple entities.",
                decision_prompt="Which entity does orders.user_id reference?",
                best_guess="users",
                confidence=0.62,
                evidence=["column name matches users.id"],
                metadata={"candidate_joins": {"users": "orders.user_id = users.id"}},
            )
        ],
    )
    full_ai_state = guided_state.model_copy(deep=True)
    full_ai_state.review_mode = ReviewMode.full_ai

    guided_updated = AIDecisionPolicyPass().apply(guided_state)
    full_ai_updated = AIDecisionPolicyPass().apply(full_ai_state)

    assert len(guided_updated.unresolved_gaps) == 1
    assert guided_updated.unresolved_gaps[0].decision_status.value == "deferred_review"
    assert full_ai_updated.unresolved_gaps == []
    assert "orders.user_id = users.id" in full_ai_updated.tables["orders"].valid_joins


def test_high_risk_high_confidence_gap_stays_as_publish_blocker_until_acknowledged() -> None:
    state = KnowledgeState(
        source_name="demo",
        review_mode=ReviewMode.full_ai,
        tables={
            "customer": SemanticTable(
                table_name="customer",
                confidence=NamedConfidence(label=ConfidenceLabel.high, score=0.92),
                columns=[SemanticColumn(column_name="email", technical_type="varchar")],
            )
        },
        unresolved_gaps=[
            SemanticGap(
                gap_id="sensitivity-customer-email",
                category=GapCategory.POTENTIAL_SENSITIVITY,
                target_entity="customer",
                target_property="email",
                description="customer.email looks sensitive.",
                decision_prompt="Should customer.email be masked?",
                best_guess="mask",
                confidence=0.92,
                evidence=["email format detected"],
            )
        ],
    )

    updated = AIDecisionPolicyPass().apply(state)
    readiness = ReadinessComputer().compute(updated)

    assert len(updated.unresolved_gaps) == 1
    assert updated.unresolved_gaps[0].decision_status.value == "warning_ack_required"
    assert updated.tables["customer"].columns[0].displayable is False
    assert readiness.publish_ready is False
    assert readiness.publish_blockers_count == 1


def test_recommended_gap_answer_prefers_best_option_value_over_best_guess_text() -> None:
    gap = SemanticGap(
        gap_id="enum-orders.status",
        category=GapCategory.UNCONFIRMED_ENUM_MAPPING,
        target_entity="orders",
        target_property="status",
        description="orders.status needs enum interpretation.",
        best_guess="Workflow or lifecycle status.",
        candidate_options=[
            QuestionOption(
                value="status_pattern",
                label="Workflow or lifecycle status",
                is_best_guess=True,
            ),
            QuestionOption(value="type_pattern", label="Type or category"),
        ],
    )

    answer = AIDecisionPolicyPass()._recommended_gap_answer(gap)

    assert answer == "status_pattern"
