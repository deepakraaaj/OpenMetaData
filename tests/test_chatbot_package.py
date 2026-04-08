from __future__ import annotations

from pathlib import Path

from app.artifacts.chatbot_package import ChatbotPackageExporter
from app.artifacts.semantic_bundle import SemanticBundleExporter
from app.artifacts.tag_bundle import TagBundleExporter
from app.models.artifacts import LLMContextPackage
from app.models.common import DatabaseType
from app.models.questionnaire import QuestionnaireBundle, QuestionnaireQuestion
from app.models.semantic import QueryPattern, SemanticColumn, SemanticSourceModel, SemanticTable
from app.models.technical import ColumnProfile, SchemaProfile, SourceTechnicalMetadata, TableProfile


def test_chatbot_package_exporter_writes_visual_runtime_and_review_assets(tmp_path: Path) -> None:
    source_dir = tmp_path / "dispatch_demo"
    source_dir.mkdir(parents=True)
    (source_dir / "normalized_metadata.json").write_text("{}", encoding="utf-8")
    (source_dir / "semantic_model.json").write_text("{}", encoding="utf-8")
    (source_dir / "technical_metadata.json").write_text("{}", encoding="utf-8")
    (source_dir / "questionnaire.json").write_text("{}", encoding="utf-8")
    (source_dir / "llm_context_package.json").write_text("{}", encoding="utf-8")

    semantic = SemanticSourceModel(
        source_name="dispatch_demo",
        db_type="sqlite",
        domain="dispatch_ops",
        description="dispatch tracking data",
        key_entities=["Dispatch", "Technician"],
        tables=[
            SemanticTable(
                table_name="dispatch",
                business_meaning="Dispatch records.",
                likely_entity="Dispatch",
                important_columns=["id", "status", "company_id"],
                common_business_questions=["Show open dispatches"],
                columns=[
                    SemanticColumn(column_name="id", technical_type="INTEGER", business_meaning="Dispatch id."),
                    SemanticColumn(column_name="status", technical_type="TEXT", business_meaning="Dispatch status."),
                ],
            )
        ],
        query_patterns=[
            QueryPattern(
                intent="dispatch_list",
                question_examples=["Show open dispatches"],
                preferred_tables=["dispatch"],
                safe_filters=["status", "company_id"],
            )
        ],
    )
    technical = SourceTechnicalMetadata(
        source_name="dispatch_demo",
        db_type=DatabaseType.sqlite,
        database_name="dispatch_demo",
        connectivity_ok=True,
        schemas=[
            SchemaProfile(
                schema_name="main",
                tables=[
                    TableProfile(
                        schema_name="main",
                        table_name="dispatch",
                        estimated_row_count=42,
                        primary_key=["id"],
                        status_columns=["status"],
                        columns=[
                            ColumnProfile(name="id", data_type="INTEGER", is_primary_key=True),
                            ColumnProfile(name="status", data_type="TEXT", enum_values=["open", "done"]),
                            ColumnProfile(name="company_id", data_type="INTEGER"),
                        ],
                    )
                ],
            )
        ],
    )
    questionnaire = QuestionnaireBundle(
        source_name="dispatch_demo",
        questions=[
            QuestionnaireQuestion(
                type="chatbot_exposure",
                question="Should dispatch be exposed to chatbot workflows?",
                table="dispatch",
                suggested_answer="review",
            ),
            QuestionnaireQuestion(
                type="column_business_meaning",
                question="What does dispatch.status mean?",
                table="dispatch",
                column="status",
                suggested_answer="Operational workflow status.",
            ),
        ],
    )
    context = LLMContextPackage(
        question="What does dispatch_demo contain and how should it be queried safely?",
        domain="dispatch_ops",
        matched_tables=["dispatch"],
        safe_joins=["dispatch.company_id = company.id"],
        notes_for_llm=["Prefer reviewed joins."],
    )

    bundle_dir = SemanticBundleExporter().write(
        semantic=semantic,
        technical=technical,
        questionnaire=questionnaire,
        source_output_dir=source_dir,
        domain_name="dispatch_ops",
    )
    tag_bundle_dir = TagBundleExporter().export(
        semantic=semantic,
        technical=technical,
        questionnaire=questionnaire,
        source_output_dir=source_dir,
        domain_name="dispatch_ops",
    )

    package_dir = ChatbotPackageExporter().export(
        semantic=semantic,
        technical=technical,
        questionnaire=questionnaire,
        context_package=context,
        source_output_dir=source_dir,
        semantic_bundle_dir=bundle_dir,
        tag_bundle_dir=tag_bundle_dir,
        domain_groups={"Dispatch": ["dispatch"]},
        domain_name="dispatch_ops",
    )

    assert (package_dir / "manifest.json").exists()
    assert (package_dir / "visuals" / "overview.html").exists()
    assert (package_dir / "questions" / "semantic_bundle_questions.json").exists()
    assert (package_dir / "runtime" / "llm_context_package.json").exists()
    assert (package_dir / "runtime" / "domain_groups.json").exists()
    assert (package_dir / "semantic_bundle" / "schema_context.json").exists()
    assert (package_dir / "tag_bundle" / "dispatch_ops" / "bundle_manifest.json").exists()

    manifest_text = (package_dir / "manifest.json").read_text(encoding="utf-8")
    overview_text = (package_dir / "visuals" / "overview.html").read_text(encoding="utf-8")
    assert "chatbot_onboarding_package" in manifest_text
    assert "semantic_bundle_questions.json" in manifest_text
    assert "Questions To Ask The User" in overview_text
