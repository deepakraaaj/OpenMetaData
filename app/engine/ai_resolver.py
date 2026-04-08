"""AI-powered gap resolver plus relation-driven table grouping."""
from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import re
from collections import defaultdict, deque
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request

from openai import OpenAI

from app.core.settings import get_settings
from app.models.semantic import SemanticSourceModel
from app.models.state import KnowledgeState, SemanticGap
from app.models.technical import SourceTechnicalMetadata

logger = logging.getLogger(__name__)

_MISC_LABEL = "Miscellaneous"
_MISC_ALIASES = {"misc", "miscellaneous", "technical", "system", "other", "admin"}
_LOCAL_OLLAMA_URL = "http://127.0.0.1:11434/v1"


@dataclass(frozen=True)
class _LLMCandidate:
    base_url: str
    model: str
    api_key: str
    name: str


def group_tables_by_relationships(
    state: KnowledgeState,
    *,
    technical_metadata: SourceTechnicalMetadata | None = None,
    semantic_model: SemanticSourceModel | None = None,
) -> dict[str, list[str]]:
    """Group tables using full schema structure plus LLM reasoning."""
    table_names = sorted(state.tables.keys())
    if not table_names:
        return {}

    adjacency = _build_relationship_adjacency(state, technical_metadata=technical_metadata)
    ai_groups = _group_tables_with_llm(
        state,
        adjacency,
        technical_metadata=technical_metadata,
        semantic_model=semantic_model,
    )
    if ai_groups:
        return _finalize_groups(ai_groups, table_names, adjacency)
    return _deterministic_group_fallback(state, adjacency)


def _build_relationship_adjacency(
    state: KnowledgeState,
    *,
    technical_metadata: SourceTechnicalMetadata | None = None,
) -> dict[str, set[str]]:
    adjacency: dict[str, set[str]] = defaultdict(set)
    for table in state.tables.values():
        for join in table.valid_joins:
            parts = str(join or "").split("=")
            if len(parts) != 2:
                continue
            left_table = parts[0].split(".")[0].strip()
            right_table = parts[1].split(".")[0].strip()
            if (
                left_table
                and right_table
                and left_table != right_table
                and left_table in state.tables
                and right_table in state.tables
            ):
                adjacency[left_table].add(right_table)
                adjacency[right_table].add(left_table)

    if technical_metadata is not None:
        known_tables = set(state.tables.keys())
        for schema in technical_metadata.schemas:
            for table in schema.tables:
                if table.table_name not in known_tables:
                    continue
                for foreign_key in table.foreign_keys:
                    neighbor = str(foreign_key.referred_table or "").strip()
                    if neighbor and neighbor in known_tables and neighbor != table.table_name:
                        adjacency[table.table_name].add(neighbor)
                        adjacency[neighbor].add(table.table_name)
                for candidate in table.candidate_joins:
                    left_table = str(candidate.left_table or "").strip()
                    right_table = str(candidate.right_table or "").strip()
                    if (
                        left_table
                        and right_table
                        and left_table != right_table
                        and left_table in known_tables
                        and right_table in known_tables
                    ):
                        adjacency[left_table].add(right_table)
                        adjacency[right_table].add(left_table)
    return adjacency


def _connected_components(table_names: list[str], adjacency: dict[str, set[str]]) -> list[list[str]]:
    visited: set[str] = set()
    components: list[list[str]] = []

    for table_name in table_names:
        if table_name in visited:
            continue
        queue: deque[str] = deque([table_name])
        component: list[str] = []
        while queue:
            current = queue.popleft()
            if current in visited:
                continue
            visited.add(current)
            component.append(current)
            for neighbor in sorted(adjacency.get(current, set())):
                if neighbor not in visited:
                    queue.append(neighbor)
        components.append(sorted(component))
    return sorted(components, key=lambda item: (-len(item), item[0]))


def _normalize_table_name(value: Any) -> str:
    return str(value or "").strip()


