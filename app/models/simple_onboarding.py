from __future__ import annotations

from typing import Any, Dict, Literal

from pydantic import BaseModel, Field, field_validator


def _dedupe_strings(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []

    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        normalized = text.lower()
        if not text or normalized in seen:
            continue
        seen.add(normalized)
        cleaned.append(text)
    return cleaned


class SimpleOnboardingRelationship(BaseModel):
    from_table: str
    from_columns: list[str] = Field(default_factory=list)
    to_table: str
    to_columns: list[str] = Field(default_factory=list)


class SimpleOnboardingArtifact(BaseModel):
    categories: Dict[str, list[str]] = Field(default_factory=dict)
    selected_tables: list[str] = Field(default_factory=list)
    table_descriptions: Dict[str, str] = Field(default_factory=dict)
    relationships: list[SimpleOnboardingRelationship] = Field(default_factory=list)
    business_context: str = ""
    metrics: list[dict[str, Any]] = Field(default_factory=list)


class SimpleOnboardingTable(BaseModel):
    name: str
    schema_name: str
    category: str
    description: str
    selected: bool = False
    suggested_action: Literal["select", "ignore"]
    selection_reason: str = ""
    business_score: int = 0
    columns: list[str] = Field(default_factory=list)
    related_tables: list[str] = Field(default_factory=list)


class SimpleOnboardingRequest(BaseModel):
    db_url: str
    source_name: str | None = None
    schema_name: str | None = None
    description: str | None = None
    business_context: str = ""
    selection_mode: Literal["review", "ai"] = "review"
    selected_tables: list[str] = Field(default_factory=list)
    include_tables: list[str] = Field(default_factory=list)
    exclude_tables: list[str] = Field(default_factory=list)
    include_categories: list[str] = Field(default_factory=list)
    exclude_categories: list[str] = Field(default_factory=list)
    bulk_include_patterns: list[str] = Field(default_factory=list)
    bulk_exclude_patterns: list[str] = Field(default_factory=list)
    persist_artifact: bool = True

    @field_validator(
        "selected_tables",
        "include_tables",
        "exclude_tables",
        "include_categories",
        "exclude_categories",
        "bulk_include_patterns",
        "bulk_exclude_patterns",
        mode="before",
    )
    @classmethod
    def _normalize_list_fields(cls, value: Any) -> list[str]:
        return _dedupe_strings(value)

    @field_validator("db_url", "source_name", "schema_name", "description", "business_context", mode="before")
    @classmethod
    def _strip_text(cls, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text


class SimpleOnboardingResponse(BaseModel):
    source_name: str
    database_target: str
    total_tables: int
    selection_mode: Literal["review", "ai"]
    categories: Dict[str, list[str]] = Field(default_factory=dict)
    selected_tables: list[str] = Field(default_factory=list)
    ignored_tables: list[str] = Field(default_factory=list)
    tables: list[SimpleOnboardingTable] = Field(default_factory=list)
    artifact: SimpleOnboardingArtifact
    artifact_path: str | None = None
