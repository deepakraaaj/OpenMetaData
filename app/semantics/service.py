from __future__ import annotations

from collections import defaultdict
import re

from app.core.inference_rules import SemanticInferenceRules, load_inference_rules
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


class SemanticGuessService:
    def __init__(self, rules: SemanticInferenceRules | None = None) -> None:
        self.rules = rules or load_inference_rules()

    def enrich(self, normalized: NormalizedSource) -> SemanticSourceModel:
        domain, domain_confidence = self._guess_domain(normalized)
        actor_table = self._actor_table_name(normalized.tables)
        tables = [self._semantic_table(table, actor_table) for table in normalized.tables]
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
        for domain, keywords in self.rules.domain_rules.items():
            keyword_set = set(keywords)
            overlap = token_pool & keyword_set
            if not overlap:
                continue
            score = 0.3 + 0.1 * len(overlap)
            if score > best_score:
                best_domain = domain
                best_score = min(score, 0.95)
                reasons = [f"matched keywords: {', '.join(sorted(overlap))}"]

        return best_domain, self._confidence(best_score, reasons)

    def _semantic_table(self, table: NormalizedTable, actor_table: str | None = None) -> SemanticTable:
        meaning, confidence = self._table_meaning(table)
        columns = [self._semantic_column(table, column, actor_table) for column in table.columns]
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

    def _semantic_column(
        self,
        table: NormalizedTable,
        column: NormalizedColumn,
        actor_table: str | None = None,
    ) -> SemanticColumn:
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
        actor_meaning = self._actor_reference_meaning(table, column, actor_table)
        if actor_meaning is not None:
            meaning, confidence = actor_meaning
        return SemanticColumn(
            column_name=column.column_name,
            technical_type=column.technical_type,
            business_meaning=meaning,
            example_values=(column.enum_values or column.top_values or column.sample_values)[:5],
            synonyms=synonyms,
            filterable=filterable,
            displayable=displayable,
            sensitive=sensitive,
            confidence=confidence,
        )

    def _actor_table_name(self, tables: list[NormalizedTable]) -> str | None:
        table_names = {table.table_name.lower(): table.table_name for table in tables}
        actor_priority = self.rules.actor_table_priority
        for candidate in actor_priority:
            if candidate in table_names:
                return table_names[candidate]
        for table in tables:
            lowered = table.table_name.lower()
            if any(token in lowered for token in actor_priority):
                return table.table_name
        return None

    def _actor_reference_meaning(
        self,
        table: NormalizedTable,
        column: NormalizedColumn,
        actor_table: str | None,
    ) -> tuple[str, NamedConfidence] | None:
        if not actor_table:
            return None

        column_name = str(column.column_name or "").strip().lower()
        actor_label = snake_to_words(actor_table).lower()
        entity_label = snake_to_words(table.table_name.rstrip("s"))

        if column_name in self.rules.audit_actor_patterns:
            action = self.rules.audit_actor_patterns[column_name]
            return (
                f"{actor_label.capitalize()} who {action} this {entity_label} record.",
                self._confidence(
                    0.94,
                    [
                        f"audit actor naming pattern: {column.column_name}",
                        f"actor table '{actor_table}' exists in schema",
                    ],
                ),
            )

        direct_patterns = {
            f"{actor_table.lower()}_id",
            "user_id" if actor_table.lower() == "user" else "",
        }
        if column_name in direct_patterns or column_name.endswith("_user_id"):
            return (
                f"Reference to the {actor_label} associated with this {entity_label} record.",
                self._confidence(
                    0.92,
                    [
                        f"direct actor reference naming: {column.column_name}",
                        f"actor table '{actor_table}' exists in schema",
                    ],
                ),
            )

        responsibility_roles = self.rules.actor_responsibility_roles
        if responsibility_roles and re.fullmatch(
            rf"({'|'.join(re.escape(role) for role in responsibility_roles)})_id",
            column_name,
        ):
            return (
                f"Reference to the {actor_label} responsible for this {entity_label} record.",
                self._confidence(
                    0.88,
                    [
                        f"actor-like identifier naming: {column.column_name}",
                        f"actor table '{actor_table}' exists in schema",
                    ],
                ),
            )
        return None

    def _table_meaning(self, table: NormalizedTable) -> tuple[str, NamedConfidence]:
        table_rules = self.rules.table_meaning
        reasons: list[str] = []
        score = 0.45
        name = table.table_name
        inferred_directory_meaning = self._communication_directory_table_meaning(table)
        if inferred_directory_meaning is not None:
            return inferred_directory_meaning
        mapping_suffix = self._matching_suffix(name, table_rules.mapping_suffixes)
        if mapping_suffix:
            reasons.append("mapping suffix")
            score = 0.85
            return (
                f"Relationship mapping records for {snake_to_words(self._trim_suffix(name, mapping_suffix))}.",
                self._confidence(score, reasons),
            )
        history_suffix = self._matching_suffix(name, table_rules.history_suffixes)
        if history_suffix:
            reasons.append("history/log suffix")
            score = 0.85
            return (
                f"Historical event records for {snake_to_words(self._trim_suffix(name, history_suffix))}.",
                self._confidence(score, reasons),
            )
        detail_suffix = self._matching_suffix(name, table_rules.detail_suffixes)
        if detail_suffix:
            reasons.append("detail suffix")
            score = 0.7
            return (
                f"Detailed records associated with {snake_to_words(self._trim_suffix(name, detail_suffix))}.",
                self._confidence(score, reasons),
            )
        if table.row_count and table.row_count > 10_000:
            reasons.append("high row count suggests transactional or master usage")
            score += 0.15
        if any(token in table.tokens for token in table_rules.lifecycle_tokens):
            reasons.append("name suggests process lifecycle")
            score += 0.1
        return (
            f"Primary records for {snake_to_words(name)}.",
            self._confidence(min(score, 0.9), reasons or ["generic table naming"]),
        )

    def _communication_directory_table_meaning(
        self,
        table: NormalizedTable,
    ) -> tuple[str, NamedConfidence] | None:
        rules = self.rules.communication_directory
        name = table.table_name.lower()
        support_columns = [
            column.column_name
            for column in table.columns
            if any(token in column.column_name.lower() for token in rules.support_column_tokens)
        ]
        if len(support_columns) < rules.minimum_support_columns:
            return None

        structure_score = sum(1 for token in rules.structure_tokens if token in name)
        related_entities = self._table_related_entities(table)
        if (
            structure_score == 0
            and len(support_columns) < rules.minimum_support_columns_without_structure
            and len(related_entities) < rules.minimum_related_entities_without_structure
        ):
            return None
        entity_phrase = self._directory_entity_phrase(related_entities)
        if support_columns and entity_phrase:
            return (
                f"Support and contact details maintained for {entity_phrase}.",
                self._confidence(
                    0.9,
                    [
                        "communication/support column pattern",
                        f"support/contact columns: {', '.join(support_columns[:4])}",
                        f"related entities: {', '.join(related_entities[:4])}" if related_entities else "related entities inferred from joins",
                    ],
                ),
            )
        return (
            "Directory of operational contact details and support channels.",
            self._confidence(
                0.82,
                [
                    "communication/support column pattern",
                    f"support/contact columns: {', '.join(support_columns[:4])}",
                ],
            ),
        )

    def _table_related_entities(self, table: NormalizedTable) -> list[str]:
        related: list[str] = []
        for join in table.join_candidates:
            try:
                left, right = join.split("=")
            except ValueError:
                continue
            left_table = left.split(".")[0].strip()
            right_table = right.split(".")[0].strip()
            for table_name in (left_table, right_table):
                if table_name and table_name != table.table_name and table_name not in related:
                    related.append(table_name)
        return related[:6]

    def _directory_entity_phrase(self, related_entities: list[str]) -> str:
        labels: list[str] = []
        seen: set[str] = set()
        for entity in related_entities:
            lowered = entity.lower()
            label = next(
                (
                    candidate_label
                    for token, candidate_label in self.rules.communication_directory.related_entity_labels.items()
                    if token in lowered
                ),
                None,
            )
            if not label:
                continue
            if label in seen:
                continue
            seen.add(label)
            labels.append(label)

        if not labels:
            return ""
        if len(labels) == 1:
            return labels[0]
        if len(labels) == 2:
            return f"{labels[0]} and {labels[1]}"
        return f"{', '.join(labels[:-1])}, and {labels[-1]}"

    def _column_meaning(self, table: NormalizedTable, column: NormalizedColumn) -> tuple[str, NamedConfidence]:
        column_rules = self.rules.column_meaning
        name = column.column_name.lower()
        reasons: list[str] = []
        score = 0.45
        low_cardinality = column.distinct_count is not None and column.distinct_count <= 12
        status_signal = column.is_status_like or any(token in name for token in column_rules.status_tokens)
        classification_signal = any(token in name for token in column_rules.classification_tokens)
        if column.is_primary_key:
            return (
                f"Unique identifier for each {snake_to_words(table.table_name.rstrip('s'))}.",
                self._confidence(0.95, ["primary key"]),
            )
        if status_signal and column.is_foreign_key:
            return (
                "Reference to the workflow or lifecycle state for the record.",
                self._confidence(0.92, ["status/state naming", "foreign-key status reference"]),
            )
        if classification_signal and column.is_foreign_key:
            return (
                "Reference to the classification or category assigned to the record.",
                self._confidence(0.88, ["type/category naming", "foreign-key classification reference"]),
            )
        if column.is_foreign_key:
            score = 0.85
            reasons.append("foreign key")
            return (
                f"Reference to a related {snake_to_words(column.column_name.replace('_id', ''))}.",
                self._confidence(score, reasons),
            )
        if status_signal:
            if low_cardinality:
                reasons.append(f"low cardinality ({column.distinct_count} distinct values)")
            return (
                "Lifecycle or workflow status for the record.",
                self._confidence(0.93 if low_cardinality else 0.9, reasons or ["status/state naming"]),
            )
        if classification_signal:
            if low_cardinality:
                reasons.append(f"low cardinality ({column.distinct_count} distinct values)")
            return (
                "Classification or category for the record.",
                self._confidence(0.85 if low_cardinality else 0.8, reasons or ["type/category naming"]),
            )
        if any(token in name for token in column_rules.timestamp_tokens) or column.is_timestamp_like:
            return (
                "Timestamp used for audit, freshness, or trend analysis.",
                self._confidence(0.85, ["timestamp-like naming"]),
            )
        if "name" in name:
            score = 0.8
            reasons.append("name field")
            return ("Human-readable name or label.", self._confidence(score, reasons))
        if low_cardinality and (column.top_values or column.enum_values):
            reasons.append(f"low cardinality ({column.distinct_count} distinct values)")
            return (
                "Controlled vocabulary or small business classification used for filtering and grouping.",
                self._confidence(0.76, reasons),
            )
        if column.sample_values and len(column.sample_values) <= 5:
            reasons.append("sample values available")
            score += 0.15
        return (
            f"Business attribute for {snake_to_words(table.table_name)} related to {snake_to_words(column.column_name)}.",
            self._confidence(min(score, 0.8), reasons or ["generic naming"]),
        )

    def _matching_suffix(self, value: str, suffixes: tuple[str, ...]) -> str | None:
        for suffix in suffixes:
            if suffix and value.endswith(suffix):
                return suffix
        return None

    def _trim_suffix(self, value: str, suffix: str) -> str:
        if suffix and value.endswith(suffix):
            return value[: -len(suffix)]
        return value

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
            status_column = next(
                (
                    column.column_name
                    for column in table.columns
                    if "status" in column.column_name.lower()
                    or column.business_meaning == "Lifecycle or workflow status for the record."
                ),
                None,
            )
            timestamp_column = next(
                (
                    column.column_name
                    for column in table.columns
                    if column.business_meaning and "timestamp" in column.business_meaning.lower()
                ),
                None,
            )
            if timestamp_column is None:
                timestamp_column = next(
                    (
                        column.column_name
                        for column in table.columns
                        if any(token in column.column_name.lower() for token in ("created", "updated", "date", "time"))
                    ),
                    None,
                )
            patterns.append(
                QueryPattern(
                    intent=f"{singular}_summary",
                    question_examples=[
                        f"Show me a summary of {singular} records",
                        f"How many {singular} records are there?",
                        f"What are the most recent {singular} records?",
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
            if status_column:
                patterns.append(
                    QueryPattern(
                        intent=f"{singular}_status_breakdown",
                        question_examples=[f"What is the status breakdown for {singular} records?"],
                        preferred_tables=[table.table_name],
                        required_joins=table.valid_joins[:3],
                        safe_filters=table.common_filters[:4],
                        optional_sql_template=(
                            f"SELECT {status_column}, COUNT(*) AS total_records "
                            f"FROM {table.table_name} GROUP BY {status_column} ORDER BY total_records DESC"
                        ),
                        rendering_guidance="Use this pattern to validate enum meaning and workflow coverage.",
                    )
                )
            if timestamp_column:
                patterns.append(
                    QueryPattern(
                        intent=f"{singular}_recent_records",
                        question_examples=[f"Show the most recent {singular} records"],
                        preferred_tables=[table.table_name],
                        required_joins=table.valid_joins[:3],
                        safe_filters=table.common_filters[:4],
                        optional_sql_template=(
                            f"SELECT * FROM {table.table_name} "
                            f"ORDER BY {timestamp_column} DESC LIMIT 20"
                        ),
                        rendering_guidance="Use recent records to sanity-check freshness and grain.",
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
