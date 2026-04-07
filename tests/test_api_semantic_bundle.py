from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import zipfile

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.api import main as api_main
from app.api.semantic_bundle_questions import build_semantic_bundle_questions
from app.artifacts.semantic_bundle import SEMANTIC_BUNDLE_DIRNAME
from app.models.common import DatabaseType
from app.models.questionnaire import QuestionnaireBundle
from app.models.semantic import QueryPattern, SemanticSourceModel, SemanticTable
from app.models.technical import ColumnProfile, SchemaProfile, SourceTechnicalMetadata, TableProfile
from app.repositories.filesystem import WorkspaceRepository


def _seed_source(repository: WorkspaceRepository, source_name: str) -> None:
    repository.save_technical_metadata(
        SourceTechnicalMetadata(
            source_name=source_name,
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
                            columns=[
                                ColumnProfile(name="id", data_type="INTEGER"),
                                ColumnProfile(name="company_id", data_type="INTEGER"),
                            ],
                            primary_key=["id"],
                        )
                    ],
                )
            ],
        )
    )
    repository.save_semantic_model(
        SemanticSourceModel(
            source_name=source_name,
            db_type="mysql",
            domain="warehouse_ops",
            description="warehouse operations",
            key_entities=["work order"],
            tables=[
                SemanticTable(
                    table_name="task_transaction",
                    business_meaning="Operational work orders.",
                    likely_entity="work order",
                    important_columns=["id", "company_id"],
                )
            ],
            query_patterns=[
                QueryPattern(
                    intent="work_order_list",
                    question_examples=["show work orders"],
                    preferred_tables=["task_transaction"],
                )
            ],
        )
    )
    repository.save_questionnaire(QuestionnaireBundle(source_name=source_name, questions=[]))


def test_semantic_bundle_api_rebuild_and_publish(tmp_path: Path, monkeypatch) -> None:
    config_dir = tmp_path / "config"
    output_dir = tmp_path / "output"
    tag_domains_dir = tmp_path / "tag-domains"
    repository = WorkspaceRepository(config_dir, output_dir)
    _seed_source(repository, "warehouse_source")

    monkeypatch.setattr(api_main, "repository", repository)
    monkeypatch.setattr(
        api_main,
        "settings",
        SimpleNamespace(
            admin_origins=["http://localhost:3000"],
            tag_domains_dir=tag_domains_dir,
        ),
    )

    client = TestClient(api_main.app)

    rebuild = client.post("/api/sources/warehouse_source/semantic-bundle/rebuild")
    assert rebuild.status_code == 200
    assert (output_dir / "warehouse_source" / SEMANTIC_BUNDLE_DIRNAME / "schema_context.json").exists()

    questions = client.get("/api/sources/warehouse_source/semantic-bundle/questions")
    assert questions.status_code == 200
    payload = questions.json()
    assert payload["sections"]

    publish = client.post(
        "/api/sources/warehouse_source/semantic-bundle/publish",
        json={"domain_name": "warehouse_ops"},
    )
    assert publish.status_code == 200
    assert (tag_domains_dir / "warehouse_ops" / SEMANTIC_BUNDLE_DIRNAME / "schema_context.json").exists()


def test_url_onboarding_endpoint_processes_db_url_and_returns_zip(tmp_path: Path, monkeypatch) -> None:
    config_dir = tmp_path / "config"
    output_dir = tmp_path / "output"
    tag_domains_dir = tmp_path / "tag-domains"
    repository = WorkspaceRepository(config_dir, output_dir)

    db_path = tmp_path / "sample.sqlite"
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE task_transaction (id INTEGER PRIMARY KEY, company_id INTEGER, status TEXT)"))
        conn.execute(text("INSERT INTO task_transaction (company_id, status) VALUES (1, 'open')"))

    monkeypatch.setattr(api_main, "repository", repository)
    monkeypatch.setattr(
        api_main,
        "settings",
        SimpleNamespace(
            admin_origins=["http://localhost:3000"],
            tag_domains_dir=tag_domains_dir,
            config_dir=config_dir,
            output_dir=output_dir,
            openmetadata_enable_sync=False,
        ),
    )

    client = TestClient(api_main.app)
    onboard = client.post(
        "/api/onboarding/url",
        json={
            "db_url": f"sqlite:///{db_path}",
            "source_name": "warehouse_direct",
            "domain_name": "warehouse_ops",
            "description": "direct sqlite onboarding",
        },
    )

    assert onboard.status_code == 200
    payload = onboard.json()
    assert payload["source_name"] == "warehouse_direct"
    assert (output_dir / "warehouse_direct" / SEMANTIC_BUNDLE_DIRNAME / "schema_context.json").exists()

    bundle_questions = client.get("/api/sources/warehouse_direct/semantic-bundle/questions")
    assert bundle_questions.status_code == 200
    assert bundle_questions.json()["sections"]

    zip_response = client.get("/api/sources/warehouse_direct/json-zip")
    assert zip_response.status_code == 200
    archive_path = tmp_path / "warehouse_direct_json_bundle.zip"
    archive_path.write_bytes(zip_response.content)
    with zipfile.ZipFile(archive_path, "r") as archive:
        names = set(archive.namelist())
        assert "semantic_bundle/schema_context.json" in names
        assert "technical_metadata.json" in names
        assert "tables.json" in names
        assert "relationships.json" in names


