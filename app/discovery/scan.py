from __future__ import annotations

from pathlib import Path

import typer

from app.core.settings import get_settings
from app.discovery.service import SourceDiscoveryService, local_only_report, report_to_paths
from app.utils.files import ensure_dir


app = typer.Typer(add_completion=False, help="Scan the local environment for database sources.")


@app.command()
def main(
    output_json: Path | None = typer.Option(None, help="Path to write discovered sources JSON."),
    output_yaml: Path | None = typer.Option(None, help="Path to write discovered sources YAML."),
    local_only: bool = typer.Option(False, help="Keep only local filesystem and localhost/socket sources."),
) -> None:
    settings = get_settings()
    ensure_dir(settings.config_dir)
    service = SourceDiscoveryService(
        roots=settings.scan_roots,
        max_file_bytes=settings.discovery_max_file_bytes,
        skip_dirs=settings.skip_dirs,
    )
    report = service.discover()
    if local_only:
        report = local_only_report(report)
    json_path = output_json or settings.discovered_sources_path
    yaml_path = output_yaml or settings.config_dir / "discovered_sources.yaml"
    report_to_paths(report, json_path, yaml_path)
    typer.echo(
        f"Discovered {len(report.discovered_sources)} sources. Wrote {json_path} and {yaml_path}."
    )


if __name__ == "__main__":
    app()
