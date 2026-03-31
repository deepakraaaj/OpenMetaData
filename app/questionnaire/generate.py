from __future__ import annotations

import typer

from app.core.settings import get_settings
from app.repositories.filesystem import WorkspaceRepository
from app.semantics.ambiguity import AmbiguityDetector


app = typer.Typer(add_completion=False, help="Generate a questionnaire for a source.")


@app.command()
def main(source: str = typer.Option(..., help="Source name.")) -> None:
    settings = get_settings()
    repository = WorkspaceRepository(settings.config_dir, settings.output_dir)
    semantic = repository.load_semantic_model(source)
    questionnaire = AmbiguityDetector().generate_questions(semantic)
    path = repository.save_questionnaire(questionnaire)
    typer.echo(f"Wrote questionnaire to {path}")


if __name__ == "__main__":
    app()

