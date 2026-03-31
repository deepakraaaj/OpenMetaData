from __future__ import annotations

import typer

from app.artifacts.generator import ArtifactGenerator
from app.core.settings import get_settings
from app.repositories.filesystem import WorkspaceRepository
from app.retrieval.service import RetrievalContextBuilder


app = typer.Typer(add_completion=False, help="Build and print an LLM retrieval context package.")


@app.command()
def main(
    source: str = typer.Option(..., help="Source name."),
    question: str = typer.Option(..., help="Natural-language question to evaluate."),
) -> None:
    settings = get_settings()
    repository = WorkspaceRepository(settings.config_dir, settings.output_dir)
    semantic = repository.load_semantic_model(source)
    package = RetrievalContextBuilder().build(semantic, question)
    output_dir = repository.source_dir(source)
    ArtifactGenerator().write_context_package(package, output_dir)
    typer.echo(package.model_dump_json(indent=2))


if __name__ == "__main__":
    app()

