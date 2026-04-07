# Architecture

## Backbone

OpenMetadata is the technical metadata backbone for the platform:

- service registration
- database metadata ingestion
- tables, schemas, columns, descriptions, tags, and ownership

Custom application layers handle:

- automatic discovery
- normalization into internal models
- heuristic semantic guessing
- ambiguity detection and questionnaire generation
- merge-back of reviewed answers
- LLM context packaging

## Flow

1. Discovery scans the local environment for database URLs, config files, and local SQLite-like files.
2. Introspection captures technical metadata with SQLAlchemy and stores stable snapshots plus deterministic Phase 1 JSON artifacts under `output/<source>/`.
3. Normalization converts raw metadata into a consistent internal representation.
4. Semantic enrichment adds business-purpose guesses, entity mapping, sensitivity hints, and query patterns.
5. Ambiguity detection emits focused questionnaires only where confidence is low.
6. Artifact generation exports compact YAML and JSON contracts for downstream LLM tooling.
7. Retrieval builds question-scoped context packages from those artifacts.

## Key modules

- `app.discovery`: local source discovery and inventory expansion
- `app.onboard`: technical metadata capture and orchestration
- `app.openmetadata`: OpenMetadata ingestion config generation and sync hooks
- `app.normalization`: internal canonical metadata models
- `app.semantics`: semantic guessing and ambiguity detection
- `app.questionnaire`: human review merge loop
- `app.artifacts`: final artifact export
- `app.retrieval`: context packaging for chatbot and NL2SQL workflows
- `app.api`: review UI and JSON endpoints
