from __future__ import annotations

import typer

from app.artifacts.generator import ArtifactGenerator
from app.core.settings import get_settings
from app.repositories.filesystem import WorkspaceRepository


app = typer.Typer(add_completion=False, help="Generate semantic artifacts for a source.")


@app.command()
def main(source: str = typer.Option(..., help="Source name.")) -> None:
    settings = get_settings()
    repository = WorkspaceRepository(settings.config_dir, settings.output_dir)
    semantic = repository.load_semantic_model(source)
    output_dir = repository.source_dir(source)
    ArtifactGenerator().generate(semantic, output_dir)
    typer.echo(f"Generated artifacts under {output_dir / 'artifacts'}")


if __name__ == "__main__":
    app()

