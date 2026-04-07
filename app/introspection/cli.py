from __future__ import annotations

import logging
from pathlib import Path

import typer

from app.introspection.env import list_database_url_presets, load_database_url_preset
from app.introspection.serializer import IntrospectionSerializer
from app.introspection.service import IntrospectionService
from app.core.logging import get_logger

app = typer.Typer(add_completion=False, help="Introspect database schema and generate deterministic artifacts.")


@app.command()
def introspect(
    url: str = typer.Argument(..., help="Database connection URL (e.g. sqlite:///test.db)"),
    output_dir: Path = typer.Option(
        Path("output/introspection"),
        "--output-dir",
        "-o",
        help="Directory to save canonical JSON artifacts",
    ),
    source_name: str = typer.Option(
        "default_source",
        "--source-name",
        "-n",
        help="Logical name of the database source",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable debug logging",
    ),
    schema: str | None = typer.Option(
        None,
        "--schema",
        help="Optional schema name to introspect instead of the default scope.",
    ),
    include_table: list[str] | None = typer.Option(
        None,
        "--include-table",
        help="Restrict introspection to one or more table names.",
    ),
) -> None:
    """
    Connects to the given database URL, extracts deterministic table and column 
    metadata, gathers basic sample values for enum detection, and serializes the 
    results into standard JSON artifacts (tables.json, columns.json, etc.).
    """
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO)
    logger = get_logger(__name__)

    try:
        typer.echo(f"Starting introspection for {source_name} at {url}...")
        service = IntrospectionService(
            connection_url=url,
            source_name=source_name,
            allow_tables=list(include_table or []),
            schema_name=schema,
        )
        
        metadata = service.introspect()
        if not metadata.connectivity_ok:
            typer.secho(f"Introspection failed: {metadata.connectivity_notes}", fg=typer.colors.RED)
            raise typer.Exit(code=1)

        serializer = IntrospectionSerializer(metadata, output_dir=output_dir)
        serializer.serialize()

        typer.secho(f"Successfully serialized introspection artifacts to {output_dir.resolve()}", fg=typer.colors.GREEN)

    except Exception as e:
        logger.exception("An error occurred during introspection.")
        typer.secho(f"Error: {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)


@app.command("list-env")
def list_env_presets(
    env_file: Path | None = typer.Option(
        None,
        "--env-file",
        help="Optional .env file to inspect. Defaults to TAG-Implementation/.env when available.",
    ),
) -> None:
    try:
        presets = list_database_url_presets(env_file)
    except FileNotFoundError as exc:
        typer.secho(f"Env file not found: {exc}", fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc

    if not presets:
        typer.secho("No database URL presets found.", fg=typer.colors.YELLOW)
        raise typer.Exit(code=1)

    typer.echo(f"Database URL presets from {presets[0].env_file}:")
    for preset in presets:
        typer.echo(
            f"- {preset.env_key} -> {preset.url_redacted} "
            f"(db={preset.database_name or '-'}, source={preset.source_name_hint})"
        )


@app.command("introspect-env")
def introspect_env(
    env_key: str = typer.Argument(..., help="Environment variable key that contains the database URL."),
    output_dir: Path = typer.Option(
        Path("output/introspection"),
        "--output-dir",
        "-o",
        help="Directory to save canonical JSON artifacts",
    ),
    env_file: Path | None = typer.Option(
        None,
        "--env-file",
        help="Optional .env file to inspect. Defaults to TAG-Implementation/.env when available.",
    ),
    source_name: str | None = typer.Option(
        None,
        "--source-name",
        "-n",
        help="Optional logical name override for the introspected source.",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable debug logging",
    ),
    schema: str | None = typer.Option(
        None,
        "--schema",
        help="Optional schema name to introspect instead of the default scope.",
    ),
    include_table: list[str] | None = typer.Option(
        None,
        "--include-table",
        help="Restrict introspection to one or more table names.",
    ),
) -> None:
    """
    Reads a database URL from a .env preset and writes only the deterministic Phase 1 artifacts.
    """
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO)
    logger = get_logger(__name__)

    try:
        preset = load_database_url_preset(env_key, env_file)
        resolved_source_name = str(source_name or preset.source_name_hint).strip() or preset.source_name_hint
        typer.echo(f"Starting introspection for {resolved_source_name} from {preset.env_key}...")
        typer.echo(f"Using {preset.url_redacted}")

        service = IntrospectionService(
            connection_url=preset.url,
            source_name=resolved_source_name,
            allow_tables=list(include_table or []),
            schema_name=schema,
        )
        metadata = service.introspect()
        if not metadata.connectivity_ok:
            typer.secho(f"Introspection failed: {metadata.connectivity_notes}", fg=typer.colors.RED)
            raise typer.Exit(code=1)

        serializer = IntrospectionSerializer(metadata, output_dir=output_dir)
        serializer.serialize()
        typer.secho(f"Successfully serialized introspection artifacts to {output_dir.resolve()}", fg=typer.colors.GREEN)
    except KeyError as exc:
        typer.secho(f"Unknown env key: {exc}", fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc
    except FileNotFoundError as exc:
        typer.secho(f"Env file not found: {exc}", fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc
    except Exception as exc:
        logger.exception("An error occurred during env-backed introspection.")
        typer.secho(f"Error: {exc}", fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc


if __name__ == "__main__":
    app()
