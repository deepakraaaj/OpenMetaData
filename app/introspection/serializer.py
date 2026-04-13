from __future__ import annotations

from pathlib import Path

from app.models.technical import SourceTechnicalMetadata
from app.utils.enum_candidates import is_enum_candidate
from app.utils.serialization import write_json


class IntrospectionSerializer:
    def __init__(
        self,
        metadata: SourceTechnicalMetadata,
        output_dir: Path,
        *,
        include_bundle: bool = True,
        bundle_filename: str = "technical_metadata_bundle.json",
    ):
        self.metadata = metadata
        self.output_dir = output_dir
        self.include_bundle = include_bundle
        self.bundle_filename = bundle_filename
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _write_json(self, name: str, data: list | dict | SourceTechnicalMetadata) -> None:
        write_json(self.output_dir / name, data)

    def build_artifacts(self) -> dict[str, list[dict] | SourceTechnicalMetadata]:
        """Slices the unified SourceTechnicalMetadata into distinct artifacts."""
        tables_data: list[dict] = []
        columns_data: list[dict] = []
        relationships_data: list[dict] = []
        profiling_data: list[dict] = []
        enum_candidates_data: list[dict] = []

        for schema_profile in self.metadata.schemas:
            schema_name = schema_profile.schema_name
            for table_profile in schema_profile.tables:
                table_name = table_profile.table_name

                tables_data.append(
                    {
                        "schema": schema_name,
                        "table": table_name,
                        "table_type": table_profile.table_type,
                        "estimated_row_count": table_profile.estimated_row_count,
                        "primary_key": table_profile.primary_key,
                        "indexes": [
                            {
                                "name": index.name,
                                "columns": index.columns,
                                "unique": index.unique,
                            }
                            for index in table_profile.indexes
                        ],
                        "timestamp_columns": table_profile.timestamp_columns,
                        "status_columns": table_profile.status_columns,
                    }
                )

                profiling_data.append(
                    {
                        "schema": schema_name,
                        "table": table_name,
                        "estimated_row_count": table_profile.estimated_row_count,
                        "sample_rows": table_profile.sample_rows,
                        "columns": [
                            {
                                "column": column.name,
                                "nullable": column.nullable,
                                "sample_values": column.sample_values,
                                "enum_values": column.enum_values,
                                "null_ratio": column.null_ratio,
                                "distinct_count": column.distinct_count,
                                "top_values": [item.model_dump(mode="json") for item in column.top_values],
                                "min_value": column.min_value,
                                "max_value": column.max_value,
                                "is_identifier_like": column.is_identifier_like,
                                "is_status_like": column.is_status_like,
                                "is_timestamp_like": column.is_timestamp_like,
                            }
                            for column in table_profile.columns
                        ],
                    }
                )

                for fk in table_profile.foreign_keys:
                    relationships_data.append(
                        {
                            "relationship_type": "foreign_key",
                            "name": fk.name,
                            "source_schema": schema_name,
                            "source_table": table_name,
                            "source_columns": fk.constrained_columns,
                            "target_schema": fk.referred_schema,
                            "target_table": fk.referred_table,
                            "target_columns": fk.referred_columns,
                            "confidence": 1.0,
                            "reasons": ["declared foreign key"],
                        }
                    )

                for join in table_profile.candidate_joins:
                    relationships_data.append(
                        {
                            "relationship_type": "candidate_join",
                            "source_schema": schema_name,
                            "source_table": join.left_table,
                            "source_columns": [join.left_column],
                            "target_schema": schema_name,
                            "target_table": join.right_table,
                            "target_columns": [join.right_column],
                            "confidence": join.confidence,
                            "reasons": join.reasons,
                            "validated_by_data": join.validated_by_data,
                            "overlap_ratio": join.overlap_ratio,
                            "overlap_sample_size": join.overlap_sample_size,
                        }
                    )

                for col in table_profile.columns:
                    col_data = col.model_dump(mode="json", exclude_none=True)
                    col_data["schema"] = schema_name
                    col_data["table"] = table_name
                    columns_data.append(col_data)

                    if is_enum_candidate(
                        column_name=col.name,
                        technical_type=col.data_type,
                        values=col.enum_values or col.sample_values,
                        is_foreign_key=col.is_foreign_key,
                        lookup_backed=bool(col.referenced_table),
                    ):
                        enum_candidates_data.append(
                            {
                                "schema": schema_name,
                                "table": table_name,
                                "column": col.name,
                                "data_type": col.data_type,
                                "enum_values": col.enum_values,
                                "sample_values": col.sample_values,
                                "status_like": col.is_status_like,
                            }
                        )

        artifacts: dict[str, list[dict] | SourceTechnicalMetadata] = {
            "tables.json": tables_data,
            "columns.json": columns_data,
            "relationships.json": relationships_data,
            "profiling.json": profiling_data,
            "enum_candidates.json": enum_candidates_data,
        }
        if self.include_bundle:
            artifacts[self.bundle_filename] = self.metadata
        return artifacts

    def serialize(self) -> None:
        for name, payload in self.build_artifacts().items():
            self._write_json(name, payload)