def test_url_onboarding_rejects_empty_schema(tmp_path: Path, monkeypatch) -> None:
    config_dir = tmp_path / "config"
    output_dir = tmp_path / "output"
    tag_domains_dir = tmp_path / "tag-domains"
    repository = WorkspaceRepository(config_dir, output_dir)

    db_path = tmp_path / "empty.sqlite"
    create_engine(f"sqlite:///{db_path}").dispose()

    monkeypatch.setattr(api_main, "repository", repository)
    monkeypatch.setattr(
        api_main,
        "settings",
        SimpleNamespace(
            admin_origins=["http://localhost:3000"],
            tag_domains_dir=tag_domains_dir,
            config_dir=config_dir,
            output_dir=output_dir,
            openmetadata_enable_sync=False,
        ),
    )

    client = TestClient(api_main.app)
    response = client.post(
        "/api/onboarding/url",
        json={
            "db_url": f"sqlite:///{db_path}",
            "source_name": "empty_direct",
        },
    )

    assert response.status_code == 422
    assert "No tables were discovered" in response.text


def test_api_allows_private_network_dev_origin_for_cors_preflight() -> None:
    client = TestClient(api_main.app)
    response = client.options(
        "/api/onboarding/url",
        headers={
            "Origin": "http://192.168.15.49:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://192.168.15.49:3000"


def test_question_builder_filters_junk_enum_questions_and_binds_answers() -> None:
    sections = build_semantic_bundle_questions(
        {
            "schema_context.json": {
                "source_name": "demo",
                "database": {"db_type": "sqlite"},
                "tables": [
                    {
                        "table_name": "dispatches",
                        "description": "Dispatch records",
                        "estimated_row_count": 7,
                        "tenant_scope_candidates": ["company_id"],
                    },
                    {
                        "table_name": "technicians",
                        "description": "Users handling dispatches",
                        "estimated_row_count": 2,
                        "tenant_scope_candidates": [],
                    },
                ],
            },
            "business_semantics.json": {
                "scope": "dispatch management",
                "key_entities": ["dispatch"],
                "glossary": [],
                "unresolved_questions": [
                    {
                        "type": "chatbot_exposure",
                        "question": "Should `dispatches` be exposed to chatbot workflows?",
                        "table": "dispatches",
                        "suggested_answer": "review",
                        "answer": None,
                    }
                ],
            },
            "relationship_map.json": {"review_questions": []},
            "enum_dictionary.json": {
                "entries": [
                    {
                        "table_name": "dispatches",
                        "column_name": "id",
                        "business_meaning": "Identifier",
                        "enum_values": ["1", "2"],
                        "sample_values": ["1", "2"],
                        "status_like": False,
                    },
                    {
                        "table_name": "dispatches",
                        "column_name": "status",
                        "business_meaning": "Workflow status",
                        "enum_values": ["pending", "completed"],
                        "sample_values": ["pending", "completed"],
                        "status_like": True,
                    },
                ]
            },
            "query_patterns.json": {
                "patterns": [],
                "review_hints": [
                    {
                        "question": "What does `dispatches` represent in business language?",
                        "table": "dispatches",
                        "column": None,
                        "suggested_answer": "Operational dispatch records",
                        "answer": None,
                    }
                ],
            },
        }
    )

    section_map = {section["id"]: section for section in sections}
    business_rules = section_map["business-rules"]["questions"]
    assert business_rules[0]["field_path"] == ["unresolved_questions", 0, "answer"]
    assert business_rules[0]["kind"] == "select"

    review_hints = section_map["review-hints"]["questions"]
    assert review_hints[0]["field_path"] == ["review_hints", 0, "answer"]

    enum_questions = section_map["enum-meaning"]["questions"]
    labels = {question["label"] for question in enum_questions}
    assert "What should `dispatches.status` values mean?" in labels
    assert "What should `dispatches.id` values mean?" not in labels
