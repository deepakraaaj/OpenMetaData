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
          <span className="eyebrow">Phase 3 — Mock Mode Active</span>
          <h1>Admin API is offline, but the UI shell is ready.</h1>
          <p>
            You are running in <strong>Mock Mode</strong>. You can explore the split-layout onboarding 
            workspace and review the premium design system safely while the backend is disconnected.
          </p>
          <div style={{ marginTop: '2rem' }}>
            <Link href="/source/demo_source" className="btn btn-primary" style={{ padding: '1rem 3rem' }}>
              Enter Mock Workspace
            </Link>
          </div>
        </section>

        <section className="card-grid" style={{ opacity: 0.5, pointerEvents: 'none' }}>
          <div className="card">
            <h3>Backend API unreachable</h3>
            <p className="hint">{message}</p>
          </div>
        </section>
      </main>
    );
  }
}
