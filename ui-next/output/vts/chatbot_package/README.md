# Chatbot Package: vts

This folder collects the artifacts needed to review and activate a database-backed chatbot domain.

## What is inside

- `visuals/overview.html` is the human-friendly review summary.
- `questions/semantic_bundle_questions.json` contains 56 schema-grounded questions for the reviewer.
- `runtime/llm_context_package.json` is the compact context package for LLM grounding.
- `semantic_bundle/` is the reviewed retrieval bundle to publish into TAG.
- `tag_bundle/platform_ops/` contains the TAG overlay bundle.
- `reference/` keeps the raw OpenMetaData outputs for traceability.

## Recommended flow

1. Review the overview HTML with the business user.
2. Answer the schema-grounded questions.
3. Finalize the semantic bundle and TAG overlay.
4. Publish into `TAG-Implementation/app/domains/platform_ops/` and reindex the runtime.
