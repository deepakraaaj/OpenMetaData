"""Load, save, and initialize KnowledgeState from disk."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from app.models.normalized import NormalizedSource
from app.models.semantic import SemanticSourceModel, SemanticTable
from app.models.source_attribution import DiscoverySource, SourceAttribution
from app.models.state import KnowledgeState


STATE_FILENAME = "knowledge_state.json"
logger = logging.getLogger(__name__)


class StateManager:
    """Manages persistence of KnowledgeState to the filesystem."""

    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir

    def _state_path(self, source_name: str) -> Path:
        return self.output_dir / source_name / STATE_FILENAME

    def exists(self, source_name: str) -> bool:
        return self._state_path(source_name).exists()

    def load(self, source_name: str) -> KnowledgeState | None:
        path = self._state_path(source_name)
        if not path.exists():
            return None
        text = path.read_text()
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as exc:
            decoder = json.JSONDecoder()
            raw, index = decoder.raw_decode(text)
            trailing = text[index:].strip()
            if not trailing:
                raise
            logger.warning(
                "Recovered knowledge state '%s' with trailing invalid JSON content: %s",
                source_name,
                trailing[:80],
            )
        return KnowledgeState.model_validate(raw)

    def save(self, source_name: str, state: KnowledgeState) -> Path:
        path = self._state_path(source_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(f"{path.suffix}.tmp")
        temp_path.write_text(state.model_dump_json(indent=2))
        temp_path.replace(path)
        return path

    def initialize_from_semantic(
        self, source_name: str, semantic: SemanticSourceModel
    ) -> KnowledgeState:
        """Convert Phase 1 SemanticSourceModel into an initial KnowledgeState."""
        tables: dict[str, SemanticTable] = {}
        for table in semantic.tables:
            tables[table.table_name] = table

        glossary = {term.term: term for term in semantic.glossary}
        entities = {e.entity_name: e for e in semantic.canonical_entities}

        state = KnowledgeState(
            source_name=source_name,
            review_mode=semantic.review_mode,
            tables=tables,
            canonical_entities=entities,
            glossary=glossary,
            query_patterns=semantic.query_patterns,
            decision_history=list(semantic.decision_history),
            review_debt=list(semantic.review_debt),
        )
        return state
