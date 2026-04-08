"use client";

import { KnowledgeState, SemanticTable, SourceAttribution } from "../lib/types";

type Props = {
  state: KnowledgeState;
};

export default function KnowledgePanel({ state }: Props) {
  const tables = Object.values(state.tables);
  const keptTables = tables.filter((table) => table.review_status === "confirmed");
  const skippedTables = tables.filter((table) => table.review_status === "skipped");
  const decidedTables = keptTables.length + skippedTables.length;
  const decisionPercentage = (decidedTables / Math.max(tables.length, 1)) * 100;

  return (
    <div className="knowledge-panel">
      <div className="panel-header" style={{ paddingBottom: '1.5rem' }}>
        <div className="stack">
          <h3>Knowledge Graph</h3>
          <span className="hint">{tables.length} tables in scope</span>
        </div>
        <div className="stack" style={{ alignItems: 'flex-end', gap: '0.25rem' }}>
          <span className="eyebrow" style={{ fontSize: '0.65rem' }}>Readiness</span>
          <div className="progress-container" style={{ width: '80px', margin: 0, height: '4px' }}>
            <div 
              className="progress-bar" 
              style={{ width: `${state.readiness.readiness_percentage}%`, background: 'var(--accent)' }}
            ></div>
          </div>
        </div>
      </div>

      <div className="panel-content stack">
        <div className="card" style={{ padding: '1rem', background: 'rgba(var(--success-rgb), 0.05)', border: '1px solid rgba(var(--success-rgb), 0.2)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.5rem' }}>
            <span style={{ fontSize: '0.8rem', fontWeight: 600 }}>Table Decisions</span>
            <span className="hint" style={{ fontSize: '0.8rem' }}>{decidedTables}/{tables.length}</span>
          </div>
          <div className="progress-container" style={{ height: '6px' }}>
            <div 
              className="progress-bar" 
              style={{ width: `${decisionPercentage}%`, background: 'var(--success)' }}
            ></div>
          </div>
          <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.75rem', flexWrap: 'wrap' }}>
            <span className="pill pill-success">{keptTables.length} needed</span>
            <span className="pill pill-warning">{tables.length - decidedTables} pending</span>
            <span className="pill">{skippedTables.length} skipped</span>
          </div>
        </div>

        <div className="stack" style={{ marginTop: '1rem' }}>
          <span className="eyebrow">Entity Clusters</span>
          {tables.map((table) => (
            <TableSummaryCard key={table.table_name} table={table} />
          ))}
        </div>

        {state.unresolved_gaps.length > 0 && (
          <div className="stack" style={{ marginTop: '2rem' }}>
            <span className="eyebrow">Unresolved Gaps</span>
            {state.unresolved_gaps.map((gap) => (
              <div key={gap.gap_id} className="card" style={{ padding: '1rem', gap: '0.5rem' }}>
                <span className={`pill ${gap.is_blocking ? 'pill-danger' : 'pill-warning'}`}>
                  {gap.category.replace(/_/g, ' ')}
                </span>
                <p style={{ fontSize: '0.875rem' }}>{gap.description}</p>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function TableSummaryCard({ table }: { table: SemanticTable }) {
  const statusLabel = {
    pending: "Pending",
    confirmed: "Needed",
    skipped: "Skipped",
  }[table.review_status];
  const statusClass = {
    pending: "pill-warning",
    confirmed: "pill-success",
    skipped: "",
  }[table.review_status];

  return (
    <div className="card" style={{ padding: '1.25rem', marginBottom: '1rem' }}>
      <div className="stack">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
          <h4>{table.table_name}</h4>
          <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
            <span className={`pill ${statusClass}`}>{statusLabel}</span>
            <span className="pill">{table.columns.length} cols</span>
          </div>
        </div>
        <p className="hint" style={{ fontSize: '0.8rem' }}>{table.business_meaning}</p>
        
        <AttributionTag attribution={table.attribution} />
      </div>

      {table.columns.length > 0 && (
        <div className="stack" style={{ gap: '0.5rem', marginTop: '0.5rem' }}>
          {table.columns.slice(0, 3).map(col => (
            <div key={col.column_name} style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem' }}>
              <span>{col.column_name}</span>
              <span className="hint">{col.technical_type}</span>
            </div>
          ))}
          {table.columns.length > 3 && <span className="hint" style={{ fontSize: '0.7rem' }}>+ {table.columns.length - 3} more columns</span>}
        </div>
      )}
    </div>
  );
}

function AttributionTag({ attribution }: { attribution: SourceAttribution }) {
  const iconClass = {
    pulled_from_db_schema: "icon-pulled",
    inferred_by_system: "icon-inferred",
    confirmed_by_user: "icon-confirmed",
    provided_by_user: "icon-confirmed",
  }[attribution.source];

  return (
    <div className="attribution-tag">
      <div className={`attribution-icon ${iconClass}`}></div>
      <span>{attribution.source.replace(/_/g, ' ')}</span>
    </div>
  );
}
