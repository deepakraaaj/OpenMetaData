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


class QuestionGenerator:
    """Transforms a semantic gap into a natural, context-rich question."""

    def generate(self, gap: SemanticGap, state: KnowledgeState) -> GeneratedQuestion:
        handler = self._handlers.get(gap.category, self._default_question)
        return handler(self, gap, state)

    def _meaning_question(self, gap: SemanticGap, state: KnowledgeState) -> GeneratedQuestion:
        evidence: list[str] = []
        suggested = None

        if gap.target_property:
            # Column-level
            table = state.tables.get(gap.target_entity or "")
            if table:
                col = next((c for c in table.columns if c.column_name == gap.target_property), None)
                if col:
                    if col.business_meaning:
                        suggested = col.business_meaning
                        evidence.append(f"System guess: {col.business_meaning}")
                    if col.example_values:
                        evidence.append(f"Sample values: {', '.join(col.example_values[:5])}")
                    evidence.append(f"Type: {col.technical_type}")
        else:
            # Table-level
            table = state.tables.get(gap.target_entity or "")
            if table:
                if table.business_meaning:
                    suggested = table.business_meaning
                    evidence.append(f"System guess: {table.business_meaning}")
                if table.grain:
                    evidence.append(f"Grain: {table.grain}")
                if table.important_columns:
                    evidence.append(f"Key columns: {', '.join(table.important_columns[:5])}")

        return GeneratedQuestion(
            gap_id=gap.gap_id,
            question=gap.suggested_question or gap.description,
            context="Help the system understand the business meaning so it can generate accurate queries.",
            evidence=evidence,
            input_type="text",
            suggested_answer=suggested,
        )

    def _enum_question(self, gap: SemanticGap, state: KnowledgeState) -> GeneratedQuestion:
        evidence: list[str] = []
        choices: list[str] = []

        table = state.tables.get(gap.target_entity or "")
        if table and gap.target_property:
            col = next((c for c in table.columns if c.column_name == gap.target_property), None)
            if col and col.example_values:
                choices = col.example_values[:10]
                evidence.append(f"Discovered values: {', '.join(choices)}")

        existing_enums = state.enums.get(f"{gap.target_entity}.{gap.target_property}", [])
        if existing_enums:
            evidence.append(f"Current mappings: {', '.join(f'{e.database_value}→{e.business_label}' for e in existing_enums)}")

        return GeneratedQuestion(
            gap_id=gap.gap_id,
            question=gap.suggested_question or gap.description,
            context="Provide the business label for each value (e.g., '0=Pending, 1=Active, 2=Closed').",
            evidence=evidence,
            input_type="tags",
            choices=choices,
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
        )

    def _relationship_question(self, gap: SemanticGap, state: KnowledgeState) -> GeneratedQuestion:
        return GeneratedQuestion(
            gap_id=gap.gap_id,
            question=gap.suggested_question or gap.description,
            context="Confirming this join ensures the system generates correct multi-table queries.",
            evidence=[f"Inferred join: {gap.target_property}"] if gap.target_property else [],
            input_type="boolean",
            choices=["Yes, this is valid", "No, this is incorrect"],
        )

    def _sensitivity_question(self, gap: SemanticGap, state: KnowledgeState) -> GeneratedQuestion:
        return GeneratedQuestion(
            gap_id=gap.gap_id,
            question=gap.suggested_question or gap.description,
            context="Marking a column as sensitive will mask it in reports and prevent it from appearing in chatbot answers.",
            evidence=[],
            input_type="boolean",
            choices=["Yes, mask this column", "No, it is safe to display"],
        )

    def _glossary_question(self, gap: SemanticGap, state: KnowledgeState) -> GeneratedQuestion:
        return GeneratedQuestion(
            gap_id=gap.gap_id,
            question=gap.suggested_question or gap.description,
            context="Adding user-facing terms helps the chatbot understand questions phrased in business language.",
            evidence=[],
            input_type="text",
        )

    def _default_question(self, gap: SemanticGap, state: KnowledgeState) -> GeneratedQuestion:
        return GeneratedQuestion(
            gap_id=gap.gap_id,
            question=gap.suggested_question or gap.description,
            context="Your answer will be recorded in the semantic bundle.",
            evidence=[],
            input_type="text",
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
