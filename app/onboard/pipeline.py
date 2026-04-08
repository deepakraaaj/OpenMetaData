from __future__ import annotations

import logging
from pathlib import Path

from app.artifacts.chatbot_package import ChatbotPackageExporter
from app.artifacts.generator import ArtifactGenerator
from app.artifacts.semantic_bundle import SemanticBundleExporter
from app.artifacts.tag_bundle import TagBundleExporter
from app.core.settings import Settings
from app.engine.ai_resolver import group_tables_by_relationships
from app.engine.service import OnboardingEngine
from app.models.onboarding_job import (
    OnboardingLogLevel,
    OnboardingProgressCounts,
    OnboardingProgressUpdate,
    OnboardingStage,
    OnboardingStepState,
)
from app.models.state import KnowledgeState
from app.normalization.service import MetadataNormalizer
from app.openmetadata.service import OpenMetadataService
from app.onboard.introspection import DatabaseIntrospector
from app.onboard.progress import (
    ProgressCallback,
    emit_progress,
    normalized_counts,
    state_counts,
    technical_counts,
)
from app.repositories.filesystem import WorkspaceRepository
from app.retrieval.service import RetrievalContextBuilder
from app.semantics.ambiguity import AmbiguityDetector
from app.semantics.service import SemanticGuessService
from app.models.source import DiscoveredSource

logger = logging.getLogger(__name__)


class OnboardingPipelineError(RuntimeError):
    """Raised when onboarding cannot produce a usable schema bundle."""


