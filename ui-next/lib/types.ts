export type DiscoverySource =
  | "pulled_from_db_schema"
  | "inferred_by_system"
  | "confirmed_by_user"
  | "provided_by_user";

export type SourceAttribution = {
  source: DiscoverySource;
  user?: string;
  timestamp?: string;
  rationale?: string;
  tooling_notes?: string;
};

export type ConfidenceLabel = "high" | "medium" | "low";

export type NamedConfidence = {
  label: ConfidenceLabel;
  score: number;
  rationale: string[];
};

export type SensitivityLabel = "none" | "possible_sensitive" | "sensitive";

export type SemanticColumn = {
  column_name: string;
  technical_type: string;
  business_meaning?: string;
  example_values: string[];
  synonyms: string[];
  filterable: boolean;
  displayable: boolean;
  sensitive: SensitivityLabel;
  confidence: NamedConfidence;
  attribution: SourceAttribution;
};

export type SemanticTable = {
  table_name: string;
  business_meaning?: string;
  grain?: string;
  likely_entity?: string;
  important_columns: string[];
  valid_joins: string[];
  common_filters: string[];
  common_business_questions: string[];
  sensitivity_notes: string[];
  confidence: NamedConfidence;
  attribution: SourceAttribution;
  columns: SemanticColumn[];
};

export type EnumMapping = {
  database_value: string;
  business_label: string;
  description?: string;
  attribution: SourceAttribution;
};

export type GapCategory =
  | "missing_primary_key"
  | "ambiguous_relationship"
  | "unknown_business_meaning"
  | "unconfirmed_enum_mapping"
  | "potential_sensitivity"
  | "other";

export type SemanticGap = {
  gap_id: string;
  category: GapCategory;
  target_entity?: string;
  target_property?: string;
  description: string;
  suggested_question?: string;
  is_blocking: boolean;
};

export type ReadinessState = {
  is_ready: boolean;
  readiness_percentage: number;
  blocking_gaps_count: number;
  total_gaps_count: number;
  readiness_notes: string[];
};

export type KnowledgeState = {
  tables: Record<string, SemanticTable>;
  canonical_entities: Record<string, unknown>; // Placeholder for Phase 2 implementation detail
  enums: Record<string, EnumMapping[]>;
  business_rules: unknown[];
  glossary: Record<string, unknown>;
  query_patterns: unknown[];
  unresolved_gaps: SemanticGap[];
  readiness: ReadinessState;
};

// Existing types for the Shell/Form (can be removed later if not needed)
export type SourceSummary = {
  name: string;
  db_type?: string;
  database_name?: string;
  domain?: string;
  status?: string;
};
