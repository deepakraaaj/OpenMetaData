from app.models.common import DatabaseType
from app.models.source import DiscoveredSource, SourceConnection
from app.models.technical import ColumnProfile, SchemaProfile, SourceTechnicalMetadata, TableProfile
from app.normalization.service import MetadataNormalizer
from app.semantics.service import SemanticGuessService


def _sample_source() -> tuple[DiscoveredSource, SourceTechnicalMetadata]:
    source = DiscoveredSource(
        name="fits_dev_march_9",
        connection=SourceConnection(type=DatabaseType.mysql, database="fits_dev_march_9"),
    )
    technical = SourceTechnicalMetadata(
        source_name="fits_dev_march_9",
        db_type=DatabaseType.mysql,
        database_name="fits_dev_march_9",
        connectivity_ok=True,
        schemas=[
            SchemaProfile(
                schema_name="fits_dev_march_9",
                tables=[
                    TableProfile(
                        schema_name="fits_dev_march_9",
                        table_name="maintenance_transaction",
                        estimated_row_count=100,
                        primary_key=["id"],
                        columns=[
                            ColumnProfile(name="id", data_type="int", is_primary_key=True, is_identifier_like=True),
                            ColumnProfile(name="facility_id", data_type="int", is_identifier_like=True, sample_values=["1", "2"]),
                            ColumnProfile(name="status", data_type="varchar", sample_values=["OPEN", "DONE"], is_status_like=True),
                            ColumnProfile(name="created_at", data_type="datetime", is_timestamp_like=True),
                        ],
                    ),
                    TableProfile(
                        schema_name="fits_dev_march_9",
                        table_name="facility",
                        estimated_row_count=25,
                        primary_key=["id"],
                        columns=[
                            ColumnProfile(name="id", data_type="int", is_primary_key=True, is_identifier_like=True),
                            ColumnProfile(name="name", data_type="varchar", sample_values=["North Depot"]),
                        ],
                    ),
                ],
            )
        ],
    )
    return source, technical


def test_semantic_enrichment_produces_domain_and_tables() -> None:
    source, technical = _sample_source()
    normalized = MetadataNormalizer().normalize(source, technical)
    semantic = SemanticGuessService().enrich(normalized)

    assert semantic.domain in {"maintenance", "operations"}
    assert semantic.tables
    assert semantic.tables[0].business_meaning
    assert semantic.tables[0].columns[0].business_meaning

