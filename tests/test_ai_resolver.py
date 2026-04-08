from app.engine import ai_resolver
from app.models.common import DatabaseType
from app.models.semantic import SemanticTable
from app.models.state import KnowledgeState
from app.models.technical import (
    CandidateJoin,
    ColumnProfile,
    ForeignKeyProfile,
    SchemaProfile,
    SourceTechnicalMetadata,
    TableProfile,
)


def _table(name: str, joins: list[str] | None = None) -> SemanticTable:
    return SemanticTable(
        table_name=name,
        valid_joins=joins or [],
    )


def _technical_metadata() -> SourceTechnicalMetadata:
    return SourceTechnicalMetadata(
        source_name="vts",
        db_type=DatabaseType.mysql,
        schemas=[
            SchemaProfile(
                schema_name="vts",
                tables=[
                    TableProfile(
                        schema_name="vts",
                        table_name="vehicle",
                        estimated_row_count=2400,
                        primary_key=["id"],
                        foreign_keys=[
                            ForeignKeyProfile(
                                constrained_columns=["company_id"],
                                referred_table="company",
                                referred_columns=["id"],
                            )
                        ],
                        candidate_joins=[
                            CandidateJoin(
                                left_table="vehicle",
                                left_column="company_id",
                                right_table="company",
                                right_column="id",
                                confidence=0.99,
                            )
                        ],
                        columns=[
                            ColumnProfile(name="id", data_type="BIGINT", is_primary_key=True),
                            ColumnProfile(name="company_id", data_type="INT", is_foreign_key=True, referenced_table="company", referenced_column="id"),
                            ColumnProfile(name="vehicle_number", data_type="VARCHAR"),
                            ColumnProfile(name="imei_no", data_type="VARCHAR"),
                        ],
                    ),
                    TableProfile(
                        schema_name="vts",
                        table_name="vts_transaction",
                        estimated_row_count=880000,
                        primary_key=["id"],
                        foreign_keys=[
                            ForeignKeyProfile(
                                constrained_columns=["vehicle_id"],
                                referred_table="vehicle",
                                referred_columns=["id"],
                            )
                        ],
                        candidate_joins=[
                            CandidateJoin(
                                left_table="vts_transaction",
                                left_column="vehicle_id",
                                right_table="vehicle",
                                right_column="id",
                                confidence=0.99,
                            )
                        ],
                        columns=[
                            ColumnProfile(name="id", data_type="BIGINT", is_primary_key=True),
                            ColumnProfile(name="vehicle_id", data_type="INT", is_foreign_key=True, referenced_table="vehicle", referenced_column="id"),
                            ColumnProfile(name="gps_ts", data_type="DATETIME", is_timestamp_like=True),
                            ColumnProfile(name="lat", data_type="DECIMAL"),
                            ColumnProfile(name="lng", data_type="DECIMAL"),
                        ],
                    ),
                ],
            )
        ],
    )


def test_group_tables_by_relationships_uses_ai_labels_and_tables(monkeypatch) -> None:
    state = KnowledgeState(
        source_name="vts",
        tables={
            "vehicle": _table("vehicle", ["vehicle.company_id=company.id"]),
            "vehicle_communication": _table(
                "vehicle_communication",
                ["vehicle_communication.vehicle_id=vehicle.id"],
            ),
            "trip": _table("trip", ["trip.vehicle_id=vehicle.id"]),
            "trip_log": _table("trip_log", ["trip_log.trip_id=trip.id"]),
            "call_log": _table("call_log", ["call_log.trip_id=trip.id"]),
            "tickets_support": _table("tickets_support", ["tickets_support.trip_id=trip.id"]),
            "company": _table("company"),
            "flyway_schema_history": _table("flyway_schema_history"),
        },
    )

    technical_metadata = _technical_metadata()

    monkeypatch.setattr(
        ai_resolver,
        "_group_tables_with_llm",
        lambda *_args, **_kwargs: {
            "Vehicles & Telematics": ["vehicle", "vehicle_communication"],
            "Trips & Dispatch": ["trip", "trip_log"],
            "Support & Communications": ["call_log", "tickets_support"],
            "Organizations & Access": ["company"],
            "Miscellaneous": ["flyway_schema_history"],
        },
    )

    groups = ai_resolver.group_tables_by_relationships(state, technical_metadata=technical_metadata)

    assert set(groups["Vehicles & Telematics"]) == {"vehicle", "vehicle_communication"}
    assert set(groups["Trips & Dispatch"]) == {"trip", "trip_log"}
    assert set(groups["Support & Communications"]) == {"call_log", "tickets_support"}
    assert set(groups["Organizations & Access"]) == {"company"}
    assert set(groups["Miscellaneous"]) == {"flyway_schema_history"}


