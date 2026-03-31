from __future__ import annotations

import re
from collections.abc import Iterable


TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


def tokenize(value: str) -> list[str]:
    return [match.group(0).lower() for match in TOKEN_RE.finditer(value)]


def snake_to_words(value: str) -> str:
    return " ".join(part for part in re.split(r"[_\W]+", value) if part)


def normalized_name(value: str) -> str:
    return "_".join(tokenize(value))


def unique_non_empty(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if not value:
            continue
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered
