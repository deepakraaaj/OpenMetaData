from __future__ import annotations

from sqlalchemy import create_engine, text

from app.onboard.introspection import DatabaseIntrospector
from app.utils.enum_candidates import has_business_enum_signal


def test_has_business_enum_signal_uses_token_boundaries() -> None:
    assert has_business_enum_signal("mode") is True
    assert has_business_enum_signal("model_number") is False
    assert has_business_enum_signal("FacilityStatus") is True
    assert has_business_enum_signal("TaskStatus") is True


def test_introspector_samples_more_values_for_cardinality_check(tmp_path) -> None:
    db_path = tmp_path / "cardinality.sqlite"
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE statuses (id INTEGER PRIMARY KEY, code TEXT NOT NULL)"))
        for value in range(1, 13):
            conn.execute(text("INSERT INTO statuses (code) VALUES (:code)"), {"code": f"code_{value}"})

    introspector = DatabaseIntrospector()
    sampled = introspector._sample_column_values(engine, None, "statuses", "code")
    assert len(sampled) == 12
    assert sampled[0].startswith("code_")
