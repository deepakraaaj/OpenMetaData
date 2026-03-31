from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

import httpx

from app.core.logging import get_logger
from app.core.settings import Settings
from app.models.common import DatabaseType
from app.models.source import DiscoveredSource
from app.utils.files import ensure_dir
from app.utils.serialization import write_yaml


LOGGER = get_logger(__name__)


class OpenMetadataService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def healthcheck(self) -> bool:
        try:
            response = httpx.get(self.settings.openmetadata_health_url, timeout=5.0)
            return response.status_code < 500
        except httpx.HTTPError:
            return False

    def prepare_source_config(self, source: DiscoveredSource, output_dir: Path) -> Path:
        ensure_dir(output_dir)
        config = self._ingestion_config(source)
        path = output_dir / f"{source.name}.metadata.yaml"
        write_yaml(path, config)
        return path

    def run_ingestion(self, config_path: Path) -> subprocess.CompletedProcess[str] | None:
        binary = shutil.which(self.settings.openmetadata_ingestion_bin)
        if not binary:
            LOGGER.warning("OpenMetadata ingestion binary `%s` was not found.", self.settings.openmetadata_ingestion_bin)
            return None
        return subprocess.run(
            [binary, "ingest", "-c", str(config_path)],
            capture_output=True,
            check=False,
            text=True,
        )

    def prepare_all(self, sources: list[DiscoveredSource], output_dir: Path) -> list[Path]:
        ensure_dir(output_dir)
        return [self.prepare_source_config(source, output_dir) for source in sources]

    def _ingestion_config(self, source: DiscoveredSource) -> dict[str, Any]:
        service_name = f"{self.settings.openmetadata_service_prefix}_{source.name}"
        source_type = self._connector_type(source.connection.type)
        service_connection = self._service_connection(source)
        return {
            "source": {
                "type": source_type,
                "serviceName": service_name,
                "serviceConnection": {"config": service_connection},
                "sourceConfig": {
                    "config": {
                        "type": "DatabaseMetadata",
                        "schemaFilterPattern": {
                            "includes": [source.connection.database] if source.connection.database else [".*"]
                        },
                        "markDeletedTables": False,
                        "includeTables": True,
                        "includeViews": False,
                    }
                },
            },
            "sink": {
                "type": "metadata-rest",
                "config": {},
            },
            "workflowConfig": {
                "openMetadataServerConfig": {
                    "hostPort": self.settings.openmetadata_host,
                    "authProvider": "openmetadata",
                    "securityConfig": (
                        {"jwtToken": self.settings.openmetadata_jwt_token}
                        if self.settings.openmetadata_jwt_token
                        else {}
                    ),
                }
            },
        }

    def _connector_type(self, db_type: DatabaseType) -> str:
        mapping = {
            DatabaseType.mysql: "mysql",
            DatabaseType.sqlite: "sqlite",
            DatabaseType.postgresql: "postgres",
        }
        return mapping.get(db_type, db_type.value)

    def _service_connection(self, source: DiscoveredSource) -> dict[str, Any]:
        connection = source.connection
        if connection.type == DatabaseType.mysql:
            return {
                "type": "MySQL",
                "username": connection.username,
                "password": connection.password,
                "hostPort": f"{connection.host or 'localhost'}:{connection.port or 3306}",
                "databaseSchema": connection.database,
                "scheme": "mysql+pymysql",
                "connectionOptions": connection.options,
                "supportsMetadataExtraction": True,
                "sslConfig": None,
            }
        if connection.type == DatabaseType.sqlite:
            return {
                "type": "SQLite",
                "databaseMode": "file",
                "database": connection.file_path,
            }
        if connection.type == DatabaseType.postgresql:
            return {
                "type": "Postgres",
                "username": connection.username,
                "password": connection.password,
                "hostPort": f"{connection.host or 'localhost'}:{connection.port or 5432}",
                "database": connection.database,
                "scheme": "postgresql+psycopg",
            }
        return {
            "type": connection.type.value,
            "connectionString": connection.url,
        }
