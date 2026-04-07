import "server-only";

import type { BundleResponse, QuestionsResponse, SourceSummary } from "./types";

function normalizeBaseUrl(value: string | undefined, fallback: string): string {
  return (value || fallback).replace(/\/$/, "");
}

export function openMetadataServerApiBaseUrl(): string {
  return normalizeBaseUrl(
    process.env.OPENMETADATA_API_BASE_URL || process.env.NEXT_PUBLIC_OPENMETADATA_API_BASE_URL,
    "http://127.0.0.1:8088",
  );
}

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${openMetadataServerApiBaseUrl()}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
    cache: "no-store",
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

export async function listSources(): Promise<SourceSummary[]> {
  return fetchJson<SourceSummary[]>("/api/sources");
}

export async function loadBundle(sourceName: string): Promise<BundleResponse> {
  return fetchJson<BundleResponse>(`/api/sources/${sourceName}/semantic-bundle`);
}

export async function loadQuestions(sourceName: string): Promise<QuestionsResponse> {
  return fetchJson<QuestionsResponse>(`/api/sources/${sourceName}/semantic-bundle/questions`);
}
