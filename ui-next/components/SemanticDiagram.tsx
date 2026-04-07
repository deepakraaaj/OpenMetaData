"use client";

import { useEffect, useRef, useState } from "react";
import mermaid from "mermaid";
import { KnowledgeState } from "../lib/types";

export default function SemanticDiagram({ state }: { state: KnowledgeState }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [rendered, setRendered] = useState(false);

  useEffect(() => {
    mermaid.initialize({
      startOnLoad: false,
      theme: 'dark',
      themeVariables: {
        darkMode: true,
        primaryColor: '#1e1e2e',
        primaryBorderColor: '#313244',
        lineColor: '#585b70',
        textColor: '#cdd6f4',
        fontSize: '14px',
        fontFamily: 'Inter, sans-serif'
      },
      flowchart: {
        curve: 'basis',
        nodeSpacing: 50,
        rankSpacing: 50,
      }
    });
  }, []);

  useEffect(() => {
    if (!containerRef.current || !state.tables) return;

    // Build graph of top tables (to avoid complete mess)
    const tables = Object.values(state.tables);
    // Find tables with the most connections to act as the core visible graph
    const connectionCounts: Record<string, number> = {};
    const edges: Array<[string, string, string]> = []; // from, to, label

    for (const table of tables) {
      for (const join of table.valid_joins || []) {
        const parts = join.split("=");
        if (parts.length === 2) {
          const left = parts[0].split(".")[0];
          const right = parts[1].split(".")[0];
          if (left && right && left !== right) {
            connectionCounts[left] = (connectionCounts[left] || 0) + 1;
            connectionCounts[right] = (connectionCounts[right] || 0) + 1;
            edges.push([left, right, ""]);
          }
        }
      }
    }

    // Take top 25 most connected tables
    const topTables = Object.entries(connectionCounts)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 25)
      .map(entry => entry[0]);

    // Only keep edges between top tables
    const visibleEdges = edges.filter(e => topTables.includes(e[0]) && topTables.includes(e[1]));

    let graphDefinition = "graph LR\n";

    // Define nodes
    for (const t of topTables) {
      const dbTable = state.tables[t];
      if (!dbTable) continue;
      const conf = dbTable.confidence?.score ?? 0;
      let styleClass = "classDef default fill:#11111b,stroke:#313244,color:#a6adc8,stroke-width:1px;";
      let style = "default";

      if (conf >= 0.8) {
        style = "high";
        graphDefinition += `classDef high fill:#11111b,stroke:#a6e3a1,color:#cdd6f4,stroke-width:2px;\n`;
      } else if (conf >= 0.55) {
        style = "med";
        graphDefinition += `classDef med fill:#11111b,stroke:#f9e2af,color:#cdd6f4,stroke-width:2px;\n`;
      } else {
        style = "low";
        graphDefinition += `classDef low fill:#11111b,stroke:#f38ba8,color:#cdd6f4,stroke-width:2px;\n`;
      }

      graphDefinition += `${t}["${t}"]:::${style}\n`;
    }

    // Define edges
    const addedEdges = new Set<string>();
    for (const [from, to] of visibleEdges) {
      const edgeKey = [from, to].sort().join("-");
      if (!addedEdges.has(edgeKey)) {
        graphDefinition += `${from} --- ${to}\n`;
        addedEdges.add(edgeKey);
      }
    }

    // Render
    containerRef.current.innerHTML = "";
    mermaid.render("mermaid-erd", graphDefinition).then(({ svg }) => {
      if (containerRef.current) {
        containerRef.current.innerHTML = svg;
        setRendered(true);
      }
    }).catch(err => {
      console.error("Mermaid render error:", err);
      if (containerRef.current) {
        containerRef.current.innerHTML = `<div style="padding: 2rem; color: var(--danger)">Diagram render failed. Too many nodes.</div>`;
      }
    });

  }, [state]);

  return (
    <div className="card" style={{ padding: '0', overflow: 'hidden' }}>
      <div style={{ padding: '1rem 1.5rem', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between' }}>
        <span className="eyebrow" style={{ margin: 0 }}>Core Entity Relationships (Top 25)</span>
        <div style={{ display: 'flex', gap: '1rem', fontSize: '0.75rem', color: 'var(--text-muted)' }}>
          <span><span style={{ color: 'var(--success)' }}>■</span> High confidence</span>
          <span><span style={{ color: 'var(--warning)' }}>■</span> Medium</span>
          <span><span style={{ color: 'var(--danger)' }}>■</span> Low — Needs Review</span>
        </div>
      </div>
      <div
        ref={containerRef}
        style={{
          width: '100%',
          minHeight: '400px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          background: 'var(--bg-surface-alt)',
          padding: '2rem',
          opacity: rendered ? 1 : 0,
          transition: 'opacity 0.3s ease'
        }}
      >
        {!rendered && <div className="spinner" />}
      </div>
    </div>
  );
}
