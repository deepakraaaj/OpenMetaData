from __future__ import annotations

from pathlib import Path

from app.models.artifacts import LLMContextPackage, SourceArtifact
from app.models.semantic import SemanticSourceModel
from app.utils.files import ensure_dir
from app.utils.serialization import write_json, write_yaml


class ArtifactGenerator:
    def generate(self, semantic: SemanticSourceModel, output_dir: Path) -> None:
        artifacts_dir = output_dir / "artifacts"
        ensure_dir(artifacts_dir)

        source_artifact = SourceArtifact(
            source_name=semantic.source_name,
            db_type=semantic.db_type,
            domain=semantic.domain,
            description=semantic.description,
            key_entities=semantic.key_entities,
            sensitive_areas=semantic.sensitive_areas,
            approved_use_cases=semantic.approved_use_cases,
        )
        write_yaml(artifacts_dir / "source.artifact.yaml", source_artifact)
        write_json(artifacts_dir / "source.artifact.json", source_artifact)

        write_yaml(artifacts_dir / "tables.artifact.yaml", [table.model_dump(mode="json") for table in semantic.tables])
        write_yaml(
            artifacts_dir / "columns.artifact.yaml",
            [
                {
                    "table_name": table.table_name,
                    "columns": [column.model_dump(mode="json") for column in table.columns],
                }
                for table in semantic.tables
            ],
        )
        write_yaml(
            artifacts_dir / "glossary.artifact.yaml",
            [term.model_dump(mode="json") for term in semantic.glossary],
        )
        write_yaml(
            artifacts_dir / "canonical_entities.artifact.yaml",
            [entity.model_dump(mode="json") for entity in semantic.canonical_entities],
        )
        write_yaml(
            artifacts_dir / "query_patterns.artifact.yaml",
            [pattern.model_dump(mode="json") for pattern in semantic.query_patterns],
        )

    def write_context_package(self, package: LLMContextPackage, output_dir: Path) -> None:
        write_json(output_dir / "llm_context_package.json", package)
        write_yaml(output_dir / "llm_context_package.yaml", package)

