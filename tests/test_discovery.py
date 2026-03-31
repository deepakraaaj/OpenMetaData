from pathlib import Path

from app.discovery.service import build_source_name, parse_connection_url
from app.models.common import DatabaseType


def test_parse_mysql_connection_url() -> None:
    connection = parse_connection_url(
        "mysql+aiomysql://root:secret@localhost:3306/fits_dev?allowPublicKeyRetrieval=true&useSSL=false"
    )
    assert connection.type == DatabaseType.mysql
    assert connection.host == "localhost"
    assert connection.port == 3306
    assert connection.database == "fits_dev"
    assert connection.options["useSSL"] == "false"


def test_parse_sqlite_connection_url_relative_path() -> None:
    connection = parse_connection_url("sqlite+aiosqlite:///data/demo.sqlite3", relative_to=Path("/tmp/project"))
    assert connection.type == DatabaseType.sqlite
    assert connection.file_path == "/tmp/project/data/demo.sqlite3"
    assert build_source_name(connection) == "demo"

