"use client";

import { useEffect, useState } from "react";

import { loadChatbotPackage, openMetadataClientApiBaseUrl } from "../lib/client-api";
import type { ChatbotPackageResponse } from "../lib/types";

function absoluteUrl(path: string): string {
  const base = openMetadataClientApiBaseUrl();
  if (!path) {
    return base;
  }
  return `${base}${path.startsWith("/") ? path : `/${path}`}`;
}

function packageFileUrl(sourceName: string, filePath: string): string {
  const encodedSource = encodeURIComponent(sourceName);
  const encodedPath = filePath
    .split("/")
    .map((segment) => encodeURIComponent(segment))
    .join("/");
  return absoluteUrl(`/chatbot-files/${encodedSource}/${encodedPath}`);
}

function titleCase(value: string): string {
  return value
    .replace(/_/g, " ")
    .trim()
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function groupInventory(paths: string[]): Array<{ label: string; files: string[] }> {
  const groups = new Map<string, string[]>();
  for (const path of paths) {
    const group = path.includes("/") ? path.split("/")[0] : "root";
    const existing = groups.get(group) || [];
    existing.push(path);
    groups.set(group, existing);
  }
  return Array.from(groups.entries())
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([label, files]) => ({ label, files: files.sort((a, b) => a.localeCompare(b)) }));
}