class OnboardingPipeline:
    def __init__(self, settings: Settings, repository: WorkspaceRepository) -> None:
        self.settings = settings
        self.repository = repository
        self.introspector = DatabaseIntrospector()
        self.normalizer = MetadataNormalizer()
        self.semantic = SemanticGuessService()
        self.ambiguity = AmbiguityDetector()
        self.artifacts = ArtifactGenerator()
        self.semantic_bundle = SemanticBundleExporter()
        self.tag_bundle = TagBundleExporter()
        self.chatbot_package = ChatbotPackageExporter()
        self.retrieval = RetrievalContextBuilder()
        self.openmetadata = OpenMetadataService(settings)
        self.engine = OnboardingEngine(settings.output_dir)

    def run_source(
        self,
        source: DiscoveredSource,
        sync_openmetadata: bool = False,
        progress: ProgressCallback | None = None,
    ) -> Path:
        technical = self.introspector.introspect_source(source, progress=progress)
        if not technical.connectivity_ok:
            detail = "; ".join(note for note in technical.connectivity_notes if str(note).strip())
            raise OnboardingPipelineError(detail or "Database introspection failed.")

        output_dir = self.repository.source_dir(source.name)
        self.repository.save_technical_metadata(technical)
        technical_progress = technical_counts(technical)

        emit_progress(
            progress,
            OnboardingProgressUpdate(
                stage=OnboardingStage.EXTRACTING_RELATIONSHIPS,
                step_state=OnboardingStepState.RUNNING,
                message="Analyzing foreign keys and inferred joins between related tables.",
                counts=technical_progress,
            ),
        )
        emit_progress(
            progress,
            OnboardingProgressUpdate(
                stage=OnboardingStage.EXTRACTING_RELATIONSHIPS,
                step_state=OnboardingStepState.COMPLETED,
                level=OnboardingLogLevel.SUCCESS,
                message=(
                    f"Found {technical_progress.foreign_key_count or 0} foreign keys and "
                    f"{technical_progress.inferred_relationship_count or 0} inferred relationships."
                ),
                counts=technical_progress,
            ),
        )

        emit_progress(
            progress,
            OnboardingProgressUpdate(
                stage=OnboardingStage.BUILDING_SEMANTIC_MODEL,
                step_state=OnboardingStepState.RUNNING,
                message="Normalizing metadata into a schema-grounded semantic model.",
                counts=technical_progress,
            ),
        )

        normalized = self.normalizer.normalize(source, technical)
        table_count = int((normalized.summary or {}).get("table_count") or 0)
        if table_count <= 0:
            raise OnboardingPipelineError(
                "No tables were discovered for this source. Verify the DB URL, credentials, and schema permissions before retrying."
            )
        self.repository.save_normalized_metadata(normalized)
        emit_progress(
            progress,
            OnboardingProgressUpdate(
                stage=OnboardingStage.BUILDING_SEMANTIC_MODEL,
                message="Detecting business concepts, entity roles, and likely table meanings.",
                counts=self._merge_counts(technical_progress, normalized_counts(normalized)),
            ),
        )

        semantic = self.semantic.enrich(normalized)
        self.repository.save_semantic_model(semantic)
        state = self.engine.initialize(source.name, normalized, semantic)
        emit_progress(
            progress,
            OnboardingProgressUpdate(
                stage=OnboardingStage.BUILDING_SEMANTIC_MODEL,
                message="Grouping related tables into reviewable business domains.",
                counts=self._merge_counts(technical_progress, normalized_counts(normalized), state_counts(state)),
            ),
        )
        domain_groups = self._persist_domain_groups(source.name, state, technical, semantic)
        semantic_progress = self._merge_counts(
            technical_progress,
            normalized_counts(normalized),
            state_counts(state),
            OnboardingProgressCounts(domain_group_count=len(domain_groups)),
        )
        emit_progress(
            progress,
            OnboardingProgressUpdate(
                stage=OnboardingStage.BUILDING_SEMANTIC_MODEL,
                step_state=OnboardingStepState.COMPLETED,
                level=OnboardingLogLevel.SUCCESS,
                message=(
                    f"Semantic model prepared for {semantic_progress.table_count or 0} tables "
                    f"with {semantic_progress.unresolved_gap_count or 0} open review gaps."
                ),
                counts=semantic_progress,
            ),
        )
        emit_progress(
            progress,
            OnboardingProgressUpdate(
                stage=OnboardingStage.READY_FOR_REVIEW,
                step_state=OnboardingStepState.COMPLETED,
                level=OnboardingLogLevel.SUCCESS,
                message="Semantic model is ready. Review questions and export artifacts will be prepared when you open the workspace.",
                counts=semantic_progress,
            ),
        )

        if sync_openmetadata or self.settings.openmetadata_enable_sync:
            openmetadata_dir = self.settings.output_dir / "openmetadata"
            config_path = self.openmetadata.prepare_source_config(source, openmetadata_dir)
            self.openmetadata.run_ingestion(config_path)

        return output_dir

    def prepare_review_workspace(self, source_name: str) -> KnowledgeState:
        output_dir = self.repository.source_dir(source_name)
        technical = self.repository.load_technical_metadata(source_name)
        normalized = self.repository.load_normalized_metadata(source_name)
        semantic = self.repository.load_semantic_model(source_name)

        state = self.engine.get_state(source_name)
        if state is None:
            state = self.engine.initialize(source_name, normalized, semantic)

        try:
            domain_groups = self.repository.load_domain_groups(source_name)
        except (FileNotFoundError, ValueError):
            domain_groups = self._persist_domain_groups(source_name, state, technical, semantic)

        if self._review_assets_exist(source_name):
            return state

        questionnaire = self.ambiguity.generate_questions(semantic)
        self.repository.save_questionnaire(questionnaire)

        self.artifacts.generate(semantic, output_dir)
        bundle_dir = self.semantic_bundle.write(
            semantic=semantic,
            technical=technical,
            questionnaire=questionnaire,
            source_output_dir=output_dir,
            domain_name=semantic.domain,
        )
        context = self.retrieval.build(
            semantic,
            question=f"What does {source_name} contain and how should it be queried safely?",
        )
        self.artifacts.write_context_package(context, output_dir)
        tag_bundle_dir = self.tag_bundle.export(
            semantic=semantic,
            technical=technical,
            questionnaire=questionnaire,
            source_output_dir=output_dir,
            domain_name=semantic.domain,
        )
        self.chatbot_package.export(
            semantic=semantic,
            technical=technical,
            questionnaire=questionnaire,
            context_package=context,
            source_output_dir=output_dir,
            semantic_bundle_dir=bundle_dir,
            tag_bundle_dir=tag_bundle_dir,
            domain_groups=domain_groups,
            domain_name=semantic.domain,
        )
        return state

    def _persist_domain_groups(
        self,
        source_name: str,
        state: KnowledgeState,
        technical,
        semantic,
    ) -> dict[str, list[str]]:
        try:
            groups = group_tables_by_relationships(
                state,
                technical_metadata=technical,
                semantic_model=semantic,
            )
        except Exception as exc:
            logger.warning("Domain grouping generation failed for source '%s': %s", source_name, exc)
            return {}

        if groups:
            self.repository.save_domain_groups(source_name, groups)
        return groups or {}

    def _merge_counts(self, *items: OnboardingProgressCounts) -> OnboardingProgressCounts:
        merged = OnboardingProgressCounts()
        for item in items:
            for key, value in item.model_dump(exclude_none=True).items():
                setattr(merged, key, value)
        return merged

    def _review_assets_exist(self, source_name: str) -> bool:
        source_dir = self.repository.source_dir(source_name)
        return (
            (source_dir / "questionnaire.json").exists()
            and (self.repository.semantic_bundle_dir(source_name) / "schema_context.json").exists()
            and (source_dir / "chatbot_package" / "manifest.json").exists()
        )
