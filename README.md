# OpenMetadata Semantic Onboarding Platform

Reusable framework to discover local databases, introspect technical metadata, normalize it into internal models, enrich it with semantic guesses, push technical metadata into OpenMetadata, and export LLM-friendly context artifacts with focused human review loops.

## What it does

- discovers database sources from the local environment
- introspects schemas, tables, columns, keys, indexes, row counts, and candidate joins
- keeps technical metadata exportable to OpenMetadata
- generates reusable semantic artifacts and ambiguity questionnaires
- merges human answers back into a durable semantic model
- builds retrieval context packages for chatbot and NL2SQL workflows

## Quick start

```bash
cp .env.example .env
uv sync --extra dev
python -m app.discovery.scan
python -m app.onboard.run --all-discovered
uv run uvicorn app.api.main:app --reload --host 127.0.0.1 --port 8088
```

If you open the admin UI from a LAN/dev origin like `http://192.168.x.x:3000`, add it to `ADMIN_UI_ORIGINS` in `.env`, or keep the default `ADMIN_UI_ORIGIN_REGEX` for private-network dev origins.

## Phase 1 deterministic core only

List DB presets from the sibling TAG runtime `.env` and run deterministic introspection only:

```bash
.venv/bin/python -m app.introspection.cli list-env --env-file ../TAG-Implementation/.env
.venv/bin/python -m app.introspection.cli introspect-env VTS_DATABASE_URL --env-file ../TAG-Implementation/.env --source-name vts_phase1_demo --output-dir output/vts_phase1_demo
```

You can also call the API without running the full onboarding pipeline:

- `GET /api/introspection/env/presets?env_file=...`
- `POST /api/introspection/env`
- `POST /api/introspection/url`

## Key outputs

- `config/discovered_sources.json`
- `output/<source_name>/technical_metadata.json`
- `output/<source_name>/tables.json`
- `output/<source_name>/columns.json`
- `output/<source_name>/relationships.json`
- `output/<source_name>/profiling.json`
- `output/<source_name>/enum_candidates.json`
- `output/<source_name>/normalized_metadata.json`
- `output/<source_name>/semantic_model.json`
- `output/<source_name>/questionnaire.json`
- `output/<source_name>/artifacts/*.yaml`
- `output/<source_name>/llm_context_package.json`
- `output/<source_name>/tag_bundle/<domain>/`

## Export For TAG

Generate a copy-ready TAG overlay bundle from an onboarded source:

```bash
python -m app.artifacts.export_tag_bundle --source fits_dev_march_9 --domain maintenance
```

That creates:

- `output/<source_name>/tag_bundle/<domain>/generated/capabilities.json`
- `output/<source_name>/tag_bundle/<domain>/generated/domain_knowledge.json`
- `output/<source_name>/tag_bundle/<domain>/review/manifest.tables.review.json`

The first two files are the safe ones to copy into an existing TAG domain folder. The review manifest is intentionally separated so you do not accidentally overwrite manual TAG CRUD and table rules.

## Local OpenMetadata

The repo ships a Docker Compose stack in [`docker/docker-compose.openmetadata.yml`](/home/user/Desktop/OpenMetaData/docker/docker-compose.openmetadata.yml) plus generated ingestion configs under `output/openmetadata/`.

See:

- [`docs/architecture.md`](/home/user/Desktop/OpenMetaData/docs/architecture.md)
- [`docs/onboarding-flow.md`](/home/user/Desktop/OpenMetaData/docs/onboarding-flow.md)
- [`docs/openmetadata-integration.md`](/home/user/Desktop/OpenMetaData/docs/openmetadata-integration.md)
- [`docs/questionnaire-design.md`](/home/user/Desktop/OpenMetaData/docs/questionnaire-design.md)
- [`docs/artifact-format.md`](/home/user/Desktop/OpenMetaData/docs/artifact-format.md)
