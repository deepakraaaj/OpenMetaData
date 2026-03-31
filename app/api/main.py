from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.core.settings import get_settings
from app.repositories.filesystem import WorkspaceRepository


settings = get_settings()
repository = WorkspaceRepository(settings.config_dir, settings.output_dir)
app = FastAPI(title="OpenMetadata Semantic Onboarding")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")


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

