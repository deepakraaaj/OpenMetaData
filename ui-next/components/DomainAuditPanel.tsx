"use client";

import { useState } from "react";
import { KnowledgeState, SemanticTable } from "../lib/types";
import { confirmTable } from "../lib/client-api";
import { formatDomainGroupLabel } from "../lib/domain-groups";

type Props = {
  state: KnowledgeState;
  groups: Record<string, string[]>;
  onStateUpdate: (state: KnowledgeState) => void;
};

export default function DomainAuditPanel({ state, groups, onStateUpdate }: Props) {
  const [activeDomain, setActiveDomain] = useState<string>(Object.keys(groups)[0] || "");
  const [confirming, setConfirming] = useState<string | null>(null);

  const domainNames = Object.keys(groups);
  const tablesInDomain = groups[activeDomain]?.map(name => state.tables[name]).filter(Boolean) || [];

  const handleConfirm = async (tableName: string) => {
    setConfirming(tableName);
    try {
      const updated = await confirmTable(state.source_name, tableName, "Admin User");
      onStateUpdate(updated);
    } catch (err) {
      console.error("Failed to confirm table:", err);
    } finally {
      setConfirming(null);
    }
  };

  if (domainNames.length === 0) {
    return (
      <div className="card" style={{ padding: '4rem', textAlign: 'center' }}>
        <p className="hint">No domains identified for auditing yet.</p>
      </div>
    );
  }

  return (
    <div className="audit-panel">
      {/* Sidebar navigation */}
      <div className="audit-sidebar">
        <span className="eyebrow" style={{ padding: '0 1rem', marginBottom: '1rem', display: 'block' }}>Business Domains</span>
        {domainNames.map(domain => {
          const tableCount = groups[domain].length;
          const confirmedCount = groups[domain].filter(name => state.tables[name]?.attribution.source === 'confirmed_by_user').length;
          const isComplete = confirmedCount === tableCount;

          return (
            <div 
              key={domain} 
              className={`audit-nav-item ${activeDomain === domain ? 'active' : ''}`}
              onClick={() => setActiveDomain(domain)}
            >
              <div className="stack" style={{ gap: '0.25rem' }}>
                <span className="domain-label">{formatDomainGroupLabel(domain)}</span>
                <span className="hint" style={{ fontSize: '0.7rem' }}>
                  {isComplete ? '✅ All Reviewed' : `${confirmedCount}/${tableCount} Confirmed`}
                </span>
              </div>
              {isComplete && <div className="dot-success" />}
            </div>
          );
        })}
      </div>

      {/* Main audit area */}
      <div className="audit-main">
        <div className="audit-header">
          <div className="stack">
            <h2>{formatDomainGroupLabel(activeDomain)}</h2>
            <p className="hint" style={{ margin: 0 }}>Review and confirm the semantic mappings for this business area.</p>
          </div>
        </div>

        <div className="audit-content stack" style={{ gap: '2rem' }}>
          {tablesInDomain.map(table => (
            <TableAuditCard 
              key={table.table_name} 
              table={table} 
              isConfirming={confirming === table.table_name}
              onConfirm={() => handleConfirm(table.table_name)}
            />
          ))}
        </div>
      </div>

      <style jsx>{`
        .audit-panel {
          display: grid;
          grid-template-columns: 260px 1fr;
          height: 700px;
          background: var(--bg-surface);
          border: 1px solid var(--border);
          border-radius: 12px;
          overflow: hidden;
          box-shadow: 0 8px 32px rgba(0,0,0,0.2);
        }
        .audit-sidebar {
          background: var(--bg-surface-alt);
          border-right: 1px solid var(--border);
          padding: 1.5rem 0;
          overflow-y: auto;
        }
        .audit-nav-item {
          padding: 1rem 1.5rem;
          cursor: pointer;
          display: flex;
          justify-content: space-between;
          align-items: center;
          transition: all 0.2s ease;
          border-left: 3px solid transparent;
        }
        .audit-nav-item:hover {
          background: rgba(255,255,255,0.05);
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
          padding: 1.5rem 2.5rem;
          border-bottom: 1px solid var(--border);
          background: var(--bg-surface);
        }
        .audit-content {
          padding: 2.5rem;
          overflow-y: auto;
          flex: 1;
          background: rgba(15,15,15,0.3);
        }
        .dot-success {
          width: 8px;
          height: 8px;
          border-radius: 50%;
          background: var(--success);
          box-shadow: 0 0 8px var(--success);
        }
      `}</style>
    </div>
  );
}

