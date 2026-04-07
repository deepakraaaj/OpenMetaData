"use client";

import { KnowledgeState, EnumMapping } from "../lib/types";

export default function EnumReviewGrid({ state }: { state: KnowledgeState }) {
  const enumEntries = Object.entries(state.enums);

  return (
    <div className="stack" style={{ gap: '2rem' }}>
      <div className="hero" style={{ padding: '2rem 0', textAlign: 'left', margin: 0 }}>
        <span className="eyebrow">Step 4 — Review Enums</span>
        <h2>Confirm the business labels for discovered status codes.</h2>
      </div>

      <div className="card-grid" style={{ padding: 0 }}>
        {enumEntries.map(([target, mappings]) => (
          <div key={target} className="card" style={{ gap: '1rem' }}>
            <div className="stack">
              <span className="pill">{target.split('.')[0]}</span>
              <h3>Column: {target.split('.')[1]}</h3>
            </div>

            <div className="stack" style={{ gap: '0.75rem' }}>
              {mappings.map((mapping) => (
                <div 
                  key={mapping.database_value} 
                  style={{ 
                    display: 'grid', 
                    gridTemplateColumns: '80px 1fr auto', 
                    alignItems: 'center', 
                    gap: '1rem',
                    padding: '0.75rem',
                    background: 'var(--bg-surface-alt)',
                    borderRadius: '8px'
                  }}
                >
                  <code style={{ fontSize: '1rem', color: 'var(--accent)' }}>{mapping.database_value}</code>
                  <input 
                    type="text" 
                    defaultValue={mapping.business_label} 
                    style={{ background: 'transparent', border: 'none', padding: 0 }}
                  />
                  <span className={`pill ${mapping.attribution.source === 'inferred_by_system' ? 'pill-warning' : 'pill-success'}`}>
                    {mapping.attribution.source === 'inferred_by_system' ? 'Inferred' : 'Confirmed'}
                  </span>
                </div>
              ))}
            </div>
            
            <div className="button-row" style={{ marginTop: 'auto' }}>
              <button className="btn btn-outline" style={{ flex: 1 }}>Confirm All</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
