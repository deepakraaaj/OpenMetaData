from __future__ import annotations

from pathlib import Path

import typer

from app.core.settings import get_settings
from app.discovery.service import SourceDiscoveryService
from app.models.source import SourceConfigFile
from app.onboard.pipeline import OnboardingPipeline
from app.repositories.filesystem import WorkspaceRepository


app = typer.Typer(add_completion=False, help="Run the onboarding pipeline for one or more sources.")


def _resolve_sources(
    all_discovered: bool,
    config: Path | None,
    source_name: str | None,
) -> tuple[list, WorkspaceRepository]:
    settings = get_settings()
    repository = WorkspaceRepository(settings.config_dir, settings.output_dir)

    if config:
        sources = SourceConfigFile.from_paths([config]).sources
    else:
        try:
            sources = repository.load_discovered_sources()
        except FileNotFoundError:
            discovery = SourceDiscoveryService(
                roots=settings.scan_roots,
                max_file_bytes=settings.discovery_max_file_bytes,
                skip_dirs=settings.skip_dirs,
            )
            report = discovery.discover()
            repository.save_discovery_report(report)
            sources = report.discovered_sources

    if source_name:
        sources = [source for source in sources if source.name == source_name]
    elif not all_discovered and sources:
        sources = sources[:1]

    return sources, repository


@app.command()
def main(
    config: Path | None = typer.Option(None, help="Optional explicit source config file."),
    all_discovered: bool = typer.Option(False, help="Run against all discovered sources."),
    source: str | None = typer.Option(None, help="Run for a single source name."),
    sync_openmetadata: bool = typer.Option(False, help="Prepare and execute OpenMetadata ingestion."),
) -> None:
    settings = get_settings()
    sources, repository = _resolve_sources(all_discovered=all_discovered, config=config, source_name=source)
    pipeline = OnboardingPipeline(settings, repository)
    if not sources:
        raise typer.BadParameter("No sources available to onboard.")

    for item in sources:
        output_dir = pipeline.run_source(item, sync_openmetadata=sync_openmetadata)
        typer.echo(f"Onboarded {item.name} -> {output_dir}")


if __name__ == "__main__":
    app()

