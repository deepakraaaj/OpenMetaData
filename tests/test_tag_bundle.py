from __future__ import annotations

from pathlib import Path

from app.artifacts.tag_bundle import TagBundleExporter
from app.models.artifacts import LLMContextPackage
from app.models.common import DatabaseType
from app.models.questionnaire import QuestionnaireBundle, QuestionnaireQuestion
from app.models.semantic import GlossaryTerm, QueryPattern, SemanticColumn, SemanticSourceModel, SemanticTable
from app.models.technical import ColumnProfile, ForeignKeyProfile, SchemaProfile, SourceTechnicalMetadata, TableProfile


def test_tag_bundle_exporter_writes_safe_overlay(tmp_path: Path) -> None:
    source_dir = tmp_path / "fits_dev_march_9"
    source_dir.mkdir(parents=True)
    (source_dir / "llm_context_package.json").write_text('{"notes_for_llm":["Prefer approved joins."]}', encoding="utf-8")
    (source_dir / "normalized_metadata.json").write_text("{}", encoding="utf-8")
    (source_dir / "semantic_model.json").write_text("{}", encoding="utf-8")
    (source_dir / "technical_metadata.json").write_text("{}", encoding="utf-8")
    (source_dir / "questionnaire.json").write_text("{}", encoding="utf-8")

    semantic = SemanticSourceModel(
        source_name="fits_dev_march_9",
        db_type="mysql",
        domain="maintenance",
        description="maintenance operations",
        key_entities=["Task Transaction", "Facility"],
        tables=[
            SemanticTable(
                table_name="task_transaction",
                business_meaning="Task records.",
                likely_entity="Task Transaction",
                important_columns=["id", "status"],
                common_business_questions=["Show pending tasks"],
                columns=[
                    SemanticColumn(
                        column_name="id",
                        technical_type="INTEGER",
                        business_meaning="Task id.",
                    ),
                    SemanticColumn(
                        column_name="status",
                        technical_type="INTEGER",
                        business_meaning="Task status.",
                    ),
                ],
            )
        ],
        glossary=[GlossaryTerm(term="backlog", meaning="Open tasks not yet completed")],
        query_patterns=[
            QueryPattern(intent="task list", question_examples=["Show pending tasks"]),
        ],
    )
    technical = SourceTechnicalMetadata(
        source_name="fits_dev_march_9",
        db_type=DatabaseType.mysql,
        schemas=[
            SchemaProfile(
                schema_name="fits_dev_march_9",
                tables=[
                    TableProfile(
                        schema_name="fits_dev_march_9",
                        table_name="task_transaction",
                        columns=[
                            ColumnProfile(name="id", data_type="INTEGER"),
                            ColumnProfile(name="status", data_type="INTEGER"),
                            ColumnProfile(name="facility_id", data_type="INTEGER"),
                        ],
                        primary_key=["id"],
                        foreign_keys=[
                            ForeignKeyProfile(
                                referred_table="facility",
                                constrained_columns=["facility_id"],
                                referred_columns=["id"],
                            )
                        ],
                    )
                ],
            )
        ],
    )
    questionnaire = QuestionnaireBundle(
        source_name="fits_dev_march_9",
        questions=[
            QuestionnaireQuestion(
                type="relationship_validation",
                question="Is task_transaction.facility_id = facility.id valid?",
                left_table="task_transaction",
                right_table="facility",
            )
        ],
    )

    bundle_dir = TagBundleExporter().export(
        semantic=semantic,
        technical=technical,
        questionnaire=questionnaire,
        source_output_dir=source_dir,
        domain_name="maintenance",
    )

    assert (bundle_dir / "generated" / "capabilities.json").exists()
    assert (bundle_dir / "generated" / "domain_knowledge.json").exists()
    assert (bundle_dir / "review" / "manifest.tables.review.json").exists()
    assert (bundle_dir / "openmetadata_exports" / "semantic_model.json").exists()
    assert "generated/capabilities.json" in (bundle_dir / "bundle_manifest.json").read_text(encoding="utf-8")
