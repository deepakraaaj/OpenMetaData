from pathlib import Path

from app.engine.service import OnboardingEngine
from app.models.common import ConfidenceLabel, NamedConfidence
from app.models.normalized import NormalizedColumn, NormalizedSource, NormalizedTable
from app.models.semantic import SemanticColumn, SemanticTable
from app.models.state import KnowledgeState


def test_refresh_backfills_inferred_actor_reference_meaning(tmp_path: Path) -> None:
    engine = OnboardingEngine(tmp_path)
    state = KnowledgeState(
        source_name="demo",
        tables={
            "alert_cfg": SemanticTable(
                table_name="alert_cfg",
                columns=[
                    SemanticColumn(
                        column_name="created_by",
                        technical_type="INTEGER",
                        business_meaning="Timestamp used for audit, freshness, or trend analysis.",
                        confidence=NamedConfidence(
                            label=ConfidenceLabel.high,
                            score=0.85,
                            rationale=["timestamp-like naming"],
                        ),
                    )
                ],
            ),
            "user": SemanticTable(table_name="user"),
        },
    )
    engine.state_manager.save("demo", state)

    normalized = NormalizedSource(
        source_name="demo",
        db_type="sqlite",
        tables=[
            NormalizedTable(
                schema_name="main",
                table_name="alert_cfg",
                columns=[
                    NormalizedColumn(
                        schema_name="main",
                        table_name="alert_cfg",
                        column_name="created_by",
                        technical_type="INTEGER",
                        sample_values=["11784212"],
                    )
                ],
            ),
            NormalizedTable(
                schema_name="main",
                table_name="user",
                columns=[
                    NormalizedColumn(
                        schema_name="main",
                        table_name="user",
                        column_name="id",
                        technical_type="INTEGER",
                        is_primary_key=True,
                    )
                ],
            ),
        ],
    )

    refreshed = engine.refresh("demo", normalized)
    created_by = refreshed.tables["alert_cfg"].columns[0]

    assert created_by.business_meaning == "User who created this alert cfg record."
    assert created_by.confidence.score >= 0.9
