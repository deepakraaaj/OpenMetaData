"use client";

import { useState, useEffect, useCallback } from "react";
import {
  initializeEngine,
  getEngineState,
  getNextQuestion,
  setReviewMode,
  submitAnswer,
  publishSemanticBundle,
  validateBusinessQuestion,
  openMetadataClientApiBaseUrl,
} from "../lib/client-api";
import { MOCK_KNOWLEDGE_STATE } from "../lib/mock-data";
import type { KnowledgeState, GeneratedQuestion, ReviewMode, SqlValidationResponse } from "../lib/types";
import KnowledgePanel from "./KnowledgePanel";
import SemanticDiagram from "./SemanticDiagram";
import DomainSummary from "./DomainSummary";
import EnumReviewGrid from "./EnumReviewGrid";
import DomainAuditPanel from "./DomainAuditPanel";
import ArtifactExplorer from "./ArtifactExplorer";

type Screen = "connect" | "overview" | "workspace" | "enums" | "final";
type DataMode = "loading" | "live" | "setup" | "mock";

export function OnboardingWizard({ sourceName }: { sourceName: string }) {
  const [screen, setScreen] = useState<Screen>("connect");
  const [state, setState] = useState<KnowledgeState>(MOCK_KNOWLEDGE_STATE);
  const [mode, setMode] = useState<DataMode>("loading");
  const [error, setError] = useState<string>("");
  const [question, setQuestion] = useState<GeneratedQuestion | null>(null);
  const [groups, setGroups] = useState<Record<string, string[]>>({});
  const [isPreparingWorkspace, setIsPreparingWorkspace] = useState(false);
  const [changingReviewMode, setChangingReviewMode] = useState(false);

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
      const engineState = await getEngineState(sourceName);
      setState(engineState);
      setMode("live");
      setError("");
      setScreen((current) => (current === "connect" ? "overview" : current));
      void loadGroups();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Could not load onboarding workspace.";
      if (message.includes("No engine state")) {
        setMode("setup");
        setError("");
        return;
      }
      setMode("mock");
      setError(message);
    }
  }, [loadGroups, sourceName]);

  // Try loading existing state on mount
  useEffect(() => {
    loadState();
  }, [loadState]);

  const handleInitialize = async () => {
    setError("");
    setIsPreparingWorkspace(true);
    try {
      const engineState = await initializeEngine(sourceName);
      setState(engineState);
      setMode("live");
      setScreen("overview");
      void loadGroups();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not reach engine API.");
    } finally {
      setIsPreparingWorkspace(false);
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
        return <ConnectScreen onNext={handleInitialize} sourceName={sourceName} mode={mode} error={error} busy={isPreparingWorkspace} />;
      case "overview":
        return (
          <OverviewScreen
            onContinue={() => setScreen("final")}
            onReviewNow={() => setScreen("workspace")}
            state={state}
            sourceName={sourceName}
            mode={mode}
            onStateUpdate={setState}
            groups={groups}
            onReviewModeChange={async (reviewMode) => {
              setChangingReviewMode(true);
              try {
                const updated = await setReviewMode(sourceName, reviewMode);
                setState(updated);
                void loadGroups();
              } catch (err) {
                setError(err instanceof Error ? err.message : "Failed to change review mode.");
              } finally {
                setChangingReviewMode(false);
              }
            }}
            changingReviewMode={changingReviewMode}
          />
        );
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
          <NavItem active={screen === 'workspace'} label="3. Review Queue" onClick={() => setScreen('workspace')} />
          <NavItem active={screen === 'enums'} label="4. Enums" onClick={() => setScreen('enums')} />
          <NavItem active={screen === 'final'} label="5. Publish" onClick={() => setScreen('final')} />
        </div>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
          <span className={`pill ${mode === 'live' ? 'pill-success' : mode === 'mock' ? 'pill-danger' : 'pill-warning'}`}>
            {mode === 'live'
              ? '● Live'
              : mode === 'loading'
                ? '◌ Loading...'
                : mode === 'setup'
                  ? '◌ Setup Required'
                  : '○ Mock'}
          </span>
          <span className="pill">{sourceName}</span>
          <span className="pill pill-success">{state.review_mode.replaceAll("_", " ")}</span>
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

function ConnectScreen({ onNext, sourceName, mode, error, busy }: { onNext: () => void; sourceName: string; mode: DataMode; error: string; busy: boolean }) {
  const message =
    mode === "live"
      ? "A cached review workspace and generated artifacts are already available."
      : mode === "loading"
        ? "Checking whether a cached review workspace already exists."
        : mode === "setup"
          ? "Semantic metadata is ready. Click to refresh the review workspace and regenerate the publish artifacts."
          : "The engine API could not be reached. You can retry once connectivity is restored.";

  const buttonLabel =
    mode === "live"
      ? "Refresh Review Workspace"
      : busy
        ? "Preparing Review Workspace..."
        : "Prepare Review Workspace";

  return (
    <div className="hero">
      <span className="eyebrow">Semantic Onboarding</span>
      <h1>Prepare the review workspace for {sourceName}.</h1>
      <p>This step loads the cached semantic model, refreshes the review state, and regenerates the publishable artifacts from the current answers.</p>

      <div className="card" style={{ maxWidth: '500px', margin: '0 auto', textAlign: 'left' }}>
        <div className="stack" style={{ gap: '1rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <div style={{ width: 10, height: 10, borderRadius: '50%', background: mode === 'live' ? 'var(--success)' : mode === 'mock' ? 'var(--danger)' : 'var(--warning)' }} />
            <span style={{ fontSize: '0.875rem', color: 'var(--text-muted)' }}>
              {message}
            </span>
          </div>
          <button className="btn btn-primary" onClick={onNext} style={{ width: '100%' }} disabled={busy || mode === 'loading'}>
            {buttonLabel}
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

function OverviewScreen({
  onContinue,
  onReviewNow,
  state,
  sourceName,
  mode,
  onStateUpdate,
  groups,
  onReviewModeChange,
  changingReviewMode,
}: {
  onContinue: () => void;
  onReviewNow: () => void;
  state: KnowledgeState;
  mode: DataMode;
  sourceName: string;
  onStateUpdate: (s: KnowledgeState) => void;
  groups: Record<string, string[]>;
  onReviewModeChange: (mode: ReviewMode) => Promise<void>;
  changingReviewMode: boolean;
}) {
  const [preparingReview, setPreparingReview] = useState(false);
  const [prepareError, setPrepareError] = useState("");
  const [activeTab, setActiveTab] = useState<'domains' | 'graph'>('domains');

  const tableCount = Object.keys(state.tables).length;
  const totalCols = Object.values(state.tables).reduce((s, t) => s + t.columns.length, 0);
  const groupedCount = state.domain_groups.length > 0 ? state.domain_groups.length : Object.keys(groups).length;
  const reviewDebtCount = state.review_debt.length;
  const publishBlockers = state.readiness.publish_blockers_count;
  const guidedReviewCount = state.unresolved_gaps.length;

  const handlePrepare = async () => {
    if (mode !== "live") {
      onContinue();
      return;
    }
    setPrepareError("");
    setPreparingReview(true);
    try {
      const refreshedState = await initializeEngine(sourceName);
      onStateUpdate(refreshedState);
    } catch (err) {
      setPrepareError(err instanceof Error ? err.message : "Failed to prepare the review workspace.");
      setPreparingReview(false);
      return;
    } finally {
      setPreparingReview(false);
    }
    onContinue();
  };

  return (
    <div className="stack" style={{ padding: '2rem', maxWidth: '1200px', margin: '0 auto' }}>
      <div style={{ marginBottom: '1.5rem', display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', gap: '1rem', flexWrap: 'wrap' }}>
        <div>
          <h2 style={{ marginBottom: '0.5rem' }}>
            {sourceName} — {tableCount} tables, {totalCols} columns
          </h2>
          <p className="hint" style={{ margin: 0, maxWidth: '60rem' }}>
            Let AI decide what it safely can, continue onboarding immediately, and come back later only for the items that actually matter.
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

      <div className="card" style={{ display: 'grid', gap: '1rem', padding: '1.25rem 1.5rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem', flexWrap: 'wrap' }}>
          <div className="stack" style={{ gap: '0.4rem' }}>
            <span className="eyebrow">Review Mode</span>
            <p className="hint" style={{ margin: 0 }}>
              Guided review is the default. You can switch modes now or later and the review debt and blockers will recompute.
            </p>
          </div>
          <span className="pill pill-success">{state.review_mode.replaceAll("_", " ")}</span>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '0.85rem' }}>
          <ModeCard
            active={state.review_mode === "full_ai"}
            title="Let AI Decide And Continue"
            description="AI auto-applies everything it safely can and leaves only high-risk publish checks behind."
            onClick={() => onReviewModeChange("full_ai")}
            disabled={changingReviewMode}
          />
          <ModeCard
            active={state.review_mode === "guided"}
            title="Review High-Impact Items"
            description="AI resolves low-risk items and queues only medium-confidence or high-impact decisions."
            onClick={() => onReviewModeChange("guided")}
            disabled={changingReviewMode}
          />
          <ModeCard
            active={state.review_mode === "deep_review"}
            title="Deep Review"
            description="Keep more decisions visible for manual inspection when the schema is especially sensitive."
            onClick={() => onReviewModeChange("deep_review")}
            disabled={changingReviewMode}
          />
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '1rem' }}>
        <SummaryCard label="AI Selected" value={state.review_summary.selected_count} tone="success" />
        <SummaryCard label="AI Excluded" value={state.review_summary.excluded_count} />
        <SummaryCard label="Domains" value={groupedCount} />
        <SummaryCard label="Review Later" value={reviewDebtCount} tone="warning" />
        <SummaryCard label="Publish Blockers" value={publishBlockers} tone="warning" />
      </div>

      <div className="card" style={{ display: 'grid', gap: '0.6rem', padding: '1.15rem 1.3rem' }}>
        <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
          <span className="pill pill-success">Continue Ready: {state.readiness.continue_ready ? "Yes" : "No"}</span>
          <span className={`pill ${state.readiness.publish_ready ? 'pill-success' : 'pill-warning'}`}>
            Publish Ready: {state.readiness.publish_ready ? "Yes" : "No"}
          </span>
          <span className="pill">{guidedReviewCount} active review item(s)</span>
        </div>
        {state.readiness.continue_notes.concat(state.readiness.publish_notes).slice(0, 3).map((note) => (
          <p key={note} className="hint" style={{ margin: 0 }}>
            {note}
          </p>
        ))}
      </div>

      {activeTab === 'domains' ? (
        <DomainSummary state={state} groups={groups} />
      ) : (
        <SemanticDiagram state={state} />
      )}

      <div className="button-row" style={{ marginTop: '1.5rem', justifyContent: 'space-between', gap: '0.75rem', flexWrap: 'wrap' }}>
        <button className="btn btn-outline" onClick={onReviewNow}>
          {guidedReviewCount > 0 ? `Review ${guidedReviewCount} Item(s) Now` : 'Open Review Queue'}
        </button>
        <button className="btn btn-primary" onClick={handlePrepare} disabled={preparingReview || changingReviewMode}>
          {preparingReview ? 'Preparing Review Workspace...' : 'Continue With AI Decisions →'}
        </button>
      </div>
      <p className="hint" style={{ marginTop: '-0.5rem', textAlign: 'right' }}>
        Artifacts regenerate for the selected review mode when you continue from this screen.
      </p>
      {prepareError ? (
        <div style={{ padding: '0.75rem', background: 'rgba(239,68,68,0.1)', border: '1px solid var(--danger)', borderRadius: '8px', fontSize: '0.8rem', color: '#fca5a5' }}>
          {prepareError}
        </div>
      ) : null}
    </div>
  );
}

function ModeCard({
  active,
  title,
  description,
  onClick,
  disabled,
}: {
  active: boolean;
  title: string;
  description: string;
  onClick: () => void;
  disabled: boolean;
}) {
  return (
    <button
      type="button"
      className="card"
      onClick={onClick}
      disabled={disabled}
      style={{
        textAlign: 'left',
        padding: '1rem 1.1rem',
        border: active ? '1px solid var(--accent)' : '1px solid var(--border)',
        background: active ? 'rgba(var(--accent-rgb), 0.08)' : 'var(--bg-surface)',
        cursor: disabled ? 'not-allowed' : 'pointer',
        opacity: disabled ? 0.7 : 1,
      }}
    >
      <strong style={{ display: 'block', marginBottom: '0.35rem' }}>{title}</strong>
      <span className="hint" style={{ fontSize: '0.8rem' }}>{description}</span>
    </button>
  );
}

function SummaryCard({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone?: "success" | "warning";
}) {
  const accent =
    tone === "success" ? "var(--success)" : tone === "warning" ? "var(--warning)" : "var(--accent)";
  return (
    <div className="card" style={{ padding: "1.1rem 1.2rem" }}>
      <div className="hint" style={{ fontSize: "0.8rem", marginBottom: "0.45rem" }}>
        {label}
      </div>
      <div style={{ fontSize: "2rem", fontWeight: 700, color: accent }}>{value}</div>
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
  const [showAlternatives, setShowAlternatives] = useState(false);
  const [showFreeText, setShowFreeText] = useState(false);

  useEffect(() => {
    setAnswer("");
    setShowAlternatives(false);
    setShowFreeText(false);
  }, [question?.gap_id]);

  if (mode !== "live") {
    return <WorkspaceUnavailablePanel mode={mode} />;
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
  const alternativeOptions = (question.candidate_options || []).filter((option) => !option.is_best_guess);
  const canConfirm = Boolean(question.best_guess || question.suggested_answer);
  const shouldShowTextInput =
    showFreeText ||
    (showAlternatives && question.allow_free_text) ||
    !question.candidate_options?.length ||
    question.input_type === "text" ||
    question.input_type === "tags";

  const handleSubmit = () => {
    if (!answer.trim()) return;
    onSubmit(question.gap_id, answer);
    setAnswer("");
    setShowFreeText(false);
    setShowAlternatives(false);
  };

  const handleConfirm = () => {
    onSubmit(question.gap_id, "__confirm__");
  };

  const handleSkip = () => {
    onSubmit(question.gap_id, "__skip__");
  };

  const handleOption = (value: string) => {
    if (value === "__other__") {
      setShowAlternatives(true);
      setShowFreeText(true);
      return;
    }
    onSubmit(question.gap_id, value);
  };

  return (
    <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem', flex: 1 }}>
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '0.75rem' }}>
          <span className={`pill ${question.input_type === 'boolean' ? 'pill-warning' : ''}`}>
            {question.gap_id}
          </span>
          <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
            {question.confidence !== undefined && question.confidence !== null ? (
              <span className="pill" style={{ fontSize: '0.7rem' }}>
                {Math.round(question.confidence * 100)}% confidence
              </span>
            ) : null}
            {question.question_type ? (
              <span className="pill pill-warning" style={{ textTransform: 'uppercase', fontSize: '0.7rem' }}>
                {question.question_type.replaceAll("_", " ")}
              </span>
            ) : null}
            {domain && (
              <span className="pill pill-success" style={{ textTransform: 'uppercase', fontSize: '0.7rem' }}>
                Domain: {domain}
              </span>
            )}
          </div>
        </div>
        <h3 style={{ marginTop: '0.5rem' }}>{question.decision_prompt || question.question}</h3>
        <p className="hint" style={{ marginTop: '0.5rem' }}>{question.context}</p>
      </div>

      {question.best_guess ? (
        <div style={{ background: 'rgba(16,185,129,0.08)', border: '1px solid rgba(16,185,129,0.25)', padding: '1rem', borderRadius: '8px' }}>
          <strong style={{ color: 'var(--text-muted)', fontSize: '0.75rem', textTransform: 'uppercase' }}>System Belief</strong>
          <div style={{ marginTop: '0.4rem', fontSize: '1rem' }}>{question.best_guess}</div>
        </div>
      ) : null}

      {question.evidence.length > 0 && (
        <div style={{ background: 'var(--bg-surface-alt)', padding: '1rem', borderRadius: '8px', fontSize: '0.8rem' }}>
          <strong style={{ color: 'var(--text-muted)', fontSize: '0.75rem', textTransform: 'uppercase' }}>Evidence</strong>
          {question.evidence.map((e, i) => (
            <div key={i} style={{ marginTop: '0.25rem', color: 'var(--text-muted)' }}>• {e}</div>
          ))}
        </div>
      )}

      <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
        {canConfirm ? (
          <button className="btn btn-primary" onClick={handleConfirm}>
            Use AI Suggestion
          </button>
        ) : null}
        <button
          className="btn btn-outline"
          onClick={() => {
            setShowAlternatives((value) => !value);
            if (!question.candidate_options?.length) {
              setShowFreeText(true);
            }
          }}
        >
          Change
        </button>
        <button className="btn btn-outline" onClick={handleSkip}>
          Skip
        </button>
      </div>

      {showAlternatives && alternativeOptions.length > 0 ? (
        <div style={{ display: 'grid', gap: '0.75rem' }}>
          {alternativeOptions.map((option) => (
            <button
              key={option.value}
              className="btn btn-outline"
              style={{ justifyContent: 'flex-start', textAlign: 'left', padding: '0.9rem 1rem' }}
              onClick={() => handleOption(option.value)}
            >
              <div style={{ display: 'grid', gap: '0.25rem' }}>
                <strong>{option.label}</strong>
                {option.description ? (
                  <span className="hint" style={{ fontSize: '0.8rem' }}>{option.description}</span>
                ) : null}
              </div>
            </button>
          ))}
        </div>
      ) : null}

      {shouldShowTextInput ? (
        <div style={{ display: 'flex', gap: '0.75rem', marginTop: 'auto' }}>
          <input
            type="text"
            value={answer}
            onChange={(e) => setAnswer(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleSubmit()}
            placeholder={question.free_text_placeholder || question.suggested_answer || "Type your answer..."}
            style={{ flex: 1 }}
          />
          <button className="btn btn-primary" onClick={handleSubmit}>Submit</button>
        </div>
      ) : null}
    </div>
  );
}

function FinalReviewScreen({ state, sourceName, onStateUpdate, groups }: { state: KnowledgeState; sourceName: string; onStateUpdate: (s: KnowledgeState) => void; groups: Record<string, string[]> }) {
  const skippedTables = Object.values(state.tables).filter((table) => table.review_status === "skipped").length;
  const publishBlockers = state.readiness.publish_blockers_count;
  const [domainName, setDomainName] = useState(sourceName);
  const [publishing, setPublishing] = useState(false);
  const [publishMessage, setPublishMessage] = useState("");
  const [publishError, setPublishError] = useState("");

  const handlePublish = async () => {
    setPublishing(true);
    setPublishError("");
    setPublishMessage("");
    try {
      const response = await publishSemanticBundle(sourceName, domainName.trim() || undefined);
      setPublishMessage(`Published to ${response.published_to}`);
      setDomainName(response.domain_name || domainName);
    } catch (err) {
      setPublishError(err instanceof Error ? err.message : "Publish failed.");
    } finally {
      setPublishing(false);
    }
  };

  return (
    <div className="stack" style={{ padding: '2rem', maxWidth: '1200px', margin: '0 auto' }}>
      <div style={{ marginBottom: '2rem' }}>
        <span className="eyebrow">Step 5 — Publish Readiness</span>
        <h1>AI-Decided Scope And Review Debt</h1>
        <p className="hint">
          Continue onboarding with AI-decided defaults now, then clear only the warnings and blockers before publish.
        </p>
      </div>

      <DomainAuditPanel 
        state={state} 
        groups={groups} 
        onStateUpdate={onStateUpdate} 
      />

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: '2rem', marginTop: '3rem' }}>
        <div className="card">
          <h3>Readiness</h3>
          <div style={{ width: '100%', height: 6, background: 'var(--bg-surface-alt)', borderRadius: 3, overflow: 'hidden', margin: '1rem 0' }}>
            <div style={{ height: '100%', width: `${state.readiness.readiness_percentage}%`, background: 'var(--accent)', transition: 'width 0.5s ease' }} />
          </div>
          <h2 style={{ color: 'var(--accent)' }}>{state.readiness.readiness_percentage}% Complete</h2>
          <p className="hint" style={{ marginTop: '0.75rem' }}>
            {skippedTables > 0
              ? `${skippedTables} table(s) have already been removed from the manual review scope.`
              : 'No tables have been removed from scope yet.'}
          </p>
          <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', marginTop: '1rem' }}>
            <span className={`pill ${state.readiness.continue_ready ? 'pill-success' : 'pill-warning'}`}>
              Continue {state.readiness.continue_ready ? 'Ready' : 'Blocked'}
            </span>
            <span className={`pill ${state.readiness.publish_ready ? 'pill-success' : 'pill-warning'}`}>
              Publish {state.readiness.publish_ready ? 'Ready' : 'Blocked'}
            </span>
            <span className="pill pill-warning">{state.review_debt.length} review later</span>
            <span className="pill pill-warning">{publishBlockers} publish blocker(s)</span>
          </div>
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
          <h3>Built Outputs</h3>
          <p className="hint">
            The wizard now exposes the real generated package instead of a mock preview. Open the
            package overview, inspect each file, or download the complete zip.
          </p>
          <div style={{ display: 'grid', gap: '0.9rem', marginTop: '1rem' }}>
            <a
              href={`${openMetadataClientApiBaseUrl()}/chatbot/${sourceName}`}
              target="_blank"
              rel="noreferrer"
              className="btn btn-primary"
              style={{ width: '100%', textAlign: 'center', textDecoration: 'none' }}
            >
              Open Chatbot Package Overview
            </a>
            <a
              href={`${openMetadataClientApiBaseUrl()}/api/sources/${sourceName}/chatbot-package/zip`}
              target="_blank"
              rel="noreferrer"
              className="btn btn-outline"
              style={{ width: '100%', textAlign: 'center', textDecoration: 'none' }}
            >
              Download Chatbot Package Zip
            </a>
            <a
              href={`${openMetadataClientApiBaseUrl()}/api/engine/${sourceName}/export-llm-artifact`}
              download={`${sourceName}.domain.json`}
              target="_blank"
              rel="noreferrer"
              className="btn btn-outline"
              style={{ width: '100%', textAlign: 'center', textDecoration: 'none' }}
            >
              Download LLM Context Artifact
            </a>
          </div>
        </div>
      </div>

      <ArtifactExplorer sourceName={sourceName} />

      <ValidationWorkbench state={state} sourceName={sourceName} />

      <div className="card" style={{ marginTop: '2rem' }}>
        <div style={{ display: 'grid', gap: '1rem' }}>
          <div>
            <h3>Publish</h3>
            <p className="hint">
              Publish now copies the real generated semantic bundle into the TAG domain folder only after the workspace artifacts are regenerated successfully.
            </p>
          </div>
          <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap', alignItems: 'center' }}>
            <input
              type="text"
              value={domainName}
              onChange={(event) => setDomainName(event.target.value)}
              placeholder="Target domain name"
              style={{ minWidth: '280px', flex: '1 1 280px' }}
            />
            <button
              className="btn btn-primary"
              style={{ padding: '1rem 2rem', fontSize: '1rem' }}
              disabled={!state.readiness.publish_ready || publishing}
              onClick={handlePublish}
            >
              {publishing
                ? 'Publishing...'
                : state.readiness.publish_ready
                  ? 'Publish to TAG Domain'
                  : 'Resolve Publish Blockers To Publish'}
            </button>
          </div>
          {publishMessage ? (
            <div style={{ padding: '0.85rem 1rem', borderRadius: '10px', background: 'rgba(16,185,129,0.12)', border: '1px solid rgba(16,185,129,0.35)' }}>
              <strong style={{ display: 'block', marginBottom: '0.25rem' }}>Publish complete</strong>
              <span className="hint" style={{ color: 'var(--text-main)' }}>{publishMessage}</span>
            </div>
          ) : null}
          {publishError ? (
            <div style={{ padding: '0.85rem 1rem', borderRadius: '10px', background: 'rgba(239,68,68,0.1)', border: '1px solid var(--danger)' }}>
              <strong style={{ display: 'block', marginBottom: '0.25rem' }}>Publish failed</strong>
              <span className="hint" style={{ color: '#fca5a5' }}>{publishError}</span>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function WorkspaceUnavailablePanel({ mode }: { mode: DataMode }) {
  const message =
    mode === "setup"
      ? "Initialize the live review workspace first. The simulated assistant path has been removed."
      : mode === "mock"
        ? "The workspace is unavailable because the live backend could not be reached."
        : "The workspace is still loading.";

  return (
    <div className="card" style={{ display: 'grid', gap: '0.9rem', flex: 1, alignContent: 'center' }}>
      <h3>Live Review Workspace Required</h3>
      <p className="hint">{message}</p>
      <p className="hint">Review answers, publish, and SQL validation now run only against the real backend workspace.</p>
    </div>
  );
}

function ValidationWorkbench({ state, sourceName }: { state: KnowledgeState; sourceName: string }) {
  const suggestedQuestions = Array.from(
    new Set(
      Object.values(state.tables)
        .flatMap((table) => table.common_business_questions)
        .filter(Boolean)
    )
  ).slice(0, 5);
  const [question, setQuestion] = useState(suggestedQuestions[0] || "");
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<SqlValidationResponse | null>(null);

  const handleRun = async () => {
    if (!question.trim()) return;
    setRunning(true);
    setError("");
    try {
      const response = await validateBusinessQuestion(sourceName, question.trim());
      setResult(response);
    } catch (err) {
      setResult(null);
      setError(err instanceof Error ? err.message : "Validation failed.");
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="card" style={{ marginTop: '2rem', display: 'grid', gap: '1rem' }}>
      <div>
        <h3>SQL Validation Workbench</h3>
        <p className="hint">
          Test real business questions against the current semantic bundle. The generated SQL stays visible and execution is limited to a guarded read-only path.
        </p>
      </div>

      {suggestedQuestions.length > 0 ? (
        <div style={{ display: 'flex', gap: '0.6rem', flexWrap: 'wrap' }}>
          {suggestedQuestions.map((item) => (
            <button
              key={item}
              className="btn btn-outline"
              style={{ fontSize: '0.8rem' }}
              onClick={() => setQuestion(item)}
            >
              {item}
            </button>
          ))}
        </div>
      ) : null}

      <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
        <input
          type="text"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="Ask a business question"
          style={{ flex: '1 1 420px' }}
        />
        <button className="btn btn-primary" onClick={handleRun} disabled={running || !question.trim()}>
          {running ? 'Running...' : 'Run Validation'}
        </button>
      </div>

      {error ? (
        <div style={{ padding: '0.85rem 1rem', borderRadius: '10px', background: 'rgba(239,68,68,0.1)', border: '1px solid var(--danger)' }}>
          <strong style={{ display: 'block', marginBottom: '0.25rem' }}>Validation error</strong>
          <span className="hint" style={{ color: '#fca5a5' }}>{error}</span>
        </div>
      ) : null}

      {result ? (
        <div style={{ display: 'grid', gap: '1rem' }}>
          <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
            <span className={`pill ${result.execution_status === 'success' ? 'pill-success' : 'pill-warning'}`}>
              {result.execution_status}
            </span>
            {result.matched_table ? <span className="pill">Table: {result.matched_table}</span> : null}
            <span className="pill">Intent: {result.intent.replaceAll("_", " ")}</span>
            <span className="pill">{result.row_count} row(s)</span>
          </div>

          <div>
            <strong style={{ display: 'block', marginBottom: '0.5rem' }}>Generated SQL</strong>
            <pre style={{ margin: 0, padding: '1rem', background: 'var(--bg-surface-alt)', borderRadius: '10px', overflowX: 'auto' }}>
              <code>{result.sql}</code>
            </pre>
          </div>

          {result.warnings.length > 0 ? (
            <div>
              <strong style={{ display: 'block', marginBottom: '0.5rem' }}>Notes</strong>
              <div className="stack" style={{ gap: '0.35rem' }}>
                {result.warnings.map((warning) => (
                  <p key={warning} className="hint" style={{ margin: 0 }}>{warning}</p>
                ))}
              </div>
            </div>
          ) : null}

          {result.error ? (
            <div style={{ padding: '0.85rem 1rem', borderRadius: '10px', background: 'rgba(239,68,68,0.1)', border: '1px solid var(--danger)' }}>
              <strong style={{ display: 'block', marginBottom: '0.25rem' }}>Execution error</strong>
              <span className="hint" style={{ color: '#fca5a5' }}>{result.error}</span>
            </div>
          ) : result.rows.length > 0 ? (
            <div>
              <strong style={{ display: 'block', marginBottom: '0.5rem' }}>Preview</strong>
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                  <thead>
                    <tr>
                      {result.columns.map((column) => (
                        <th key={column} style={{ textAlign: 'left', padding: '0.6rem', borderBottom: '1px solid var(--border)', color: 'var(--text-muted)' }}>
                          {column}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {result.rows.map((row, index) => (
                      <tr key={`${index}-${JSON.stringify(row)}`}>
                        {result.columns.map((column) => (
                          <td key={`${index}-${column}`} style={{ padding: '0.6rem', borderBottom: '1px solid var(--border)' }}>
                            {String(row[column] ?? "")}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ) : (
            <p className="hint" style={{ margin: 0 }}>The query executed successfully but returned no rows.</p>
          )}
        </div>
      ) : null}
    </div>
  );
}
