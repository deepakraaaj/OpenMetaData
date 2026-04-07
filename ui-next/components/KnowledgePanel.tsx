"use client";

import { KnowledgeState, SemanticTable, SourceAttribution } from "../lib/types";

type Props = {
  state: KnowledgeState;
};

export default function KnowledgePanel({ state }: Props) {
  const tables = Object.values(state.tables);

  return (
    <div className="knowledge-panel">
      <div className="panel-header">
        <div className="stack">
          <h3>Knowledge Graph</h3>
          <span className="hint">{tables.length} tables interpreted</span>
        </div>
        <div className="progress-container" style={{ width: '100px', margin: 0 }}>
          <div 
            className="progress-bar" 
            style={{ width: `${state.readiness.readiness_percentage}%` }}
          ></div>
        </div>
      </div>

      <div className="panel-content stack">
        {tables.map((table) => (
          <TableSummaryCard key={table.table_name} table={table} />
        ))}

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
  return (
    <div className="card" style={{ padding: '1.25rem', marginBottom: '1rem' }}>
      <div className="stack">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
          <h4>{table.table_name}</h4>
          <span className="pill">{table.columns.length} cols</span>
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
