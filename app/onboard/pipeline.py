from __future__ import annotations

from pathlib import Path

from app.artifacts.generator import ArtifactGenerator
from app.artifacts.semantic_bundle import SemanticBundleExporter
from app.core.settings import Settings
from app.normalization.service import MetadataNormalizer
from app.openmetadata.service import OpenMetadataService
from app.onboard.introspection import DatabaseIntrospector
from app.repositories.filesystem import WorkspaceRepository
from app.retrieval.service import RetrievalContextBuilder
from app.semantics.ambiguity import AmbiguityDetector
from app.semantics.service import SemanticGuessService
from app.models.source import DiscoveredSource


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
        self.retrieval = RetrievalContextBuilder()
        self.openmetadata = OpenMetadataService(settings)

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

        questionnaire = self.ambiguity.generate_questions(semantic)
        self.repository.save_questionnaire(questionnaire)

        self.artifacts.generate(semantic, output_dir)
        self.semantic_bundle.write(
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

        if sync_openmetadata or self.settings.openmetadata_enable_sync:
            openmetadata_dir = self.settings.output_dir / "openmetadata"
            config_path = self.openmetadata.prepare_source_config(source, openmetadata_dir)
            self.openmetadata.run_ingestion(config_path)

        return output_dir
