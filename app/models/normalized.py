from __future__ import annotations

from pydantic import BaseModel, Field


class NormalizedColumn(BaseModel):
    schema_name: str
    table_name: str
    column_name: str
    technical_type: str
    tokens: list[str] = Field(default_factory=list)
    sample_values: list[str] = Field(default_factory=list)
    enum_values: list[str] = Field(default_factory=list)
    is_primary_key: bool = False
    is_foreign_key: bool = False
    is_identifier_like: bool = False
    is_status_like: bool = False
    is_timestamp_like: bool = False
    sensitivity_hints: list[str] = Field(default_factory=list)


class NormalizedTable(BaseModel):
    schema_name: str
    table_name: str
    tokens: list[str] = Field(default_factory=list)
    row_count: int | None = None
    primary_key: list[str] = Field(default_factory=list)
    foreign_keys: list[str] = Field(default_factory=list)
    join_candidates: list[str] = Field(default_factory=list)
    filters: list[str] = Field(default_factory=list)
    grain_hint: str | None = None
    entity_hint: str | None = None
    columns: list[NormalizedColumn] = Field(default_factory=list)


class NormalizedSource(BaseModel):
    source_name: str
    db_type: str
    database_name: str | None = None
    domain_hints: list[str] = Field(default_factory=list)
    tables: list[NormalizedTable] = Field(default_factory=list)
    summary: dict[str, int] = Field(default_factory=dict)

