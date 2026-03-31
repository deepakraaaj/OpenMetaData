from __future__ import annotations

from pathlib import Path


CANDIDATE_FILE_NAMES = {
    ".env",
    ".env.example",
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yaml",
    "compose.yml",
    "application.yml",
    "application.yaml",
    "config.json",
    "config.yaml",
    "settings.py",
    "schema.prisma",
    "knexfile.js",
    "knexfile.ts",
    "README.md",
    "README",
    "apps.yaml",
    "apps.local.yaml",
}

SQLITE_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".duckdb"}


def is_candidate_file(path: Path) -> bool:
    return path.name in CANDIDATE_FILE_NAMES or path.suffix in {".sh", ".sql"}

