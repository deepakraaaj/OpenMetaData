"use client";

import { useState } from "react";
import { MOCK_KNOWLEDGE_STATE } from "../lib/mock-data";
import KnowledgePanel from "./KnowledgePanel";
import Chatbot from "./Chatbot";
import SemanticDiagram from "./SemanticDiagram";
import EnumReviewGrid from "./EnumReviewGrid";

type Screen = "connect" | "overview" | "workspace" | "enums" | "final";

export function OnboardingWizard({ sourceName }: { sourceName: string }) {
  const [screen, setScreen] = useState<Screen>("connect");
  const [state, setState] = useState(MOCK_KNOWLEDGE_STATE);

  const renderScreen = () => {
    switch (screen) {
      case "connect":
        return <ConnectScreen onNext={() => setScreen("overview")} sourceName={sourceName} />;
      case "overview":
        return <OverviewScreen onNext={() => setScreen("workspace")} state={state} sourceName={sourceName} />;
      case "workspace":
        return (
          <div className="workspace">
            <Chatbot state={state} />
            <KnowledgePanel state={state} />
          </div>
        );
      case "enums":
        return <EnumReviewGrid state={state} />;
      case "final":
        return <FinalReviewScreen state={state} />;
    }
  };

  return (
    <div className="frame">
      {/* Navigation Header */}
      <nav style={{ padding: '1rem 2.5rem', borderBottom: '1px solid var(--border)', display: 'flex', gap: '2rem', alignItems: 'center', background: 'var(--bg-surface)' }}>
        <div style={{ fontWeight: 700, fontSize: '1.25rem', color: 'var(--accent)' }}>MD Onboarder</div>
        <div style={{ display: 'flex', gap: '1.5rem', fontSize: '0.875rem' }}>
          <NavItem active={screen === 'connect'} label="1. Connect" onClick={() => setScreen('connect')} />
          <NavItem active={screen === 'overview'} label="2. Overview" onClick={() => setScreen('overview')} />
          <NavItem active={screen === 'workspace'} label="3. Workspace" onClick={() => setScreen('workspace')} />
          <NavItem active={screen === 'enums'} label="4. Enums" onClick={() => setScreen('enums')} />
          <NavItem active={screen === 'final'} label="5. Review" onClick={() => setScreen('final')} />
        </div>
        <div style={{ marginLeft: 'auto' }}>
          <span className="pill pill-success">Live: {sourceName}</span>
        </div>
      </nav>

      <div style={{ flex: 1, overflow: 'auto' }}>
        {renderScreen()}
      </div>
    </div>
  );
}

function NavItem({ active, label, onClick }: { active: boolean, label: string, onClick: () => void }) {
  return (
    <span 
      onClick={onClick}
      style={{ 
        cursor: 'pointer', 
        color: active ? 'var(--text-main)' : 'var(--text-muted)',
        fontWeight: active ? 600 : 400,
        position: 'relative'
      }}
    >
      {label}
      {active && <div style={{ position: 'absolute', bottom: '-21px', left: 0, right: 0, height: '2px', background: 'var(--accent)' }} />}
    </span>
  );
}

function ConnectScreen({ onNext, sourceName }: { onNext: () => void, sourceName: string }) {
  return (
    <div className="hero">
      <span className="eyebrow">Phase 3 — Mock Mode</span>
      <h1>Connect your data source.</h1>
      <p>Select a verified connection from OpenMetaData to begin the semantic grounding process.</p>
      
      <div className="card" style={{ maxWidth: '500px', margin: '0 auto', textAlign: 'left' }}>
        <div className="stack" style={{ gap: '1rem' }}>
          <div className="stack" style={{ gap: '0.5rem' }}>
            <label className="hint">Select Active Database</label>
            <select defaultValue={`${sourceName.toLowerCase()}_prod`}>
              <option value={`${sourceName.toLowerCase()}_prod`}>{sourceName.toLowerCase()}_prod</option>
              <option value={`${sourceName.toLowerCase()}_staging`}>{sourceName.toLowerCase()}_staging</option>
              <option>production_warehouse_v2</option>
              <option>demo_sqlite</option>
            </select>
          </div>
          <button className="btn btn-primary" onClick={onNext} style={{ width: '100%' }}>Initialize Onboarding</button>
        </div>
      </div>
    </div>
  );
}

function OverviewScreen({ onNext, state, sourceName }: { onNext: () => void, state: any, sourceName: string }) {
  return (
    <div className="stack" style={{ padding: '2rem' }}>
      <div className="hero" style={{ padding: '2rem 0', textAlign: 'left', margin: 0 }}>
        <span className="eyebrow">Step 2 — Schema Overview</span>
        <h2>We identified {Object.keys(state.tables).length} core tables in {sourceName}.</h2>
        <p>Before we start the chatbot review, confirm if this looks right.</p>
      </div>

      <SemanticDiagram state={state} />

      <div className="button-row" style={{ marginTop: '2rem', justifyContent: 'flex-end' }}>
        <button className="btn btn-primary" onClick={onNext}>Continue to Workspace</button>
      </div>
    </div>
  );
}

function FinalReviewScreen({ state }: { state: any }) {
  return (
    <div className="hero" style={{ textAlign: 'left', maxWidth: '1000px' }}>
      <span className="eyebrow">Step 5 — Final Review</span>
      <h1>Review and Export Bundle.</h1>
      
      <div className="grid" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '2rem', marginTop: '2rem' }}>
        <div className="card">
          <h3>Readiness</h3>
          <div className="progress-container">
            <div className="progress-bar" style={{ width: `${state.readiness.readiness_percentage}%` }}></div>
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
            <div style={{ color: 'var(--accent)' }}>/bundle/</div>
            <div>  ├── tables.json</div>
            <div>  ├── enums.json</div>
            <div>  ├── business_rules.json</div>
            <div>  └── readiness.json</div>
          </div>
          <button className="btn btn-outline" style={{ marginTop: '1rem', width: '100%' }}>Download ZIP</button>
        </div>
      </div>

      <button className="btn btn-primary" style={{ marginTop: '2rem', padding: '1rem 3rem' }} disabled={!state.readiness.is_ready}>
        Publish to TAG Domain
      </button>
    </div>
  );
}
