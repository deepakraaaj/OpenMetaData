from __future__ import annotations

from pathlib import Path

import typer

from app.core.settings import get_settings
from app.models.source import SourceConfigFile
from app.openmetadata.service import OpenMetadataService
from app.repositories.filesystem import WorkspaceRepository


app = typer.Typer(add_completion=False, help="Prepare or run OpenMetadata ingestion configs.")


@app.command()
def main(
    source: str | None = typer.Option(None, help="Single source name to sync."),
    prepare_only: bool = typer.Option(False, help="Only render ingestion YAML files."),
    config: Path | None = typer.Option(None, help="Optional explicit source config file."),
) -> None:
    settings = get_settings()
    repository = WorkspaceRepository(settings.config_dir, settings.output_dir)
    service = OpenMetadataService(settings)
    sources = SourceConfigFile.from_paths([config]).sources if config else repository.load_discovered_sources()
    if source:
        sources = [item for item in sources if item.name == source]
    output_dir = settings.output_dir / "openmetadata"
    paths = service.prepare_all(sources, output_dir)
    typer.echo(f"Prepared {len(paths)} OpenMetadata ingestion config(s) under {output_dir}")

    if prepare_only:
        return

    for path in paths:
        result = service.run_ingestion(path)
        if result is None:
            typer.echo(f"Skipped execution for {path.name}; ingestion CLI was not found.")
        else:
            typer.echo(f"{path.name}: exit_code={result.returncode}")


if __name__ == "__main__":
    app()
