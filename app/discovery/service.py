from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Iterable
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlparse

import yaml
from sqlalchemy import create_engine, text

from app.core.logging import get_logger
from app.models.common import DatabaseType
from app.models.source import DiscoveredSource, DiscoveryReport, SourceConnection, SourceEvidence
from app.utils.text import normalized_name, unique_non_empty


LOGGER = get_logger(__name__)

URL_RE = re.compile(
    r"(?P<url>(?:mysql|mysql\+\w+|postgres|postgresql|postgresql\+\w+|sqlite|sqlite\+\w+|mssql|oracle|duckdb)://[^\s\"']+)"
)

ENV_URL_RE = re.compile(
    r"(?P<key>[A-Z0-9_]*(?:DATABASE_URL|DB_URL|SQLALCHEMY_DATABASE_URI|JDBC_URL)[A-Z0-9_]*)\s*=\s*(?P<value>.+)"
)

MASKED_VALUES = {
    "user",
    "pass",
    "password",
    "dbname",
    "database",
    "host",
    "localhost",
    "example",
    "sqlx",
    "mydb",
    "my_database",
}
IGNORED_ENV_KEYS = {"APP_METADATA_DATABASE_URL"}


def parse_connection_url(url: str, relative_to: Path | None = None) -> SourceConnection:
    url = url.strip().strip("`")
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    raw_type = scheme.split("+", 1)[0]
    db_type = DatabaseType(raw_type) if raw_type in DatabaseType._value2member_map_ else DatabaseType.unknown

    database = unquote(parsed.path.lstrip("/")) or None
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    file_path = None
    if db_type in {DatabaseType.sqlite, DatabaseType.duckdb}:
        if url.startswith("sqlite") or url.startswith("duckdb"):
            file_path = unquote(url.split(":///", 1)[1])
        if file_path and relative_to and not Path(file_path).is_absolute():
            file_path = str((relative_to / file_path).resolve())
        database = database or (Path(file_path).stem if file_path else None)

    return SourceConnection(
        type=db_type,
        url=url,
        host=parsed.hostname,
        port=parsed.port,
        database=database,
        username=unquote(parsed.username) if parsed.username else None,
        password=unquote(parsed.password) if parsed.password else None,
        schema_name=None,
        unix_socket=query.get("unix_socket"),
        file_path=file_path,
        options=query,
    )


def build_source_name(connection: SourceConnection, preferred_name: str | None = None) -> str:
    if preferred_name:
        return normalized_name(preferred_name)
    if connection.type in {DatabaseType.sqlite, DatabaseType.duckdb} and connection.file_path:
        return normalized_name(Path(connection.file_path).stem)
    host = connection.host or "local"
    database = connection.database or connection.file_path or "database"
    return normalized_name(f"{host}_{database}")


def source_key(source: DiscoveredSource) -> tuple[str, str | None, int | None, str | None, str | None]:
    connection = source.connection
    return (
        connection.type.value,
        connection.host or connection.file_path,
        connection.port,
        connection.database,
        connection.unix_socket,
    )


def looks_like_placeholder(url: str) -> bool:
    tokens = {token.lower() for token in re.split(r"[^a-zA-Z0-9]+", url) if token}
    return bool(tokens & MASKED_VALUES) and "localhost" not in url and "127.0.0.1" not in url


