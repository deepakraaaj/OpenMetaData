from __future__ import annotations

from collections import Counter, defaultdict

from app.models.questionnaire import (
    QuestionAction,
    QuestionOption,
    QuestionnaireQuestion,
)
from app.models.review import TableRole
from app.models.semantic import DomainCluster, SemanticColumn, SemanticSourceModel, SemanticTable
from app.semantics.confidence import clamp_score
from app.utils.text import snake_to_words, unique_non_empty

_SYSTEM_DOMAIN = "Configuration / Internal"
_TECHNICAL_ROLES = {TableRole.log_event, TableRole.history_audit, TableRole.config_system}
_DOMAIN_CANDIDATES = [
    "Telemetry",
    "Trip Operations",
    "Vehicle Management",
    "Billing / Commercial",
    "Users & Access",
    "Configuration / Internal",
]


class AmbiguityCompressor:
    def build_questions(self, semantic: SemanticSourceModel) -> list[QuestionnaireQuestion]:
        questions: list[QuestionnaireQuestion] = []
        covered_tables: set[str] = set()

        cluster_questions = self._cluster_questions(semantic)
        questions.extend(cluster_questions)
        for question in cluster_questions:
            covered_tables.update(list(question.metadata.get("member_tables", [])))

        role_questions = self._role_pattern_questions(semantic)
        questions.extend(role_questions)
        for question in role_questions:
            covered_tables.update(list(question.metadata.get("member_tables", [])))

        questions.extend(self._status_pattern_questions(semantic))
        questions.extend(self._table_follow_up_questions(semantic, covered_tables))
        questions.extend(self._relationship_follow_up_questions(semantic, covered_tables))
        questions.extend(self._sensitivity_questions(semantic))

        deduped = self._dedupe(questions)
        return sorted(
            deduped,
            key=lambda item: (
                -(item.priority_score or 0.0),
                -(item.impact_score or 0.0),
                item.table or "",
                item.column or "",
                item.type,
            ),
        )[:32]

    def _cluster_questions(self, semantic: SemanticSourceModel) -> list[QuestionnaireQuestion]:
        questions: list[QuestionnaireQuestion] = []
        for cluster in semantic.domain_clusters:
            if len(cluster.member_tables) <= 1:
                continue
            avg_impact = self._score(
                self._average_for_tables(
                    semantic,
                    cluster.member_tables,
                    field_name="impact_score",
                    fallback=0.35,
                )
            )
            avg_business_relevance = self._score(
                self._average_for_tables(
                    semantic,
                    cluster.member_tables,
                    field_name="business_relevance",
                    fallback=0.42,
                )
            )
            ambiguity = self._score(
                max(
                    0.16,
                    1.0 - cluster.confidence.score + (0.12 if cluster.requires_review else 0.0),
                )
            )
            priority = self._priority(avg_impact, ambiguity, avg_business_relevance)
            if priority < 0.18:
                continue

            cluster_label = str(cluster.cluster_name or "").strip() or _SYSTEM_DOMAIN
            best_guess = str(cluster.inferred_business_meaning or f"Business area grouped as {cluster_label}.").strip()
            questions.append(
                QuestionnaireQuestion(
                    type="domain_cluster_confirmation",
                    question=f"We grouped {len(cluster.member_tables)} tables into `{cluster_label}`.",
                    question_type="domain_confirmation",
                    table=cluster.anchor_tables[0] if cluster.anchor_tables else cluster.member_tables[0],
                    best_guess=best_guess,
                    confidence=cluster.confidence.score,
                    evidence=unique_non_empty(
                        [
                            f"anchor tables: {', '.join(cluster.anchor_tables[:3])}" if cluster.anchor_tables else "",
                            f"members: {', '.join(cluster.member_tables[:6])}",
                            f"cluster meaning: {cluster.inferred_business_meaning}" if cluster.inferred_business_meaning else "",
                            *list(cluster.evidence[:3]),
                        ]
                    )[:5],
                    candidate_options=self._domain_options(cluster_label),
                    decision_prompt=f"Which label best fits this group of tables?",
                    actions=self._default_actions(),
                    impact_score=avg_impact,
                    ambiguity_score=ambiguity,
                    business_relevance=avg_business_relevance,
                    priority_score=priority,
                    allow_free_text=True,
                    free_text_placeholder="Optional: provide a better business domain label only if none of the options fits.",
                    suggested_answer=cluster_label,
                    metadata={
                        "member_tables": list(cluster.member_tables),
                        "anchor_tables": list(cluster.anchor_tables),
                        "cluster_name": cluster_label,
                    },
                )
            )
        return questions

    def _role_pattern_questions(self, semantic: SemanticSourceModel) -> list[QuestionnaireQuestion]:
        grouped: dict[TableRole, list[SemanticTable]] = defaultdict(list)
        for table in semantic.tables:
            if table.role in {TableRole.core_entity, TableRole.transaction}:
                continue
            grouped[table.role].append(table)

        questions: list[QuestionnaireQuestion] = []
        for role, tables in grouped.items():
            if len(tables) < 2:
                continue
            avg_confidence = sum(table.confidence.score for table in tables) / len(tables)
            avg_impact = self._score(sum(table.impact_score for table in tables) / len(tables))
            avg_relevance = self._score(sum(table.business_relevance for table in tables) / len(tables))
            if avg_confidence >= 0.82 and avg_impact < 0.45:
                continue

            ambiguity = self._score(max(0.18, 1.0 - avg_confidence + 0.08))
            priority = self._priority(avg_impact, ambiguity, avg_relevance)
            if priority < 0.18:
                continue

            member_names = [table.table_name for table in tables]
            question_type = "ignore_confirmation" if role in _TECHNICAL_ROLES else "pattern_confirmation"
            best_guess = self._role_pattern_guess(role)
            questions.append(
                QuestionnaireQuestion(
                    type=f"{role.value}_pattern_confirmation",
                    question=self._role_pattern_question(role, member_names),
                    question_type=question_type,
                    table=member_names[0],
                    best_guess=best_guess,
                    confidence=self._score(avg_confidence),
                    evidence=unique_non_empty(
                        [
                            f"member tables: {', '.join(member_names[:6])}",
                            f"common reasons: {tables[0].classification_reason}" if tables[0].classification_reason else "",
                            f"default selection: {sum(1 for table in tables if table.selected_by_default)} included / {len(tables)} total",
                            f"domains: {', '.join(unique_non_empty([table.domain or _SYSTEM_DOMAIN for table in tables])[:3])}",
                        ]
                    )[:5],
                    candidate_options=self._role_pattern_options(role),
                    decision_prompt=self._role_pattern_decision(role),
                    actions=self._default_actions(),
                    impact_score=avg_impact,
                    ambiguity_score=ambiguity,
                    business_relevance=avg_relevance,
                    priority_score=priority,
                    allow_free_text=True,
                    free_text_placeholder="Optional: describe the exception only if the pattern is misleading.",
                    suggested_answer=best_guess,
                    metadata={
                        "member_tables": member_names,
                        "role": role.value,
                    },
                )
            )
        return questions

    def _status_pattern_questions(self, semantic: SemanticSourceModel) -> list[QuestionnaireQuestion]:
        status_groups: dict[str, list[tuple[SemanticTable, SemanticColumn]]] = defaultdict(list)
        for table in semantic.tables:
            if not table.selected:
                continue
            for column in table.columns:
                key = self._status_group_key(column.column_name)
                if not key:
                    continue
                if len(set(column.example_values[:6])) < 2:
                    continue
                status_groups[key].append((table, column))

        questions: list[QuestionnaireQuestion] = []
        for group_name, columns in status_groups.items():
            if len(columns) < 3:
                continue
            avg_impact = self._score(sum(item[0].impact_score for item in columns) / len(columns))
            avg_relevance = self._score(sum(item[0].business_relevance for item in columns) / len(columns))
            ambiguity = self._score(0.34 if "status" in group_name else 0.42)
            priority = self._priority(avg_impact, ambiguity, avg_relevance)
            if priority < 0.18:
                continue

            examples = [
                f"{table.table_name}.{column.column_name}"
                for table, column in columns[:6]
            ]
            questions.append(
                QuestionnaireQuestion(
                    type="status_pattern_confirmation",
                    question=f"We found {len(columns)} similar `{group_name}` fields across the selected tables.",
                    question_type="pattern_confirmation",
                    table=columns[0][0].table_name,
                    column=columns[0][1].column_name,
                    best_guess="Workflow or lifecycle status.",
                    confidence=0.64,
                    evidence=unique_non_empty(
                        [
                            f"fields: {', '.join(examples)}",
                            f"sample values: {', '.join(unique_non_empty(value for _table, column in columns for value in column.example_values[:3])[:6])}",
                        ]
                    ),
                    candidate_options=[
                        self._option(
                            "status_pattern",
                            "Workflow or lifecycle status",
                            "Treat these fields as business states or stages.",
                            is_best_guess=True,
                        ),
                        self._option("type_pattern", "Type or category", "Treat them as classifications."),
                        self._option("flag_pattern", "Boolean or active flag", "Treat them as yes/no style fields."),
                        self._option("__other__", "Something else", "Use a different shared interpretation.", is_fallback=True),
                    ],
                    decision_prompt=f"What is the closest shared interpretation for these `{group_name}` fields?",
                    actions=self._default_actions(),
                    impact_score=avg_impact,
                    ambiguity_score=ambiguity,
                    business_relevance=avg_relevance,
                    priority_score=priority,
                    allow_free_text=True,
                    free_text_placeholder="Optional: add a better cross-table pattern label.",
                    suggested_answer="status_pattern",
                    metadata={"member_columns": examples},
                )
            )
        return questions

    def _table_follow_up_questions(
        self,
        semantic: SemanticSourceModel,
        covered_tables: set[str],
    ) -> list[QuestionnaireQuestion]:
        questions: list[QuestionnaireQuestion] = []
        for table in semantic.tables:
            if not table.requires_review:
                continue
            if table.table_name in covered_tables and table.role != TableRole.unknown:
                continue
            if table.impact_score < 0.42 and table.business_relevance < 0.45:
                continue

            ambiguity = self._score(
                max(
                    0.2,
                    1.0 - table.confidence.score + (0.1 if table.role == TableRole.unknown else 0.0),
                )
            )
            priority = self._priority(table.impact_score, ambiguity, max(table.business_relevance, 0.25))
            if priority < 0.18:
                continue

            if table.role == TableRole.unknown or table.confidence.score < 0.58:
                questions.append(self._table_role_question(table, ambiguity, priority))
            elif self._looks_generic_meaning(table.business_meaning):
                questions.append(self._table_meaning_question(table, ambiguity, priority))
        return questions

    def _relationship_follow_up_questions(
        self,
        semantic: SemanticSourceModel,
        covered_tables: set[str],
    ) -> list[QuestionnaireQuestion]:
        questions: list[QuestionnaireQuestion] = []
        for table in semantic.tables:
            if not table.selected or table.table_name in covered_tables:
                continue
            grouped: dict[str, list[str]] = defaultdict(list)
            for join in table.valid_joins:
                try:
                    left, right = str(join).split("=")
                except ValueError:
                    continue
                left_parts = left.split(".")
                right_parts = right.split(".")
                if len(left_parts) != 2 or len(right_parts) != 2:
                    continue
                grouped[left_parts[1].strip()].append(right_parts[0].strip())

            for column_name, candidates in grouped.items():
                deduped = unique_non_empty(candidates)
                if len(deduped) < 2 or len(deduped) > 4:
                    continue
                ambiguity = self._score(0.42 + min((len(deduped) - 1) * 0.12, 0.24))
                priority = self._priority(table.impact_score, ambiguity, max(table.business_relevance, 0.25))
                if priority < 0.2:
                    continue
                questions.append(
                    QuestionnaireQuestion(
                        type="relationship_validation",
                        question=f"We found multiple plausible targets for `{table.table_name}.{column_name}`.",
                        question_type="role_confirmation",
                        table=table.table_name,
                        column=column_name,
                        best_guess=deduped[0],
                        confidence=0.56,
                        evidence=unique_non_empty(
                            [
                                f"candidate targets: {', '.join(deduped)}",
                                f"current joins: {', '.join(join for join in table.valid_joins if f'{table.table_name}.{column_name}=' in join)}",
                            ]
                        ),
                        candidate_options=[
                            self._option(
                                value=name,
                                label=snake_to_words(name),
                                description=f"Treat `{table.table_name}.{column_name}` as a reference to `{name}`.",
                                is_best_guess=index == 0,
                            )
                            for index, name in enumerate(deduped)
                        ]
                        + [self._option("__other__", "Something else", "None of these targets is correct.", is_fallback=True)],
                        decision_prompt=f"Which entity does `{table.table_name}.{column_name}` most likely reference?",
                        actions=self._default_actions(),
                        impact_score=table.impact_score,
                        ambiguity_score=ambiguity,
                        business_relevance=table.business_relevance,
                        priority_score=priority,
                        allow_free_text=True,
                        free_text_placeholder="Optional: enter a better target entity.",
                        suggested_answer=deduped[0],
                        metadata={
                            "candidate_tables": deduped,
                            "candidate_joins": {
                                target: join
                                for join in table.valid_joins
                                for target in deduped
                                if join.endswith(f"{target}.id")
                            },
                        },
                    )
                )
        return questions

    def _sensitivity_questions(self, semantic: SemanticSourceModel) -> list[QuestionnaireQuestion]:
        questions: list[QuestionnaireQuestion] = []
        for table in semantic.tables:
            if not table.selected or table.impact_score < 0.45:
                continue
            for column in table.columns:
                if column.sensitive.value != "possible_sensitive":
                    continue
                ambiguity = 0.36
                priority = self._priority(table.impact_score, ambiguity, max(table.business_relevance, 0.25))
                if priority < 0.18:
                    continue
                questions.append(
                    QuestionnaireQuestion(
                        type="sensitivity_classification",
                        question=f"We flagged `{table.table_name}.{column.column_name}` as potentially sensitive.",
                        question_type="ignore_confirmation",
                        table=table.table_name,
                        column=column.column_name,
                        best_guess="Mask this column",
                        confidence=0.58,
                        evidence=unique_non_empty(
                            [
                                f"column name: {column.column_name}",
                                f"sample values: {', '.join(column.example_values[:4])}" if column.example_values else "",
                            ]
                        ),
                        candidate_options=[
                            self._option("mask", "Mask this column", "Keep it out of user-facing answers.", is_best_guess=True),
                            self._option("display", "Allow display", "Treat it as safe for standard outputs."),
                            self._option("__other__", "Something else", "Use a more specific masking rule.", is_fallback=True),
                        ],
                        decision_prompt=f"How should `{table.table_name}.{column.column_name}` be handled in outputs?",
                        actions=self._default_actions(),
                        impact_score=table.impact_score,
                        ambiguity_score=ambiguity,
                        business_relevance=table.business_relevance,
                        priority_score=priority,
                        allow_free_text=True,
                        free_text_placeholder="Optional: describe a role-based masking rule.",
                        suggested_answer="mask",
                    )
                )
        return questions

    def _table_role_question(
        self,
        table: SemanticTable,
        ambiguity: float,
        priority: float,
    ) -> QuestionnaireQuestion:
        best_guess = table.role.value.replace("_", " ") if table.role != TableRole.unknown else "Core business table"
        return QuestionnaireQuestion(
            type="table_role_confirmation",
            question=f"We are not fully confident about the role of `{table.table_name}`.",
            question_type="role_confirmation",
            table=table.table_name,
            best_guess=best_guess,
            confidence=table.confidence.score,
            evidence=unique_non_empty(
                [
                    table.classification_reason or "",
                    f"selection reason: {table.selection_reason}" if table.selection_reason else "",
                    f"related tables: {', '.join(table.related_tables[:4])}" if table.related_tables else "",
                ]
            )[:4],
            candidate_options=[
                self._option("core_entity", "Core Entity", "One record per main business object.", is_best_guess=table.role == TableRole.core_entity),
                self._option("transaction", "Transaction", "One record per workflow or operational event.", is_best_guess=table.role == TableRole.transaction),
                self._option("lookup_master", "Lookup / Master", "Reference data used for labels or filters.", is_best_guess=table.role == TableRole.lookup_master),
                self._option("mapping_bridge", "Mapping / Bridge", "Links two or more entities.", is_best_guess=table.role == TableRole.mapping_bridge),
                self._option("__other__", "Something else", "Use a different role.", is_fallback=True),
            ],
            decision_prompt=f"Which table role is closest for `{table.table_name}`?",
            actions=self._default_actions(),
            impact_score=table.impact_score,
            ambiguity_score=ambiguity,
            business_relevance=table.business_relevance,
            priority_score=priority,
            allow_free_text=True,
            free_text_placeholder="Optional: describe a better role if none of the options fits.",
            suggested_answer=table.role.value if table.role != TableRole.unknown else "core_entity",
        )

    def _table_meaning_question(
        self,
        table: SemanticTable,
        ambiguity: float,
        priority: float,
    ) -> QuestionnaireQuestion:
        best_guess = self._table_best_guess(table)
        return QuestionnaireQuestion(
            type="table_business_meaning",
            question=f"We formed a best guess for `{table.table_name}`.",
            question_type="meaning_confirmation",
            table=table.table_name,
            best_guess=best_guess,
            confidence=table.confidence.score,
            evidence=unique_non_empty(
                [
                    f"important columns: {', '.join(table.important_columns[:5])}" if table.important_columns else "",
                    f"likely entity: {table.likely_entity}" if table.likely_entity else "",
                    f"domain: {table.domain}" if table.domain else "",
                    table.classification_reason or "",
                ]
            )[:5],
            candidate_options=[
                self._option(best_guess, best_guess, "Current system best guess.", is_best_guess=True),
                self._option("Operational workflow or transaction records.", "Operational workflow", "One row per business event or workflow item."),
                self._option("Configuration or reference setup records.", "Reference or config", "Setup or supporting metadata rather than operational facts."),
                self._option("Relationship mapping between entities.", "Relationship mapping", "Primarily used to link other entities."),
                self._option("__other__", "Something else", "Use a different business meaning.", is_fallback=True),
            ],
            decision_prompt=f"Which interpretation is closest for `{table.table_name}`?",
            actions=self._default_actions(),
            impact_score=table.impact_score,
            ambiguity_score=ambiguity,
            business_relevance=table.business_relevance,
            priority_score=priority,
            allow_free_text=True,
            free_text_placeholder="Optional: describe the real business meaning only if none of the options fits.",
            suggested_answer=best_guess,
        )

    def _domain_options(self, best_label: str) -> list[QuestionOption]:
        options = [self._option(best_label, best_label, "Current system grouping.", is_best_guess=True)]
        for label in _DOMAIN_CANDIDATES:
            if label.lower() == best_label.lower():
                continue
            options.append(self._option(label, label, f"Regroup these tables under {label}."))
            if len(options) >= 4:
                break
        options.append(self._option("__other__", "Something else", "Use a different domain label.", is_fallback=True))
        return options

    def _role_pattern_guess(self, role: TableRole) -> str:
        mapping = {
            TableRole.lookup_master: "Reference or lookup tables.",
            TableRole.mapping_bridge: "Bridge tables that connect core entities.",
            TableRole.log_event: "Operational logs or event streams.",
            TableRole.history_audit: "History or audit trail tables.",
            TableRole.config_system: "Configuration or internal system tables.",
            TableRole.unknown: "Mixed or unclear support tables.",
        }
        return mapping.get(role, role.value.replace("_", " "))

    def _role_pattern_question(self, role: TableRole, member_names: list[str]) -> str:
        preview = ", ".join(member_names[:4])
        if role in _TECHNICAL_ROLES:
            return f"We think these {len(member_names)} tables are mostly technical support tables: {preview}."
        if role == TableRole.mapping_bridge:
            return f"We think these {len(member_names)} tables are bridge tables used for joins: {preview}."
        if role == TableRole.lookup_master:
            return f"We think these {len(member_names)} tables are lookup/reference data: {preview}."
        return f"We found a repeated `{role.value}` pattern across {len(member_names)} tables."

    def _role_pattern_decision(self, role: TableRole) -> str:
        if role in _TECHNICAL_ROLES:
            return "How should this technical-table pattern be treated by default?"
        return f"Which interpretation best fits this `{role.value.replace('_', ' ')}` pattern?"

    def _role_pattern_options(self, role: TableRole) -> list[QuestionOption]:
        if role in _TECHNICAL_ROLES:
            return [
                self._option("confirm_pattern", "Confirm technical pattern", "Exclude these by default unless they are unusually important.", is_best_guess=True),
                self._option("keep_reference", "Keep as reference only", "Retain them for context but not as core business tables."),
                self._option("treat_as_business", "Treat as business tables", "Keep them in the main selected scope."),
                self._option("__other__", "Something else", "Use a custom rule.", is_fallback=True),
            ]
        if role == TableRole.mapping_bridge:
            return [
                self._option("confirm_pattern", "Confirm bridge tables", "Use them mainly when joins require many-to-many traversal.", is_best_guess=True),
                self._option("keep_selected", "Keep selected by default", "Treat most of them as important in daily analysis."),
                self._option("exclude_pattern", "Exclude by default", "Only include specific bridge tables when a use case demands it."),
                self._option("__other__", "Something else", "Use a custom rule.", is_fallback=True),
            ]
        if role == TableRole.lookup_master:
            return [
                self._option("confirm_pattern", "Confirm reference pattern", "Keep them optional unless labels or filters depend on them.", is_best_guess=True),
                self._option("keep_selected", "Keep selected by default", "Treat most of them as necessary business context."),
                self._option("exclude_pattern", "Exclude by default", "Use them only on demand."),
                self._option("__other__", "Something else", "Use a custom rule.", is_fallback=True),
            ]
        return [
            self._option("confirm_pattern", "Confirm pattern", "Use the current interpretation.", is_best_guess=True),
            self._option("__other__", "Something else", "Use a different interpretation.", is_fallback=True),
        ]

    def _status_group_key(self, column_name: str) -> str:
        lowered = str(column_name or "").strip().lower()
        if not lowered:
            return ""
        if "status" in lowered or "state" in lowered or "stage" in lowered:
            return "status"
        if "type" in lowered or "category" in lowered:
            return "type"
        if "flag" in lowered or lowered.startswith("is_") or lowered.startswith("has_"):
            return "flag"
        return ""

    def _table_best_guess(self, table: SemanticTable) -> str:
        name = table.table_name.lower()
        columns = {column.column_name.lower() for column in table.columns}
        if "location" in name and ("fence" in name or {"latitude", "longitude"} <= columns or "perimeter" in columns):
            return "Geofence or area boundary around a location."
        if table.likely_entity:
            return f"{table.likely_entity} records."
        if str(table.business_meaning or "").strip():
            return str(table.business_meaning).strip()
        return f"Operational records for {snake_to_words(table.table_name)}."

    def _looks_generic_meaning(self, text: str | None) -> bool:
        value = str(text or "").strip()
        if not value:
            return True
        return value.startswith(
            (
                "Business attribute for ",
                "Reference to a related ",
                "Primary records for ",
                "Detailed records associated with ",
                "Historical event records for ",
                "Timestamp used for audit",
            )
        )

    def _average_for_tables(
        self,
        semantic: SemanticSourceModel,
        table_names: list[str],
        *,
        field_name: str,
        fallback: float,
    ) -> float:
        table_map = {table.table_name: table for table in semantic.tables}
        values = [
            float(getattr(table_map[name], field_name, fallback) or fallback)
            for name in table_names
            if name in table_map
        ]
        if not values:
            return fallback
        return sum(values) / len(values)

    def _dedupe(self, questions: list[QuestionnaireQuestion]) -> list[QuestionnaireQuestion]:
        seen: set[tuple[str, str | None, str | None]] = set()
        results: list[QuestionnaireQuestion] = []
        for question in questions:
            key = (question.type, question.table, question.column)
            if key in seen:
                continue
            seen.add(key)
            results.append(question)
        return results

    def _default_actions(self) -> list[QuestionAction]:
        return [
            QuestionAction(value="confirm", label="Confirm"),
            QuestionAction(value="change", label="Change"),
            QuestionAction(value="skip", label="Skip"),
        ]

    def _option(
        self,
        value: str,
        label: str,
        description: str | None = None,
        *,
        is_best_guess: bool = False,
        is_fallback: bool = False,
    ) -> QuestionOption:
        return QuestionOption(
            value=value,
            label=label,
            description=description,
            is_best_guess=is_best_guess,
            is_fallback=is_fallback,
        )

    def _priority(self, impact_score: float, ambiguity_score: float, business_relevance: float) -> float:
        return round(impact_score * ambiguity_score * business_relevance, 4)

    def _score(self, value: float) -> float:
        return clamp_score(value)
