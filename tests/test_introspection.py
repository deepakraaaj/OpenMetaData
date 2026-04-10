from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import create_engine, text

from app.introspection.serializer import IntrospectionSerializer
from app.introspection.service import IntrospectionService
from app.models.common import DatabaseType
from app.models.source import DiscoveredSource, SourceConnection
from app.onboard.introspection import DatabaseIntrospector
from app.repositories.filesystem import WorkspaceRepository


class _FakeInspector:
    default_schema_name = "public"

    def get_schema_names(self) -> list[str]:
        return ["information_schema", "pg_catalog", "public", "custom_reporting"]


def test_database_introspector_prefers_explicit_or_default_schema_scope() -> None:
    introspector = DatabaseIntrospector()
    source = DiscoveredSource(
        name="analytics",
        connection=SourceConnection(type=DatabaseType.postgresql, database="analytics"),
    )

    assert introspector._schema_names(_FakeInspector(), source) == ["public"]

    source.connection.schema_name = "custom_reporting"
    assert introspector._schema_names(_FakeInspector(), source) == ["custom_reporting"]


def test_database_introspector_status_like_is_conservative() -> None:
    introspector = DatabaseIntrospector()

    assert introspector._is_status_like("status", "TEXT", ["OPEN", "DONE"]) is True
    assert introspector._is_status_like("approval_bucket", "ENUM('new','done')", ["new", "done"]) is True
    assert introspector._is_status_like("gps_fix", "INTEGER", ["0", "1"]) is False


def test_introspection_service_and_serializer_generate_phase_one_artifacts(tmp_path: Path) -> None:
    db_path = tmp_path / "phase1.sqlite"
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE sites (id INTEGER PRIMARY KEY, name TEXT NOT NULL)"))
        conn.execute(
            text(
                """
                CREATE TABLE work_orders (
                    id INTEGER PRIMARY KEY,
                    site_id INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    priority TEXT,
                    gps_fix INTEGER,
                    created_at TEXT,
                    FOREIGN KEY(site_id) REFERENCES sites(id)
                )
                """
            )
        )
        conn.execute(text("CREATE TABLE audit_log (id INTEGER PRIMARY KEY, event_type TEXT NOT NULL)"))
        conn.execute(text("INSERT INTO sites (name) VALUES ('North Depot'), ('South Yard')"))
        conn.execute(
            text(
                """
                INSERT INTO work_orders (site_id, status, priority, gps_fix, created_at)
                VALUES
                    (1, 'OPEN', 'HIGH', 1, '2026-04-07T10:00:00'),
                    (2, 'DONE', 'LOW', 0, '2026-04-07T11:00:00')
                """
            )
        )
        conn.execute(text("INSERT INTO audit_log (event_type) VALUES ('created')"))

    metadata = IntrospectionService(
        connection_url=f"sqlite:///{db_path}",
        source_name="warehouse_ops",
        allow_tables=["sites", "work_orders"],
    ).introspect()

    assert metadata.connectivity_ok is True
    assert metadata.source_summary["table_count"] == 2
    assert {table.table_name for schema in metadata.schemas for table in schema.tables} == {"sites", "work_orders"}

    output_dir = tmp_path / "artifacts"
    IntrospectionSerializer(metadata, output_dir).serialize()

    tables = json.loads((output_dir / "tables.json").read_text(encoding="utf-8"))
    columns = json.loads((output_dir / "columns.json").read_text(encoding="utf-8"))
    relationships = json.loads((output_dir / "relationships.json").read_text(encoding="utf-8"))
    profiling = json.loads((output_dir / "profiling.json").read_text(encoding="utf-8"))
    enum_candidates = json.loads((output_dir / "enum_candidates.json").read_text(encoding="utf-8"))

    assert {entry["table"] for entry in tables} == {"sites", "work_orders"}
    assert any(entry["table"] == "work_orders" and entry["column"] == "status" for entry in enum_candidates)
    assert not any(entry["table"] == "work_orders" and entry["column"] == "gps_fix" for entry in enum_candidates)
    assert any(
        entry["source_table"] == "work_orders"
        and entry["target_table"] == "sites"
        and entry["relationship_type"] == "foreign_key"
        for entry in relationships
    )
    assert any(
        entry["table"] == "work_orders"
        and any(column["column"] == "created_at" and column["is_timestamp_like"] for column in entry["columns"])
        for entry in profiling
    )
    assert any(entry["table"] == "work_orders" and entry["name"] == "status" for entry in columns)
    assert (output_dir / "technical_metadata_bundle.json").exists()


def test_workspace_repository_save_technical_metadata_writes_phase_one_json_slices(tmp_path: Path) -> None:
    db_path = tmp_path / "repo_phase1.sqlite"
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE tasks (id INTEGER PRIMARY KEY, status TEXT NOT NULL)"))
        conn.execute(text("INSERT INTO tasks (status) VALUES ('OPEN'), ('DONE')"))

    metadata = IntrospectionService(
        connection_url=f"sqlite:///{db_path}",
        source_name="repo_source",
    ).introspect()

    repository = WorkspaceRepository(tmp_path / "config", tmp_path / "output")
    repository.save_technical_metadata(metadata)

    source_dir = repository.source_dir("repo_source")
    assert (source_dir / "technical_metadata.json").exists()
    assert (source_dir / "tables.json").exists()
    assert (source_dir / "columns.json").exists()
    assert (source_dir / "relationships.json").exists()
    assert (source_dir / "profiling.json").exists()
    assert (source_dir / "enum_candidates.json").exists()
