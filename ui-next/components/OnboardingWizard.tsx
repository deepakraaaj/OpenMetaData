"use client";

import { useState, useEffect, useCallback } from "react";
import { initializeEngine, getEngineState, getNextQuestion, submitAnswer, openMetadataClientApiBaseUrl } from "../lib/client-api";
import { MOCK_KNOWLEDGE_STATE } from "../lib/mock-data";
import type { KnowledgeState, GeneratedQuestion } from "../lib/types";
import KnowledgePanel from "./KnowledgePanel";
import Chatbot from "./Chatbot";
import SemanticDiagram from "./SemanticDiagram";
import DomainSummary from "./DomainSummary";
import EnumReviewGrid from "./EnumReviewGrid";
import DomainAuditPanel from "./DomainAuditPanel";

type Screen = "connect" | "overview" | "workspace" | "enums" | "final";
type DataMode = "loading" | "live" | "mock";

export function OnboardingWizard({ sourceName }: { sourceName: string }) {
  const [screen, setScreen] = useState<Screen>("connect");
  const [state, setState] = useState<KnowledgeState>(MOCK_KNOWLEDGE_STATE);
  const [mode, setMode] = useState<DataMode>("loading");
  const [error, setError] = useState<string>("");
  const [question, setQuestion] = useState<GeneratedQuestion | null>(null);
  const [groups, setGroups] = useState<Record<string, string[]>>({});

  const loadGroups = useCallback(async () => {
    try {
      const { aiGroupTables } = await import("../lib/client-api");
      const g = await aiGroupTables(sourceName);
      setGroups(g.groups);
    } catch (err) {
      console.error("Domain grouping failed:", err);
    }
  }, [sourceName]);

  const loadState = useCallback(async () => {
    try {
      const { getEngineState } = await import("../lib/client-api");
      const engineState = await getEngineState(sourceName);
      setState(engineState);
      setMode("live");
      setError("");
      void loadGroups();
    } catch {
      setMode("mock");
    }
  }, [loadGroups, sourceName]);

  // Try loading existing state on mount
  useEffect(() => {
    loadState();
  }, [loadState]);

  const handleInitialize = async () => {
    setError("");
    try {
      const { initializeEngine } = await import("../lib/client-api");
      const engineState = await initializeEngine(sourceName);
      setState(engineState);
      setMode("live");
      setScreen("overview");
      void loadGroups();
    } catch (err) {
      setMode("mock");
      setScreen("overview");
      setError(err instanceof Error ? err.message : "Could not reach engine API.");
    }
  };

  const handleNextQuestion = useCallback(async () => {
    if (mode !== "live") return;
    try {
      const q = await getNextQuestion(sourceName);
      if (q.status === "complete") {
        setQuestion(null);
      } else {
        setQuestion(q);
      }
    } catch {
      setQuestion(null);
    }
  }, [mode, sourceName]);

  const handleSubmitAnswer = async (gapId: string, answer: string) => {
    if (mode !== "live") return;
    try {
      const updatedState = await submitAnswer(sourceName, gapId, answer);
      setState(updatedState);
      await handleNextQuestion();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to submit answer.");
    }
  };

  useEffect(() => {
    if (mode === "live" && screen === "workspace") {
      handleNextQuestion();
    }
  }, [mode, screen, handleNextQuestion]);

  const renderScreen = () => {
    switch (screen) {
      case "connect":
        return <ConnectScreen onNext={handleInitialize} sourceName={sourceName} mode={mode} error={error} />;
      case "overview":
        return <OverviewScreen onNext={() => setScreen("workspace")} state={state} sourceName={sourceName} mode={mode} onStateUpdate={setState} groups={groups} />;
      case "workspace":
        return (
          <div className="workspace">
            <ChatPanel
              state={state}
              question={question}
              onSubmit={handleSubmitAnswer}
              mode={mode}
              groups={groups}
            />
            <KnowledgePanel state={state} />
          </div>
        );
      case "enums":
        return <EnumReviewGrid state={state} />;
      case "final":
        return <FinalReviewScreen state={state} sourceName={sourceName} onStateUpdate={setState} groups={groups} />;
    }
  };

  return (
    <div className="frame">
      <nav style={{ padding: '1rem 2.5rem', borderBottom: '1px solid var(--border)', display: 'flex', gap: '2rem', alignItems: 'center', background: 'var(--bg-surface)' }}>
        <div style={{ fontWeight: 700, fontSize: '1.25rem', color: 'var(--accent)' }}>MD Onboarder</div>
        <div style={{ display: 'flex', gap: '1.5rem', fontSize: '0.875rem' }}>
          <NavItem active={screen === 'connect'} label="1. Connect" onClick={() => setScreen('connect')} />
          <NavItem active={screen === 'overview'} label="2. Overview" onClick={() => setScreen('overview')} />
          <NavItem active={screen === 'workspace'} label="3. Workspace" onClick={() => setScreen('workspace')} />
          <NavItem active={screen === 'enums'} label="4. Enums" onClick={() => setScreen('enums')} />
          <NavItem active={screen === 'final'} label="5. Review" onClick={() => setScreen('final')} />
        </div>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
          <span className={`pill ${mode === 'live' ? 'pill-success' : 'pill-warning'}`}>
            {mode === 'live' ? '● Live' : mode === 'loading' ? '◌ Loading...' : '○ Mock'}
          </span>
          <span className="pill">{sourceName}</span>
        </div>
      </nav>

      <div style={{ flex: 1, overflow: 'auto' }}>
        {renderScreen()}
      </div>
    </div>
  );
}

