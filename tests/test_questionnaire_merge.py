from app.models.common import ConfidenceLabel, NamedConfidence, SensitivityLabel
from app.models.questionnaire import QuestionnaireBundle, QuestionnaireQuestion
from app.models.semantic import SemanticColumn, SemanticSourceModel, SemanticTable
from app.questionnaire.merge import QuestionnaireMergeService


def test_questionnaire_merge_updates_semantic_model() -> None:
    semantic = SemanticSourceModel(
        source_name="vts",
        db_type="mysql",
        tables=[
            SemanticTable(
                table_name="driver",
                business_meaning="Primary driver records.",
                columns=[
                    SemanticColumn(
                        column_name="mobile_number",
                        technical_type="varchar",
                        business_meaning="Driver mobile number",
                        sensitive=SensitivityLabel.possible_sensitive,
                        confidence=NamedConfidence(label=ConfidenceLabel.medium, score=0.6),
                    )
                ],
            )
        ],
    )
    bundle = QuestionnaireBundle(
        source_name="vts",
        questions=[
            QuestionnaireQuestion(
                type="sensitivity_classification",
                table="driver",
                column="mobile_number",
                question="Should driver.mobile_number be masked?",
                answer="yes",
            )
        ],
    )

    result = QuestionnaireMergeService().merge(semantic, bundle)
    assert result.applied_answers == 1
    assert semantic.tables[0].columns[0].sensitive == SensitivityLabel.sensitive
