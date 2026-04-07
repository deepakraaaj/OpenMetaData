# Next.js Onboarding UI

This app is a richer review surface for OpenMetaData semantic onboarding.

## What It Does

1. Paste a live database URL on the home page.
2. The backend introspects that URL immediately.
3. The UI opens a schema-grounded question wizard.
4. Your answers update the semantic bundle JSON files.
5. You can download a zip containing all generated JSON outputs for that source.
6. You can publish the reviewed semantic bundle into TAG and trigger TAG reindex.

## Run

Start the OpenMetaData API first:

```bash
uv run uvicorn app.api.main:app --reload --host 127.0.0.1 --port 8088
```

Then run the UI:

```bash
cd ui-next
npm install
NEXT_PUBLIC_OPENMETADATA_API_BASE_URL=http://127.0.0.1:8088 \
NEXT_PUBLIC_TAG_API_BASE_URL=http://127.0.0.1:8001/api/v1 \
npm run dev
```

If the UI shows `ECONNREFUSED 127.0.0.1:8088`, the Next app is running but the OpenMetaData API is not. Start it first:

```bash
cd /home/deepakrajb/Desktop/MD/OpenMetaData
uv run uvicorn app.api.main:app --reload --host 127.0.0.1 --port 8088
```

Optional dev config:

- `ALLOWED_DEV_ORIGINS=localhost,127.0.0.1,192.168.15.49`
  Controls Next.js `allowedDevOrigins` if you open the UI from another host/IP in dev.
- `ADMIN_UI_ORIGINS=http://127.0.0.1:3000,http://localhost:3000,http://192.168.15.49:3000`
  Controls which UI origins the OpenMetaData API accepts for CORS.

The wizard asks schema-grounded business questions, saves answers back into the semantic bundle,
publishes the reviewed bundle into `TAG-Implementation/app/domains/<domain>/semantic_bundle/`,
and can trigger TAG's `/semantic/reindex` endpoint immediately after publish.
