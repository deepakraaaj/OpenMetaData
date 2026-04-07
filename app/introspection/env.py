from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

from app.discovery.service import build_source_name, parse_connection_url
from app.models.common import DatabaseType
from app.services.database import normalize_sqlalchemy_url, redacted_url
from app.utils.text import normalized_name


WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_TAG_ENV_FILE = WORKSPACE_ROOT / "TAG-Implementation" / ".env"
DEFAULT_LOCAL_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
DATABASE_URL_SUFFIXES = ("DATABASE_URL", "DB_URL", "SQLALCHEMY_DATABASE_URI", "JDBC_URL")


@dataclass(frozen=True)
class DatabaseUrlPreset:
    env_key: str
    env_file: Path
    url: str
    url_redacted: str
    db_type: DatabaseType
    database_name: str | None
    source_name_hint: str

    def to_dict(self) -> dict[str, str | None]:
        return {
            "env_key": self.env_key,
            "env_file": str(self.env_file),
            "url_redacted": self.url_redacted,
            "db_type": self.db_type.value,
            "database_name": self.database_name,
            "source_name_hint": self.source_name_hint,
        }


def resolve_env_file(env_file: str | Path | None = None) -> Path:
    if env_file is not None and str(env_file).strip():
        path = Path(str(env_file)).expanduser().resolve()
    elif DEFAULT_TAG_ENV_FILE.exists():
        path = DEFAULT_TAG_ENV_FILE
    else:
        path = DEFAULT_LOCAL_ENV_FILE.resolve()
    if not path.exists():
        raise FileNotFoundError(path)
    return path


def list_database_url_presets(env_file: str | Path | None = None) -> list[DatabaseUrlPreset]:
    path = resolve_env_file(env_file)
    values = dotenv_values(path)
    presets: list[DatabaseUrlPreset] = []
    for key, raw_value in values.items():
        if not _is_database_url_key(key):
            continue
        value = str(raw_value or "").strip()
        if not value:
            continue
        connection = parse_connection_url(value, relative_to=path.parent)
        if connection.type == DatabaseType.unknown:
            continue
        presets.append(
            DatabaseUrlPreset(
                env_key=key,
                env_file=path,
                url=normalize_sqlalchemy_url(connection),
                url_redacted=redacted_url(connection) or value,
                db_type=connection.type,
                database_name=connection.resolved_database,
                source_name_hint=_source_name_hint(key, connection),
            )
        )
    presets.sort(key=lambda item: item.env_key)
    return presets


def load_database_url_preset(env_key: str, env_file: str | Path | None = None) -> DatabaseUrlPreset:
    target_key = str(env_key or "").strip()
    if not target_key:
        raise KeyError("env_key is required")
    for preset in list_database_url_presets(env_file):
        if preset.env_key == target_key:
            return preset
    raise KeyError(target_key)


def _is_database_url_key(key: str | None) -> bool:
    text = str(key or "").strip()
    if not text or text.startswith("OPENMETADATA_"):
        return False
    return any(text.endswith(suffix) for suffix in DATABASE_URL_SUFFIXES)


def _source_name_hint(env_key: str, connection) -> str:
    key_name = str(env_key or "").strip().upper()
    for suffix in DATABASE_URL_SUFFIXES:
        if key_name.endswith(suffix):
            base = key_name[: -len(suffix)].strip("_")
            if base:
                return normalized_name(base)
            break
    return build_source_name(connection)
