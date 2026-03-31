from __future__ import annotations

import typer

from app.artifacts.tag_bundle import TagBundleExporter
from app.core.settings import get_settings
from app.repositories.filesystem import WorkspaceRepository
from app.utils.serialization import read_json


app = typer.Typer(add_completion=False, help="Export a copy-ready TAG bundle from OpenMetaData outputs.")


@app.command()
def main(
    source: str = typer.Option(..., help="Source name."),
    domain: str | None = typer.Option(None, help="Target TAG domain name."),
    include_raw_exports: bool = typer.Option(True, help="Copy raw OpenMetaData JSON files into the bundle."),
) -> None:
    settings = get_settings()
    repository = WorkspaceRepository(settings.config_dir, settings.output_dir)
    semantic = repository.load_semantic_model(source)
    technical = repository.load_technical_metadata(source)
    questionnaire = None
    questionnaire_path = repository.source_dir(source) / "questionnaire.json"
    if questionnaire_path.exists():
        questionnaire = repository.load_questionnaire(source)

    bundle_dir = TagBundleExporter().export(
        semantic=semantic,
        technical=technical,
        questionnaire=questionnaire,
        source_output_dir=repository.source_dir(source),
        domain_name=domain,
        include_raw_exports=include_raw_exports,
    )
    manifest = read_json(bundle_dir / "bundle_manifest.json")
    typer.echo(f"Exported TAG bundle to {bundle_dir}")
    for relative_path in manifest.get("copy_targets", []):
        typer.echo(f"Safe copy target: {bundle_dir / relative_path}")


if __name__ == "__main__":
    app()
