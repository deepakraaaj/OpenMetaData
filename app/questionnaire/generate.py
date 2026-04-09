from __future__ import annotations

import typer

from app.core.settings import get_settings
from app.engine.service import OnboardingEngine
from app.questionnaire.builder import PolicyQuestionnaireBuilder
from app.repositories.filesystem import WorkspaceRepository


app = typer.Typer(add_completion=False, help="Generate a questionnaire for a source.")


@app.command()
def main(source: str = typer.Option(..., help="Source name.")) -> None:
    settings = get_settings()
    repository = WorkspaceRepository(settings.config_dir, settings.output_dir)
    semantic = repository.load_semantic_model(source)
    try:
        normalized = repository.load_normalized_metadata(source)
        technical = repository.load_technical_metadata(source)
        engine = OnboardingEngine(settings.output_dir)
        state = engine.apply_review_plan(
            source,
            normalized,
            technical=technical,
            semantic=semantic,
        )
    except FileNotFoundError:
        state = engine.get_state(source) if "engine" in locals() else None
        if state is None:
            state = OnboardingEngine(settings.output_dir).get_state(source)
    if state is None:
        raise typer.BadParameter(f"No knowledge state or semantic model found for '{source}'.")
    questionnaire = PolicyQuestionnaireBuilder().build(state)
    path = repository.save_questionnaire(questionnaire)
    typer.echo(f"Wrote questionnaire to {path}")


if __name__ == "__main__":
    app()
