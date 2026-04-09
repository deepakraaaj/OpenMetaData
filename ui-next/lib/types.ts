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

export type TableRole =
  | "core_entity"
  | "transaction"
  | "lookup_master"
  | "mapping_bridge"
  | "log_event"
  | "history_audit"
  | "config_system"
  | "unknown";

export type TableReviewDecision = "selected" | "excluded" | "review";

export type BulkReviewAction =
  | "select_recommended"
  | "exclude_noise"
  | "include_lookup_tables"
  | "include_all";

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
  review_status: "pending" | "confirmed" | "skipped";
  domain?: string;
  role: TableRole;
  selected: boolean;
  recommended_selected: boolean;
  selected_by_default: boolean;
  review_decision: TableReviewDecision;
  needs_review: boolean;
  requires_review: boolean;
  business_meaning?: string;
  grain?: string;
  likely_entity?: string;
  important_columns: string[];
  valid_joins: string[];
  common_filters: string[];
  common_business_questions: string[];
  sensitivity_notes: string[];
  reason_for_classification?: string;
  classification_reason?: string;
  selection_reason?: string;
  review_reason?: string;
  related_tables: string[];
  impact_score: number;
  business_relevance: number;
  naming_clarity: number;
  graph_connectivity: number;
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
  question_type?: string;
  best_guess?: string;
  confidence?: number;
  evidence?: string[];
  candidate_options?: QuestionOption[];
  decision_prompt?: string;
  actions?: QuestionAction[];
  impact_score?: number;
  ambiguity_score?: number;
  business_relevance?: number;
  priority_score?: number;
  allow_free_text?: boolean;
  free_text_placeholder?: string;
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

export type TableSelectionSummary = {
  analyzed_table_count: number;
  selected_count: number;
  excluded_count: number;
  review_count: number;
  high_confidence_count: number;
  medium_confidence_count: number;
  low_confidence_count: number;
  detected_domains: string[];
};

export type DomainReviewGroup = {
  domain: string;
  tables: string[];
  core_tables: string[];
  anchor_tables: string[];
  selected_count: number;
  excluded_count: number;
  review_count: number;
  inferred_business_meaning?: string;
  requires_review: boolean;
  review_reason?: string;
  confidence: NamedConfidence;
};

export type ReviewQueueItem = {
  table_name: string;
  domain?: string;
  role: TableRole;
  confidence: NamedConfidence;
  selected: boolean;
  open_gap_count: number;
  reason_for_classification?: string;
  selection_reason?: string;
  review_reason?: string;
  impact_score: number;
  business_relevance: number;
  related_tables: string[];
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
  review_summary: TableSelectionSummary;
  domain_groups: DomainReviewGroup[];
  review_queue: ReviewQueueItem[];
};

export type OnboardingStage =
  | "connecting_to_database"
  | "reading_schema"
  | "extracting_relationships"
  | "building_semantic_model"
  | "generating_review_questions"
  | "ready_for_review";

export type OnboardingStepState = "pending" | "running" | "completed" | "error";

export type OnboardingJobState = "queued" | "running" | "completed" | "failed";

export type OnboardingProgressCounts = {
  schema_count?: number;
  table_count?: number;
  column_count?: number;
  foreign_key_count?: number;
  inferred_relationship_count?: number;
  review_item_count?: number;
  domain_group_count?: number;
  unresolved_gap_count?: number;
};

export type OnboardingStepStatus = {
  stage: OnboardingStage;
  label: string;
  state: OnboardingStepState;
  message?: string;
  started_at?: string;
  completed_at?: string;
};

export type OnboardingLogEntry = {
  timestamp: string;
  stage: OnboardingStage;
  level: "info" | "success" | "error";
  message: string;
};

export type OnboardingResult = {
  source_name: string;
  output_dir: string;
  bundle_dir: string;
  chatbot_package_dir: string;
  wizard_url: string;
  api_wizard_url: string;
  download_url: string;
  chatbot_package_url: string;
  chatbot_package_download_url: string;
  legacy_review_url: string;
};

export type OnboardingJobSnapshot = {
  job_id: string;
  source_name: string;
  status: OnboardingJobState;
  current_stage?: OnboardingStage;
  progress_percent: number;
  estimated_wait_message: string;
  counts: OnboardingProgressCounts;
  steps: OnboardingStepStatus[];
  logs: OnboardingLogEntry[];
  status_url: string;
  wizard_url: string;
  result?: OnboardingResult;
  error_message?: string;
  reused_existing_job?: boolean;
  created_at: string;
  updated_at: string;
  finished_at?: string;
};

export type BundleResponse = {
  source_name: string;
  bundle_dir: string;
  files: Record<string, unknown>;
};

export type ChatbotPackageManifest = {
  package_type: string;
  version: number;
  generated_at: string;
  source_name: string;
  domain_name: string;
  summary: {
    db_type?: string;
    database_name?: string;
    table_count?: number;
    key_entity_count?: number;
    question_count?: number;
    domain_group_count?: number;
  };
  entrypoints: Record<string, string>;
  next_steps: string[];
  inventory: string[];
};

export type ChatbotPackageResponse = {
  source_name: string;
  package_dir: string;
  manifest: ChatbotPackageManifest;
  overview_url: string;
  download_url: string;
};

export type QuestionsResponse = {
  source_name: string;
  sections: Array<Record<string, unknown>>;
};

export type QuestionOption = {
  value: string;
  label: string;
  description?: string;
  is_best_guess?: boolean;
  is_fallback?: boolean;
};

export type QuestionAction = {
  value: string;
  label: string;
};

export type GeneratedQuestion = {
  gap_id: string;
  question: string;
  context: string;
  evidence: string[];
  input_type: string;
  choices: string[];
  target_entity?: string;
  target_property?: string;
  suggested_answer?: string;
  question_type?: string;
  best_guess?: string;
  confidence?: number;
  candidate_options: QuestionOption[];
  decision_prompt?: string;
  actions: QuestionAction[];
  impact_score?: number;
  ambiguity_score?: number;
  business_relevance?: number;
  priority_score?: number;
  allow_free_text?: boolean;
  free_text_placeholder?: string;
};

export type SourceSummary = {
  name: string;
  db_type?: string;
  database_name?: string;
  domain?: string;
  status?: string;
};
