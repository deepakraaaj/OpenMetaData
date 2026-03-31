from app.models.artifacts import LLMContextPackage
from app.models.common import ConfidenceLabel, NamedConfidence, SensitivityLabel
from app.models.semantic import QueryPattern, SemanticColumn, SemanticSourceModel, SemanticTable
from app.retrieval.service import RetrievalContextBuilder


def test_retrieval_context_matches_tables_and_columns() -> None:
    semantic = SemanticSourceModel(
        source_name="ioc_dev_march_9",
        db_type="mysql",
        domain="fleet_operations",
        tables=[
            SemanticTable(
                table_name="trip",
                business_meaning="Primary trip records.",
                likely_entity="Trip",
                valid_joins=["trip.vehicle_id=vehicle.id"],
                columns=[
                    SemanticColumn(
                        column_name="vehicle_id",
                        technical_type="int",
                        business_meaning="Vehicle reference",
                        sensitive=SensitivityLabel.none,
                        confidence=NamedConfidence(label=ConfidenceLabel.high, score=0.9),
                    )
                ],
            )
        ],
        query_patterns=[
            QueryPattern(
                intent="trip_summary",
                question_examples=["How many trips happened today?"],
                preferred_tables=["trip"],
            )
        ],
    )

    package = RetrievalContextBuilder().build(semantic, "How many trips by vehicle?")
    assert isinstance(package, LLMContextPackage)
    assert "trip" in package.matched_tables
    assert "trip.vehicle_id" in package.matched_columns

