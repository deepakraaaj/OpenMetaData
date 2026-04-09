from __future__ import annotations

from app.engine.question_generator import QuestionGenerator
from app.models.questionnaire import QuestionAction, QuestionOption, QuestionnaireBundle, QuestionnaireQuestion
from app.models.state import KnowledgeState, SemanticGap


class PolicyQuestionnaireBuilder:
    def __init__(self) -> None:
        self.question_generator = QuestionGenerator()

    def build(self, state: KnowledgeState) -> QuestionnaireBundle:
        questions: list[QuestionnaireQuestion] = []
        questions.extend(self._table_scope_questions(state))
        questions.extend(self._gap_questions(state))
        return QuestionnaireBundle(source_name=state.source_name, questions=questions)

    def _table_scope_questions(self, state: KnowledgeState) -> list[QuestionnaireQuestion]:
        questions: list[QuestionnaireQuestion] = []
        seen_tables: set[str] = set()
        for item in state.review_queue:
            table = state.tables.get(item.table_name)
            if table is None or table.table_name in seen_tables:
                continue
            seen_tables.add(table.table_name)
            suggested = "selected" if table.selected else "excluded"
            questions.append(
                QuestionnaireQuestion(
                    type="table_scope_review",
                    question=f"Should `{table.table_name}` stay in the semantic bundle scope?",
                    question_type="table_scope_review",
                    table=table.table_name,
                    best_guess=suggested,
                    confidence=table.confidence.score,
                    evidence=[entry for entry in table.evidence_refs[:6] if entry],
                    candidate_options=[
                        QuestionOption(
                            value="selected",
                            label="Keep in Scope",
                            description="Publish this table into the semantic bundle.",
                            is_best_guess=table.selected,
                        ),
                        QuestionOption(
                            value="excluded",
                            label="Exclude for Now",
                            description="Keep it out of the bundle until a human confirms it.",
                            is_best_guess=not table.selected,
                        ),
                    ],
                    decision_prompt=f"Use the AI suggestion for `{table.table_name}` or override it.",
                    actions=[
                        QuestionAction(value="confirm", label="Use AI Suggestion"),
                        QuestionAction(value="change", label="Override"),
                        QuestionAction(value="skip", label="Review Later"),
                    ],
                    impact_score=table.impact_score,
                    business_relevance=table.business_relevance,
                    priority_score=round(table.impact_score + table.business_relevance + (1 - table.confidence.score), 4),
                    suggested_answer=suggested,
                    metadata={
                        "review_mode": state.review_mode.value,
                        "decision_status": table.decision_status.value if table.decision_status else None,
                        "decision_actor": table.decision_actor.value if table.decision_actor else None,
                        "risk_level": table.risk_level.value if table.risk_level else None,
                        "policy_reason": table.policy_reason,
                        "review_debt": table.review_debt,
                        "publish_blocker": table.publish_blocker,
                        "needs_acknowledgement": table.needs_acknowledgement,
                        "domain": table.domain,
                        "related_tables": list(table.related_tables[:8]),
                    },
                )
            )
        return questions

    def _gap_questions(self, state: KnowledgeState) -> list[QuestionnaireQuestion]:
        return [self._question_from_gap(gap, state) for gap in state.unresolved_gaps]

    def _question_from_gap(self, gap: SemanticGap, state: KnowledgeState) -> QuestionnaireQuestion:
        generated = self.question_generator.generate(gap, state)
        return QuestionnaireQuestion(
            type=self._question_type(gap),
            question=generated.question,
            question_type=generated.question_type,
            table=generated.target_entity,
            column=generated.target_property,
            left_table=gap.metadata.get("left_table") if isinstance(gap.metadata, dict) else None,
            right_table=gap.metadata.get("right_table") if isinstance(gap.metadata, dict) else None,
            best_guess=generated.best_guess,
            confidence=generated.confidence,
            evidence=list(generated.evidence),
            candidate_options=list(generated.candidate_options),
            decision_prompt=generated.decision_prompt,
            actions=list(generated.actions),
            impact_score=generated.impact_score,
            ambiguity_score=generated.ambiguity_score,
            business_relevance=generated.business_relevance,
            priority_score=generated.priority_score,
            allow_free_text=generated.allow_free_text,
            free_text_placeholder=generated.free_text_placeholder,
            suggested_answer=generated.suggested_answer,
            suggested_join=gap.metadata.get("suggested_join") if isinstance(gap.metadata, dict) else None,
            metadata={
                "gap_id": gap.gap_id,
                "review_mode": state.review_mode.value,
                "decision_status": gap.decision_status.value if gap.decision_status else None,
                "risk_level": gap.risk_level.value if gap.risk_level else None,
                "policy_reason": gap.policy_reason,
                "review_debt": gap.review_debt,
                "publish_blocker": gap.publish_blocker,
                "needs_acknowledgement": gap.needs_acknowledgement,
                **dict(gap.metadata),
            },
        )

    def _question_type(self, gap: SemanticGap) -> str:
        if gap.category.value == "unknown_business_meaning":
            return "column_business_meaning" if gap.target_property else "table_business_meaning"
        if gap.category.value == "unconfirmed_enum_mapping":
            return "column_pattern_confirmation"
        if gap.category.value in {"ambiguous_relationship", "relationship_role_unclear"}:
            return "relationship_disambiguation"
        if gap.category.value == "potential_sensitivity":
            return "sensitivity_classification"
        if gap.category.value == "missing_primary_key":
            return "primary_key_confirmation"
        if gap.category.value == "glossary_term_missing":
            return "glossary_term_missing"
        return gap.category.value
