from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field

from app.core.settings import get_settings
from app.utils.serialization import read_yaml


class CommunicationDirectoryRules(BaseModel):
    support_column_tokens: tuple[str, ...] = ()
    structure_tokens: tuple[str, ...] = ()
    related_entity_labels: dict[str, str] = Field(default_factory=dict)
    minimum_support_columns: int = 2
    minimum_support_columns_without_structure: int = 3
    minimum_related_entities_without_structure: int = 2


class GapDetectionRules(BaseModel):
    audit_column_suffixes: tuple[str, ...] = ()
    audit_column_names: tuple[str, ...] = ()
    temporal_name_tokens: tuple[str, ...] = ()
    enum_name_tokens: tuple[str, ...] = ()
    boolean_prefixes: tuple[str, ...] = ()


class TableMeaningRules(BaseModel):
    mapping_suffixes: tuple[str, ...] = ()
    history_suffixes: tuple[str, ...] = ()
    detail_suffixes: tuple[str, ...] = ()
    lifecycle_tokens: tuple[str, ...] = ()


class ColumnMeaningRules(BaseModel):
    status_tokens: tuple[str, ...] = ()
    classification_tokens: tuple[str, ...] = ()
    timestamp_tokens: tuple[str, ...] = ()


class SemanticInferenceRules(BaseModel):
    domain_rules: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    actor_table_priority: tuple[str, ...] = ()
    audit_actor_patterns: dict[str, str] = Field(default_factory=dict)
    actor_responsibility_roles: tuple[str, ...] = ()
    communication_directory: CommunicationDirectoryRules = Field(
        default_factory=CommunicationDirectoryRules
    )
    table_meaning: TableMeaningRules = Field(default_factory=TableMeaningRules)
    column_meaning: ColumnMeaningRules = Field(default_factory=ColumnMeaningRules)
    gap_detection: GapDetectionRules = Field(default_factory=GapDetectionRules)


def _candidate_rule_paths(config_dir: Path | None = None) -> list[Path]:
    if config_dir is not None:
        return [config_dir / "semantic_inference.yaml"]
    settings_path = get_settings().config_dir / "semantic_inference.yaml"
    repo_local_path = Path(__file__).resolve().parents[2] / "config" / "semantic_inference.yaml"
    if repo_local_path == settings_path:
        return [settings_path]
    return [settings_path, repo_local_path]


@lru_cache(maxsize=4)
def load_inference_rules(config_dir: Path | None = None) -> SemanticInferenceRules:
    for path in _candidate_rule_paths(config_dir):
        if not path.exists():
            continue
        payload = read_yaml(path) or {}
        return SemanticInferenceRules.model_validate(payload)
    return SemanticInferenceRules()
