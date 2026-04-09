from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class QuestionOption(BaseModel):
    value: str
    label: str
    description: str | None = None
    is_best_guess: bool = False
    is_fallback: bool = False


class QuestionAction(BaseModel):
    value: str
    label: str


class QuestionnaireQuestion(BaseModel):
    type: str
    question: str
    question_type: str = "meaning_confirmation"
    table: str | None = None
    column: str | None = None
    left_table: str | None = None
    right_table: str | None = None
    best_guess: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    evidence: list[str] = Field(default_factory=list)
    candidate_options: list[QuestionOption] = Field(default_factory=list)
    decision_prompt: str | None = None
    actions: list[QuestionAction] = Field(default_factory=list)
    impact_score: float | None = Field(default=None, ge=0, le=1)
    ambiguity_score: float | None = Field(default=None, ge=0, le=1)
    business_relevance: float | None = Field(default=None, ge=0, le=1)
    priority_score: float | None = Field(default=None, ge=0)
    allow_free_text: bool = False
    free_text_placeholder: str | None = None
    suggested_answer: str | None = None
    suggested_join: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    answer: str | bool | list[str] | None = None


class QuestionnaireBundle(BaseModel):
    source_name: str
    questions: list[QuestionnaireQuestion] = Field(default_factory=list)


class QuestionnaireMergeResult(BaseModel):
    source_name: str
    applied_answers: int = 0
    updated_tables: list[str] = Field(default_factory=list)
    updated_columns: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
