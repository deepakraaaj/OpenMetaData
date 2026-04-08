from __future__ import annotations

from collections.abc import Callable

from app.models.normalized import NormalizedSource
from app.models.onboarding_job import OnboardingProgressCounts, OnboardingProgressUpdate
from app.models.state import KnowledgeState
from app.models.technical import SourceTechnicalMetadata


ProgressCallback = Callable[[OnboardingProgressUpdate], None]


def emit_progress(progress: ProgressCallback | None, update: OnboardingProgressUpdate) -> None:
    if progress is not None:
        progress(update)


def technical_counts(metadata: SourceTechnicalMetadata) -> OnboardingProgressCounts:
    tables = [table for schema in metadata.schemas for table in schema.tables]
    return OnboardingProgressCounts(
        schema_count=len(metadata.schemas),
        table_count=len(tables),
        column_count=sum(len(table.columns) for table in tables),
        foreign_key_count=sum(len(table.foreign_keys) for table in tables),
        inferred_relationship_count=sum(len(table.candidate_joins) for table in tables),
    )


def normalized_counts(normalized: NormalizedSource) -> OnboardingProgressCounts:
    return OnboardingProgressCounts(
        table_count=len(normalized.tables),
        column_count=sum(len(table.columns) for table in normalized.tables),
        foreign_key_count=sum(len(table.foreign_keys) for table in normalized.tables),
        inferred_relationship_count=sum(len(table.join_candidates) for table in normalized.tables),
    )


def state_counts(state: KnowledgeState) -> OnboardingProgressCounts:
    return OnboardingProgressCounts(
        table_count=len(state.tables),
        column_count=sum(len(table.columns) for table in state.tables.values()),
        unresolved_gap_count=len(state.unresolved_gaps),
    )
