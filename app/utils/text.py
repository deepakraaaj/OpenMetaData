from __future__ import annotations

import re
from collections.abc import Iterable


def tokenize(value: str) -> list[str]:
    text = str(value or "")
    tokens: list[str] = []
    for segment in re.split(r"[^A-Za-z0-9]+", text):
        if not segment:
            continue
        split_segment = re.sub(r"(.)([A-Z][a-z]+)", r"\1 \2", segment)
        split_segment = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", split_segment)
        for token in split_segment.split():
            cleaned = token.strip().lower()
            if cleaned:
                tokens.append(cleaned)
    return tokens


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
