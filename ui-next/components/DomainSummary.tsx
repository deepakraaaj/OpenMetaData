"use client";

import { KnowledgeState } from "../lib/types";
import { formatDomainGroupLabel } from "../lib/domain-groups";

export default function DomainSummary({ state, groups }: { state: KnowledgeState, groups: Record<string, string[]> }) {
  if (!groups || Object.keys(groups).length === 0) {
    return (
      <div className="card" style={{ display: 'flex', justifyContent: 'center', padding: '4rem' }}>
        <p className="hint">Identifying domains...</p>
      </div>
    );
  }

  // Pre-calculate domain confidence
  const domainStats = Object.entries(groups).map(([domain, tables]) => {
    const tableObjs = tables.map(t => state.tables[t]).filter(Boolean);
    const highConf = tableObjs.filter(t => (t.confidence?.score ?? 0) >= 0.8).length;
    const medConf = tableObjs.filter(t => { const s = t.confidence?.score ?? 0; return s >= 0.55 && s < 0.8; }).length;
    const lowConf = tableObjs.length - highConf - medConf;
    
    // Sort tables by connection count to show "Core Tables" first
    const sortedTables = tableObjs.sort((a, b) => b.valid_joins.length - a.valid_joins.length);

    return { domain, tables: sortedTables, counts: { highConf, medConf, lowConf, total: tableObjs.length } };
  }).sort((a, b) => b.tables.length - a.tables.length); // largest domains first

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(350px, 1fr))', gap: '1.5rem' }}>
        {domainStats.map(({ domain, tables, counts }) => (
          <div key={domain} className="card" style={{ display: 'flex', flexDirection: 'column' }}>
            <div style={{ borderBottom: '1px solid var(--border)', paddingBottom: '1rem', marginBottom: '1rem' }}>
              <h3 style={{ margin: 0, textTransform: 'capitalize', fontSize: '1.2rem', color: 'var(--text)' }}>
                {formatDomainGroupLabel(domain)}
              </h3>
              <div style={{ display: 'flex', gap: '1rem', fontSize: '0.75rem', marginTop: '0.5rem', color: 'var(--text-muted)' }}>
                <span>{counts.total} Tables</span>
                <span><span style={{ color: 'var(--success)' }}>●</span> {counts.highConf} High</span>
                <span><span style={{ color: 'var(--danger)' }}>●</span> {counts.lowConf} Needs Review</span>
              </div>
            </div>

            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '0.75rem', overflowY: 'auto', maxHeight: '300px' }}>
              {tables.map(table => {
                const confScore = table.confidence?.score ?? 0;
                let colorClass = 'var(--danger)';
                if (confScore >= 0.8) colorClass = 'var(--success)';
                else if (confScore >= 0.55) colorClass = 'var(--warning)';

                return (
                  <div key={table.table_name} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '0.85rem' }}>
                    <div style={{ flex: 1, textOverflow: 'ellipsis', overflow: 'hidden', whiteSpace: 'nowrap' }}>
                      <span style={{ color: colorClass, marginRight: '0.5rem', fontSize: '0.5rem' }}>●</span>
                      {table.table_name}
                    </div>
                    <div style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>
                      {table.valid_joins.length} joins
                    </div>
                  </div>
                );
              })}
            </div>
            {tables.length > 0 && (
              <div style={{ marginTop: '1rem', paddingTop: '1rem', borderTop: '1px solid var(--border)', fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                Core Hub: <strong>{tables[0].table_name}</strong>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
