from __future__ import annotations

import typer

from app.core.settings import get_settings
from app.engine.service import OnboardingEngine
from app.repositories.filesystem import WorkspaceRepository
from app.semantics.ambiguity import AmbiguityDetector


app = typer.Typer(add_completion=False, help="Generate a questionnaire for a source.")


@app.command()
def main(source: str = typer.Option(..., help="Source name.")) -> None:
    settings = get_settings()
    repository = WorkspaceRepository(settings.config_dir, settings.output_dir)
    semantic = repository.load_semantic_model(source)
    try:
        normalized = repository.load_normalized_metadata(source)
        technical = repository.load_technical_metadata(source)
        planner = OnboardingEngine(settings.output_dir).review_planner
        planner.annotate(
            normalized=normalized,
            technical=technical,
            semantic=semantic,
        )
        repository.save_semantic_model(semantic)
    except FileNotFoundError:
        pass
    questionnaire = AmbiguityDetector().generate_questions(semantic)
    path = repository.save_questionnaire(questionnaire)
    typer.echo(f"Wrote questionnaire to {path}")


if __name__ == "__main__":
    app()
