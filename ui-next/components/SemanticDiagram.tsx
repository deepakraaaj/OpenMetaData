"use client";

import { useState, useMemo, useCallback } from "react";
import dynamic from "next/dynamic";
import { KnowledgeState } from "../lib/types";

// Must dynamically import because it renders canvas and relies on 'window'
const ForceGraph2D = dynamic(() => import("react-force-graph-2d"), {
  ssr: false,
  loading: () => <div className="spinner" />
});

export default function SemanticDiagram({ state }: { state: KnowledgeState }) {
  const [highlightNodes, setHighlightNodes] = useState(new Set<string>());
  const [highlightLinks, setHighlightLinks] = useState(new Set<string>());
  const [hoverNode, setHoverNode] = useState<any>(null);

  // Compute graph data
  const graphData = useMemo(() => {
    if (!state.tables) return { nodes: [], links: [] };

    const nodes: any[] = [];
    const links: any[] = [];
    
    // Track connection degree to size nodes
    const degreeCount: Record<string, number> = {};

    Object.values(state.tables).forEach(table => {
      const source = table.table_name;
      // Initialize degree
      if (degreeCount[source] === undefined) degreeCount[source] = 0;

      table.valid_joins?.forEach(join => {
        const parts = join.split("=");
        if (parts.length === 2) {
          const left = parts[0].split(".")[0];
          const right = parts[1].split(".")[0];
          if (left && right && left !== right) {
            links.push({
              source: left,
              target: right,
              id: `${left}-${right}`
            });
            degreeCount[left] = (degreeCount[left] || 0) + 1;
            degreeCount[right] = (degreeCount[right] || 0) + 1;
          }
        }
      });
    });

    Object.values(state.tables).forEach(table => {
      const name = table.table_name;
      const conf = table.confidence?.score ?? 0;
      let color = "#f38ba8"; // Red/Low
      if (conf >= 0.8) color = "#a6e3a1"; // Green/High
      else if (conf >= 0.55) color = "#f9e2af"; // Yellow/Med

      // Size based on connections, minimum 3, maximum 15
      const degree = degreeCount[name] || 0;
      const val = Math.min(Math.max(degree * 1.5, 3), 20);

      nodes.push({
        id: name,
        name: name,
        color: color,
        val: val,
        columns: table.columns.length,
        degree: degree
      });
    });

    return { nodes, links };
  }, [state.tables]);

  const handleNodeHover = useCallback((node: any) => {
    setHighlightNodes(new Set());
    setHighlightLinks(new Set());
    
    if (node) {
      const newNodes = new Set([node.id]);
      const newLinks = new Set<string>();
      
      graphData.links.forEach(l => {
        const sourceId = typeof l.source === 'object' ? l.source.id : l.source;
        const targetId = typeof l.target === 'object' ? l.target.id : l.target;
        
        if (sourceId === node.id || targetId === node.id) {
          newLinks.add(l.id);
          newNodes.add(sourceId);
          newNodes.add(targetId);
        }
      });

      setHighlightNodes(newNodes);
      setHighlightLinks(newLinks);
      setHoverNode(node);
    } else {
      setHoverNode(null);
    }
  }, [graphData]);

  // Confidence calculations for header
  const tables = Object.values(state.tables || {});
  const highConf = tables.filter(t => (t.confidence?.score ?? 0) >= 0.8).length;
  const medConf = tables.filter(t => {
    const s = t.confidence?.score ?? 0;
    return s >= 0.55 && s < 0.8;
  }).length;
  const lowConf = tables.length - highConf - medConf;

  return (
    <div className="card" style={{ padding: '0', overflow: 'hidden' }}>
      <div style={{ padding: '1rem 1.5rem', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span className="eyebrow" style={{ margin: 0 }}>Semantic Schema Brain</span>
        <div style={{ display: 'flex', gap: '1rem', fontSize: '0.75rem', color: 'var(--text-muted)' }}>
          <span><span style={{ color: 'var(--success)' }}>●</span> High confidence</span>
          <span><span style={{ color: 'var(--warning)' }}>●</span> Medium</span>
          <span><span style={{ color: 'var(--danger)' }}>●</span> Needs Review</span>
        </div>
      </div>

      <div style={{ width: '100%', height: '600px', background: '#11111b', position: 'relative' }}>
        <ForceGraph2D
          graphData={graphData}
          nodeLabel="name"
          nodeColor={node => highlightNodes.size && !highlightNodes.has(node.id as string) 
            ? 'rgba(100,100,100,0.2)' 
            : (node.color as string)}
          nodeRelSize={2.5}
          linkColor={link => highlightLinks.has((link as any).id) ? 'rgba(255,255,255,0.8)' : '#313244'}
          linkWidth={link => highlightLinks.has((link as any).id) ? 2 : 1}
          linkDirectionalParticles={4}
          linkDirectionalParticleWidth={link => highlightLinks.has((link as any).id) ? 4 : 0}
          onNodeHover={handleNodeHover}
          backgroundColor="#11111b"
          cooldownTicks={100}
        />
        
        {/* Floating tooltip for hovered node */}
        {hoverNode && (
          <div style={{
            position: 'absolute',
            bottom: '20px',
            left: '20px',
            background: 'rgba(30, 30, 46, 0.9)',
            border: '1px solid var(--border)',
            borderRadius: '8px',
            padding: '1rem',
            color: 'var(--text)',
            pointerEvents: 'none',
            backdropFilter: 'blur(4px)',
            boxShadow: '0 4px 6px rgba(0,0,0,0.3)',
            zIndex: 10
          }}>
            <div style={{ fontWeight: 600, fontSize: '1rem', marginBottom: '0.25rem' }}>{hoverNode.name}</div>
            <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
              {hoverNode.columns} columns • {hoverNode.degree} connections
            </div>
            <div style={{ fontSize: '0.75rem', marginTop: '0.5rem', color: hoverNode.color }}>
              ◎ Confidence Level
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