def _normalize_group_label(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if not text:
        return ""
    if text.lower() in _MISC_ALIASES:
        return _MISC_LABEL
    if "_" in text and re.fullmatch(r"[a-z0-9_]+", text):
        return " ".join(part.capitalize() for part in text.split("_") if part)
    return text


def _extract_json_object(raw: str) -> dict[str, Any] | list[Any] | None:
    text = str(raw or "").strip()
    if not text:
        return None
    if "```" in text:
        for block in re.findall(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE):
            candidate = block.strip()
            try:
                payload = json.loads(candidate)
            except Exception:
                continue
            if isinstance(payload, (dict, list)):
                return payload
    try:
        payload = json.loads(text)
        if isinstance(payload, (dict, list)):
            return payload
    except Exception:
        pass

    match = re.search(r"(\{.*\}|\[.*\])", text, flags=re.DOTALL)
    if not match:
        return None
    try:
        payload = json.loads(match.group(1))
    except Exception:
        return None
    return payload if isinstance(payload, (dict, list)) else None


def _normalize_group_payload(payload: Any) -> dict[str, list[str]] | None:
    if isinstance(payload, dict) and isinstance(payload.get("groups"), list):
        items = payload.get("groups") or []
    elif isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        normalized: dict[str, list[str]] = {}
        for key, value in payload.items():
            if not isinstance(value, list):
                continue
            label = _normalize_group_label(key)
            if not label:
                continue
            normalized.setdefault(label, []).extend(_normalize_table_name(item) for item in value)
        return normalized or None
    else:
        return None

    normalized = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        label = _normalize_group_label(item.get("label") or item.get("group") or item.get("name"))
        tables = item.get("tables")
        if not label or not isinstance(tables, list):
            continue
        normalized.setdefault(label, []).extend(_normalize_table_name(entry) for entry in tables)
    return normalized or None


def _component_hubs(component: list[str], adjacency: dict[str, set[str]]) -> list[str]:
    return sorted(component, key=lambda name: (-len(adjacency.get(name, set())), name))


def _table_summary_lines(state: KnowledgeState, adjacency: dict[str, set[str]]) -> list[str]:
    lines: list[str] = []
    for table_name in sorted(state.tables.keys()):
        table = state.tables[table_name]
        neighbors = sorted(adjacency.get(table_name, set()))
        meaning = re.sub(r"\s+", " ", str(table.business_meaning or "")).strip()
        likely_entity = str(table.likely_entity or "").strip()
        columns = [column.column_name for column in table.columns[:6]]
        line = (
            f"- {table_name} | entity={likely_entity or '-'} | "
            f"meaning={meaning or '-'} | degree={len(neighbors)} | "
            f"neighbors={', '.join(neighbors[:6]) if neighbors else 'none'} | "
            f"columns={', '.join(columns) if columns else 'none'}"
        )
        lines.append(line)
    return lines


def _component_summary_lines(table_names: list[str], adjacency: dict[str, set[str]]) -> list[str]:
    lines: list[str] = []
    for index, component in enumerate(_connected_components(table_names, adjacency), start=1):
        hubs = _component_hubs(component, adjacency)[:4]
        member_preview = ", ".join(component[:12])
        if len(component) > 12:
            member_preview += ", ..."
        lines.append(
            f"- cluster_{index}: size={len(component)} | hubs={', '.join(hubs) if hubs else 'none'} | members={member_preview}"
        )
    return lines


def _collect_semantic_table_map(
    state: KnowledgeState,
    semantic_model: SemanticSourceModel | None,
) -> dict[str, Any]:
    semantic_tables: dict[str, Any] = {}
    if semantic_model is not None:
        for table in semantic_model.tables:
            semantic_tables[str(table.table_name).strip()] = table
    for table_name, table in state.tables.items():
        semantic_tables.setdefault(table_name, table)
    return semantic_tables


def _format_column_descriptor(column: Any) -> str:
    markers: list[str] = []
    if bool(getattr(column, "is_primary_key", False)):
        markers.append("pk")
    if bool(getattr(column, "is_foreign_key", False)):
        referenced_table = str(getattr(column, "referenced_table", "") or "").strip()
        referenced_column = str(getattr(column, "referenced_column", "") or "").strip()
        if referenced_table and referenced_column:
            markers.append(f"fk>{referenced_table}.{referenced_column}")
        elif referenced_table:
            markers.append(f"fk>{referenced_table}")
        else:
            markers.append("fk")
    if bool(getattr(column, "is_status_like", False)):
        markers.append("status")
    if bool(getattr(column, "is_timestamp_like", False)):
        markers.append("timestamp")
    if bool(getattr(column, "is_identifier_like", False)):
        markers.append("identifier")

    column_name = str(getattr(column, "name", "") or getattr(column, "column_name", "") or "").strip()
    if markers:
        return f"{column_name}[{','.join(markers)}]"
    return column_name


def _build_full_schema_lines(
    state: KnowledgeState,
    adjacency: dict[str, set[str]],
    technical_metadata: SourceTechnicalMetadata | None,
    semantic_model: SemanticSourceModel | None,
) -> list[str]:
    technical_table_map: dict[str, Any] = {}
    if technical_metadata is not None:
        for schema in technical_metadata.schemas:
            for table in schema.tables:
                technical_table_map[str(table.table_name).strip()] = table

    lines: list[str] = []
    for table_name in sorted(state.tables.keys()):
        technical_table = technical_table_map.get(table_name)

        if technical_table is not None:
            columns = [_format_column_descriptor(column) for column in technical_table.columns]
            primary_key = list(technical_table.primary_key or [])
        else:
            state_table = state.tables[table_name]
            columns = [_format_column_descriptor(column) for column in state_table.columns]
            primary_key = [
                column.column_name
                for column in state_table.columns
                if "pk" in _format_column_descriptor(column)
            ]

        neighbors = sorted(adjacency.get(table_name, set()))
        lines.append(
            " | ".join(
                [
                    f"{table_name}",
                    f"pk={','.join(primary_key) if primary_key else '-'}",
                    f"neighbors={','.join(neighbors) if neighbors else '-'}",
                    f"cols={','.join(columns) if columns else '-'}",
                ]
            )
        )
    return lines


def _build_grouping_prompt(state: KnowledgeState, adjacency: dict[str, set[str]]) -> str:
    table_names = sorted(state.tables.keys())
    table_lines = _table_summary_lines(state, adjacency)
    component_lines = _component_summary_lines(table_names, adjacency)
    min_group_count = 2 if len(table_names) <= 8 else 3
    max_group_count = min(8, max(4, len(table_names) // 10 + 2))

    return f"""You are grouping database tables into business-facing domains for an onboarding UI.

SOURCE: {state.source_name}

RELATION CLUSTERS:
{chr(10).join(component_lines)}

TABLE CONTEXT:
{chr(10).join(table_lines)}

Task:
Group the tables into business domains using BOTH:
1. relation neighborhoods and graph structure
2. semantic reasoning from table names, likely entities, and business meanings

Important rules:
- Some joins may be noisy or generic. Do NOT let one weak bridge collapse the whole schema into one giant bucket.
- Prefer workflow-oriented domains over technical prefixes.
- Put obvious technical/system leftovers into "{_MISC_LABEL}".
- Assign every table exactly once.
- Use between {min_group_count} and {max_group_count} groups unless the schema is truly tiny.
- Labels must be short, human-readable, and business-facing. Example style: "Vehicles & Telematics".
- Do not invent tables or labels that do not fit the schema.

Return ONLY valid JSON in this exact shape:
{{
  "groups": [
    {{
      "label": "Vehicles & Telematics",
      "tables": ["vehicle", "vehicle_communication"]
    }}
  ]
}}"""


def _build_full_schema_grouping_prompt(
    state: KnowledgeState,
    adjacency: dict[str, set[str]],
    technical_metadata: SourceTechnicalMetadata | None,
    semantic_model: SemanticSourceModel | None,
) -> str:
    table_names = sorted(state.tables.keys())
    component_lines = _component_summary_lines(table_names, adjacency)
    schema_lines = _build_full_schema_lines(state, adjacency, technical_metadata, semantic_model)
    min_group_count = 3 if len(table_names) >= 20 else 2
    max_group_count = min(10, max(4, len(table_names) // 9 + 2))
    total_columns = sum(len(table.columns) for table in state.tables.values())

    return f"""You are designing clean business-domain groupings for a database onboarding UI.

SOURCE: {state.source_name}
TOTAL_TABLES: {len(table_names)}
TOTAL_COLUMNS: {total_columns}

CONNECTED RELATION CLUSTERS:
{chr(10).join(component_lines)}

FULL SCHEMA STRUCTURE:
{chr(10).join(schema_lines)}

Goal:
Create clear, business-facing categories for the entire schema.

Requirements:
- Use the FULL schema structure above, not just prefixes.
- Keep strongly related tables together when they support the same business workflow.
- Split apart giant confusing clusters into clearer business areas when weak or generic joins are the only bridge.
- Every table must appear exactly once.
- Use between {min_group_count} and {max_group_count} groups unless the schema is truly simpler.
- Labels must be business-facing and human-readable.
- Labels must NOT be raw table names, mapping table names, or technical suffix phrases like "master", "mapping", "history", "cfg", or "log".
- Good label examples: "Vehicles & Telematics", "Trips & Dispatch", "Alerts & Monitoring", "Support & Communications".
- Put only real leftovers into "{_MISC_LABEL}".

Return ONLY valid JSON in this exact shape:
{{
  "groups": [
    {{
      "label": "Vehicles & Telematics",
      "summary": "Core vehicle, device, and live telemetry tables.",
      "tables": ["vehicle", "vts_transaction", "vehicle_communication"]
    }}
  ]
}}"""


def _compact_grouping_columns(technical_table: Any, state_table: Any, *, limit: int = 12) -> list[str]:
    technical_columns = list(getattr(technical_table, "columns", []) or []) if technical_table is not None else []
    state_columns = list(getattr(state_table, "columns", []) or [])

    prioritized: list[str] = []
    seen: set[str] = set()

    def add(name: str) -> None:
        cleaned = str(name or "").strip()
        key = cleaned.lower()
        if not cleaned or key in seen:
            return
        seen.add(key)
        prioritized.append(cleaned)

    for column in technical_columns:
        name = str(getattr(column, "name", "") or "").strip()
        lowered = name.lower()
        if (
            bool(getattr(column, "is_primary_key", False))
            or bool(getattr(column, "is_foreign_key", False))
            or bool(getattr(column, "is_status_like", False))
            or bool(getattr(column, "is_timestamp_like", False))
            or bool(getattr(column, "is_identifier_like", False))
            or any(token in lowered for token in ("name", "number", "imei", "status", "state", "type", "category"))
        ):
            add(name)
    for column in technical_columns:
        add(str(getattr(column, "name", "") or "").strip())
        if len(prioritized) >= limit:
            break
    for column in state_columns:
        add(str(getattr(column, "column_name", "") or "").strip())
        if len(prioritized) >= limit:
            break
    return prioritized[:limit]


def _build_local_fallback_grouping_prompt(
    state: KnowledgeState,
    adjacency: dict[str, set[str]],
    technical_metadata: SourceTechnicalMetadata | None,
) -> str:
    technical_table_map: dict[str, Any] = {}
    if technical_metadata is not None:
        for schema in technical_metadata.schemas:
            for table in schema.tables:
                technical_table_map[str(table.table_name).strip()] = table

    lines: list[str] = []
    for table_name in sorted(state.tables.keys()):
        technical_table = technical_table_map.get(table_name)
        state_table = state.tables[table_name]
        pk = []
        if technical_table is not None:
            pk = list(technical_table.primary_key or [])
        compact_cols = _compact_grouping_columns(technical_table, state_table)
        neighbors = sorted(adjacency.get(table_name, set()))[:8]
        lines.append(
            " | ".join(
                [
                    table_name,
                    f"pk={','.join(pk) if pk else '-'}",
                    f"links={','.join(neighbors) if neighbors else '-'}",
                    f"cols={','.join(compact_cols) if compact_cols else '-'}",
                ]
            )
        )

    return f"""Group this database schema into clear business domains.

Rules:
- Use relation links first, names second.
- Keep every table in exactly one group.
- Prefer clean business labels, not raw table names.
- Use only a small Miscellaneous group for real leftovers.

SCHEMA:
{chr(10).join(lines)}

Return ONLY valid JSON:
{{
  "groups": [
    {{"label": "Vehicles & Telematics", "tables": ["vehicle", "vts_transaction"]}}
  ]
}}"""


def _normalize_lookup_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _technical_label_issues(groups: dict[str, list[str]], table_names: list[str]) -> list[str]:
    issues: list[str] = []
    normalized_table_names = {_normalize_lookup_key(name): name for name in table_names}
    total_tables = len(table_names)

    if total_tables >= 20 and len(groups) < 3:
        issues.append("too few groups for a large schema")

    for label, members in groups.items():
        if label == _MISC_LABEL:
            continue
        normalized_label = _normalize_lookup_key(label)
        if normalized_label in normalized_table_names:
            issues.append(f"label '{label}' is just a table name")
        lowered = label.lower()
        if any(token in lowered for token in (" mapping", " history", " master", " cfg", " log")):
            issues.append(f"label '{label}' is too technical")
        if total_tables >= 20 and len(members) > int(total_tables * 0.7):
            issues.append(f"label '{label}' is too broad and captures most tables")
    return issues


def _settings_candidate() -> _LLMCandidate | None:
    settings = get_settings()
    base_url = str(settings.llm_base_url or "").strip()
    model = str(settings.llm_model or "").strip()
    if not base_url or not model:
        return None
    return _LLMCandidate(
        base_url=base_url,
        model=model,
        api_key=str(settings.llm_api_key or "dummy"),
        name="openmetadata-env",
    )


def _local_ollama_candidate() -> _LLMCandidate | None:
    try:
        with urllib_request.urlopen(f"{_LOCAL_OLLAMA_URL}/models", timeout=2.0) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib_error.URLError, urllib_error.HTTPError, TimeoutError, OSError, ValueError):
        return None

    models = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(models, list):
        return None
    for item in models:
        if not isinstance(item, dict):
            continue
        model_id = str(item.get("id") or "").strip()
        if model_id:
            return _LLMCandidate(
                base_url=_LOCAL_OLLAMA_URL,
                model=model_id,
                api_key="dummy",
                name=f"local-ollama:{model_id}",
            )
    return None


def _llm_candidates() -> list[_LLMCandidate]:
    candidates: list[_LLMCandidate] = []
    seen: set[tuple[str, str]] = set()
    for candidate in (_settings_candidate(), _local_ollama_candidate()):
        if candidate is None:
            continue
        key = (candidate.base_url, candidate.model)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(candidate)
    return candidates


def _group_tables_with_llm(
    state: KnowledgeState,
    adjacency: dict[str, set[str]],
    *,
    technical_metadata: SourceTechnicalMetadata | None,
    semantic_model: SemanticSourceModel | None,
) -> dict[str, list[str]] | None:
    prompt = _build_full_schema_grouping_prompt(
        state,
        adjacency,
        technical_metadata,
        semantic_model,
    )
    retry_feedback = ""
    table_names = sorted(state.tables.keys())

    candidates = _llm_candidates()
    if not candidates:
        logger.warning("AI table grouping fell back because no LLM candidates are configured or reachable")
        return None

    for candidate in candidates:
        retry_feedback = ""
        is_local_candidate = candidate.base_url == _LOCAL_OLLAMA_URL
        client = OpenAI(
            base_url=candidate.base_url,
            api_key=candidate.api_key,
            timeout=18.0 if is_local_candidate else 30.0,
            max_retries=0,
        )
        candidate_prompt = prompt
        if is_local_candidate:
            candidate_prompt = _build_local_fallback_grouping_prompt(
                state,
                adjacency,
                technical_metadata,
            )
        max_attempts = 1 if is_local_candidate else 2
        max_tokens = 1200 if is_local_candidate else 1800
        for attempt in range(max_attempts):
            try:
                user_prompt = candidate_prompt
                if retry_feedback:
                    user_prompt = (
                        f"{candidate_prompt}\n\nQUALITY FEEDBACK FROM LAST ATTEMPT:\n"
                        f"{retry_feedback}\nRegenerate the grouping."
                    )
                response = client.chat.completions.create(
                    model=candidate.model,
                    messages=[
                        {
                            "role": "system",
                            "content": "You are a precise schema analysis assistant. Output valid JSON only.",
                        },
                        {
                            "role": "user",
                            "content": user_prompt,
                        },
                    ],
                    temperature=0.0,
                    max_tokens=max_tokens,
                )
                raw = response.choices[0].message.content or ""
                payload = _extract_json_object(raw)
                groups = _normalize_group_payload(payload)
                if not groups:
                    retry_feedback = "The previous output was not valid JSON in the required groups format."
                    continue
                issues = _technical_label_issues(groups, table_names)
                if not issues:
                    logger.info(
                        "AI table grouping succeeded with candidate '%s' on attempt %d",
                        candidate.name,
                        attempt + 1,
                    )
                    return groups
                retry_feedback = "\n".join(f"- {issue}" for issue in issues[:8])
            except Exception as exc:
                logger.warning(
                    "AI table grouping failed with candidate '%s' on attempt %d: %s",
                    candidate.name,
                    attempt + 1,
                    exc,
                )
                break

    logger.warning("AI table grouping fell back to deterministic grouping after all LLM candidates failed")
    return None


def _best_existing_group_for_table(
    table_name: str,
    adjacency: dict[str, set[str]],
    assignments: dict[str, str],
) -> str:
    scores: dict[str, int] = defaultdict(int)
    for neighbor in adjacency.get(table_name, set()):
        label = assignments.get(neighbor)
        if label and label != _MISC_LABEL:
            scores[label] += 1
    if not scores:
        return _MISC_LABEL
    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    best_label, best_score = ranked[0]
    second_score = ranked[1][1] if len(ranked) > 1 else 0
    if best_score == second_score and len(ranked) > 1:
        return _MISC_LABEL
    return best_label


def _finalize_groups(
    proposed_groups: dict[str, list[str]],
    table_names: list[str],
    adjacency: dict[str, set[str]],
) -> dict[str, list[str]]:
    known_tables = set(table_names)
    assignments: dict[str, str] = {}
    groups: dict[str, list[str]] = {}

    for raw_label, raw_members in proposed_groups.items():
        label = _normalize_group_label(raw_label)
        if not label:
            continue
        for raw_table in raw_members:
            table_name = _normalize_table_name(raw_table)
            if not table_name or table_name not in known_tables or table_name in assignments:
                continue
            assignments[table_name] = label
            groups.setdefault(label, []).append(table_name)

    for table_name in table_names:
        if table_name in assignments:
            continue
        label = _best_existing_group_for_table(table_name, adjacency, assignments)
        assignments[table_name] = label
        groups.setdefault(label, []).append(table_name)

    normalized_groups: dict[str, list[str]] = {}
    for label, members in groups.items():
        deduped = sorted({member for member in members if member in known_tables})
        if deduped:
            normalized_groups[label] = deduped

    return _sort_groups(normalized_groups)


def _fallback_label_for_component(
    state: KnowledgeState,
    component: list[str],
    adjacency: dict[str, set[str]],
) -> str:
    hub = _component_hubs(component, adjacency)[0]
    table = state.tables.get(hub)
    if table is None:
        return _MISC_LABEL
    entity = str(table.likely_entity or "").strip()
    if entity:
        return entity
    name = hub.replace("_", " ").strip()
    return " ".join(part.capitalize() for part in name.split()) or _MISC_LABEL


def _deterministic_group_fallback(
    state: KnowledgeState,
    adjacency: dict[str, set[str]],
) -> dict[str, list[str]]:
    table_names = sorted(state.tables.keys())
    components = _connected_components(table_names, adjacency)
    groups: dict[str, list[str]] = {}
    misc_members: list[str] = []

    for component in components:
        if len(component) == 1:
            misc_members.extend(component)
            continue
        label = _fallback_label_for_component(state, component, adjacency)
        groups.setdefault(label, []).extend(component)

    if misc_members:
        groups.setdefault(_MISC_LABEL, []).extend(misc_members)

    return _sort_groups({label: sorted(set(members)) for label, members in groups.items() if members})


def _sort_groups(groups: dict[str, list[str]]) -> dict[str, list[str]]:
    return dict(
        sorted(
            ((label, sorted(set(members))) for label, members in groups.items() if members),
            key=lambda item: (item[0] == _MISC_LABEL, -len(item[1]), item[0].lower()),
        )
    )


# ── LLM-powered gap resolution ────────────────────────────────────────────

def _get_client() -> OpenAI:
    settings = get_settings()
    return OpenAI(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
    )


def _get_model() -> str:
    return get_settings().llm_model


def _build_schema_summary(state: KnowledgeState) -> str:
    """Build a compact text description grouped by domains for higher LLM reasoning accuracy."""
    groups = group_tables_by_relationships(state)

    sections: list[str] = []
    for domain, tables in groups.items():
        domain_lines = [f"DOMAIN: {domain.upper()}"]
        for name in tables:
            if name not in state.tables:
                continue
            table = state.tables[name]
            cols = ", ".join(c.column_name for c in table.columns[:8])
            domain_lines.append(f"  - {name} ({len(table.columns)} cols): {cols}")
        sections.append("\n".join(domain_lines))

    return "\n\n".join(sections)


def ai_resolve_gaps(
    state: KnowledgeState,
    gaps: list[SemanticGap],
    max_batch: int = 40,
) -> dict[str, str]:
    """Ask the LLM to answer a batch of semantic gaps."""
    if not gaps:
        return {}

    batch = gaps[:max_batch]
    schema_summary = _build_schema_summary(state)

    gap_lines: list[str] = []
    for g in batch:
        gap_lines.append(
            f"- gap_id: \"{g.gap_id}\"\n"
            f"  category: {g.category.value}\n"
            f"  entity: {g.target_entity or 'N/A'}\n"
            f"  property: {g.target_property or 'N/A'}\n"
            f"  question: {g.suggested_question or g.description}"
        )

    prompt = f"""You are a database domain expert. The system introspected a database and needs your help understanding the schema.

SCHEMA:
{schema_summary}

GAPS TO RESOLVE:
{chr(10).join(gap_lines)}

For each gap, provide a concise answer. Respond with ONLY valid JSON. No explanation. Format:
{{"gap_id_1": "your answer", "gap_id_2": "your answer"}}

Rules:
- For business_meaning gaps: describe what the table represents in 1 sentence
- For enum_mapping gaps: provide mappings like "0=Inactive, 1=Active"
- For relationship gaps: answer "Yes" or "No"
- For sensitivity gaps: answer "Yes, mask this column" or "No, it is safe to display"
- For glossary gaps: provide the business term users would use
- If you are uncertain about a gap, SKIP it (don't include its gap_id in the response)
- Be specific to this domain"""

    try:
        client = _get_client()
        resp = client.chat.completions.create(
            model=_get_model(),
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=3000,
        )
        raw = resp.choices[0].message.content or "{}"
        payload = _extract_json_object(raw)
        if isinstance(payload, dict):
            return {k: str(v) for k, v in payload.items() if v}
    except Exception as exc:
        logger.warning("AI gap resolution failed: %s", exc)

    return {}
