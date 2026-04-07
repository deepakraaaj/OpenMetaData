"""AI-powered gap resolver + deterministic relationship-based table grouping.

Grouping: Uses the existing join/FK graph (no LLM needed).
Gap resolution: Uses the LLM to auto-answer business meanings, enums, etc.
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict

from openai import OpenAI

from app.core.settings import get_settings
from app.models.state import KnowledgeState, SemanticGap

logger = logging.getLogger(__name__)


# ── Deterministic table grouping via relationship graph ────────────────────

def group_tables_by_relationships(state: KnowledgeState) -> dict[str, list[str]]:
    """Group tables using the FK/join graph. Pure graph traversal, no LLM."""
    table_names = list(state.tables.keys())
    if not table_names:
        return {}

    # Build adjacency list from valid_joins
    adj: dict[str, set[str]] = defaultdict(set)
    for name, table in state.tables.items():
        for join in table.valid_joins:
            # join looks like "table_a.col=table_b.col"
            parts = join.split("=")
            if len(parts) == 2:
                left_table = parts[0].split(".")[0]
                right_table = parts[1].split(".")[0]
                if left_table in state.tables and right_table in state.tables:
                    adj[left_table].add(right_table)
                    adj[right_table].add(left_table)

    # Find connected components via BFS
    visited: set[str] = set()
    components: list[list[str]] = []

    for table in table_names:
        if table in visited:
            continue
        component: list[str] = []
        queue = [table]
        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            component.append(current)
            for neighbor in adj.get(current, set()):
                if neighbor not in visited:
                    queue.append(neighbor)
        components.append(sorted(component))

    # Name each group by the most common prefix or the largest table
    groups: dict[str, list[str]] = {}
    for comp in sorted(components, key=len, reverse=True):
        if len(comp) == 1:
            # Collect singletons later
            continue
        label = _pick_group_label(comp)
        groups[label] = comp

    # Collect singletons
    singletons = [t for comp in components if len(comp) == 1 for t in comp]
    if singletons:
        # Try to merge singletons with related groups by prefix
        remaining: list[str] = []
        for s in singletons:
            prefix = s.split("_")[0] if "_" in s else s
            merged = False
            for label, members in groups.items():
                if any(m.startswith(prefix + "_") for m in members):
                    members.append(s)
                    merged = True
                    break
            if not merged:
                remaining.append(s)
        if remaining:
            groups["misc"] = remaining

    return groups


def _pick_group_label(tables: list[str]) -> str:
    """Pick a readable label for a group of related tables."""
    # Count prefixes
    prefix_counts: dict[str, int] = defaultdict(int)
    for t in tables:
        prefix = t.split("_")[0] if "_" in t else t
        prefix_counts[prefix] += 1
    # Use the most common prefix
    best_prefix = max(prefix_counts, key=lambda k: prefix_counts[k])
    return best_prefix


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
    """Build a compact text description of all tables for the LLM."""
    lines: list[str] = []
    for name, table in state.tables.items():
        cols = ", ".join(c.column_name for c in table.columns[:10])
        joins = ", ".join(table.valid_joins[:3]) if table.valid_joins else "none"
        lines.append(f"- {name} ({len(table.columns)} cols: {cols}) joins: [{joins}]")
    return "\n".join(lines)


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
