from __future__ import annotations

from pydantic import BaseModel, Field


class SourceArtifact(BaseModel):
    source_name: str
    db_type: str
    domain: str | None = None
    description: str | None = None
    key_entities: list[str] = Field(default_factory=list)
    sensitive_areas: list[str] = Field(default_factory=list)
    approved_use_cases: list[str] = Field(default_factory=list)


class LLMContextPackage(BaseModel):
    question: str
    domain: str | None = None
    review_mode: str | None = None
    matched_entities: list[str] = Field(default_factory=list)
    matched_tables: list[str] = Field(default_factory=list)
    matched_columns: list[str] = Field(default_factory=list)
    glossary_terms: list[str] = Field(default_factory=list)
    safe_joins: list[str] = Field(default_factory=list)
    query_patterns: list[str] = Field(default_factory=list)
    provisional_items: list[str] = Field(default_factory=list)
    blocked_items: list[str] = Field(default_factory=list)
    notes_for_llm: list[str] = Field(default_factory=list)
