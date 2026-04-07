"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";

import { onboardFromUrl } from "../lib/client-api";

export function StartOnboardingForm() {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();
  const [dbUrl, setDbUrl] = useState("");
  const [sourceName, setSourceName] = useState("");
  const [domainName, setDomainName] = useState("");
  const [description, setDescription] = useState("");
  const [status, setStatus] = useState("");
  const [tone, setTone] = useState<"muted" | "success" | "error">("muted");

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setStatus("Connecting to the database, introspecting the schema, and preparing questions...");
    setTone("muted");
    try {
      const payload = await onboardFromUrl({
        db_url: dbUrl,
        source_name: sourceName || undefined,
        domain_name: domainName || undefined,
        description: description || undefined,
      });
      setStatus(`Onboarding source '${payload.source_name}' is ready. Opening the wizard...`);
      setTone("success");
      startTransition(() => {
        router.push(payload.wizard_url);
        router.refresh();
      });
    } catch (error) {
      setTone("error");
      setStatus(error instanceof Error ? error.message : "Failed to process the DB URL.");
    }
  }

  return (
    <section className="panel stack">
      <div className="stack">
        <span className="pill">Direct DB URL Onboarding</span>
        <h2>Paste a DB URL and start the questionnaire immediately.</h2>
        <p className="hint">
          This path introspects the URL you enter, generates the semantic bundle, and then takes
          you straight into the question wizard. After review, you can download a zip of all JSON
          outputs.
        </p>
      </div>

      <form className="stack" onSubmit={handleSubmit}>
        <div className="stack">
          <label htmlFor="db-url">Database URL</label>
          <textarea
            id="db-url"
            className="area"
            placeholder="mysql+pymysql://user:pass@host:3306/database"
            value={dbUrl}
            onChange={(event) => setDbUrl(event.target.value)}
            required
          />
        </div>

        <div className="card-grid">
          <div className="stack">
            <label htmlFor="source-name">Source name</label>
            <input
              id="source-name"
              className="field"
              placeholder="Optional stable source slug"
              value={sourceName}
              onChange={(event) => setSourceName(event.target.value)}
            />
          </div>

          <div className="stack">
            <label htmlFor="domain-name">Target domain</label>
            <input
              id="domain-name"
              className="field"
              placeholder="Optional TAG domain name"
              value={domainName}
              onChange={(event) => setDomainName(event.target.value)}
            />
          </div>
        </div>

        <div className="stack">
          <label htmlFor="description">Description</label>
          <input
            id="description"
            className="field"
            placeholder="Optional business summary for this source"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
          />
        </div>

        <div className="button-row">
          <button className="btn btn-primary" type="submit" disabled={isPending || !dbUrl.trim()}>
            Process URL And Ask Questions
          </button>
        </div>

        <div className={`status ${tone === "success" ? "success" : tone === "error" ? "error" : ""}`}>
          {status || "Nothing submitted yet."}
        </div>
      </form>
    </section>
  );
}
