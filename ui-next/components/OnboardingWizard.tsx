"use client";

import { useMemo, useState, useTransition } from "react";
import { useRouter } from "next/navigation";

import type { BundleResponse, QuestionChoice, QuestionItem, QuestionSection } from "../lib/types";
import { openMetadataClientApiBaseUrl, tagClientApiBaseUrl } from "../lib/client-api";

type Props = {
  sourceName: string;
  initialBundle: BundleResponse;
  sections: QuestionSection[];
  downloadUrl: string;
};

type SectionSummary = {
  id: string;
  title: string;
  total: number;
  missing: number;
  answered: number;
};

type ChoiceOption = {
  label: string;
  value: string;
  hint?: string;
};

type SchemaTableContext = {
  tableName: string;
  label: string;
  description: string;
  importantColumns: string[];
  tenantScopeCandidates: string[];
  timestampColumns: string[];
  statusColumns: string[];
};

type AdaptiveClarification = QuestionItem & {
  description?: string;
};

type AnswerInterpretation = {
  title: string;
  body: string;
  bullets: string[];
};

type HistoryEntry = {
  id: string;
  sectionTitle: string;
  label: string;
  answer: string;
};

function deepClone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function getAtPath(root: Record<string, unknown>, path: Array<string | number> = []): unknown {
  let current: any = root;
  for (const segment of path) {
    if (current === null || current === undefined) {
      return undefined;
    }
    current = current[segment];
  }
  return current;
}

function setAtPath(
  root: Record<string, unknown>,
  path: Array<string | number>,
  value: unknown,
): Record<string, unknown> {
  const next = deepClone(root);
  let cursor: any = next;
  for (let index = 0; index < path.length - 1; index += 1) {
    const segment = path[index];
    const nextSegment = path[index + 1];
    if (cursor[segment] === undefined) {
      cursor[segment] = typeof nextSegment === "number" ? [] : {};
    }
    cursor = cursor[segment];
  }
  cursor[path[path.length - 1]] = value;
  return next;
}

function encodeTableColumnChoice(value: string) {
  const [tableName, columnName] = value.split(".");
  return {
    table_name: tableName || "",
    column_name: columnName || "",
  };
}

function formatValue(kind: string, value: unknown): string {
  if (Array.isArray(value)) {
    return value.join(", ");
  }
  if (typeof value === "boolean") {
    return value ? "true" : "false";
  }
  if (kind === "table-column-select" && value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    return `${record.table_name || ""}.${record.column_name || ""}`;
  }
  return String(value ?? "");
}

function normalizeValue(kind: string, raw: string): unknown {
  if (kind === "tags") {
    return raw
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
  }
  if (kind === "table-column-select") {
    return encodeTableColumnChoice(raw);
  }
  return raw;
}

function isValueBlank(value: unknown): boolean {
  if (value === undefined || value === null) {
    return true;
  }
  if (typeof value === "string") {
    return value.trim().length === 0;
  }
  if (Array.isArray(value)) {
    return value.length === 0;
  }
  if (typeof value === "object") {
    return Object.values(value as Record<string, unknown>).every((item) => isValueBlank(item));
  }
  return false;
}

function buildQuestionSnapshot(
  question: QuestionItem,
  draftFiles: Record<string, Record<string, unknown>>,
): {
  displayValue: string;
  storedValue: unknown;
  effectiveValue: unknown;
  hasStoredValue: boolean;
  hasSuggestedValue: boolean;
  isMissing: boolean;
} {
  const storedValue =
    question.bundle_file && question.field_path
      ? getAtPath(draftFiles[question.bundle_file] || {}, question.field_path)
      : undefined;
  const hasStoredValue = !isValueBlank(storedValue);
  const effectiveValue = hasStoredValue ? storedValue : undefined;
  return {
    displayValue: formatValue(question.kind, hasStoredValue ? storedValue : ""),
    storedValue,
    effectiveValue,
    hasStoredValue,
    hasSuggestedValue: !isValueBlank(question.suggested_answer),
    isMissing: !hasStoredValue,
  };
}

function summarizeSections(
  sections: QuestionSection[],
  draftFiles: Record<string, Record<string, unknown>>,
): SectionSummary[] {
  return sections.map((section) => {
    const missing = section.questions.filter((question) => buildQuestionSnapshot(question, draftFiles).isMissing).length;
    return {
      id: section.id,
      title: section.title,
      total: section.questions.length,
      missing,
      answered: section.questions.length - missing,
    };
  });
}

function findInitialSectionIndex(
  sections: QuestionSection[],
  draftFiles: Record<string, Record<string, unknown>>,
): number {
  const firstMissingIndex = summarizeSections(sections, draftFiles).findIndex((section) => section.missing > 0);
  return firstMissingIndex >= 0 ? firstMissingIndex : 0;
}

function findInitialQuestionIndex(
  section: QuestionSection | undefined,
  draftFiles: Record<string, Record<string, unknown>>,
): number {
  if (!section?.questions.length) {
    return 0;
  }
  const firstMissingIndex = section.questions.findIndex((question) => buildQuestionSnapshot(question, draftFiles).isMissing);
  return firstMissingIndex >= 0 ? firstMissingIndex : 0;
}

function updateDomainNameInFiles(
  files: Record<string, Record<string, unknown>>,
  domainName: string,
): Record<string, Record<string, unknown>> {
  const nextFiles = deepClone(files);
  for (const payload of Object.values(nextFiles)) {
    if (payload && typeof payload === "object") {
      payload.domain_name = domainName;
    }
  }
  return nextFiles;
}

function buildChoiceOptions(question: QuestionItem): ChoiceOption[] {
  if (question.kind === "table-column-select") {
    return (question.choices || []).flatMap((choice) =>
      (choice.columns || []).map((column) => ({
        label: `${choice.table_name || ""}.${column}`,
        value: `${choice.table_name || ""}.${column}`,
        hint: choice.table_name || "",
      })),
    );
  }

  return (question.choices || [])
    .map((choice: QuestionChoice) => ({
      label: String(choice.label || "").trim(),
      value: String(choice.label || "").trim(),
      hint: String(choice.hint || "").trim(),
    }))
    .filter((choice) => choice.label);
}

