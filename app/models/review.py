from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from app.models.common import NamedConfidence


class TableRole(str, Enum):
    core_entity = "core_entity"
    transaction = "transaction"
    lookup_master = "lookup_master"
    mapping_bridge = "mapping_bridge"
    log_event = "log_event"
    history_audit = "history_audit"
    config_system = "config_system"
    unknown = "unknown"


class TableReviewDecision(str, Enum):
    selected = "selected"
    excluded = "excluded"
    review = "review"


class BulkReviewAction(str, Enum):
    select_recommended = "select_recommended"
    exclude_noise = "exclude_noise"
    include_lookup_tables = "include_lookup_tables"
    include_all = "include_all"


class ReviewQueueItem(BaseModel):
    table_name: str
    domain: str | None = None
    role: TableRole = TableRole.core_entity
    confidence: NamedConfidence = Field(default_factory=NamedConfidence)
    selected: bool = True
    open_gap_count: int = 0
    reason_for_classification: str | None = None
    selection_reason: str | None = None
    review_reason: str | None = None
    impact_score: float = Field(default=0.0, ge=0.0, le=1.0)
    business_relevance: float = Field(default=0.0, ge=0.0, le=1.0)
    related_tables: list[str] = Field(default_factory=list)


class DomainReviewGroup(BaseModel):
    domain: str
    tables: list[str] = Field(default_factory=list)
    core_tables: list[str] = Field(default_factory=list)
    anchor_tables: list[str] = Field(default_factory=list)
    selected_count: int = 0
    excluded_count: int = 0
    review_count: int = 0
    inferred_business_meaning: str | None = None
    requires_review: bool = False
    review_reason: str | None = None
    confidence: NamedConfidence = Field(default_factory=NamedConfidence)


class TableSelectionSummary(BaseModel):
    analyzed_table_count: int = 0
    selected_count: int = 0
    excluded_count: int = 0
    review_count: int = 0
    high_confidence_count: int = 0
    medium_confidence_count: int = 0
    low_confidence_count: int = 0
    detected_domains: list[str] = Field(default_factory=list)
