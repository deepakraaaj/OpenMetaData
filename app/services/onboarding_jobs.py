from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import logging
from threading import Lock
from uuid import uuid4

from app.artifacts.chatbot_package import CHATBOT_PACKAGE_DIRNAME
from app.core.settings import Settings
from app.models.onboarding_job import (
    ONBOARDING_STAGE_ORDER,
    OnboardingJobSnapshot,
    OnboardingJobState,
    OnboardingLogEntry,
    OnboardingLogLevel,
    OnboardingProgressCounts,
    OnboardingProgressUpdate,
    OnboardingResult,
    OnboardingStage,
    OnboardingStepState,
    build_default_onboarding_steps,
)
from app.models.source import DiscoveredSource
from app.onboard.pipeline import OnboardingPipeline, OnboardingPipelineError
from app.repositories.filesystem import WorkspaceRepository


LOGGER = logging.getLogger(__name__)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class InMemoryOnboardingJobStore:
    def __init__(self, max_workers: int = 4, log_limit: int = 48) -> None:
        self._jobs: dict[str, OnboardingJobSnapshot] = {}
        self._active_jobs_by_source: dict[str, str] = {}
        self._lock = Lock()
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="onboarding-job")
        self._log_limit = log_limit

    def find_active_job(self, source_name: str) -> OnboardingJobSnapshot | None:
        source_key = source_name.strip().lower()
        with self._lock:
            job_id = self._active_jobs_by_source.get(source_key)
            if not job_id:
                return None
            snapshot = self._jobs.get(job_id)
            if snapshot is None or snapshot.status not in {OnboardingJobState.QUEUED, OnboardingJobState.RUNNING}:
                self._active_jobs_by_source.pop(source_key, None)
                return None
            return snapshot.model_copy(deep=True)

    def create_job(self, source_name: str) -> OnboardingJobSnapshot:
        now = _utc_now()
        job_id = uuid4().hex
        snapshot = OnboardingJobSnapshot(
            job_id=job_id,
            source_name=source_name,
            status=OnboardingJobState.QUEUED,
            steps=build_default_onboarding_steps(),
            status_url=f"/api/onboarding/jobs/{job_id}",
            wizard_url=f"/source/{source_name}",
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self._jobs[job_id] = snapshot
            self._active_jobs_by_source[source_name.strip().lower()] = job_id
        return snapshot.model_copy(deep=True)

    def get_job(self, job_id: str) -> OnboardingJobSnapshot | None:
        with self._lock:
            snapshot = self._jobs.get(job_id)
            return snapshot.model_copy(deep=True) if snapshot is not None else None

    def apply_update(self, job_id: str, update: OnboardingProgressUpdate) -> None:
        with self._lock:
            snapshot = self._jobs.get(job_id)
            if snapshot is None:
                return
            self._apply_update_locked(snapshot, update)

    def mark_failed(self, job_id: str, error_message: str, stage: OnboardingStage | None = None) -> None:
        with self._lock:
            snapshot = self._jobs.get(job_id)
            if snapshot is None:
                return

            now = _utc_now()
            failed_stage = stage or snapshot.current_stage or OnboardingStage.CONNECTING_TO_DATABASE
            for step in snapshot.steps:
                if step.stage == failed_stage:
                    step.state = OnboardingStepState.ERROR
                    step.message = error_message
                    step.started_at = step.started_at or now
                    step.completed_at = now
                    break

            snapshot.status = OnboardingJobState.FAILED
            snapshot.current_stage = failed_stage
            snapshot.error_message = error_message
            snapshot.finished_at = now
            snapshot.updated_at = now
            snapshot.logs.append(
                OnboardingLogEntry(
                    timestamp=now,
                    stage=failed_stage,
                    level=OnboardingLogLevel.ERROR,
                    message=error_message,
                )
            )
            snapshot.logs = snapshot.logs[-self._log_limit :]
            snapshot.progress_percent = self._progress_percent(snapshot)
            self._active_jobs_by_source.pop(snapshot.source_name.strip().lower(), None)

    def mark_completed(self, job_id: str, result: OnboardingResult) -> None:
        with self._lock:
            snapshot = self._jobs.get(job_id)
            if snapshot is None:
                return

            now = _utc_now()
            snapshot.status = OnboardingJobState.COMPLETED
            snapshot.result = result
            snapshot.error_message = None
            snapshot.finished_at = now
            snapshot.updated_at = now
            snapshot.current_stage = OnboardingStage.READY_FOR_REVIEW
            snapshot.progress_percent = 100
            self._active_jobs_by_source.pop(snapshot.source_name.strip().lower(), None)

    def submit(
        self,
        job_id: str,
        settings: Settings,
        repository: WorkspaceRepository,
        source: DiscoveredSource,
        *,
        sync_openmetadata: bool = False,
    ) -> None:
        self._executor.submit(
            self._run_job,
            job_id,
            settings,
            repository,
            source,
            sync_openmetadata,
        )

    def _run_job(
        self,
        job_id: str,
        settings: Settings,
        repository: WorkspaceRepository,
        source: DiscoveredSource,
        sync_openmetadata: bool,
    ) -> None:
        pipeline = OnboardingPipeline(settings, repository)
        try:
            output_dir = pipeline.run_source(
                source,
                sync_openmetadata=sync_openmetadata,
                progress=lambda update: self.apply_update(job_id, update),
            )
            self.apply_update(
                job_id,
                OnboardingProgressUpdate(
                    stage=OnboardingStage.GENERATING_REVIEW_QUESTIONS,
                    step_state=OnboardingStepState.RUNNING,
                    level=OnboardingLogLevel.INFO,
                    message="Generating review questions, semantic bundle, and chatbot package.",
                ),
            )
            pipeline.prepare_review_workspace(source.name)
            if not pipeline._review_assets_exist(source.name):
                raise OnboardingPipelineError(
                    "Onboarding finished introspection, but required review artifacts were not generated."
                )
            self.apply_update(
                job_id,
                OnboardingProgressUpdate(
                    stage=OnboardingStage.GENERATING_REVIEW_QUESTIONS,
                    step_state=OnboardingStepState.COMPLETED,
                    level=OnboardingLogLevel.SUCCESS,
                    message="Review workspace, semantic bundle, and package files are ready.",
                ),
            )
            self.apply_update(
                job_id,
                OnboardingProgressUpdate(
                    stage=OnboardingStage.READY_FOR_REVIEW,
                    step_state=OnboardingStepState.COMPLETED,
                    level=OnboardingLogLevel.SUCCESS,
                    message="Onboarding completed with real review artifacts available for publish and validation.",
                ),
            )
            repository.upsert_discovered_source(source)
            self.mark_completed(
                job_id,
                OnboardingResult(
                    source_name=source.name,
                    output_dir=str(output_dir),
                    bundle_dir=str(repository.semantic_bundle_dir(source.name)),
                    chatbot_package_dir=str(repository.source_dir(source.name) / CHATBOT_PACKAGE_DIRNAME),
                    wizard_url=f"/source/{source.name}",
                    api_wizard_url=f"/api/sources/{source.name}/semantic-bundle/questions",
                    download_url=f"/api/sources/{source.name}/json-zip",
                    chatbot_package_url=f"/chatbot/{source.name}",
                    chatbot_package_download_url=f"/api/sources/{source.name}/chatbot-package/zip",
                    legacy_review_url=f"/review/{source.name}",
                ),
            )
        except OnboardingPipelineError as exc:
            self.mark_failed(job_id, str(exc))
        except Exception as exc:  # pragma: no cover - defensive path for unexpected failures
            LOGGER.exception("Unexpected onboarding job failure for source '%s'", source.name)
            self.mark_failed(job_id, f"Unexpected onboarding failure: {exc}")

    def _apply_update_locked(self, snapshot: OnboardingJobSnapshot, update: OnboardingProgressUpdate) -> None:
        now = _utc_now()
        snapshot.status = OnboardingJobState.RUNNING
        snapshot.updated_at = now
        snapshot.current_stage = update.stage
        self._merge_counts(snapshot.counts, update.counts)

        for step in snapshot.steps:
            if step.stage != update.stage:
                continue
            if update.step_state is not None:
                step.state = update.step_state
                step.message = update.message
                if update.step_state == OnboardingStepState.RUNNING:
                    step.started_at = step.started_at or now
                if update.step_state in {OnboardingStepState.COMPLETED, OnboardingStepState.ERROR}:
                    step.started_at = step.started_at or now
                    step.completed_at = now
            elif update.message:
                step.message = update.message
            break

        snapshot.logs.append(
            OnboardingLogEntry(
                timestamp=now,
                stage=update.stage,
                level=update.level,
                message=update.message,
            )
        )
        snapshot.logs = snapshot.logs[-self._log_limit :]
        snapshot.progress_percent = self._progress_percent(snapshot)

    def _merge_counts(
        self,
        target: OnboardingProgressCounts,
        incoming: OnboardingProgressCounts,
    ) -> None:
        payload = incoming.model_dump(exclude_none=True)
        for key, value in payload.items():
            setattr(target, key, value)

    def _progress_percent(self, snapshot: OnboardingJobSnapshot) -> int:
        if snapshot.status == OnboardingJobState.COMPLETED:
            return 100

        total_steps = len(ONBOARDING_STAGE_ORDER)
        if total_steps == 0:
            return 0

        completed_steps = sum(1 for step in snapshot.steps if step.state == OnboardingStepState.COMPLETED)
        running_steps = sum(1 for step in snapshot.steps if step.state == OnboardingStepState.RUNNING)
        raw_progress = completed_steps + (0.5 if running_steps else 0.0)
        return max(3, min(99, round((raw_progress / total_steps) * 100)))


class OnboardingJobService:
    def __init__(
        self,
        settings: Settings,
        repository: WorkspaceRepository,
        store: InMemoryOnboardingJobStore,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.store = store

    def start_job(
        self,
        source: DiscoveredSource,
        *,
        sync_openmetadata: bool = False,
    ) -> OnboardingJobSnapshot:
        existing = self.store.find_active_job(source.name)
        if existing is not None:
            existing.reused_existing_job = True
            return existing

        created = self.store.create_job(source.name)
        self.store.apply_update(
            created.job_id,
            OnboardingProgressUpdate(
                stage=OnboardingStage.CONNECTING_TO_DATABASE,
                step_state=OnboardingStepState.RUNNING,
                level=OnboardingLogLevel.INFO,
                message="Starting onboarding job and validating database access.",
            ),
        )
        self.store.submit(
            created.job_id,
            self.settings,
            self.repository,
            source,
            sync_openmetadata=sync_openmetadata,
        )
        snapshot = self.store.get_job(created.job_id)
        if snapshot is None:  # pragma: no cover - defensive
            raise RuntimeError(f"Failed to create onboarding job for source '{source.name}'.")
        return snapshot

    def get_job(self, job_id: str) -> OnboardingJobSnapshot | None:
        return self.store.get_job(job_id)
