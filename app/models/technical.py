from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.models.common import DatabaseType


class ColumnProfile(BaseModel):
    name: str
    data_type: str
    nullable: bool = True
    default: str | None = None
    ordinal_position: int | None = None
    is_primary_key: bool = False
    is_foreign_key: bool = False
    referenced_table: str | None = None
    referenced_column: str | None = None
    enum_values: list[str] = Field(default_factory=list)
    sample_values: list[str] = Field(default_factory=list)
    is_timestamp_like: bool = False
    is_status_like: bool = False
    is_identifier_like: bool = False


class ForeignKeyProfile(BaseModel):
    name: str | None = None
    constrained_columns: list[str] = Field(default_factory=list)
    referred_schema: str | None = None
    referred_table: str
    referred_columns: list[str] = Field(default_factory=list)


class IndexProfile(BaseModel):
    name: str
    columns: list[str] = Field(default_factory=list)
    unique: bool = False


class CandidateJoin(BaseModel):
    left_table: str
    left_column: str
    right_table: str
    right_column: str
    confidence: float
    reasons: list[str] = Field(default_factory=list)


class TableProfile(BaseModel):
    schema_name: str
    table_name: str
    table_type: str = "BASE TABLE"
    estimated_row_count: int | None = None
    description: str | None = None
    columns: list[ColumnProfile] = Field(default_factory=list)
    primary_key: list[str] = Field(default_factory=list)
    foreign_keys: list[ForeignKeyProfile] = Field(default_factory=list)
    indexes: list[IndexProfile] = Field(default_factory=list)
    candidate_joins: list[CandidateJoin] = Field(default_factory=list)
    sample_rows: list[dict[str, Any]] = Field(default_factory=list)
    timestamp_columns: list[str] = Field(default_factory=list)
    status_columns: list[str] = Field(default_factory=list)


class SchemaProfile(BaseModel):
    schema_name: str
    tables: list[TableProfile] = Field(default_factory=list)


class SourceTechnicalMetadata(BaseModel):
    source_name: str
    db_type: DatabaseType
    database_name: str | None = None
    schemas: list[SchemaProfile] = Field(default_factory=list)
    connectivity_ok: bool = False
    connectivity_notes: list[str] = Field(default_factory=list)
    source_summary: dict[str, Any] = Field(default_factory=dict)

