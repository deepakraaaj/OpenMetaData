from __future__ import annotations

from pathlib import Path

import typer

from app.core.settings import get_settings
from app.models.common import SensitivityLabel
from app.models.questionnaire import QuestionnaireBundle, QuestionnaireMergeResult
from app.models.review import TableReviewDecision, TableRole
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
            resolved_answer = self._resolved_answer(question)
            if resolved_answer in (None, "", []):
                continue
            applied += 1
            if question.type == "table_business_meaning" and question.table and question.table in table_map:
                table_map[question.table].business_meaning = str(resolved_answer)
                updated_tables.add(question.table)
            elif question.type == "table_role_confirmation" and question.table and question.table in table_map:
                answer = str(resolved_answer).strip()
                if answer in {role.value for role in TableRole}:
                    table_map[question.table].role = TableRole(answer)
                    updated_tables.add(question.table)
            elif question.type == "domain_cluster_confirmation":
                domain_label = str(resolved_answer).strip()
                member_tables = question.metadata.get("member_tables", []) if isinstance(question.metadata, dict) else []
                if domain_label and isinstance(member_tables, list):
                    for table_name in member_tables:
                        if table_name in table_map:
                            table_map[table_name].domain = domain_label
                            updated_tables.add(table_name)
            elif question.type.endswith("_pattern_confirmation"):
                member_tables = question.metadata.get("member_tables", []) if isinstance(question.metadata, dict) else []
                role = str(question.metadata.get("role", "")) if isinstance(question.metadata, dict) else ""
                if isinstance(member_tables, list):
                    for table_name in member_tables:
                        table = table_map.get(str(table_name))
                        if table is None:
                            continue
                        answer = str(resolved_answer).strip().lower()
                        if answer in {"exclude_pattern", "confirm_pattern"} and role in {
                            TableRole.log_event.value,
                            TableRole.history_audit.value,
                            TableRole.config_system.value,
                        }:
                            table.selected = False
                            table.review_decision = TableReviewDecision.excluded
                            table.needs_review = False
                        elif answer in {"keep_selected", "treat_as_business"}:
                            table.selected = True
                            table.review_decision = TableReviewDecision.selected
                        updated_tables.add(table_name)
            elif question.type == "column_business_meaning" and question.table and question.column:
                table = table_map.get(question.table)
                if table:
                    for column in table.columns:
                        if column.column_name == question.column:
                            column.business_meaning = str(resolved_answer)
                            updated_columns.add(f"{question.table}.{question.column}")
            elif question.type == "sensitivity_classification" and question.table and question.column:
                table = table_map.get(question.table)
                if table:
                    for column in table.columns:
                        if column.column_name == question.column:
                            answer = str(resolved_answer).lower()
                            column.sensitive = (
                                SensitivityLabel.sensitive
                                if answer in {"yes", "true", "sensitive", "mask", "mask this column"}
                                else SensitivityLabel.none
                            )
                            updated_columns.add(f"{question.table}.{question.column}")
            elif (
                question.type in {"relationship_validation", "relationship_disambiguation"}
                and question.table
                and question.column
            ):
                table = table_map.get(question.table)
                candidate_joins = question.metadata.get("candidate_joins", {}) if isinstance(question.metadata, dict) else {}
                if table and isinstance(candidate_joins, dict):
                    selected = str(resolved_answer).strip().lower()
                    selected_join = None
                    for table_name, join in candidate_joins.items():
                        join_value = str(join)
                        if join_value in table.valid_joins:
                            table.valid_joins.remove(join_value)
                        if selected == str(table_name).strip().lower():
                            selected_join = join_value
                    if selected_join and selected_join not in table.valid_joins:
                        table.valid_joins.append(selected_join)
                        updated_tables.add(question.table)
            elif question.type == "relationship_validation" and question.table is None and question.suggested_join:
                if str(resolved_answer).lower() in {"yes", "true", "valid", "confirm", "__confirm__"}:
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

    def _resolved_answer(self, question) -> str | bool | list[str] | None:
        answer = question.answer
        if answer in (None, "", []):
            return answer
        if isinstance(answer, str):
            normalized = answer.strip().lower()
            if normalized in {"skip", "__skip__"}:
                return None
            if normalized in {"confirm", "__confirm__"} and (question.suggested_answer or question.best_guess):
                selected_value = question.suggested_answer or question.best_guess
                if question.type == "sensitivity_classification":
                    return "mask"
                if question.type == "relationship_validation" and question.best_guess:
                    return question.best_guess
                return selected_value
            for option in question.candidate_options:
                if normalized in {str(option.value or "").strip().lower(), str(option.label or "").strip().lower()}:
                    return option.value or option.label
        return answer


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
