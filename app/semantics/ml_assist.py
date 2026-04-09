from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from app.models.review import TableRole


@dataclass(frozen=True)
class TableAssistSuggestion:
    table_name: str
    role: TableRole | None = None
    role_confidence: float | None = None
    domain: str | None = None
    domain_confidence: float | None = None
    reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ClusterAssistSuggestion:
    member_tables: list[str]
    cluster_name: str | None = None
    confidence: float | None = None
    reasons: list[str] = field(default_factory=list)


class SchemaMLAssist(Protocol):
    """Optional local assist hook for weak-schema cases.

    Implementations should be lightweight, local/edge-friendly, and safe to ignore.
    """

    def suggest_table(self, *, table_name: str, features: dict) -> TableAssistSuggestion | None:
        ...

    def suggest_cluster(self, *, member_tables: list[str], features: dict) -> ClusterAssistSuggestion | None:
        ...


class NoOpSchemaMLAssist:
    def suggest_table(self, *, table_name: str, features: dict) -> TableAssistSuggestion | None:
        del table_name, features
        return None

    def suggest_cluster(self, *, member_tables: list[str], features: dict) -> ClusterAssistSuggestion | None:
        del member_tables, features
        return None
