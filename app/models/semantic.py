from __future__ import annotations

from pydantic import BaseModel, Field

from app.models.common import NamedConfidence, SensitivityLabel


class SemanticColumn(BaseModel):
    column_name: str
    technical_type: str
    business_meaning: str | None = None
    example_values: list[str] = Field(default_factory=list)
    synonyms: list[str] = Field(default_factory=list)
    filterable: bool = True
    displayable: bool = True
    sensitive: SensitivityLabel = SensitivityLabel.none
    confidence: NamedConfidence = Field(default_factory=NamedConfidence)


class SemanticTable(BaseModel):
    table_name: str
    business_meaning: str | None = None
    grain: str | None = None
    likely_entity: str | None = None
    important_columns: list[str] = Field(default_factory=list)
    valid_joins: list[str] = Field(default_factory=list)
    common_filters: list[str] = Field(default_factory=list)
    common_business_questions: list[str] = Field(default_factory=list)
    sensitivity_notes: list[str] = Field(default_factory=list)
    confidence: NamedConfidence = Field(default_factory=NamedConfidence)
    columns: list[SemanticColumn] = Field(default_factory=list)


class CanonicalEntity(BaseModel):
    entity_name: str
    description: str | None = None
    mapped_source_tables: list[str] = Field(default_factory=list)
    mapped_columns: list[str] = Field(default_factory=list)
    confidence: NamedConfidence = Field(default_factory=NamedConfidence)


class GlossaryTerm(BaseModel):
    term: str
    meaning: str
    synonyms: list[str] = Field(default_factory=list)
    related_tables: list[str] = Field(default_factory=list)
    related_columns: list[str] = Field(default_factory=list)


class QueryPattern(BaseModel):
    intent: str
    question_examples: list[str] = Field(default_factory=list)
    preferred_tables: list[str] = Field(default_factory=list)
    required_joins: list[str] = Field(default_factory=list)
    safe_filters: list[str] = Field(default_factory=list)
    optional_sql_template: str | None = None
    rendering_guidance: str | None = None


class SemanticSourceModel(BaseModel):
    source_name: str
    db_type: str
    domain: str | None = None
    description: str | None = None
    key_entities: list[str] = Field(default_factory=list)
    sensitive_areas: list[str] = Field(default_factory=list)
    approved_use_cases: list[str] = Field(default_factory=list)
    tables: list[SemanticTable] = Field(default_factory=list)
    glossary: list[GlossaryTerm] = Field(default_factory=list)
    canonical_entities: list[CanonicalEntity] = Field(default_factory=list)
    query_patterns: list[QueryPattern] = Field(default_factory=list)

