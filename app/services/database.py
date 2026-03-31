from __future__ import annotations

from pathlib import Path
from urllib.parse import quote_plus, urlencode, urlparse

from sqlalchemy import Engine, create_engine

from app.models.common import DatabaseType
from app.models.source import SourceConnection


def normalize_sqlalchemy_url(connection: SourceConnection) -> str:
    if connection.url:
        url = connection.url
        url = url.replace("mysql+aiomysql://", "mysql+pymysql://")
        url = url.replace("mysql+asyncmy://", "mysql+pymysql://")
        url = url.replace("postgresql+asyncpg://", "postgresql+psycopg://")
        url = url.replace("postgres+asyncpg://", "postgresql+psycopg://")
        url = url.replace("sqlite+aiosqlite://", "sqlite://")
        return url

    if connection.type == DatabaseType.sqlite:
        file_path = connection.file_path or connection.database
        if not file_path:
            raise ValueError("SQLite connection requires file_path or database")
        return f"sqlite:///{Path(file_path).expanduser().resolve()}"

    if connection.type == DatabaseType.mysql:
        host = connection.host or "localhost"
        port = connection.port or 3306
        database = connection.database or ""
        username = quote_plus(connection.username or "")
        password = quote_plus(connection.password or "")
        query = dict(connection.options)
        if connection.unix_socket:
            query["unix_socket"] = connection.unix_socket
        suffix = f"?{urlencode(query)}" if query else ""
        return f"mysql+pymysql://{username}:{password}@{host}:{port}/{database}{suffix}"

    if connection.type == DatabaseType.postgresql:
        host = connection.host or "localhost"
        port = connection.port or 5432
        database = connection.database or ""
        username = quote_plus(connection.username or "")
        password = quote_plus(connection.password or "")
        suffix = f"?{urlencode(connection.options)}" if connection.options else ""
        return f"postgresql+psycopg://{username}:{password}@{host}:{port}/{database}{suffix}"

    if connection.type == DatabaseType.duckdb:
        file_path = connection.file_path or connection.database
        return f"duckdb:///{Path(file_path or ':memory:').expanduser().resolve()}"

    return connection.url or ""


def create_db_engine(connection: SourceConnection) -> Engine:
    return create_engine(normalize_sqlalchemy_url(connection), future=True)


def redacted_url(connection: SourceConnection) -> str | None:
    if not connection.url:
        return None
    parsed = urlparse(connection.url)
    if not parsed.password:
        return connection.url
    password = "***"
    netloc = parsed.netloc.replace(parsed.password, password)
    return parsed._replace(netloc=netloc).geturl()

