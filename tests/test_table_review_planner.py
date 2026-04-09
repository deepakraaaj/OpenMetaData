from app.engine.service import OnboardingEngine
from app.engine.table_review_planner import TableReviewPlanner
from app.models.common import DatabaseType
from app.models.normalized import NormalizedColumn, NormalizedSource, NormalizedTable
from app.models.review import BulkReviewAction, TableReviewDecision, TableRole
from app.models.semantic import SemanticSourceModel, SemanticTable, TableReviewStatus
from app.models.source import DiscoveredSource, SourceConnection
from app.models.technical import ColumnProfile, ForeignKeyProfile, SchemaProfile, SourceTechnicalMetadata, TableProfile
from app.normalization.service import MetadataNormalizer


def _review_source() -> tuple[NormalizedSource, SourceTechnicalMetadata, SemanticSourceModel]:
    technical = SourceTechnicalMetadata(
        source_name="planner_demo",
        db_type=DatabaseType.mysql,
        database_name="planner_demo",
        connectivity_ok=True,
        schemas=[
            SchemaProfile(
                schema_name="planner_demo",
                tables=[
                    TableProfile(
                        schema_name="planner_demo",
                        table_name="users",
                        estimated_row_count=120,
                        primary_key=["id"],
                        columns=[
                            ColumnProfile(name="id", data_type="int", is_primary_key=True, is_identifier_like=True),
                            ColumnProfile(name="name", data_type="varchar"),
                            ColumnProfile(name="email", data_type="varchar"),
                        ],
                    ),
                    TableProfile(
                        schema_name="planner_demo",
                        table_name="trip_transaction",
                        estimated_row_count=50000,
                        primary_key=["id"],
                        foreign_keys=[
                            ForeignKeyProfile(
                                referred_table="users",
                                constrained_columns=["user_id"],
                                referred_columns=["id"],
                            )
                        ],
                        columns=[
                            ColumnProfile(name="id", data_type="int", is_primary_key=True, is_identifier_like=True),
                            ColumnProfile(name="user_id", data_type="int", is_foreign_key=True),
                            ColumnProfile(name="status", data_type="varchar", is_status_like=True),
                            ColumnProfile(name="created_at", data_type="datetime", is_timestamp_like=True),
                        ],
                        status_columns=["status"],
                        timestamp_columns=["created_at"],
                    ),
                    TableProfile(
                        schema_name="planner_demo",
                        table_name="trip_status",
                        estimated_row_count=6,
                        primary_key=["id"],
                        columns=[
                            ColumnProfile(name="id", data_type="int", is_primary_key=True, is_identifier_like=True),
                            ColumnProfile(name="code", data_type="varchar"),
                            ColumnProfile(name="label", data_type="varchar"),
                        ],
                    ),
                    TableProfile(
                        schema_name="planner_demo",
                        table_name="user_role_mapping",
                        estimated_row_count=280,
                        primary_key=["user_id", "role_id"],
                        foreign_keys=[
                            ForeignKeyProfile(
                                referred_table="users",
                                constrained_columns=["user_id"],
                                referred_columns=["id"],
                            ),
                            ForeignKeyProfile(
                                referred_table="trip_status",
                                constrained_columns=["role_id"],
                                referred_columns=["id"],
                            ),
                        ],
                        columns=[
                            ColumnProfile(name="user_id", data_type="int", is_foreign_key=True),
                            ColumnProfile(name="role_id", data_type="int", is_foreign_key=True),
                        ],
                    ),
                    TableProfile(
                        schema_name="planner_demo",
                        table_name="audit_log",
                        estimated_row_count=200000,
                        primary_key=["id"],
                        columns=[
                            ColumnProfile(name="id", data_type="int", is_primary_key=True, is_identifier_like=True),
                            ColumnProfile(name="event_type", data_type="varchar", is_status_like=True),
                            ColumnProfile(name="created_at", data_type="datetime", is_timestamp_like=True),
                        ],
                        timestamp_columns=["created_at"],
                    ),
                    TableProfile(
                        schema_name="planner_demo",
                        table_name="system_config",
                        estimated_row_count=12,
                        primary_key=["id"],
                        columns=[
                            ColumnProfile(name="id", data_type="int", is_primary_key=True, is_identifier_like=True),
                            ColumnProfile(name="config_key", data_type="varchar"),
                            ColumnProfile(name="config_value", data_type="varchar"),
                        ],
                    ),
                ],
            )
        ],
    )
    normalized = MetadataNormalizer().normalize(
        DiscoveredSource(
            name="planner_demo",
            connection=SourceConnection(type=DatabaseType.mysql, database="planner_demo"),
        ),
        technical,
    )
    semantic = SemanticSourceModel(
        source_name="planner_demo",
        db_type="mysql",
        tables=[SemanticTable(table_name=table.table_name) for table in normalized.tables],
    )
    return normalized, technical, semantic


