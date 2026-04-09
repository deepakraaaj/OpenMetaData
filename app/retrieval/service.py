from __future__ import annotations

from collections import defaultdict

from app.models.artifacts import LLMContextPackage
from app.models.decision import DecisionStatus
from app.models.semantic import SemanticSourceModel
from app.utils.text import tokenize


class RetrievalContextBuilder:
    def build(self, semantic: SemanticSourceModel, question: str) -> LLMContextPackage:
        q_tokens = self._expanded_tokens(question)
        table_scores: dict[str, int] = defaultdict(int)
        column_scores: dict[str, int] = defaultdict(int)
        glossary_scores: dict[str, int] = defaultdict(int)
        pattern_scores: dict[str, int] = defaultdict(int)

        for table in semantic.tables:
            table_tokens = self._expanded_tokens(table.table_name)
            table_scores[table.table_name] += len(q_tokens & table_tokens)
            for column in table.columns:
                column_key = f"{table.table_name}.{column.column_name}"
                column_scores[column_key] += len(q_tokens & self._expanded_tokens(column.column_name))
        for term in semantic.glossary:
            glossary_scores[term.term] += len(q_tokens & self._expanded_tokens(term.term))
        for pattern in semantic.query_patterns:
            pattern_scores[pattern.intent] += len(q_tokens & self._expanded_tokens(pattern.intent))

        matched_tables = [name for name, score in sorted(table_scores.items(), key=lambda item: item[1], reverse=True) if score > 0][:8]
        matched_columns = [name for name, score in sorted(column_scores.items(), key=lambda item: item[1], reverse=True) if score > 0][:12]
        glossary_terms = [name for name, score in sorted(glossary_scores.items(), key=lambda item: item[1], reverse=True) if score > 0][:8]
        query_patterns = [name for name, score in sorted(pattern_scores.items(), key=lambda item: item[1], reverse=True) if score > 0][:6]

        safe_joins = []
        matched_entities = []
        provisional_items = []
        blocked_items = []
        for table in semantic.tables:
            if table.decision_status in {DecisionStatus.warning_ack_required, DecisionStatus.publish_blocked}:
                label = f"{table.table_name} ({table.decision_status.value})"
                if table.decision_status == DecisionStatus.publish_blocked:
                    blocked_items.append(label)
                else:
                    provisional_items.append(label)
            if table.table_name in matched_tables:
                if table.decision_status not in {DecisionStatus.warning_ack_required, DecisionStatus.publish_blocked}:
                    safe_joins.extend(table.valid_joins[:4])
                if table.likely_entity:
                    matched_entities.append(table.likely_entity)

        return LLMContextPackage(
            question=question,
            domain=semantic.domain,
            review_mode=semantic.review_mode.value,
            matched_entities=matched_entities[:8],
            matched_tables=matched_tables,
            matched_columns=matched_columns,
            glossary_terms=glossary_terms,
            safe_joins=safe_joins[:10],
            query_patterns=query_patterns,
            provisional_items=provisional_items[:12],
            blocked_items=blocked_items[:12],
            notes_for_llm=[
                "Prefer approved joins from the context package over inferred joins.",
                "Avoid exposing sensitive columns unless explicitly approved.",
                "Ask for clarification if the question references ambiguous status codes or entities.",
                "Do not rely on publish-blocked or acknowledgement-required items as final truth.",
            ],
        )

    def _expanded_tokens(self, value: str) -> set[str]:
        tokens = set(tokenize(value))
        expanded = set(tokens)
        for token in tokens:
            if token.endswith("s") and len(token) > 3:
                expanded.add(token[:-1])
            else:
                expanded.add(f"{token}s")
        return expanded
