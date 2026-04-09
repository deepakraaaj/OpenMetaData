"use client";

import { DomainReviewGroup, KnowledgeState } from "../lib/types";
import { formatDomainGroupLabel } from "../lib/domain-groups";

type Props = {
  state: KnowledgeState;
  groups: Record<string, string[]>;
};

export default function DomainSummary({ state, groups }: Props) {
  const domainGroups = state.domain_groups.length > 0 ? state.domain_groups : fallbackGroups(state, groups);
  const summary = state.review_summary;

  if (domainGroups.length === 0) {
    return (
      <div className="card" style={{ display: "flex", justifyContent: "center", padding: "4rem" }}>
        <p className="hint">Identifying domains...</p>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1.5rem" }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: "1rem" }}>
        <SummaryCard label="Analyzed" value={summary.analyzed_table_count} />
        <SummaryCard label="Selected" value={summary.selected_count} tone="success" />
        <SummaryCard label="Excluded" value={summary.excluded_count} />
        <SummaryCard label="Needs Review" value={summary.review_count} tone="warning" />
      </div>

      <div className="card" style={{ padding: "1.25rem 1.5rem" }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: "1rem", flexWrap: "wrap" }}>
          <div className="stack" style={{ gap: "0.35rem" }}>
            <span className="eyebrow">Detected Domains</span>
            <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
              {summary.detected_domains.map((domain) => (
                <span key={domain} className="pill pill-success">
                  {formatDomainGroupLabel(domain)}
                </span>
              ))}
            </div>
          </div>
          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", alignItems: "flex-start" }}>
            <span className="pill">{summary.high_confidence_count} high confidence</span>
            <span className="pill">{summary.medium_confidence_count} medium confidence</span>
            <span className="pill pill-warning">{summary.low_confidence_count} low confidence</span>
          </div>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: "1rem" }}>
        {domainGroups.map((domain) => (
          <DomainCard key={domain.domain} domain={domain} state={state} />
        ))}
      </div>
    </div>
  );
}

function SummaryCard({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone?: "success" | "warning";
}) {
  const accent =
    tone === "success" ? "var(--success)" : tone === "warning" ? "var(--warning)" : "var(--accent)";
  return (
    <div className="card" style={{ padding: "1.2rem 1.25rem" }}>
      <div className="hint" style={{ fontSize: "0.8rem", marginBottom: "0.5rem" }}>
        {label}
      </div>
      <div style={{ fontSize: "2rem", fontWeight: 700, color: accent }}>{value}</div>
    </div>
  );
}

function DomainCard({ domain, state }: { domain: DomainReviewGroup; state: KnowledgeState }) {
  const tone =
    domain.confidence.label === "high"
      ? "pill-success"
      : domain.confidence.label === "medium"
        ? ""
        : "pill-warning";
  const sampleTables = domain.tables.slice(0, 4);

  return (
    <div className="card" style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: "1rem", alignItems: "flex-start" }}>
        <div className="stack" style={{ gap: "0.35rem" }}>
          <h3 style={{ margin: 0 }}>{formatDomainGroupLabel(domain.domain)}</h3>
          <p className="hint" style={{ margin: 0, fontSize: "0.8rem" }}>
            {domain.tables.length} tables, {domain.review_count} pending confirmation
          </p>
        </div>
        <span className={`pill ${tone}`}>{domain.confidence.label} confidence</span>
      </div>

      <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
        <span className="pill pill-success">{domain.selected_count} selected</span>
        <span className="pill">{domain.excluded_count} excluded</span>
        <span className="pill pill-warning">{domain.review_count} review</span>
      </div>

      {domain.inferred_business_meaning ? (
        <p className="hint" style={{ margin: 0, fontSize: "0.8rem" }}>
          {domain.inferred_business_meaning}
        </p>
      ) : null}

      {domain.anchor_tables.length > 0 ? (
        <div>
          <div className="eyebrow" style={{ marginBottom: "0.5rem" }}>
            Anchor Tables
          </div>
          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
            {domain.anchor_tables.map((tableName) => (
              <span key={tableName} className="pill">
                {tableName}
              </span>
            ))}
          </div>
        </div>
      ) : null}

      {domain.core_tables.length > 0 ? (
        <div>
          <div className="eyebrow" style={{ marginBottom: "0.5rem" }}>
            Core Tables
          </div>
          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
            {domain.core_tables.map((tableName) => (
              <span key={tableName} className="pill pill-success">
                {tableName}
              </span>
            ))}
          </div>
        </div>
      ) : null}

      <div style={{ display: "grid", gap: "0.75rem" }}>
        {sampleTables.map((tableName) => {
          const table = state.tables[tableName];
          if (!table) return null;
          return (
            <div
              key={table.table_name}
              style={{
                display: "flex",
                justifyContent: "space-between",
                gap: "1rem",
                alignItems: "center",
                padding: "0.75rem 0.9rem",
                borderRadius: "12px",
                background: "var(--bg-surface-alt)",
              }}
            >
              <div className="stack" style={{ gap: "0.25rem" }}>
                <strong style={{ fontSize: "0.9rem" }}>{table.table_name}</strong>
                <span className="hint" style={{ fontSize: "0.75rem" }}>
                  {table.selection_reason || table.reason_for_classification || table.business_meaning || "Awaiting classification context"}
                </span>
                {table.review_reason ? (
                  <span className="hint" style={{ fontSize: "0.72rem" }}>
                    Review: {table.review_reason}
                  </span>
                ) : null}
              </div>
              <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap", justifyContent: "flex-end" }}>
                <span className="pill">{table.role.replace(/_/g, " ")}</span>
                <span className={`pill ${table.selected ? "pill-success" : ""}`}>
                  {table.selected ? "Selected" : "Excluded"}
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function fallbackGroups(state: KnowledgeState, groups: Record<string, string[]>): DomainReviewGroup[] {
  return Object.entries(groups).map(([domain, tables]) => {
    const members = tables.map((name) => state.tables[name]).filter(Boolean);
    const avgScore =
      members.reduce((total, table) => total + (table?.confidence.score || 0), 0) / Math.max(members.length, 1);
    return {
      domain,
      tables,
      core_tables: members
        .filter((table) => table.role === "core_entity" || table.role === "transaction")
        .slice(0, 3)
        .map((table) => table.table_name),
      selected_count: members.filter((table) => table.selected).length,
      excluded_count: members.filter((table) => !table.selected).length,
      review_count: members.filter((table) => table.requires_review || table.needs_review).length,
      anchor_tables: members
        .slice()
        .sort((left, right) => (right.impact_score || 0) - (left.impact_score || 0))
        .slice(0, 3)
        .map((table) => table.table_name),
      inferred_business_meaning:
        members[0]?.domain ? `Business area centered on ${members.slice(0, 3).map((table) => table.table_name).join(", ")}.` : undefined,
      requires_review: members.some((table) => table.requires_review),
      review_reason: members.find((table) => table.review_reason)?.review_reason,
      confidence: {
        label: avgScore >= 0.78 ? "high" : avgScore >= 0.55 ? "medium" : "low",
        score: Number(avgScore.toFixed(2)),
        rationale: ["Derived from table confidence scores"],
      },
    };
  });
}
