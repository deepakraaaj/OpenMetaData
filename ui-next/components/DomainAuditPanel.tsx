"use client";

import { useEffect, useMemo, useState } from "react";
import { applyAIDefaults, bulkReviewTables, reviewTable } from "../lib/client-api";
import { formatDomainGroupLabel } from "../lib/domain-groups";
import {
  BulkReviewAction,
  DecisionStatus,
  DomainReviewGroup,
  KnowledgeState,
  ReviewDebtItem,
  SemanticGap,
  SemanticTable,
} from "../lib/types";

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

const QUICK_ACTIONS: Array<{
  action: BulkReviewAction;
  label: string;
  description: string;
}> = [
  {
    action: "select_recommended",
    label: "Select All Recommended",
    description: "Accept the AI include/exclude recommendations in one pass.",
  },
  {
    action: "exclude_noise",
    label: "Exclude Logs / History",
    description: "Remove logs, audit trails, and system tables from scope.",
  },
  {
    action: "include_lookup_tables",
    label: "Include Lookup Tables",
    description: "Bring optional lookup/master tables into the selected set.",
  },
  {
    action: "include_all",
    label: "Include All",
    description: "Force every table into review scope.",
  },
];

export default function DomainAuditPanel({ state, groups, onStateUpdate }: Props) {
  const [activeDomain, setActiveDomain] = useState<string>("");
  const [savingTable, setSavingTable] = useState<string | null>(null);
  const [runningAction, setRunningAction] = useState<BulkReviewAction | null>(null);
  const [applyingDefaults, setApplyingDefaults] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [debtFilter, setDebtFilter] = useState<"all" | "ai_decided" | "warnings" | "blockers" | "overridden">("all");

  const domainGroups = useMemo(() => {
    if (state.domain_groups.length > 0) {
      return state.domain_groups;
    }
    return fallbackGroups(state, groups);
  }, [groups, state]);

  useEffect(() => {
    if (activeDomain && domainGroups.some((domain) => domain.domain === activeDomain)) {
      return;
    }
    setActiveDomain(domainGroups[0]?.domain || "");
  }, [activeDomain, domainGroups]);

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

  const activeGroup = domainGroups.find((domain) => domain.domain === activeDomain) || domainGroups[0];
  const tablesInDomain = useMemo(() => {
    const names = activeGroup?.tables || [];
    return names
      .map((name) => state.tables[name])
      .filter(Boolean)
      .filter((table) => matchesFilter(table, debtFilter))
      .sort((left, right) => {
        const leftScore = reviewPriority(left, gapsByTable[left.table_name] || []);
        const rightScore = reviewPriority(right, gapsByTable[right.table_name] || []);
        if (leftScore !== rightScore) {
          return rightScore - leftScore;
        }
        return left.table_name.localeCompare(right.table_name);
      });
  }, [activeGroup, debtFilter, gapsByTable, state.tables]);

  const handleReview = async (tableName: string, reviewStatus: SemanticTable["review_status"]) => {
    setError("");
    setSavingTable(tableName);
    try {
      const updated = await reviewTable(state.source_name, tableName, reviewStatus, "Admin User");
      onStateUpdate(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save table decision.");
    } finally {
      setSavingTable(null);
    }
  };

  const handleQuickAction = async (action: BulkReviewAction) => {
    setError("");
    setRunningAction(action);
    try {
      const updated = await bulkReviewTables(state.source_name, action, "Admin User");
      onStateUpdate(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to apply bulk review action.");
    } finally {
      setRunningAction(null);
    }
  };

  const handleAiDefaults = async (payload: { domain_name?: string; table_name?: string }, key: string) => {
    setError("");
    setApplyingDefaults(key);
    try {
      const updated = await applyAIDefaults(state.source_name, payload);
      onStateUpdate(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to apply AI defaults.");
    } finally {
      setApplyingDefaults(null);
    }
  };

  const filteredDebt = state.review_debt.filter((item) => matchesDebtFilter(item, debtFilter));

  if (domainGroups.length === 0) {
    return (
      <div className="card" style={{ padding: "4rem", textAlign: "center" }}>
        <p className="hint">No domain recommendations are available yet.</p>
      </div>
    );
  }

  const summary = state.review_summary;

  return (
    <div style={{ display: "grid", gap: "1.5rem" }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: "1rem" }}>
        <SummaryCard label="Analyzed" value={summary.analyzed_table_count} />
        <SummaryCard label="Selected" value={summary.selected_count} tone="success" />
        <SummaryCard label="Excluded" value={summary.excluded_count} />
        <SummaryCard label="Needs Review" value={summary.review_count} tone="warning" />
        <SummaryCard label="Review Later" value={summary.review_debt_count} tone="warning" />
        <SummaryCard label="Publish Blockers" value={summary.publish_blocked_count + summary.warning_ack_required_count} tone="warning" />
      </div>

      <div className="card" style={{ padding: "1.25rem 1.5rem", display: "grid", gap: "1rem" }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: "1rem", flexWrap: "wrap" }}>
          <div className="stack" style={{ gap: "0.35rem" }}>
            <span className="eyebrow">Quick Actions</span>
            <p className="hint" style={{ margin: 0 }}>
              Accept the AI defaults or correct broad classes of tables without drilling into each one.
            </p>
          </div>
          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
            {QUICK_ACTIONS.map((item) => (
              <button
                key={item.action}
                className="btn btn-outline"
                disabled={runningAction !== null}
                onClick={() => handleQuickAction(item.action)}
              >
                {runningAction === item.action ? "Applying..." : item.label}
              </button>
            ))}
          </div>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "0.75rem" }}>
          {QUICK_ACTIONS.map((item) => (
            <div key={item.action} style={{ padding: "0.85rem 0.9rem", borderRadius: "12px", background: "var(--bg-surface-alt)" }}>
              <strong style={{ display: "block", marginBottom: "0.35rem" }}>{item.label}</strong>
              <span className="hint" style={{ fontSize: "0.76rem" }}>{item.description}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="card" style={{ padding: "1.25rem 1.5rem", display: "grid", gap: "1rem" }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: "1rem", flexWrap: "wrap" }}>
          <div className="stack" style={{ gap: "0.35rem" }}>
            <span className="eyebrow">Review Later Filters</span>
            <p className="hint" style={{ margin: 0 }}>
              Reopen only the AI-decided, warning, blocker, or overridden items instead of replaying the whole review.
            </p>
          </div>
          <div style={{ display: "flex", gap: "0.45rem", flexWrap: "wrap" }}>
            {[
              { value: "all", label: "All" },
              { value: "ai_decided", label: "AI Decided" },
              { value: "warnings", label: "Warnings" },
              { value: "blockers", label: "Blockers" },
              { value: "overridden", label: "Overridden" },
            ].map((item) => (
              <button
                key={item.value}
                className={`btn ${debtFilter === item.value ? "btn-primary" : "btn-outline"}`}
                onClick={() => setDebtFilter(item.value as typeof debtFilter)}
              >
                {item.label}
              </button>
            ))}
          </div>
        </div>
        <div style={{ display: "grid", gap: "0.75rem" }}>
          {filteredDebt.length > 0 ? (
            filteredDebt.slice(0, 8).map((item) => (
              <div
                key={item.decision_id}
                style={{
                  padding: "0.95rem 1rem",
                  borderRadius: "14px",
                  background: "var(--bg-surface-alt)",
                  display: "grid",
                  gap: "0.45rem",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", gap: "0.75rem", alignItems: "center" }}>
                  <strong>{item.table_name || item.title}</strong>
                  <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap" }}>
                    <span className={`pill ${item.publish_blocker ? "pill-warning" : item.decision_status === "auto_accepted" ? "pill-success" : ""}`}>
                      {labelForDecisionStatus(item.decision_status)}
                    </span>
                    <span className="pill">{item.risk_level}</span>
                  </div>
                </div>
                <span className="hint" style={{ fontSize: "0.75rem" }}>
                  {item.policy_reason || "AI decided for now and left this available for later review."}
                </span>
              </div>
            ))
          ) : (
            <p className="hint" style={{ margin: 0 }}>
              No items match the current filter.
            </p>
          )}
        </div>
      </div>

      {state.review_queue.length > 0 ? (
        <div className="card" style={{ padding: "1.25rem 1.5rem" }}>
          <div className="stack" style={{ gap: "0.35rem", marginBottom: "1rem" }}>
            <span className="eyebrow">Review Queue</span>
            <p className="hint" style={{ margin: 0 }}>
              Only high-impact or low-confidence tables are shown here first.
            </p>
          </div>
          <div style={{ display: "grid", gap: "0.75rem" }}>
            {state.review_queue.slice(0, 8).map((item) => (
              <div
                key={item.table_name}
                style={{
                  padding: "0.95rem 1rem",
                  borderRadius: "14px",
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
                    <span className={`pill ${item.publish_blocker ? "pill-warning" : item.decision_status === "auto_accepted" ? "pill-success" : ""}`}>
                      {labelForDecisionStatus(item.decision_status)}
                    </span>
                  </div>
                </div>
                <span className="hint" style={{ fontSize: "0.75rem" }}>
                  {item.selection_reason || item.reason_for_classification || "Needs review."}
                </span>
                <span className="hint" style={{ fontSize: "0.72rem" }}>
                  {formatDomainGroupLabel(item.domain || "Configuration / Internal")} • {item.open_gap_count} open issue(s)
                </span>
                {item.review_reason ? (
                  <span className="hint" style={{ fontSize: "0.72rem" }}>
                    Review: {item.review_reason}
                  </span>
                ) : null}
              </div>
            ))}
          </div>
        </div>
      ) : null}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: "1rem" }}>
        {domainGroups.map((domain) => (
          <button
            key={domain.domain}
            type="button"
            onClick={() => setActiveDomain(domain.domain)}
            className="card"
            style={{
              textAlign: "left",
              border: activeDomain === domain.domain ? "1px solid var(--accent)" : "1px solid var(--border)",
              background: activeDomain === domain.domain ? "rgba(var(--accent-rgb), 0.08)" : "var(--bg-surface)",
              padding: "1.2rem 1.25rem",
              cursor: "pointer",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", gap: "0.75rem", alignItems: "flex-start" }}>
              <div className="stack" style={{ gap: "0.35rem" }}>
                <strong>{formatDomainGroupLabel(domain.domain)}</strong>
                <span className="hint" style={{ fontSize: "0.75rem" }}>
                  {domain.tables.length} tables
                </span>
                {domain.inferred_business_meaning ? (
                  <span className="hint" style={{ fontSize: "0.72rem" }}>
                    {domain.inferred_business_meaning}
                  </span>
                ) : null}
              </div>
              <span
                className={`pill ${
                  domain.confidence.label === "high"
                    ? "pill-success"
                    : domain.confidence.label === "low"
                      ? "pill-warning"
                      : ""
                }`}
              >
                {domain.confidence.label}
              </span>
            </div>
            <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap", marginTop: "0.9rem" }}>
              <span className="pill pill-success">{domain.selected_count} selected</span>
              <span className="pill">{domain.excluded_count} excluded</span>
              <span className="pill pill-warning">{domain.review_count} review</span>
              <span className="pill pill-warning">{domain.review_debt_count} later</span>
              {domain.publish_blocker_count > 0 ? (
                <span className="pill pill-warning">{domain.publish_blocker_count} blocker</span>
              ) : null}
            </div>
          </button>
        ))}
      </div>

      {error ? (
        <div className="audit-error">{error}</div>
      ) : null}

      {activeGroup ? (
        <div className="card" style={{ padding: "1.5rem", display: "grid", gap: "1rem" }}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: "1rem", flexWrap: "wrap" }}>
            <div className="stack" style={{ gap: "0.4rem" }}>
              <span className="eyebrow">Domain Review</span>
              <h2 style={{ margin: 0 }}>{formatDomainGroupLabel(activeGroup.domain)}</h2>
              <p className="hint" style={{ margin: 0 }}>
                Expand a table only when you need more detail. Most tables should be a one-click confirmation.
              </p>
              {activeGroup.review_reason ? (
                <p className="hint" style={{ margin: 0 }}>
                  Review focus: {activeGroup.review_reason}
                </p>
              ) : null}
            </div>
            <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
              <span className="pill pill-success">{activeGroup.selected_count} selected</span>
              <span className="pill">{activeGroup.excluded_count} excluded</span>
              <span className="pill pill-warning">{activeGroup.review_count} pending</span>
              <span className="pill pill-warning">{activeGroup.review_debt_count} later</span>
              {activeGroup.publish_blocker_count > 0 ? (
                <span className="pill pill-warning">{activeGroup.publish_blocker_count} blocker</span>
              ) : null}
              <button
                className="btn btn-outline"
                onClick={() => handleAiDefaults({ domain_name: activeGroup.domain }, `domain:${activeGroup.domain}`)}
                disabled={applyingDefaults !== null}
              >
                {applyingDefaults === `domain:${activeGroup.domain}` ? "Applying..." : "Let AI Decide This Domain"}
              </button>
            </div>
          </div>

          {activeGroup.anchor_tables.length > 0 ? (
            <div style={{ display: "flex", gap: "0.45rem", flexWrap: "wrap" }}>
              {activeGroup.anchor_tables.map((tableName) => (
                <span key={tableName} className="pill">
                  Anchor: {tableName}
                </span>
              ))}
            </div>
          ) : null}

          <div style={{ display: "grid", gap: "0.85rem" }}>
            {tablesInDomain.map((table) => (
              <TableAuditDisclosure
                key={table.table_name}
                table={table}
                questions={gapsByTable[table.table_name] || []}
                isSaving={savingTable === table.table_name}
                onReview={handleReview}
                onUseAIDefault={() => handleAiDefaults({ table_name: table.table_name }, `table:${table.table_name}`)}
                applyingDefault={applyingDefaults === `table:${table.table_name}`}
              />
            ))}
          </div>
        </div>
      ) : null}

      <style jsx>{`
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

function TableAuditDisclosure({
  table,
  questions,
  isSaving,
  onReview,
  onUseAIDefault,
  applyingDefault,
}: {
  table: SemanticTable;
  questions: SemanticGap[];
  isSaving: boolean;
  onReview: (tableName: string, reviewStatus: SemanticTable["review_status"]) => void;
  onUseAIDefault: () => void;
  applyingDefault: boolean;
}) {
  const selectionLabel =
    table.review_status === "confirmed"
      ? "Included"
      : table.review_status === "skipped"
        ? "Excluded"
        : table.selected
          ? "AI Selected"
          : "AI Excluded";
  const selectionTone =
    table.review_status === "confirmed" || (table.review_status === "pending" && table.selected)
      ? "pill-success"
      : table.requires_review || table.needs_review
        ? "pill-warning"
        : "";

  return (
    <details
      style={{
        border: "1px solid var(--border)",
        borderRadius: "16px",
        background: "var(--bg-surface-alt)",
        overflow: "hidden",
      }}
    >
      <summary
        style={{
          listStyle: "none",
          cursor: "pointer",
          padding: "1rem 1.1rem",
          display: "grid",
          gap: "0.65rem",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", gap: "1rem", alignItems: "flex-start", flexWrap: "wrap" }}>
          <div className="stack" style={{ gap: "0.3rem" }}>
            <strong style={{ fontSize: "1rem" }}>{table.table_name}</strong>
            <span className="hint" style={{ fontSize: "0.76rem" }}>
              {table.selection_reason || table.reason_for_classification || table.business_meaning || "Awaiting classification explanation"}
            </span>
            {table.review_reason ? (
              <span className="hint" style={{ fontSize: "0.72rem" }}>
                Review: {table.review_reason}
              </span>
            ) : null}
          </div>
          <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap", justifyContent: "flex-end" }}>
            <span className="pill">{table.role.replace(/_/g, " ")}</span>
            <span className={`pill ${selectionTone}`}>{selectionLabel}</span>
            <span className="pill">{table.confidence.label} confidence</span>
            <span className={`pill ${table.publish_blocker ? "pill-warning" : table.decision_status === "auto_accepted" ? "pill-success" : ""}`}>
              {labelForDecisionStatus(table.decision_status)}
            </span>
          </div>
        </div>
      </summary>

      <div style={{ padding: "0 1.1rem 1.1rem", display: "grid", gap: "1rem" }}>
        <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
          <span className="pill">{table.columns.length} columns</span>
          <span className="pill">{table.related_tables.length} related tables</span>
          <span className="pill pill-warning">{questions.length} open review items</span>
          <span className="pill">impact {table.impact_score.toFixed(2)}</span>
        </div>

        <p style={{ margin: 0, color: "var(--text-main)" }}>
          {table.business_meaning || "No stable business meaning has been confirmed yet."}
        </p>

        {table.related_tables.length > 0 ? (
          <div>
            <div className="eyebrow" style={{ marginBottom: "0.5rem" }}>
              Related Tables
            </div>
            <div style={{ display: "flex", gap: "0.45rem", flexWrap: "wrap" }}>
              {table.related_tables.slice(0, 8).map((item) => (
                <span key={item} className="pill">
                  {item}
                </span>
              ))}
            </div>
          </div>
        ) : null}

        {questions.length > 0 ? (
          <div style={{ display: "grid", gap: "0.6rem" }}>
            <div className="eyebrow">Open Questions</div>
            {questions.slice(0, 3).map((gap) => (
              <div
                key={gap.gap_id}
                style={{
                  padding: "0.8rem 0.9rem",
                  borderRadius: "12px",
                  background: "rgba(255,255,255,0.04)",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", gap: "0.75rem", alignItems: "center", marginBottom: "0.35rem" }}>
                  <span className="pill pill-warning">{GAP_LABELS[gap.category] || "Review"}</span>
                  <span className="hint" style={{ fontSize: "0.72rem" }}>
                    Priority {gap.priority}
                  </span>
                </div>
                <p className="hint" style={{ margin: 0 }}>
                  {gap.description}
                </p>
              </div>
            ))}
          </div>
        ) : null}

        <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
          <button
            className="btn btn-outline"
            onClick={onUseAIDefault}
            disabled={applyingDefault}
          >
            {applyingDefault ? "Applying..." : "Use AI Suggestion"}
          </button>
          <button
            className={`btn ${table.selected ? "btn-success" : "btn-primary"}`}
            onClick={() => onReview(table.table_name, "confirmed")}
            disabled={isSaving}
          >
            {isSaving && table.selected ? "Saving..." : "Include Table"}
          </button>
          <button
            className="btn btn-outline"
            onClick={() => onReview(table.table_name, "skipped")}
            disabled={isSaving}
          >
            {isSaving && !table.selected ? "Saving..." : "Exclude Table"}
          </button>
        </div>
      </div>
    </details>
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
  const color =
    tone === "success" ? "var(--success)" : tone === "warning" ? "var(--warning)" : "var(--accent)";
  return (
    <div className="card" style={{ padding: "1.15rem 1.2rem" }}>
      <div className="hint" style={{ fontSize: "0.8rem", marginBottom: "0.45rem" }}>
        {label}
      </div>
      <div style={{ fontSize: "2rem", fontWeight: 700, color }}>{value}</div>
    </div>
  );
}

function reviewPriority(table: SemanticTable, gaps: SemanticGap[]) {
  const selectionWeight = table.selected ? 2 : 1;
  const uncertaintyWeight = table.requires_review || table.needs_review ? 2 : 0;
  return selectionWeight + uncertaintyWeight + gaps.length * 2 + (1 - table.confidence.score) + table.impact_score;
}

function labelForDecisionStatus(status?: DecisionStatus) {
  if (status === "auto_accepted") return "AI Decided";
  if (status === "user_confirmed") return "User Confirmed";
  if (status === "user_overridden") return "User Overrode";
  if (status === "publish_blocked") return "Publish Blocker";
  if (status === "warning_ack_required") return "Ack Required";
  if (status === "deferred_review") return "Needs Review Later";
  return "Needs Review";
}

function matchesFilter(table: SemanticTable, filter: "all" | "ai_decided" | "warnings" | "blockers" | "overridden") {
  if (filter === "all") return true;
  if (filter === "ai_decided") {
    return table.decision_actor === "ai_auto" || table.decision_status === "auto_accepted";
  }
  if (filter === "warnings") {
    return table.decision_status === "warning_ack_required" || table.review_debt;
  }
  if (filter === "blockers") {
    return table.publish_blocker || table.decision_status === "publish_blocked";
  }
  if (filter === "overridden") {
    return table.decision_status === "user_overridden";
  }
  return true;
}

function matchesDebtFilter(item: ReviewDebtItem, filter: "all" | "ai_decided" | "warnings" | "blockers" | "overridden") {
  if (filter === "all") return true;
  if (filter === "ai_decided") {
    return item.decision_actor === "ai_auto" || item.decision_status === "auto_accepted";
  }
  if (filter === "warnings") {
    return item.decision_status === "warning_ack_required" || item.review_debt;
  }
  if (filter === "blockers") {
    return item.publish_blocker || item.decision_status === "publish_blocked";
  }
  if (filter === "overridden") {
    return item.decision_status === "user_overridden";
  }
  return true;
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
        members.length > 0
          ? `Business area centered on ${members.slice(0, 3).map((table) => table.table_name).join(", ")}.`
          : undefined,
      requires_review: members.some((table) => table.requires_review),
      review_reason: members.find((table) => table.review_reason)?.review_reason,
      confidence: {
        label: avgScore >= 0.78 ? "high" : avgScore >= 0.55 ? "medium" : "low",
        score: Number(avgScore.toFixed(2)),
        rationale: ["Derived from table confidence scores"],
      },
      review_debt_count: members.filter((table) => table.review_debt).length,
      publish_blocker_count: members.filter((table) => table.publish_blocker).length,
      warning_ack_required_count: members.filter((table) => table.needs_acknowledgement).length,
    };
  });
}