function TableAuditCard({ table, onConfirm, isConfirming }: { table: SemanticTable, onConfirm: () => void, isConfirming: boolean }) {
  const isConfirmed = table.attribution.source === 'confirmed_by_user';

  return (
    <div className={`card audit-card ${isConfirmed ? 'confirmed' : ''}`} style={{ padding: '2rem', border: isConfirmed ? '1px solid var(--success)' : '1px solid var(--border)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '1.5rem' }}>
        <div className="stack">
          <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
            <h3 style={{ margin: 0, fontSize: '1.25rem' }}>{table.table_name}</h3>
            <span className="pill">{table.likely_entity || 'Generic Entity'}</span>
          </div>
          <p style={{ marginTop: '0.75rem', fontSize: '1rem', color: 'var(--text-main)', maxWidth: '600px' }}>
            {table.business_meaning}
          </p>
        </div>

        <button 
          className={`btn ${isConfirmed ? 'btn-success' : 'btn-primary'}`}
          onClick={onConfirm}
          disabled={isConfirming || isConfirmed}
          style={{ padding: '0.75rem 2rem' }}
        >
          {isConfirming ? 'Confirming...' : isConfirmed ? '✓ Confirmed' : 'Confirm Accuracy'}
        </button>
      </div>

      <div className="stack" style={{ gap: '1.5rem' }}>
        <div className="grid" style={{ gridTemplateColumns: '1fr 1fr', gap: '2rem' }}>
          {/* Join Review */}
          <div className="stack">
            <span className="eyebrow">Relation Hops</span>
            <div className="stack" style={{ gap: '0.5rem', marginTop: '0.5rem' }}>
              {table.valid_joins.length > 0 ? (
                table.valid_joins.map((join, i) => (
                  <div key={i} className="audit-detail-item">
                    <span className="icon-join" />
                    <span style={{ fontSize: '0.8rem', fontFamily: 'monospace' }}>{join}</span>
                  </div>
                ))
              ) : (
                <span className="hint">No relationships detected.</span>
              )}
            </div>
          </div>

          {/* Column Review */}
          <div className="stack">
            <span className="eyebrow">Semantic Columns</span>
            <div className="stack" style={{ gap: '0.5rem', marginTop: '0.5rem' }}>
              {table.columns.slice(0, 5).map(col => (
                <div key={col.column_name} className="audit-detail-item" style={{ justifyContent: 'space-between' }}>
                  <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                    <span style={{ fontWeight: 600, fontSize: '0.8rem' }}>{col.column_name}</span>
                    <span className="hint" style={{ fontSize: '0.7rem' }}>{col.technical_type}</span>
                  </div>
                  <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>{col.business_meaning || '-'}</span>
                </div>
              ))}
              {table.columns.length > 5 && (
                <span className="hint" style={{ fontSize: '0.7rem' }}>+ {table.columns.length - 5} more columns</span>
              )}
            </div>
          </div>
        </div>
      </div>

      <style jsx>{`
        .audit-card {
          position: relative;
          transition: transform 0.2s ease, box-shadow 0.2s ease;
        }
        .audit-card:hover {
          transform: translateY(-2px);
          box-shadow: 0 12px 40px rgba(0,0,0,0.3);
        }
        .confirmed {
          background: rgba(var(--success-rgb), 0.05);
        }
        .audit-detail-item {
          background: var(--bg-surface-alt);
          padding: 0.5rem 0.75rem;
          border-radius: 6px;
          display: flex;
          gap: 0.75rem;
          align-items: center;
        }
        .icon-join {
          width: 8px;
          height: 8px;
          border-radius: 50%;
          background: var(--accent);
        }
      `}</style>
    </div>
  );
}
