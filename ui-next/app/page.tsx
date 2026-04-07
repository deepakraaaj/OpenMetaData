import Link from "next/link";

import { StartOnboardingForm } from "../components/StartOnboardingForm";
import { listSources, openMetadataServerApiBaseUrl } from "../lib/server-api";

function dedupeSources<T extends { name: string }>(sources: T[]): T[] {
  const seen = new Set<string>();
  const unique: T[] = [];
  for (const source of sources) {
    const key = source.name.toLowerCase();
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    unique.push(source);
  }
  return unique;
}

export default async function HomePage() {
  try {
    const sources = dedupeSources(await listSources());

    return (
      <main>
        <section className="hero">
          <span className="eyebrow">OpenMetaData → TAG</span>
          <h1>Turn schema metadata into a reviewed semantic bundle.</h1>
          <p>
            This admin surface asks the business questions the LLM cannot answer safely on its own.
            Review the suggestions, correct the domain truth, then publish the semantic bundle into
            a TAG domain folder.
          </p>
        </section>

        <StartOnboardingForm />

        <section className="card-grid">
          {sources.map((source) => (
            <Link className="card" href={`/source/${source.name}`} key={source.name}>
              <div className="stack">
                <span className="pill">{source.db_type || "source"}</span>
                <h2>{source.name}</h2>
                <p className="hint">
                  {source.domain
                    ? `Suggested domain: ${source.domain}`
                    : "No explicit domain set yet. Use the wizard to define the business scope."}
                </p>
              </div>

              <div className="meta-row">
                {source.database_name ? <span>DB: {source.database_name}</span> : null}
                {source.status ? <span>Status: {source.status}</span> : null}
              </div>

              <div className="button-row">
                <span className="btn btn-primary">Open Wizard</span>
              </div>
            </Link>
          ))}
        </section>
      </main>
    );
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unknown API error.";

    return (
      <main className="stack">
        <section className="hero">
          <span className="eyebrow">OpenMetaData → TAG</span>
          <h1>Onboarding UI is up, but the backend API is not reachable.</h1>
          <p>
            The Next.js app is trying to load sources from the OpenMetaData API and could not reach
            it. Start the API first, then refresh this page.
          </p>
        </section>

        <StartOnboardingForm />

        <section className="panel stack">
          <div className="notice">
            <strong>Expected API base URL</strong>
            <div>
              <code>{openMetadataServerApiBaseUrl()}</code>
            </div>
          </div>

          <div className="notice">
            <strong>Start the API</strong>
            <div>
              <code>cd /home/deepakrajb/Desktop/MD/OpenMetaData</code>
            </div>
            <div>
              <code>uv run uvicorn app.api.main:app --reload --host 127.0.0.1 --port 8088</code>
            </div>
          </div>

          <div className="notice">
            <strong>Current error</strong>
            <div className="hint">{message}</div>
          </div>
        </section>
      </main>
    );
  }
}
