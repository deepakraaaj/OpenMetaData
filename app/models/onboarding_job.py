from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class OnboardingStage(str, Enum):
    CONNECTING_TO_DATABASE = "connecting_to_database"
    READING_SCHEMA = "reading_schema"
    EXTRACTING_RELATIONSHIPS = "extracting_relationships"
    BUILDING_SEMANTIC_MODEL = "building_semantic_model"
    GENERATING_REVIEW_QUESTIONS = "generating_review_questions"
    READY_FOR_REVIEW = "ready_for_review"


class OnboardingStepState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    ERROR = "error"


class OnboardingJobState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class OnboardingLogLevel(str, Enum):
    INFO = "info"
    SUCCESS = "success"
    ERROR = "error"


class OnboardingProgressCounts(BaseModel):
    schema_count: int | None = None
    table_count: int | None = None
    column_count: int | None = None
    foreign_key_count: int | None = None
    inferred_relationship_count: int | None = None
    review_item_count: int | None = None
    domain_group_count: int | None = None
    unresolved_gap_count: int | None = None


class OnboardingStepStatus(BaseModel):
    stage: OnboardingStage
    label: str
    state: OnboardingStepState = OnboardingStepState.PENDING
    message: str | None = None
    started_at: str | None = None
    completed_at: str | None = None


class OnboardingLogEntry(BaseModel):
    timestamp: str
    stage: OnboardingStage
    level: OnboardingLogLevel = OnboardingLogLevel.INFO
    message: str


class OnboardingProgressUpdate(BaseModel):
    stage: OnboardingStage
    message: str
    step_state: OnboardingStepState | None = None
    level: OnboardingLogLevel = OnboardingLogLevel.INFO
    counts: OnboardingProgressCounts = Field(default_factory=OnboardingProgressCounts)


class OnboardingResult(BaseModel):
    source_name: str
    output_dir: str
    bundle_dir: str
    chatbot_package_dir: str
    wizard_url: str
    api_wizard_url: str
    download_url: str
    chatbot_package_url: str
    chatbot_package_download_url: str
    legacy_review_url: str


class OnboardingJobSnapshot(BaseModel):
    job_id: str
    source_name: str
    status: OnboardingJobState = OnboardingJobState.QUEUED
    current_stage: OnboardingStage | None = None
    progress_percent: int = 0
    estimated_wait_message: str = "This may take 20–60 seconds depending on schema size."
    counts: OnboardingProgressCounts = Field(default_factory=OnboardingProgressCounts)
    steps: list[OnboardingStepStatus] = Field(default_factory=list)
    logs: list[OnboardingLogEntry] = Field(default_factory=list)
    status_url: str = ""
    wizard_url: str = ""
    result: OnboardingResult | None = None
    error_message: str | None = None
    reused_existing_job: bool = False
    created_at: str
    updated_at: str
    finished_at: str | None = None


ONBOARDING_STAGE_LABELS: dict[OnboardingStage, str] = {
    OnboardingStage.CONNECTING_TO_DATABASE: "Connecting to database",
    OnboardingStage.READING_SCHEMA: "Reading schema",
    OnboardingStage.EXTRACTING_RELATIONSHIPS: "Extracting relationships",
    OnboardingStage.BUILDING_SEMANTIC_MODEL: "Building semantic model",
    OnboardingStage.READY_FOR_REVIEW: "Open review workspace",
}


ONBOARDING_STAGE_ORDER: tuple[OnboardingStage, ...] = tuple(ONBOARDING_STAGE_LABELS.keys())


def build_default_onboarding_steps() -> list[OnboardingStepStatus]:
    return [
        OnboardingStepStatus(stage=stage, label=label)
        for stage, label in ONBOARDING_STAGE_LABELS.items()
    ]
