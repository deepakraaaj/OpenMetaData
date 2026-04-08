"""Convert a SemanticGap into a human-readable question with context."""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.models.state import GapCategory, KnowledgeState, SemanticGap


class GeneratedQuestion(BaseModel):
    gap_id: str
    question: str
    context: str = ""
    evidence: list[str] = Field(default_factory=list)
    input_type: str = "text"  # text, boolean, select, tags
    choices: list[str] = Field(default_factory=list)
    suggested_answer: str | None = None
    target_entity: str | None = None
    target_property: str | None = None


class QuestionGenerator:
    """Transforms a semantic gap into a natural, context-rich question."""

    def generate(self, gap: SemanticGap, state: KnowledgeState) -> GeneratedQuestion:
        handler = self._handlers.get(gap.category, self._default_question)
        return handler(self, gap, state)

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
        )

    def _sensitivity_question(self, gap: SemanticGap, state: KnowledgeState) -> GeneratedQuestion:
        return GeneratedQuestion(
            gap_id=gap.gap_id,
            question=gap.suggested_question or gap.description,
            context="Marking a column as sensitive will mask it in reports and prevent it from appearing in chatbot answers.",
            evidence=[],
            input_type="boolean",
            choices=["Yes, mask this column", "No, it is safe to display"],
            target_entity=gap.target_entity,
            target_property=gap.target_property,
        )

    def _glossary_question(self, gap: SemanticGap, state: KnowledgeState) -> GeneratedQuestion:
        return GeneratedQuestion(
            gap_id=gap.gap_id,
            question=gap.suggested_question or gap.description,
            context="Provide the real business term teams use in day-to-day conversations, dashboards, or SOPs.",
            evidence=[],
            input_type="text",
            target_entity=gap.target_entity,
            target_property=gap.target_property,
        )

    def _default_question(self, gap: SemanticGap, state: KnowledgeState) -> GeneratedQuestion:
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
