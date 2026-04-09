"use client";

import type {
  BulkReviewAction,
  ChatbotPackageResponse,
  KnowledgeState,
  OnboardingJobSnapshot,
  ReviewMode,
} from "./types";

function normalizeBaseUrl(value: string | undefined, fallback = ""): string {
  return (value || fallback).replace(/\/$/, "");
}

export function openMetadataClientApiBaseUrl(): string {
  return normalizeBaseUrl(process.env.NEXT_PUBLIC_OPENMETADATA_API_BASE_URL, "http://127.0.0.1:8088");
}

export function tagClientApiBaseUrl(): string {
  return normalizeBaseUrl(process.env.NEXT_PUBLIC_TAG_API_BASE_URL);
}

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${openMetadataClientApiBaseUrl()}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
  });
  if (!response.ok) {
    const text = await response.text();
    try {
      const payload = JSON.parse(text) as { detail?: string; message?: string };
      throw new Error(payload.detail || payload.message || text || `Request failed: ${response.status}`);
    } catch {
      throw new Error(text || `Request failed: ${response.status}`);
    }
  }
  return response.json() as Promise<T>;
}

async function fetchJsonWithTimeout<T>(
  path: string,
  timeoutMs: number,
  init?: RequestInit,
): Promise<T> {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetchJson<T>(path, {
      ...init,
      signal: controller.signal,
    });
  } finally {
    window.clearTimeout(timeoutId);
  }
}

export async function startOnboardingJob(payload: {
  db_url: string;
  source_name?: string;
  domain_name?: string;
  description?: string;
}): Promise<OnboardingJobSnapshot> {
  return fetchJson<OnboardingJobSnapshot>("/api/onboarding/url", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getOnboardingJob(jobId: string): Promise<OnboardingJobSnapshot> {
  return fetchJson<OnboardingJobSnapshot>(`/api/onboarding/jobs/${jobId}`);
}

export async function loadChatbotPackage(sourceName: string): Promise<ChatbotPackageResponse> {
  return fetchJson<ChatbotPackageResponse>(`/api/sources/${sourceName}/chatbot-package`);
}

// Phase 4 Engine API
export async function initializeEngine(sourceName: string): Promise<KnowledgeState> {
  return fetchJson<KnowledgeState>(`/api/engine/${sourceName}/initialize`, {
    method: "POST",
  });
}

export async function getEngineState(sourceName: string): Promise<KnowledgeState> {
  return fetchJsonWithTimeout<KnowledgeState>(`/api/engine/${sourceName}/state`, 5000);
}

export async function getNextQuestion(sourceName: string): Promise<any> {
  return fetchJson<any>(`/api/engine/${sourceName}/next-question`);
}

export async function submitAnswer(
  sourceName: string,
  gapId: string,
  answer: string,
  reviewer?: string,
): Promise<KnowledgeState> {
  return fetchJson<KnowledgeState>(`/api/engine/${sourceName}/answer`, {
    method: "POST",
    body: JSON.stringify({ gap_id: gapId, answer, reviewer }),
  });
}

export async function setReviewMode(
  sourceName: string,
  reviewMode: ReviewMode,
): Promise<KnowledgeState> {
  return fetchJson<KnowledgeState>(`/api/engine/${sourceName}/review-mode`, {
    method: "POST",
    body: JSON.stringify({ review_mode: reviewMode }),
  });
}

// AI-powered endpoints
export async function aiGroupTables(sourceName: string): Promise<{ groups: Record<string, string[]> }> {
  return fetchJsonWithTimeout<{ groups: Record<string, string[]> }>(
    `/api/engine/${sourceName}/ai-group`,
    8000,
  );
}

export async function aiResolveGaps(sourceName: string): Promise<{
  resolved_count: number;
  remaining_gaps: number;
  readiness: any;
}> {
  return fetchJson(`/api/engine/${sourceName}/ai-resolve`, { method: "POST" });
}

export async function applyAIDefaults(
  sourceName: string,
  payload: { domain_name?: string; table_name?: string } = {},
): Promise<KnowledgeState> {
  return fetchJson<KnowledgeState>(`/api/engine/${sourceName}/ai-defaults`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
export async function confirmTable(
  sourceName: string,
  tableName: string,
  reviewer?: string,
): Promise<KnowledgeState> {
  return fetchJson<KnowledgeState>(`/api/engine/${sourceName}/confirm-table`, {
    method: "POST",
    body: JSON.stringify({ table_name: tableName, reviewer }),
  });
}

export async function reviewTable(
  sourceName: string,
  tableName: string,
  reviewStatus: "pending" | "confirmed" | "skipped",
  reviewer?: string,
): Promise<KnowledgeState> {
  return fetchJson<KnowledgeState>(`/api/engine/${sourceName}/review-table`, {
    method: "POST",
    body: JSON.stringify({ table_name: tableName, review_status: reviewStatus, reviewer }),
  });
}

export async function bulkReviewTables(
  sourceName: string,
  action: BulkReviewAction,
  reviewer?: string,
): Promise<KnowledgeState> {
  return fetchJson<KnowledgeState>(`/api/engine/${sourceName}/bulk-review`, {
    method: "POST",
    body: JSON.stringify({ action, reviewer }),
  });
}
