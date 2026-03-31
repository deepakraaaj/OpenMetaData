from __future__ import annotations

from pathlib import Path

from app.models.normalized import NormalizedSource
from app.models.questionnaire import QuestionnaireBundle
from app.models.semantic import SemanticSourceModel
from app.models.source import DiscoveredSource, DiscoveryReport
from app.models.technical import SourceTechnicalMetadata
from app.utils.files import ensure_dir, source_output_dir
from app.utils.serialization import read_json, write_json, write_yaml


class WorkspaceRepository:
    def __init__(self, config_dir: Path, output_dir: Path) -> None:
        self.config_dir = config_dir
        self.output_dir = output_dir
        ensure_dir(self.config_dir)
        ensure_dir(self.output_dir)

    def save_discovery_report(self, report: DiscoveryReport) -> None:
        write_json(self.config_dir / "discovered_sources.json", report)
        write_yaml(self.config_dir / "discovered_sources.yaml", report)

    def load_discovered_sources(self) -> list[DiscoveredSource]:
        payload = read_json(self.config_dir / "discovered_sources.json")
        report = DiscoveryReport.model_validate(payload)
        return report.discovered_sources

    def source_dir(self, source_name: str) -> Path:
        return source_output_dir(self.output_dir, source_name)

    def save_technical_metadata(self, metadata: SourceTechnicalMetadata) -> Path:
        directory = self.source_dir(metadata.source_name)
        write_json(directory / "technical_metadata.json", metadata)
        write_yaml(directory / "technical_metadata.yaml", metadata)
        return directory / "technical_metadata.json"

    def load_technical_metadata(self, source_name: str) -> SourceTechnicalMetadata:
        payload = read_json(self.source_dir(source_name) / "technical_metadata.json")
        return SourceTechnicalMetadata.model_validate(payload)

    def save_normalized_metadata(self, metadata: NormalizedSource) -> Path:
        directory = self.source_dir(metadata.source_name)
        write_json(directory / "normalized_metadata.json", metadata)
        write_yaml(directory / "normalized_metadata.yaml", metadata)
        return directory / "normalized_metadata.json"

    def load_normalized_metadata(self, source_name: str) -> NormalizedSource:
        payload = read_json(self.source_dir(source_name) / "normalized_metadata.json")
        return NormalizedSource.model_validate(payload)

    def save_semantic_model(self, model: SemanticSourceModel) -> Path:
        directory = self.source_dir(model.source_name)
        write_json(directory / "semantic_model.json", model)
        write_yaml(directory / "semantic_model.yaml", model)
        return directory / "semantic_model.json"

    def load_semantic_model(self, source_name: str) -> SemanticSourceModel:
        payload = read_json(self.source_dir(source_name) / "semantic_model.json")
        return SemanticSourceModel.model_validate(payload)

    def save_questionnaire(self, bundle: QuestionnaireBundle) -> Path:
        directory = self.source_dir(bundle.source_name)
        write_json(directory / "questionnaire.json", bundle)
        write_yaml(directory / "questionnaire.yaml", bundle)
        return directory / "questionnaire.json"

    def load_questionnaire(self, source_name: str) -> QuestionnaireBundle:
        payload = read_json(self.source_dir(source_name) / "questionnaire.json")
        return QuestionnaireBundle.model_validate(payload)

