from __future__ import annotations

import typer

from app.artifacts.chatbot_package import ChatbotPackageExporter
from app.artifacts.tag_bundle import TagBundleExporter
from app.core.settings import get_settings
from app.models.artifacts import LLMContextPackage
from app.repositories.filesystem import WorkspaceRepository
from app.retrieval.service import RetrievalContextBuilder
from app.utils.serialization import read_json


app = typer.Typer(add_completion=False, help="Export a chatbot-ready package from OpenMetaData outputs.")


@app.command()
def main(
    source: str = typer.Option(..., help="Source name."),
    domain: str | None = typer.Option(None, help="Override target domain name."),
) -> None:
    settings = get_settings()
    repository = WorkspaceRepository(settings.config_dir, settings.output_dir)
    source_dir = repository.source_dir(source)

    semantic = repository.load_semantic_model(source)
    technical = repository.load_technical_metadata(source)

    questionnaire = None
    questionnaire_path = source_dir / "questionnaire.json"
    if questionnaire_path.exists():
        questionnaire = repository.load_questionnaire(source)

    bundle_dir = repository.semantic_bundle_dir(source)
    if not bundle_dir.exists():
        raise typer.BadParameter(
            f"Semantic bundle for '{source}' does not exist. Rebuild onboarding artifacts before exporting."
        )

    context_path = source_dir / "llm_context_package.json"
    if context_path.exists():
        context_package = LLMContextPackage.model_validate(read_json(context_path))
    else:
        context_package = RetrievalContextBuilder().build(
            semantic,
            question=f"What does {source} contain and how should it be queried safely?",
        )

    try:
        domain_groups = repository.load_domain_groups(source)
    except (FileNotFoundError, ValueError):
        domain_groups = {}

    tag_bundle_dir = TagBundleExporter().export(
        semantic=semantic,
        technical=technical,
        questionnaire=questionnaire,
        source_output_dir=source_dir,
        domain_name=domain or semantic.domain,
    )

    package_dir = ChatbotPackageExporter().export(
        semantic=semantic,
        technical=technical,
        questionnaire=questionnaire,
        context_package=context_package,
        source_output_dir=source_dir,
        semantic_bundle_dir=bundle_dir,
        tag_bundle_dir=tag_bundle_dir,
        domain_groups=domain_groups,
        domain_name=domain or semantic.domain,
    )
    typer.echo(f"Exported chatbot package to {package_dir}")
    typer.echo(f"Open {package_dir / 'visuals' / 'overview.html'} for the visual summary")


if __name__ == "__main__":
    app()