function tokenizeValue(value: string): string[] {
  return String(value || "")
    .toLowerCase()
    .split(/[^a-z0-9]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function uniqueStrings(values: string[]): string[] {
  const seen = new Set<string>();
  return values.filter((value) => {
    const normalized = value.trim().toLowerCase();
    if (!normalized || seen.has(normalized)) {
      return false;
    }
    seen.add(normalized);
    return true;
  });
}

function extractColumnNames(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((item) => {
      if (typeof item === "string") {
        return item.trim();
      }
      if (item && typeof item === "object") {
        return String((item as Record<string, unknown>).column_name || "").trim();
      }
      return "";
    })
    .filter(Boolean);
}

function getSchemaTables(draftFiles: Record<string, Record<string, unknown>>): SchemaTableContext[] {
  const rawTables = draftFiles["schema_context.json"]?.tables;
  if (!Array.isArray(rawTables)) {
    return [];
  }

  return rawTables
    .map((item) => {
      const record = item as Record<string, unknown>;
      return {
        tableName: String(record.table_name || "").trim(),
        label: String(record.label || record.table_name || "").trim(),
        description: String(record.description || "").trim(),
        importantColumns: extractColumnNames(record.important_columns),
        tenantScopeCandidates: Array.isArray(record.tenant_scope_candidates)
          ? record.tenant_scope_candidates.map((value) => String(value || "").trim()).filter(Boolean)
          : [],
        timestampColumns: Array.isArray(record.timestamp_columns)
          ? record.timestamp_columns.map((value) => String(value || "").trim()).filter(Boolean)
          : [],
        statusColumns: Array.isArray(record.status_columns)
          ? record.status_columns.map((value) => String(value || "").trim()).filter(Boolean)
          : [],
      };
    })
    .filter((table) => table.tableName);
}

function buildTableChoicesFromTerms(
  tables: SchemaTableContext[],
  terms: string[],
): Array<{ label: string; hint?: string; score: number }> {
  const normalizedTerms = uniqueStrings(terms.flatMap((term) => tokenizeValue(term)));
  if (!normalizedTerms.length) {
    return [];
  }

  return tables
    .map((table) => {
      let score = 0;
      const haystacks = [
        table.tableName.toLowerCase(),
        table.label.toLowerCase(),
        table.description.toLowerCase(),
        ...table.importantColumns.map((column) => column.toLowerCase()),
      ];
      for (const term of normalizedTerms) {
        if (table.tableName.toLowerCase() === term || table.label.toLowerCase() === term) {
          score += 8;
          continue;
        }
        if (table.tableName.toLowerCase().includes(term) || table.label.toLowerCase().includes(term)) {
          score += 5;
          continue;
        }
        if (haystacks.some((value) => value.includes(term))) {
          score += 2;
        }
      }
      return {
        label: table.tableName,
        hint: table.description,
        score,
      };
    })
    .filter((item) => item.score > 0)
    .sort((left, right) => right.score - left.score || left.label.localeCompare(right.label));
}

function buildAdaptiveClarification(
  question: QuestionItem,
  draftFiles: Record<string, Record<string, unknown>>,
): AdaptiveClarification | null {
  const tables = getSchemaTables(draftFiles);

  if (question.id === "key-entities") {
    const value = getAtPath(draftFiles["business_semantics.json"] || {}, ["key_entities"]);
    const entities = Array.isArray(value) ? value.map((item) => String(item || "").trim()).filter(Boolean) : [];
    if (!entities.length) {
      return null;
    }

    const existingPrimaryTable = getAtPath(draftFiles["business_semantics.json"] || {}, ["table_roles", "primary_table"]);
    if (!isValueBlank(existingPrimaryTable)) {
      return null;
    }

    const candidates = buildTableChoicesFromTerms(tables, entities).slice(0, 8);
    if (!candidates.length) {
      return null;
    }

    return {
      id: "clarify-primary-table",
      label: `Based on "${entities[0]}", which table stores those records most directly?`,
      description: "I matched your wording against table names, labels, and important columns. Confirm the real operational table before continuing.",
      kind: "select",
      bundle_file: "business_semantics.json",
      field_path: ["table_roles", "primary_table"],
      choices: candidates.map((item) => ({ label: item.label, hint: item.hint })),
      suggested_answer: candidates[0]?.label || "",
      evidence: candidates.slice(0, 4).map((item) => `${item.label}${item.hint ? `: ${item.hint}` : ""}`),
    };
  }

  if (question.id === "primary-table") {
    const selectedTableName = String(
      getAtPath(draftFiles["business_semantics.json"] || {}, ["table_roles", "primary_table"]) || "",
    ).trim();
    if (!selectedTableName) {
      return null;
    }

    const existingTenantScope = getAtPath(draftFiles["schema_context.json"] || {}, ["table_roles", "tenant_scope"]);
    if (!isValueBlank(existingTenantScope)) {
      return null;
    }

    const selectedTable = tables.find((table) => table.tableName === selectedTableName);
    if (!selectedTable) {
      return null;
    }

    const scopeCandidates = uniqueStrings([
      ...selectedTable.tenantScopeCandidates,
      ...selectedTable.importantColumns.filter((column) =>
        /(company|tenant|org|organisation|organization|client|account|customer)/i.test(column),
      ),
    ]);
    if (!scopeCandidates.length) {
      return null;
    }

    return {
      id: "clarify-tenant-scope",
      label: `For "${selectedTableName}", which field should TAG use for company or tenant scoping?`,
      description: "This helps TAG avoid generating cross-company queries when the app is multi-tenant.",
      kind: "table-column-select",
      bundle_file: "schema_context.json",
      field_path: ["table_roles", "tenant_scope"],
      choices: [{ table_name: selectedTableName, columns: scopeCandidates }],
      suggested_answer: `${selectedTableName}.${scopeCandidates[0]}`,
      evidence: [
        `Selected table: ${selectedTableName}`,
        `Candidate scope fields: ${scopeCandidates.join(", ")}`,
      ],
    };
  }

  if (question.id.startsWith("glossary-") && question.field_path?.length) {
    const glossaryIndex = typeof question.field_path[1] === "number" ? question.field_path[1] : null;
    if (glossaryIndex === null) {
      return null;
    }
    const glossaryItem = getAtPath(draftFiles["business_semantics.json"] || {}, ["glossary", glossaryIndex]);
    const glossaryRecord = glossaryItem && typeof glossaryItem === "object" ? (glossaryItem as Record<string, unknown>) : null;
    const term = String(glossaryRecord?.term || "").trim();
    const meaning = String(glossaryRecord?.meaning || "").trim();
    const synonyms = Array.isArray(glossaryRecord?.synonyms)
      ? glossaryRecord!.synonyms.map((item) => String(item || "").trim()).filter(Boolean)
      : [];
    if (!term || !meaning || synonyms.length) {
      return null;
    }

    const related = Array.isArray(glossaryRecord?.related_tables)
      ? glossaryRecord!.related_tables.map((item) => String(item || "").trim()).filter(Boolean)
      : [];

    return {
      id: `clarify-synonyms-${glossaryIndex}`,
      label: `What other words do users use instead of "${term}"?`,
      description: "Add the real user-facing words here so retrieval does not depend on schema naming.",
      kind: "tags",
      bundle_file: "business_semantics.json",
      field_path: ["glossary", glossaryIndex, "synonyms"],
      suggested_answer: related.slice(0, 3),
      evidence: related.length ? [`Related tables: ${related.join(", ")}`] : [`Meaning: ${meaning}`],
    };
  }

  return null;
}

function buildAnswerInterpretation(
  question: QuestionItem,
  snapshot: { effectiveValue: unknown },
  draftFiles: Record<string, Record<string, unknown>>,
): AnswerInterpretation | null {
  const tables = getSchemaTables(draftFiles);
  const displayValue = formatValue(question.kind, snapshot.effectiveValue).trim();

  if (!displayValue) {
    return null;
  }

  if (question.id === "key-entities") {
    const entities = Array.isArray(snapshot.effectiveValue)
      ? snapshot.effectiveValue.map((item) => String(item || "").trim()).filter(Boolean)
      : [];
    const candidates = buildTableChoicesFromTerms(tables, entities).slice(0, 3);
    return {
      title: "What I inferred from your wording",
      body: `I will treat ${entities.join(", ")} as the user-facing names for the core records in this domain.`,
      bullets: candidates.length
        ? [
            `Closest schema matches: ${candidates.map((item) => item.label).join(", ")}`,
            "These names will be used as aliases during retrieval and later SQL generation.",
          ]
        : ["These names will be used as business aliases in the semantic bundle."],
    };
  }

  if (
    question.id === "primary-table" ||
    question.id === "people-table" ||
    question.id === "location-table"
  ) {
    const selectedTable = tables.find((table) => table.tableName === displayValue);
    return {
      title: "How this table will be treated",
      body: selectedTable
        ? `${displayValue} will become a named table role in the bundle. TAG will prioritize it when deciding which tables to query.`
        : `${displayValue} will be saved as a trusted table role for this domain.`,
      bullets: selectedTable
        ? [
            selectedTable.description || "No table description was available.",
            selectedTable.importantColumns.length
              ? `Important columns: ${selectedTable.importantColumns.slice(0, 6).join(", ")}`
              : "Important columns will be inferred later from the semantic bundle.",
          ]
        : [],
    };
  }

  if (question.id === "tenant-scope") {
    return {
      title: "How TAG will use this scope field",
      body: `I will treat ${displayValue} as the tenant or company boundary when SQL is generated for the primary workflow table.`,
      bullets: [
        "This reduces the chance of cross-company queries.",
        "The selected field will also be surfaced to later review and retrieval steps.",
      ],
    };
  }

  if (question.id.startsWith("glossary-")) {
    return {
      title: "How this business term will be grounded",
      body: `${displayValue} will be stored as the human meaning for this glossary term.`,
      bullets: [
        "The glossary is used to bridge user language and schema language.",
        "This meaning can trigger a targeted follow-up for synonyms if users speak differently.",
      ],
    };
  }

  if (question.id.startsWith("pattern-") || question.id === "additional-real-questions") {
    return {
      title: "How retrieval will use these examples",
      body: "These phrasings will be added as real user-language examples for semantic retrieval.",
      bullets: [
        "Similar future questions will rank these patterns higher.",
        "This directly improves query intent matching without changing the schema bundle structure.",
      ],
    };
  }

  if (question.kind === "boolean") {
    return {
      title: "How this decision will be applied",
      body: `This answer is recorded as ${displayValue} and will be treated as a reviewed rule rather than an LLM guess.`,
      bullets: [
        "Validated rules are safer than inferred joins or exposure policies.",
      ],
    };
  }

  return {
    title: "How this answer will be used",
    body: `${displayValue} will be written into the semantic bundle and used as reviewed business context.`,
    bullets: [
      "This replaces an LLM assumption with a human-approved answer.",
    ],
  };
}

function buildTagSuggestions(question: QuestionItem): string[] {
  const fromSuggested = Array.isArray(question.suggested_answer)
    ? question.suggested_answer.map((item) => String(item || "").trim())
    : [];
  const fromChoices = (question.choices || []).map((choice) => String(choice.label || "").trim());
  const fromEvidence = (question.evidence || []).map((item) => String(item || "").trim());

  const seen = new Set<string>();
  const ordered = [...fromSuggested, ...fromChoices, ...fromEvidence].filter((item) => {
    if (!item) {
      return false;
    }
    const normalized = item.toLowerCase();
    if (seen.has(normalized)) {
      return false;
    }
    seen.add(normalized);
    return true;
  });

  return ordered.slice(0, 8);
}

function questionInputHint(question: QuestionItem): string {
  if (question.kind === "tags") {
    return "Separate multiple answers with commas.";
  }
  if (question.kind === "table-column-select") {
    return "Pick the exact table.column pair TAG should trust.";
  }
  if (question.kind === "boolean") {
    return "Choose the answer you want written into the bundle.";
  }
  if (question.kind === "select") {
    return "Use the suggested choice if it already looks right.";
  }
  return "Short, direct answers are enough here.";
}

export function OnboardingWizard({ sourceName, initialBundle, sections, downloadUrl }: Props) {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();
  const [draftFiles, setDraftFiles] = useState<Record<string, Record<string, unknown>>>(initialBundle.files);
  const [domainName, setDomainName] = useState(
    String(initialBundle.files["business_semantics.json"]?.domain_name || sourceName),
  );
  const [currentSectionIndex, setCurrentSectionIndex] = useState(() =>
    findInitialSectionIndex(sections, initialBundle.files),
  );
  const [currentQuestionIndex, setCurrentQuestionIndex] = useState(() =>
    findInitialQuestionIndex(
      sections[findInitialSectionIndex(sections, initialBundle.files)],
      initialBundle.files,
    ),
  );
  const [status, setStatus] = useState<string>("");
  const [statusTone, setStatusTone] = useState<"success" | "error" | "muted">("muted");

  const sectionSummaries = useMemo(() => summarizeSections(sections, draftFiles), [sections, draftFiles]);
  const activeSection = sections[currentSectionIndex] || sections[0];
  const safeQuestionIndex = activeSection
    ? Math.min(Math.max(currentQuestionIndex, 0), Math.max(activeSection.questions.length - 1, 0))
    : 0;
  const activeQuestion = activeSection?.questions[safeQuestionIndex];
  const activeSnapshot = activeQuestion ? buildQuestionSnapshot(activeQuestion, draftFiles) : null;
  const activeClarificationCandidate =
    activeQuestion && activeSnapshot && !activeSnapshot.isMissing
      ? buildAdaptiveClarification(activeQuestion, draftFiles)
      : null;
  const activeClarificationStoredValue =
    activeClarificationCandidate?.bundle_file && activeClarificationCandidate.field_path
      ? getAtPath(
          draftFiles[activeClarificationCandidate.bundle_file] || {},
          activeClarificationCandidate.field_path,
        )
      : undefined;
  const activeClarification =
    activeClarificationCandidate &&
    isValueBlank(activeClarificationStoredValue)
      ? activeClarificationCandidate
      : null;
  const activeClarificationSnapshot = activeClarification
    ? buildQuestionSnapshot(activeClarification, draftFiles)
    : null;
  const answerInterpretation =
    activeQuestion && activeSnapshot && !activeSnapshot.isMissing
      ? buildAnswerInterpretation(activeQuestion, activeSnapshot, draftFiles)
      : null;
  const preview = useMemo(() => JSON.stringify(draftFiles, null, 2), [draftFiles]);
  const discoveredTableCount = Array.isArray(draftFiles["schema_context.json"]?.tables)
    ? draftFiles["schema_context.json"]!.tables.length
    : 0;
  const totalQuestions = sectionSummaries.reduce((sum, section) => sum + section.total, 0);
  const missingQuestions = sectionSummaries.reduce((sum, section) => sum + section.missing, 0);
  const completionPercent =
    totalQuestions === 0 ? 0 : Math.round(((totalQuestions - missingQuestions) / totalQuestions) * 100);
  const answeredQuestions = totalQuestions - missingQuestions;
  const choiceOptions = activeQuestion ? buildChoiceOptions(activeQuestion) : [];
  const tagSuggestions = activeQuestion ? buildTagSuggestions(activeQuestion) : [];
  const clarificationChoiceOptions = activeClarification ? buildChoiceOptions(activeClarification) : [];
  const sectionSummaryMap = useMemo(
    () => new Map(sectionSummaries.map((section) => [section.id, section])),
    [sectionSummaries],
  );
  const answeredHistory = useMemo<HistoryEntry[]>(() => {
    const history: HistoryEntry[] = [];

    sections.forEach((section, sectionIndex) => {
      section.questions.forEach((question, questionIndex) => {
        if (sectionIndex === currentSectionIndex && questionIndex === safeQuestionIndex) {
          return;
        }
        const snapshot = buildQuestionSnapshot(question, draftFiles);
        if (!snapshot.hasStoredValue || isValueBlank(snapshot.effectiveValue)) {
          return;
        }
        history.push({
          id: question.id,
          sectionTitle: section.title,
          label: question.label,
          answer: formatValue(question.kind, snapshot.effectiveValue),
        });
      });
    });

    return history.slice(-4);
  }, [sections, currentSectionIndex, safeQuestionIndex, draftFiles]);
  const recentHistory = answeredHistory.slice(-2);
  const activeSectionSummary = activeSection ? sectionSummaryMap.get(activeSection.id) : null;

  async function persistBundleFiles(filesToPersist: Record<string, Record<string, unknown>>) {
    await Promise.all(
      Object.entries(filesToPersist).map(async ([fileName, payload]) => {
        const response = await fetch(
          `${openMetadataClientApiBaseUrl()}/api/sources/${sourceName}/semantic-bundle/${fileName}`,
          {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ payload }),
          },
        );
        if (!response.ok) {
          throw new Error(await response.text());
        }
      }),
    );
  }

  async function saveAll() {
    setStatus("Saving semantic bundle files...");
    setStatusTone("muted");
    try {
      const normalizedFiles = updateDomainNameInFiles(draftFiles, domainName.trim() || sourceName);
      setDraftFiles(normalizedFiles);
      await persistBundleFiles(normalizedFiles);
      setStatus("Semantic bundle saved.");
      setStatusTone("success");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Failed to save semantic bundle.");
      setStatusTone("error");
    }
  }

  async function publish() {
    setStatus("Publishing semantic bundle into TAG...");
    setStatusTone("muted");
    try {
      const normalizedDomainName = domainName.trim() || sourceName;
      const normalizedFiles = updateDomainNameInFiles(draftFiles, normalizedDomainName);
      setDraftFiles(normalizedFiles);
      await persistBundleFiles(normalizedFiles);

      const response = await fetch(
        `${openMetadataClientApiBaseUrl()}/api/sources/${sourceName}/semantic-bundle/publish`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ domain_name: normalizedDomainName }),
        },
      );
      if (!response.ok) {
        throw new Error(await response.text());
      }
      const tagBaseUrl = tagClientApiBaseUrl();
      if (tagBaseUrl) {
        const syncResponse = await fetch(
          `${tagBaseUrl}/semantic/reindex?domain=${encodeURIComponent(normalizedDomainName)}`,
          {
            method: "POST",
          },
        );
        if (!syncResponse.ok) {
          throw new Error(await syncResponse.text());
        }
        setStatus(`Published semantic bundle to '${normalizedDomainName}' and triggered TAG reindex.`);
      } else {
        setStatus(`Published semantic bundle to TAG domain '${normalizedDomainName}'.`);
      }
      setStatusTone("success");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Failed to publish semantic bundle.");
      setStatusTone("error");
    }
  }

  async function rebuild() {
    setStatus("Rebuilding bundle suggestions from source metadata...");
    setStatusTone("muted");
    try {
      const response = await fetch(
        `${openMetadataClientApiBaseUrl()}/api/sources/${sourceName}/semantic-bundle/rebuild`,
        {
          method: "POST",
        },
      );
      if (!response.ok) {
        throw new Error(await response.text());
      }
      setStatus("Suggestions rebuilt. Refreshing the guided interview...");
      startTransition(() => router.refresh());
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Failed to rebuild bundle.");
      setStatusTone("error");
    }
  }

  function writeQuestionValue(question: QuestionItem, value: unknown) {
    if (!question.bundle_file || !question.field_path?.length) {
      return;
    }

    setDraftFiles((current) => {
      const filePayload = deepClone(current[question.bundle_file!] || {});
      return {
        ...current,
        [question.bundle_file!]: setAtPath(filePayload, question.field_path!, value),
      };
    });
  }

  function updateQuestion(question: QuestionItem, rawValue: string | boolean) {
    writeQuestionValue(
      question,
      typeof rawValue === "boolean" ? rawValue : normalizeValue(question.kind, rawValue),
    );
  }

  function applySuggestedAnswer() {
    if (!activeQuestion || activeQuestion.suggested_answer === undefined) {
      return;
    }
    writeQuestionValue(activeQuestion, deepClone(activeQuestion.suggested_answer));
    setStatus("Suggested answer copied into the bundle draft.");
    setStatusTone("muted");
  }

  function addTagSuggestion(tag: string) {
    if (!activeQuestion || activeQuestion.kind !== "tags") {
      return;
    }
    const currentTags = Array.isArray(activeSnapshot?.effectiveValue)
      ? activeSnapshot?.effectiveValue.map((item) => String(item || "").trim()).filter(Boolean)
      : [];
    const normalized = tag.trim();
    if (!normalized || currentTags.some((item) => item.toLowerCase() === normalized.toLowerCase())) {
      return;
    }
    writeQuestionValue(activeQuestion, [...currentTags, normalized]);
  }

  function jumpToTop() {
    if (typeof window !== "undefined") {
      window.scrollTo({ top: 0, behavior: "smooth" });
    }
  }

  function jumpToSection(index: number, questionIndex?: number) {
    const nextSection = sections[index];
    setCurrentSectionIndex(index);
    setCurrentQuestionIndex(
      questionIndex === undefined ? findInitialQuestionIndex(nextSection, draftFiles) : questionIndex,
    );
    jumpToTop();
  }

  function jumpToFirstMissing() {
    const nextSectionIndex = findInitialSectionIndex(sections, draftFiles);
    jumpToSection(nextSectionIndex);
  }

  function nextPrompt() {
    if (!activeSection) {
      return;
    }
    if (safeQuestionIndex < activeSection.questions.length - 1) {
      setCurrentQuestionIndex(safeQuestionIndex + 1);
      jumpToTop();
      return;
    }
    if (currentSectionIndex < sections.length - 1) {
      jumpToSection(currentSectionIndex + 1);
    }
  }

  function previousPrompt() {
    if (!activeSection) {
      return;
    }
    if (safeQuestionIndex > 0) {
      setCurrentQuestionIndex(safeQuestionIndex - 1);
      jumpToTop();
      return;
    }
    if (currentSectionIndex > 0) {
      const previousSection = sections[currentSectionIndex - 1];
      jumpToSection(currentSectionIndex - 1, Math.max(previousSection.questions.length - 1, 0));
    }
  }

  function skipPrompt() {
    setStatus(
      activeClarification
        ? "Current prompt kept. Clarification skipped for now, and you can come back later."
        : "Prompt skipped for now. You can return from the sidebar later.",
    );
    setStatusTone("muted");
    nextPrompt();
  }

  function renderField() {
    if (!activeQuestion || !activeSnapshot) {
      return null;
    }

    if (activeQuestion.kind === "textarea") {
      return (
        <textarea
          className="area focus-input"
          value={activeSnapshot.displayValue}
          onChange={(event) => updateQuestion(activeQuestion, event.target.value)}
        />
      );
    }

    if (activeQuestion.kind === "text" || activeQuestion.kind === "tags") {
      return (
        <input
          className="field focus-input"
          value={activeSnapshot.displayValue}
          onChange={(event) => updateQuestion(activeQuestion, event.target.value)}
          placeholder={activeQuestion.kind === "tags" ? "trip, work order, dispatch" : "Type the answer"}
        />
      );
    }

    if (activeQuestion.kind === "boolean") {
      const currentValue = typeof activeSnapshot.effectiveValue === "boolean" ? activeSnapshot.effectiveValue : null;
      return (
        <div className="choice-grid boolean-grid">
          {[true, false].map((choice) => (
            <button
              className={`choice-pill ${currentValue === choice ? "active" : ""}`}
              key={String(choice)}
              type="button"
              onClick={() => updateQuestion(activeQuestion, choice)}
            >
              {choice ? "Yes" : "No"}
            </button>
          ))}
        </div>
      );
    }

    if (activeQuestion.kind === "select") {
      return (
        <select
          className="select focus-input"
          value={activeSnapshot.displayValue}
          onChange={(event) => updateQuestion(activeQuestion, event.target.value)}
        >
          <option value="">Select an option</option>
          {choiceOptions.map((choice) => (
            <option key={choice.value} value={choice.value}>
              {choice.label}
            </option>
          ))}
        </select>
      );
    }

    if (activeQuestion.kind === "table-column-select") {
      return (
        <select
          className="select focus-input"
          value={activeSnapshot.displayValue}
          onChange={(event) => updateQuestion(activeQuestion, event.target.value)}
        >
          <option value="">Select table.column</option>
          {(activeQuestion.choices || []).map((choice) => (
            <optgroup key={choice.table_name || String(choice.label || "")} label={choice.table_name || "table"}>
              {(choice.columns || []).map((column) => {
                const value = `${choice.table_name || ""}.${column}`;
                return (
                  <option key={value} value={value}>
                    {value}
                  </option>
                );
              })}
            </optgroup>
          ))}
        </select>
      );
    }

    return (
      <input
        className="field focus-input"
        value={activeSnapshot.displayValue}
        onChange={(event) => updateQuestion(activeQuestion, event.target.value)}
      />
    );
  }

  function renderClarificationField() {
    if (!activeClarification || !activeClarificationSnapshot) {
      return null;
    }

    if (activeClarification.kind === "tags") {
      return (
        <input
          className="field focus-input"
          value={activeClarificationSnapshot.displayValue}
          onChange={(event) => updateQuestion(activeClarification, event.target.value)}
          placeholder="driver, technician, operator"
        />
      );
    }

    if (activeClarification.kind === "select") {
      return (
        <select
          className="select focus-input"
          value={activeClarificationSnapshot.displayValue}
          onChange={(event) => updateQuestion(activeClarification, event.target.value)}
        >
          <option value="">Select an option</option>
          {clarificationChoiceOptions.map((choice) => (
            <option key={choice.value} value={choice.value}>
              {choice.label}
            </option>
          ))}
        </select>
      );
    }

    if (activeClarification.kind === "table-column-select") {
      return (
        <select
          className="select focus-input"
          value={activeClarificationSnapshot.displayValue}
          onChange={(event) => updateQuestion(activeClarification, event.target.value)}
        >
          <option value="">Select table.column</option>
          {(activeClarification.choices || []).map((choice) => (
            <optgroup key={choice.table_name || String(choice.label || "")} label={choice.table_name || "table"}>
              {(choice.columns || []).map((column) => {
                const value = `${choice.table_name || ""}.${column}`;
                return (
                  <option key={value} value={value}>
                    {value}
                  </option>
                );
              })}
            </optgroup>
          ))}
        </select>
      );
    }

    return (
      <input
        className="field focus-input"
        value={activeClarificationSnapshot.displayValue}
        onChange={(event) => updateQuestion(activeClarification, event.target.value)}
      />
    );
  }

  const activeAnswerValue =
    activeQuestion && activeSnapshot && !activeSnapshot.isMissing
      ? formatValue(activeQuestion.kind, activeSnapshot.effectiveValue)
      : "";

  const pendingInputMode = activeClarification
    ? "clarification"
    : activeQuestion && activeSnapshot?.isMissing
      ? "answer"
      : "none";
  const languageSummary = [
    sectionSummaryMap.get("domain-purpose"),
    sectionSummaryMap.get("table-roles"),
    sectionSummaryMap.get("business-language"),
  ].filter(Boolean) as SectionSummary[];
  const rulesSummary = [
    sectionSummaryMap.get("review-hints"),
    sectionSummaryMap.get("business-rules"),
    sectionSummaryMap.get("enum-meaning"),
    sectionSummaryMap.get("relationships"),
  ].filter(Boolean) as SectionSummary[];
  const examplesSummary = [sectionSummaryMap.get("query-patterns")].filter(Boolean) as SectionSummary[];

  function summarizeGroup(items: SectionSummary[]) {
    return items.reduce(
      (accumulator, item) => ({
        total: accumulator.total + item.total,
        answered: accumulator.answered + item.answered,
        missing: accumulator.missing + item.missing,
      }),
      { total: 0, answered: 0, missing: 0 },
    );
  }

  const languageProgress = summarizeGroup(languageSummary);
  const rulesProgress = summarizeGroup(rulesSummary);
  const examplesProgress = summarizeGroup(examplesSummary);
  const diagramSteps = [
    {
      title: "Inspect schema",
      detail: `${discoveredTableCount} tables discovered from ${sourceName}`,
      state: "done",
    },
    {
      title: "Name the business language",
      detail: `${languageProgress.answered}/${languageProgress.total} answers reviewed`,
      state:
        activeSection && ["domain-purpose", "table-roles", "business-language"].includes(activeSection.id)
          ? "active"
          : languageProgress.missing === 0
            ? "done"
            : "pending",
    },
    {
      title: "Define rules and meanings",
      detail: `${rulesProgress.answered}/${rulesProgress.total} clarified`,
      state:
        activeSection && ["review-hints", "business-rules", "enum-meaning", "relationships"].includes(activeSection.id)
          ? "active"
          : rulesProgress.missing === 0
            ? "done"
            : "pending",
    },
    {
      title: "Capture real questions",
      detail: `${examplesProgress.answered}/${examplesProgress.total} example prompts reviewed`,
      state:
        activeSection?.id === "query-patterns"
          ? "active"
          : examplesProgress.missing === 0
            ? "done"
            : "pending",
    },
    {
      title: "Export and publish",
      detail: `ZIP + TAG publish to ${domainName || sourceName}`,
      state: missingQuestions === 0 ? "active" : "pending",
    },
  ] as const;
  const canContinue =
    pendingInputMode === "none" ||
    (pendingInputMode === "answer" ? Boolean(activeSnapshot && !activeSnapshot.isMissing) : false) ||
    (pendingInputMode === "clarification" &&
      Boolean(activeClarificationSnapshot && !activeClarificationSnapshot.isMissing));

  return (
    <div className="wizard-layout chat-layout">
      <div className="panel stack chat-canvas">
        {discoveredTableCount === 0 ? (
          <section className="section-card notice-block">
            <span className="pill">Schema Issue</span>
            <h3>No tables were discovered for this source.</h3>
            <p>
              This usually means the DB URL could connect partially but schema introspection failed,
              or the selected database is empty. Re-run onboarding after fixing credentials, MySQL
              auth support, or database permissions.
            </p>
          </section>
        ) : null}

        <section className="section-card chat-hero-card">
          <div className="chat-hero-top">
            <div className="stack chat-hero-copy">
              <span className="pill">Onboarding Chat</span>
              <h2>{domainName || sourceName}</h2>
              <p>
                Answer naturally. I will ground each reply into the semantic bundle, explain the
                interpretation, and only ask a follow-up when the schema needs precision.
              </p>
            </div>
            <div className="chat-hero-stats">
              <div className="hero-stat">
                <strong>{completionPercent}%</strong>
                <span>bundle reviewed</span>
              </div>
              <div className="hero-stat">
                <strong>{answeredQuestions}</strong>
                <span>answers confirmed</span>
              </div>
              <div className="hero-stat">
                <strong>{missingQuestions}</strong>
                <span>still open</span>
              </div>
            </div>
          </div>
          <div className="chat-hero-progress">
            <div className="progress-track" aria-hidden="true">
              <div className="progress-fill" style={{ width: `${completionPercent}%` }} />
            </div>
            <div className="chat-hero-inline">
              <div className="chat-topic-chip">
                <span className="chat-topic-label">Current topic</span>
                <strong>{activeSection?.title || "Guided Interview"}</strong>
                {activeSectionSummary ? (
                  <span>
                    {activeSectionSummary.answered}/{activeSectionSummary.total} reviewed
                  </span>
                ) : null}
              </div>
              <button className="btn btn-secondary" disabled={isPending} onClick={jumpToFirstMissing} type="button">
                Resume From Next Gap
              </button>
            </div>
          </div>
          <div className={`status hero-status ${statusTone === "success" ? "success" : statusTone === "error" ? "error" : ""}`}>
            {status ||
              `${discoveredTableCount} tables are loaded. Keep replying here and export only when the business truth looks right.`}
          </div>
        </section>

        <section className="section-card journey-card compact-journey-card">
          <div className="stack conversation-intro-copy">
            <span className="pill">Bundle Flow</span>
            <h3>What this chat is building in the background</h3>
          </div>
          <div className="journey-diagram journey-strip">
            {diagramSteps.map((step, index) => (
              <div className={`journey-node ${step.state}`} key={step.title}>
                <span className="journey-index">0{index + 1}</span>
                <strong>{step.title}</strong>
                <span>{step.detail}</span>
              </div>
            ))}
          </div>
        </section>

        {activeQuestion && activeSnapshot ? (
          <section className="section-card thread-card chat-thread-card">
            <div className="thread">
              {recentHistory.length ? (
                <div className="history-thread">
                  <div className="history-thread-header">
                    <span className="pill">Recent Context</span>
                    <span className="hint">Only the latest confirmed replies stay in view</span>
                  </div>
                  {recentHistory.map((entry) => (
                    <div className="history-pair" key={entry.id}>
                      <div className="bubble bubble-history-assistant">
                        <span className="bubble-label">{entry.sectionTitle}</span>
                        <strong>{entry.label}</strong>
                      </div>
                      <div className="bubble bubble-history-user">
                        <span className="bubble-label">You</span>
                        <p className="user-answer">{entry.answer}</p>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="assistant-note">
                  <span className="pill">Start Here</span>
                  <p>
                    Reply naturally. I will capture the answer, explain what it means for TAG, and
                    ask one follow-up only when the schema needs more precision.
                  </p>
                </div>
              )}

              <div className="bubble bubble-assistant">
                <span className="bubble-label">Assistant</span>
                <strong>{activeQuestion.label}</strong>
                <p>{questionInputHint(activeQuestion)}</p>

                {!activeSnapshot.hasStoredValue && !isValueBlank(activeQuestion.suggested_answer) ? (
                  <div className="suggestion-card">
                    <div className="stack suggestion-copy">
                      <span className="pill">Schema suggestion</span>
                      <strong>{formatValue(activeQuestion.kind, activeQuestion.suggested_answer)}</strong>
                    </div>
                    <button className="btn btn-secondary" type="button" onClick={applySuggestedAnswer}>
                      Use Suggestion
                    </button>
                  </div>
                ) : null}

                <details className="evidence-panel bubble-evidence">
                  <summary>Why I am asking this</summary>
                  <ul className="evidence-list">
                    {(activeQuestion.evidence || []).length ? (
                      activeQuestion.evidence?.map((item) => <li key={item}>{item}</li>)
                    ) : (
                      <li>This prompt is here because the bundle still needs a human-approved business answer.</li>
                    )}
                  </ul>
                </details>
              </div>

              {!activeSnapshot.isMissing ? (
                <div className="bubble bubble-user">
                  <span className="bubble-label">You answered</span>
                  <p className="user-answer">{activeAnswerValue}</p>
                </div>
              ) : null}

              {answerInterpretation ? (
                <div className="bubble bubble-system">
                  <span className="bubble-label">I processed that as</span>
                  <strong>{answerInterpretation.title}</strong>
                  <p>{answerInterpretation.body}</p>
                  {answerInterpretation.bullets.length ? (
                    <ul className="evidence-list interpretation-list">
                      {answerInterpretation.bullets.map((item) => (
                        <li key={item}>{item}</li>
                      ))}
                    </ul>
                  ) : null}
                </div>
              ) : null}

              {activeClarification && activeClarificationSnapshot ? (
                <div className="bubble bubble-assistant clarify-bubble">
                  <span className="bubble-label">One clarification before I continue</span>
                  <strong>{activeClarification.label}</strong>
                  {activeClarification.description ? (
                    <p className="clarify-description">{activeClarification.description}</p>
                  ) : null}

                  {activeClarification.suggested_answer !== undefined &&
                  !isValueBlank(activeClarification.suggested_answer) &&
                  activeClarificationSnapshot.hasStoredValue === false ? (
                    <div className="suggestion-card">
                      <div className="stack suggestion-copy">
                        <span className="pill">Schema suggestion</span>
                        <strong>{formatValue(activeClarification.kind, activeClarification.suggested_answer)}</strong>
                      </div>
                      <button
                        className="btn btn-secondary"
                        type="button"
                        onClick={() => writeQuestionValue(activeClarification, deepClone(activeClarification.suggested_answer))}
                      >
                        Use Suggestion
                      </button>
                    </div>
                  ) : null}

                  <details className="evidence-panel clarify-evidence">
                    <summary>How I generated this follow-up</summary>
                    <ul className="evidence-list">
                      {(activeClarification.evidence || []).length ? (
                        activeClarification.evidence?.map((item) => <li key={item}>{item}</li>)
                      ) : (
                        <li>This clarification was generated from your answer and the current schema draft.</li>
                      )}
                    </ul>
                  </details>
                </div>
              ) : null}

              <div className="section-card composer-card">
                <div className="stack">
                  <span className="pill">
                    {pendingInputMode === "clarification"
                      ? "Your clarification"
                      : pendingInputMode === "answer"
                        ? "Your answer"
                        : "Ready to continue"}
                  </span>
                  <h4 className="composer-title">
                    {pendingInputMode === "clarification"
                      ? "Confirm the follow-up detail"
                      : pendingInputMode === "answer"
                        ? "Reply to the assistant"
                        : "This reply is grounded enough"}
                  </h4>
                  <p className="hint">
                    {pendingInputMode === "clarification"
                      ? questionInputHint(activeClarification!)
                      : pendingInputMode === "answer"
                        ? questionInputHint(activeQuestion)
                        : "Save and continue when the current interpretation looks right."}
                  </p>
                </div>

                {pendingInputMode === "clarification" ? renderClarificationField() : null}
                {pendingInputMode === "answer" ? renderField() : null}

                {pendingInputMode === "answer" && activeQuestion.kind === "tags" && tagSuggestions.length ? (
                  <div className="assist-panel">
                    <span className="assist-label">Quick add</span>
                    <div className="assist-chip-row">
                      {tagSuggestions.map((tag) => (
                        <button className="assist-chip" key={tag} type="button" onClick={() => addTagSuggestion(tag)}>
                          {tag}
                        </button>
                      ))}
                    </div>
                  </div>
                ) : null}

                {pendingInputMode === "none" ? (
                  <div className="conversation-note">
                    I have enough context to move on. Save and continue when the interpretation above matches the business truth.
                  </div>
                ) : null}
              </div>
            </div>
          </section>
        ) : (
          <section className="section-card empty-state">
            <strong>No prompts found for this step.</strong>
            <span>Rebuild suggestions if this source has changed.</span>
          </section>
        )}

        <div className="section-card wizard-footer-nav conversation-footer">
          <div className="button-row">
            <button className="btn btn-secondary" disabled={isPending || (currentSectionIndex === 0 && safeQuestionIndex === 0)} onClick={previousPrompt} type="button">
              Back
            </button>
            <button className="btn btn-secondary" disabled={isPending} onClick={skipPrompt} type="button">
              Skip
            </button>
          </div>
          <div className="button-row">
            <button className="btn btn-secondary" disabled={isPending} onClick={saveAll} type="button">
              Save
            </button>
            <button
              className="btn btn-primary"
              disabled={isPending || !canContinue || (!activeSection && currentSectionIndex >= sections.length - 1)}
              onClick={nextPrompt}
              type="button"
            >
              {activeClarification
                ? "Continue"
                : currentSectionIndex === sections.length - 1 &&
                    safeQuestionIndex === (activeSection?.questions.length || 1) - 1
                  ? "Finish"
                  : "Continue"}
            </button>
          </div>
        </div>

        <details className="section-card workspace-drawer">
          <summary>Workspace, export, and advanced controls</summary>
          <div className="workspace-drawer-grid">
            <div className="stack">
              <span className="pill">Publish Target</span>
              <label htmlFor="domainName">TAG domain folder</label>
              <input
                id="domainName"
                className="field"
                value={domainName}
                onChange={(event) => {
                  const nextDomainName = event.target.value;
                  setDomainName(nextDomainName);
                  setDraftFiles((current) => updateDomainNameInFiles(current, nextDomainName));
                }}
              />
            </div>
            <div className="stack workspace-actions">
              <button className="btn btn-primary btn-block" disabled={isPending} onClick={saveAll} type="button">
                Save Draft
              </button>
              <button className="btn btn-secondary btn-block" disabled={isPending} onClick={publish} type="button">
                Publish To TAG
              </button>
              <button className="btn btn-secondary btn-block" disabled={isPending} onClick={rebuild} type="button">
                Rebuild Suggestions
              </button>
              <a className="btn btn-secondary btn-block" href={downloadUrl}>
                Download JSON ZIP
              </a>
            </div>
          </div>

          <details className="section-card review-map inline-drawer">
            <summary>Question map</summary>
            <p className="hint">Open only when you want to jump to a different onboarding area.</p>
            <div className="section-nav">
              {sectionSummaries.map((section, index) => (
                <button
                  className={`section-nav-item ${index === currentSectionIndex ? "active" : ""}`}
                  key={section.id}
                  type="button"
                  onClick={() => jumpToSection(index)}
                >
                  <div className="section-nav-copy">
                    <strong>{section.title}</strong>
                    <span>
                      {section.missing > 0
                        ? `${section.missing} gap${section.missing === 1 ? "" : "s"} left`
                        : "Reviewed"}
                    </span>
                  </div>
                  <span className={`section-nav-count ${section.missing === 0 ? "complete" : ""}`}>
                    {section.answered}/{section.total}
                  </span>
                </button>
              ))}
            </div>
          </details>

          <details className="section-card preview-details inline-drawer">
            <summary>Bundle preview</summary>
            <p className="hint">This is the JSON that will be saved and zipped from the current draft.</p>
            <pre className="code-box">{preview}</pre>
          </details>
        </details>
      </div>
    </div>
  );
}
