from pathlib import Path

from app.engine.state_manager import StateManager
from app.models.semantic import SemanticTable
from app.models.state import KnowledgeState


def test_state_manager_load_recovers_from_trailing_invalid_json(tmp_path: Path) -> None:
    manager = StateManager(tmp_path)
    state = KnowledgeState(source_name="demo", tables={"vehicle": SemanticTable(table_name="vehicle")})
    path = manager.save("demo", state)
    path.write_text(path.read_text() + "\n}")

    loaded = manager.load("demo")

    assert loaded is not None
    assert loaded.source_name == "demo"
    assert "vehicle" in loaded.tables
