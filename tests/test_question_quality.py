from app.core.inference_rules import GapDetectionRules, SemanticInferenceRules
from app.engine.answer_interpreter import AnswerInterpreter
from app.engine.gap_detector import GapDetector
from app.engine.prioritizer import GapPrioritizer
from app.engine.question_generator import QuestionGenerator
from app.models.normalized import NormalizedColumn, NormalizedSource, NormalizedTable
from app.models.semantic import SemanticTable
from app.models.state import GapCategory, KnowledgeState, SemanticGap


def _column(
    name: str,
    *,
    enum_values: list[str] | None = None,
    sample_values: list[str] | None = None,
    is_status_like: bool = False,
    is_identifier_like: bool = False,
    is_foreign_key: bool = False,
) -> NormalizedColumn:
    return NormalizedColumn(
        schema_name="main",
        table_name="api_key",
        column_name=name,
        technical_type="TEXT",
        enum_values=enum_values or [],
        sample_values=sample_values or [],
        is_status_like=is_status_like,
        is_identifier_like=is_identifier_like,
        is_foreign_key=is_foreign_key,
    )


def test_gap_detector_skips_audit_enum_noise_and_prioritizes_table_meaning() -> None:
    normalized = NormalizedSource(
        source_name="demo",
        db_type="sqlite",
        tables=[
            NormalizedTable(
                schema_name="main",
                table_name="alert_cfg",
                join_candidates=["alert_cfg.vehicle_id=vehicle.id"],
                entity_hint="Alert Configuration",
                grain_hint="One row per alert rule.",
                columns=[
                    _column("created_by", enum_values=["11784212"], sample_values=["11784212"], is_status_like=True),
                    _column("status", enum_values=["OPEN", "CLOSED"], sample_values=["OPEN", "CLOSED"], is_status_like=True),
                ],
            )
        ],
    )
    state = KnowledgeState(
        source_name="demo",
        tables={"alert_cfg": SemanticTable(table_name="alert_cfg")},
    )

    gaps = GapDetector().detect(normalized, state)

    assert not any(gap.gap_id == "enum-alert_cfg.created_by" for gap in gaps)
    assert any(gap.gap_id == "enum-alert_cfg.status" for gap in gaps)

    top_gap = GapPrioritizer().next_gap(gaps)
    assert top_gap is not None
    assert top_gap.category == GapCategory.UNKNOWN_BUSINESS_MEANING
    assert top_gap.target_entity == "alert_cfg"


def test_gap_detector_creates_relationship_disambiguation_gap() -> None:
    normalized = NormalizedSource(
        source_name="demo",
        db_type="sqlite",
        tables=[
            NormalizedTable(
                schema_name="main",
                table_name="trip",
                join_candidates=[
                    "trip.billing_company_id=company.id",
                    "trip.billing_company_id=vehicle_billing_company_history.id",
                    "trip.billing_company_id=vehicle_billing_company_product_mapping.id",
                ],
                columns=[
                    _column("billing_company_id", sample_values=["11784212"], is_identifier_like=True),
                ],
            )
        ],
    )
    state = KnowledgeState(
        source_name="demo",
        tables={"trip": SemanticTable(table_name="trip")},
    )

    gaps = GapDetector().detect(normalized, state)
    relationship_gap = next(gap for gap in gaps if gap.category == GapCategory.AMBIGUOUS_RELATIONSHIP)

    assert relationship_gap.target_property == "billing_company_id"
    assert relationship_gap.metadata["candidate_tables"] == [
        "vehicle_billing_company_history",
        "vehicle_billing_company_product_mapping",
        "company",
    ]
    assert "trip.billing_company_id" in relationship_gap.description


def test_question_generator_and_answer_interpreter_handle_relationship_choices() -> None:
    state = KnowledgeState(
        source_name="demo",
        tables={"api_key": SemanticTable(table_name="api_key")},
    )
    gap = SemanticGap(
        gap_id="rel-api_key-user_id",
        category=GapCategory.AMBIGUOUS_RELATIONSHIP,
        target_entity="api_key",
        target_property="user_id",
        description="Column 'api_key.user_id' may reference one of several user entities.",
        metadata={
            "candidate_tables": ["user", "user_role"],
            "candidate_joins": {
                "user": "api_key.user_id=user.id",
                "user_role": "api_key.user_id=user_role.id",
            },
        },
    )

    question = QuestionGenerator().generate(gap, state)

    assert question.input_type == "select"
    assert question.choices == ["user", "user_role"]
    assert question.target_entity == "api_key"

    updated = AnswerInterpreter().apply(state, gap, "user")
    assert "api_key.user_id=user.id" in updated.tables["api_key"].valid_joins
    assert "api_key.user_id=user_role.id" not in updated.tables["api_key"].valid_joins


def test_gap_detector_uses_configured_enum_tokens() -> None:
    normalized = NormalizedSource(
        source_name="demo",
        db_type="sqlite",
        tables=[
            NormalizedTable(
                schema_name="main",
                table_name="shipment",
                columns=[
                    _column("phase", enum_values=["queued", "loaded"], sample_values=["queued", "loaded"]),
                ],
            )
        ],
    )
    state = KnowledgeState(
        source_name="demo",
        tables={"shipment": SemanticTable(table_name="shipment")},
    )

    gaps = GapDetector(
        SemanticInferenceRules(
            gap_detection=GapDetectionRules(
                enum_name_tokens=("phase",),
                boolean_prefixes=(),
            )
        )
    ).detect(normalized, state)

    assert any(gap.gap_id == "enum-shipment.phase" for gap in gaps)
