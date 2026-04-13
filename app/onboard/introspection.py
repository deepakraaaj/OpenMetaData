from __future__ import annotations

from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.core.logging import get_logger
from app.models.common import DatabaseType
from app.models.onboarding_job import (
    OnboardingLogLevel,
    OnboardingProgressUpdate,
    OnboardingStage,
    OnboardingStepState,
)
from app.models.source import DiscoveredSource
from app.models.technical import (
    CandidateJoin,
    ColumnProfile,
    ForeignKeyProfile,
    IndexProfile,
    SchemaProfile,
    SourceTechnicalMetadata,
    TableProfile,
    TopValueProfile,
)
from app.onboard.progress import ProgressCallback, emit_progress, technical_counts
from app.services.database import create_db_engine
from app.utils.enum_candidates import has_business_enum_signal, is_declared_enum_type
from app.utils.text import tokenize


LOGGER = get_logger(__name__)

SENSITIVE_NAME_PARTS = {
    "password",
    "secret",
    "token",
    "mobile",
    "phone",
    "email",
    "address",
    "aadhaar",
    "pan",
    "ssn",
    "dob",
}

PROFILE_ROW_LIMIT = 5_000
TOP_VALUES_LIMIT = 10
SAMPLE_VALUES_LIMIT = 12
JOIN_VALIDATION_SAMPLE_LIMIT = 200
JOIN_VALIDATION_LIMIT_PER_TABLE = 4


