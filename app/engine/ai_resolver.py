"""AI-powered gap resolver and table grouping.

Uses the LLM to:
1. Group tables into logical business domains using relationship data
2. Auto-resolve obvious semantic gaps (meanings, enums, relationships)
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from openai import OpenAI

from app.core.settings import get_settings
from app.models.state import KnowledgeState, SemanticGap

logger = logging.getLogger(__name__)


def _get_client() -> OpenAI:
    settings = get_settings()
    return OpenAI(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
    )


def _get_model() -> str:
    return get_settings().llm_model


def _build_schema_summary(state: KnowledgeState) -> str:
    """Build a compact text description of all tables for the LLM."""
    lines: list[str] = []
    for name, table in state.tables.items():
        cols = ", ".join(c.column_name for c in table.columns[:10])
        joins = ", ".join(table.valid_joins[:3]) if table.valid_joins else "none"
        lines.append(f"- {name} ({len(table.columns)} cols: {cols}) joins: [{joins}]")
    return "\n".join(lines)


def ai_group_tables(state: KnowledgeState) -> dict[str, list[str]]:
    """Ask the LLM to group tables into logical business domains."""
    schema_summary = _build_schema_summary(state)

    prompt = f"""You are analyzing a database schema for a business application.
Group these tables into logical business domains (e.g., "Fleet Management", "User & Access", "Trip Tracking", etc.)
based on their names, columns, and join relationships.

Tables:
{schema_summary}

Respond with ONLY valid JSON. No explanation. Format:
{{"domain_name": ["table1", "table2"], "another_domain": ["table3"]}}

Rules:
- Every table must appear in exactly one domain
- Use 4-8 groups max
- Domain names should be short business terms (2-3 words)
- Group related tables together based on joins and naming patterns"""

    try:
        client = _get_client()
        resp = client.chat.completions.create(
            model=_get_model(),
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=2000,
        )
        raw = resp.choices[0].message.content or "{}"
        # Extract JSON from response (may have markdown fences)
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        groups = json.loads(raw.strip())
        if isinstance(groups, dict) and all(isinstance(v, list) for v in groups.values()):
            return groups
    except Exception as e:
        logger.warning(f"AI grouping failed, falling back to prefix grouping: {e}")

    # Fallback: prefix-based grouping
    return _prefix_group_tables(state)


def _prefix_group_tables(state: KnowledgeState) -> dict[str, list[str]]:
    """Fallback: group by table name prefix."""
    groups: dict[str, list[str]] = {}
    for name in state.tables:
        parts = name.split("_")
        prefix = parts[0] if len(parts) > 1 else name
        if prefix not in groups:
            groups[prefix] = []
        groups[prefix].append(name)
    # Merge singletons
    misc: list[str] = []
    merged: dict[str, list[str]] = {}
    for prefix, tables in groups.items():
        if len(tables) < 2:
            misc.extend(tables)
        else:
            merged[prefix] = tables
    if misc:
        merged["misc"] = misc
    return merged


def ai_resolve_gaps(
    state: KnowledgeState,
    gaps: list[SemanticGap],
    max_batch: int = 40,
) -> dict[str, str]:
    """Ask the LLM to answer a batch of semantic gaps.

    Returns a dict of {gap_id: answer_string}.
    Only resolves gaps where the LLM is confident.
    """
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
- Be specific to this domain (this appears to be a vehicle/fleet tracking system)"""

    try:
        client = _get_client()
        resp = client.chat.completions.create(
            model=_get_model(),
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=3000,
        )
        raw = resp.choices[0].message.content or "{}"
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        answers = json.loads(raw.strip())
        if isinstance(answers, dict):
            return {k: str(v) for k, v in answers.items() if v}
    except Exception as e:
        logger.warning(f"AI gap resolution failed: {e}")

    return {}
