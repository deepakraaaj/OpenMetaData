"use client";

import { KnowledgeState } from "../lib/types";

export default function SemanticDiagram({ state }: { state: KnowledgeState }) {
  const tables = Object.values(state.tables);
  const totalColumns = tables.reduce((sum, t) => sum + t.columns.length, 0);

  // Group tables by likely_entity or first word of table name
  const groups: Record<string, typeof tables> = {};
  for (const table of tables) {
    const group = table.likely_entity || table.table_name.split("_")[0] || "other";
    if (!groups[group]) groups[group] = [];
    groups[group].push(table);
  }

  const sortedGroups = Object.entries(groups).sort((a, b) => b[1].length - a[1].length);

  return (
    <div className="card" style={{ padding: '2rem' }}>
      <span className="eyebrow">Semantic Object Model</span>

      {/* Summary stats */}
      <div style={{ display: 'flex', gap: '2rem', margin: '1.5rem 0', flexWrap: 'wrap' }}>
        <div>
          <span style={{ fontSize: '1.5rem', fontWeight: 700, color: 'var(--accent)' }}>{tables.length}</span>
          <span className="hint" style={{ marginLeft: '0.5rem' }}>tables</span>
        </div>
        <div>
          <span style={{ fontSize: '1.5rem', fontWeight: 700, color: 'var(--text-main)' }}>{totalColumns}</span>
          <span className="hint" style={{ marginLeft: '0.5rem' }}>columns</span>
        </div>
        <div>
          <span style={{ fontSize: '1.5rem', fontWeight: 700, color: 'var(--text-main)' }}>{sortedGroups.length}</span>
          <span className="hint" style={{ marginLeft: '0.5rem' }}>entity groups</span>
        </div>
      </div>

      {/* Entity groups as a compact grid */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
        {sortedGroups.slice(0, 12).map(([group, groupTables]) => (
          <div key={group}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '0.75rem' }}>
              <span style={{
                fontSize: '0.75rem',
                fontWeight: 600,
                textTransform: 'uppercase',
                letterSpacing: '0.05em',
                color: 'var(--accent)',
              }}>
                {group}
              </span>
              <span className="hint" style={{ fontSize: '0.75rem' }}>
                {groupTables.length} table{groupTables.length > 1 ? 's' : ''}
              </span>
              <div style={{ flex: 1, height: 1, background: 'var(--border)' }} />
            </div>

            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem' }}>
              {groupTables.map((table) => {
                const conf = table.confidence?.score ?? 0;
                const borderColor = conf >= 0.8 ? 'var(--success)' : conf >= 0.55 ? 'var(--warning)' : 'var(--danger)';
                return (
                  <div
                    key={table.table_name}
                    title={`${table.table_name}\n${table.business_meaning || 'No meaning yet'}\nConfidence: ${(conf * 100).toFixed(0)}%`}
                    style={{
                      padding: '0.4rem 0.75rem',
                      background: 'var(--bg-surface-alt)',
                      border: `1px solid ${borderColor}`,
                      borderRadius: '6px',
                      fontSize: '0.75rem',
                      fontFamily: 'monospace',
                      cursor: 'default',
                      whiteSpace: 'nowrap',
                      transition: 'all 0.15s ease',
                    }}
                  >
                    {table.table_name}
                    <span style={{ marginLeft: '0.5rem', fontSize: '0.65rem', color: 'var(--text-muted)' }}>
                      ({table.columns.length})
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        ))}

        {sortedGroups.length > 12 && (
          <p className="hint" style={{ textAlign: 'center' }}>
            + {sortedGroups.length - 12} more entity groups ({tables.length - sortedGroups.slice(0, 12).reduce((s, [, t]) => s + t.length, 0)} tables)
          </p>
        )}
      </div>

      <div className="hint" style={{ marginTop: '1.5rem', textAlign: 'center', fontSize: '0.75rem' }}>
        <span style={{ color: 'var(--success)' }}>■</span> High confidence
        {' · '}
        <span style={{ color: 'var(--warning)' }}>■</span> Medium
        {' · '}
        <span style={{ color: 'var(--danger)' }}>■</span> Low — needs review
      </div>
    </div>
  );
}
