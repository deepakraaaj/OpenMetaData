import { KnowledgeState, SemanticTable, SourceAttribution } from "./types";

const defaultAttribution: SourceAttribution = {
  source: "pulled_from_db_schema",
  tooling_notes: "Discovered via SQLAlchemy inspector",
};

export const MOCK_KNOWLEDGE_STATE: KnowledgeState = {
  tables: {
    users: {
      table_name: "users",
      business_meaning: "Core table for registered platform users.",
      grain: "One row per user account",
      likely_entity: "User",
      important_columns: ["id", "email", "created_at"],
      valid_joins: ["orders", "user_profiles"],
      common_filters: ["active = true", "created_at > last_month"],
      common_business_questions: [
        "How many active users signed up in the last 30 days?",
        "Which users have not placed an order yet?",
      ],
      sensitivity_notes: ["Contains PII (email)"],
      confidence: { label: "high", score: 0.9, rationale: ["Validated by standard schema patterns"] },
      attribution: defaultAttribution,
      columns: [
        {
          column_name: "id",
          technical_type: "INTEGER",
          business_meaning: "Internal unique identifier for a user.",
          example_values: ["101", "102", "103"],
          synonyms: ["user_id", "uid"],
          filterable: true,
          displayable: true,
          sensitive: "none",
          confidence: { label: "high", score: 1.0, rationale: ["Primary key"] },
          attribution: defaultAttribution,
        },
        {
          column_name: "email",
          technical_type: "VARCHAR(255)",
          business_meaning: "Primary contact email address.",
          example_values: ["alice@example.com", "bob@work.com"],
          synonyms: ["login", "username"],
          filterable: true,
          displayable: true,
          sensitive: "sensitive",
          confidence: { label: "high", score: 0.95, rationale: ["Format match"] },
          attribution: { source: "inferred_by_system", rationale: "Detected via regex pattern matching" },
        },
      ],
    },
    orders: {
      table_name: "orders",
      business_meaning: "Transactional records for sales and subscriptions.",
      grain: "One row per line item purchase",
      important_columns: ["id", "user_id", "status", "amount"],
      valid_joins: ["users", "products"],
      common_filters: ["status = 'completed'", "amount > 0"],
      common_business_questions: ["What is the total revenue for this month?"],
      sensitivity_notes: [],
      confidence: { label: "medium", score: 0.7, rationale: ["Ambiguous mapping for 'status' codes"] },
      attribution: defaultAttribution,
      columns: [],
    },
  },
  canonical_entities: {},
  enums: {
    "orders.status": [
      { database_value: "0", business_label: "Pending", attribution: { source: "inferred_by_system" } },
      { database_value: "1", business_label: "Completed", attribution: { source: "inferred_by_system" } },
      { database_value: "2", business_label: "Cancelled", attribution: { source: "inferred_by_system" } },
    ],
  },
  business_rules: [],
  glossary: {},
  query_patterns: [],
  unresolved_gaps: [
    {
      gap_id: "gap-users-pk",
      category: "missing_primary_key",
      target_entity: "users",
      description: "Database schema does not explicitly define a primary key for 'users'.",
      suggested_question: "Should I treat 'id' as the unique primary key for the users table?",
      is_blocking: true,
    },
    {
      gap_id: "gap-orders-status",
      category: "unconfirmed_enum_mapping",
      target_entity: "orders",
      target_property: "status",
      description: "Found low-cardinality codes (0, 1, 2) in status column.",
      suggested_question: "Do these status codes map to Pending, Completed, and Cancelled?",
      is_blocking: false,
    },
  ],
  readiness: {
    is_ready: false,
    readiness_percentage: 65.0,
    blocking_gaps_count: 1,
    total_gaps_count: 2,
    readiness_notes: ["Missing primary key on core entity 'users' is blocking the semantic diagram generation."],
  },
};
