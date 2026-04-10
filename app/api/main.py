from __future__ import annotations

import io
from typing import Any
from pathlib import Path
import zipfile

from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from app.api.semantic_bundle_questions import build_semantic_bundle_questions
from app.api.engine_routes import router as engine_router
from app.artifacts.chatbot_package import CHATBOT_PACKAGE_DIRNAME, ChatbotPackageExporter
from app.artifacts.semantic_bundle import SEMANTIC_BUNDLE_FILES, SemanticBundleExporter
from app.artifacts.tag_bundle import TagBundleExporter
from app.core.settings import get_settings
from app.discovery.service import build_source_name, parse_connection_url
from app.introspection.env import list_database_url_presets, load_database_url_preset, resolve_env_file
from app.introspection.service import IntrospectionService
from app.models.artifacts import LLMContextPackage
from app.models.common import DatabaseType
from app.models.simple_onboarding import SimpleOnboardingRequest
from app.models.semantic import SemanticSourceModel
from app.models.state import KnowledgeState
from app.models.source import DiscoveredSource
from app.onboard.simple_flow import SimpleOnboardingService
from app.repositories.filesystem import WorkspaceRepository
from app.retrieval.service import RetrievalContextBuilder
from app.services.onboarding_jobs import InMemoryOnboardingJobStore, OnboardingJobService
from app.utils.serialization import read_json


settings = get_settings()
repository = WorkspaceRepository(settings.config_dir, settings.output_dir)
onboarding_job_store = InMemoryOnboardingJobStore()
app = FastAPI(title="OpenMetadata Semantic Onboarding")
app.include_router(engine_router)
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.admin_origins or ["*"],
    allow_origin_regex=settings.admin_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class BundleFileUpdateRequest(BaseModel):
    payload: dict = Field(default_factory=dict)


class PublishBundleRequest(BaseModel):
    domain_name: str | None = None


class UrlOnboardingRequest(BaseModel):
    db_url: str
    source_name: str | None = None
    domain_name: str | None = None
    description: str | None = None
    approved_use_cases: list[str] = Field(default_factory=list)
    allow_tables: list[str] = Field(default_factory=list)
    protected_tables: list[str] = Field(default_factory=list)


class DeterministicIntrospectionUrlRequest(BaseModel):
    db_url: str
    source_name: str | None = None
    schema_name: str | None = None
    allow_tables: list[str] = Field(default_factory=list)


class DeterministicIntrospectionEnvRequest(BaseModel):
    env_key: str
    env_file: str | None = None
    source_name: str | None = None
    schema_name: str | None = None
    allow_tables: list[str] = Field(default_factory=list)


def get_onboarding_job_service() -> OnboardingJobService:
    return OnboardingJobService(settings, repository, onboarding_job_store)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/sources")
def list_sources() -> JSONResponse:
    try:
        sources = repository.load_discovered_sources()
    except FileNotFoundError:
        sources = []
    return JSONResponse([source.model_dump(mode="json", exclude_none=True) for source in sources])


@app.get("/sources/{source_name}")
def get_source(source_name: str) -> JSONResponse:
    try:
        semantic = repository.load_semantic_model(source_name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Source `{source_name}` has not been onboarded.") from exc
    return JSONResponse(semantic.model_dump(mode="json", exclude_none=True))


@app.get("/", response_class=HTMLResponse)
def review_index(request: Request) -> HTMLResponse:
    sources = _source_cards()
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "request": request,
            "sources": sources,
        },
    )


