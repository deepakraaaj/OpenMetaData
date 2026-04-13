from pathlib import Path

from app.engine.answer_interpreter import AnswerInterpreter
from app.engine.service import OnboardingEngine
from app.models.common import ConfidenceLabel, NamedConfidence
from app.models.normalized import NormalizedColumn, NormalizedSource, NormalizedTable
from app.models.semantic import SemanticSourceModel, SemanticTable, TableReviewStatus
from app.models.state import GapCategory, SemanticGap


def _normalized_source() -> NormalizedSource:
    return NormalizedSource(
        source_name="demo",
        db_type="sqlite",
        tables=[
            NormalizedTable(
                schema_name="main",
                table_name="dispatch_task",
                entity_hint="Dispatch Task",
                row_count=2400,
                join_candidates=["dispatch_task.user_id=users.id"],
                columns=[
                    NormalizedColumn(
                        schema_name="main",
                        table_name="dispatch_task",
                        column_name="id",
                        technical_type="INTEGER",
                        is_primary_key=True,
                    ),
                    NormalizedColumn(
                        schema_name="main",
                        table_name="dispatch_task",
                        column_name="status",
                        technical_type="TEXT",
                        enum_values=["OPEN", "DONE"],
                        is_status_like=True,
                    ),
                    NormalizedColumn(
                        schema_name="main",
                        table_name="dispatch_task",
                        column_name="user_id",
                        technical_type="INTEGER",
                        is_foreign_key=True,
                    ),
                ],
            ),
            NormalizedTable(
                schema_name="main",
                table_name="users",
                entity_hint="User",
                columns=[
                    NormalizedColumn(
                        schema_name="main",
                        table_name="users",
                        column_name="id",
                        technical_type="INTEGER",
                        is_primary_key=True,
                    )
                ],
            ),
        ],
    )


def _semantic_source() -> SemanticSourceModel:
    return SemanticSourceModel(
        source_name="demo",
        db_type="sqlite",
        tables=[
            SemanticTable(
                table_name="dispatch_task",
                business_meaning="",
                confidence=NamedConfidence(
                    label=ConfidenceLabel.low,
                    score=0.2,
                    rationale=["no reliable semantic hint"],
                ),
            ),
            SemanticTable(
                table_name="users",
                business_meaning="Core user records.",
                confidence=NamedConfidence(
                    label=ConfidenceLabel.high,
                    score=0.9,
                    rationale=["clear naming"],
                ),
            ),
        ],
    )


def test_review_table_skip_removes_table_from_gap_queue(tmp_path: Path) -> None:
    engine = OnboardingEngine(tmp_path)
    normalized = _normalized_source()
    semantic = _semantic_source()

    initial = engine.initialize("demo", normalized, semantic=semantic)
    assert any(gap.target_entity == "dispatch_task" for gap in initial.unresolved_gaps)

    updated = engine.review_table(
        "demo",
        "dispatch_task",
        TableReviewStatus.skipped,
        normalized=normalized,
    )

    assert updated.tables["dispatch_task"].review_status == TableReviewStatus.skipped
    assert not any(gap.target_entity == "dispatch_task" for gap in updated.unresolved_gaps)


def test_confirm_table_refreshes_gaps_and_marks_review_status(tmp_path: Path) -> None:
    engine = OnboardingEngine(tmp_path)
    normalized = _normalized_source()
    semantic = _semantic_source()

    initial = engine.initialize("demo", normalized, semantic=semantic)
    assert any(gap.target_entity == "dispatch_task" for gap in initial.unresolved_gaps)

    updated = engine.confirm_table("demo", "dispatch_task", "Reviewer", normalized=normalized)

    assert updated.tables["dispatch_task"].review_status == TableReviewStatus.confirmed
    assert not any(gap.target_entity == "dispatch_task" for gap in updated.unresolved_gaps)


def test_answer_interpreter_persists_business_rules_for_enum_mappings() -> None:
    engine = OnboardingEngine(Path("/tmp"))
    normalized = _normalized_source()
    semantic = _semantic_source()
    state = engine.state_manager.initialize_from_semantic("demo", semantic)
    state.tables["dispatch_task"].columns = semantic.tables[0].columns

    gap = SemanticGap(
        gap_id="enum-dispatch_task.status",
        category=GapCategory.UNCONFIRMED_ENUM_MAPPING,
        target_entity="dispatch_task",
        target_property="status",
        description="Status mapping needs confirmation.",
        metadata={"observed_values": ["OPEN", "DONE"]},
    )

    updated = AnswerInterpreter().apply(
        state,
        gap,
        "OPEN=Open, DONE=Completed",
    )

    assert any(rule.rule_name == "enum:dispatch_task.status:OPEN" for rule in updated.business_rules)
    assert any(rule.rule_name == "enum:dispatch_task.status:DONE" for rule in updated.business_rules)
