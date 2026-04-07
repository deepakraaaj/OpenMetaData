# Onboarding Flow

## Automated-first process

1. Run discovery:

   ```bash
   python -m app.discovery.scan
   ```

2. Review `config/discovered_sources.json`. Only fill `config/source.missing.template.yaml` if discovery could not infer a source safely.

3. Run onboarding:

   ```bash
   python -m app.onboard.run --all-discovered
   ```

4. Open the review UI:

   ```bash
   uv run uvicorn app.api.main:app --reload --host 127.0.0.1 --port 8088
   ```

5. Optional: open the richer Next.js onboarding wizard:

   ```bash
   cd ui-next
   npm install
   OPENMETADATA_API_BASE_URL=http://127.0.0.1:8088 \
   NEXT_PUBLIC_TAG_API_BASE_URL=http://127.0.0.1:8001/api/v1 \
   npm run dev
   ```

   Use it to answer schema-grounded business questions and save the reviewed `semantic_bundle/`.

6. Fill questionnaire outputs when needed and merge them back:

   ```bash
   python -m app.questionnaire.merge --file output/<source>/questionnaire_filled.json
   ```

7. Regenerate artifacts if answers changed:

   ```bash
   python -m app.artifacts.generate --source <source_name>
   ```

8. Publish the reviewed semantic bundle into TAG and trigger runtime reindex:

   - OpenMetaData publishes `output/<source>/semantic_bundle/` into `TAG-Implementation/app/domains/<domain>/semantic_bundle/`.
   - TAG can then reindex via `POST /api/v1/semantic/reindex?domain=<domain>`.

9. Debug context assembly for a realistic business question:

   ```bash
   python -m app.retrieval.debug --source <source_name> --question "How many active trips were completed this week?"
   ```
