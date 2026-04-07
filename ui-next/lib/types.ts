export type SourceSummary = {
  name: string;
  db_type?: string;
  database_name?: string;
  domain?: string;
  status?: string;
};

export type BundleResponse = {
  source_name: string;
  bundle_dir: string;
  files: Record<string, Record<string, unknown>>;
};

export type QuestionChoice = {
  label?: string;
  hint?: string;
  table_name?: string;
  columns?: string[];
};

export type QuestionItem = {
  id: string;
  label: string;
  kind: string;
  bundle_file?: string;
  field_path?: Array<string | number>;
  suggested_answer?: unknown;
  evidence?: string[];
  choices?: QuestionChoice[];
};

export type QuestionSection = {
  id: string;
  title: string;
  description?: string;
  questions: QuestionItem[];
};

export type QuestionsResponse = {
  source_name: string;
  sections: QuestionSection[];
};

export type UrlOnboardingResponse = {
  status: string;
  source_name: string;
  output_dir: string;
  bundle_dir: string;
  wizard_url: string;
  api_wizard_url: string;
  download_url: string;
};
