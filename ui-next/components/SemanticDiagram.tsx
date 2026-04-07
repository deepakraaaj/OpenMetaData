"use client";

import { KnowledgeState } from "../lib/types";

export default function SemanticDiagram({ state }: { state: KnowledgeState }) {
  const tables = Object.values(state.tables);
  
  return (
    <div className="card shadow" style={{ minHeight: '300px', display: 'flex', flexDirection: 'column', padding: '2rem', background: 'var(--bg-deep)', border: '1px solid var(--border)' }}>
      <div className="eyebrow" style={{ marginBottom: '2rem' }}>Semantic Object Model</div>
      
      <div style={{ position: 'relative', flex: 1, display: 'flex', justifyContent: 'center', alignItems: 'center', gap: '3rem' }}>
        {tables.map((table, idx) => (
          <div 
            key={table.table_name} 
            className="card" 
            style={{ 
              width: '180px', 
              padding: '1rem', 
              textAlign: 'center', 
              background: 'var(--bg-surface)', 
              borderColor: table.confidence.label === 'high' ? 'var(--success)' : 'var(--accent)',
              zIndex: 2
            }}
          >
            <div style={{ fontSize: '0.75rem', fontWeight: 700, opacity: 0.6 }}>{table.likely_entity || 'TABLE'}</div>
            <div style={{ fontWeight: 600 }}>{table.table_name}</div>
            
            <div style={{ marginTop: '0.5rem', display: 'flex', flexWrap: 'wrap', gap: '4px', justifyContent: 'center' }}>
              {table.important_columns.slice(0, 3).map(c => (
                <span key={c} style={{ fontSize: '0.6rem', padding: '1px 4px', background: 'var(--bg-surface-alt)', borderRadius: '4px' }}>{c}</span>
              ))}
            </div>
          </div>
        ))}

        {/* Mock Relationship Line */}
        {tables.length > 1 && (
          <div style={{ 
            position: 'absolute', 
            height: '2px', 
            width: '100px', 
            background: 'linear-gradient(90deg, var(--accent), var(--border))', 
            zIndex: 1 
          }}></div>
        )}
      </div>

      <div className="hint" style={{ marginTop: '2rem', textAlign: 'center' }}>
        Relationships inferred from schema constraints and naming patterns.
      </div>
    </div>
  );
}
