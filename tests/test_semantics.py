from app.core.inference_rules import CommunicationDirectoryRules, SemanticInferenceRules
from app.models.common import DatabaseType
from app.models.source import DiscoveredSource, SourceConnection
from app.models.technical import CandidateJoin, ColumnProfile, SchemaProfile, SourceTechnicalMetadata, TableProfile
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


def test_semantic_enrichment_inferrs_audit_actor_user_reference() -> None:
    source = DiscoveredSource(
        name="vts_demo",
        connection=SourceConnection(type=DatabaseType.mysql, database="vts_demo"),
    )
    technical = SourceTechnicalMetadata(
        source_name="vts_demo",
        db_type=DatabaseType.mysql,
        database_name="vts_demo",
        connectivity_ok=True,
        schemas=[
            SchemaProfile(
                schema_name="vts_demo",
                tables=[
                    TableProfile(
                        schema_name="vts_demo",
                        table_name="alert_cfg",
                        primary_key=["id"],
                        columns=[
                            ColumnProfile(name="id", data_type="int", is_primary_key=True, is_identifier_like=True),
                            ColumnProfile(name="created_by", data_type="int", sample_values=["11784212"]),
                        ],
                    ),
                    TableProfile(
                        schema_name="vts_demo",
                        table_name="user",
                        primary_key=["id"],
                        columns=[
                            ColumnProfile(name="id", data_type="int", is_primary_key=True, is_identifier_like=True),
                            ColumnProfile(name="name", data_type="varchar", sample_values=["Deepak"]),
                        ],
                    ),
                ],
            )
        ],
    )

    normalized = MetadataNormalizer().normalize(source, technical)
    semantic = SemanticGuessService().enrich(normalized)

    alert_cfg = next(table for table in semantic.tables if table.table_name == "alert_cfg")
    created_by = next(column for column in alert_cfg.columns if column.column_name == "created_by")

    assert created_by.business_meaning == "User who created this alert cfg record."
    assert created_by.confidence.score >= 0.9


def test_semantic_enrichment_treats_status_foreign_key_as_status_reference() -> None:
    source = DiscoveredSource(
        name="vts_demo",
        connection=SourceConnection(type=DatabaseType.mysql, database="vts_demo"),
    )
    technical = SourceTechnicalMetadata(
        source_name="vts_demo",
        db_type=DatabaseType.mysql,
        database_name="vts_demo",
        connectivity_ok=True,
        schemas=[
            SchemaProfile(
                schema_name="vts_demo",
                tables=[
                    TableProfile(
                        schema_name="vts_demo",
                        table_name="trip",
                        primary_key=["id"],
                        columns=[
                            ColumnProfile(name="id", data_type="int", is_primary_key=True, is_identifier_like=True),
                            ColumnProfile(
                                name="recent_state_id",
                                data_type="int",
                                is_foreign_key=True,
                                enum_values=["10", "20", "30"],
                                sample_values=["10", "20", "30"],
                                is_status_like=True,
                            ),
                        ],
                    ),
                    TableProfile(
                        schema_name="vts_demo",
                        table_name="trip_status_master",
                        primary_key=["id"],
                        columns=[
                            ColumnProfile(name="id", data_type="int", is_primary_key=True, is_identifier_like=True),
                            ColumnProfile(name="display_type", data_type="varchar", sample_values=["Created", "En route", "Reached"]),
                        ],
                    ),
                ],
            )
        ],
    )

    normalized = MetadataNormalizer().normalize(source, technical)
    semantic = SemanticGuessService().enrich(normalized)

    trip = next(table for table in semantic.tables if table.table_name == "trip")
    recent_state_id = next(column for column in trip.columns if column.column_name == "recent_state_id")

    assert recent_state_id.business_meaning == "Reference to the workflow or lifecycle state for the record."
    assert recent_state_id.example_values == ["10", "20", "30"]


