"use client";

import { useState, useEffect, useCallback } from "react";
import { initializeEngine, getEngineState, getNextQuestion, submitAnswer } from "../lib/client-api";
import { MOCK_KNOWLEDGE_STATE } from "../lib/mock-data";
import type { KnowledgeState, GeneratedQuestion } from "../lib/types";
import KnowledgePanel from "./KnowledgePanel";
import Chatbot from "./Chatbot";
import SemanticDiagram from "./SemanticDiagram";
import EnumReviewGrid from "./EnumReviewGrid";

type Screen = "connect" | "overview" | "workspace" | "enums" | "final";
type DataMode = "loading" | "live" | "mock";

export function OnboardingWizard({ sourceName }: { sourceName: string }) {
  const [screen, setScreen] = useState<Screen>("connect");
  const [state, setState] = useState<KnowledgeState>(MOCK_KNOWLEDGE_STATE);
  const [mode, setMode] = useState<DataMode>("loading");
  const [error, setError] = useState<string>("");
  const [question, setQuestion] = useState<GeneratedQuestion | null>(null);

  const loadState = useCallback(async () => {
    try {
      const engineState = await getEngineState(sourceName);
      setState(engineState);
      setMode("live");
      setError("");
    } catch {
      // Engine not initialized yet — will initialize on "connect"
      setMode("mock");
    }
  }, [sourceName]);

  // Try loading existing state on mount
  useEffect(() => {
    loadState();
  }, [loadState]);

  const handleInitialize = async () => {
    setError("");
    try {
      const engineState = await initializeEngine(sourceName);
      setState(engineState);
      setMode("live");
      setScreen("overview");
    } catch (err) {
      // Backend not running — fall through to mock
      setMode("mock");
      setScreen("overview");
      setError(err instanceof Error ? err.message : "Could not reach engine API. Running in mock mode.");
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
        return <OverviewScreen onNext={() => setScreen("workspace")} state={state} sourceName={sourceName} mode={mode} />;
      case "workspace":
        return (
          <div className="workspace">
            <ChatPanel
              state={state}
              question={question}
              onSubmit={handleSubmitAnswer}
              mode={mode}
            />
            <KnowledgePanel state={state} />
          </div>
        );
      case "enums":
        return <EnumReviewGrid state={state} />;
      case "final":
        return <FinalReviewScreen state={state} sourceName={sourceName} />;
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

function OverviewScreen({ onNext, state, sourceName, mode }: { onNext: () => void; state: KnowledgeState; mode: DataMode; sourceName: string }) {
  const tableCount = Object.keys(state.tables).length;
  const totalCols = Object.values(state.tables).reduce((s, t) => s + t.columns.length, 0);
  const gapCount = state.unresolved_gaps.length;

  return (
    <div className="stack" style={{ padding: '2rem', maxWidth: '1000px', margin: '0 auto' }}>
      <div style={{ marginBottom: '1.5rem' }}>
        <h2 style={{ marginBottom: '0.5rem' }}>
          {sourceName} — {tableCount} tables, {totalCols} columns
        </h2>
        <p className="hint">
          {gapCount > 0
            ? `The system understood most of the schema but needs your input on ${gapCount} items.`
            : 'Everything looks good. The schema is fully understood.'}
        </p>
      </div>

      <SemanticDiagram state={state} />

      <div className="button-row" style={{ marginTop: '2rem', justifyContent: 'flex-end' }}>
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
}: {
  state: KnowledgeState;
  question: GeneratedQuestion | null;
  onSubmit: (gapId: string, answer: string) => void;
  mode: DataMode;
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

  const handleSubmit = () => {
    if (!answer.trim()) return;
    onSubmit(question.gap_id, answer);
    setAnswer("");
  };

  return (
    <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem', flex: 1 }}>
      <div>
        <span className={`pill ${question.input_type === 'boolean' ? 'pill-warning' : ''}`} style={{ marginBottom: '0.75rem', display: 'inline-block' }}>
          {question.gap_id}
        </span>
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

function FinalReviewScreen({ state, sourceName }: { state: KnowledgeState; sourceName: string }) {
  return (
    <div className="hero" style={{ textAlign: 'left', maxWidth: '1000px' }}>
      <span className="eyebrow">Step 5 — Final Review</span>
      <h1>Review and Export Bundle.</h1>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '2rem', marginTop: '2rem' }}>
        <div className="card">
          <h3>Readiness</h3>
          <div style={{ width: '100%', height: 6, background: 'var(--bg-surface-alt)', borderRadius: 3, overflow: 'hidden', margin: '1rem 0' }}>
            <div style={{ height: '100%', width: `${state.readiness.readiness_percentage}%`, background: 'var(--accent)', transition: 'width 0.5s ease' }} />
          </div>
          <h2 style={{ color: 'var(--accent)' }}>{state.readiness.readiness_percentage}% Complete</h2>
          <div className="stack" style={{ marginTop: '1rem' }}>
            {state.readiness.readiness_notes.map((note: string, i: number) => (
              <p key={i} className="hint" style={{ color: 'var(--warning)' }}>⚠️ {note}</p>
            ))}
          </div>
        </div>

        <div className="card">
          <h3>Export Preview</h3>
          <div style={{ background: 'var(--bg-surface-alt)', padding: '1rem', borderRadius: '8px', fontSize: '0.8rem', fontFamily: 'monospace' }}>
            <div style={{ color: 'var(--accent)' }}>/{sourceName}/</div>
            <div>  ├── knowledge_state.json</div>
            <div>  ├── tables.json</div>
            <div>  ├── enums.json</div>
            <div>  └── readiness.json</div>
          </div>
          <a href={`/api/sources/${sourceName}/json-zip`} className="btn btn-outline" style={{ marginTop: '1rem', width: '100%', display: 'block', textAlign: 'center', textDecoration: 'none' }}>
            Download ZIP
          </a>
        </div>
      </div>

      <button className="btn btn-primary" style={{ marginTop: '2rem', padding: '1rem 3rem' }} disabled={!state.readiness.is_ready}>
        Publish to TAG Domain
      </button>
    </div>
  );
}
