from __future__ import annotations

from enum import Enum
from pydantic import BaseModel, Field

from app.models.semantic import (
    SemanticTable,
    CanonicalEntity,
    GlossaryTerm,
    QueryPattern,
    EnumMapping,
    BusinessRule,
)


class GapCategory(str, Enum):
    MISSING_PRIMARY_KEY = "missing_primary_key"
    AMBIGUOUS_RELATIONSHIP = "ambiguous_relationship"
    UNKNOWN_BUSINESS_MEANING = "unknown_business_meaning"
    UNCONFIRMED_ENUM_MAPPING = "unconfirmed_enum_mapping"
    POTENTIAL_SENSITIVITY = "potential_sensitivity"
    GLOSSARY_TERM_MISSING = "glossary_term_missing"
    RELATIONSHIP_ROLE_UNCLEAR = "relationship_role_unclear"
    OTHER = "other"


class SemanticGap(BaseModel):
    gap_id: str
    category: GapCategory
    target_entity: str | None = None
    target_property: str | None = None
    description: str
    suggested_question: str | None = None
    is_blocking: bool = False
    priority: int = Field(default=3, ge=1, le=3)  # 1=blocking, 2=high, 3=nice-to-have


class ReadinessState(BaseModel):
    is_ready: bool = False
    readiness_percentage: float = 0.0
    blocking_gaps_count: int = 0
    total_gaps_count: int = 0
    readiness_notes: list[str] = Field(default_factory=list)


class KnowledgeState(BaseModel):
    source_name: str = ""
    tables: dict[str, SemanticTable] = Field(default_factory=dict)
    canonical_entities: dict[str, CanonicalEntity] = Field(default_factory=dict)
    enums: dict[str, list[EnumMapping]] = Field(default_factory=dict)
    business_rules: list[BusinessRule] = Field(default_factory=list)
    glossary: dict[str, GlossaryTerm] = Field(default_factory=dict)
    query_patterns: list[QueryPattern] = Field(default_factory=list)

    unresolved_gaps: list[SemanticGap] = Field(default_factory=list)
    readiness: ReadinessState = Field(default_factory=ReadinessState)

