from __future__ import annotations

import typer

from app.artifacts.generator import ArtifactGenerator
from app.artifacts.semantic_bundle import SemanticBundleExporter
from app.core.settings import get_settings
from app.repositories.filesystem import WorkspaceRepository


app = typer.Typer(add_completion=False, help="Generate semantic artifacts for a source.")


@app.command()
def main(source: str = typer.Option(..., help="Source name.")) -> None:
    settings = get_settings()
    repository = WorkspaceRepository(settings.config_dir, settings.output_dir)
    semantic = repository.load_semantic_model(source)
    technical = repository.load_technical_metadata(source)
    questionnaire = None
    questionnaire_path = repository.source_dir(source) / "questionnaire.json"
    if questionnaire_path.exists():
        questionnaire = repository.load_questionnaire(source)
    output_dir = repository.source_dir(source)
    ArtifactGenerator().generate(semantic, output_dir)
    SemanticBundleExporter().write(
        semantic=semantic,
        technical=technical,
        questionnaire=questionnaire,
        source_output_dir=output_dir,
        domain_name=semantic.domain,
    )
    typer.echo(f"Generated artifacts under {output_dir / 'artifacts'}")


if __name__ == "__main__":
    app()
