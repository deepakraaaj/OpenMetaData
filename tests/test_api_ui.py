from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.api import main as api_main
from app.models.common import DatabaseType
from app.models.source import DiscoveredSource, SourceConnection
from app.models.technical import ColumnProfile, SchemaProfile, SourceTechnicalMetadata, TableProfile
from app.repositories.filesystem import WorkspaceRepository


def _seed_technical_source(repository: WorkspaceRepository, source_name: str) -> None:
    repository.upsert_discovered_source(
        DiscoveredSource(
            name=source_name,
            connection=SourceConnection(type=DatabaseType.sqlite, database="demo"),
            description="Phase 1 technical source",
        )
    )
    repository.save_technical_metadata(
        SourceTechnicalMetadata(
            source_name=source_name,
            db_type=DatabaseType.sqlite,
            database_name="demo",
            connectivity_ok=True,
            connectivity_notes=["Connection test succeeded."],
            source_summary={"schema_count": 1, "table_count": 1, "column_count": 3},
            schemas=[
                SchemaProfile(
                    schema_name="main",
                    tables=[
                        TableProfile(
                            schema_name="main",
                            table_name="tickets",
                            estimated_row_count=12,
                            primary_key=["id"],
                            timestamp_columns=["created_at"],
                            status_columns=["status"],
                            columns=[
                                ColumnProfile(name="id", data_type="INTEGER", is_primary_key=True),
                                ColumnProfile(name="status", data_type="TEXT", enum_values=["OPEN", "DONE"]),
                                ColumnProfile(name="created_at", data_type="TEXT", is_timestamp_like=True),
                            ],
                        )
                    ],
                )
            ],
        )
    )


def test_index_page_renders_phase_one_form_and_technical_link(tmp_path: Path, monkeypatch) -> None:
    repository = WorkspaceRepository(tmp_path / "config", tmp_path / "output")
    _seed_technical_source(repository, "phase1_ui_source")
    monkeypatch.setattr(api_main, "repository", repository)

    client = TestClient(api_main.app)
    response = client.get("/")

    assert response.status_code == 200
    assert "Run Deterministic Introspection" in response.text
    assert "/technical/phase1_ui_source" in response.text
    assert "Technical Snapshot" in response.text


def test_technical_snapshot_page_renders_saved_phase_one_artifacts(tmp_path: Path, monkeypatch) -> None:
    repository = WorkspaceRepository(tmp_path / "config", tmp_path / "output")
    _seed_technical_source(repository, "phase1_ui_source")
    monkeypatch.setattr(api_main, "repository", repository)

    client = TestClient(api_main.app)
    response = client.get("/technical/phase1_ui_source")

    assert response.status_code == 200
    assert "Phase 1 Deterministic Core" in response.text
    assert "tickets" in response.text
    assert "Download JSON Bundle" in response.text
