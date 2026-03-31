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

5. Fill questionnaire outputs when needed and merge them back:

   ```bash
   python -m app.questionnaire.merge --file output/<source>/questionnaire_filled.json
   ```

6. Regenerate artifacts if answers changed:

   ```bash
   python -m app.artifacts.generate --source <source_name>
   ```

7. Debug context assembly for a realistic business question:

   ```bash
   python -m app.retrieval.debug --source <source_name> --question "How many active trips were completed this week?"
   ```

