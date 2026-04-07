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
  | "glossary_term_missing"
  | "relationship_role_unclear"
  | "other";

export type SemanticGap = {
  gap_id: string;
  category: GapCategory;
  target_entity?: string;
  target_property?: string;
  description: string;
  suggested_question?: string;
  is_blocking: boolean;
  priority: number;
};

export type ReadinessState = {
  is_ready: boolean;
  readiness_percentage: number;
  blocking_gaps_count: number;
  total_gaps_count: number;
  readiness_notes: string[];
};

export type KnowledgeState = {
  source_name: string;
  tables: Record<string, SemanticTable>;
  canonical_entities: Record<string, unknown>;
  enums: Record<string, EnumMapping[]>;
  business_rules: unknown[];
  glossary: Record<string, unknown>;
  query_patterns: unknown[];
  unresolved_gaps: SemanticGap[];
  readiness: ReadinessState;
};

export type UrlOnboardingResponse = {
  status: string;
  source_name: string;
  output_dir: string;
  wizard_url: string;
};

export type GeneratedQuestion = {
  gap_id: string;
  question: string;
  context: string;
  evidence: string[];
  input_type: string;
  choices: string[];
  suggested_answer?: string;
};

export type SourceSummary = {
  name: string;
  db_type?: string;
  database_name?: string;
  domain?: string;
  status?: string;
};
