from pathlib import Path

from app.engine.service import OnboardingEngine
from app.models.common import ConfidenceLabel, NamedConfidence
from app.models.normalized import NormalizedColumn, NormalizedSource, NormalizedTable
from app.models.semantic import SemanticSourceModel, SemanticTable, TableReviewStatus


def _normalized_source() -> NormalizedSource:
    return NormalizedSource(
        source_name="demo",
        db_type="sqlite",
        tables=[
            NormalizedTable(
                schema_name="main",
                table_name="audit_log",
                entity_hint="Audit Event",
                columns=[
                    NormalizedColumn(
                        schema_name="main",
                        table_name="audit_log",
                        column_name="id",
                        technical_type="INTEGER",
                        is_primary_key=True,
                    ),
                    NormalizedColumn(
                        schema_name="main",
                        table_name="audit_log",
                        column_name="event_type",
                        technical_type="TEXT",
                        enum_values=["LOGIN", "LOGOUT"],
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
                table_name="audit_log",
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
    assert any(gap.target_entity == "audit_log" for gap in initial.unresolved_gaps)

    updated = engine.review_table(
        "demo",
        "audit_log",
        TableReviewStatus.skipped,
        normalized=normalized,
    )

    assert updated.tables["audit_log"].review_status == TableReviewStatus.skipped
    assert not any(gap.target_entity == "audit_log" for gap in updated.unresolved_gaps)


def test_confirm_table_refreshes_gaps_and_marks_review_status(tmp_path: Path) -> None:
    engine = OnboardingEngine(tmp_path)
    normalized = _normalized_source()
    semantic = _semantic_source()

    initial = engine.initialize("demo", normalized, semantic=semantic)
    assert any(gap.target_entity == "audit_log" for gap in initial.unresolved_gaps)

    updated = engine.confirm_table("demo", "audit_log", "Reviewer", normalized=normalized)

    assert updated.tables["audit_log"].review_status == TableReviewStatus.confirmed
    assert not any(gap.target_entity == "audit_log" for gap in updated.unresolved_gaps)