def test_group_tables_by_relationships_assigns_missing_tables_from_neighbors(monkeypatch) -> None:
    state = KnowledgeState(
        source_name="vts",
        tables={
            "vehicle": _table("vehicle", ["vehicle.company_id=company.id"]),
            "vehicle_communication": _table(
                "vehicle_communication",
                ["vehicle_communication.vehicle_id=vehicle.id"],
            ),
            "dms_transaction": _table(
                "dms_transaction",
                [
                    "dms_transaction.vehicle_id=vehicle.id",
                    "dms_transaction.vehicle_communication_id=vehicle_communication.id",
                ],
            ),
            "company": _table("company"),
        },
    )

    technical_metadata = _technical_metadata()

    monkeypatch.setattr(
        ai_resolver,
        "_group_tables_with_llm",
        lambda *_args, **_kwargs: {
            "Vehicles & Telematics": ["vehicle", "vehicle_communication"],
            "Organizations & Access": ["company"],
        },
    )

    groups = ai_resolver.group_tables_by_relationships(state, technical_metadata=technical_metadata)

    assert "dms_transaction" in groups["Vehicles & Telematics"]


def test_group_tables_by_relationships_has_relation_based_fallback_when_ai_unavailable(monkeypatch) -> None:
    state = KnowledgeState(
        source_name="demo",
        tables={
            "orders": _table("orders", ["orders.user_id=users.id"]),
            "order_items": _table("order_items", ["order_items.order_id=orders.id"]),
            "users": _table("users"),
            "flyway_schema_history": _table("flyway_schema_history"),
        },
    )

    monkeypatch.setattr(ai_resolver, "_group_tables_with_llm", lambda *_args, **_kwargs: None)

    groups = ai_resolver.group_tables_by_relationships(state)

    assigned = {table for members in groups.values() for table in members}
    assert assigned == set(state.tables.keys())
    assert "Miscellaneous" in groups


def test_full_schema_grouping_prompt_includes_tables_columns_and_relationships() -> None:
    state = KnowledgeState(
        source_name="vts",
        tables={
            "vehicle": _table("vehicle"),
            "vts_transaction": _table("vts_transaction"),
            "company": _table("company"),
        },
    )
    technical_metadata = _technical_metadata()
    adjacency = ai_resolver._build_relationship_adjacency(
        state,
        technical_metadata=technical_metadata,
    )

    prompt = ai_resolver._build_full_schema_grouping_prompt(
        state,
        adjacency,
        technical_metadata,
        semantic_model=None,
    )

    assert "FULL SCHEMA STRUCTURE" in prompt
    assert "vehicle | pk=id" in prompt
    assert "vts_transaction | pk=id" in prompt
    assert "vehicle_number" in prompt
    assert "gps_ts[timestamp]" in prompt
    assert "company_id[fk>company.id]" in prompt
    assert "neighbors=vehicle" in prompt or "neighbors=company,vehicle" in prompt


def test_grouping_llm_falls_back_to_second_candidate(monkeypatch) -> None:
    state = KnowledgeState(
        source_name="vts",
        tables={
            "vehicle": _table("vehicle"),
            "vehicle_communication": _table("vehicle_communication"),
        },
    )
    adjacency = {"vehicle": {"vehicle_communication"}, "vehicle_communication": {"vehicle"}}

    monkeypatch.setattr(
        ai_resolver,
        "_llm_candidates",
        lambda: [
            ai_resolver._LLMCandidate("http://bad.example/v1", "bad-model", "dummy", "bad"),
            ai_resolver._LLMCandidate("http://good.example/v1", "good-model", "dummy", "good"),
        ],
    )

    class _BadClient:
        def __init__(self):
            self.chat = self
            self.completions = self

        def create(self, **_kwargs):
            raise RuntimeError("connection error")

    class _GoodClient:
        def __init__(self):
            self.chat = self
            self.completions = self

        def create(self, **_kwargs):
            return type(
                "Resp",
                (),
                {
                    "choices": [
                        type(
                            "Choice",
                            (),
                            {
                                "message": type(
                                    "Msg",
                                    (),
                                    {
                                        "content": '{"groups":[{"label":"Vehicles & Telematics","tables":["vehicle","vehicle_communication"]}]}'
                                    },
                                )()
                            },
                        )()
                    ]
                },
            )()

    def _fake_openai(
        *,
        base_url: str,
        api_key: str,
        timeout: float | None = None,
        max_retries: int | None = None,
    ):
        assert api_key == "dummy"
        assert timeout == 30.0
        assert max_retries == 0
        if base_url == "http://bad.example/v1":
            return _BadClient()
        return _GoodClient()

    monkeypatch.setattr(ai_resolver, "OpenAI", _fake_openai)

    groups = ai_resolver._group_tables_with_llm(
        state,
        adjacency,
        technical_metadata=None,
        semantic_model=None,
    )

    assert groups == {"Vehicles & Telematics": ["vehicle", "vehicle_communication"]}
