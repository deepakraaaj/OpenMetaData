"use client";

import { KnowledgeState, EnumMapping } from "../lib/types";

const BOOLEAN_LIKE_VALUES = new Set([
  "0",
  "1",
  "y",
  "n",
  "yes",
  "no",
  "true",
  "false",
  "on",
  "off",
  "enabled",
  "disabled",
  "active",
  "inactive",
]);

const BUSINESS_ENUM_TOKENS = [
  "status",
  "state",
  "phase",
  "stage",
  "type",
  "category",
  "mode",
  "priority",
  "severity",
  "reason",
  "result",
];

const TECHNICAL_ENUM_NOISE_TOKENS = [
  "adc",
  "battery",
  "check_sum",
  "checksum",
  "current",
  "digital_input",
  "digital_output",
  "distance",
  "duration",
  "fan_invoice",
  "frame",
  "fuel",
  "gps",
  "gsm",
  "gprs",
  "ignition",
  "imei",
  "imsi",
  "input",
  "invoice_number",
  "kilometer",
  "kilometre",
  "latitude",
  "longitude",
  "meter",
  "meters",
  "mobile",
  "number",
  "odometer",
  "output",
  "packet",
  "phone",
  "plant_code",
  "power",
  "satellite",
  "seconds",
  "sequence",
  "signal",
  "speed",
  "temperature",
  "total",
  "voltage",
];

function normalizeValue(value: string): string {
  return String(value || "").trim().toLowerCase().replace(/\s+/g, " ");
}

const GENERIC_ENUM_GUESSES = new Set(
  [
    "Workflow or lifecycle status.",
    "Workflow or lifecycle status code.",
    "Priority or severity level.",
    "Type or category classification.",
    "Boolean or enable/disable flag.",
    "Type or status code used in business workflows.",
    "Lifecycle or workflow status for the record.",
    "Priority or severity level for the record.",
    "Classification or category for the record.",
    "Boolean or enable/disable flag for the record.",
  ].map(normalizeValue)
);

function hasBusinessEnumSignal(columnName: string): boolean {
  const normalizedName = normalizeValue(columnName);
  return BUSINESS_ENUM_TOKENS.some((token) => normalizedName.includes(token));
}

function filterMappings(mappings: EnumMapping[]): EnumMapping[] {
  return mappings.filter((mapping) => {
    const databaseValue = normalizeValue(mapping.database_value);
    const businessLabel = normalizeValue(mapping.business_label);
    return (
      databaseValue !== "" &&
      !GENERIC_ENUM_GUESSES.has(databaseValue) &&
      !GENERIC_ENUM_GUESSES.has(businessLabel)
    );
  });
}

function isTechnicalEnumNoise(columnName: string, mappings: EnumMapping[]): boolean {
  const normalizedName = normalizeValue(columnName);
  const values = mappings
    .map((mapping) => normalizeValue(mapping.database_value))
    .filter(Boolean);

  if (values.length === 0) {
    return false;
  }

  const allNumeric = values.every((value) => /^\d+$/.test(value));
  const booleanLike = values.every((value) => BOOLEAN_LIKE_VALUES.has(value));
  if (!allNumeric && !booleanLike) {
    return false;
  }

  return TECHNICAL_ENUM_NOISE_TOKENS.some((token) => normalizedName.includes(token));
}

function hasMeaningfulMappings(mappings: EnumMapping[]): boolean {
  return mappings.some((mapping) => {
    const databaseValue = normalizeValue(mapping.database_value);
    const businessLabel = normalizeValue(mapping.business_label);
    if (!databaseValue || !businessLabel) {
      return false;
    }
    return databaseValue !== businessLabel || mapping.database_value.trim() !== mapping.business_label.trim();
  });
}

function isReviewableEnumEntry(
  target: string,
  mappings: EnumMapping[],
  state: KnowledgeState
): boolean {
  const [tableName = "", columnName = ""] = target.split(".");
  if (!columnName) {
    return false;
  }
  if (columnName === "id" || columnName.endsWith("_id")) {
    return false;
  }

  const table = state.tables[tableName];
  if (table && !table.selected) {
    return false;
  }
  if (mappings.length === 0) {
    return false;
  }
  if (isTechnicalEnumNoise(columnName, mappings)) {
    return false;
  }

  return hasBusinessEnumSignal(columnName) || hasMeaningfulMappings(mappings);
}

export default function EnumReviewGrid({ state }: { state: KnowledgeState }) {
  const enumEntries = Object.entries(state.enums)
    .map(([target, mappings]) => [target, filterMappings(mappings)] as const)
    .filter(([target, mappings]) => isReviewableEnumEntry(target, mappings, state));

  return (
    <div className="stack" style={{ gap: '2rem' }}>
      <div className="hero" style={{ padding: '2rem 0', textAlign: 'left', margin: 0 }}>
        <span className="eyebrow">Step 4 — Review Enums</span>
        <h2>Confirm the business labels for discovered status codes.</h2>
      </div>

      <div className="card-grid" style={{ padding: 0 }}>
        {enumEntries.length === 0 ? (
          <div className="card" style={{ gap: '0.75rem' }}>
            <h3>No enum review needed</h3>
            <p style={{ margin: 0, color: 'var(--text-muted)' }}>
              Only business-facing status, type, category, and priority mappings are shown here.
            </p>
          </div>
        ) : (
          enumEntries.map(([target, mappings]) => {
            const [tableName = "", columnName = ""] = target.split(".");
            return (
              <div key={target} className="card" style={{ gap: '1rem' }}>
                <div className="stack">
                  <span className="pill">{tableName}</span>
                  <h3>Column: {columnName}</h3>
                </div>

                <div className="stack" style={{ gap: '0.75rem' }}>
                  {mappings.map((mapping) => (
                    <div
                      key={mapping.database_value}
                      style={{
                        display: 'grid',
                        gridTemplateColumns: '80px 1fr auto',
                        alignItems: 'center',
                        gap: '1rem',
                        padding: '0.75rem',
                        background: 'var(--bg-surface-alt)',
                        borderRadius: '8px'
                      }}
                    >
                      <code style={{ fontSize: '1rem', color: 'var(--accent)' }}>{mapping.database_value}</code>
                      <input
                        type="text"
                        defaultValue={mapping.business_label}
                        style={{ background: 'transparent', border: 'none', padding: 0 }}
                      />
                      <span className={`pill ${mapping.attribution.source === 'inferred_by_system' ? 'pill-warning' : 'pill-success'}`}>
                        {mapping.attribution.source === 'inferred_by_system' ? 'Inferred' : 'Confirmed'}
                      </span>
                    </div>
                  ))}
                </div>

                <div className="button-row" style={{ marginTop: 'auto' }}>
                  <button className="btn btn-outline" style={{ flex: 1 }}>Confirm All</button>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
