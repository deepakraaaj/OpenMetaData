"use client";

import { useEffect, useState } from "react";
import { KnowledgeState, SemanticGap } from "../lib/types";

type Message = {
  id: string;
  role: "ai" | "user";
  text: string;
  gapId?: string;
};

type Props = {
  state: KnowledgeState;
};

export default function Chatbot({ state }: Props) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");

  useEffect(() => {
    // Initial greeting and first question based on gaps
    const firstGap = state.unresolved_gaps.find(g => g.is_blocking) || state.unresolved_gaps[0];
    
    setMessages([
      {
        id: "m1",
        role: "ai",
        text: "I've analyzed your database schema. I found a few things that need your clarification to ensure I generate accurate semantic models.",
      },
      {
        id: "m2",
        role: "ai",
        text: firstGap?.suggested_question || "Everything looks good! Would you like to review the final bundle?",
        gapId: firstGap?.gap_id,
      }
    ]);
  }, [state.unresolved_gaps]);

  const handleSend = () => {
    if (!input.trim()) return;

    setMessages(prev => [...prev, { id: Date.now().toString(), role: "user", text: input }]);
    setInput("");

    // Simulate AI thinking and moving to next gap
    setTimeout(() => {
      setMessages(prev => [...prev, {
        id: (Date.now() + 1).toString(),
        role: "ai",
        text: "Understood. I've updated the knowledge state. Looking at the next item...",
      }]);
    }, 600);
  };

  return (
    <div className="chat-panel">
      <div className="chat-header">
        <div className="stack">
          <h3>Onboarding Assistant</h3>
          <span className="pill pill-success">Agent Active</span>
        </div>
      </div>

      <div className="chat-messages">
        {messages.map((m) => (
          <div key={m.id} className={`message ${m.role === 'ai' ? 'message-ai' : 'message-user'}`}>
            <p>{m.text}</p>
          </div>
        ))}
      </div>

      <div style={{ padding: '1.5rem', borderTop: '1px solid var(--border)' }}>
        <div style={{ display: 'flex', gap: '0.75rem' }}>
          <input 
            type="text" 
            placeholder="Type your answer..." 
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleSend()}
          />
          <button className="btn btn-primary" onClick={handleSend}>Send</button>
        </div>
      </div>
    </div>
  );
}
