"""Main orchestrator — ties gap detection, prioritization, question generation,
answer interpretation, and readiness computation together."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.engine.answer_interpreter import AnswerInterpreter
from app.engine.decision_policy import AIDecisionPolicyPass
from app.engine.gap_detector import GapDetector
from app.engine.prioritizer import GapPrioritizer
from app.engine.question_generator import GeneratedQuestion, QuestionGenerator
from app.engine.readiness import ReadinessComputer
from app.engine.state_manager import StateManager
from app.engine.table_review_planner import TableReviewPlanner
from app.models.common import ConfidenceLabel
from app.models.decision import DecisionActor, ReviewMode
from app.models.normalized import NormalizedSource
from app.models.review import BulkReviewAction, TableReviewDecision, TableRole
from app.models.semantic import SemanticSourceModel, TableReviewStatus
from app.models.state import KnowledgeState
from app.models.source_attribution import DiscoverySource
from app.normalization.service import MetadataNormalizer
from app.semantics.service import SemanticGuessService
from app.utils.serialization import read_json, write_json, write_yaml


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
        self.review_planner = TableReviewPlanner()
        self.decision_policy = AIDecisionPolicyPass()
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
        state.unresolved_gaps = self.gap_detector.detect(normalized, state)
        state = self.decision_policy.apply(state)
        state.readiness = self.readiness_computer.compute(state)
        self.review_planner.refresh_state_view(state)

        self.state_manager.save(source_name, state)
        self._sync_state_to_semantic(source_name, state, semantic=semantic)
        return state

    def get_state(self, source_name: str) -> KnowledgeState | None:
        """Return the current knowledge state, or None if not initialized."""
        return self.state_manager.load(source_name)

    def refresh(
        self,
        source_name: str,
        normalized: NormalizedSource,
    ) -> KnowledgeState:
        """Recompute gaps and readiness using the latest detector logic."""
        state = self.state_manager.load(source_name)
        if state is None:
            raise ValueError(f"No knowledge state found for source '{source_name}'.")

        refreshed_semantic = self.semantic_service.enrich(normalized)
        self._merge_inferred_semantics(state, refreshed_semantic)
        state.unresolved_gaps = self.gap_detector.detect(normalized, state)
        state = self.decision_policy.apply(state)
        state.readiness = self.readiness_computer.compute(state)
        self.review_planner.refresh_state_view(state)
        self.state_manager.save(source_name, state)
        self._sync_state_to_semantic(source_name, state)
        return state

    def next_question(
        self, source_name: str, normalized: NormalizedSource | None = None
    ) -> GeneratedQuestion | None:
        """Get the highest-priority unresolved question."""
        state = self.state_manager.load(source_name)
        if state is None:
            return None

        # Optionally re-detect gaps if normalized data is provided
        if normalized is not None:
            refreshed_semantic = self.semantic_service.enrich(normalized)
            self._merge_inferred_semantics(state, refreshed_semantic)
            state.unresolved_gaps = self.gap_detector.detect(normalized, state)
            state = self.decision_policy.apply(state)
            state.readiness = self.readiness_computer.compute(state)
            self.review_planner.refresh_state_view(state)
            self.state_manager.save(source_name, state)
            self._sync_state_to_semantic(source_name, state)

        top_gap = self.prioritizer.next_gap(state.unresolved_gaps)
        if top_gap is None:
            return None

        return self.question_generator.generate(top_gap, state)

    def submit_answer(
        self,
        source_name: str,
        gap_id: str,
        answer: str,
        reviewer: str | None = None,
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
        actor = self._decision_actor_for_answer(gap, answer)
        state = self.answer_interpreter.apply(
            state,
            gap,
            answer,
            actor=actor,
            reviewer=reviewer,
        )
        self.decision_policy.record_gap_decision(
            state,
            gap,
            answer,
            actor=actor,
            reviewer=reviewer,
        )

        # Re-detect remaining gaps if we have normalized data
        if normalized is not None:
            refreshed_semantic = self.semantic_service.enrich(normalized)
            self._merge_inferred_semantics(state, refreshed_semantic)
            state.unresolved_gaps = self.gap_detector.detect(normalized, state)
            state = self.decision_policy.apply(state)

        # Recompute readiness
        state.readiness = self.readiness_computer.compute(state)
        self.review_planner.refresh_state_view(state)

        # Persist
        self.state_manager.save(source_name, state)
        self._sync_state_to_semantic(source_name, state)
        return state

    def confirm_table(
        self,
        source_name: str,
        table_name: str,
        reviewer: str | None = None,
        normalized: NormalizedSource | None = None,
    ) -> KnowledgeState:
        """Mark a table and all its current column mappings as human-confirmed."""
        state = self.state_manager.load(source_name)
        if state is None:
            raise ValueError(f"No knowledge state found for source '{source_name}'.")

        if table_name not in state.tables:
            raise ValueError(f"Table '{table_name}' not found in knowledge state.")

        table = state.tables[table_name]
        table.review_status = TableReviewStatus.confirmed
        table.attribution.source = DiscoverySource.CONFIRMED_BY_USER
        table.attribution.user = reviewer
        table.attribution.timestamp = datetime.now(timezone.utc).isoformat()
        table.confidence.score = 1.0
        table.confidence.label = ConfidenceLabel.high
        table.selected = True
        table.needs_review = False

        # Also confirm all columns currently in the model
        for column in table.columns:
            column.attribution.source = DiscoverySource.CONFIRMED_BY_USER
            column.attribution.user = reviewer
            column.attribution.timestamp = datetime.now(timezone.utc).isoformat()
            column.confidence.score = 1.0
            column.confidence.label = ConfidenceLabel.high

        self.decision_policy.record_table_decision(
            state,
            table,
            selected=True,
            reviewer=reviewer,
        )

        if normalized is not None:
            state.unresolved_gaps = self.gap_detector.detect(normalized, state)
        else:
            state.unresolved_gaps = [
                gap for gap in state.unresolved_gaps if gap.target_entity != table_name
            ]

        state = self.decision_policy.apply(state)
        # Recompute readiness
        state.readiness = self.readiness_computer.compute(state)
        self.review_planner.refresh_state_view(state)

        # Persist
        self.state_manager.save(source_name, state)
        self._sync_state_to_semantic(source_name, state)
        return state

    def review_table(
        self,
        source_name: str,
        table_name: str,
        review_status: TableReviewStatus,
        reviewer: str | None = None,
        normalized: NormalizedSource | None = None,
    ) -> KnowledgeState:
        """Persist a user's keep/skip decision for a table and recompute state."""
        state = self.state_manager.load(source_name)
        if state is None:
            raise ValueError(f"No knowledge state found for source '{source_name}'.")

        if table_name not in state.tables:
            raise ValueError(f"Table '{table_name}' not found in knowledge state.")

        table = state.tables[table_name]
        table.review_status = review_status
        table.attribution.user = reviewer
        table.attribution.timestamp = datetime.now(timezone.utc).isoformat()
        if review_status == TableReviewStatus.confirmed:
            table.selected = True
            table.needs_review = False
        elif review_status == TableReviewStatus.skipped:
            table.selected = False
            table.needs_review = False
        else:
            table.selected = table.recommended_selected
            table.needs_review = table.review_decision == TableReviewDecision.review
        if review_status == TableReviewStatus.skipped:
            table.attribution.tooling_notes = "Skipped from review scope by user."
        elif table.attribution.tooling_notes == "Skipped from review scope by user.":
            table.attribution.tooling_notes = None

        if review_status in {TableReviewStatus.confirmed, TableReviewStatus.skipped}:
            self.decision_policy.record_table_decision(
                state,
                table,
                selected=review_status == TableReviewStatus.confirmed,
                reviewer=reviewer,
            )

        if normalized is not None:
            state.unresolved_gaps = self.gap_detector.detect(normalized, state)
        elif review_status == TableReviewStatus.skipped:
            state.unresolved_gaps = [
                gap for gap in state.unresolved_gaps if gap.target_entity != table_name
            ]

        state = self.decision_policy.apply(state)
        state.readiness = self.readiness_computer.compute(state)
        self.review_planner.refresh_state_view(state)
        self.state_manager.save(source_name, state)
        self._sync_state_to_semantic(source_name, state)
        return state

    def bulk_review(
        self,
        source_name: str,
        action: BulkReviewAction,
        reviewer: str | None = None,
        normalized: NormalizedSource | None = None,
    ) -> KnowledgeState:
        state = self.state_manager.load(source_name)
        if state is None:
            raise ValueError(f"No knowledge state found for source '{source_name}'.")

        for table in state.tables.values():
            if action == BulkReviewAction.select_recommended:
                self._set_table_selection(
                    table,
                    selected=table.recommended_selected,
                    reviewer=reviewer,
                )
                self.decision_policy.record_table_decision(
                    state,
                    table,
                    selected=table.recommended_selected,
                    reviewer=reviewer,
                )
                continue
            if action == BulkReviewAction.exclude_noise:
                if table.role in {TableRole.log_event, TableRole.history_audit, TableRole.config_system}:
                    self._set_table_selection(table, selected=False, reviewer=reviewer)
                    self.decision_policy.record_table_decision(
                        state,
                        table,
                        selected=False,
                        reviewer=reviewer,
                    )
                continue
            if action == BulkReviewAction.include_lookup_tables:
                if table.role == TableRole.lookup_master:
                    self._set_table_selection(table, selected=True, reviewer=reviewer)
                    self.decision_policy.record_table_decision(
                        state,
                        table,
                        selected=True,
                        reviewer=reviewer,
                    )
                continue
            if action == BulkReviewAction.include_all:
                self._set_table_selection(table, selected=True, reviewer=reviewer)
                self.decision_policy.record_table_decision(
                    state,
                    table,
                    selected=True,
                    reviewer=reviewer,
                )

        if normalized is not None:
            state.unresolved_gaps = self.gap_detector.detect(normalized, state)
        else:
            state.unresolved_gaps = [
                gap
                for gap in state.unresolved_gaps
                if state.tables.get(gap.target_entity or "", None) is None
                or state.tables[gap.target_entity].selected
            ]

        state = self.decision_policy.apply(state)
        state.readiness = self.readiness_computer.compute(state)
        self.review_planner.refresh_state_view(state)
        self.state_manager.save(source_name, state)
        self._sync_state_to_semantic(source_name, state)
        return state

    def apply_review_plan(
        self,
        source_name: str,
        normalized: NormalizedSource,
        *,
        technical,
        semantic: SemanticSourceModel,
        domain_groups: dict[str, list[str]] | None = None,
    ) -> KnowledgeState:
        state = self.state_manager.load(source_name)
        if state is None:
            state = self.initialize(source_name, normalized, semantic)

        self.review_planner.annotate(
            normalized=normalized,
            technical=technical,
            semantic=semantic,
            state=state,
            domain_groups=domain_groups,
        )
        state.unresolved_gaps = self.gap_detector.detect(normalized, state)
        state = self.decision_policy.apply(state)
        state.readiness = self.readiness_computer.compute(state)
        self.review_planner.refresh_state_view(state)
        self.state_manager.save(source_name, state)
        self._sync_state_to_semantic(source_name, state, semantic=semantic)
        return state

    def set_review_mode(
        self,
        source_name: str,
        review_mode: ReviewMode,
        normalized: NormalizedSource,
        *,
        technical,
        semantic: SemanticSourceModel | None = None,
        domain_groups: dict[str, list[str]] | None = None,
    ) -> KnowledgeState:
        state = self.state_manager.load(source_name)
        if state is None:
            state = self.initialize(source_name, normalized, semantic)

        state.review_mode = review_mode
        semantic_model = semantic or self._load_semantic_model(source_name)
        if semantic_model is None:
            semantic_model = self.semantic_service.enrich(normalized)
        semantic_model.review_mode = review_mode

        return self.apply_review_plan(
            source_name,
            normalized,
            technical=technical,
            semantic=semantic_model,
            domain_groups=domain_groups,
        )

    def apply_ai_defaults(
        self,
        source_name: str,
        *,
        domain_name: str | None = None,
        table_name: str | None = None,
        normalized: NormalizedSource | None = None,
    ) -> KnowledgeState:
        state = self.state_manager.load(source_name)
        if state is None:
            raise ValueError(f"No knowledge state found for source '{source_name}'.")

        if normalized is not None:
            refreshed_semantic = self.semantic_service.enrich(normalized)
            self._merge_inferred_semantics(state, refreshed_semantic)
            state.unresolved_gaps = self.gap_detector.detect(normalized, state)
            state = self.decision_policy.apply(state)

        state = self.decision_policy.apply_scope_ai_defaults(
            state,
            domain_name=domain_name,
            table_name=table_name,
        )
        state.readiness = self.readiness_computer.compute(state)
        self.review_planner.refresh_state_view(state)
        self.state_manager.save(source_name, state)
        self._sync_state_to_semantic(source_name, state)
        return state

    def _decision_actor_for_answer(self, gap, answer: str) -> DecisionActor:
        normalized = str(answer or "").strip().lower()
        if normalized in {"confirm", "__confirm__"}:
            return DecisionActor.user_confirmed
        if gap.best_guess is not None and normalized == str(gap.best_guess).strip().lower():
            return DecisionActor.user_confirmed
        for option in gap.candidate_options:
            values = {
                str(option.value or "").strip().lower(),
                str(option.label or "").strip().lower(),
            }
            if normalized in values:
                if option.is_best_guess:
                    return DecisionActor.user_confirmed
                break
        return DecisionActor.user_overridden

    def _semantic_path(self, source_name: str) -> Path:
        return self.state_manager.output_dir / source_name / "semantic_model.json"

    def _load_semantic_model(self, source_name: str) -> SemanticSourceModel | None:
        path = self._semantic_path(source_name)
        if not path.exists():
            return None
        return SemanticSourceModel.model_validate(read_json(path))

    def _sync_state_to_semantic(
        self,
        source_name: str,
        state: KnowledgeState,
        *,
        semantic: SemanticSourceModel | None = None,
    ) -> None:
        semantic_model = semantic or self._load_semantic_model(source_name)
        if semantic_model is None:
            return

        semantic_model.review_mode = state.review_mode
        semantic_model.decision_history = list(state.decision_history)
        semantic_model.review_debt = list(state.review_debt)
        semantic_model.glossary = list(state.glossary.values())
        semantic_model.canonical_entities = list(state.canonical_entities.values())
        semantic_model.query_patterns = list(state.query_patterns)
        semantic_model.business_rules = list(state.business_rules)

        state_tables = state.tables
        semantic_tables = {table.table_name: table for table in semantic_model.tables}
        for table_name, state_table in state_tables.items():
            semantic_table = semantic_tables.get(table_name)
            if semantic_table is None:
                continue

            semantic_table.review_status = state_table.review_status
            semantic_table.domain = state_table.domain
            semantic_table.role = state_table.role
            semantic_table.selected = state_table.selected
            semantic_table.recommended_selected = state_table.recommended_selected
            semantic_table.selected_by_default = state_table.selected_by_default
            semantic_table.review_decision = state_table.review_decision
            semantic_table.needs_review = state_table.needs_review
            semantic_table.requires_review = state_table.requires_review
            semantic_table.business_meaning = state_table.business_meaning
            semantic_table.grain = state_table.grain
            semantic_table.likely_entity = state_table.likely_entity
            semantic_table.important_columns = list(state_table.important_columns)
            semantic_table.valid_joins = list(state_table.valid_joins)
            semantic_table.common_filters = list(state_table.common_filters)
            semantic_table.common_business_questions = list(state_table.common_business_questions)
            semantic_table.sensitivity_notes = list(state_table.sensitivity_notes)
            semantic_table.reason_for_classification = state_table.reason_for_classification
            semantic_table.classification_reason = state_table.classification_reason
            semantic_table.selection_reason = state_table.selection_reason
            semantic_table.review_reason = state_table.review_reason
            semantic_table.related_tables = list(state_table.related_tables)
            semantic_table.impact_score = state_table.impact_score
            semantic_table.business_relevance = state_table.business_relevance
            semantic_table.naming_clarity = state_table.naming_clarity
            semantic_table.graph_connectivity = state_table.graph_connectivity
            semantic_table.confidence = state_table.confidence
            semantic_table.attribution = state_table.attribution
            semantic_table.decision_id = state_table.decision_id
            semantic_table.decision_status = state_table.decision_status
            semantic_table.decision_actor = state_table.decision_actor
            semantic_table.risk_level = state_table.risk_level
            semantic_table.policy_reason = state_table.policy_reason
            semantic_table.evidence_refs = list(state_table.evidence_refs)
            semantic_table.review_debt = state_table.review_debt
            semantic_table.publish_blocker = state_table.publish_blocker
            semantic_table.needs_acknowledgement = state_table.needs_acknowledgement

            state_columns = {column.column_name: column for column in state_table.columns}
            for semantic_column in semantic_table.columns:
                state_column = state_columns.get(semantic_column.column_name)
                if state_column is None:
                    continue
                semantic_column.business_meaning = state_column.business_meaning
                semantic_column.example_values = list(state_column.example_values)
                semantic_column.synonyms = list(state_column.synonyms)
                semantic_column.filterable = state_column.filterable
                semantic_column.displayable = state_column.displayable
                semantic_column.sensitive = state_column.sensitive
                semantic_column.confidence = state_column.confidence
                semantic_column.attribution = state_column.attribution
                semantic_column.decision_id = state_column.decision_id
                semantic_column.decision_status = state_column.decision_status
                semantic_column.decision_actor = state_column.decision_actor
                semantic_column.risk_level = state_column.risk_level
                semantic_column.policy_reason = state_column.policy_reason
                semantic_column.evidence_refs = list(state_column.evidence_refs)
                semantic_column.review_debt = state_column.review_debt
                semantic_column.publish_blocker = state_column.publish_blocker
                semantic_column.needs_acknowledgement = state_column.needs_acknowledgement

        path = self._semantic_path(source_name)
        write_json(path, semantic_model)
        write_yaml(path.with_suffix(".yaml"), semantic_model)

    def _merge_inferred_semantics(
        self,
        state: KnowledgeState,
        semantic: SemanticSourceModel,
    ) -> None:
        semantic_tables = {table.table_name: table for table in semantic.tables}
        for table_name, state_table in state.tables.items():
            inferred_table = semantic_tables.get(table_name)
            if inferred_table is None:
                continue

            if (
                state_table.attribution.source != DiscoverySource.CONFIRMED_BY_USER
                and inferred_table.confidence.score >= state_table.confidence.score
                and self._should_replace_meaning(state_table.business_meaning, inferred_table.business_meaning)
            ):
                state_table.business_meaning = inferred_table.business_meaning
                state_table.confidence = inferred_table.confidence
                if not state_table.likely_entity and inferred_table.likely_entity:
                    state_table.likely_entity = inferred_table.likely_entity
                if not state_table.grain and inferred_table.grain:
                    state_table.grain = inferred_table.grain

            inferred_columns = {column.column_name: column for column in inferred_table.columns}
            for state_column in state_table.columns:
                inferred_column = inferred_columns.get(state_column.column_name)
                if inferred_column is None:
                    continue
                if state_column.attribution.source == DiscoverySource.CONFIRMED_BY_USER:
                    continue
                if inferred_column.confidence.score < state_column.confidence.score:
                    continue
                if not self._should_replace_meaning(state_column.business_meaning, inferred_column.business_meaning):
                    continue
                state_column.business_meaning = inferred_column.business_meaning
                state_column.confidence = inferred_column.confidence
                if inferred_column.synonyms:
                    state_column.synonyms = inferred_column.synonyms

    def _should_replace_meaning(self, current: str | None, incoming: str | None) -> bool:
        current_text = str(current or "").strip()
        incoming_text = str(incoming or "").strip()
        if not incoming_text:
            return False
        if not current_text:
            return True
        if current_text == incoming_text:
            return True
        generic_prefixes = (
            "Business attribute for ",
            "Reference to a related ",
            "Primary records for ",
            "Detailed records associated with ",
            "Historical event records for ",
            "Timestamp used for audit",
        )
        return current_text.startswith(generic_prefixes) and current_text != incoming_text

    def _set_table_selection(
        self,
        table,
        *,
        selected: bool,
        reviewer: str | None,
    ) -> None:
        table.selected = selected
        table.review_status = TableReviewStatus.confirmed if selected else TableReviewStatus.skipped
        table.needs_review = False
        table.attribution.user = reviewer
        table.attribution.timestamp = datetime.now(timezone.utc).isoformat()
