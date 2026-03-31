from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, computed_field

from app.models.common import DatabaseType


class SourceEvidence(BaseModel):
    kind: str
    path: str | None = None
    line_number: int | None = None
    snippet: str | None = None
    note: str | None = None


class SourceConnection(BaseModel):
    type: DatabaseType
    url: str | None = None
    host: str | None = None
    port: int | None = None
    database: str | None = None
    username: str | None = None
    password: str | None = None
    schema_name: str | None = None
    file_path: str | None = None
    unix_socket: str | None = None
    options: dict[str, Any] = Field(default_factory=dict)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def resolved_database(self) -> str | None:
        return self.database or self.schema_name


class DiscoveredSource(BaseModel):
    name: str
    connection: SourceConnection
    description: str | None = None
    evidence: list[SourceEvidence] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    allow_tables: list[str] = Field(default_factory=list)
    protected_tables: list[str] = Field(default_factory=list)
    approved_use_cases: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    is_active: bool = True

    @computed_field  # type: ignore[prop-decorator]
    @property
    def output_slug(self) -> str:
        return self.name.lower().replace(" ", "_")


class DiscoveryReport(BaseModel):
    generated_at: str
    roots_scanned: list[str]
    discovered_sources: list[DiscoveredSource] = Field(default_factory=list)
    missing_connection_templates: list[dict[str, Any]] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)


class SourceConfigFile(BaseModel):
    sources: list[DiscoveredSource] = Field(default_factory=list)

    @classmethod
    def from_paths(cls, paths: list[Path]) -> "SourceConfigFile":
        from app.utils.serialization import read_json, read_yaml

        merged: list[DiscoveredSource] = []
        for path in paths:
            data = read_json(path) if path.suffix == ".json" else read_yaml(path)
            payload = data.get("sources") or data.get("discovered_sources") or data
            merged.extend(DiscoveredSource.model_validate(item) for item in payload)
        return cls(sources=merged)
