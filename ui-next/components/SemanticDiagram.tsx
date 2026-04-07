"use client";

import { KnowledgeState } from "../lib/types";

export default function SemanticDiagram({ state }: { state: KnowledgeState }) {
  const tables = Object.values(state.tables);
  const totalColumns = tables.reduce((sum, t) => sum + t.columns.length, 0);

  // Group by TABLE PREFIX (e.g., "event_log" → "event", "route_history" → "route")
  const groups: Record<string, typeof tables> = {};
  for (const table of tables) {
    const parts = table.table_name.split("_");
    const prefix = parts.length > 1 ? parts[0] : table.table_name;
    if (!groups[prefix]) groups[prefix] = [];
    groups[prefix].push(table);
  }

  // Sort by size (biggest domains first) and merge tiny groups into "other"
  const entries = Object.entries(groups);
  const significant = entries.filter(([, t]) => t.length >= 2).sort((a, b) => b[1].length - a[1].length);
  const singles = entries.filter(([, t]) => t.length < 2);
  const otherCount = singles.reduce((sum, [, t]) => sum + t.length, 0);

  // Confidence breakdown
  const highConf = tables.filter(t => t.confidence?.score >= 0.8).length;
  const medConf = tables.filter(t => t.confidence?.score >= 0.55 && t.confidence?.score < 0.8).length;
  const lowConf = tables.length - highConf - medConf;

  return (
    <div className="card" style={{ padding: '2rem' }}>
      {/* Clean confidence bar */}
      <div style={{ display: 'flex', height: 8, borderRadius: 4, overflow: 'hidden', marginBottom: '1.5rem' }}>
        {highConf > 0 && <div style={{ flex: highConf, background: 'var(--success)' }} title={`${highConf} high confidence`} />}
        {medConf > 0 && <div style={{ flex: medConf, background: 'var(--warning)' }} title={`${medConf} medium confidence`} />}
        {lowConf > 0 && <div style={{ flex: lowConf, background: 'var(--danger)' }} title={`${lowConf} low confidence`} />}
      </div>
      <div style={{ display: 'flex', gap: '1.5rem', fontSize: '0.75rem', color: 'var(--text-muted)', marginBottom: '2rem' }}>
        <span><span style={{ color: 'var(--success)' }}>●</span> {highConf} understood</span>
        <span><span style={{ color: 'var(--warning)' }}>●</span> {medConf} guessed</span>
        <span><span style={{ color: 'var(--danger)' }}>●</span> {lowConf} unclear</span>
      </div>

      {/* Domain groups as a clean grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: '0.75rem' }}>
        {significant.map(([prefix, groupTables]) => {
          const avgConf = groupTables.reduce((s, t) => s + (t.confidence?.score ?? 0), 0) / groupTables.length;
          const color = avgConf >= 0.8 ? 'var(--success)' : avgConf >= 0.55 ? 'var(--warning)' : 'var(--danger)';
          return (
            <div
              key={prefix}
              style={{
                padding: '1rem',
                background: 'var(--bg-surface-alt)',
                borderLeft: `3px solid ${color}`,
                borderRadius: '8px',
              }}
            >
              <div style={{ fontWeight: 600, fontSize: '0.9rem' }}>{prefix}</div>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.25rem' }}>
                {groupTables.length} table{groupTables.length > 1 ? 's' : ''} · {groupTables.reduce((s, t) => s + t.columns.length, 0)} cols
              </div>
            </div>
          );
        })}

        {otherCount > 0 && (
          <div
            style={{
              padding: '1rem',
              background: 'var(--bg-surface-alt)',
              borderLeft: '3px solid var(--border)',
              borderRadius: '8px',
            }}
          >
            <div style={{ fontWeight: 600, fontSize: '0.9rem', color: 'var(--text-muted)' }}>misc</div>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.25rem' }}>
              {otherCount} standalone table{otherCount > 1 ? 's' : ''}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
