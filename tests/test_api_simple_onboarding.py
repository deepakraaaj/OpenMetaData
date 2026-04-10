from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.api import main as api_main
from app.repositories.filesystem import WorkspaceRepository


def _create_demo_db(db_path: Path) -> None:
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE person (id INTEGER PRIMARY KEY, first_name TEXT, last_name TEXT)"))
        conn.execute(text("CREATE TABLE site (id INTEGER PRIMARY KEY, name TEXT, city TEXT)"))
        conn.execute(
            text(
                """
                CREATE TABLE task_transaction (
                    id INTEGER PRIMARY KEY,
                    title TEXT,
                    status TEXT,
                    priority TEXT,
                    scheduled_date TEXT,
                    assignee_id INTEGER,
                    site_id INTEGER,
                    FOREIGN KEY(assignee_id) REFERENCES person(id),
                    FOREIGN KEY(site_id) REFERENCES site(id)
                )
                """
            )
        )
        conn.execute(text("CREATE TABLE task_status (id INTEGER PRIMARY KEY, name TEXT, display_order INTEGER)"))
        conn.execute(text("CREATE TABLE audit_log (id INTEGER PRIMARY KEY, message TEXT)"))


def test_simple_onboarding_endpoint_returns_minimal_artifact_and_persists_files(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_dir = tmp_path / "config"
    output_dir = tmp_path / "output"
    repository = WorkspaceRepository(config_dir, output_dir)

    db_path = tmp_path / "simple.sqlite"
    _create_demo_db(db_path)

    monkeypatch.setattr(api_main, "repository", repository)
    client = TestClient(api_main.app)

    response = client.post(
        "/api/onboarding/simple",
        json={
            "db_url": f"sqlite:///{db_path}",
            "source_name": "simple_demo",
            "business_context": "field service onboarding",
            "selection_mode": "review",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_name"] == "simple_demo"
    assert payload["total_tables"] == 5
    assert "task_transaction" in payload["selected_tables"]
    assert "audit_log" in payload["ignored_tables"]
    assert payload["artifact"]["business_context"] == "field service onboarding"
    assert payload["artifact"]["table_descriptions"]["task_transaction"].startswith("Tracks task transaction records")
    assert any(
        relationship["from_table"] == "task_transaction" and relationship["to_table"] == "person"
        for relationship in payload["artifact"]["relationships"]
    )

    artifact_path = Path(payload["artifact_path"])
    assert artifact_path.exists()
    written_artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert written_artifact["selected_tables"] == payload["artifact"]["selected_tables"]
    assert (repository.source_dir("simple_demo") / "technical_metadata.json").exists()
    assert (config_dir / "discovered_sources.json").exists()


def test_simple_onboarding_endpoint_rejects_invalid_url(tmp_path: Path, monkeypatch) -> None:
    repository = WorkspaceRepository(tmp_path / "config", tmp_path / "output")
    monkeypatch.setattr(api_main, "repository", repository)
    client = TestClient(api_main.app)

    response = client.post(
        "/api/onboarding/simple",
        json={
            "db_url": "not-a-valid-url",
        },
    )

    assert response.status_code == 400
    assert "invalid database url" in response.json()["detail"].lower() or "unsupported" in response.json()["detail"].lower()
