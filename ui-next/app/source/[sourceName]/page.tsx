import Link from "next/link";

import { OnboardingWizard } from "../../../components/OnboardingWizard";
import { loadBundle, loadQuestions, openMetadataServerApiBaseUrl } from "../../../lib/server-api";

type Props = {
  params: Promise<{ sourceName: string }>;
};

export default async function SourcePage({ params }: Props) {
  const { sourceName } = await params;
  try {
    const bundle = await loadBundle(sourceName);
    const questions = await loadQuestions(sourceName);

    return (
      <main className="stack">
        <Link className="back-link" href="/">
          ← Back to sources
        </Link>

        <section className="hero">
          <span className="eyebrow">Onboarding Chat</span>
          <h1>{sourceName}</h1>
          <p>
            Teach the business meaning in plain language. The assistant turns each confirmed reply
            into reviewed JSON that you can download or publish into TAG.
          </p>
        </section>

        <OnboardingWizard
          sourceName={sourceName}
          initialBundle={bundle}
          sections={questions.sections}
          downloadUrl={`${openMetadataServerApiBaseUrl()}/api/sources/${sourceName}/json-zip`}
        />
      </main>
    );
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unknown API error.";

    return (
      <main className="stack">
        <Link className="back-link" href="/">
          ← Back to sources
        </Link>

        <section className="hero">
          <span className="eyebrow">Onboarding Chat</span>
          <h1>{sourceName}</h1>
          <p>
            The wizard could not load this source from the OpenMetaData API. Start the backend or
            fix the configured API base URL, then refresh.
          </p>
        </section>

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
