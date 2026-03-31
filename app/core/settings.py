from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = Field(default="development", alias="APP_ENV")
    app_name: str = Field(default="openmetadata-semantic-onboarding", alias="APP_NAME")
    app_host: str = Field(default="127.0.0.1", alias="APP_HOST")
    app_port: int = Field(default=8088, alias="APP_PORT")
    workspace_root: Path = Field(default=Path("."), alias="WORKSPACE_ROOT")
    config_dir: Path = Field(default=Path("./config"), alias="CONFIG_DIR")
    output_dir: Path = Field(default=Path("./output"), alias="OUTPUT_DIR")
    app_metadata_database_url: str = Field(
        default="sqlite+pysqlite:///./output/app_metadata.db",
        alias="APP_METADATA_DATABASE_URL",
    )

    openmetadata_host: str = Field(default="http://127.0.0.1:8585/api", alias="OPENMETADATA_HOST")
    openmetadata_health_url: str = Field(
        default="http://127.0.0.1:8585",
        alias="OPENMETADATA_HEALTH_URL",
    )
    openmetadata_jwt_token: str | None = Field(default=None, alias="OPENMETADATA_JWT_TOKEN")
    openmetadata_ingestion_bin: str = Field(default="metadata", alias="OPENMETADATA_INGESTION_BIN")
    openmetadata_version: str = Field(default="1.12.0", alias="OPENMETADATA_VERSION")
    openmetadata_service_prefix: str = Field(default="local", alias="OPENMETADATA_SERVICE_PREFIX")
    openmetadata_enable_sync: bool = Field(default=False, alias="OPENMETADATA_ENABLE_SYNC")

    discovery_scan_roots: str = Field(
        default="/home/user/Desktop,/home/user/Downloads,/home/user/Work",
        alias="DISCOVERY_SCAN_ROOTS",
    )
    discovery_include_home: bool = Field(default=True, alias="DISCOVERY_INCLUDE_HOME")
    discovery_max_file_bytes: int = Field(default=524_288, alias="DISCOVERY_MAX_FILE_BYTES")
    discovery_skip_dirs: str = Field(
        default=".git,node_modules,.venv,venv,dist,build,target,.cache,.cargo,site-packages",
        alias="DISCOVERY_SKIP_DIRS",
    )

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def repo_root(self) -> Path:
        return self.workspace_root.resolve()

    @property
    def discovered_sources_path(self) -> Path:
        return self.config_dir / "discovered_sources.json"

    @property
    def question_schema_path(self) -> Path:
        return self.config_dir / "questionnaire.schema.json"

    @property
    def scan_roots(self) -> list[Path]:
        values = [part.strip() for part in self.discovery_scan_roots.split(",") if part.strip()]
        return [Path(value).expanduser() for value in values]

    @property
    def skip_dirs(self) -> set[str]:
        return {part.strip() for part in self.discovery_skip_dirs.split(",") if part.strip()}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
