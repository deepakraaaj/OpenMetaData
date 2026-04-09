from __future__ import annotations

from app.core.inference_rules import SemanticInferenceRules, load_inference_rules
from app.models.questionnaire import QuestionnaireBundle
from app.models.semantic import SemanticSourceModel
from app.semantics.ambiguity_compressor import AmbiguityCompressor


class AmbiguityDetector:
    def __init__(self, rules: SemanticInferenceRules | None = None) -> None:
        self.rules = rules or load_inference_rules()
        self.compressor = AmbiguityCompressor()

    def generate_questions(self, semantic: SemanticSourceModel) -> QuestionnaireBundle:
        return QuestionnaireBundle(
            source_name=semantic.source_name,
            questions=self.compressor.build_questions(semantic),
        )
