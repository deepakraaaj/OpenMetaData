"use client";

import type { UrlOnboardingResponse } from "./types";

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

export async function onboardFromUrl(payload: {
  db_url: string;
  source_name?: string;
  domain_name?: string;
  description?: string;
}): Promise<UrlOnboardingResponse> {
  return fetchJson<UrlOnboardingResponse>("/api/onboarding/url", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
