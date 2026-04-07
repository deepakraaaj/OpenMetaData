"use client";

import { useState, useMemo, useCallback, useRef, useEffect } from "react";
import dynamic from "next/dynamic";
import { KnowledgeState, SemanticTable } from "../lib/types";

// Must dynamically import because it renders canvas and relies on 'window'
const ForceGraph2D = dynamic(() => import("react-force-graph-2d"), {
  ssr: false,
  loading: () => <div className="spinner" style={{ margin: 'auto' }} />
});

export default function SemanticDiagram({ state }: { state: KnowledgeState }) {
  const fgRef = useRef<any>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [dimensions, setDimensions] = useState({ width: 0, height: 0 });
  const [highlightNodes, setHighlightNodes] = useState(new Set<string>());
  const [highlightLinks, setHighlightLinks] = useState(new Set<string>());
  const [hoverNode, setHoverNode] = useState<any>(null);
  const [selectedTable, setSelectedTable] = useState<SemanticTable | null>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);

  // Resize observer to maintain canvas size sync with flex dimensions
  useEffect(() => {
    if (!containerRef.current) return;
    const observer = new ResizeObserver(entries => {
      if (entries[0]) {
        const { width, height } = entries[0].contentRect;
        setDimensions({ width: Math.floor(width), height: Math.floor(height) });
      }
    });
    observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, []);

  // Compute graph data
  const graphData = useMemo(() => {
    if (!state.tables) return { nodes: [], links: [] };

    const nodes: any[] = [];
    const links: any[] = [];
    const degreeCount: Record<string, number> = {};

    Object.values(state.tables).forEach(table => {
      const source = table.table_name;
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

  const updateHighlights = useCallback((nodeId: string | null) => {
    const newNodes = new Set<string>();
    const newLinks = new Set<string>();

    if (nodeId) {
      newNodes.add(nodeId);
      graphData.links.forEach(l => {
        const sourceId = typeof l.source === 'object' ? l.source.id : l.source;
        const targetId = typeof l.target === 'object' ? l.target.id : l.target;
        
        if (sourceId === nodeId || targetId === nodeId) {
          newLinks.add(l.id);
          newNodes.add(sourceId);
          newNodes.add(targetId);
        }
      });
    }

    setHighlightNodes(newNodes);
    setHighlightLinks(newLinks);
  }, [graphData]);

  const handleNodeHover = useCallback((node: any) => {
    if (selectedTable) return; // Lock highlights if a node is selected
    setHoverNode(node);
    updateHighlights(node ? node.id : null);
  }, [selectedTable, updateHighlights]);

  const handleNodeClick = useCallback((node: any) => {
    const table = state.tables[node.id];
    if (table) {
      setSelectedTable(table);
      updateHighlights(node.id);
      
      // Expand and zoom into the clicked node
      if (fgRef.current) {
        fgRef.current.centerAt(node.x, node.y, 800);
        fgRef.current.zoom(4, 800); // 4x zoom, 800ms transition
      }
    }
  }, [state.tables, updateHighlights]);

  const handleBackgroundClick = useCallback(() => {
    setSelectedTable(null);
    updateHighlights(null);
    if (fgRef.current) {
      fgRef.current.zoomToFit(800, 40); // Auto zoom out to fit all nodes
    }
  }, [updateHighlights]);

  // Confidence calculations
  const tables = Object.values(state.tables || {});
  const highConf = tables.filter(t => (t.confidence?.score ?? 0) >= 0.8).length;
  const medConf = tables.filter(t => { const s = t.confidence?.score ?? 0; return s >= 0.55 && s < 0.8; }).length;
  const lowConf = tables.length - highConf - medConf;

  // Viewport classes based on fullscreen state
  const containerClass = isFullscreen 
    ? "fixed inset-0 z-50 bg-[#11111b] flex flex-col" 
    : "card p-0 overflow-hidden relative";

  const containerStyle = isFullscreen 
    ? { position: 'fixed' as const, top: 0, left: 0, right: 0, bottom: 0, zIndex: 100, display: 'flex', flexDirection: 'column' as const, background: '#11111b' }
    : { padding: '0', overflow: 'hidden', position: 'relative' as const };

  return (
    <div className={isFullscreen ? "" : "card"} style={containerStyle}>
      <div style={{ padding: '1rem 1.5rem', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: 'var(--bg-surface)' }}>
        <span className="eyebrow" style={{ margin: 0 }}>Semantic Schema Brain</span>
        <div style={{ display: 'flex', gap: '1.5rem', alignItems: 'center', fontSize: '0.75rem', color: 'var(--text-muted)' }}>
          <span><span style={{ color: 'var(--success)' }}>●</span> High confidence</span>
          <span><span style={{ color: 'var(--warning)' }}>●</span> Medium</span>
          <span><span style={{ color: 'var(--danger)' }}>●</span> Needs Review</span>
          <button 
            className="btn btn-outline" 
            style={{ padding: '0.2rem 0.5rem', fontSize: '0.7rem', height: 'auto', minHeight: 'auto' }}
            onClick={() => {
              setIsFullscreen(!isFullscreen);
              setTimeout(() => fgRef.current?.zoomToFit(400, 40), 100);
            }}
          >
            {isFullscreen ? '⤓ Collapse' : '⤢ Expand View'}
          </button>
        </div>
      </div>

      <div style={{ width: '100%', height: isFullscreen ? '100%' : '600px', background: '#11111b', position: 'relative', display: 'flex', flex: 1 }}>
        <div ref={containerRef} style={{ flex: 1, position: 'relative' }}>
          {dimensions.width > 0 && (
            <ForceGraph2D
              ref={fgRef}
              width={dimensions.width}
              height={dimensions.height}
              graphData={graphData}
              nodeRelSize={2}
              nodeVal={node => (node as any).val}
              nodeColor={node => highlightNodes.size && !highlightNodes.has(node.id as string) 
                ? 'rgba(100,100,100,0.2)' 
                : ((node as any).color as string)}
              nodeCanvasObjectMode={() => "after"}
              nodeCanvasObject={(node: any, ctx, globalScale) => {
                const isHighlight = highlightNodes.has(node.id);
                const isHovered = hoverNode && hoverNode.id === node.id;
                
                if (isHighlight || isHovered) {
                  const label = node.name;
                  const fontSize = Math.max(12 / globalScale, 4); // Scale text but keep it readable
                  const nodeSize = Math.sqrt(node.val) * 2; // Approximate visual radius
                  
                  ctx.font = `${fontSize}px Inter, sans-serif`;
                  ctx.textAlign = 'center';
                  ctx.textBaseline = 'top';
                  
                  ctx.shadowColor = '#11111b';
                  ctx.shadowBlur = 4;
                  ctx.lineWidth = 2;
                  ctx.strokeStyle = '#11111b';
                  ctx.strokeText(label, node.x, node.y + nodeSize + 2);
                  
                  ctx.shadowBlur = 0;
                  ctx.fillStyle = 'rgba(255, 255, 255, 0.9)';
                  ctx.fillText(label, node.x, node.y + nodeSize + 2);
                }
              }}
              linkColor={link => highlightLinks.has((link as any).id) ? 'rgba(255,255,255,0.8)' : '#313244'}
              linkWidth={link => highlightLinks.has((link as any).id) ? 2 : 1}
              linkDirectionalParticles={4}
              linkDirectionalParticleWidth={link => highlightLinks.has((link as any).id) ? 4 : 0}
              onNodeHover={handleNodeHover}
              onNodeClick={handleNodeClick}
              onBackgroundClick={handleBackgroundClick}
              backgroundColor="#11111b"
              cooldownTicks={100}
              enableZoomInteraction={true}
              enablePanInteraction={true}
            />
          )}
        </div>
        
        {/* Detail Panel: Makes data "meaningful" to user */}
        {selectedTable && (
          <div style={{
            width: '350px',
            background: 'var(--bg-surface)',
            borderLeft: '1px solid var(--border)',
            display: 'flex',
            flexDirection: 'column',
            overflowY: 'auto'
          }}>
            <div style={{ padding: '1.5rem', borderBottom: '1px solid var(--border)' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
                <h3 style={{ margin: 0, color: 'var(--text)', wordBreak: 'break-all' }}>{selectedTable.table_name}</h3>
                <button onClick={handleBackgroundClick} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: '1.2rem' }}>×</button>
              </div>
              <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                {selectedTable.business_meaning || "No description available."}
              </div>
              
              <div style={{ display: 'flex', gap: '0.5rem', marginTop: '1rem' }}>
                <span className="badge" style={{ background: 'var(--bg-surface-alt)', color: 'var(--text-muted)' }}>{selectedTable.columns.length} Cols</span>
                <span className="badge" style={{ background: 'var(--bg-surface-alt)', color: 'var(--text-muted)' }}>{selectedTable.valid_joins.length} Joins</span>
                <span className="badge" style={{ 
                  background: (selectedTable.confidence?.score ?? 0) >= 0.8 ? 'rgba(166, 227, 161, 0.2)' : 'rgba(243, 139, 168, 0.2)',
                  color: (selectedTable.confidence?.score ?? 0) >= 0.8 ? 'var(--success)' : 'var(--danger)'
                }}>
                  {Math.round((selectedTable.confidence?.score ?? 0) * 100)}% Conf
                </span>
              </div>
            </div>

            <div style={{ padding: '1.5rem', flex: 1 }}>
              <h4 style={{ fontSize: '0.75rem', textTransform: 'uppercase', color: 'var(--text-muted)', letterSpacing: '0.05em', marginBottom: '1rem' }}>Identified Relationships</h4>
              {selectedTable.valid_joins.length === 0 ? (
                <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', fontStyle: 'italic' }}>No joins detected.</div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                  {selectedTable.valid_joins.map((join, i) => (
                    <div key={i} style={{ fontSize: '0.75rem', padding: '0.5rem', background: 'var(--bg-surface-alt)', borderRadius: '4px', fontFamily: 'monospace', color: 'var(--accent)' }}>
                      {join}
                    </div>
                  ))}
                </div>
              )}

              <h4 style={{ fontSize: '0.75rem', textTransform: 'uppercase', color: 'var(--text-muted)', letterSpacing: '0.05em', margin: '1.5rem 0 1rem 0' }}>Schema Columns</h4>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                {selectedTable.columns.map((col: any, i) => (
                  <div key={i} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '0.8rem', paddingBottom: '0.5rem', borderBottom: '1px solid var(--border)' }}>
                    <div>
                      <span style={{ color: 'var(--text)' }}>{col.column_name}</span>
                      {col.is_primary_key && <span style={{ marginLeft: '0.5rem', color: '#f9e2af', fontSize: '0.7rem' }}>PK</span>}
                      {col.is_foreign_key && <span style={{ marginLeft: '0.5rem', color: '#89b4fa', fontSize: '0.7rem' }}>FK</span>}
                    </div>
                    <span style={{ color: 'var(--text-muted)' }}>{col.technical_type || col.logical_type}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* Floating tooltip only when NOT selected */}
        {!selectedTable && hoverNode && (
          <div style={{
            position: 'absolute', bottom: '20px', left: '20px', background: 'rgba(30, 30, 46, 0.9)',
            border: '1px solid var(--border)', borderRadius: '8px', padding: '1rem',
            pointerEvents: 'none', backdropFilter: 'blur(4px)', boxShadow: '0 4px 6px rgba(0,0,0,0.3)'
          }}>
            <div style={{ fontWeight: 600, fontSize: '1rem', color: 'white' }}>{hoverNode.name}</div>
            <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>Click to view schema details</div>
          </div>
        )}
      </div>
    </div>
  );
}
