from __future__ import annotations

from app.core.inference_rules import SemanticInferenceRules, load_inference_rules
from app.models.common import SensitivityLabel
from app.models.questionnaire import QuestionnaireBundle, QuestionnaireQuestion
from app.models.semantic import SemanticSourceModel


class AmbiguityDetector:
    def __init__(self, rules: SemanticInferenceRules | None = None) -> None:
        self.rules = rules or load_inference_rules()

    def generate_questions(self, semantic: SemanticSourceModel) -> QuestionnaireBundle:
        questions: list[QuestionnaireQuestion] = []

        for table in semantic.tables:
            if table.confidence.score < 0.7:
                questions.append(
                    QuestionnaireQuestion(
                        type="table_business_meaning",
                        table=table.table_name,
                        question=f"In business terms, what workflow or entity does `{table.table_name}` represent?",
                        suggested_answer=table.business_meaning,
                        metadata={
                            "likely_entity": table.likely_entity or "",
                            "important_columns": table.important_columns[:5],
                            "business_questions": table.common_business_questions[:3],
                        },
                    )
                )

            if not table.valid_joins and table.important_columns:
                questions.append(
                    QuestionnaireQuestion(
                        type="chatbot_exposure",
                        table=table.table_name,
                        question=f"Should `{table.table_name}` be exposed to chatbot and reporting workflows?",
                        suggested_answer="Review before exposure",
                    )
                )

            relationship_options = self._relationship_options(table.valid_joins)
            for column_name, candidate_tables in relationship_options.items():
                if 2 <= len(candidate_tables) <= 4:
                    questions.append(
                        QuestionnaireQuestion(
                            type="relationship_disambiguation",
                            table=table.table_name,
                            column=column_name,
                            question=f"Which entity does `{table.table_name}.{column_name}` actually reference?",
                            suggested_answer=None,
                            metadata={"choices": candidate_tables},
                        )
                    )

            for column in table.columns:
                if column.sensitive == SensitivityLabel.possible_sensitive:
                    questions.append(
                        QuestionnaireQuestion(
                            type="sensitivity_classification",
                            table=table.table_name,
                            column=column.column_name,
                            question=(
                                f"Should `{table.table_name}.{column.column_name}` be treated as sensitive and masked?"
                            ),
                            suggested_answer="Yes if used outside operational support roles",
                        )
                    )
                if (
                    not self._is_low_signal_column(column.column_name)
                    and (column.business_meaning is None or column.confidence.score < 0.55)
                ):
                    questions.append(
                        QuestionnaireQuestion(
                            type="column_business_meaning",
                            table=table.table_name,
                            column=column.column_name,
                            question=f"For `{table.table_name}.{column.column_name}`, what does this field mean in business terms?",
                            suggested_answer=column.business_meaning,
                        )
                    )
                if self._is_status_column(column.column_name) and len(set(column.example_values[:8])) >= 2:
                    questions.append(
                        QuestionnaireQuestion(
                            type="status_semantics",
                            table=table.table_name,
                            column=column.column_name,
                            question=f"What do the allowed values of `{table.table_name}.{column.column_name}` mean in the business workflow?",
                            suggested_answer=", ".join(column.example_values[:5]) or None,
                        )
                    )

        deduped = self._dedupe(questions)[:80]
        return QuestionnaireBundle(source_name=semantic.source_name, questions=deduped)

    def _dedupe(self, questions: list[QuestionnaireQuestion]) -> list[QuestionnaireQuestion]:
        seen: set[tuple[str, str | None, str | None, str | None]] = set()
        results: list[QuestionnaireQuestion] = []
        for question in questions:
            key = (question.type, question.table, question.column, question.suggested_join)
            if key in seen:
                continue
            seen.add(key)
            results.append(question)
        return results

    def _is_low_signal_column(self, column_name: str) -> bool:
        name = str(column_name or "").strip().lower()
        rules = self.rules.gap_detection
        if not name:
            return True
        if name == "id" or name in rules.audit_column_names:
            return True
        if name.endswith("_id"):
            return True
        if rules.audit_column_suffixes and name.endswith(rules.audit_column_suffixes):
            return True
        return any(token in name for token in rules.temporal_name_tokens)

    def _is_status_column(self, column_name: str) -> bool:
        name = str(column_name or "").strip().lower()
        return any(token in name for token in self.rules.gap_detection.enum_name_tokens)

    def _relationship_options(self, joins: list[str]) -> dict[str, list[str]]:
        grouped: dict[str, list[str]] = {}
        for join in joins:
            try:
                left, right = join.split("=")
            except ValueError:
                continue
            left_parts = left.split(".")
            right_parts = right.split(".")
            if len(left_parts) != 2 or len(right_parts) != 2:
                continue
            column_name = left_parts[1].strip()
            if self._is_relationship_noise_column(column_name):
                continue
            right_table = right_parts[0].strip()
            grouped.setdefault(column_name, [])
            if right_table and right_table not in grouped[column_name]:
                grouped[column_name].append(right_table)
        return grouped

    def _is_relationship_noise_column(self, column_name: str) -> bool:
        name = str(column_name or "").strip().lower()
        rules = self.rules.gap_detection
        if not name:
            return True
        if name in rules.audit_column_names:
            return True
        if rules.audit_column_suffixes and name.endswith(rules.audit_column_suffixes):
            return True
        return any(token in name for token in rules.temporal_name_tokens)
