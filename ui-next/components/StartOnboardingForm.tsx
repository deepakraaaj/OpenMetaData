"use client";

import { useEffect, useMemo, useState, useTransition } from "react";
import { useRouter } from "next/navigation";

import { getOnboardingJob, startOnboardingJob } from "../lib/client-api";
import type {
  OnboardingJobSnapshot,
  OnboardingLogEntry,
  OnboardingProgressCounts,
  OnboardingStage,
} from "../lib/types";

const POLL_INTERVAL_MS = 1200;
const REDIRECT_DELAY_MS = 1800;

export function StartOnboardingForm() {
  const router = useRouter();
  const [isRedirectPending, startTransition] = useTransition();
  const [dbUrl, setDbUrl] = useState("");
  const [sourceName, setSourceName] = useState("");
  const [domainName, setDomainName] = useState("");
  const [description, setDescription] = useState("");
  const [job, setJob] = useState<OnboardingJobSnapshot | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState("");
  const [statusWarning, setStatusWarning] = useState("");

  const isJobActive = job?.status === "queued" || job?.status === "running";
  const isBusy = isSubmitting || isJobActive || isRedirectPending;

  useEffect(() => {
    if (!job || !isJobActive) {
      return;
    }

    let cancelled = false;
    let timeoutId: number | undefined;

    const poll = async () => {
      try {
        const nextJob = await getOnboardingJob(job.job_id);
        if (cancelled) {
          return;
        }
        setJob(nextJob);
        setStatusWarning("");
        if (nextJob.status === "queued" || nextJob.status === "running") {
          timeoutId = window.setTimeout(poll, POLL_INTERVAL_MS);
        }
      } catch (error) {
        if (cancelled) {
          return;
        }
        setStatusWarning(error instanceof Error ? error.message : "Could not refresh onboarding status.");
        timeoutId = window.setTimeout(poll, POLL_INTERVAL_MS * 2);
      }
    };

    timeoutId = window.setTimeout(poll, POLL_INTERVAL_MS);

    return () => {
      cancelled = true;
      if (timeoutId) {
        window.clearTimeout(timeoutId);
      }
    };
  }, [job, isJobActive]);

  useEffect(() => {
    if (!job || job.status !== "completed" || !job.result) {
      return;
    }

    const timeoutId = window.setTimeout(() => {
      startTransition(() => {
        router.push(job.result?.wizard_url || job.wizard_url);
        router.refresh();
      });
    }, REDIRECT_DELAY_MS);

    return () => window.clearTimeout(timeoutId);
  }, [job, router, startTransition]);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (isBusy || !dbUrl.trim()) {
      return;
    }

    setSubmitError("");
    setStatusWarning("");
    setJob(null);
    setIsSubmitting(true);

    try {
      const snapshot = await startOnboardingJob({
        db_url: dbUrl,
        source_name: sourceName || undefined,
        domain_name: domainName || undefined,
        description: description || undefined,
      });
      setJob(snapshot);
    } catch (error) {
      setSubmitError(error instanceof Error ? error.message : "Failed to process the DB URL.");
    } finally {
      setIsSubmitting(false);
    }
  }

  const buttonLabel = isRedirectPending
    ? "Opening review workspace..."
    : isSubmitting
      ? "Submitting..."
      : isJobActive
        ? "Processing..."
        : "Process URL And Ask Questions";

  return (
    <section className="panel stack onboarding-panel">
      <div className="stack">
        <span className="pill">Direct DB URL Onboarding</span>
        <h2>Paste a DB URL and start the questionnaire immediately.</h2>
        <p className="hint">
          This path connects to the database, reads the schema, builds the semantic review bundle,
          and then takes you into the guided review workspace. Large schemas usually take between
          20 and 60 seconds.
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
            disabled={isBusy}
            required
          />
        </div>

        <div className="card-grid onboarding-fields">
          <div className="stack">
            <label htmlFor="source-name">Source name</label>
            <input
              id="source-name"
              className="field"
              placeholder="Optional stable source slug"
              value={sourceName}
              onChange={(event) => setSourceName(event.target.value)}
              disabled={isBusy}
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
              disabled={isBusy}
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
            disabled={isBusy}
          />
        </div>

        <div className="button-row">
          <button className="btn btn-primary" type="submit" disabled={isBusy || !dbUrl.trim()}>
            {buttonLabel}
          </button>
        </div>

        {submitError ? (
          <div className="status error">{submitError}</div>
        ) : statusWarning ? (
          <div className="status">{statusWarning}</div>
        ) : (
          <div className="status">
            {job
              ? job.reused_existing_job
                ? "A matching onboarding job is already running. Reusing that live progress stream."
                : job.status === "failed"
                  ? "Onboarding stopped. Update the connection details and retry when ready."
                  : job.status === "completed"
                    ? "The semantic workspace is ready. Redirecting now."
                    : "Onboarding request accepted. Live progress is shown below."
              : "Nothing submitted yet."}
          </div>
        )}
      </form>

      {job ? <OnboardingProgressPanel job={job} isRedirecting={isRedirectPending} /> : null}
    </section>
  );
}

