from __future__ import annotations

from pathlib import Path

from app.artifacts.semantic_bundle import SEMANTIC_BUNDLE_FILES, SemanticBundleExporter
from app.models.common import DatabaseType
from app.models.questionnaire import QuestionnaireBundle, QuestionnaireQuestion
from app.models.semantic import GlossaryTerm, QueryPattern, SemanticColumn, SemanticSourceModel, SemanticTable
from app.models.technical import ColumnProfile, ForeignKeyProfile, SchemaProfile, SourceTechnicalMetadata, TableProfile


def _semantic() -> SemanticSourceModel:
    return SemanticSourceModel(
        source_name="warehouse_source",
        db_type="mysql",
        domain="warehouse_ops",
        description="warehouse operations",
        key_entities=["work order", "technician"],
        approved_use_cases=["list open work orders"],
        tables=[
            SemanticTable(
                table_name="task_transaction",
                business_meaning="Operational work orders.",
                likely_entity="work order",
                important_columns=["id", "status", "company_id", "assignee_id"],
                valid_joins=["task_transaction.assignee_id = person.id"],
                common_business_questions=["show open work orders"],
                columns=[
                    SemanticColumn(column_name="id", technical_type="INTEGER", business_meaning="work order id"),
                    SemanticColumn(column_name="status", technical_type="INTEGER", business_meaning="work order status"),
                ],
            )
        ],
        glossary=[GlossaryTerm(term="backlog", meaning="open work orders")],
        query_patterns=[
            QueryPattern(
                intent="work_order_list",
                question_examples=["show open work orders"],
                preferred_tables=["task_transaction"],
                safe_filters=["status", "company_id"],
            )
        ],
    )


def _technical() -> SourceTechnicalMetadata:
    return SourceTechnicalMetadata(
        source_name="warehouse_source",
        db_type=DatabaseType.mysql,
        database_name="warehouse",
        connectivity_ok=True,
        schemas=[
            SchemaProfile(
                schema_name="warehouse",
                tables=[
                    TableProfile(
                        schema_name="warehouse",
                        table_name="task_transaction",
                        estimated_row_count=125,
                        columns=[
                            ColumnProfile(name="id", data_type="INTEGER"),
                            ColumnProfile(
                                name="status",
                                data_type="INTEGER",
                                enum_values=["0", "1", "2"],
                                sample_values=["0", "1", "2"],
                                is_status_like=True,
                            ),
                            ColumnProfile(name="company_id", data_type="INTEGER"),
                            ColumnProfile(name="assignee_id", data_type="INTEGER"),
                        ],
                        primary_key=["id"],
                        foreign_keys=[
                            ForeignKeyProfile(
                                referred_table="person",
                                constrained_columns=["assignee_id"],
                                referred_columns=["id"],
                            )
                        ],
                        status_columns=["status"],
                    )
                ],
            )
        ],
    )


def _questionnaire() -> QuestionnaireBundle:
    return QuestionnaireBundle(
        source_name="warehouse_source",
        questions=[
            QuestionnaireQuestion(
                type="relationship_validation",
                question="Is task_transaction.assignee_id = person.id the assignee join?",
                left_table="task_transaction",
                right_table="person",
                suggested_join="task_transaction.assignee_id = person.id",
            ),
            QuestionnaireQuestion(
                type="chatbot_exposure",
                question="Should task_transaction be exposed to chatbot and reporting workflows?",
                table="task_transaction",
                suggested_answer="review",
            ),
            QuestionnaireQuestion(
                type="column_business_meaning",
                question="What does task_transaction.status mean to the business?",
                table="task_transaction",
                column="status",
                suggested_answer="Workflow status for the work order.",
            ),
        ],
    )


def test_semantic_bundle_exporter_writes_all_bundle_files(tmp_path: Path) -> None:
    source_dir = tmp_path / "warehouse_source"
    source_dir.mkdir(parents=True)

    bundle_dir = SemanticBundleExporter().write(
        semantic=_semantic(),
        technical=_technical(),
        questionnaire=_questionnaire(),
        source_output_dir=source_dir,
        domain_name="warehouse_ops",
    )

    for filename in SEMANTIC_BUNDLE_FILES:
        assert (bundle_dir / filename).exists()
    assert (bundle_dir / "bundle_manifest.json").exists()


def test_semantic_bundle_contains_enums_and_patterns() -> None:
    bundle = SemanticBundleExporter().build(
        semantic=_semantic(),
        technical=_technical(),
        questionnaire=_questionnaire(),
        domain_name="warehouse_ops",
    )

    schema = bundle["schema_context.json"]
    business = bundle["business_semantics.json"]
    enums = bundle["enum_dictionary.json"]
    patterns = bundle["query_patterns.json"]

    assert schema["tables"][0]["table_name"] == "task_transaction"
    assert schema["tables"][0]["tenant_scope_candidates"] == ["company_id"]
    assert business["unresolved_questions"][0]["type"] == "chatbot_exposure"
    assert business["unresolved_questions"][0]["answer"] is None
    assert enums["entries"][0]["column_name"] == "status"
    assert patterns["patterns"][0]["intent"] == "work_order_list"
    assert patterns["learned_queries"] == []
    assert patterns["review_hints"][0]["answer"] is None
