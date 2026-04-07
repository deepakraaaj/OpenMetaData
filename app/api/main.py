from __future__ import annotations

import io
from pathlib import Path
import zipfile

from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from app.api.semantic_bundle_questions import build_semantic_bundle_questions
from app.artifacts.semantic_bundle import SEMANTIC_BUNDLE_FILES, SemanticBundleExporter
from app.core.settings import get_settings
from app.discovery.service import build_source_name, parse_connection_url
from app.models.source import DiscoveredSource
from app.onboard.pipeline import OnboardingPipeline, OnboardingPipelineError
from app.repositories.filesystem import WorkspaceRepository


settings = get_settings()
repository = WorkspaceRepository(settings.config_dir, settings.output_dir)
app = FastAPI(title="OpenMetadata Semantic Onboarding")
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
    try:
        sources = repository.load_discovered_sources()
    except FileNotFoundError:
        sources = []
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

    pipeline = OnboardingPipeline(settings, repository)
    try:
        output_dir = pipeline.run_source(source, sync_openmetadata=False)
    except OnboardingPipelineError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    repository.upsert_discovered_source(source)

    return JSONResponse(
        {
            "status": "ok",
            "source_name": source_name,
            "output_dir": str(output_dir),
            "bundle_dir": str(repository.semantic_bundle_dir(source_name)),
            "wizard_url": f"/source/{source_name}",
            "api_wizard_url": f"/api/sources/{source_name}/semantic-bundle/questions",
            "download_url": f"/api/sources/{source_name}/json-zip",
        }
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


@app.get("/api/sources/{source_name}/json-zip")
def download_source_json_zip(source_name: str) -> StreamingResponse:
    source_dir = repository.source_dir(source_name)
    if not source_dir.exists():
        raise HTTPException(status_code=404, detail=f"Source `{source_name}` has not been onboarded.")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source_dir.rglob("*.json")):
            if path.name.endswith(".zip"):
                continue
            archive.write(path, arcname=str(path.relative_to(source_dir)))
    buffer.seek(0)

    filename = f"{source_name}_json_bundle.zip"
    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
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
