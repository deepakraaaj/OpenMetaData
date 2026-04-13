from __future__ import annotations

from typing import Any

from sqlglot import exp, parse_one
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.models.semantic import BusinessRule, SemanticSourceModel, SemanticTable
from app.models.source import DiscoveredSource
from app.models.technical import SourceTechnicalMetadata, TableProfile
from app.models.validation import SqlValidationResult
from app.services.database import create_db_engine
from app.utils.text import tokenize


SQL_PREVIEW_LIMIT = 20
SQL_RESULT_LIMIT = 50


class SqlValidationService:
    def validate_question(
        self,
        *,
        source: DiscoveredSource,
        semantic: SemanticSourceModel,
        technical: SourceTechnicalMetadata,
        question: str,
    ) -> SqlValidationResult:
        intent, matched_table, matched_join, sql, warnings = self._build_sql(
            semantic=semantic,
            technical=technical,
            question=question,
        )
        safe_sql = self._ensure_safe_read_only(sql, dialect=self._sqlglot_dialect(source.connection.type.value))

        columns: list[str] = []
        rows: list[dict[str, Any]] = []
        row_count = 0
        error: str | None = None
        execution_status = "success"

        try:
            engine = create_db_engine(source.connection)
            with engine.connect() as conn:
                results = conn.execute(text(safe_sql)).mappings().all()
            rows = [self._json_safe_row(row) for row in results[:SQL_RESULT_LIMIT]]
            columns = list(rows[0].keys()) if rows else []
            row_count = len(rows)
        except SQLAlchemyError as exc:
            execution_status = "error"
            error = str(exc)

        warnings.extend(self._relevant_rule_notes(semantic.business_rules, matched_table, matched_join))

        return SqlValidationResult(
            source_name=source.name,
            question=question,
            intent=intent,
            matched_table=matched_table,
            matched_join=matched_join,
            sql=safe_sql,
            execution_status=execution_status,
            columns=columns,
            rows=rows,
            row_count=row_count,
            warnings=warnings,
            error=error,
        )

    def _build_sql(
        self,
        *,
        semantic: SemanticSourceModel,
        technical: SourceTechnicalMetadata,
        question: str,
    ) -> tuple[str, str | None, str | None, str, list[str]]:
        question_tokens = set(tokenize(question))
        table = self._match_table(semantic, question_tokens)
        if table is None:
            raise ValueError("Could not match the question to a reviewed table.")

        technical_table = self._technical_table(technical, table.table_name)
        if technical_table is None:
            raise ValueError(f"Technical metadata for table '{table.table_name}' is missing.")

        intent = self._detect_intent(question_tokens)
        join_value = self._match_join(table, semantic, question_tokens)
        warnings = [f"Matched `{table.table_name}` using semantic metadata and question token overlap."]
        if join_value:
            warnings.append(f"Including approved join `{join_value}`.")

        if intent == "status_breakdown":
            status_column = self._status_column(table, technical_table)
            if status_column:
                return (
                    intent,
                    table.table_name,
                    join_value,
                    (
                        f"SELECT {self._table_column(table.table_name, status_column)}, COUNT(*) AS total_records "
                        f"FROM {table.table_name} "
                        f"{self._join_clause(join_value)}"
                        f"GROUP BY {self._table_column(table.table_name, status_column)} "
                        "ORDER BY total_records DESC "
                        f"LIMIT {SQL_RESULT_LIMIT}"
                    ),
                    warnings,
                )
            warnings.append("No status-like column was confirmed, so this fell back to a recent-record preview.")
            intent = "recent_records"

        if intent == "count":
            return (
                intent,
                table.table_name,
                join_value,
                f"SELECT COUNT(*) AS total_records FROM {table.table_name} {self._join_clause(join_value)}",
                warnings,
            )

        if intent == "recent_records":
            timestamp_column = self._timestamp_column(table, technical_table)
            select_list = self._select_list(table, semantic, technical_table, join_value)
            order_clause = (
                f" ORDER BY {self._table_column(table.table_name, timestamp_column)} DESC"
                if timestamp_column
                else ""
            )
            return (
                intent,
                table.table_name,
                join_value,
                (
                    f"SELECT {select_list} FROM {table.table_name} "
                    f"{self._join_clause(join_value)}"
                    f"{order_clause} LIMIT {SQL_PREVIEW_LIMIT}"
                ),
                warnings,
            )

        select_list = self._select_list(table, semantic, technical_table, join_value)
        return (
            "list_preview",
            table.table_name,
            join_value,
            (
                f"SELECT {select_list} FROM {table.table_name} "
                f"{self._join_clause(join_value)}"
                f" LIMIT {SQL_PREVIEW_LIMIT}"
            ),
            warnings,
        )

    def _match_table(
        self,
        semantic: SemanticSourceModel,
        question_tokens: set[str],
    ) -> SemanticTable | None:
        scored: list[tuple[float, SemanticTable]] = []
        for table in semantic.tables:
            score = 0.0
            score += len(question_tokens & set(tokenize(table.table_name))) * 2.0
            score += len(question_tokens & set(tokenize(table.likely_entity or ""))) * 2.0
            score += len(question_tokens & set(tokenize(table.business_meaning or ""))) * 0.5
            for question in table.common_business_questions[:5]:
                score += len(question_tokens & set(tokenize(question))) * 0.25
            if table.selected:
                score += 0.5
            elif table.recommended_selected or table.selected_by_default:
                score += 0.2
            else:
                score -= 0.1
            if table.review_status == "confirmed":
                score += 0.25
            scored.append((score, table))
        scored.sort(key=lambda item: item[0], reverse=True)
        if scored and scored[0][0] > 0:
            return scored[0][1]
        fallback = next((table for table in semantic.tables if table.selected), None)
        if fallback is None:
            fallback = next(
                (
                    table
                    for table in semantic.tables
                    if table.recommended_selected or table.selected_by_default
                ),
                None,
            )
        if fallback is None and semantic.tables:
            fallback = semantic.tables[0]
        return fallback

    def _detect_intent(self, question_tokens: set[str]) -> str:
        if {"count", "many"} & question_tokens or ("how" in question_tokens and "many" in question_tokens):
            return "count"
        if "status" in question_tokens and ({"breakdown", "distribution", "group", "wise", "by"} & question_tokens):
            return "status_breakdown"
        if {"recent", "latest", "newest"} & question_tokens:
            return "recent_records"
        return "list_preview"

    def _match_join(
        self,
        table: SemanticTable,
        semantic: SemanticSourceModel,
        question_tokens: set[str],
    ) -> str | None:
        joins = list(table.valid_joins)
        if not joins:
            return None
        table_lookup = {item.table_name: item for item in semantic.tables}
        best_join = None
        best_score = 0.0
        for join_value in joins:
            related_tables = [name for name in self._tables_from_join(join_value) if name != table.table_name]
            if not related_tables:
                continue
            related_table = table_lookup.get(related_tables[0])
            score = len(question_tokens & set(tokenize(related_tables[0]))) * 2.0
            if related_table is not None:
                score += len(question_tokens & set(tokenize(related_table.likely_entity or ""))) * 2.0
                score += len(question_tokens & set(tokenize(related_table.business_meaning or ""))) * 0.5
            if score > best_score:
                best_score = score
                best_join = join_value
        return best_join if best_score > 0 else None

    def _join_clause(self, join_value: str | None) -> str:
        if not join_value:
            return ""
        left_side, right_side = [part.strip() for part in join_value.split("=", 1)]
        related_tables = self._tables_from_join(join_value)
        if len(related_tables) < 2:
            return ""
        right_table = related_tables[1]
        return f"JOIN {right_table} ON {left_side} = {right_side} "

    def _status_column(self, table: SemanticTable, technical_table: TableProfile) -> str | None:
        if technical_table.status_columns:
            return technical_table.status_columns[0]
        return next(
            (
                column.column_name
                for column in table.columns
                if "status" in column.column_name.lower()
            ),
            None,
        )

    def _timestamp_column(self, table: SemanticTable, technical_table: TableProfile) -> str | None:
        if technical_table.timestamp_columns:
            return technical_table.timestamp_columns[0]
        return next(
            (
                column.column_name
                for column in table.columns
                if any(token in column.column_name.lower() for token in ("created", "updated", "date", "time"))
            ),
            None,
        )

    def _select_list(
        self,
        table: SemanticTable,
        semantic: SemanticSourceModel,
        technical_table: TableProfile,
        join_value: str | None,
    ) -> str:
        selected_columns: list[str] = []
        for column_name in list(table.important_columns) + [column.column_name for column in table.columns]:
            if column_name not in selected_columns:
                selected_columns.append(column_name)
            if len(selected_columns) >= 5:
                break

        if not selected_columns:
            selected_columns = [column.name for column in technical_table.columns[:5]]

        expressions = [
            f"{self._table_column(table.table_name, column_name)} AS {table.table_name}_{column_name}"
            for column_name in selected_columns
        ]
        if join_value:
            related_tables = [name for name in self._tables_from_join(join_value) if name != table.table_name]
            related_table_name = related_tables[0] if related_tables else None
            related_table = next(
                (item for item in semantic.tables if item.table_name == related_table_name),
                None,
            )
            if related_table is not None:
                display_column = next(
                    (
                        column.column_name
                        for column in related_table.columns
                        if any(token in column.column_name.lower() for token in ("name", "label", "title", "code"))
                    ),
                    related_table.columns[0].column_name if related_table.columns else None,
                )
                if display_column:
                    expressions.append(
                        f"{self._table_column(related_table.table_name, display_column)} "
                        f"AS {related_table.table_name}_{display_column}"
                    )
        return ", ".join(expressions[:8])

    def _relevant_rule_notes(
        self,
        rules: list[BusinessRule],
        matched_table: str | None,
        matched_join: str | None,
    ) -> list[str]:
        if not matched_table:
            return []
        related_tables = {matched_table, *self._tables_from_join(matched_join or "")}
        notes = [
            f"Business rule: {rule.description}"
            for rule in rules
            if related_tables & set(rule.related_tables)
        ]
        return notes[:3]

    def _technical_table(
        self,
        technical: SourceTechnicalMetadata,
        table_name: str,
    ) -> TableProfile | None:
        for schema in technical.schemas:
            for table in schema.tables:
                if table.table_name == table_name:
                    return table
        return None

    def _table_column(self, table_name: str, column_name: str) -> str:
        return f"{table_name}.{column_name}"

    def _tables_from_join(self, join_value: str) -> list[str]:
        tables: list[str] = []
        for side in str(join_value or "").split("="):
            table_name = side.split(".")[0].strip()
            if table_name and table_name not in tables:
                tables.append(table_name)
        return tables

    def _ensure_safe_read_only(self, sql: str, *, dialect: str) -> str:
        statement = str(sql or "").strip().rstrip(";")
        if not statement:
            raise ValueError("Generated SQL was empty.")
        if ";" in statement:
            raise ValueError("Only single-statement read-only SQL is allowed.")

        expression = parse_one(statement, read=dialect)
        forbidden = (
            exp.Insert,
            exp.Update,
            exp.Delete,
            exp.Create,
            exp.Drop,
            exp.Alter,
            exp.Merge,
            exp.Command,
        )
        for node_type in forbidden:
            if expression.find(node_type) is not None:
                raise ValueError("Only read-only SELECT SQL is allowed.")
        if expression.find(exp.Select) is None:
            raise ValueError("Only SELECT SQL is allowed.")
        return expression.sql(dialect=dialect)

    def _sqlglot_dialect(self, db_type: str) -> str:
        if db_type == "postgresql":
            return "postgres"
        return db_type

    def _json_safe_row(self, row: Any) -> dict[str, Any]:
        return {
            str(key): self._json_safe_value(value)
            for key, value in dict(row).items()
        }

    def _json_safe_value(self, value: Any) -> Any:
        if value is None or isinstance(value, (bool, int, float, str)):
            return value
        if isinstance(value, bytes):
            return "<bytes>"
        return str(value)