def test_table_review_planner_classifies_roles_and_scope() -> None:
    normalized, technical, semantic = _review_source()
    planner = TableReviewPlanner()

    planner.annotate(
        normalized=normalized,
        technical=technical,
        semantic=semantic,
        domain_groups={
            "Trip Operations": ["trip_transaction", "trip_status"],
            "Users & Access": ["users", "user_role_mapping"],
            "System / Internal": ["audit_log", "system_config"],
        },
    )

    tables = {table.table_name: table for table in semantic.tables}

    assert tables["users"].role == TableRole.core_entity
    assert tables["users"].selected is True
    assert tables["trip_transaction"].role == TableRole.transaction
    assert tables["trip_transaction"].selected is True
    assert tables["trip_status"].role == TableRole.lookup_master
    assert tables["trip_status"].recommended_selected is False
    assert tables["trip_status"].review_decision == TableReviewDecision.review
    assert tables["user_role_mapping"].role == TableRole.mapping_bridge
    assert tables["audit_log"].role in {TableRole.log_event, TableRole.history_audit}
    assert tables["audit_log"].selected is False
    assert tables["system_config"].role == TableRole.config_system
    assert tables["system_config"].selected is False


def test_bulk_review_select_recommended_applies_ai_defaults(tmp_path) -> None:
    engine = OnboardingEngine(tmp_path)
    normalized = NormalizedSource(
        source_name="demo",
        db_type="sqlite",
        tables=[
            NormalizedTable(
                schema_name="main",
                table_name="audit_log",
                columns=[
                    NormalizedColumn(
                        schema_name="main",
                        table_name="audit_log",
                        column_name="id",
                        technical_type="INTEGER",
                        is_primary_key=True,
                    )
                ],
            ),
            NormalizedTable(
                schema_name="main",
                table_name="users",
                columns=[
                    NormalizedColumn(
                        schema_name="main",
                        table_name="users",
                        column_name="id",
                        technical_type="INTEGER",
                        is_primary_key=True,
                    )
                ],
            ),
        ],
    )
    semantic = SemanticSourceModel(
        source_name="demo",
        db_type="sqlite",
        tables=[
            SemanticTable(
                table_name="audit_log",
                role=TableRole.log_event,
                recommended_selected=False,
                selected=True,
                review_decision=TableReviewDecision.excluded,
            ),
            SemanticTable(
                table_name="users",
                role=TableRole.core_entity,
                recommended_selected=True,
                selected=True,
                review_decision=TableReviewDecision.selected,
            ),
        ],
    )

    engine.initialize("demo", normalized, semantic=semantic)
    updated = engine.bulk_review(
        "demo",
        BulkReviewAction.select_recommended,
        normalized=normalized,
    )

    assert updated.tables["audit_log"].selected is False
    assert updated.tables["audit_log"].review_status == TableReviewStatus.skipped
    assert updated.tables["users"].selected is True
    assert updated.tables["users"].review_status == TableReviewStatus.confirmed
    assert updated.review_summary.selected_count == 1
    assert updated.review_summary.excluded_count == 1
