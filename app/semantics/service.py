from __future__ import annotations

from collections import defaultdict

from app.models.common import ConfidenceLabel, NamedConfidence, SensitivityLabel
from app.models.normalized import NormalizedColumn, NormalizedSource, NormalizedTable
from app.models.semantic import (
    CanonicalEntity,
    GlossaryTerm,
    QueryPattern,
    SemanticColumn,
    SemanticSourceModel,
    SemanticTable,
)
from app.utils.text import snake_to_words, tokenize, unique_non_empty


DOMAIN_RULES = {
    "maintenance": {"maintenance", "facility", "asset", "scheduler", "task", "technician"},
    "fleet_operations": {"trip", "vehicle", "driver", "tracking", "lock", "econtroller", "dispatch"},
    "inventory_supply_chain": {"purchase", "delivery", "vendor", "component", "stock", "assembly", "bom"},
    "billing_finance": {"invoice", "billing", "currency", "tax", "bank"},
    "platform_ops": {"user", "role", "privilege", "api", "notification", "session"},
}


class SemanticGuessService:
    def enrich(self, normalized: NormalizedSource) -> SemanticSourceModel:
        domain, domain_confidence = self._guess_domain(normalized)
        tables = [self._semantic_table(table) for table in normalized.tables]
        glossary = self._glossary_terms(domain, tables)
        canonical_entities = self._canonical_entities(tables)
        query_patterns = self._query_patterns(tables)

        key_entities = [entity.entity_name for entity in canonical_entities[:8]]
        sensitive_areas = unique_non_empty(
            [table.table_name for table in tables if table.sensitivity_notes]
        )

        return SemanticSourceModel(
            source_name=normalized.source_name,
            db_type=normalized.db_type,
            domain=domain,
            description=f"{normalized.source_name} appears to support {domain.replace('_', ' ')} workflows.",
            key_entities=key_entities,
            sensitive_areas=sensitive_areas,
            approved_use_cases=[
                "business question answering",
                "metadata onboarding",
                "safe NL2SQL grounding",
            ],
            tables=tables,
            glossary=glossary,
            canonical_entities=canonical_entities,
            query_patterns=query_patterns,
        )

    def _guess_domain(self, normalized: NormalizedSource) -> tuple[str, NamedConfidence]:
        token_pool = set(tokenize(normalized.source_name))
        for table in normalized.tables:
            token_pool.update(table.tokens)

        best_domain = "operations"
        best_score = 0.2
        reasons: list[str] = ["default operational domain"]
        for domain, keywords in DOMAIN_RULES.items():
            overlap = token_pool & keywords
            if not overlap:
                continue
            score = 0.3 + 0.1 * len(overlap)
            if score > best_score:
                best_domain = domain
                best_score = min(score, 0.95)
                reasons = [f"matched keywords: {', '.join(sorted(overlap))}"]

        return best_domain, self._confidence(best_score, reasons)

    def _semantic_table(self, table: NormalizedTable) -> SemanticTable:
        meaning, confidence = self._table_meaning(table)
        columns = [self._semantic_column(table, column) for column in table.columns]
        important_columns = unique_non_empty(
            [
                *table.primary_key,
                *[
                    column.column_name
                    for column in table.columns
                    if column.is_status_like or column.is_timestamp_like or "name" in column.column_name
                ],
            ]
        )[:10]
        valid_joins = table.join_candidates[:8]
        common_filters = table.filters[:8]
        sensitivity_notes = unique_non_empty(
            [
                f"{column.column_name}: {', '.join(column.sensitivity_hints)}"
                for column in table.columns
                if column.sensitivity_hints
            ]
        )
        return SemanticTable(
            table_name=table.table_name,
            business_meaning=meaning,
            grain=table.grain_hint,
            likely_entity=table.entity_hint,
            important_columns=important_columns,
            valid_joins=valid_joins,
            common_filters=common_filters,
            common_business_questions=self._business_questions(table),
            sensitivity_notes=sensitivity_notes,
            confidence=confidence,
            columns=columns,
        )

    def _semantic_column(self, table: NormalizedTable, column: NormalizedColumn) -> SemanticColumn:
        meaning, confidence = self._column_meaning(table, column)
        sensitive = (
            SensitivityLabel.sensitive
            if any("secret" in hint or "token" in hint for hint in column.sensitivity_hints)
            else SensitivityLabel.possible_sensitive
            if column.sensitivity_hints
            else SensitivityLabel.none
        )
        synonyms = unique_non_empty(
            [
                snake_to_words(column.column_name),
                column.column_name.replace("_", " "),
                table.entity_hint or "",
            ]
        )[:4]
        displayable = sensitive == SensitivityLabel.none
        filterable = not any(token in column.technical_type.lower() for token in ("blob", "text"))
        return SemanticColumn(
            column_name=column.column_name,
            technical_type=column.technical_type,
            business_meaning=meaning,
            example_values=column.sample_values[:5],
            synonyms=synonyms,
            filterable=filterable,
            displayable=displayable,
            sensitive=sensitive,
            confidence=confidence,
        )

    def _table_meaning(self, table: NormalizedTable) -> tuple[str, NamedConfidence]:
        reasons: list[str] = []
        score = 0.45
        name = table.table_name
        if name.endswith("_mapping"):
            reasons.append("mapping suffix")
            score = 0.85
            return (
                f"Relationship mapping records for {snake_to_words(name.replace('_mapping', ''))}.",
                self._confidence(score, reasons),
            )
        if name.endswith("_history") or name.endswith("_log"):
            reasons.append("history/log suffix")
            score = 0.85
            return (
                f"Historical event records for {snake_to_words(name.replace('_history', '').replace('_log', ''))}.",
                self._confidence(score, reasons),
            )
        if name.endswith("_detail") or name.endswith("_details"):
            reasons.append("detail suffix")
            score = 0.7
            return (
                f"Detailed records associated with {snake_to_words(name.replace('_details', '').replace('_detail', ''))}.",
                self._confidence(score, reasons),
            )
        if table.row_count and table.row_count > 10_000:
            reasons.append("high row count suggests transactional or master usage")
            score += 0.15
        if any(token in table.tokens for token in {"status", "state", "transaction"}):
            reasons.append("name suggests process lifecycle")
            score += 0.1
        return (
            f"Primary records for {snake_to_words(name)}.",
            self._confidence(min(score, 0.9), reasons or ["generic table naming"]),
        )

    def _column_meaning(self, table: NormalizedTable, column: NormalizedColumn) -> tuple[str, NamedConfidence]:
        name = column.column_name.lower()
        reasons: list[str] = []
        score = 0.45
        if column.is_primary_key:
            return (
                f"Unique identifier for each {snake_to_words(table.table_name.rstrip('s'))}.",
                self._confidence(0.95, ["primary key"]),
            )
        if column.is_foreign_key:
            score = 0.85
            reasons.append("foreign key")
            return (
                f"Reference to a related {snake_to_words(column.column_name.replace('_id', ''))}.",
                self._confidence(score, reasons),
            )
        if "status" in name or "state" in name:
            return (
                "Lifecycle or workflow status for the record.",
                self._confidence(0.9, ["status/state naming"]),
            )
        if "type" in name or "category" in name:
            return (
                "Classification or category for the record.",
                self._confidence(0.8, ["type/category naming"]),
            )
        if "created" in name or "updated" in name or column.is_timestamp_like:
            return (
                "Timestamp used for audit, freshness, or trend analysis.",
                self._confidence(0.85, ["timestamp-like naming"]),
            )
        if "name" in name:
            score = 0.8
            reasons.append("name field")
            return ("Human-readable name or label.", self._confidence(score, reasons))
        if column.sample_values and len(column.sample_values) <= 5:
            reasons.append("sample values available")
            score += 0.15
        return (
            f"Business attribute for {snake_to_words(table.table_name)} related to {snake_to_words(column.column_name)}.",
            self._confidence(min(score, 0.8), reasons or ["generic naming"]),
        )

    def _business_questions(self, table: NormalizedTable) -> list[str]:
        singular = snake_to_words(table.table_name.rstrip("s"))
        questions = [
            f"How many {singular} records exist?",
            f"What are the most recent {singular} records?",
        ]
        if any(column.is_status_like for column in table.columns):
            questions.append(f"What is the status breakdown for {singular} records?")
        if any(column.is_timestamp_like for column in table.columns):
            questions.append(f"How has {singular} volume changed over time?")
        if table.join_candidates:
            questions.append(f"How do {singular} records relate to adjacent entities?")
        return questions[:5]

    def _glossary_terms(self, domain: str, tables: list[SemanticTable]) -> list[GlossaryTerm]:
        terms: list[GlossaryTerm] = [
            GlossaryTerm(
                term=domain.replace("_", " "),
                meaning=f"Operational domain inferred from schema structure for {domain.replace('_', ' ')}.",
            )
        ]
        for table in tables[:20]:
            terms.append(
                GlossaryTerm(
                    term=snake_to_words(table.table_name),
                    meaning=table.business_meaning or "",
                    synonyms=[table.likely_entity or ""],
                    related_tables=[table.table_name],
                    related_columns=[column.column_name for column in table.columns[:5]],
                )
            )
        return terms

    def _canonical_entities(self, tables: list[SemanticTable]) -> list[CanonicalEntity]:
        grouped: dict[str, list[SemanticTable]] = defaultdict(list)
        for table in tables:
            if table.likely_entity:
                grouped[table.likely_entity].append(table)
        entities: list[CanonicalEntity] = []
        for entity_name, entity_tables in grouped.items():
            entities.append(
                CanonicalEntity(
                    entity_name=entity_name,
                    description=f"Canonical entity spanning {len(entity_tables)} related table(s).",
                    mapped_source_tables=[table.table_name for table in entity_tables],
                    mapped_columns=[
                        f"{table.table_name}.{column.column_name}"
                        for table in entity_tables
                        for column in table.columns[:3]
                    ][:12],
                    confidence=self._confidence(
                        min(0.55 + 0.1 * len(entity_tables), 0.9),
                        ["derived from table naming overlap"],
                    ),
                )
            )
        entities.sort(key=lambda item: item.confidence.score, reverse=True)
        return entities

    def _query_patterns(self, tables: list[SemanticTable]) -> list[QueryPattern]:
        patterns: list[QueryPattern] = []
        for table in tables[:12]:
            singular = snake_to_words(table.table_name.rstrip("s"))
            patterns.append(
                QueryPattern(
                    intent=f"{singular}_summary",
                    question_examples=[
                        f"Show me a summary of {singular} records",
                        f"How many {singular} records are there?",
                    ],
                    preferred_tables=[table.table_name],
                    required_joins=table.valid_joins[:3],
                    safe_filters=table.common_filters[:4],
                    optional_sql_template=(
                        f"SELECT COUNT(*) AS total_records FROM {table.table_name}"
                    ),
                    rendering_guidance="Default to counts, recent records, and status breakdowns before raw detail dumps.",
                )
            )
        return patterns

    def _confidence(self, score: float, reasons: list[str]) -> NamedConfidence:
        if score >= 0.8:
            label = ConfidenceLabel.high
        elif score >= 0.55:
            label = ConfidenceLabel.medium
        else:
            label = ConfidenceLabel.low
        return NamedConfidence(label=label, score=round(score, 2), rationale=reasons)

