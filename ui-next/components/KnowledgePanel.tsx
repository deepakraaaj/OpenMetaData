"use client";

import { KnowledgeState } from "../lib/types";
import { formatDomainGroupLabel } from "../lib/domain-groups";

type Props = {
  state: KnowledgeState;
};

export default function KnowledgePanel({ state }: Props) {
  const summary = state.review_summary;
  const domainGroups = state.domain_groups.slice(0, 4);
  const reviewQueue = state.review_queue.slice(0, 6);

  return (
    <div className="knowledge-panel">
      <div className="panel-header" style={{ paddingBottom: "1.25rem" }}>
        <div className="stack">
          <h3>AI Table Selection</h3>
          <span className="hint">
            {summary.analyzed_table_count} tables analyzed, {summary.review_count} still need confirmation
          </span>
        </div>
        <div className="stack" style={{ alignItems: "flex-end", gap: "0.25rem" }}>
          <span className="eyebrow" style={{ fontSize: "0.65rem" }}>
            Readiness
          </span>
          <div className="progress-container" style={{ width: "92px", margin: 0, height: "4px" }}>
            <div
              className="progress-bar"
              style={{ width: `${state.readiness.readiness_percentage}%`, background: "var(--accent)" }}
            ></div>
          </div>
        </div>
      </div>

      <div className="panel-content stack" style={{ gap: "1rem" }}>
        <div
          className="card"
          style={{
            padding: "1rem",
            background: "rgba(var(--success-rgb), 0.05)",
            border: "1px solid rgba(var(--success-rgb), 0.18)",
          }}
        >
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: "0.75rem" }}>
            <Metric label="Selected" value={summary.selected_count} tone="success" />
            <Metric label="Excluded" value={summary.excluded_count} />
            <Metric label="Review" value={summary.review_count} tone="warning" />
          </div>
        </div>

        <div className="card" style={{ padding: "1rem" }}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: "0.75rem", flexWrap: "wrap" }}>
            <span className="eyebrow" style={{ marginBottom: 0 }}>
              Domains
            </span>
            <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap" }}>
              {summary.detected_domains.slice(0, 5).map((domain) => (
                <span key={domain} className="pill pill-success">
                  {formatDomainGroupLabel(domain)}
                </span>
              ))}
            </div>
          </div>
          <div style={{ display: "grid", gap: "0.75rem", marginTop: "1rem" }}>
            {domainGroups.map((domain) => (
              <div
                key={domain.domain}
                style={{
                  padding: "0.85rem 0.95rem",
                  borderRadius: "12px",
                  background: "var(--bg-surface-alt)",
                  display: "flex",
                  justifyContent: "space-between",
                  gap: "1rem",
                }}
              >
                <div className="stack" style={{ gap: "0.2rem" }}>
                  <strong>{formatDomainGroupLabel(domain.domain)}</strong>
                  <span className="hint" style={{ fontSize: "0.75rem" }}>
                    {domain.tables.length} tables, {domain.review_count} pending
                  </span>
                  {domain.inferred_business_meaning ? (
                    <span className="hint" style={{ fontSize: "0.72rem" }}>
                      {domain.inferred_business_meaning}
                    </span>
                  ) : null}
                </div>
                <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap", justifyContent: "flex-end" }}>
                  <span className="pill pill-success">{domain.selected_count}</span>
                  <span className="pill">{domain.excluded_count}</span>
                  <span className="pill pill-warning">{domain.review_count}</span>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="card" style={{ padding: "1rem" }}>
          <span className="eyebrow">Review Queue</span>
          <div style={{ display: "grid", gap: "0.75rem", marginTop: "0.9rem" }}>
            {reviewQueue.length > 0 ? (
              reviewQueue.map((item) => (
                <div
                  key={item.table_name}
                  style={{
                    padding: "0.9rem 0.95rem",
                    borderRadius: "12px",
                    background: "var(--bg-surface-alt)",
                    display: "grid",
                    gap: "0.45rem",
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", gap: "0.75rem", alignItems: "center" }}>
                    <strong>{item.table_name}</strong>
                    <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap" }}>
                      <span className="pill">{item.role.replace(/_/g, " ")}</span>
                      <span className={`pill ${item.selected ? "pill-success" : ""}`}>
                        {item.selected ? "Selected" : "Excluded"}
                      </span>
                    </div>
                  </div>
                  <span className="hint" style={{ fontSize: "0.75rem" }}>
                    {item.selection_reason || item.reason_for_classification || "Needs confirmation."}
                  </span>
                  <span className="hint" style={{ fontSize: "0.72rem" }}>
                    {item.open_gap_count} open issue(s) • {formatDomainGroupLabel(item.domain || "Configuration / Internal")}
                  </span>
                  {item.review_reason ? (
                    <span className="hint" style={{ fontSize: "0.72rem" }}>
                      Review: {item.review_reason}
                    </span>
                  ) : null}
                </div>
              ))
            ) : (
              <p className="hint" style={{ margin: 0 }}>
                No high-impact review items remain.
              </p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function Metric({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone?: "success" | "warning";
}) {
  const color =
    tone === "success" ? "var(--success)" : tone === "warning" ? "var(--warning)" : "var(--text-main)";
  return (
    <div style={{ padding: "0.8rem 0.85rem", borderRadius: "12px", background: "var(--bg-surface-alt)" }}>
      <div className="hint" style={{ fontSize: "0.72rem" }}>
        {label}
      </div>
      <div style={{ fontSize: "1.5rem", fontWeight: 700, color }}>{value}</div>
    </div>
  );
}
