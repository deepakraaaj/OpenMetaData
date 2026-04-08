"use client";

import { useEffect, useMemo, useState } from "react";
import { reviewTable } from "../lib/client-api";
import { formatDomainGroupLabel } from "../lib/domain-groups";
import { KnowledgeState, SemanticGap, SemanticTable } from "../lib/types";

type Props = {
  state: KnowledgeState;
  groups: Record<string, string[]>;
  onStateUpdate: (state: KnowledgeState) => void;
};

const GAP_LABELS: Record<string, string> = {
  unknown_business_meaning: "Meaning",
  ambiguous_relationship: "Relationship",
  unconfirmed_enum_mapping: "Enum",
  potential_sensitivity: "Sensitive Data",
  glossary_term_missing: "Glossary",
  missing_primary_key: "Primary Key",
  relationship_role_unclear: "Relationship",
  other: "Review",
};

export default function DomainAuditPanel({ state, groups, onStateUpdate }: Props) {
  const [activeDomain, setActiveDomain] = useState<string>(Object.keys(groups)[0] || "");
  const [savingTable, setSavingTable] = useState<string | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (activeDomain && groups[activeDomain]) {
      return;
    }
    setActiveDomain(Object.keys(groups)[0] || "");
  }, [activeDomain, groups]);

  const gapsByTable = useMemo(() => {
    const grouped: Record<string, SemanticGap[]> = {};
    for (const gap of state.unresolved_gaps) {
      const key = gap.target_entity || "unassigned";
      if (!grouped[key]) {
        grouped[key] = [];
      }
      grouped[key].push(gap);
    }
    return grouped;
  }, [state.unresolved_gaps]);

  const domainNames = Object.keys(groups);
  const tablesInDomain = useMemo(() => {
    const tables =
      groups[activeDomain]
        ?.map((name) => state.tables[name])
        .filter(Boolean) ?? [];

    return [...tables].sort((left, right) => {
      const statusRank = { pending: 0, confirmed: 1, skipped: 2 };
      const leftRank = statusRank[left.review_status];
      const rightRank = statusRank[right.review_status];
      if (leftRank !== rightRank) {
        return leftRank - rightRank;
      }
      const leftGapCount = gapsByTable[left.table_name]?.length || 0;
      const rightGapCount = gapsByTable[right.table_name]?.length || 0;
      if (leftGapCount !== rightGapCount) {
        return rightGapCount - leftGapCount;
      }
      return left.table_name.localeCompare(right.table_name);
    });
  }, [activeDomain, gapsByTable, groups, state.tables]);

  const handleReview = async (
    tableName: string,
    reviewStatus: SemanticTable["review_status"],
  ) => {
    setError("");
    setSavingTable(tableName);
    try {
      const updated = await reviewTable(
        state.source_name,
        tableName,
        reviewStatus,
        "Admin User",
      );
      onStateUpdate(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save table decision.");
    } finally {
      setSavingTable(null);
    }
  };

  if (domainNames.length === 0) {
    return (
      <div className="card" style={{ padding: "4rem", textAlign: "center" }}>
        <p className="hint">No domains identified for auditing yet.</p>
      </div>
    );
  }

  const activeQuestionCount = tablesInDomain.reduce(
    (sum, table) => sum + (gapsByTable[table.table_name]?.length || 0),
    0,
  );
  const activeNeededCount = tablesInDomain.filter(
    (table) => table.review_status === "confirmed",
  ).length;
  const activeSkippedCount = tablesInDomain.filter(
    (table) => table.review_status === "skipped",
  ).length;

  return (
    <div className="audit-panel">
      <div className="audit-sidebar">
        <span
          className="eyebrow"
          style={{ padding: "0 1rem", marginBottom: "1rem", display: "block" }}
        >
          Business Domains
        </span>
        {domainNames.map((domain) => {
          const domainTables = groups[domain]
            .map((name) => state.tables[name])
            .filter(Boolean);
          const decidedCount = domainTables.filter(
            (table) => table.review_status !== "pending",
          ).length;
          const openQuestions = domainTables.reduce(
            (sum, table) => sum + (gapsByTable[table.table_name]?.length || 0),
            0,
          );

          return (
            <div
              key={domain}
              className={`audit-nav-item ${activeDomain === domain ? "active" : ""}`}
              onClick={() => setActiveDomain(domain)}
            >
              <div className="stack" style={{ gap: "0.25rem" }}>
                <span className="domain-label">{formatDomainGroupLabel(domain)}</span>
                <span className="hint" style={{ fontSize: "0.7rem" }}>
                  {decidedCount}/{domainTables.length} decided
                </span>
              </div>
              <span className="pill" style={{ fontSize: "0.7rem" }}>
                {openQuestions} open
              </span>
            </div>
          );
        })}
      </div>

      <div className="audit-main">
        <div className="audit-header">
          <div className="stack" style={{ gap: "0.75rem" }}>
            <div>
              <h2>{formatDomainGroupLabel(activeDomain)}</h2>
              <p className="hint" style={{ margin: 0 }}>
                Review the table cards below, decide what stays in scope, and skip tables
                that do not matter for this source.
              </p>
            </div>
            <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
              <span className="pill">{tablesInDomain.length} tables</span>
              <span className="pill pill-warning">{activeQuestionCount} open questions</span>
              <span className="pill pill-success">{activeNeededCount} needed</span>
              <span className="pill">{activeSkippedCount} skipped</span>
            </div>
          </div>
        </div>

        <div className="audit-content stack" style={{ gap: "1.5rem" }}>
          {error ? (
            <div className="audit-error">{error}</div>
          ) : null}

          {tablesInDomain.map((table) => (
            <TableAuditCard
              key={table.table_name}
              table={table}
              questions={gapsByTable[table.table_name] || []}
              isSaving={savingTable === table.table_name}
              onReview={handleReview}
            />
          ))}
        </div>
      </div>

      <style jsx>{`
        .audit-panel {
          display: grid;
          grid-template-columns: 260px 1fr;
          min-height: 700px;
          background: var(--bg-surface);
          border: 1px solid var(--border);
          border-radius: 12px;
          overflow: hidden;
          box-shadow: 0 8px 32px rgba(0, 0, 0, 0.2);
        }
        .audit-sidebar {
          background: var(--bg-surface-alt);
          border-right: 1px solid var(--border);
          padding: 1.5rem 0;
          overflow-y: auto;
        }
        .audit-nav-item {
          padding: 1rem 1.25rem;
          cursor: pointer;
          display: flex;
          justify-content: space-between;
          align-items: center;
          transition: all 0.2s ease;
          border-left: 3px solid transparent;
          gap: 0.75rem;
        }
        .audit-nav-item:hover {
          background: rgba(255, 255, 255, 0.04);
        }
        .audit-nav-item.active {
          background: rgba(var(--accent-rgb), 0.1);
          border-left-color: var(--accent);
        }
        .domain-label {
          font-weight: 600;
          text-transform: capitalize;
          font-size: 0.9rem;
        }
        .audit-main {
          display: flex;
          flex-direction: column;
          overflow: hidden;
        }
        .audit-header {
          padding: 1.5rem 2rem;
          border-bottom: 1px solid var(--border);
          background: var(--bg-surface);
        }
        .audit-content {
          padding: 2rem;
          overflow-y: auto;
          flex: 1;
          background: rgba(15, 15, 15, 0.3);
        }
        .audit-error {
          padding: 0.9rem 1rem;
          border: 1px solid var(--danger);
          border-radius: 10px;
          background: rgba(239, 68, 68, 0.08);
          color: #fca5a5;
          font-size: 0.85rem;
        }
      `}</style>
    </div>
  );
}

