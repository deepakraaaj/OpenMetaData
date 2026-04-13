from __future__ import annotations

from collections import Counter

from app.models.normalized import NormalizedColumn, NormalizedSource, NormalizedTable
from app.models.source import DiscoveredSource
from app.models.technical import SourceTechnicalMetadata
from app.utils.text import tokenize


SENSITIVE_HINTS = {
    "email": "contains email-like content",
    "phone": "contains phone-like content",
    "mobile": "contains phone-like content",
    "password": "contains secret credential content",
    "token": "contains token-like content",
    "address": "contains location or address content",
}


class MetadataNormalizer:
    def normalize(self, source: DiscoveredSource, technical: SourceTechnicalMetadata) -> NormalizedSource:
        tables: list[NormalizedTable] = []
        domain_tokens: list[str] = []

        for schema in technical.schemas:
            for table in schema.tables:
                table_tokens = tokenize(table.table_name)
                domain_tokens.extend(table_tokens)
                normalized_columns: list[NormalizedColumn] = []
                for column in table.columns:
                    sensitivity_hints = [
                        hint
                        for token, hint in SENSITIVE_HINTS.items()
                        if token in column.name.lower()
                    ]
                    normalized_columns.append(
                        NormalizedColumn(
                            schema_name=schema.schema_name,
                            table_name=table.table_name,
                            column_name=column.name,
                            technical_type=column.data_type,
                            tokens=tokenize(column.name),
                            sample_values=column.sample_values,
                            enum_values=column.enum_values,
                            null_ratio=column.null_ratio,
                            distinct_count=column.distinct_count,
                            top_values=[item.value for item in column.top_values],
                            min_value=column.min_value,
                            max_value=column.max_value,
                            is_primary_key=column.is_primary_key,
                            is_foreign_key=column.is_foreign_key,
                            is_identifier_like=column.is_identifier_like,
                            is_status_like=column.is_status_like,
                            is_timestamp_like=column.is_timestamp_like,
                            sensitivity_hints=sensitivity_hints,
                        )
                    )
                tables.append(
                    NormalizedTable(
                        schema_name=schema.schema_name,
                        table_name=table.table_name,
                        tokens=table_tokens,
                        row_count=table.estimated_row_count,
                        primary_key=table.primary_key,
                        foreign_keys=[
                            f"{fk.referred_table}({','.join(fk.constrained_columns)})" for fk in table.foreign_keys
                        ],
                        join_candidates=[
                            f"{join.left_table}.{join.left_column}={join.right_table}.{join.right_column}"
                            for join in table.candidate_joins
                        ],
                        filters=[
                            column.name
                            for column in table.columns
                            if column.is_status_like or column.is_timestamp_like
                        ],
                        grain_hint=self._grain_hint(table.table_name),
                        entity_hint=self._entity_hint(table.table_name),
                        columns=normalized_columns,
                    )
                )

        common_tokens = [
            token
            for token, count in Counter(domain_tokens).most_common(12)
            if count > 1 and token not in {"id", "log", "mapping", "detail"}
        ]
        return NormalizedSource(
            source_name=source.name,
            db_type=source.connection.type.value,
            database_name=source.connection.database,
            domain_hints=common_tokens[:8],
            tables=tables,
            summary={
                "table_count": len(tables),
                "column_count": sum(len(table.columns) for table in tables),
            },
        )

    def _grain_hint(self, table_name: str) -> str:
        singular = table_name.rstrip("s")
        if table_name.endswith("_mapping"):
            return f"One row per relationship in {table_name}."
        if table_name.endswith("_history") or table_name.endswith("_log"):
            return f"One row per {singular.replace('_', ' ')} event."
        return f"One row per {singular.replace('_', ' ')}."

    def _entity_hint(self, table_name: str) -> str:
        return table_name.rstrip("s").replace("_", " ").title()
