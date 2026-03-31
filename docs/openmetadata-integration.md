# OpenMetadata Integration

## Local stack

The repository includes a local Docker Compose stack at [`docker/docker-compose.openmetadata.yml`](/home/user/Desktop/OpenMetaData/docker/docker-compose.openmetadata.yml).

Start it with:

```bash
./scripts/bootstrap_openmetadata.sh
```

If Docker is unavailable, you can still generate ingestion configs without running the stack:

```bash
python -m app.openmetadata.sync --prepare-only
```

## Ingestion strategy

The framework generates one metadata-ingestion YAML file per discovered source under `output/openmetadata/`.

Those configs are designed to:

- register the source service in OpenMetadata
- push schemas, tables, and columns into OpenMetadata
- keep OpenMetadata as the technical metadata source of truth

## Notes

- The OpenMetadata CLI binary defaults to `metadata`.
- The sync module prepares configs for MySQL, PostgreSQL, and SQLite.
- If the ingestion CLI is not installed, the configs are still usable artifacts for a later run.
- The Python package dependency is intentionally not pinned in the main app environment because current `openmetadata-ingestion` releases still depend on SQLAlchemy `<2`, while this framework uses SQLAlchemy 2.x. Treat the `metadata` CLI as an external toolchain when needed.
