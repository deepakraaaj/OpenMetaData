from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from app.utils.files import ensure_parent


def _to_data(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", exclude_none=True)
    if isinstance(value, list):
        return [_to_data(item) for item in value]
    if isinstance(value, dict):
        return {key: _to_data(item) for key, item in value.items()}
    return value


def write_json(path: Path, value: Any) -> None:
    ensure_parent(path)
    path.write_text(json.dumps(_to_data(value), indent=2, sort_keys=False), encoding="utf-8")


def write_yaml(path: Path, value: Any) -> None:
    ensure_parent(path)
    path.write_text(yaml.safe_dump(_to_data(value), sort_keys=False), encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))

