from __future__ import annotations

from enum import Enum
from typing import Any
from pydantic import BaseModel, Field

from app.models.questionnaire import QuestionAction, QuestionOption
from app.models.review import DomainReviewGroup, ReviewQueueItem, TableSelectionSummary
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
    question_type: str = "meaning_confirmation"
    best_guess: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    evidence: list[str] = Field(default_factory=list)
    candidate_options: list[QuestionOption] = Field(default_factory=list)
    decision_prompt: str | None = None
    actions: list[QuestionAction] = Field(default_factory=list)
    impact_score: float = Field(default=0.0, ge=0, le=1)
    ambiguity_score: float = Field(default=0.0, ge=0, le=1)
    business_relevance: float = Field(default=0.0, ge=0, le=1)
    priority_score: float = Field(default=0.0, ge=0)
    allow_free_text: bool = False
    free_text_placeholder: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
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
    review_summary: TableSelectionSummary = Field(default_factory=TableSelectionSummary)
    domain_groups: list[DomainReviewGroup] = Field(default_factory=list)
    review_queue: list[ReviewQueueItem] = Field(default_factory=list)