function OnboardingProgressPanel({
  job,
  isRedirecting,
}: {
  job: OnboardingJobSnapshot;
  isRedirecting: boolean;
}) {
  const labelByStage = useMemo(
    () =>
      Object.fromEntries(job.steps.map((step) => [step.stage, step.label])) as Record<
        OnboardingStage,
        string
      >,
    [job.steps],
  );

  const summaryItems = buildSummaryItems(job.counts);
  const latestMessage =
    job.logs[job.logs.length - 1]?.message ||
    job.steps.find((step) => step.state === "running")?.message ||
    job.steps.find((step) => step.state === "completed")?.message ||
    "Preparing onboarding job.";

  return (
    <div className="card onboarding-progress-shell">
      <div className="onboarding-progress-header">
        <div className="stack" style={{ gap: "0.5rem" }}>
          <div className="meta-row">
            <span className={`pill ${toneClass(job.status)}`}>{job.status.replace("_", " ")}</span>
            <span className="pill">{job.source_name}</span>
          </div>
          <h3>{headingForJob(job, isRedirecting)}</h3>
          <p className="hint">{latestMessage}</p>
          <p className="hint">{job.estimated_wait_message}</p>
        </div>
        <div className="onboarding-progress-value">{job.progress_percent}%</div>
      </div>

      <div className="onboarding-progress-track">
        <div
          className="onboarding-progress-bar"
          style={{ width: `${job.progress_percent}%` }}
        />
      </div>

      <div className="onboarding-stepper">
        {job.steps.map((step) => (
          <div className={`onboarding-step onboarding-step-${step.state}`} key={step.stage}>
            <div className="onboarding-step-marker">{markerForStep(step.state)}</div>
            <div className="stack" style={{ gap: "0.35rem" }}>
              <div className="onboarding-step-title-row">
                <strong>{step.label}</strong>
                <span className="hint">{statusText(step.state)}</span>
              </div>
              <p className="hint">{step.message || fallbackStepMessage(step.stage, step.state)}</p>
            </div>
          </div>
        ))}
      </div>

      {summaryItems.length > 0 ? (
        <div className="onboarding-summary-grid">
          {summaryItems.map((item) => (
            <div className="onboarding-summary-card" key={item.label}>
              <span className="hint">{item.label}</span>
              <strong>{item.value}</strong>
            </div>
          ))}
        </div>
      ) : null}

      <div className="onboarding-log-panel">
        <div className="onboarding-log-header">
          <strong>Live status</strong>
          <span className="hint">{job.logs.length} updates</span>
        </div>
        <div className="onboarding-log-list">
          {job.logs.map((entry, index) => (
            <LogLine
              entry={entry}
              key={`${entry.timestamp}-${index}`}
              labelByStage={labelByStage}
            />
          ))}
        </div>
      </div>

      {job.status === "failed" ? (
        <div className="status error">{job.error_message || "Onboarding failed before review was ready."}</div>
      ) : null}

      {job.status === "completed" && job.result ? (
        <div className="status success">
          {isRedirecting
            ? "Semantic model ready. Opening the workspace now."
            : "Semantic model ready. Redirecting after the final summary."}
        </div>
      ) : null}
    </div>
  );
}

function LogLine({
  entry,
  labelByStage,
}: {
  entry: OnboardingLogEntry;
  labelByStage: Record<OnboardingStage, string>;
}) {
  const time = new Date(entry.timestamp);
  const formattedTime = Number.isNaN(time.getTime())
    ? entry.timestamp
    : time.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });

  return (
    <div className={`onboarding-log-entry onboarding-log-entry-${entry.level}`}>
      <span className="onboarding-log-time">{formattedTime}</span>
      <span className="onboarding-log-stage">{labelByStage[entry.stage] || entry.stage}</span>
      <span className="onboarding-log-message">{entry.message}</span>
    </div>
  );
}

function buildSummaryItems(counts: OnboardingProgressCounts) {
  return [
    counts.table_count ? { label: "Tables", value: counts.table_count } : null,
    counts.column_count ? { label: "Columns", value: counts.column_count } : null,
    counts.foreign_key_count ? { label: "Foreign keys", value: counts.foreign_key_count } : null,
    counts.review_item_count ? { label: "Review items", value: counts.review_item_count } : null,
  ].filter((item): item is { label: string; value: number } => item !== null);
}

function headingForJob(job: OnboardingJobSnapshot, isRedirecting: boolean) {
  if (job.status === "failed") {
    return "Onboarding stopped before review could begin.";
  }
  if (job.status === "completed") {
    return isRedirecting ? "Workspace is opening." : "Semantic model is ready.";
  }
  return "Preparing semantic review from the database URL.";
}

function toneClass(status: OnboardingJobSnapshot["status"]) {
  if (status === "completed") {
    return "pill-success";
  }
  if (status === "failed") {
    return "pill-danger";
  }
  return "pill-warning";
}

function markerForStep(state: string) {
  if (state === "completed") {
    return "✓";
  }
  if (state === "running") {
    return "●";
  }
  if (state === "error") {
    return "!";
  }
  return "";
}

function statusText(state: string) {
  if (state === "completed") {
    return "Done";
  }
  if (state === "running") {
    return "In progress";
  }
  if (state === "error") {
    return "Failed";
  }
  return "Pending";
}

function fallbackStepMessage(stage: OnboardingStage, state: string) {
  if (state === "pending") {
    return "Waiting for earlier stages to finish.";
  }

  switch (stage) {
    case "connecting_to_database":
      return "Verifying connectivity and credentials.";
    case "reading_schema":
      return "Inspecting schemas, tables, and columns.";
    case "extracting_relationships":
      return "Mapping keys and likely joins.";
    case "building_semantic_model":
      return "Assembling semantic understanding from the schema.";
    case "generating_review_questions":
      return "Preparing reviewer prompts and bundle artifacts.";
    case "ready_for_review":
      return "Everything needed for review is available.";
  }
}
