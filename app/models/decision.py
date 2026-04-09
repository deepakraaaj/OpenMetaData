from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ReviewMode(str, Enum):
    full_ai = "full_ai"
    guided = "guided"
    deep_review = "deep_review"


class RiskLevel(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class DecisionActor(str, Enum):
    ai_auto = "ai_auto"
    user_confirmed = "user_confirmed"
    user_overridden = "user_overridden"
    rule_default = "rule_default"


class DecisionStatus(str, Enum):
    auto_accepted = "auto_accepted"
    user_confirmed = "user_confirmed"
    user_overridden = "user_overridden"
    deferred_review = "deferred_review"
    publish_blocked = "publish_blocked"
    warning_ack_required = "warning_ack_required"


class DecisionRecord(BaseModel):
    decision_id: str
    item_key: str
    item_type: str
    title: str
    target_entity: str | None = None
    target_property: str | None = None
    decision_actor: DecisionActor
    review_mode: ReviewMode = ReviewMode.guided
    decision_status: DecisionStatus
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    risk_level: RiskLevel = RiskLevel.medium
    evidence_refs: list[str] = Field(default_factory=list)
    policy_reason: str | None = None
    applied_value: str | bool | list[str] | dict[str, Any] | None = None
    suggested_value: str | bool | list[str] | dict[str, Any] | None = None
    provisional: bool = False
    review_debt: bool = False
    needs_human_review: bool = False
    publish_blocker: bool = False
    needs_acknowledgement: bool = False
    supersedes: str | None = None
    overridden_by: str | None = None
    timestamp: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReviewDebtItem(BaseModel):
    decision_id: str
    item_key: str
    item_type: str
    title: str
    target_entity: str | None = None
    target_property: str | None = None
    decision_actor: DecisionActor
    review_mode: ReviewMode = ReviewMode.guided
    decision_status: DecisionStatus
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    risk_level: RiskLevel = RiskLevel.medium
    policy_reason: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    domain: str | None = None
    table_name: str | None = None
    review_debt: bool = False
    needs_human_review: bool = False
    publish_blocker: bool = False
    needs_acknowledgement: bool = False
    timestamp: str
    metadata: dict[str, Any] = Field(default_factory=dict)
