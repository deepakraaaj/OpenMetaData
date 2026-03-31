from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class DatabaseType(str, Enum):
    mysql = "mysql"
    postgresql = "postgresql"
    sqlite = "sqlite"
    mssql = "mssql"
    oracle = "oracle"
    duckdb = "duckdb"
    unknown = "unknown"


class ConfidenceLabel(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"


class SensitivityLabel(str, Enum):
    none = "none"
    possible_sensitive = "possible_sensitive"
    sensitive = "sensitive"


class NamedConfidence(BaseModel):
    label: ConfidenceLabel = Field(default=ConfidenceLabel.medium)
    score: float = Field(default=0.5, ge=0.0, le=1.0)
    rationale: list[str] = Field(default_factory=list)