class DatabaseIntrospector:
    def introspect_source(
        self,
        source: DiscoveredSource,
        progress: ProgressCallback | None = None,
    ) -> SourceTechnicalMetadata:
        current_stage = OnboardingStage.CONNECTING_TO_DATABASE
        try:
            engine = create_db_engine(source.connection)
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            emit_progress(
                progress,
                OnboardingProgressUpdate(
                    stage=OnboardingStage.CONNECTING_TO_DATABASE,
                    step_state=OnboardingStepState.COMPLETED,
                    level=OnboardingLogLevel.SUCCESS,
                    message="Connected successfully. Credentials and network path are valid.",
                ),
            )
            current_stage = OnboardingStage.READING_SCHEMA
            emit_progress(
                progress,
                OnboardingProgressUpdate(
                    stage=OnboardingStage.READING_SCHEMA,
                    step_state=OnboardingStepState.RUNNING,
                    message="Reading schemas, columns, keys, and representative values.",
                ),
            )
            metadata = self._introspect(engine, source, progress=progress)
            metadata.connectivity_ok = True
            metadata.connectivity_notes.append("Connection test succeeded.")
            emit_progress(
                progress,
                OnboardingProgressUpdate(
                    stage=OnboardingStage.READING_SCHEMA,
                    step_state=OnboardingStepState.COMPLETED,
                    level=OnboardingLogLevel.SUCCESS,
                    message=(
                        f"Found {metadata.source_summary.get('table_count', 0)} tables and "
                        f"{metadata.source_summary.get('column_count', 0)} columns."
                    ),
                    counts=technical_counts(metadata),
                ),
            )
            return metadata
        except Exception as exc:
            LOGGER.exception("Failed to introspect %s", source.name)
            emit_progress(
                progress,
                OnboardingProgressUpdate(
                    stage=current_stage,
                    step_state=OnboardingStepState.ERROR,
                    level=OnboardingLogLevel.ERROR,
                    message=f"Introspection failed: {exc}",
                ),
            )
            return SourceTechnicalMetadata(
                source_name=source.name,
                db_type=source.connection.type,
                database_name=source.connection.database,
                connectivity_ok=False,
                connectivity_notes=[str(exc)],
            )

    def _introspect(
        self,
        engine: Engine,
        source: DiscoveredSource,
        progress: ProgressCallback | None = None,
    ) -> SourceTechnicalMetadata:
        inspector = inspect(engine)
        schema_names = self._schema_names(inspector, source)
        schemas: list[SchemaProfile] = []

        for schema_name in schema_names:
            schema_tables = inspector.get_table_names(schema=schema_name)
            emit_progress(
                progress,
                OnboardingProgressUpdate(
                    stage=OnboardingStage.READING_SCHEMA,
                    message=(
                        f"Inspecting schema `{schema_name or 'main'}` "
                        f"with {len(schema_tables)} tables."
                    ),
                ),
            )
            tables = []
            total_tables = len(schema_tables)
            for index, table_name in enumerate(schema_tables, start=1):
                table_profile = self._table_profile(engine, inspector, schema_name, table_name)
                if source.allow_tables and table_profile.table_name not in source.allow_tables:
                    continue
                tables.append(table_profile)
                if index == 1 or index % 10 == 0 or index == total_tables:
                    emit_progress(
                        progress,
                        OnboardingProgressUpdate(
                            stage=OnboardingStage.READING_SCHEMA,
                            message=(
                                f"Scanned {index}/{total_tables} tables in "
                                f"`{schema_name or 'main'}`."
                            ),
                        ),
                    )
            schemas.append(SchemaProfile(schema_name=schema_name or "main", tables=tables))

        self._attach_candidate_joins(engine, schemas)
        return SourceTechnicalMetadata(
            source_name=source.name,
            db_type=source.connection.type,
            database_name=source.connection.database,
            schemas=schemas,
            source_summary=self._source_summary(schemas),
        )

    def _schema_names(self, inspector: Any, source: DiscoveredSource) -> list[str | None]:
        connection = source.connection
        if connection.type in {DatabaseType.sqlite, DatabaseType.duckdb}:
            return ["main"]
        if connection.schema_name:
            return [connection.schema_name]

        system_schemas = {
            "information_schema",
            "pg_catalog",
            "pg_toast",
            "mysql",
            "performance_schema",
            "sys",
        }
        names = [name for name in inspector.get_schema_names() if name and name not in system_schemas]
        if connection.type == DatabaseType.mysql and connection.database:
            return [connection.database]

        default_schema = getattr(inspector, "default_schema_name", None)
        if default_schema and default_schema in names:
            return [default_schema]
        return names or [default_schema or None]

    def _table_profile(
        self,
        engine: Engine,
        inspector: Any,
        schema_name: str | None,
        table_name: str,
    ) -> TableProfile:
        pk = inspector.get_pk_constraint(table_name, schema=schema_name) or {}
        fks = inspector.get_foreign_keys(table_name, schema=schema_name) or []
        indexes = inspector.get_indexes(table_name, schema=schema_name) or []
        columns_meta = inspector.get_columns(table_name, schema=schema_name) or []
        estimated_row_count = self._estimated_row_count(engine, schema_name, table_name)

        column_profiles = self._column_profiles(
            engine=engine,
            schema_name=schema_name,
            table_name=table_name,
            columns_meta=columns_meta,
            primary_key=set(pk.get("constrained_columns") or []),
            foreign_keys=fks,
            estimated_row_count=estimated_row_count,
        )
        sample_rows = self._sample_rows(engine, schema_name, table_name, column_profiles)

        return TableProfile(
            schema_name=schema_name or "main",
            table_name=table_name,
            estimated_row_count=estimated_row_count,
            columns=column_profiles,
            primary_key=list(pk.get("constrained_columns") or []),
            foreign_keys=[
                ForeignKeyProfile(
                    name=fk.get("name"),
                    constrained_columns=list(fk.get("constrained_columns") or []),
                    referred_schema=fk.get("referred_schema"),
                    referred_table=fk.get("referred_table") or "",
                    referred_columns=list(fk.get("referred_columns") or []),
                )
                for fk in fks
            ],
            indexes=[
                IndexProfile(
                    name=index.get("name") or f"{table_name}_idx",
                    columns=list(index.get("column_names") or []),
                    unique=bool(index.get("unique")),
                )
                for index in indexes
            ],
            sample_rows=sample_rows,
            timestamp_columns=[column.name for column in column_profiles if column.is_timestamp_like],
            status_columns=[column.name for column in column_profiles if column.is_status_like],
        )

    def _column_profiles(
        self,
        engine: Engine,
        schema_name: str | None,
        table_name: str,
        columns_meta: list[dict[str, Any]],
        primary_key: set[str],
        foreign_keys: list[dict[str, Any]],
        estimated_row_count: int | None,
    ) -> list[ColumnProfile]:
        fk_map: dict[str, tuple[str | None, str | None]] = {}
        for fk in foreign_keys:
            for column_name, referred_column in zip(
                fk.get("constrained_columns") or [],
                fk.get("referred_columns") or [],
                strict=False,
            ):
                fk_map[column_name] = (fk.get("referred_table"), referred_column)

        profiles: list[ColumnProfile] = []
        for position, column in enumerate(columns_meta, start=1):
            name = str(column["name"])
            data_type = str(column["type"])
            profiling = self._profile_column(
                engine,
                schema_name,
                table_name,
                name,
                data_type,
                estimated_row_count=estimated_row_count,
            )
            sample_values = profiling["sample_values"]
            enum_values = sample_values if self._is_low_cardinality(sample_values, profiling["distinct_count"]) else []
            referenced_table, referenced_column = fk_map.get(name, (None, None))
            profiles.append(
                ColumnProfile(
                    name=name,
                    data_type=data_type,
                    nullable=bool(column.get("nullable", True)),
                    default=None if column.get("default") is None else str(column.get("default")),
                    ordinal_position=position,
                    is_primary_key=name in primary_key,
                    is_foreign_key=name in fk_map,
                    referenced_table=referenced_table,
                    referenced_column=referenced_column,
                    enum_values=enum_values,
                    sample_values=sample_values,
                    null_ratio=profiling["null_ratio"],
                    distinct_count=profiling["distinct_count"],
                    top_values=profiling["top_values"],
                    min_value=profiling["min_value"],
                    max_value=profiling["max_value"],
                    is_timestamp_like=self._is_timestamp_like(name, data_type),
                    is_status_like=self._is_status_like(name, data_type, sample_values),
                    is_identifier_like=self._is_identifier_like(name),
                )
            )
        return profiles

    def _sample_rows(
        self,
        engine: Engine,
        schema_name: str | None,
        table_name: str,
        columns: list[ColumnProfile],
    ) -> list[dict[str, Any]]:
        visible_columns = [column.name for column in columns if not self._is_sensitive_name(column.name)][:8]
        if not visible_columns:
            return []
        query = self._select_sql(engine, schema_name, table_name, visible_columns, limit=2)
        try:
            with engine.connect() as conn:
                rows = conn.execute(text(query)).mappings().all()
            return [{key: self._sanitize_value(key, value) for key, value in row.items()} for row in rows]
        except SQLAlchemyError:
            return []

    def _profile_column(
        self,
        engine: Engine,
        schema_name: str | None,
        table_name: str,
        column_name: str,
        data_type: str,
        *,
        estimated_row_count: int | None,
    ) -> dict[str, Any]:
        if self._is_sensitive_name(column_name):
            stats = self._column_stats(
                engine,
                schema_name,
                table_name,
                column_name,
                data_type,
                estimated_row_count=estimated_row_count,
            )
            return {
                "sample_values": ["<masked>"],
                "null_ratio": stats["null_ratio"],
                "distinct_count": stats["distinct_count"],
                "top_values": [],
                "min_value": None,
                "max_value": None,
            }

        stats = self._column_stats(
            engine,
            schema_name,
            table_name,
            column_name,
            data_type,
            estimated_row_count=estimated_row_count,
        )
        top_values = self._top_values(
            engine,
            schema_name,
            table_name,
            column_name,
            estimated_row_count=estimated_row_count,
        )
        sample_values = [item.value for item in top_values][:SAMPLE_VALUES_LIMIT]
        if not sample_values:
            sample_values = self._sample_column_values(engine, schema_name, table_name, column_name)
        return {
            "sample_values": sample_values,
            "null_ratio": stats["null_ratio"],
            "distinct_count": stats["distinct_count"],
            "top_values": top_values,
            "min_value": stats["min_value"],
            "max_value": stats["max_value"],
        }

    def _column_stats(
        self,
        engine: Engine,
        schema_name: str | None,
        table_name: str,
        column_name: str,
        data_type: str,
        *,
        estimated_row_count: int | None,
    ) -> dict[str, Any]:
        source_sql = self._profiling_source_sql(
            engine,
            schema_name,
            table_name,
            column_name,
            estimated_row_count=estimated_row_count,
        )
        quoted_column = self._quote(engine, column_name)
        include_min_max = self._supports_min_max(data_type)
        min_value = "MIN({column})".format(column=quoted_column) if include_min_max else "NULL"
        max_value = "MAX({column})".format(column=quoted_column) if include_min_max else "NULL"
        query = (
            "SELECT COUNT(*) AS total_rows, "
            f"SUM(CASE WHEN {quoted_column} IS NULL THEN 1 ELSE 0 END) AS null_count, "
            f"COUNT(DISTINCT {quoted_column}) AS distinct_count, "
            f"{min_value} AS min_value, "
            f"{max_value} AS max_value "
            f"FROM {source_sql}"
        )
        try:
            with engine.connect() as conn:
                row = conn.execute(text(query)).mappings().first()
        except SQLAlchemyError:
            return {
                "null_ratio": None,
                "distinct_count": None,
                "min_value": None,
                "max_value": None,
            }

        total_rows = int(row["total_rows"] or 0) if row else 0
        null_count = int(row["null_count"] or 0) if row else 0
        return {
            "null_ratio": round(null_count / total_rows, 4) if total_rows else None,
            "distinct_count": int(row["distinct_count"] or 0) if row and row["distinct_count"] is not None else None,
            "min_value": self._render_scalar(row["min_value"]) if row and row["min_value"] is not None else None,
            "max_value": self._render_scalar(row["max_value"]) if row and row["max_value"] is not None else None,
        }

    def _top_values(
        self,
        engine: Engine,
        schema_name: str | None,
        table_name: str,
        column_name: str,
        *,
        estimated_row_count: int | None,
    ) -> list[TopValueProfile]:
        source_sql = self._profiling_source_sql(
            engine,
            schema_name,
            table_name,
            column_name,
            estimated_row_count=estimated_row_count,
        )
        quoted_column = self._quote(engine, column_name)
        query = (
            f"SELECT {quoted_column} AS value, COUNT(*) AS value_count "
            f"FROM {source_sql} "
            f"WHERE {quoted_column} IS NOT NULL "
            f"GROUP BY {quoted_column} "
            f"ORDER BY value_count DESC, {quoted_column} "
            f"LIMIT {TOP_VALUES_LIMIT}"
        )
        try:
            with engine.connect() as conn:
                rows = conn.execute(text(query)).mappings().all()
        except SQLAlchemyError:
            return []
        return [
            TopValueProfile(value=self._render_scalar(row["value"]), count=int(row["value_count"] or 0))
            for row in rows
            if row["value"] is not None
        ]

    def _sample_column_values(
        self,
        engine: Engine,
        schema_name: str | None,
        table_name: str,
        column_name: str,
    ) -> list[str]:
        if self._is_sensitive_name(column_name):
            return ["<masked>"]
        query = self._distinct_sql(engine, schema_name, table_name, column_name, limit=SAMPLE_VALUES_LIMIT)
        try:
            with engine.connect() as conn:
                rows = conn.execute(text(query)).fetchall()
            return [
                self._render_scalar(value[0])
                for value in rows
                if value and value[0] is not None
            ][:SAMPLE_VALUES_LIMIT]
        except SQLAlchemyError:
            return []

    def _estimated_row_count(self, engine: Engine, schema_name: str | None, table_name: str) -> int | None:
        dialect = engine.dialect.name
        try:
            with engine.connect() as conn:
                if dialect == "mysql" and schema_name:
                    row = conn.execute(
                        text(
                            """
                            SELECT table_rows
                            FROM information_schema.tables
                            WHERE table_schema = :schema_name AND table_name = :table_name
                            """
                        ),
                        {"schema_name": schema_name, "table_name": table_name},
                    ).first()
                    return int(row[0]) if row and row[0] is not None else None

                row = conn.execute(
                    text(f"SELECT COUNT(*) FROM {self._quoted_name(engine, schema_name, table_name)}")
                ).first()
                return int(row[0]) if row else None
        except SQLAlchemyError:
            return None

    def _attach_candidate_joins(self, engine: Engine, schemas: list[SchemaProfile]) -> None:
        tables = [table for schema in schemas for table in schema.tables]
        table_names = {table.table_name: table for table in tables}
        pk_map = {
            table.table_name: set(table.primary_key or ["id"])
            for table in tables
        }

        for table in tables:
            joins: list[CandidateJoin] = []
            existing_fk_columns = {column.name for column in table.columns if column.is_foreign_key}
            for column in table.columns:
                if column.name in existing_fk_columns:
                    continue
                if not column.is_identifier_like or column.is_primary_key:
                    continue
                for target_name, target_table in table_names.items():
                    if target_name == table.table_name:
                        continue
                    score, reasons = self._candidate_join_score(table.table_name, column.name, target_table, pk_map)
                    if score < 0.4:
                        continue
                    target_pk = next(iter(pk_map[target_name]), "id")
                    joins.append(
                        CandidateJoin(
                            left_table=table.table_name,
                            left_column=column.name,
                            right_table=target_name,
                            right_column=target_pk,
                            confidence=round(score, 2),
                            reasons=reasons,
                        )
                    )
            joins.sort(key=lambda item: item.confidence, reverse=True)
            self._validate_candidate_joins(engine, table, table_names, joins)
            joins.sort(key=lambda item: item.confidence, reverse=True)
            table.candidate_joins = [join for join in joins if join.confidence >= 0.35][:12]

    def _validate_candidate_joins(
        self,
        engine: Engine,
        table: TableProfile,
        table_names: dict[str, TableProfile],
        joins: list[CandidateJoin],
    ) -> None:
        for join in joins[:JOIN_VALIDATION_LIMIT_PER_TABLE]:
            target_table = table_names.get(join.right_table)
            if target_table is None:
                continue
            overlap_ratio, sample_size = self._join_overlap_ratio(
                engine,
                left_schema=table.schema_name,
                left_table=join.left_table,
                left_column=join.left_column,
                right_schema=target_table.schema_name,
                right_table=join.right_table,
                right_column=join.right_column,
            )
            if overlap_ratio is None:
                continue
            join.validated_by_data = True
            join.overlap_ratio = overlap_ratio
            join.overlap_sample_size = sample_size
            join.reasons.append(
                f"sample overlap {round(overlap_ratio * 100)}% across {sample_size} distinct values"
            )
            if overlap_ratio >= 0.7:
                join.confidence = round(min(join.confidence + 0.18, 0.98), 2)
            elif overlap_ratio >= 0.35:
                join.confidence = round(min(join.confidence + 0.08, 0.95), 2)
            else:
                join.confidence = round(max(join.confidence - 0.18, 0.0), 2)

    def _join_overlap_ratio(
        self,
        engine: Engine,
        *,
        left_schema: str | None,
        left_table: str,
        left_column: str,
        right_schema: str | None,
        right_table: str,
        right_column: str,
    ) -> tuple[float | None, int | None]:
        left_values = self._join_distinct_values(
            engine,
            left_schema,
            left_table,
            left_column,
        )
        right_values = self._join_distinct_values(
            engine,
            right_schema,
            right_table,
            right_column,
        )
        if not left_values or not right_values:
            return None, None
        overlap = left_values & right_values
        sample_size = min(len(left_values), len(right_values))
        return round(len(overlap) / max(sample_size, 1), 4), sample_size

    def _join_distinct_values(
        self,
        engine: Engine,
        schema_name: str | None,
        table_name: str,
        column_name: str,
    ) -> set[str]:
        query = self._distinct_sql(
            engine,
            schema_name if schema_name != "main" else None,
            table_name,
            column_name,
            limit=JOIN_VALIDATION_SAMPLE_LIMIT,
        )
        try:
            with engine.connect() as conn:
                rows = conn.execute(text(query)).fetchall()
        except SQLAlchemyError:
            return set()
        return {
            self._render_scalar(value[0])
            for value in rows
            if value and value[0] is not None
        }

    def _candidate_join_score(
        self,
        table_name: str,
        column_name: str,
        target_table: TableProfile,
        pk_map: dict[str, set[str]],
    ) -> tuple[float, list[str]]:
        reasons: list[str] = []
        score = 0.0
        target_tokens = set(tokenize(target_table.table_name))
        column_tokens = set(tokenize(column_name))
        if "id" in column_tokens:
            score += 0.2
            reasons.append("identifier suffix")
        overlap = column_tokens & target_tokens
        if overlap:
            score += 0.45
            reasons.append(f"name overlap: {', '.join(sorted(overlap))}")
        singular = target_table.table_name.rstrip("s")
        if column_name == f"{singular}_id":
            score += 0.3
            reasons.append("singular foreign-key naming")
        if next(iter(pk_map[target_table.table_name]), "id") == "id":
            score += 0.1
            reasons.append("target uses conventional primary key")
        if table_name.rstrip("s") in column_name:
            score -= 0.15
            reasons.append("self-like identifier")
        return min(score, 0.95), reasons

    def _source_summary(self, schemas: list[SchemaProfile]) -> dict[str, Any]:
        tables = [table for schema in schemas for table in schema.tables]
        columns = [column for table in tables for column in table.columns]
        return {
            "schema_count": len(schemas),
            "table_count": len(tables),
            "column_count": len(columns),
            "tables_with_candidate_joins": sum(1 for table in tables if table.candidate_joins),
        }

    def _is_timestamp_like(self, name: str, data_type: str) -> bool:
        lowered = f"{name} {data_type}".lower()
        return any(token in lowered for token in ("timestamp", "datetime", "created", "updated", "deleted", "date"))

    def _is_status_like(self, name: str, data_type: str, sample_values: list[str]) -> bool:
        lowered = str(name or "").strip().lower()
        if lowered == "id" or lowered.endswith("_id"):
            return False
        if is_declared_enum_type(data_type):
            return True
        if has_business_enum_signal(name):
            return True
        return False

    def _is_identifier_like(self, name: str) -> bool:
        lowered = name.lower()
        return lowered == "id" or lowered.endswith("_id") or lowered.endswith("id")

    def _is_sensitive_name(self, name: str) -> bool:
        return any(part in name.lower() for part in SENSITIVE_NAME_PARTS)

    def _is_low_cardinality(self, values: list[str], distinct_count: int | None = None) -> bool:
        if distinct_count is not None:
            return 1 <= distinct_count <= 12
        if not values:
            return False
        unique_values = {value for value in values if value}
        return 1 <= len(unique_values) <= 12

    def _sanitize_value(self, key: str, value: Any) -> Any:
        if self._is_sensitive_name(key):
            return "<masked>"
        return self._render_scalar(value)

    def _render_scalar(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, bytes):
            return "<bytes>"
        return str(value)[:120]

    def _supports_min_max(self, data_type: str) -> bool:
        lowered = str(data_type or "").lower()
        return any(
            token in lowered
            for token in (
                "int",
                "numeric",
                "decimal",
                "float",
                "double",
                "real",
                "date",
                "time",
                "year",
            )
        )

    def _profiling_source_sql(
        self,
        engine: Engine,
        schema_name: str | None,
        table_name: str,
        column_name: str,
        *,
        estimated_row_count: int | None,
    ) -> str:
        quoted_table = self._quoted_table(engine, schema_name, table_name)
        quoted_column = self._quote(engine, column_name)
        if estimated_row_count is not None and estimated_row_count > PROFILE_ROW_LIMIT:
            return (
                f"(SELECT {quoted_column} FROM {quoted_table} "
                f"LIMIT {PROFILE_ROW_LIMIT}) AS profiling_source"
            )
        return quoted_table

    def _quoted_name(self, engine: Engine, schema_name: str | None, table_name: str, column_name: str | None = None) -> str:
        preparer = engine.dialect.identifier_preparer
        if column_name is None:
            if schema_name:
                return f"{preparer.quote_identifier(schema_name)}.{preparer.quote_identifier(table_name)}"
            return preparer.quote_identifier(table_name)
        if schema_name:
            return (
                f"{preparer.quote_identifier(schema_name)}."
                f"{preparer.quote_identifier(table_name)}."
                f"{preparer.quote_identifier(column_name)}"
            )
        return f"{preparer.quote_identifier(table_name)}.{preparer.quote_identifier(column_name)}"

    def _distinct_sql(
        self,
        engine: Engine,
        schema_name: str | None,
        table_name: str,
        column_name: str,
        limit: int,
    ) -> str:
        quoted_table = self._quoted_table(engine, schema_name, table_name)
        quoted_column = self._quote(engine, column_name)
        return (
            f"SELECT DISTINCT {quoted_column} FROM {quoted_table} "
            f"WHERE {quoted_column} IS NOT NULL LIMIT {limit}"
        )

    def _select_sql(
        self,
        engine: Engine,
        schema_name: str | None,
        table_name: str,
        columns: list[str],
        limit: int,
    ) -> str:
        quoted_table = self._quoted_table(engine, schema_name, table_name)
        select_list = ", ".join(self._quote(engine, column) for column in columns)
        return f"SELECT {select_list} FROM {quoted_table} LIMIT {limit}"

    def _quoted_table(self, engine: Engine, schema_name: str | None, table_name: str) -> str:
        preparer = engine.dialect.identifier_preparer
        if schema_name and schema_name != "main":
            return f"{preparer.quote_identifier(schema_name)}.{preparer.quote_identifier(table_name)}"
        return preparer.quote_identifier(table_name)

    def _quote(self, engine: Engine, identifier: str) -> str:
        return engine.dialect.identifier_preparer.quote_identifier(identifier)
