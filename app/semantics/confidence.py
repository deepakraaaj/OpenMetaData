from __future__ import annotations

from app.models.common import ConfidenceLabel, NamedConfidence
from app.utils.text import unique_non_empty


def clamp_score(value: float) -> float:
    return round(min(max(value, 0.0), 1.0), 2)


def named_confidence(
    score: float,
    rationale: list[str],
    *,
    high_threshold: float = 0.78,
    medium_threshold: float = 0.55,
) -> NamedConfidence:
    normalized = clamp_score(score)
    if normalized >= high_threshold:
        label = ConfidenceLabel.high
    elif normalized >= medium_threshold:
        label = ConfidenceLabel.medium
    else:
        label = ConfidenceLabel.low
    return NamedConfidence(
        label=label,
        score=normalized,
        rationale=unique_non_empty([str(item).strip() for item in rationale if str(item).strip()]),
    )


def weighted_confidence(parts: list[tuple[float, float]], rationale: list[str]) -> NamedConfidence:
    total_weight = sum(weight for weight, _score in parts) or 1.0
    score = sum(weight * score for weight, score in parts) / total_weight
    return named_confidence(score, rationale)
