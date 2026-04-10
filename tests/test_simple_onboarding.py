from __future__ import annotations

from app.models.common import DatabaseType
from app.models.simple_onboarding import SimpleOnboardingRequest
from app.models.technical import (
    ColumnProfile,
    ForeignKeyProfile,
    SchemaProfile,
    SourceTechnicalMetadata,
    TableProfile,
)
from app.onboard.simple_flow import SimpleOnboardingService


def _metadata() -> SourceTechnicalMetadata:
    return SourceTechnicalMetadata(
        source_name="warehouse_source",
        db_type=DatabaseType.mysql,
        database_name="warehouse",
        connectivity_ok=True,
        schemas=[
            SchemaProfile(
                schema_name="warehouse",
                tables=[
                    TableProfile(
                        schema_name="warehouse",
                        table_name="person",
                        columns=[
                            ColumnProfile(name="id", data_type="INTEGER"),
                            ColumnProfile(name="first_name", data_type="TEXT"),
                            ColumnProfile(name="last_name", data_type="TEXT"),
                            ColumnProfile(name="email", data_type="TEXT"),
                        ],
                        primary_key=["id"],
                    ),
                    TableProfile(
                        schema_name="warehouse",
                        table_name="site",
                        columns=[
                            ColumnProfile(name="id", data_type="INTEGER"),
                            ColumnProfile(name="name", data_type="TEXT"),
                            ColumnProfile(name="city", data_type="TEXT"),
                        ],
                        primary_key=["id"],
                    ),
                    TableProfile(
                        schema_name="warehouse",
                        table_name="task_transaction",
                        columns=[
                            ColumnProfile(name="id", data_type="INTEGER"),
                            ColumnProfile(name="title", data_type="TEXT"),
                            ColumnProfile(name="status", data_type="TEXT"),
                            ColumnProfile(name="priority", data_type="TEXT"),
                            ColumnProfile(name="scheduled_date", data_type="TEXT"),
                            ColumnProfile(name="assignee_id", data_type="INTEGER"),
                            ColumnProfile(name="site_id", data_type="INTEGER"),
                        ],
                        primary_key=["id"],
                        foreign_keys=[
                            ForeignKeyProfile(
                                constrained_columns=["assignee_id"],
                                referred_table="person",
                                referred_columns=["id"],
                            ),
                            ForeignKeyProfile(
                                constrained_columns=["site_id"],
                                referred_table="site",
                                referred_columns=["id"],
                            ),
                        ],
                    ),
                    TableProfile(
                        schema_name="warehouse",
                        table_name="task_status",
                        columns=[
                            ColumnProfile(name="id", data_type="INTEGER"),
                            ColumnProfile(name="name", data_type="TEXT"),
                            ColumnProfile(name="display_order", data_type="INTEGER"),
                        ],
                        primary_key=["id"],
                    ),
                    TableProfile(
                        schema_name="warehouse",
                        table_name="task_asset_mapping",
                        columns=[
                            ColumnProfile(name="id", data_type="INTEGER"),
                            ColumnProfile(name="task_transaction_id", data_type="INTEGER"),
                            ColumnProfile(name="asset_id", data_type="INTEGER"),
                        ],
                        primary_key=["id"],
                        foreign_keys=[
                            ForeignKeyProfile(
                                constrained_columns=["task_transaction_id"],
                                referred_table="task_transaction",
                                referred_columns=["id"],
                            ),
                            ForeignKeyProfile(
                                constrained_columns=["asset_id"],
                                referred_table="asset",
                                referred_columns=["id"],
                            ),
                        ],
                    ),
                    TableProfile(
                        schema_name="warehouse",
                        table_name="audit_log",
                        columns=[
                            ColumnProfile(name="id", data_type="INTEGER"),
                            ColumnProfile(name="message", data_type="TEXT"),
                        ],
                        primary_key=["id"],
                    ),
                ],
            )
        ],
    )


def test_simple_onboarding_builds_business_friendly_output() -> None:
    service = SimpleOnboardingService()

    response = service.build_from_metadata(
        metadata=_metadata(),
        request=SimpleOnboardingRequest(
            db_url="mysql://demo",
            business_context="field operations",
            selection_mode="review",
        ),
        source_name="warehouse_source",
        database_target="mysql://db.example.com:3306/warehouse",
    )

    table_map = {table.name: table for table in response.tables}

    assert response.source_name == "warehouse_source"
    assert response.database_target == "mysql://db.example.com:3306/warehouse"
    assert "task_transaction" in response.categories["Core Operations"]
    assert table_map["person"].category == "People & Teams"
    assert table_map["site"].category == "Locations & Facilities"
    assert table_map["task_transaction"].description.startswith("Tracks task transaction records")
    assert "audit_log" in response.ignored_tables
    assert response.artifact.business_context == "field operations"
    assert any(
        relationship.from_table == "task_transaction" and relationship.to_table == "person"
        for relationship in response.artifact.relationships
    )
    assert any(
        relationship.from_table == "task_transaction" and relationship.to_table == "site"
        for relationship in response.artifact.relationships
    )


def test_simple_onboarding_applies_bulk_rules_and_manual_overrides() -> None:
    service = SimpleOnboardingService()

    response = service.build_from_metadata(
        metadata=_metadata(),
        request=SimpleOnboardingRequest(
            db_url="mysql://demo",
            selection_mode="ai",
            include_categories=["Reference Data"],
            bulk_include_patterns=["*mapping*"],
            bulk_exclude_patterns=["*person*"],
        ),
        source_name="warehouse_source",
        database_target="mysql://db.example.com:3306/warehouse",
    )

    assert "task_transaction" in response.selected_tables
    assert "site" in response.selected_tables
    assert "task_status" in response.selected_tables
    assert "task_asset_mapping" in response.selected_tables
    assert "person" not in response.selected_tables
    assert "audit_log" not in response.selected_tables
    assert response.artifact.categories["Reference Data"] == ["task_asset_mapping", "task_status"]
