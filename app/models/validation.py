from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SqlValidationRequest(BaseModel):
    question: str


class SqlValidationResult(BaseModel):
    source_name: str
    question: str
    intent: str
    matched_table: str | None = None
    matched_join: str | None = None
    sql: str
    execution_status: str
    columns: list[str] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    row_count: int = 0
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None
