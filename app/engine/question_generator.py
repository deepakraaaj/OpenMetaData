"""Convert a SemanticGap into a structured confirmation question."""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.models.questionnaire import QuestionAction, QuestionOption
from app.models.state import GapCategory, KnowledgeState, SemanticGap


class GeneratedQuestion(BaseModel):
    gap_id: str
    question: str
    context: str = ""
    evidence: list[str] = Field(default_factory=list)
    input_type: str = "text"
    choices: list[str] = Field(default_factory=list)
    suggested_answer: str | None = None
    target_entity: str | None = None
    target_property: str | None = None
    question_type: str = "meaning_confirmation"
    best_guess: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    candidate_options: list[QuestionOption] = Field(default_factory=list)
    decision_prompt: str | None = None
    actions: list[QuestionAction] = Field(default_factory=list)
    impact_score: float = Field(default=0.0, ge=0, le=1)
    ambiguity_score: float = Field(default=0.0, ge=0, le=1)
    business_relevance: float = Field(default=0.0, ge=0, le=1)
    priority_score: float = Field(default=0.0, ge=0)
    allow_free_text: bool = False
    free_text_placeholder: str | None = None


class QuestionGenerator:
    """Transforms a semantic gap into a context-rich confirmation question."""

    def generate(self, gap: SemanticGap, state: KnowledgeState) -> GeneratedQuestion:
        if (
            gap.best_guess
            or gap.candidate_options
            or gap.evidence
            or gap.decision_prompt
            or gap.actions
            or gap.priority_score > 0
            or gap.allow_free_text
        ):
            return self._structured_question(gap, state)
        handler = self._handlers.get(gap.category, self._default_question)
        return handler(self, gap, state)

    def _structured_question(self, gap: SemanticGap, state: KnowledgeState) -> GeneratedQuestion:
        del state  # Structured gaps already carry the needed evidence bundle.
        choices = [option.label for option in gap.candidate_options if not option.is_fallback]
        input_type = "select" if gap.candidate_options else "text"
        return GeneratedQuestion(
            gap_id=gap.gap_id,
            question=gap.decision_prompt or gap.suggested_question or gap.description,
            context=self._context_for_question_type(gap.question_type),
            evidence=list(gap.evidence),
            input_type=input_type,
            choices=choices,
            suggested_answer=gap.best_guess,
            target_entity=gap.target_entity,
            target_property=gap.target_property,
            question_type=gap.question_type,
            best_guess=gap.best_guess,
            confidence=gap.confidence,
            candidate_options=list(gap.candidate_options),
            decision_prompt=gap.decision_prompt or gap.suggested_question,
            actions=list(gap.actions) or self._default_actions(),
            impact_score=gap.impact_score,
            ambiguity_score=gap.ambiguity_score,
            business_relevance=gap.business_relevance,
            priority_score=gap.priority_score,
            allow_free_text=gap.allow_free_text,
            free_text_placeholder=gap.free_text_placeholder,
        )

    def _context_for_question_type(self, question_type: str) -> str:
        contexts = {
            "meaning_confirmation": "Review the system belief first, then confirm or correct it. Free text is only needed if none of the options fits.",
            "role_confirmation": "Pick the real business target so joins attach to the correct entity.",
            "pattern_confirmation": "Confirm the kind of business pattern this field represents. Add custom text only if the pattern or labels need correction.",
            "domain_confirmation": "Confirm the business-facing label users should see.",
            "ignore_confirmation": "Confirm whether this should stay masked, ignored, or deprioritized in user-facing flows.",
        }
        return contexts.get(
            str(question_type or "").strip(),
            "Confirm the best guess when it looks right. Use free text only as a fallback.",
        )

    def _default_actions(self) -> list[QuestionAction]:
        return [
            QuestionAction(value="confirm", label="Confirm"),
            QuestionAction(value="change", label="Change"),
            QuestionAction(value="skip", label="Skip"),
        ]

    def _meaning_question(self, gap: SemanticGap, state: KnowledgeState) -> GeneratedQuestion:
        evidence: list[str] = []
        suggested = None

        table = state.tables.get(gap.target_entity or "")
        if table:
            if table.business_meaning:
                suggested = table.business_meaning
                evidence.append(f"Current guess: {table.business_meaning}")
            if table.likely_entity:
                evidence.append(f"Likely entity: {table.likely_entity}")
            if table.grain:
                evidence.append(f"Grain: {table.grain}")
            columns = gap.metadata.get("important_columns") if isinstance(gap.metadata, dict) else None
            if columns:
                evidence.append(f"Important columns: {', '.join(columns[:5])}")
            elif table.important_columns:
                evidence.append(f"Important columns: {', '.join(table.important_columns[:5])}")
            neighbors = gap.metadata.get("neighbor_tables") if isinstance(gap.metadata, dict) else None
            if neighbors:
                evidence.append(f"Connected to: {', '.join(neighbors[:5])}")

        return GeneratedQuestion(
            gap_id=gap.gap_id,
            question=gap.suggested_question or gap.description,
            context="Answer with the real business concept or workflow this table represents. Use operational language, not SQL structure.",
            evidence=evidence,
            input_type="text",
            suggested_answer=suggested,
            target_entity=gap.target_entity,
            target_property=gap.target_property,
            question_type="meaning_confirmation",
            best_guess=suggested,
        )

    def _enum_question(self, gap: SemanticGap, state: KnowledgeState) -> GeneratedQuestion:
        evidence: list[str] = []
        choices: list[str] = []

        table = state.tables.get(gap.target_entity or "")
        if table and gap.target_property:
            col = next((c for c in table.columns if c.column_name == gap.target_property), None)
            if col and col.example_values:
                choices = list(dict.fromkeys(col.example_values))[:10]
        observed_values = gap.metadata.get("observed_values") if isinstance(gap.metadata, dict) else None
        if observed_values:
            choices = [str(value) for value in observed_values[:10]]
        if choices:
            evidence.append(f"Observed values: {', '.join(choices)}")

        existing_enums = state.enums.get(f"{gap.target_entity}.{gap.target_property}", [])
        if existing_enums:
            evidence.append(f"Current mappings: {', '.join(f'{e.database_value}→{e.business_label}' for e in existing_enums)}")

        return GeneratedQuestion(
            gap_id=gap.gap_id,
            question=gap.suggested_question or gap.description,
            context="Map each observed value to the business meaning users would understand. Example: `open=Ready to dispatch, closed=No further action`.",
            evidence=evidence,
            input_type="tags",
            choices=choices,
            target_entity=gap.target_entity,
            target_property=gap.target_property,
            question_type="pattern_confirmation",
        )

    def _pk_question(self, gap: SemanticGap, state: KnowledgeState) -> GeneratedQuestion:
        evidence: list[str] = []
        choices: list[str] = []

        table = state.tables.get(gap.target_entity or "")
        if table:
            id_cols = [c.column_name for c in table.columns if "id" in c.column_name.lower()]
            choices = id_cols
            if id_cols:
                evidence.append(f"Likely candidates: {', '.join(id_cols)}")

        return GeneratedQuestion(
            gap_id=gap.gap_id,
            question=gap.suggested_question or gap.description,
            context="Identifying the primary key helps the system avoid duplicate records in queries.",
            evidence=evidence,
            input_type="select" if choices else "text",
            choices=choices,
            suggested_answer=choices[0] if choices else None,
            target_entity=gap.target_entity,
            target_property=gap.target_property,
            question_type="role_confirmation",
            best_guess=choices[0] if choices else None,
        )

    def _relationship_question(self, gap: SemanticGap, state: KnowledgeState) -> GeneratedQuestion:
        candidate_tables = gap.metadata.get("candidate_tables") if isinstance(gap.metadata, dict) else None
        evidence = []
        if candidate_tables:
            evidence.append(f"Possible target tables: {', '.join(candidate_tables)}")
        return GeneratedQuestion(
            gap_id=gap.gap_id,
            question=gap.suggested_question or gap.description,
            context="Choose the real entity this field references so cross-table queries join to the correct business object.",
            evidence=evidence,
            input_type="select" if candidate_tables else "boolean",
            choices=list(candidate_tables or ["Yes, this is valid", "No, this is incorrect", "None of these"]),
            target_entity=gap.target_entity,
            target_property=gap.target_property,
            question_type="role_confirmation",
            best_guess=str(candidate_tables[0]) if candidate_tables else None,
        )

    def _sensitivity_question(self, gap: SemanticGap, state: KnowledgeState) -> GeneratedQuestion:
        del state
        return GeneratedQuestion(
            gap_id=gap.gap_id,
            question=gap.suggested_question or gap.description,
            context="Marking a column as sensitive will mask it in reports and prevent it from appearing in chatbot answers.",
            evidence=[],
            input_type="boolean",
            choices=["Yes, mask this column", "No, it is safe to display"],
            target_entity=gap.target_entity,
            target_property=gap.target_property,
            question_type="ignore_confirmation",
            best_guess="Yes, mask this column",
        )

    def _glossary_question(self, gap: SemanticGap, state: KnowledgeState) -> GeneratedQuestion:
        del state
        return GeneratedQuestion(
            gap_id=gap.gap_id,
            question=gap.suggested_question or gap.description,
            context="Provide the real business term teams use in day-to-day conversations, dashboards, or SOPs.",
            evidence=[],
            input_type="text",
            target_entity=gap.target_entity,
            target_property=gap.target_property,
            question_type="domain_confirmation",
        )

    def _default_question(self, gap: SemanticGap, state: KnowledgeState) -> GeneratedQuestion:
        del state
        return GeneratedQuestion(
            gap_id=gap.gap_id,
            question=gap.suggested_question or gap.description,
            context="Your answer will be recorded in the semantic bundle.",
            evidence=[],
            input_type="text",
            target_entity=gap.target_entity,
            target_property=gap.target_property,
        )

    _handlers = {
        GapCategory.UNKNOWN_BUSINESS_MEANING: _meaning_question,
        GapCategory.UNCONFIRMED_ENUM_MAPPING: _enum_question,
        GapCategory.MISSING_PRIMARY_KEY: _pk_question,
        GapCategory.AMBIGUOUS_RELATIONSHIP: _relationship_question,
        GapCategory.RELATIONSHIP_ROLE_UNCLEAR: _relationship_question,
        GapCategory.POTENTIAL_SENSITIVITY: _sensitivity_question,
        GapCategory.GLOSSARY_TERM_MISSING: _glossary_question,
    }
