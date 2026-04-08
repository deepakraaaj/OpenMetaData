"""Main orchestrator — ties gap detection, prioritization, question generation,
answer interpretation, and readiness computation together."""
from __future__ import annotations

from pathlib import Path

from app.engine.answer_interpreter import AnswerInterpreter
from app.engine.gap_detector import GapDetector
from app.engine.prioritizer import GapPrioritizer
from app.engine.question_generator import GeneratedQuestion, QuestionGenerator
from app.engine.readiness import ReadinessComputer
from app.engine.state_manager import StateManager
from app.models.normalized import NormalizedSource
from app.models.semantic import SemanticSourceModel
from app.models.state import KnowledgeState
from app.normalization.service import MetadataNormalizer
from app.semantics.service import SemanticGuessService


class OnboardingEngine:
    """
    The real onboarding engine.

    Lifecycle:
        1. initialize(source_name, normalized) — bootstrap KnowledgeState
        2. next_question(source_name) — get the top-priority question
        3. submit_answer(source_name, gap_id, answer) — apply mutation
        4. repeat 2–3 until readiness is sufficient
    """

    def __init__(self, output_dir: Path) -> None:
        self.state_manager = StateManager(output_dir)
        self.gap_detector = GapDetector()
        self.prioritizer = GapPrioritizer()
        self.question_generator = QuestionGenerator()
        self.answer_interpreter = AnswerInterpreter()
        self.readiness_computer = ReadinessComputer()
        self.normalizer = MetadataNormalizer()
        self.semantic_service = SemanticGuessService()

    def initialize(
        self,
        source_name: str,
        normalized: NormalizedSource,
        semantic: SemanticSourceModel | None = None,
    ) -> KnowledgeState:
        """Bootstrap a KnowledgeState from normalized schema data."""
        if semantic is None:
            semantic = self.semantic_service.enrich(normalized)

        state = self.state_manager.initialize_from_semantic(source_name, semantic)

        # Run initial gap detection
        gaps = self.gap_detector.detect(normalized, state)
        state.unresolved_gaps = gaps
        state.readiness = self.readiness_computer.compute(state)

        self.state_manager.save(source_name, state)
        return state

    def get_state(self, source_name: str) -> KnowledgeState | None:
        """Return the current knowledge state, or None if not initialized."""
        return self.state_manager.load(source_name)

    def next_question(
        self, source_name: str, normalized: NormalizedSource | None = None
    ) -> GeneratedQuestion | None:
        """Get the highest-priority unresolved question."""
        state = self.state_manager.load(source_name)
        if state is None:
            return None

        # Optionally re-detect gaps if normalized data is provided
        if normalized is not None:
            fresh_gaps = self.gap_detector.detect(normalized, state)
            state.unresolved_gaps = fresh_gaps

        top_gap = self.prioritizer.next_gap(state.unresolved_gaps)
        if top_gap is None:
            return None

        return self.question_generator.generate(top_gap, state)

    def submit_answer(
        self,
        source_name: str,
        gap_id: str,
        answer: str,
        normalized: NormalizedSource | None = None,
    ) -> KnowledgeState:
        """Apply a user's answer and recompute state."""
        state = self.state_manager.load(source_name)
        if state is None:
            raise ValueError(f"No knowledge state found for source '{source_name}'.")

        # Find the gap being answered
        gap = next((g for g in state.unresolved_gaps if g.gap_id == gap_id), None)
        if gap is None:
            raise ValueError(f"Gap '{gap_id}' not found in unresolved gaps.")

        # Apply the answer
        state = self.answer_interpreter.apply(state, gap, answer)

        # Re-detect remaining gaps if we have normalized data
        if normalized is not None:
            fresh_gaps = self.gap_detector.detect(normalized, state)
            state.unresolved_gaps = fresh_gaps

        # Recompute readiness
        state.readiness = self.readiness_computer.compute(state)

        # Persist
        self.state_manager.save(source_name, state)
        return state
    def confirm_table(
        self, source_name: str, table_name: str, reviewer: str | None = None
    ) -> KnowledgeState:
        """Mark a table and all its current column mappings as human-confirmed."""
        state = self.state_manager.load(source_name)
        if state is None:
            raise ValueError(f"No knowledge state found for source '{source_name}'.")

        if table_name not in state.tables:
            raise ValueError(f"Table '{table_name}' not found in knowledge state.")

        from datetime import datetime
        from app.models.source_attribution import DiscoverySource

        table = state.tables[table_name]
        table.attribution.source = DiscoverySource.CONFIRMED_BY_USER
        table.attribution.user = reviewer
        table.attribution.timestamp = datetime.utcnow().isoformat()
        table.confidence.score = 1.0
        table.confidence.label = "high"

        # Also confirm all columns currently in the model
        for column in table.columns:
            column.attribution.source = DiscoverySource.CONFIRMED_BY_USER
            column.attribution.user = reviewer
            column.attribution.timestamp = datetime.utcnow().isoformat()
            column.confidence.score = 1.0
            column.confidence.label = "high"

        # Recompute readiness
        state.readiness = self.readiness_computer.compute(state)

        # Persist
        self.state_manager.save(source_name, state)
        return state
