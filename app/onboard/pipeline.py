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
from app.models.state import KnowledgeState
from app.normalization.service import MetadataNormalizer
from app.openmetadata.service import OpenMetadataService
from app.onboard.introspection import DatabaseIntrospector
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

    def run_source(self, source: DiscoveredSource, sync_openmetadata: bool = False) -> Path:
        technical = self.introspector.introspect_source(source)
        if not technical.connectivity_ok:
            detail = "; ".join(note for note in technical.connectivity_notes if str(note).strip())
            raise OnboardingPipelineError(detail or "Database introspection failed.")

        output_dir = self.repository.source_dir(source.name)
        self.repository.save_technical_metadata(technical)

        normalized = self.normalizer.normalize(source, technical)
        table_count = int((normalized.summary or {}).get("table_count") or 0)
        if table_count <= 0:
            raise OnboardingPipelineError(
                "No tables were discovered for this source. Verify the DB URL, credentials, and schema permissions before retrying."
            )
        self.repository.save_normalized_metadata(normalized)

        semantic = self.semantic.enrich(normalized)
        self.repository.save_semantic_model(semantic)
        state = self.engine.initialize(source.name, normalized, semantic)
        domain_groups = self._persist_domain_groups(source.name, state, technical, semantic)

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
            question=f"What does {source.name} contain and how should it be queried safely?",
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

        if sync_openmetadata or self.settings.openmetadata_enable_sync:
            openmetadata_dir = self.settings.output_dir / "openmetadata"
            config_path = self.openmetadata.prepare_source_config(source, openmetadata_dir)
            self.openmetadata.run_ingestion(config_path)

        return output_dir

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