@app.get("/review/{source_name}", response_class=HTMLResponse)
def review_source(request: Request, source_name: str) -> HTMLResponse:
    try:
        semantic = repository.load_semantic_model(source_name)
        questionnaire = repository.load_questionnaire(source_name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Source `{source_name}` has not been onboarded.") from exc
    return templates.TemplateResponse(
        request,
        "source.html",
        {
            "request": request,
            "semantic": semantic,
            "questionnaire": questionnaire,
        },
    )


@app.get("/technical/{source_name}", response_class=HTMLResponse)
def technical_source(request: Request, source_name: str) -> HTMLResponse:
    try:
        technical = repository.load_technical_metadata(source_name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Source `{source_name}` has not been introspected yet.") from exc

    source_record = _discovered_source_by_name(source_name)
    table_rows: list[dict[str, Any]] = []
    relationship_count = 0
    enum_candidate_count = 0
    sample_table_count = 0
    timestamp_table_count = 0

    for schema in technical.schemas:
        for table in schema.tables:
            sample_table_count += 1 if table.sample_rows else 0
            timestamp_table_count += 1 if table.timestamp_columns else 0
            relationship_count += len(table.foreign_keys) + len(table.candidate_joins)
            enum_candidate_count += sum(1 for column in table.columns if column.enum_values)
            table_rows.append(
                {
                    "schema_name": schema.schema_name,
                    "table_name": table.table_name,
                    "row_count": table.estimated_row_count,
                    "primary_key": ", ".join(table.primary_key) or "None",
                    "foreign_key_count": len(table.foreign_keys),
                    "candidate_join_count": len(table.candidate_joins),
                    "enum_candidate_count": sum(1 for column in table.columns if column.enum_values),
                    "sample_column_count": sum(1 for column in table.columns if column.sample_values),
                    "timestamp_columns": table.timestamp_columns,
                    "status_columns": table.status_columns,
                }
            )

    table_rows.sort(key=lambda item: (item["schema_name"], item["table_name"]))
    summary = dict(technical.source_summary or {})
    summary.setdefault("schema_count", len(technical.schemas))
    summary.setdefault("table_count", len(table_rows))
    summary.setdefault("column_count", sum(len(table.columns) for schema in technical.schemas for table in schema.tables))
    summary["relationship_count"] = relationship_count
    summary["enum_candidate_count"] = enum_candidate_count
    summary["tables_with_samples"] = sample_table_count
    summary["tables_with_timestamps"] = timestamp_table_count

    has_semantic = (repository.source_dir(source_name) / "semantic_model.json").exists()
    has_chatbot_package = (repository.source_dir(source_name) / CHATBOT_PACKAGE_DIRNAME / "manifest.json").exists()
    return templates.TemplateResponse(
        request,
        "technical.html",
        {
            "request": request,
            "source_name": source_name,
            "technical": technical,
            "source_record": source_record,
            "summary": summary,
            "table_rows": table_rows[:40],
            "has_semantic": has_semantic,
            "has_chatbot_package": has_chatbot_package,
        },
    )


@app.get("/api/sources")
def api_list_sources() -> JSONResponse:
    return list_sources()


@app.get("/api/sources/{source_name}")
def api_get_source(source_name: str) -> JSONResponse:
    return get_source(source_name)


@app.post("/api/onboarding/url")
def onboard_from_db_url(request: UrlOnboardingRequest) -> JSONResponse:
    db_url = str(request.db_url or "").strip()
    if not db_url:
        raise HTTPException(status_code=400, detail="db_url is required.")

    connection = parse_connection_url(db_url)
    if str(connection.type.value) == "unknown":
        raise HTTPException(status_code=400, detail="Unsupported or invalid database URL.")

    source_name = build_source_name(
        connection,
        preferred_name=str(request.source_name or request.domain_name or "").strip() or None,
    )
    source = DiscoveredSource(
        name=source_name,
        connection=connection,
        description=str(request.description or "").strip() or f"Manual onboarding for {source_name}",
        tags=["manual", "url_onboarding"],
        allow_tables=[str(item).strip() for item in request.allow_tables if str(item).strip()],
        protected_tables=[str(item).strip() for item in request.protected_tables if str(item).strip()],
        approved_use_cases=[str(item).strip() for item in request.approved_use_cases if str(item).strip()],
        notes=["Created from direct DB URL onboarding request."],
    )

    job = get_onboarding_job_service().start_job(source, sync_openmetadata=False)
    return JSONResponse(job.model_dump(mode="json", exclude_none=True), status_code=202)


@app.post("/api/onboarding/simple")
def simple_onboarding(request: SimpleOnboardingRequest) -> JSONResponse:
    try:
        payload = SimpleOnboardingService(repository=repository).build(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse(payload.model_dump(mode="json", exclude_none=True))


@app.get("/api/onboarding/jobs/{job_id}")
def get_onboarding_job(job_id: str) -> JSONResponse:
    job = get_onboarding_job_service().get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Onboarding job `{job_id}` was not found.")
    return JSONResponse(job.model_dump(mode="json", exclude_none=True))


@app.get("/api/introspection/env/presets")
def list_introspection_env_presets(env_file: str | None = None) -> JSONResponse:
    try:
        presets = list_database_url_presets(env_file)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Env file not found: {exc}") from exc

    resolved_file = str(resolve_env_file(env_file)) if presets else str(resolve_env_file(env_file))
    return JSONResponse(
        {
            "env_file": resolved_file,
            "presets": [preset.to_dict() for preset in presets],
        }
    )


@app.post("/api/introspection/url")
def introspect_from_db_url(request: DeterministicIntrospectionUrlRequest) -> JSONResponse:
    db_url = str(request.db_url or "").strip()
    if not db_url:
        raise HTTPException(status_code=400, detail="db_url is required.")

    connection = parse_connection_url(db_url)
    if connection.type == DatabaseType.unknown:
        raise HTTPException(status_code=400, detail="Unsupported or invalid database URL.")

    source_name = build_source_name(
        connection,
        preferred_name=str(request.source_name or "").strip() or None,
    )
    if request.schema_name:
        connection.schema_name = str(request.schema_name).strip()
    source = DiscoveredSource(
        name=source_name,
        connection=connection,
        description=f"Deterministic introspection for {source_name}",
        tags=["manual", "phase1_only", "url_introspection"],
        allow_tables=[str(item).strip() for item in request.allow_tables if str(item).strip()],
        approved_use_cases=["deterministic_introspection"],
        notes=["Created from deterministic DB URL introspection request."],
    )
    return _run_deterministic_introspection(
        source=source,
        db_url=db_url,
        schema_name=request.schema_name,
        source_details={
            "mode": "url",
            "db_type": connection.type.value,
            "database_name": connection.resolved_database,
        },
    )


@app.post("/api/introspection/env")
def introspect_from_env_preset(request: DeterministicIntrospectionEnvRequest) -> JSONResponse:
    try:
        preset = load_database_url_preset(request.env_key, request.env_file)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Env file not found: {exc}") from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown env key `{exc.args[0]}`.") from exc

    connection = parse_connection_url(preset.url)
    source_name = str(request.source_name or preset.source_name_hint).strip() or preset.source_name_hint
    if request.schema_name:
        connection.schema_name = str(request.schema_name).strip()
    source = DiscoveredSource(
        name=source_name,
        connection=connection,
        description=f"Deterministic introspection for {source_name} from env preset",
        tags=["manual", "phase1_only", "env_introspection"],
        allow_tables=[str(item).strip() for item in request.allow_tables if str(item).strip()],
        approved_use_cases=["deterministic_introspection"],
        notes=[f"Created from env preset {preset.env_key}."],
    )
    return _run_deterministic_introspection(
        source=source,
        db_url=preset.url,
        schema_name=request.schema_name,
        source_details={
            "mode": "env",
            "env_key": preset.env_key,
            "env_file": str(preset.env_file),
            "url_redacted": preset.url_redacted,
            "db_type": preset.db_type.value,
            "database_name": preset.database_name,
        },
    )


@app.get("/api/sources/{source_name}/semantic-bundle")
def get_semantic_bundle(source_name: str) -> JSONResponse:
    try:
        bundle = repository.load_semantic_bundle(source_name)
    except FileNotFoundError:
        bundle_dir = _rebuild_semantic_bundle(source_name)
        bundle = repository.load_semantic_bundle(source_name)
        return JSONResponse(
            {
                "source_name": source_name,
                "bundle_dir": str(bundle_dir),
                "files": bundle,
            }
        )
    return JSONResponse(
        {
            "source_name": source_name,
            "bundle_dir": str(repository.semantic_bundle_dir(source_name)),
            "files": bundle,
        }
    )


@app.get("/api/sources/{source_name}/semantic-bundle/questions")
def get_semantic_bundle_questions(source_name: str) -> JSONResponse:
    try:
        bundle = repository.load_semantic_bundle(source_name)
    except FileNotFoundError:
        _rebuild_semantic_bundle(source_name)
        bundle = repository.load_semantic_bundle(source_name)
    return JSONResponse(
        {
            "source_name": source_name,
            "sections": build_semantic_bundle_questions(bundle),
        }
    )


@app.put("/api/sources/{source_name}/semantic-bundle/{file_name}")
def update_semantic_bundle_file(source_name: str, file_name: str, request: BundleFileUpdateRequest) -> JSONResponse:
    safe_name = str(file_name or "").strip()
    if safe_name not in SEMANTIC_BUNDLE_FILES:
        raise HTTPException(status_code=404, detail=f"Unknown semantic bundle file `{safe_name}`.")
    try:
        path = repository.save_semantic_bundle_file(source_name, safe_name, request.payload)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown semantic bundle file `{safe_name}`.") from exc
    return JSONResponse(
        {
            "source_name": source_name,
            "file_name": safe_name,
            "path": str(path),
            "status": "saved",
        }
    )


@app.post("/api/sources/{source_name}/semantic-bundle/rebuild")
def rebuild_semantic_bundle(source_name: str) -> JSONResponse:
    bundle_dir = _rebuild_semantic_bundle(source_name)
    return JSONResponse(
        {
            "source_name": source_name,
            "bundle_dir": str(bundle_dir),
            "status": "rebuilt",
        }
    )


@app.post("/api/sources/{source_name}/semantic-bundle/publish")
def publish_semantic_bundle(source_name: str, request: PublishBundleRequest) -> JSONResponse:
    try:
        bundle_dir = repository.semantic_bundle_dir(source_name)
        if not bundle_dir.exists():
            bundle_dir = _rebuild_semantic_bundle(source_name)
        business_semantics = repository.load_semantic_bundle_file(source_name, "business_semantics.json")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Source `{source_name}` has not been onboarded.") from exc

    state_path = repository.source_dir(source_name) / "knowledge_state.json"
    if state_path.exists():
        state = KnowledgeState.model_validate(read_json(state_path))
        if not state.readiness.publish_ready:
            reasons = state.readiness.publish_notes or state.readiness.readiness_notes or [
                "Publish blockers still need confirmation.",
            ]
            raise HTTPException(status_code=409, detail=" ".join(reasons))

    domain_name = str(request.domain_name or business_semantics.get("domain_name") or source_name).strip()
    if not domain_name:
        raise HTTPException(status_code=400, detail="A target domain name is required.")

    target_domain_dir = settings.tag_domains_dir / domain_name
    target_dir = SemanticBundleExporter().publish(
        bundle_dir=bundle_dir,
        target_domain_dir=target_domain_dir,
    )
    return JSONResponse(
        {
            "source_name": source_name,
            "domain_name": domain_name,
            "published_to": str(target_dir),
            "status": "published",
        }
    )


@app.get("/chatbot/{source_name}")
def chatbot_package_overview(source_name: str) -> RedirectResponse:
    package_dir = _rebuild_chatbot_package(source_name)
    overview_path = package_dir / "visuals" / "overview.html"
    if not overview_path.exists():
        raise HTTPException(status_code=404, detail=f"Chatbot package overview for `{source_name}` is missing.")
    return RedirectResponse(url=f"/chatbot-files/{source_name}/visuals/overview.html")


@app.get("/chatbot-files/{source_name}/{file_path:path}")
def chatbot_package_file(source_name: str, file_path: str) -> FileResponse:
    package_dir = _rebuild_chatbot_package(source_name).resolve()
    target_path = (package_dir / file_path).resolve()
    try:
        target_path.relative_to(package_dir)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Unknown package file.") from exc
    if not target_path.exists() or not target_path.is_file():
        raise HTTPException(status_code=404, detail="Unknown package file.")
    return FileResponse(target_path)


@app.get("/api/sources/{source_name}/chatbot-package")
def get_chatbot_package(source_name: str) -> JSONResponse:
    package_dir = _rebuild_chatbot_package(source_name)
    manifest = read_json(package_dir / "manifest.json")
    return JSONResponse(
        {
            "source_name": source_name,
            "package_dir": str(package_dir),
            "manifest": manifest,
            "overview_url": f"/chatbot/{source_name}",
            "download_url": f"/api/sources/{source_name}/chatbot-package/zip",
        }
    )


@app.get("/api/sources/{source_name}/chatbot-package/zip")
def download_chatbot_package_zip(source_name: str) -> StreamingResponse:
    package_dir = _rebuild_chatbot_package(source_name)
    return _stream_directory_zip(
        directory=package_dir,
        filename=f"{source_name}_chatbot_package.zip",
    )


@app.get("/api/sources/{source_name}/json-zip")
def download_source_json_zip(source_name: str) -> StreamingResponse:
    source_dir = repository.source_dir(source_name)
    if not source_dir.exists():
        raise HTTPException(status_code=404, detail=f"Source `{source_name}` has not been onboarded.")

    return _stream_directory_zip(
        directory=source_dir,
        filename=f"{source_name}_json_bundle.zip",
        only_json=True,
    )


def _rebuild_semantic_bundle(source_name: str) -> Path:
    try:
        semantic = repository.load_semantic_model(source_name)
        technical = repository.load_technical_metadata(source_name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Source `{source_name}` has not been onboarded.") from exc

    questionnaire = None
    questionnaire_path = repository.source_dir(source_name) / "questionnaire.json"
    if questionnaire_path.exists():
        questionnaire = repository.load_questionnaire(source_name)

    return SemanticBundleExporter().write(
        semantic=semantic,
        technical=technical,
        questionnaire=questionnaire,
        source_output_dir=repository.source_dir(source_name),
        domain_name=semantic.domain,
    )


def _rebuild_chatbot_package(source_name: str) -> Path:
    source_dir = repository.source_dir(source_name)
    if not source_dir.exists():
        raise HTTPException(status_code=404, detail=f"Source `{source_name}` has not been onboarded.")

    try:
        semantic = repository.load_semantic_model(source_name)
        technical = repository.load_technical_metadata(source_name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Source `{source_name}` has not been onboarded.") from exc

    questionnaire = None
    questionnaire_path = source_dir / "questionnaire.json"
    if questionnaire_path.exists():
        questionnaire = repository.load_questionnaire(source_name)

    semantic_bundle_dir = repository.semantic_bundle_dir(source_name)
    if not semantic_bundle_dir.exists():
        semantic_bundle_dir = _rebuild_semantic_bundle(source_name)

    context_package = _load_context_package(source_name, semantic)

    tag_bundle_dir = source_dir / "tag_bundle" / str(semantic.domain or semantic.source_name).strip().lower().replace(" ", "_")
    if not tag_bundle_dir.exists():
        tag_bundle_dir = TagBundleExporter().export(
            semantic=semantic,
            technical=technical,
            questionnaire=questionnaire,
            source_output_dir=source_dir,
            domain_name=semantic.domain,
        )

    try:
        domain_groups = repository.load_domain_groups(source_name)
    except (FileNotFoundError, ValueError):
        domain_groups = {}

    return ChatbotPackageExporter().export(
        semantic=semantic,
        technical=technical,
        questionnaire=questionnaire,
        context_package=context_package,
        source_output_dir=source_dir,
        semantic_bundle_dir=semantic_bundle_dir,
        tag_bundle_dir=tag_bundle_dir,
        domain_groups=domain_groups,
        domain_name=semantic.domain,
    )


def _load_context_package(source_name: str, semantic: SemanticSourceModel) -> LLMContextPackage:
    context_path = repository.source_dir(source_name) / "llm_context_package.json"
    if context_path.exists():
        return LLMContextPackage.model_validate(read_json(context_path))

    package = RetrievalContextBuilder().build(
        semantic,
        question=f"What does {source_name} contain and how should it be queried safely?",
    )
    return package


def _stream_directory_zip(
    *,
    directory: Path,
    filename: str,
    only_json: bool = False,
) -> StreamingResponse:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(directory.rglob("*")):
            if not path.is_file() or path.name.endswith(".zip"):
                continue
            if only_json and path.suffix.lower() != ".json":
                continue
            archive.write(path, arcname=str(path.relative_to(directory)))
    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _run_deterministic_introspection(
    *,
    source: DiscoveredSource,
    db_url: str,
    schema_name: str | None = None,
    source_details: dict[str, str | None],
) -> JSONResponse:
    service = IntrospectionService(
        connection_url=db_url,
        source_name=source.name,
        allow_tables=source.allow_tables,
        schema_name=str(schema_name or "").strip() or None,
    )
    metadata = service.introspect()
    if not metadata.connectivity_ok:
        detail = "; ".join(note for note in metadata.connectivity_notes if str(note).strip())
        raise HTTPException(status_code=422, detail=detail or "Database introspection failed.")

    repository.save_technical_metadata(metadata)
    repository.upsert_discovered_source(source)
    output_dir = repository.source_dir(source.name)

    return JSONResponse(
        {
            "status": "ok",
            "phase": "phase_1_deterministic_core",
            "source_name": source.name,
            "output_dir": str(output_dir),
            "artifacts": sorted(path.name for path in output_dir.glob("*.json")),
            "summary": metadata.source_summary,
            "download_url": f"/api/sources/{source.name}/json-zip",
            "source": source_details,
        }
    )


def _discovered_source_by_name(source_name: str) -> DiscoveredSource | None:
    try:
        sources = repository.load_discovered_sources()
    except FileNotFoundError:
        return None
    for source in sources:
        if source.name == source_name:
            return source
    return None


def _source_cards() -> list[dict[str, Any]]:
    try:
        sources = repository.load_discovered_sources()
    except FileNotFoundError:
        return []

    cards: list[dict[str, Any]] = []
    for source in sources:
        source_dir = repository.source_dir(source.name)
        has_technical = (source_dir / "technical_metadata.json").exists()
        has_semantic = (source_dir / "semantic_model.json").exists()
        summary: dict[str, Any] = {}
        if has_technical:
            try:
                technical = repository.load_technical_metadata(source.name)
                summary = dict(technical.source_summary or {})
            except FileNotFoundError:
                summary = {}

        if has_semantic:
            action_href = f"/review/{source.name}"
            action_label = "Semantic Review"
            status = "Semantic"
        elif has_technical:
            action_href = f"/technical/{source.name}"
            action_label = "Technical Snapshot"
            status = "Phase 1"
        else:
            action_href = ""
            action_label = ""
            status = "Detected"

        cards.append(
            {
                "name": source.name,
                "db_type": source.connection.type.value,
                "database_name": source.connection.database,
                "description": source.description or "Discovered local data source",
                "status": status,
                "action_href": action_href,
                "action_label": action_label,
                "has_action": bool(action_href),
                "table_count": summary.get("table_count"),
                "column_count": summary.get("column_count"),
            }
        )
    return cards
