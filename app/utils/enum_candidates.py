from __future__ import annotations

from collections.abc import Sequence
import re


BUSINESS_ENUM_TOKENS = (
    "status",
    "state",
    "phase",
    "stage",
    "type",
    "category",
    "mode",
    "priority",
    "severity",
    "reason",
    "result",
    "class",
)

BOOLEAN_LIKE_ENUM_VALUES = {
    "0",
    "1",
    "y",
    "n",
    "yes",
    "no",
    "true",
    "false",
    "on",
    "off",
    "enabled",
    "disabled",
    "active",
    "inactive",
}

TECHNICAL_ENUM_NOISE_TOKENS = (
    "adc",
    "battery",
    "check_sum",
    "checksum",
    "current",
    "digital_input",
    "digital_output",
    "distance",
    "duration",
    "fan_invoice",
    "frame",
    "fuel",
    "gps",
    "gsm",
    "gprs",
    "ignition",
    "imei",
    "imsi",
    "input",
    "invoice_number",
    "kilometer",
    "kilometre",
    "latitude",
    "longitude",
    "meter",
    "meters",
    "mobile",
    "number",
    "odometer",
    "output",
    "packet",
    "phone",
    "plant_code",
    "power",
    "satellite",
    "seconds",
    "sequence",
    "signal",
    "speed",
    "temperature",
    "total",
    "voltage",
)

_DECLARED_ENUM_TYPE_RE = re.compile(r"(^|[^a-z])(enum|set)([^a-z]|$)")


def meaningful_distinct_values(values: Sequence[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = str(raw or "").strip()
        lowered = value.lower()
        if not value or lowered in seen:
            continue
        if lowered in {"<bytes>", "null", "none", "nan"}:
            continue
        seen.add(lowered)
        cleaned.append(value)
    return cleaned


def is_declared_enum_type(data_type: str) -> bool:
    normalized = str(data_type or "").strip().lower()
    if not normalized:
        return False
    return _DECLARED_ENUM_TYPE_RE.search(normalized) is not None


def has_business_enum_signal(column_name: str, extra_tokens: Sequence[str] | None = None) -> bool:
    name = str(column_name or "").strip().lower()
    if not name:
        return False
    if any(token in name for token in BUSINESS_ENUM_TOKENS):
        return True
    return any(token in name for token in tuple(extra_tokens or ()))


def is_technical_enum_noise(column_name: str, values: Sequence[str]) -> bool:
    name = str(column_name or "").strip().lower()
    normalized_values = {str(value).strip().lower() for value in values if str(value).strip()}
    if not name or not normalized_values:
        return False

    all_numeric = all(re.fullmatch(r"[0-9]+", value) for value in normalized_values)
    boolean_like = normalized_values <= BOOLEAN_LIKE_ENUM_VALUES
    if not all_numeric and not boolean_like:
        return False

    if name in BUSINESS_ENUM_TOKENS:
        return False
    return any(token in name for token in TECHNICAL_ENUM_NOISE_TOKENS)


def is_enum_candidate(
    *,
    column_name: str,
    technical_type: str,
    values: Sequence[str],
    extra_name_tokens: Sequence[str] | None = None,
    is_foreign_key: bool = False,
    lookup_backed: bool = False,
) -> bool:
    name = str(column_name or "").strip().lower()
    cleaned_values = meaningful_distinct_values(values)
    if not name or name == "id":
        return False
    if len(cleaned_values) < 2 or len(cleaned_values) > 8:
        return False
    if any(len(value) > 32 for value in cleaned_values):
        return False

    declared_enum = is_declared_enum_type(technical_type)
    business_signal = has_business_enum_signal(name, extra_name_tokens)
    if is_technical_enum_noise(name, cleaned_values) and not (declared_enum or lookup_backed):
        return False

    if is_foreign_key and not (declared_enum or lookup_backed or business_signal):
        return False

    all_numeric = all(re.fullmatch(r"[0-9]+", value) for value in cleaned_values)
    if all_numeric and not (declared_enum or lookup_backed or business_signal):
        return False

    return declared_enum or lookup_backed or business_signal
