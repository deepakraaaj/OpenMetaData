from __future__ import annotations

from app.models.common import SensitivityLabel
from app.models.questionnaire import QuestionnaireBundle, QuestionnaireQuestion
from app.models.semantic import SemanticSourceModel


class AmbiguityDetector:
    def generate_questions(self, semantic: SemanticSourceModel) -> QuestionnaireBundle:
        questions: list[QuestionnaireQuestion] = []

        for table in semantic.tables:
            if table.confidence.score < 0.7:
                questions.append(
                    QuestionnaireQuestion(
                        type="table_business_meaning",
                        table=table.table_name,
                        question=f"What does the table `{table.table_name}` represent in business language?",
                        suggested_answer=table.business_meaning,
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
                if column.business_meaning is None or column.confidence.score < 0.65:
                    questions.append(
                        QuestionnaireQuestion(
                            type="column_business_meaning",
                            table=table.table_name,
                            column=column.column_name,
                            question=f"What is the business meaning of `{table.table_name}.{column.column_name}`?",
                            suggested_answer=column.business_meaning,
                        )
                    )
                if "status" in column.column_name.lower() or "state" in column.column_name.lower():
                    questions.append(
                        QuestionnaireQuestion(
                            type="status_semantics",
                            table=table.table_name,
                            column=column.column_name,
                            question=f"What are the allowed values and meanings for `{table.table_name}.{column.column_name}`?",
                            suggested_answer=", ".join(column.example_values[:5]) or None,
                        )
                    )

            for join in table.valid_joins[:3]:
                left, right = join.split("=")
                left_table = left.split(".")[0]
                right_table = right.split(".")[0]
                questions.append(
                    QuestionnaireQuestion(
                        type="relationship_validation",
                        left_table=left_table,
                        right_table=right_table,
                        suggested_join=join,
                        question=f"Is `{join}` a valid join for business reporting?",
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

