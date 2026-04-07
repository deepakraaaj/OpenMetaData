from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.api import main as api_main
from app.repositories.filesystem import WorkspaceRepository


def _create_demo_db(db_path: Path) -> None:
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE sites (id INTEGER PRIMARY KEY, name TEXT NOT NULL)"))
        conn.execute(
            text(
                """
                CREATE TABLE tickets (
                    id INTEGER PRIMARY KEY,
                    site_id INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT,
                    FOREIGN KEY(site_id) REFERENCES sites(id)
                )
                """
            )
        )
        conn.execute(text("INSERT INTO sites (name) VALUES ('North Depot')"))
        conn.execute(text("INSERT INTO tickets (site_id, status, created_at) VALUES (1, 'OPEN', '2026-04-07T10:00:00')"))


def test_api_lists_env_presets_and_runs_phase_one_introspection_from_env(tmp_path: Path, monkeypatch) -> None:
    config_dir = tmp_path / "config"
    output_dir = tmp_path / "output"
    repository = WorkspaceRepository(config_dir, output_dir)

    env_dir = tmp_path / "env"
    env_dir.mkdir(parents=True, exist_ok=True)
    db_path = env_dir / "demo.sqlite"
    _create_demo_db(db_path)
    env_file = env_dir / "demo.env"
    env_file.write_text("DEMO_DATABASE_URL=sqlite:///demo.sqlite\n", encoding="utf-8")

    monkeypatch.setattr(api_main, "repository", repository)
    client = TestClient(api_main.app)

    presets = client.get("/api/introspection/env/presets", params={"env_file": str(env_file)})
    assert presets.status_code == 200
    payload = presets.json()
    assert payload["env_file"] == str(env_file.resolve())
    assert payload["presets"][0]["env_key"] == "DEMO_DATABASE_URL"
    assert payload["presets"][0]["db_type"] == "sqlite"

    response = client.post(
        "/api/introspection/env",
        json={
            "env_key": "DEMO_DATABASE_URL",
            "env_file": str(env_file),
            "source_name": "demo_env_source",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["phase"] == "phase_1_deterministic_core"
    assert "tables.json" in body["artifacts"]
    assert "relationships.json" in body["artifacts"]

    source_dir = repository.source_dir("demo_env_source")
    assert (source_dir / "technical_metadata.json").exists()
    assert (source_dir / "tables.json").exists()
    assert (source_dir / "columns.json").exists()
    assert (source_dir / "profiling.json").exists()


def test_api_runs_phase_one_introspection_from_raw_url(tmp_path: Path, monkeypatch) -> None:
    config_dir = tmp_path / "config"
    output_dir = tmp_path / "output"
    repository = WorkspaceRepository(config_dir, output_dir)

    db_path = tmp_path / "direct.sqlite"
    _create_demo_db(db_path)

    monkeypatch.setattr(api_main, "repository", repository)
    client = TestClient(api_main.app)

    response = client.post(
        "/api/introspection/url",
        json={
            "db_url": f"sqlite:///{db_path}",
            "source_name": "direct_phase1",
            "allow_tables": ["sites", "tickets"],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["source"]["mode"] == "url"
    assert body["summary"]["table_count"] == 2
    assert "enum_candidates.json" in body["artifacts"]

    source_dir = repository.source_dir("direct_phase1")
    assert (source_dir / "relationships.json").exists()