export default function ArtifactExplorer({ sourceName }: { sourceName: string }) {
  const [artifactPackage, setArtifactPackage] = useState<ChatbotPackageResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;

    async function loadArtifacts() {
      setLoading(true);
      setError("");
      try {
        const response = await loadChatbotPackage(sourceName);
        if (!active) {
          return;
        }
        setArtifactPackage(response);
      } catch (err) {
        if (!active) {
          return;
        }
        setError(err instanceof Error ? err.message : "Could not load chatbot package.");
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    }

    void loadArtifacts();
    return () => {
      active = false;
    };
  }, [sourceName]);

  if (loading) {
    return (
      <div className="card">
        <h3>Built Artifacts</h3>
        <p className="hint">Loading the generated package inventory...</p>
      </div>
    );
  }

  if (error || !artifactPackage) {
    return (
      <div className="card">
        <h3>Built Artifacts</h3>
        <p className="hint" style={{ color: "var(--danger)" }}>
          {error || "Chatbot package is not available."}
        </p>
      </div>
    );
  }

  const { manifest } = artifactPackage;
  const groups = groupInventory(manifest.inventory || []);
  const entrypoints = Object.entries(manifest.entrypoints || {}).filter(([, value]) => Boolean(value));
  const stats = [
    { label: "Tables", value: manifest.summary.table_count ?? 0 },
    { label: "Questions", value: manifest.summary.question_count ?? 0 },
    { label: "Groups", value: manifest.summary.domain_group_count ?? 0 },
    { label: "Files", value: manifest.inventory.length },
  ];

  return (
    <div className="stack" style={{ gap: "1.5rem", marginTop: "2rem" }}>
      <div className="card">
        <div style={{ display: "flex", justifyContent: "space-between", gap: "1rem", alignItems: "flex-start", flexWrap: "wrap" }}>
          <div>
            <span className="eyebrow">Built Artifacts</span>
            <h3 style={{ marginBottom: "0.5rem" }}>{manifest.source_name} chatbot package</h3>
            <p className="hint">
              Domain: <strong style={{ color: "var(--text-main)" }}>{manifest.domain_name}</strong>
              {" · "}
              DB: <strong style={{ color: "var(--text-main)" }}>{manifest.summary.db_type || "unknown"}</strong>
              {manifest.summary.database_name ? ` · ${manifest.summary.database_name}` : ""}
            </p>
          </div>
          <div className="button-row" style={{ flexWrap: "wrap", justifyContent: "flex-end" }}>
            <a
              href={absoluteUrl(artifactPackage.overview_url)}
              target="_blank"
              rel="noreferrer"
              className="btn btn-primary"
              style={{ textDecoration: "none" }}
            >
              Open Package Overview
            </a>
            <a
              href={absoluteUrl(artifactPackage.download_url)}
              target="_blank"
              rel="noreferrer"
              className="btn btn-outline"
              style={{ textDecoration: "none" }}
            >
              Download Package Zip
            </a>
            <a
              href={absoluteUrl(`/api/sources/${sourceName}/json-zip`)}
              target="_blank"
              rel="noreferrer"
              className="btn btn-outline"
              style={{ textDecoration: "none" }}
            >
              Download Raw JSON
            </a>
          </div>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: "1rem", marginTop: "1.5rem" }}>
          {stats.map((item) => (
            <div
              key={item.label}
              style={{
                border: "1px solid var(--border)",
                borderRadius: "12px",
                padding: "1rem",
                background: "var(--bg-surface-alt)",
              }}
            >
              <div className="hint" style={{ marginBottom: "0.35rem" }}>{item.label}</div>
              <div style={{ fontSize: "1.5rem", fontWeight: 700 }}>{item.value}</div>
            </div>
          ))}
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: "1.5rem" }}>
        <div className="card">
          <h3>Entry Points</h3>
          <div className="stack" style={{ gap: "0.9rem" }}>
            {entrypoints.map(([key, value]) => {
              const label = titleCase(key);
              const href =
                value.endsWith(".json") || value.endsWith(".html") || value.endsWith(".md") || value.endsWith(".yaml")
                  ? packageFileUrl(sourceName, value)
                  : undefined;
              return (
                <div
                  key={key}
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    gap: "1rem",
                    alignItems: "center",
                    padding: "0.85rem 1rem",
                    borderRadius: "10px",
                    background: "var(--bg-surface-alt)",
                    border: "1px solid var(--border)",
                  }}
                >
                  <div>
                    <div style={{ fontWeight: 600 }}>{label}</div>
                    <div className="hint" style={{ fontFamily: "monospace", fontSize: "0.78rem" }}>{value}</div>
                  </div>
                  {href ? (
                    <a
                      href={href}
                      target="_blank"
                      rel="noreferrer"
                      className="btn btn-outline"
                      style={{ whiteSpace: "nowrap", textDecoration: "none" }}
                    >
                      Open
                    </a>
                  ) : (
                    <span className="pill">{value}</span>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        <div className="card">
          <h3>Next Steps</h3>
          <div className="stack" style={{ gap: "0.85rem" }}>
            {(manifest.next_steps || []).map((step, index) => (
              <div
                key={`${index}-${step}`}
                style={{
                  display: "flex",
                  gap: "0.85rem",
                  padding: "0.85rem 1rem",
                  borderRadius: "10px",
                  background: "var(--bg-surface-alt)",
                  border: "1px solid var(--border)",
                }}
              >
                <span className="pill pill-success" style={{ minWidth: "2rem", justifyContent: "center" }}>
                  {index + 1}
                </span>
                <p className="hint" style={{ color: "var(--text-main)" }}>{step}</p>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="card">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "1rem", flexWrap: "wrap" }}>
          <div>
            <h3>Everything Built</h3>
            <p className="hint">Every file in the generated chatbot package is listed below and grouped by folder.</p>
          </div>
          <span className="pill">{manifest.inventory.length} files</span>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: "1rem", marginTop: "1.25rem" }}>
          {groups.map((group) => (
            <div
              key={group.label}
              style={{
                border: "1px solid var(--border)",
                borderRadius: "12px",
                padding: "1rem",
                background: "linear-gradient(180deg, rgba(99, 102, 241, 0.08), rgba(24, 24, 27, 0.8))",
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.75rem" }}>
                <div style={{ fontWeight: 700 }}>{group.label === "root" ? "Root Files" : titleCase(group.label)}</div>
                <span className="pill">{group.files.length}</span>
              </div>
              <div className="stack" style={{ gap: "0.5rem" }}>
                {group.files.map((file) => (
                  <a
                    key={file}
                    href={packageFileUrl(sourceName, file)}
                    target="_blank"
                    rel="noreferrer"
                    style={{
                      display: "block",
                      textDecoration: "none",
                      padding: "0.65rem 0.75rem",
                      borderRadius: "10px",
                      background: "rgba(9, 9, 11, 0.45)",
                      border: "1px solid rgba(63, 63, 70, 0.85)",
                      color: "var(--text-main)",
                      fontSize: "0.82rem",
                      fontFamily: "monospace",
                      wordBreak: "break-word",
                    }}
                  >
                    {file}
                  </a>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