def test_semantic_enrichment_inferrs_support_directory_meaning_without_table_name_hardcode() -> None:
    source = DiscoveredSource(
        name="vts_demo",
        connection=SourceConnection(type=DatabaseType.mysql, database="vts_demo"),
    )
    technical = SourceTechnicalMetadata(
        source_name="vts_demo",
        db_type=DatabaseType.mysql,
        database_name="vts_demo",
        connectivity_ok=True,
        schemas=[
            SchemaProfile(
                schema_name="vts_demo",
                tables=[
                    TableProfile(
                        schema_name="vts_demo",
                        table_name="service_reachability",
                        primary_key=["id"],
                        columns=[
                            ColumnProfile(name="id", data_type="int", is_primary_key=True, is_identifier_like=True),
                            ColumnProfile(name="company_id", data_type="int", is_identifier_like=True),
                            ColumnProfile(name="state_office_id", data_type="int", is_identifier_like=True),
                            ColumnProfile(name="customer_support_mobile_number", data_type="varchar", sample_values=["9999999999"]),
                            ColumnProfile(name="operations_support_mobile_number", data_type="varchar", sample_values=["8888888888"]),
                        ],
                        candidate_joins=[
                            CandidateJoin(
                                left_table="service_reachability",
                                left_column="company_id",
                                right_table="company",
                                right_column="id",
                                confidence=0.95,
                            ),
                            CandidateJoin(
                                left_table="service_reachability",
                                left_column="state_office_id",
                                right_table="state_office",
                                right_column="id",
                                confidence=0.95,
                            ),
                        ],
                    ),
                    TableProfile(
                        schema_name="vts_demo",
                        table_name="company",
                        primary_key=["id"],
                        columns=[ColumnProfile(name="id", data_type="int", is_primary_key=True, is_identifier_like=True)],
                    ),
                    TableProfile(
                        schema_name="vts_demo",
                        table_name="state_office",
                        primary_key=["id"],
                        columns=[ColumnProfile(name="id", data_type="int", is_primary_key=True, is_identifier_like=True)],
                    ),
                ],
            )
        ],
    )

    normalized = MetadataNormalizer().normalize(source, technical)
    semantic = SemanticGuessService().enrich(normalized)

    contact_info = next(table for table in semantic.tables if table.table_name == "service_reachability")

    assert contact_info.business_meaning == "Support and contact details maintained for companies and offices."
    assert contact_info.confidence.score >= 0.85


def test_semantic_enrichment_uses_configured_inference_rules() -> None:
    source = DiscoveredSource(
        name="aviation_demo",
        connection=SourceConnection(type=DatabaseType.mysql, database="aviation_demo"),
    )
    technical = SourceTechnicalMetadata(
        source_name="aviation_demo",
        db_type=DatabaseType.mysql,
        database_name="aviation_demo",
        connectivity_ok=True,
        schemas=[
            SchemaProfile(
                schema_name="aviation_demo",
                tables=[
                    TableProfile(
                        schema_name="aviation_demo",
                        table_name="hangar_task",
                        primary_key=["id"],
                        columns=[
                            ColumnProfile(name="id", data_type="int", is_primary_key=True, is_identifier_like=True),
                            ColumnProfile(name="authored_by", data_type="int", sample_values=["44"]),
                        ],
                    ),
                    TableProfile(
                        schema_name="aviation_demo",
                        table_name="member",
                        primary_key=["id"],
                        columns=[
                            ColumnProfile(name="id", data_type="int", is_primary_key=True, is_identifier_like=True),
                            ColumnProfile(name="name", data_type="varchar", sample_values=["Alex"]),
                        ],
                    ),
                ],
            )
        ],
    )

    normalized = MetadataNormalizer().normalize(source, technical)
    semantic = SemanticGuessService(
        SemanticInferenceRules(
            domain_rules={"aviation_ops": ("hangar", "flight")},
            actor_table_priority=("member",),
            audit_actor_patterns={"authored_by": "authored"},
            communication_directory=CommunicationDirectoryRules(),
        )
    ).enrich(normalized)

    hangar_task = next(table for table in semantic.tables if table.table_name == "hangar_task")
    authored_by = next(column for column in hangar_task.columns if column.column_name == "authored_by")

    assert semantic.domain == "aviation_ops"
    assert authored_by.business_meaning == "Member who authored this hangar task record."
    assert authored_by.confidence.score >= 0.9