function TableAuditCard({
  table,
  questions,
  isSaving,
  onReview,
}: {
  table: SemanticTable;
  questions: SemanticGap[];
  isSaving: boolean;
  onReview: (tableName: string, reviewStatus: SemanticTable["review_status"]) => void;
}) {
  const isNeeded = table.review_status === "confirmed";
  const isSkipped = table.review_status === "skipped";
  const statusLabel = isSkipped ? "Skipped" : isNeeded ? "Needed" : "Pending";
  const statusClass = isSkipped ? "" : isNeeded ? "pill-success" : "pill-warning";

  return (
    <div
      className={`card table-audit-card ${isSkipped ? "is-skipped" : ""}`}
      style={{ padding: "1.5rem" }}
    >
      <div className="card-top">
        <div className="stack" style={{ gap: "0.75rem" }}>
          <div style={{ display: "flex", gap: "0.75rem", alignItems: "center", flexWrap: "wrap" }}>
            <h3 style={{ margin: 0, fontSize: "1.15rem" }}>{table.table_name}</h3>
            <span className={`pill ${statusClass}`}>{statusLabel}</span>
            {table.likely_entity ? <span className="pill">{table.likely_entity}</span> : null}
          </div>

          <p style={{ margin: 0, color: "var(--text-main)", maxWidth: "760px" }}>
            {table.business_meaning || "No stable business meaning has been confirmed yet."}
          </p>

          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
            <span className="pill">{table.columns.length} columns</span>
            <span className="pill">{table.valid_joins.length} joins</span>
            <span className="pill pill-warning">{questions.length} open questions</span>
          </div>
        </div>

        <div className="action-row">
          <button
            className={`btn ${isNeeded ? "btn-success" : "btn-primary"}`}
            onClick={() => onReview(table.table_name, "confirmed")}
            disabled={isSaving}
          >
            {isSaving && !isSkipped ? "Saving..." : isNeeded ? "Needed" : "Keep Table"}
          </button>
          <button
            className="btn btn-outline"
            onClick={() => onReview(table.table_name, "skipped")}
            disabled={isSaving}
          >
            {isSaving && isSkipped ? "Saving..." : isSkipped ? "Skipped" : "Skip Table"}
          </button>
        </div>
      </div>

      <div className="table-grid">
        <div className="stack" style={{ gap: "0.75rem" }}>
          <span className="eyebrow">Open Review Questions</span>
          {questions.length > 0 ? (
            questions.map((gap) => (
              <div key={gap.gap_id} className="question-item">
                <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", alignItems: "center" }}>
                  <span className={`pill ${gap.is_blocking ? "pill-danger" : "pill-warning"}`}>
                    {GAP_LABELS[gap.category] || "Review"}
                  </span>
                  {gap.target_property ? (
                    <span className="question-property">{gap.target_property}</span>
                  ) : null}
                </div>
                <p>{gap.suggested_question || gap.description}</p>
                <span className="hint" style={{ fontSize: "0.75rem" }}>
                  {gap.description}
                </span>
              </div>
            ))
          ) : (
            <div className="empty-state">
              No open semantic questions for this table. Keep it if it matters for downstream
              TAG usage, or skip it to reduce review scope.
            </div>
          )}
        </div>

        <div className="stack" style={{ gap: "0.75rem" }}>
          <span className="eyebrow">What The System Found</span>

          <div className="detail-block">
            <strong>Important columns</strong>
            <div className="detail-list">
              {table.important_columns.length > 0 ? (
                table.important_columns.slice(0, 6).map((columnName) => (
                  <span key={columnName} className="detail-chip">
                    {columnName}
                  </span>
                ))
              ) : (
                <span className="hint">No standout columns detected yet.</span>
              )}
            </div>
          </div>

          <div className="detail-block">
            <strong>Relationships</strong>
            <div className="detail-list">
              {table.valid_joins.length > 0 ? (
                table.valid_joins.slice(0, 5).map((join) => (
                  <span key={join} className="detail-chip detail-chip-mono">
                    {join}
                  </span>
                ))
              ) : (
                <span className="hint">No clear joins detected.</span>
              )}
            </div>
          </div>

          {table.common_business_questions.length > 0 ? (
            <div className="detail-block">
              <strong>Business questions this table supports</strong>
              <div className="stack" style={{ gap: "0.5rem" }}>
                {table.common_business_questions.slice(0, 3).map((question) => (
                  <div key={question} className="question-preview">
                    {question}
                  </div>
                ))}
              </div>
            </div>
          ) : null}
        </div>
      </div>

      <style jsx>{`
        .table-audit-card {
          border: 1px solid var(--border);
          transition: transform 0.2s ease, box-shadow 0.2s ease, opacity 0.2s ease;
        }
        .table-audit-card:hover {
          transform: translateY(-1px);
          box-shadow: 0 10px 30px rgba(0, 0, 0, 0.22);
        }
        .table-audit-card.is-skipped {
          opacity: 0.72;
          background: rgba(255, 255, 255, 0.02);
        }
        .card-top {
          display: flex;
          justify-content: space-between;
          gap: 1rem;
          align-items: flex-start;
          margin-bottom: 1.5rem;
        }
        .action-row {
          display: flex;
          gap: 0.75rem;
          flex-wrap: wrap;
        }
        .table-grid {
          display: grid;
          grid-template-columns: minmax(0, 1.2fr) minmax(0, 0.8fr);
          gap: 1.25rem;
        }
        .question-item {
          display: flex;
          flex-direction: column;
          gap: 0.5rem;
          padding: 0.9rem 1rem;
          border-radius: 10px;
          border: 1px solid var(--border);
          background: rgba(255, 255, 255, 0.03);
        }
        .question-item p {
          margin: 0;
          font-size: 0.92rem;
          line-height: 1.45;
        }
        .question-property {
          padding: 0.2rem 0.45rem;
          border-radius: 999px;
          background: rgba(255, 255, 255, 0.08);
          font-size: 0.72rem;
          font-family: monospace;
        }
        .empty-state {
          padding: 1rem;
          border-radius: 10px;
          border: 1px dashed var(--border);
          color: var(--text-muted);
          background: rgba(255, 255, 255, 0.02);
          font-size: 0.85rem;
          line-height: 1.5;
        }
        .detail-block {
          padding: 0.9rem 1rem;
          border-radius: 10px;
          border: 1px solid var(--border);
          background: var(--bg-surface-alt);
        }
        .detail-block strong {
          display: block;
          margin-bottom: 0.75rem;
          font-size: 0.82rem;
        }
        .detail-list {
          display: flex;
          gap: 0.5rem;
          flex-wrap: wrap;
        }
        .detail-chip {
          padding: 0.3rem 0.55rem;
          border-radius: 999px;
          background: rgba(255, 255, 255, 0.05);
          font-size: 0.76rem;
        }
        .detail-chip-mono {
          font-family: monospace;
        }
        .question-preview {
          padding: 0.75rem 0.85rem;
          border-radius: 10px;
          background: rgba(var(--accent-rgb), 0.08);
          border: 1px solid rgba(var(--accent-rgb), 0.18);
          font-size: 0.82rem;
          line-height: 1.45;
        }
        @media (max-width: 1100px) {
          .card-top {
            flex-direction: column;
          }
          .table-grid {
            grid-template-columns: 1fr;
          }
        }
      `}</style>
    </div>
  );
}
