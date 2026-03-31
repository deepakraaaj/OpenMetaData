# Artifact Format

Artifacts are compact, editable, and versionable.

## Files produced

- `source.artifact.yaml`
- `tables.artifact.yaml`
- `columns.artifact.yaml`
- `glossary.artifact.yaml`
- `canonical_entities.artifact.yaml`
- `query_patterns.artifact.yaml`
- `llm_context_package.yaml`

## Design goals

- small enough to ground LLM prompts without dumping raw full schemas
- stable keys for downstream retrieval and agent workflows
- human-readable for review and incremental refinement

## Confidence handling

Every guessed semantic record keeps a score and label:

- `high`
- `medium`
- `low`

Low-confidence records should trigger questionnaires before they are treated as authoritative.