class SourceDiscoveryService:
    def __init__(self, roots: Iterable[Path], max_file_bytes: int = 524_288, skip_dirs: set[str] | None = None):
        self.roots = [root.expanduser() for root in roots]
        self.max_file_bytes = max_file_bytes
        self.skip_dirs = skip_dirs or set()

    def discover(self) -> DiscoveryReport:
        discovered: dict[tuple[str, str | None, int | None, str | None, str | None], DiscoveredSource] = {}
        roots_scanned = [str(root) for root in self.roots]

        for root in self.roots:
            if not root.exists():
                continue
            for path in self._walk(root):
                for source in self._scan_file(path):
                    key = source_key(source)
                    if key in discovered:
                        existing = discovered[key]
                        existing.evidence.extend(source.evidence)
                        existing.tags = unique_non_empty([*existing.tags, *source.tags])
                        existing.notes = unique_non_empty([*existing.notes, *source.notes])
                        existing.allow_tables = unique_non_empty([*existing.allow_tables, *source.allow_tables])
                        existing.protected_tables = unique_non_empty(
                            [*existing.protected_tables, *source.protected_tables]
                        )
                    else:
                        discovered[key] = source

            for source in self._discover_sqlite_files(root):
                key = source_key(source)
                discovered.setdefault(key, source)

        expanded = self._expand_local_mysql_schemas(list(discovered.values()))
        for source in expanded:
            discovered[source_key(source)] = source

        sources = sorted(discovered.values(), key=lambda item: item.name)
        missing = [self._missing_template(source) for source in sources if self._requires_user_input(source)]
        summary = self._build_summary(sources)
        return DiscoveryReport(
            generated_at=self._iso_now(),
            roots_scanned=roots_scanned,
            discovered_sources=sources,
            missing_connection_templates=missing,
            summary=summary,
        )

    def _walk(self, root: Path) -> Iterable[Path]:
        for path in root.rglob("*"):
            if any(part in self.skip_dirs for part in path.parts):
                continue
            if not path.is_file():
                continue
            if path.stat().st_size > self.max_file_bytes:
                continue
            from app.discovery.patterns import is_candidate_file

            if is_candidate_file(path):
                yield path

    def _scan_file(self, path: Path) -> list[DiscoveredSource]:
        content = self._read_text(path)
        if content is None:
            return []

        sources: list[DiscoveredSource] = []
        if path.suffix in {".yaml", ".yml"}:
            sources.extend(self._scan_yaml_registry(path, content))

        for line_number, line in enumerate(content.splitlines(), start=1):
            env_match = ENV_URL_RE.search(line)
            skip_url_literals = False
            if env_match:
                env_key = env_match.group("key")
                if env_key in IGNORED_ENV_KEYS or env_key.startswith("OPENMETADATA_"):
                    skip_url_literals = True
                else:
                    raw_value = env_match.group("value").strip().strip("\"'")
                    if raw_value.startswith("#"):
                        continue
                    if "://" in raw_value and not looks_like_placeholder(raw_value):
                        connection = parse_connection_url(raw_value, relative_to=path.parent)
                        if connection.type == DatabaseType.unknown:
                            continue
                        if connection.type in {DatabaseType.sqlite, DatabaseType.duckdb} and connection.file_path:
                            if not Path(connection.file_path).exists():
                                continue
                        sources.append(
                            DiscoveredSource(
                                name=build_source_name(connection, preferred_name=self._hint_name(path, env_key)),
                                connection=connection,
                                description=f"Discovered from {path.name}",
                                evidence=[
                                    SourceEvidence(
                                        kind="env_assignment",
                                        path=str(path),
                                        line_number=line_number,
                                        snippet=line.strip()[:200],
                                    )
                                ],
                                tags=["discovered", path.stem],
                                notes=[f"Found in variable {env_key}"],
                            )
                        )
            if skip_url_literals:
                continue
            for url_match in URL_RE.finditer(line):
                raw_value = url_match.group("url").strip().strip("\"'")
                if looks_like_placeholder(raw_value):
                    continue
                connection = parse_connection_url(raw_value, relative_to=path.parent)
                if connection.type == DatabaseType.unknown:
                    continue
                if connection.type in {DatabaseType.sqlite, DatabaseType.duckdb} and connection.file_path:
                    if not Path(connection.file_path).exists():
                        continue
                sources.append(
                    DiscoveredSource(
                        name=build_source_name(connection),
                        connection=connection,
                        description=f"Discovered in {path.name}",
                        evidence=[
                            SourceEvidence(
                                kind="url_literal",
                                path=str(path),
                                line_number=line_number,
                                snippet=line.strip()[:200],
                            )
                        ],
                        tags=["discovered", path.suffix.lstrip(".") or "file"],
                    )
                )
        return sources

    def _scan_yaml_registry(self, path: Path, content: str) -> list[DiscoveredSource]:
        try:
            payload = yaml.safe_load(content) or {}
        except yaml.YAMLError:
            return []
        apps = payload.get("apps")
        if not isinstance(apps, dict):
            return []

        results: list[DiscoveredSource] = []
        for app_name, app_config in apps.items():
            if not isinstance(app_config, dict) or "database_url" not in app_config:
                continue
            url = str(app_config["database_url"])
            if looks_like_placeholder(url):
                continue
            connection = parse_connection_url(url, relative_to=path.parent)
            if connection.type in {DatabaseType.sqlite, DatabaseType.duckdb} and connection.file_path:
                if not Path(connection.file_path).exists():
                    continue
            results.append(
                DiscoveredSource(
                    name=build_source_name(connection, preferred_name=app_name),
                    connection=connection,
                    description=app_config.get("description") or f"Discovered in {path.name}",
                    evidence=[
                        SourceEvidence(
                            kind="yaml_app_registry",
                            path=str(path),
                            snippet=f"apps.{app_name}.database_url",
                        )
                    ],
                    tags=["discovered", "app_registry"],
                    allow_tables=list(app_config.get("allowed_tables", []) or []),
                    protected_tables=list(app_config.get("protected_tables", []) or []),
                    approved_use_cases=["semantic_onboarding", "chatbot_context", "metadata_discovery"],
                )
            )
        return results

    def _discover_sqlite_files(self, root: Path) -> list[DiscoveredSource]:
        from app.discovery.patterns import SQLITE_SUFFIXES

        results: list[DiscoveredSource] = []
        for path in root.rglob("*"):
            if any(part in self.skip_dirs for part in path.parts):
                continue
            if not path.is_file() or path.suffix.lower() not in SQLITE_SUFFIXES:
                continue
            if self._ignore_sqlite_path(path):
                continue
            db_type = DatabaseType.duckdb if path.suffix.lower() == ".duckdb" else DatabaseType.sqlite
            connection = SourceConnection(
                type=db_type,
                url=f"{db_type.value}:///{path}",
                database=path.stem,
                file_path=str(path.resolve()),
            )
            results.append(
                DiscoveredSource(
                    name=build_source_name(connection, preferred_name=path.stem),
                    connection=connection,
                    description=f"Local {db_type.value} file",
                    evidence=[SourceEvidence(kind="file_scan", path=str(path))],
                    tags=["file_discovery", db_type.value],
                    approved_use_cases=["semantic_onboarding", "metadata_discovery"],
                )
            )
        return results

    def _expand_local_mysql_schemas(self, sources: list[DiscoveredSource]) -> list[DiscoveredSource]:
        expanded = list(sources)
        mysql_sources = [source for source in sources if source.connection.type == DatabaseType.mysql]
        grouped: dict[tuple[str | None, int | None, str | None, str | None], list[DiscoveredSource]] = {}
        for source in mysql_sources:
            connection = source.connection
            key = (connection.host, connection.port, connection.username, connection.unix_socket)
            grouped.setdefault(key, []).append(source)

        for group_sources in grouped.values():
            reference = group_sources[0]
            connection = reference.connection
            if not connection.username or not connection.password:
                continue
            if not (connection.host or connection.unix_socket):
                continue
            try:
                engine = create_engine(self._inventory_url(reference.connection))
                with engine.connect() as db:
                    rows = db.execute(
                        text(
                            """
                            SELECT schema_name
                            FROM information_schema.schemata
                            WHERE schema_name NOT IN ('information_schema', 'mysql', 'performance_schema', 'sys')
                            ORDER BY schema_name
                            """
                        )
                    ).fetchall()
                existing = {item.connection.database for item in group_sources}
                for row in rows:
                    schema_name = row[0]
                    if schema_name in existing:
                        continue
                    derived_connection = connection.model_copy(
                        update={
                            "database": schema_name,
                            "url": self._inventory_url(connection, database=schema_name),
                        }
                    )
                    expanded.append(
                        DiscoveredSource(
                            name=build_source_name(derived_connection, preferred_name=schema_name),
                            connection=derived_connection,
                            description="Auto-expanded from local MySQL inventory",
                            evidence=[
                                SourceEvidence(
                                    kind="live_mysql_inventory",
                                    note=f"Enumerated from {reference.name}",
                                )
                            ],
                            tags=["live_inventory", "mysql"],
                            approved_use_cases=["semantic_onboarding", "metadata_discovery", "chatbot_context"],
                        )
                    )
            except Exception as exc:  # pragma: no cover - environment specific
                LOGGER.warning("Failed to expand MySQL schemas for %s: %s", reference.name, exc)
        return expanded

    def _inventory_url(self, connection: SourceConnection, database: str | None = None) -> str:
        db_name = database or connection.database or "information_schema"
        host = connection.host or "localhost"
        port = connection.port or 3306
        user = connection.username or ""
        password = connection.password or ""
        query = ""
        if connection.unix_socket:
            query = f"?unix_socket={connection.unix_socket}"
        return f"mysql+pymysql://{user}:{password}@{host}:{port}/{db_name}{query}"

    def _requires_user_input(self, source: DiscoveredSource) -> bool:
        connection = source.connection
        if connection.type in {DatabaseType.sqlite, DatabaseType.duckdb}:
            return not connection.file_path
        return not (connection.url or (connection.host and connection.database))

    def _missing_template(self, source: DiscoveredSource) -> dict[str, object]:
        return {
            "name": source.name,
            "type": source.connection.type.value,
            "missing_fields": [
                key
                for key, value in {
                    "host": source.connection.host,
                    "port": source.connection.port,
                    "database": source.connection.database,
                    "username": source.connection.username,
                    "password": source.connection.password,
                    "file_path": source.connection.file_path,
                }.items()
                if value in (None, "")
            ],
        }

    def _build_summary(self, sources: list[DiscoveredSource]) -> dict[str, object]:
        by_type: dict[str, int] = {}
        for source in sources:
            by_type[source.connection.type.value] = by_type.get(source.connection.type.value, 0) + 1
        return {
            "total_sources": len(sources),
            "by_type": by_type,
            "listening_ports": self._listening_ports(),
        }

    def _listening_ports(self) -> list[dict[str, object]]:
        try:
            completed = subprocess.run(
                ["bash", "-lc", "ss -ltnp | rg '(:5432|:3306|:1433|:1521|:27017|:6379|:8080|:8585|:9200)'"],
                capture_output=True,
                check=False,
                text=True,
            )
        except FileNotFoundError:
            return []
        ports: list[dict[str, object]] = []
        for line in completed.stdout.splitlines():
            parts = line.split()
            if len(parts) < 4:
                continue
            ports.append({"listener": parts[0], "endpoint": parts[3]})
        return ports

    def _hint_name(self, path: Path, key: str) -> str:
        stem = path.stem.replace(".example", "")
        return normalized_name(f"{stem}_{key}")

    def _ignore_sqlite_path(self, path: Path) -> bool:
        ignored_parts = {
            ".cache",
            "tracker3",
            "google-chrome",
            "JetBrains",
            ".pki",
            "mesa_shader_cache_db",
            "assets",
            "output",
        }
        if any(part in ignored_parts for part in path.parts):
            return True
        return path.name == "app_metadata.db"

    def _read_text(self, path: Path) -> str | None:
        try:
            return path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return None

    def _iso_now(self) -> str:
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).isoformat()


def report_to_paths(report: DiscoveryReport, json_path: Path, yaml_path: Path) -> None:
    from app.utils.serialization import write_json, write_yaml

    write_json(json_path, report)
    write_yaml(yaml_path, report)
    LOGGER.info("Wrote discovery report to %s and %s", json_path, yaml_path)


def print_report(report: DiscoveryReport) -> None:
    print(json.dumps(report.model_dump(mode="json", exclude_none=True), indent=2))


def is_local_source(source: DiscoveredSource) -> bool:
    connection = source.connection
    if connection.file_path:
        return True
    if connection.unix_socket:
        return True
    return connection.host in {None, "localhost", "127.0.0.1", "host.docker.internal"}


def local_only_report(report: DiscoveryReport) -> DiscoveryReport:
    sources = [source for source in report.discovered_sources if is_local_source(source)]
    summary = {
        **report.summary,
        "total_sources": len(sources),
        "by_type": {
            key: sum(1 for source in sources if source.connection.type.value == key)
            for key in sorted({source.connection.type.value for source in sources})
        },
    }
    return report.model_copy(update={"discovered_sources": sources, "summary": summary})
