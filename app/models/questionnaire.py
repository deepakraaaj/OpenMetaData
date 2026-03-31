from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class QuestionnaireQuestion(BaseModel):
    type: str
    question: str
    table: str | None = None
    column: str | None = None
    left_table: str | None = None
    right_table: str | None = None
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

