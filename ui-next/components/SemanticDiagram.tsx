"use client";

import { useState, useEffect } from "react";
import { aiGroupTables } from "../lib/client-api";
import { KnowledgeState } from "../lib/types";

type TableGroups = Record<string, string[]>;

export default function SemanticDiagram({ state }: { state: KnowledgeState }) {
  const [groups, setGroups] = useState<TableGroups | null>(null);
  const [loading, setLoading] = useState(false);
  const tables = Object.values(state.tables);
  const sourceName = state.source_name;

  // Try AI grouping, fall back to prefix-based
  useEffect(() => {
    if (!sourceName || tables.length === 0) return;
    setLoading(true);
    aiGroupTables(sourceName)
      .then((res) => setGroups(res.groups))
      .catch(() => setGroups(prefixGroup(state)))
      .finally(() => setLoading(false));
  }, [sourceName, tables.length]);

  const displayGroups = groups || prefixGroup(state);
  const sortedGroups = Object.entries(displayGroups).sort((a, b) => b[1].length - a[1].length);

  // Confidence breakdown
  const highConf = tables.filter(t => (t.confidence?.score ?? 0) >= 0.8).length;
  const medConf = tables.filter(t => {
    const s = t.confidence?.score ?? 0;
    return s >= 0.55 && s < 0.8;
  }).length;
  const lowConf = tables.length - highConf - medConf;

  return (
    <div className="card" style={{ padding: '2rem' }}>
      {/* Confidence bar */}
      <div style={{ display: 'flex', height: 6, borderRadius: 3, overflow: 'hidden', marginBottom: '1rem' }}>
        {highConf > 0 && <div style={{ flex: highConf, background: 'var(--success)' }} />}
        {medConf > 0 && <div style={{ flex: medConf, background: 'var(--warning)' }} />}
        {lowConf > 0 && <div style={{ flex: lowConf, background: 'var(--danger)' }} />}
      </div>
      <div style={{ display: 'flex', gap: '1.5rem', fontSize: '0.7rem', color: 'var(--text-muted)', marginBottom: '1.5rem' }}>
        <span><span style={{ color: 'var(--success)' }}>●</span> {highConf} understood</span>
        <span><span style={{ color: 'var(--warning)' }}>●</span> {medConf} guessed</span>
        <span><span style={{ color: 'var(--danger)' }}>●</span> {lowConf} unclear</span>
        {loading && <span style={{ marginLeft: 'auto', fontStyle: 'italic' }}>AI grouping...</span>}
        {groups && !loading && <span style={{ marginLeft: 'auto', color: 'var(--accent)' }}>✦ AI-grouped</span>}
      </div>

      {/* Domain groups */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: '0.75rem' }}>
        {sortedGroups.map(([domain, tableNames]) => {
          const domainTables = tableNames.map(n => state.tables[n]).filter(Boolean);
          const avg = domainTables.length > 0
            ? domainTables.reduce((s, t) => s + (t.confidence?.score ?? 0), 0) / domainTables.length
            : 0;
          const color = avg >= 0.8 ? 'var(--success)' : avg >= 0.55 ? 'var(--warning)' : 'var(--danger)';
          return (
            <div
              key={domain}
              style={{
                padding: '0.75rem 1rem',
                background: 'var(--bg-surface-alt)',
                borderLeft: `3px solid ${color}`,
                borderRadius: '8px',
              }}
            >
              <div style={{ fontWeight: 600, fontSize: '0.85rem', textTransform: 'capitalize' }}>{domain}</div>
              <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginTop: '0.2rem' }}>
                {tableNames.length} table{tableNames.length > 1 ? 's' : ''}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function prefixGroup(state: KnowledgeState): TableGroups {
  const groups: TableGroups = {};
  for (const name of Object.keys(state.tables)) {
    const parts = name.split("_");
    const prefix = parts.length > 1 ? parts[0] : name;
    if (!groups[prefix]) groups[prefix] = [];
    groups[prefix].push(name);
  }
  const misc: string[] = [];
  const merged: TableGroups = {};
  for (const [prefix, tables] of Object.entries(groups)) {
    if (tables.length < 2) misc.push(...tables);
    else merged[prefix] = tables;
  }
  if (misc.length) merged["misc"] = misc;
  return merged;
}
