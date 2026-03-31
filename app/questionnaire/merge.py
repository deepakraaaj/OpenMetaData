from __future__ import annotations

from pathlib import Path

import typer

from app.core.settings import get_settings
from app.models.common import SensitivityLabel
from app.models.questionnaire import QuestionnaireBundle, QuestionnaireMergeResult
from app.models.semantic import SemanticSourceModel
from app.repositories.filesystem import WorkspaceRepository
from app.utils.serialization import read_json, read_yaml, write_json


class QuestionnaireMergeService:
    def merge(self, semantic: SemanticSourceModel, bundle: QuestionnaireBundle) -> QuestionnaireMergeResult:
        applied = 0
        updated_tables: set[str] = set()
        updated_columns: set[str] = set()

        table_map = {table.table_name: table for table in semantic.tables}

        for question in bundle.questions:
            if question.answer in (None, "", []):
                continue
            applied += 1
            if question.type == "table_business_meaning" and question.table and question.table in table_map:
                table_map[question.table].business_meaning = str(question.answer)
                updated_tables.add(question.table)
            elif question.type == "column_business_meaning" and question.table and question.column:
                table = table_map.get(question.table)
                if table:
                    for column in table.columns:
                        if column.column_name == question.column:
                            column.business_meaning = str(question.answer)
                            updated_columns.add(f"{question.table}.{question.column}")
            elif question.type == "sensitivity_classification" and question.table and question.column:
                table = table_map.get(question.table)
                if table:
                    for column in table.columns:
                        if column.column_name == question.column:
                            answer = str(question.answer).lower()
                            column.sensitive = (
                                SensitivityLabel.sensitive if answer in {"yes", "true", "sensitive"} else SensitivityLabel.none
                            )
                            updated_columns.add(f"{question.table}.{question.column}")
            elif question.type == "relationship_validation" and question.table is None and question.suggested_join:
                if str(question.answer).lower() in {"yes", "true", "valid"}:
                    left_table = question.left_table or question.suggested_join.split("=")[0].split(".")[0]
                    if left_table in table_map and question.suggested_join not in table_map[left_table].valid_joins:
                        table_map[left_table].valid_joins.append(question.suggested_join)
                        updated_tables.add(left_table)

        return QuestionnaireMergeResult(
            source_name=semantic.source_name,
            applied_answers=applied,
            updated_tables=sorted(updated_tables),
            updated_columns=sorted(updated_columns),
            notes=["Merged questionnaire answers into semantic model."],
        )


app = typer.Typer(add_completion=False, help="Merge a filled questionnaire into the semantic model.")


@app.command()
def main(file: Path = typer.Option(..., help="Path to a filled questionnaire JSON or YAML file.")) -> None:
    settings = get_settings()
    repository = WorkspaceRepository(settings.config_dir, settings.output_dir)
    payload = read_json(file) if file.suffix == ".json" else read_yaml(file)
    bundle = QuestionnaireBundle.model_validate(payload)
    semantic = repository.load_semantic_model(bundle.source_name)
    result = QuestionnaireMergeService().merge(semantic, bundle)
    repository.save_semantic_model(semantic)
    output_path = repository.source_dir(bundle.source_name) / "questionnaire_merge_result.json"
    write_json(output_path, result)
    typer.echo(f"Merged {result.applied_answers} answers for {bundle.source_name} -> {output_path}")


if __name__ == "__main__":
    app()
