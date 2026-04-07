from __future__ import annotations

from app.discovery.service import build_source_name, parse_connection_url
from app.models.common import DatabaseType
from app.models.source import DiscoveredSource
from app.models.technical import SourceTechnicalMetadata
from app.onboard.introspection import DatabaseIntrospector


class IntrospectionService:
    def __init__(
        self,
        connection_url: str,
        source_name: str = "default_source",
        *,
        allow_tables: list[str] | None = None,
        schema_name: str | None = None,
    ):
        self.connection_url = connection_url
        self.source_name = source_name
        self.allow_tables = [item for item in (allow_tables or []) if str(item).strip()]
        self.schema_name = str(schema_name or "").strip() or None
        self.introspector = DatabaseIntrospector()

    def introspect(self) -> SourceTechnicalMetadata:
        connection = parse_connection_url(self.connection_url)
        if connection.type == DatabaseType.unknown:
            return SourceTechnicalMetadata(
                source_name=self.source_name,
                db_type=DatabaseType.unknown,
                connectivity_ok=False,
                connectivity_notes=["Unsupported or invalid database URL."],
            )
        if self.schema_name:
            connection.schema_name = self.schema_name
        resolved_name = str(self.source_name or "").strip() or build_source_name(connection)
        source = DiscoveredSource(
            name=resolved_name,
            connection=connection,
            description="Deterministic schema introspection",
            allow_tables=self.allow_tables,
            approved_use_cases=["deterministic_introspection"],
        )
        return self.introspector.introspect_source(source)
