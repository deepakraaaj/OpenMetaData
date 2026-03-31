from __future__ import annotations

from pathlib import Path


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def source_output_dir(base_dir: Path, source_name: str) -> Path:
    output_dir = base_dir / source_name
    ensure_dir(output_dir)
    return output_dir