function NavItem({ active, label, onClick }: { active: boolean; label: string; onClick: () => void }) {
  return (
    <span
      onClick={onClick}
      style={{
        cursor: 'pointer',
        color: active ? 'var(--text-main)' : 'var(--text-muted)',
        fontWeight: active ? 600 : 400,
        position: 'relative',
      }}
    >
      {label}
      {active && <div style={{ position: 'absolute', bottom: '-21px', left: 0, right: 0, height: '2px', background: 'var(--accent)' }} />}
    </span>
  );
}

function ConnectScreen({ onNext, sourceName, mode, error }: { onNext: () => void; sourceName: string; mode: DataMode; error: string }) {
  return (
    <div className="hero">
      <span className="eyebrow">Semantic Onboarding</span>
      <h1>Initialize the engine for {sourceName}.</h1>
      <p>This will read the normalized schema from Phase 1 and detect all semantic gaps that need your attention.</p>

      <div className="card" style={{ maxWidth: '500px', margin: '0 auto', textAlign: 'left' }}>
        <div className="stack" style={{ gap: '1rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <div style={{ width: 10, height: 10, borderRadius: '50%', background: mode === 'live' ? 'var(--success)' : 'var(--warning)' }} />
            <span style={{ fontSize: '0.875rem', color: 'var(--text-muted)' }}>
              {mode === 'live' ? 'Engine is initialized and live.' : 'Engine API ready. Click to bootstrap.'}
            </span>
          </div>
          <button className="btn btn-primary" onClick={onNext} style={{ width: '100%' }}>
            {mode === 'live' ? 'Re-initialize Engine' : 'Initialize Onboarding Engine'}
          </button>
          {error && (
            <div style={{ padding: '0.75rem', background: 'rgba(239,68,68,0.1)', border: '1px solid var(--danger)', borderRadius: '8px', fontSize: '0.8rem', color: '#fca5a5' }}>
              {error}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function OverviewScreen({ onNext, state, sourceName, mode, onStateUpdate, groups }: { onNext: () => void; state: KnowledgeState; mode: DataMode; sourceName: string; onStateUpdate: (s: KnowledgeState) => void, groups: Record<string, string[]> }) {
  const [resolving, setResolving] = useState(false);
  const [activeTab, setActiveTab] = useState<'domains' | 'graph'>('domains');
  const [resolveResult, setResolveResult] = useState<{ resolved: number; remaining: number } | null>(null);

  const tableCount = Object.keys(state.tables).length;
  const totalCols = Object.values(state.tables).reduce((s, t) => s + t.columns.length, 0);
  const gapCount = state.unresolved_gaps.length;

  const handleAiResolve = async () => {
    setResolving(true);
    try {
      const { aiResolveGaps, getEngineState } = await import("../lib/client-api");
      const result = await aiResolveGaps(sourceName);
      setResolveResult({ resolved: result.resolved_count, remaining: result.remaining_gaps });
      // Reload state
      const fresh = await getEngineState(sourceName);
      onStateUpdate(fresh);
    } catch (err) {
      console.error("AI resolve failed:", err);
    } finally {
      setResolving(false);
    }
  };

  return (
    <div className="stack" style={{ padding: '2rem', maxWidth: '1200px', margin: '0 auto' }}>
      <div style={{ marginBottom: '1.5rem', display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end' }}>
        <div>
          <h2 style={{ marginBottom: '0.5rem' }}>
            {sourceName} — {tableCount} tables, {totalCols} columns
          </h2>
          <p className="hint" style={{ margin: 0 }}>
            {gapCount > 0
              ? `The system understood most of the schema but needs your input on ${gapCount} items.`
              : 'Everything looks good. The schema is fully understood.'}
          </p>
        </div>
        
        <div style={{ display: 'flex', background: 'var(--bg-surface)', padding: '0.25rem', borderRadius: '8px', border: '1px solid var(--border)' }}>
          <button 
            className={`btn ${activeTab === 'domains' ? 'btn-primary' : 'btn-ghost'}`} 
            style={{ padding: '0.5rem 1rem', fontSize: '0.85rem' }}
            onClick={() => setActiveTab('domains')}
          >
            Business Domains
          </button>
          <button 
            className={`btn ${activeTab === 'graph' ? 'btn-primary' : 'btn-ghost'}`} 
            style={{ padding: '0.5rem 1rem', fontSize: '0.85rem' }}
            onClick={() => setActiveTab('graph')}
          >
            Technical Brain Map
          </button>
        </div>
      </div>

      {activeTab === 'domains' ? (
        <DomainSummary state={state} groups={groups} />
      ) : (
        <SemanticDiagram state={state} />
      )}

      {/* AI resolve bar */}
      {gapCount > 0 && mode === 'live' && (
        <div className="card" style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginTop: '1.5rem', padding: '1rem 1.5rem' }}>
          <div style={{ flex: 1 }}>
            <div style={{ fontWeight: 600, fontSize: '0.9rem' }}>
              {resolveResult
                ? `✦ AI resolved ${resolveResult.resolved} items — ${resolveResult.remaining} remaining`
                : `✦ Let AI resolve the obvious ${gapCount} items`}
            </div>
            <div className="hint" style={{ fontSize: '0.75rem' }}>
              {resolveResult
                ? 'You can run it again or review the remaining items manually.'
                : 'The LLM will answer business meanings, enum labels, and relationship confirmations.'}
            </div>
          </div>
          <button
            className="btn btn-outline"
            onClick={handleAiResolve}
            disabled={resolving}
            style={{ whiteSpace: 'nowrap' }}
          >
            {resolving ? 'Resolving...' : resolveResult ? 'Run Again' : 'Auto-Resolve'}
          </button>
        </div>
      )}

      <div className="button-row" style={{ marginTop: '1.5rem', justifyContent: 'flex-end' }}>
        <button className="btn btn-primary" onClick={onNext}>
          {gapCount > 0 ? `Review ${gapCount} items →` : 'Continue →'}
        </button>
      </div>
    </div>
  );
}

function ChatPanel({
  state,
  question,
  onSubmit,
  mode,
  groups,
}: {
  state: KnowledgeState;
  question: GeneratedQuestion | null;
  onSubmit: (gapId: string, answer: string) => void;
  mode: DataMode;
  groups: Record<string, string[]>;
}) {
  const [answer, setAnswer] = useState("");

  if (mode !== "live") {
    return <Chatbot state={state} />;
  }

  if (!question) {
    return (
      <div className="card" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: '1rem', flex: 1 }}>
        <div style={{ fontSize: '3rem' }}>✅</div>
        <h3>All gaps resolved!</h3>
        <p className="hint">No more questions. You can proceed to Review.</p>
      </div>
    );
  }

  // Determine domain context
  const domain = [...Object.entries(groups)].find(([_, tables]) => tables.includes(question.target_entity || ""))?.[0];

  const handleSubmit = () => {
    if (!answer.trim()) return;
    onSubmit(question.gap_id, answer);
    setAnswer("");
  };

  return (
    <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem', flex: 1 }}>
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '0.75rem' }}>
          <span className={`pill ${question.input_type === 'boolean' ? 'pill-warning' : ''}`}>
            {question.gap_id}
          </span>
          {domain && (
            <span className="pill pill-success" style={{ textTransform: 'uppercase', fontSize: '0.7rem' }}>
              Domain: {domain}
            </span>
          )}
        </div>
        <h3 style={{ marginTop: '0.5rem' }}>{question.question}</h3>
        <p className="hint" style={{ marginTop: '0.5rem' }}>{question.context}</p>
      </div>

      {question.evidence.length > 0 && (
        <div style={{ background: 'var(--bg-surface-alt)', padding: '1rem', borderRadius: '8px', fontSize: '0.8rem' }}>
          <strong style={{ color: 'var(--text-muted)', fontSize: '0.75rem', textTransform: 'uppercase' }}>Evidence</strong>
          {question.evidence.map((e, i) => (
            <div key={i} style={{ marginTop: '0.25rem', color: 'var(--text-muted)' }}>• {e}</div>
          ))}
        </div>
      )}

      {question.input_type === 'boolean' && question.choices.length > 0 ? (
        <div style={{ display: 'flex', gap: '0.75rem' }}>
          {question.choices.map((choice) => (
            <button
              key={choice}
              className="btn btn-outline"
              style={{ flex: 1 }}
              onClick={() => onSubmit(question.gap_id, choice)}
            >
              {choice}
            </button>
          ))}
        </div>
      ) : (
        <div style={{ display: 'flex', gap: '0.75rem', marginTop: 'auto' }}>
          <input
            type="text"
            value={answer}
            onChange={(e) => setAnswer(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleSubmit()}
            placeholder={question.suggested_answer || "Type your answer..."}
            style={{ flex: 1 }}
          />
          <button className="btn btn-primary" onClick={handleSubmit}>Submit</button>
        </div>
      )}
    </div>
  );
}

function FinalReviewScreen({ state, sourceName, onStateUpdate, groups }: { state: KnowledgeState; sourceName: string; onStateUpdate: (s: KnowledgeState) => void; groups: Record<string, string[]> }) {
  return (
    <div className="stack" style={{ padding: '2rem', maxWidth: '1200px', margin: '0 auto' }}>
      <div style={{ marginBottom: '2rem' }}>
        <span className="eyebrow">Step 5 — Final Review</span>
        <h1>Manual Domain Audit</h1>
        <p className="hint">Review the AI-generated semantic mappings below. Confirm each table to reach 100% readiness for TAG deployment.</p>
      </div>

      <DomainAuditPanel 
        state={state} 
        groups={groups} 
        onStateUpdate={onStateUpdate} 
      />

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '2rem', marginTop: '3rem' }}>
        <div className="card">
          <h3>Readiness</h3>
          <div style={{ width: '100%', height: 6, background: 'var(--bg-surface-alt)', borderRadius: 3, overflow: 'hidden', margin: '1rem 0' }}>
            <div style={{ height: '100%', width: `${state.readiness.readiness_percentage}%`, background: 'var(--accent)', transition: 'width 0.5s ease' }} />
          </div>
          <h2 style={{ color: 'var(--accent)' }}>{state.readiness.readiness_percentage}% Complete</h2>
          <div className="stack" style={{ marginTop: '1rem' }}>
            {state.readiness.readiness_notes.length > 0 ? (
              state.readiness.readiness_notes.map((note: string, i: number) => (
                <p key={i} className="hint" style={{ color: 'var(--warning)', fontSize: '0.8rem' }}>⚠️ {note}</p>
              ))
            ) : (
              <p className="hint" style={{ color: 'var(--success)' }}>✓ All semantic quality checks passed.</p>
            )}
          </div>
        </div>

        <div className="card">
          <h3>Export Preview</h3>
          <div style={{ background: 'var(--bg-surface-alt)', padding: '1rem', borderRadius: '8px', fontSize: '0.8rem', fontFamily: 'monospace' }}>
            <div style={{ color: 'var(--accent)' }}>/{sourceName}/</div>
            <div>  ├── knowledge_state.json</div>
            <div>  ├── tables.json</div>
            <div style={{ fontWeight: 'bold', color: 'var(--success)' }}>  └── {sourceName}.domain.json (LLM Artifact)</div>
          </div>
          <a 
            href={`${openMetadataClientApiBaseUrl()}/api/engine/${sourceName}/export-llm-artifact`} 
            download={`${sourceName}.domain.json`}
            target="_blank"
            className="btn btn-primary" 
            style={{ marginTop: '1.5rem', width: '100%', display: 'block', textAlign: 'center', textDecoration: 'none' }}
          >
            Download LLM Context Artifact (.domain.json)
          </a>
        </div>
      </div>

      <div style={{ marginTop: '3rem', display: 'flex', justifyContent: 'center' }}>
        <button 
          className="btn btn-outline" 
          style={{ padding: '1rem 4rem', fontSize: '1.1rem' }} 
          disabled={!state.readiness.is_ready}
        >
          {state.readiness.is_ready ? '🚀 Publish to TAG Domain' : 'Complete Audit to Publish'}
        </button>
      </div>
    </div>
  );
}
