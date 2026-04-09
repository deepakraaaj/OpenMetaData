"""FastAPI routes for the Phase 4 Onboarding Engine."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core.settings import get_settings
from app.engine.service import OnboardingEngine
from app.models.decision import ReviewMode
from app.models.review import BulkReviewAction
from app.models.semantic import TableReviewStatus
from app.onboard.pipeline import OnboardingPipeline
from app.repositories.filesystem import WorkspaceRepository

settings = get_settings()
repository = WorkspaceRepository(settings.config_dir, settings.output_dir)
engine = OnboardingEngine(settings.output_dir)

router = APIRouter(prefix="/api/engine", tags=["onboarding-engine"])


class AnswerRequest(BaseModel):
    gap_id: str
    answer: str
    reviewer: str | None = None


class ReviewModeRequest(BaseModel):
    review_mode: ReviewMode


class AIDefaultsRequest(BaseModel):
    domain_name: str | None = None
    table_name: str | None = None


@router.post("/{source_name}/initialize")
def initialize_engine(source_name: str) -> JSONResponse:
    """Prepare the review workspace from existing normalized + semantic data."""
    try:
        pipeline = OnboardingPipeline(settings, repository)
        pipeline.engine = engine
        state = pipeline.prepare_review_workspace(source_name)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=f"Source '{source_name}' has no normalized metadata. Run Phase 1 introspection first.",
        ) from exc
    return JSONResponse(state.model_dump(mode="json"))


@router.get("/{source_name}/state")
def get_engine_state(source_name: str) -> JSONResponse:
    """Return the cached knowledge state without recomputing it."""
    state = engine.get_state(source_name)
    if state is None:
        raise HTTPException(
            status_code=404,
            detail=f"No engine state for '{source_name}'. Call /initialize first.",
        )
    return JSONResponse(state.model_dump(mode="json"))


@router.get("/{source_name}/next-question")
def next_question(source_name: str) -> JSONResponse:
    """Get the highest-priority unresolved question."""
    try:
        normalized = repository.load_normalized_metadata(source_name)
    except FileNotFoundError:
        normalized = None

    question = engine.next_question(source_name, normalized=normalized)
    if question is None:
        return JSONResponse(
            {"status": "complete", "message": "All semantic gaps have been resolved."}
        )
    return JSONResponse(question.model_dump(mode="json"))


@router.post("/{source_name}/answer")
def submit_answer(source_name: str, request: AnswerRequest) -> JSONResponse:
    """Submit an answer to a specific gap and get the updated state."""
    try:
        normalized = repository.load_normalized_metadata(source_name)
    except FileNotFoundError:
        normalized = None

    try:
        state = engine.submit_answer(
            source_name,
            request.gap_id,
            request.answer,
            reviewer=request.reviewer,
            normalized=normalized,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse(state.model_dump(mode="json"))


@router.post("/{source_name}/review-mode")
def set_review_mode(source_name: str, request: ReviewModeRequest) -> JSONResponse:
    try:
        normalized = repository.load_normalized_metadata(source_name)
        semantic = repository.load_semantic_model(source_name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Missing semantic metadata for '{source_name}'.") from exc

    try:
        technical = repository.load_technical_metadata(source_name)
    except FileNotFoundError:
        technical = None

    try:
        domain_groups = repository.load_domain_groups(source_name)
    except (FileNotFoundError, ValueError):
        domain_groups = None

    try:
        state = engine.set_review_mode(
            source_name,
            request.review_mode,
            normalized,
            technical=technical,
            semantic=semantic,
            domain_groups=domain_groups,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse(state.model_dump(mode="json"))


@router.get("/{source_name}/ai-group")
def ai_group(source_name: str) -> JSONResponse:
    """Return deterministic table grouping derived from the schema intelligence layer."""

    try:
        cached_groups = repository.load_domain_groups(source_name)
    except (FileNotFoundError, ValueError):
        cached_groups = None

    if cached_groups:
        return JSONResponse({"source_name": source_name, "groups": cached_groups, "cached": True})

    try:
        normalized = repository.load_normalized_metadata(source_name)
        semantic_model = repository.load_semantic_model(source_name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Missing semantic metadata for '{source_name}'.") from exc

    try:
        technical_metadata = repository.load_technical_metadata(source_name)
    except FileNotFoundError:
        technical_metadata = None

    state = engine.get_state(source_name)
    if state is None:
        state = engine.initialize(source_name, normalized, semantic_model)

    engine.apply_review_plan(
        source_name,
        normalized,
        technical=technical_metadata,
        semantic=semantic_model,
    )
    repository.save_semantic_model(semantic_model)
    groups = engine.review_planner.groups_from_semantic(semantic_model)
    if groups:
        repository.save_domain_groups(source_name, groups)
    return JSONResponse({"source_name": source_name, "groups": groups, "cached": False})


@router.post("/{source_name}/ai-resolve")
def ai_resolve(source_name: str) -> JSONResponse:
    """Use the LLM to auto-resolve obvious semantic gaps."""
    from app.engine.ai_resolver import ai_resolve_gaps

    state = engine.get_state(source_name)
    if state is None:
        raise HTTPException(status_code=404, detail=f"No engine state for '{source_name}'.")

    gaps = state.unresolved_gaps
    answers = ai_resolve_gaps(state, gaps)

    # Apply each answer through the engine
    resolved_count = 0
    for gap_id, answer in answers.items():
        try:
            state = engine.submit_answer(source_name, gap_id, answer)
            resolved_count += 1
        except ValueError:
            continue

    return JSONResponse({
        "source_name": source_name,
        "resolved_count": resolved_count,
        "remaining_gaps": len(state.unresolved_gaps),
        "readiness": state.readiness.model_dump(mode="json"),
    })


@router.post("/{source_name}/ai-defaults")
def apply_ai_defaults(source_name: str, request: AIDefaultsRequest) -> JSONResponse:
    try:
        normalized = repository.load_normalized_metadata(source_name)
    except FileNotFoundError:
        normalized = None

    try:
        state = engine.apply_ai_defaults(
            source_name,
            domain_name=request.domain_name,
            table_name=request.table_name,
            normalized=normalized,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse(state.model_dump(mode="json"))

class ConfirmTableRequest(BaseModel):
    table_name: str
    reviewer: str | None = None


class ReviewTableRequest(BaseModel):
    table_name: str
    review_status: TableReviewStatus
    reviewer: str | None = None


class BulkReviewRequest(BaseModel):
    action: BulkReviewAction
    reviewer: str | None = None


@router.post("/{source_name}/review-table")
def review_table(source_name: str, request: ReviewTableRequest) -> JSONResponse:
    """Mark a table as needed or skipped for the remaining review flow."""
    try:
        normalized = repository.load_normalized_metadata(source_name)
    except FileNotFoundError:
        normalized = None

    try:
        state = engine.review_table(
            source_name,
            request.table_name,
            request.review_status,
            request.reviewer,
            normalized=normalized,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse(state.model_dump(mode="json"))


@router.post("/{source_name}/bulk-review")
def bulk_review(source_name: str, request: BulkReviewRequest) -> JSONResponse:
    try:
        normalized = repository.load_normalized_metadata(source_name)
    except FileNotFoundError:
        normalized = None

    try:
        state = engine.bulk_review(
            source_name,
            request.action,
            request.reviewer,
            normalized=normalized,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse(state.model_dump(mode="json"))


@router.post("/{source_name}/confirm-table")
def confirm_table(source_name: str, request: ConfirmTableRequest) -> JSONResponse:
    """Manually confirm a table's semantic mappings."""
    try:
        normalized = repository.load_normalized_metadata(source_name)
    except FileNotFoundError:
        normalized = None

    try:
        state = engine.confirm_table(
            source_name,
            request.table_name,
            request.reviewer,
            normalized=normalized,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse(state.model_dump(mode="json"))


@router.get("/{source_name}/export-llm-artifact")

def export_llm_artifact(source_name: str) -> JSONResponse:
    """Generates the optimized Chatbot context artifact."""
    from app.engine.export_artifact import generate_llm_domain_artifact

    state = engine.get_state(source_name)
    if state is None:
        raise HTTPException(status_code=404, detail=f"No engine state for '{source_name}'.")

    artifact = generate_llm_domain_artifact(state)
    return JSONResponse(artifact)
