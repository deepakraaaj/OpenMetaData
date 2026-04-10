from app.core.inference_rules import GapDetectionRules, SemanticInferenceRules
from app.engine.answer_interpreter import AnswerInterpreter
from app.engine.gap_detector import GapDetector
from app.engine.prioritizer import GapPrioritizer
from app.engine.question_generator import QuestionGenerator
from app.models.common import ConfidenceLabel, NamedConfidence
from app.models.normalized import NormalizedColumn, NormalizedSource, NormalizedTable
from app.models.questionnaire import QuestionAction, QuestionOption
from app.models.semantic import SemanticColumn, SemanticTable
from app.models.source_attribution import DiscoverySource
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


def test_gap_detector_suppresses_low_value_enum_noise_and_prioritizes_structured_table_meaning() -> None:
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
        tables={
            "alert_cfg": SemanticTable(
                table_name="alert_cfg",
                confidence=NamedConfidence(label=ConfidenceLabel.low, score=0.2),
            )
        },
    )

    gaps = GapDetector().detect(normalized, state)

    assert not any(gap.gap_id == "enum-alert_cfg.created_by" for gap in gaps)
    assert not any(gap.gap_id == "enum-alert_cfg.status" for gap in gaps)

    meaning_gap = next(gap for gap in gaps if gap.gap_id == "meaning-alert_cfg")
    assert meaning_gap.question_type == "meaning_confirmation"
    assert meaning_gap.best_guess
    assert meaning_gap.candidate_options
    assert meaning_gap.candidate_options[-1].is_fallback is True

    top_gap = GapPrioritizer().next_gap(gaps)
    assert top_gap is not None
    assert top_gap.gap_id == "meaning-alert_cfg"
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
        question_type="role_confirmation",
        best_guess="user",
        confidence=0.58,
        evidence=["column name overlaps with user", "candidate joins: user, user_role"],
        candidate_options=[
            QuestionOption(value="user", label="user", is_best_guess=True),
            QuestionOption(value="user_role", label="user_role"),
            QuestionOption(value="__other__", label="Something else", is_fallback=True),
        ],
        decision_prompt="Which entity does `api_key.user_id` most likely reference?",
        actions=[
            QuestionAction(value="confirm", label="Confirm"),
            QuestionAction(value="change", label="Change"),
            QuestionAction(value="skip", label="Skip"),
        ],
        impact_score=0.62,
        ambiguity_score=0.74,
        business_relevance=0.81,
        priority_score=0.37,
        allow_free_text=True,
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
    assert question.best_guess == "user"
    assert question.question_type == "role_confirmation"
    assert [option.value for option in question.candidate_options[:2]] == ["user", "user_role"]
    assert question.target_entity == "api_key"

    updated = AnswerInterpreter().apply(state, gap, "__confirm__")
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
                row_count=4200,
                join_candidates=["shipment.order_id=order.id"],
                entity_hint="Shipment",
                columns=[
                    _column("phase", enum_values=["0", "1"], sample_values=["0", "1"]),
                    _column("status", enum_values=["ready", "complete"], sample_values=["ready", "complete"], is_status_like=True),
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

    phase_gap = next(gap for gap in gaps if gap.gap_id == "enum-shipment.phase")
    assert phase_gap.question_type == "pattern_confirmation"
    assert phase_gap.best_guess
    assert phase_gap.priority_score > 0


def test_gap_detector_suppresses_telemetry_style_enum_noise() -> None:
    normalized = NormalizedSource(
        source_name="demo",
        db_type="sqlite",
        tables=[
            NormalizedTable(
                schema_name="main",
                table_name="vts_transaction",
                row_count=5000,
                join_candidates=["vts_transaction.vehicle_id=vehicle.id"],
                entity_hint="Vehicle trip transaction",
                columns=[
                    _column("check_sum", enum_values=["10", "20", "30"], sample_values=["10", "20", "30"]),
                    _column("gps_fix", enum_values=["0", "1"], sample_values=["0", "1"]),
                    _column(
                        "gsm_signal_strength",
                        enum_values=["1", "2", "3"],
                        sample_values=["1", "2", "3"],
                    ),
                    _column("imei_no", enum_values=["1001", "1002"], sample_values=["1001", "1002"]),
                    _column(
                        "main_power_status",
                        enum_values=["0", "1"],
                        sample_values=["0", "1"],
                        is_status_like=True,
                    ),
                    _column(
                        "number_of_satellite",
                        enum_values=["3", "4", "5"],
                        sample_values=["3", "4", "5"],
                    ),
                    _column(
                        "trip_status",
                        enum_values=["OPEN", "CLOSED"],
                        sample_values=["OPEN", "CLOSED"],
                        is_status_like=True,
                    ),
                ],
            )
        ],
    )
    state = KnowledgeState(
        source_name="demo",
        tables={"vts_transaction": SemanticTable(table_name="vts_transaction")},
    )

    gaps = GapDetector().detect(normalized, state)
    gap_ids = {gap.gap_id for gap in gaps}

    assert "enum-vts_transaction.trip_status" in gap_ids
    assert "enum-vts_transaction.check_sum" not in gap_ids
    assert "enum-vts_transaction.gps_fix" not in gap_ids
    assert "enum-vts_transaction.gsm_signal_strength" not in gap_ids
    assert "enum-vts_transaction.imei_no" not in gap_ids
    assert "enum-vts_transaction.main_power_status" not in gap_ids
    assert "enum-vts_transaction.number_of_satellite" not in gap_ids


def test_gap_detector_keeps_lookup_backed_status_id_as_enum_gap() -> None:
    normalized = NormalizedSource(
        source_name="demo",
        db_type="sqlite",
        tables=[
            NormalizedTable(
                schema_name="main",
                table_name="trip",
                row_count=4200,
                join_candidates=["trip.recent_state_id=trip_status_master.id"],
                entity_hint="Trip",
                columns=[
                    _column(
                        "recent_state_id",
                        enum_values=["10", "20", "30"],
                        sample_values=["10", "20", "30"],
                        is_status_like=True,
                        is_foreign_key=True,
                    ),
                ],
            ),
            NormalizedTable(
                schema_name="main",
                table_name="trip_status_master",
                columns=[
                    _column("id", sample_values=["10", "20", "30"], is_identifier_like=True),
                    _column("display_type", sample_values=["Created", "En Route", "Reached"]),
                ],
            ),
        ],
    )
    state = KnowledgeState(
        source_name="demo",
        tables={"trip": SemanticTable(table_name="trip")},
    )

    gaps = GapDetector().detect(normalized, state)
    gap = next(gap for gap in gaps if gap.gap_id == "enum-trip.recent_state_id")

    assert gap.metadata["lookup_tables"] == ["trip_status_master"]
    assert gap.metadata["auto_labels"] == ["Created", "En Route", "Reached"]
    assert any("trip_status_master" in item for item in gap.evidence)


def test_answer_interpreter_confirms_enum_pattern_without_fake_numeric_mapping() -> None:
    state = KnowledgeState(
        source_name="demo",
        tables={
            "trip": SemanticTable(
                table_name="trip",
                columns=[
                    SemanticColumn(
                        column_name="recent_state_id",
                        technical_type="INTEGER",
                    )
                ],
            )
        },
    )
    gap = SemanticGap(
        gap_id="enum-trip.recent_state_id",
        category=GapCategory.UNCONFIRMED_ENUM_MAPPING,
        target_entity="trip",
        target_property="recent_state_id",
        description="Column 'trip.recent_state_id' has unconfirmed business value interpretation.",
        question_type="pattern_confirmation",
        best_guess="Workflow or lifecycle status.",
        metadata={
            "observed_values": ["10", "20", "30"],
            "auto_labels": [],
        },
    )

    updated = AnswerInterpreter().apply(state, gap, "status_pattern")
    column = updated.tables["trip"].columns[0]

    assert "trip.recent_state_id" not in updated.enums
    assert column.business_meaning == "Lifecycle or workflow status for the record."
    assert column.attribution.source == DiscoverySource.CONFIRMED_BY_USER
