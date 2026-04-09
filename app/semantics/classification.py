from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass

from app.models.normalized import NormalizedSource, NormalizedTable
from app.models.review import TableReviewDecision, TableRole
from app.models.semantic import SemanticSourceModel, SemanticTable
from app.models.technical import SourceTechnicalMetadata, TableProfile
from app.semantics.confidence import clamp_score, named_confidence
from app.semantics.ml_assist import NoOpSchemaMLAssist, SchemaMLAssist
from app.utils.text import tokenize, unique_non_empty

_GENERIC_TOKENS = {
    "data",
    "record",
    "records",
    "info",
    "detail",
    "details",
    "table",
    "main",
}
_MAPPING_TOKENS = {
    "association",
    "assoc",
    "bridge",
    "junction",
    "link",
    "map",
    "mapping",
    "relation",
    "xref",
}
_HISTORY_TOKENS = {
    "archive",
    "audit",
    "history",
    "ledger",
    "revision",
    "snapshot",
    "trail",
    "version",
}
_LOG_TOKENS = {
    "activity",
    "event",
    "heartbeat",
    "log",
    "message",
    "metric",
    "notification",
    "queue",
    "trace",
}
_CONFIG_TOKENS = {
    "admin",
    "api",
    "cache",
    "cfg",
    "config",
    "configuration",
    "cron",
    "feature",
    "flag",
    "internal",
    "job",
    "lock",
    "menu",
    "migration",
    "parameter",
    "permission",
    "preference",
    "role",
    "scheduler",
    "secret",
    "setting",
    "system",
    "template",
    "token",
}
_LOOKUP_TOKENS = {
    "catalog",
    "category",
    "code",
    "dictionary",
    "dimension",
    "directory",
    "lookup",
    "master",
    "reference",
    "ref",
    "status",
    "type",
}
_TRANSACTION_TOKENS = {
    "assignment",
    "billing",
    "booking",
    "charge",
    "collection",
    "delivery",
    "dispatch",
    "invoice",
    "journey",
    "movement",
    "operation",
    "order",
    "payment",
    "request",
    "ride",
    "schedule",
    "shipment",
    "task",
    "ticket",
    "transaction",
    "trip",
    "visit",
    "work",
}
_AUDIT_COLUMN_TOKENS = ("created", "updated", "deleted", "modified", "approved", "authored")
_NAME_COLUMN_TOKENS = ("name", "title", "code", "number", "label")


@dataclass(frozen=True)
class TableSelectionPlan:
    recommended_selected: bool
    review_decision: TableReviewDecision
    requires_review: bool
    selection_reason: str
    review_reason: str | None = None


@dataclass(frozen=True)
class TableClassification:
    table_name: str
    role: TableRole
    confidence_score: float
    confidence_reasons: list[str]
    impact_score: float
    business_relevance: float
    naming_clarity: float
    graph_connectivity: float
    related_tables: list[str]
    classification_reason: str
    selection_plan: TableSelectionPlan


def build_relationship_graph(
    normalized: NormalizedSource,
    technical: SourceTechnicalMetadata | None,
) -> tuple[dict[str, set[str]], Counter[str], Counter[str]]:
    table_names = {table.table_name for table in normalized.tables}
    adjacency: dict[str, set[str]] = {table_name: set() for table_name in table_names}
    inbound_refs: Counter[str] = Counter()
    outbound_refs: Counter[str] = Counter()
    seen_edges: set[tuple[str, str]] = set()

    def add_edge(left_table: str, right_table: str) -> None:
        if (
            not left_table
            or not right_table
            or left_table == right_table
            or left_table not in table_names
            or right_table not in table_names
        ):
            return
        edge = (left_table, right_table)
        if edge in seen_edges:
            return
        seen_edges.add(edge)
        adjacency[left_table].add(right_table)
        adjacency[right_table].add(left_table)
        outbound_refs[left_table] += 1
        inbound_refs[right_table] += 1

    for table in normalized.tables:
        for join in table.join_candidates:
            try:
                left, right = str(join or "").split("=")
            except ValueError:
                continue
            add_edge(left.split(".")[0].strip(), right.split(".")[0].strip())

    if technical is not None:
        for schema in technical.schemas:
            for table in schema.tables:
                for foreign_key in table.foreign_keys:
                    add_edge(table.table_name, str(foreign_key.referred_table or "").strip())
                for candidate in table.candidate_joins:
                    add_edge(str(candidate.left_table or "").strip(), str(candidate.right_table or "").strip())

    return adjacency, inbound_refs, outbound_refs


class TableClassifier:
    def __init__(self, ml_assist: SchemaMLAssist | None = None) -> None:
        self.ml_assist = ml_assist or NoOpSchemaMLAssist()

    def classify_all(
        self,
        *,
        normalized: NormalizedSource,
        technical: SourceTechnicalMetadata | None,
        semantic: SemanticSourceModel,
    ) -> dict[str, TableClassification]:
        normalized_tables = {table.table_name: table for table in normalized.tables}
        technical_tables = self._technical_table_map(technical)
        adjacency, inbound_refs, outbound_refs = build_relationship_graph(normalized, technical)

        results: dict[str, TableClassification] = {}
        for semantic_table in semantic.tables:
            normalized_table = normalized_tables.get(semantic_table.table_name)
            if normalized_table is None:
                continue
            results[semantic_table.table_name] = self.classify_table(
                semantic_table=semantic_table,
                normalized_table=normalized_table,
                technical_table=technical_tables.get(semantic_table.table_name),
                adjacency=adjacency,
                inbound_refs=inbound_refs,
                outbound_refs=outbound_refs,
            )
        return results

    def classify_table(
        self,
        *,
        semantic_table: SemanticTable,
        normalized_table: NormalizedTable,
        technical_table: TableProfile | None,
        adjacency: dict[str, set[str]],
        inbound_refs: Counter[str],
        outbound_refs: Counter[str],
    ) -> TableClassification:
        table_name = normalized_table.table_name
        lowered = table_name.lower()
        tokens = set(normalized_table.tokens or tokenize(table_name))
        degree = len(adjacency.get(table_name, set()))
        inbound = inbound_refs.get(table_name, 0)
        outbound = outbound_refs.get(table_name, 0)
        row_count = normalized_table.row_count or getattr(technical_table, "estimated_row_count", None) or 0
        fk_count = len(technical_table.foreign_keys) if technical_table is not None else len(normalized_table.foreign_keys)
        timestamp_count = len(technical_table.timestamp_columns) if technical_table is not None else sum(
            1 for column in normalized_table.columns if column.is_timestamp_like
        )
        status_count = len(technical_table.status_columns) if technical_table is not None else sum(
            1 for column in normalized_table.columns if column.is_status_like
        )
        non_key_columns = [
            column
            for column in normalized_table.columns
            if not column.is_primary_key and not column.is_foreign_key
        ]
        low_signal_non_keys = sum(
            1
            for column in non_key_columns
            if any(token in column.column_name.lower() for token in _AUDIT_COLUMN_TOKENS)
            or column.is_timestamp_like
        )
        meaningful_non_keys = max(len(non_key_columns) - low_signal_non_keys, 0)
        has_name_like_column = any(
            any(token in column.column_name.lower() for token in _NAME_COLUMN_TOKENS)
            for column in normalized_table.columns
        )

        scores: dict[TableRole, float] = {role: 0.05 for role in TableRole}
        reasons: dict[TableRole, list[str]] = defaultdict(list)

        def add(role: TableRole, score: float, reason: str) -> None:
            scores[role] += score
            reasons[role].append(reason)

        if tokens & _MAPPING_TOKENS or self._suffix_match(lowered, ("_map", "_mapping", "_bridge", "_xref")):
            add(TableRole.mapping_bridge, 0.62, "mapping/bridge naming pattern")
        if fk_count >= 2:
            add(TableRole.mapping_bridge, 0.18, "multiple foreign keys")
        if fk_count >= 2 and meaningful_non_keys <= 2:
            add(TableRole.mapping_bridge, 0.18, "mostly key columns with little standalone payload")
        if degree >= 2:
            add(TableRole.mapping_bridge, 0.08, "connects multiple related tables")

        if tokens & _HISTORY_TOKENS or self._suffix_match(lowered, ("_history", "_audit", "_archive", "_snapshot")):
            add(TableRole.history_audit, 0.65, "history/audit naming pattern")
        if timestamp_count:
            add(TableRole.history_audit, 0.08, "contains timeline columns")
        if any(token in lowered for token in ("audit", "revision", "version", "snapshot")):
            add(TableRole.history_audit, 0.12, "temporal/audit tokens in table name")

        if tokens & _LOG_TOKENS or self._suffix_match(lowered, ("_log", "_event", "_trace")):
            add(TableRole.log_event, 0.62, "log/event naming pattern")
        if timestamp_count:
            add(TableRole.log_event, 0.1, "timestamp-heavy structure")
        if row_count and row_count >= 10_000:
            add(TableRole.log_event, 0.08, "high row volume consistent with append-only events")

        if tokens & _CONFIG_TOKENS or self._suffix_match(lowered, ("_cfg", "_config", "_setting", "_settings")):
            add(TableRole.config_system, 0.65, "config/system naming pattern")
        if row_count and row_count <= 200:
            add(TableRole.config_system, 0.08, "small cardinality typical of settings tables")
        if outbound == 0 and inbound == 0:
            add(TableRole.config_system, 0.06, "isolated from core relationship graph")

        if tokens & _LOOKUP_TOKENS or self._suffix_match(lowered, ("_type", "_status", "_category", "_code")):
            add(TableRole.lookup_master, 0.52, "lookup/master naming pattern")
        if has_name_like_column:
            add(TableRole.lookup_master, 0.08, "contains label/code style columns")
        if inbound >= 2:
            add(TableRole.lookup_master, 0.16, "referenced by multiple tables")
        if row_count and row_count <= 500:
            add(TableRole.lookup_master, 0.08, "small table volume")
        if not timestamp_count:
            add(TableRole.lookup_master, 0.05, "few temporal signals")

        if tokens & _TRANSACTION_TOKENS:
            add(TableRole.transaction, 0.52, "transaction/workflow naming pattern")
        if row_count and row_count >= 1_000:
            add(TableRole.transaction, 0.12, "high row volume")
        if timestamp_count:
            add(TableRole.transaction, 0.1, "timeline columns suggest events or workflow steps")
        if status_count:
            add(TableRole.transaction, 0.08, "status columns suggest lifecycle tracking")
        if fk_count:
            add(TableRole.transaction, 0.08, "links to other business entities")
        if degree >= 2:
            add(TableRole.transaction, 0.06, "participates in a wider business graph")

        add(TableRole.core_entity, 0.24, "default entity candidate")
        if has_name_like_column:
            add(TableRole.core_entity, 0.12, "contains descriptive identity columns")
        if inbound >= 1:
            add(TableRole.core_entity, 0.14, "other tables depend on it")
        if degree >= 2:
            add(TableRole.core_entity, 0.12, "high relationship centrality")
        if row_count and 1 <= row_count <= 500_000:
            add(TableRole.core_entity, 0.04, "stable operational table volume")

        ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0].value))
        top_role, top_score = ranked[0]
        second_score = ranked[1][1] if len(ranked) > 1 else 0.0
        margin = max(top_score - second_score, 0.0)
        if top_score < 0.28 or margin < 0.04:
            top_role = TableRole.unknown
            reasons[top_role].append("weak or conflicting structural signals")

        naming_clarity = clamp_score(
            0.2
            + (0.22 if semantic_table.likely_entity else 0.0)
            + (0.12 if has_name_like_column else 0.0)
            + (0.18 if top_role in {TableRole.mapping_bridge, TableRole.history_audit, TableRole.log_event, TableRole.config_system, TableRole.lookup_master} else 0.0)
            + min(margin, 0.25) * 0.7
        )
        graph_connectivity = clamp_score(
            0.08
            + min(degree * 0.1, 0.42)
            + min(inbound * 0.07, 0.18)
            + min(outbound * 0.05, 0.14)
        )
        confidence_score = clamp_score(
            min(0.97, 0.28 + min(top_score, 1.15) * 0.4 + min(margin, 0.35) * 0.48 + naming_clarity * 0.12)
        )
        impact_score = clamp_score(
            0.1
            + min(degree * 0.08, 0.32)
            + min(inbound * 0.06, 0.18)
            + min(outbound * 0.04, 0.12)
            + (0.14 if row_count >= 10_000 else 0.09 if row_count >= 1_000 else 0.04 if row_count >= 100 else 0.0)
            + (0.08 if top_role in {TableRole.core_entity, TableRole.transaction} else 0.05 if top_role in {TableRole.lookup_master, TableRole.mapping_bridge} else 0.0)
        )
        business_relevance = clamp_score(
            0.16
            + (0.24 if top_role in {TableRole.core_entity, TableRole.transaction} else 0.12 if top_role in {TableRole.lookup_master, TableRole.mapping_bridge} else 0.03)
            + min(degree * 0.06, 0.24)
            + min(meaningful_non_keys * 0.04, 0.16)
            + (0.12 if getattr(semantic_table, "common_business_questions", []) else 0.0)
            - (0.14 if top_role in {TableRole.log_event, TableRole.history_audit, TableRole.config_system} else 0.0)
        )

        ml_suggestion = self.ml_assist.suggest_table(
            table_name=table_name,
            features={
                "role_scores": {role.value: round(score, 3) for role, score in ranked[:5]},
                "degree": degree,
                "inbound": inbound,
                "outbound": outbound,
                "row_count": row_count,
                "naming_clarity": naming_clarity,
            },
        )
        ml_reasons: list[str] = []
        if ml_suggestion and ml_suggestion.role is not None and ml_suggestion.role != top_role:
            ml_conf = clamp_score(ml_suggestion.role_confidence or 0.0)
            if ml_conf >= 0.82 and confidence_score < 0.6:
                top_role = ml_suggestion.role
                confidence_score = clamp_score(max(confidence_score, ml_conf * 0.92))
                ml_reasons.append(f"local ML assist preferred role '{ml_suggestion.role.value}'")
            elif ml_suggestion.role == top_role:
                confidence_score = clamp_score(max(confidence_score, ml_conf * 0.88))
                ml_reasons.append("local ML assist agreed with heuristic role")
        elif ml_suggestion and ml_suggestion.role == top_role:
            ml_conf = clamp_score(ml_suggestion.role_confidence or 0.0)
            confidence_score = clamp_score(max(confidence_score, ml_conf * 0.88))
            ml_reasons.append("local ML assist agreed with heuristic role")

        confidence_reasons = unique_non_empty(
            list(reasons[top_role][:4])
            + [f"relationship degree={degree}", f"inbound refs={inbound}"]
            + ml_reasons
        )
        classification_reason = self._reason_text(top_role, confidence_reasons)
        selection_plan = self._selection_plan(top_role, confidence_score, impact_score, business_relevance)
        return TableClassification(
            table_name=table_name,
            role=top_role,
            confidence_score=confidence_score,
            confidence_reasons=confidence_reasons,
            impact_score=impact_score,
            business_relevance=business_relevance,
            naming_clarity=naming_clarity,
            graph_connectivity=graph_connectivity,
            related_tables=sorted(adjacency.get(table_name, set())),
            classification_reason=classification_reason,
            selection_plan=selection_plan,
        )

    def _technical_table_map(
        self,
        technical: SourceTechnicalMetadata | None,
    ) -> dict[str, TableProfile]:
        table_map: dict[str, TableProfile] = {}
        if technical is None:
            return table_map
        for schema in technical.schemas:
            for table in schema.tables:
                table_map[table.table_name] = table
        return table_map

    def _selection_plan(
        self,
        role: TableRole,
        confidence_score: float,
        impact_score: float,
        business_relevance: float,
    ) -> TableSelectionPlan:
        if role in {TableRole.log_event, TableRole.history_audit, TableRole.config_system}:
            if impact_score >= 0.45 and confidence_score < 0.78:
                return TableSelectionPlan(
                    recommended_selected=False,
                    review_decision=TableReviewDecision.review,
                    requires_review=True,
                    selection_reason="Deprioritized by default because the table looks technical rather than user-facing.",
                    review_reason="Connected enough to core business tables that a human should confirm whether it belongs in scope.",
                )
            return TableSelectionPlan(
                recommended_selected=False,
                review_decision=TableReviewDecision.excluded,
                requires_review=False,
                selection_reason="Excluded by default because the table matches logs, audit/history, or system/config patterns.",
                review_reason=None,
            )

        if role == TableRole.lookup_master:
            if impact_score >= 0.68 and confidence_score >= 0.72:
                return TableSelectionPlan(
                    recommended_selected=True,
                    review_decision=TableReviewDecision.selected,
                    requires_review=False,
                    selection_reason="Included because lookup labels appear important for filters, labels, or joins.",
                    review_reason=None,
                )
            if impact_score >= 0.4 or business_relevance >= 0.45:
                return TableSelectionPlan(
                    recommended_selected=False,
                    review_decision=TableReviewDecision.review,
                    requires_review=True,
                    selection_reason="Not selected by default because this looks like optional reference data.",
                    review_reason="Review only if business labels, codes, or filters depend on it.",
                )
            if impact_score >= 0.25:
                return TableSelectionPlan(
                    recommended_selected=False,
                    review_decision=TableReviewDecision.review,
                    requires_review=True,
                    selection_reason="Not selected by default because this looks like optional reference data.",
                    review_reason="Review if labels, statuses, or reference codes might matter in the user experience.",
                )
            return TableSelectionPlan(
                recommended_selected=False,
                review_decision=TableReviewDecision.excluded,
                requires_review=False,
                selection_reason="Excluded until needed because this lookup/master table has low business impact.",
                review_reason=None,
            )

        if role == TableRole.mapping_bridge:
            if impact_score >= 0.65 and confidence_score >= 0.72:
                return TableSelectionPlan(
                    recommended_selected=True,
                    review_decision=TableReviewDecision.review,
                    requires_review=True,
                    selection_reason="Included by default because this bridge table may be required for multi-hop joins.",
                    review_reason="Confirm only if analysts need cross-entity joins or many-to-many relationship traversal.",
                )
            if impact_score >= 0.38 or business_relevance >= 0.45:
                return TableSelectionPlan(
                    recommended_selected=False,
                    review_decision=TableReviewDecision.review,
                    requires_review=True,
                    selection_reason="Not selected by default because bridge tables are only useful when specific joins matter.",
                    review_reason="Review if users need combined views across the related entities.",
                )
            return TableSelectionPlan(
                recommended_selected=False,
                review_decision=TableReviewDecision.excluded,
                requires_review=False,
                selection_reason="Excluded by default because this low-signal bridge table adds little standalone business value.",
                review_reason=None,
            )

        if role == TableRole.unknown:
            return TableSelectionPlan(
                recommended_selected=True,
                review_decision=TableReviewDecision.review,
                requires_review=True,
                selection_reason="Tentatively included because the table might matter, but the role is unclear.",
                review_reason="Low confidence classification. A human should confirm the table role before it drives review questions or retrieval.",
            )

        if confidence_score >= 0.8 and impact_score >= 0.42:
            return TableSelectionPlan(
                recommended_selected=True,
                review_decision=TableReviewDecision.selected,
                requires_review=False,
                selection_reason="Included because it looks like a core business table with strong supporting signals.",
                review_reason=None,
            )
        return TableSelectionPlan(
            recommended_selected=True,
            review_decision=TableReviewDecision.review,
            requires_review=True,
            selection_reason="Included by default because it appears business-relevant.",
            review_reason="The table looks important, but the role or scope still needs confirmation.",
        )

    def _reason_text(self, role: TableRole, reasons: list[str]) -> str:
        if not reasons:
            return f"Inferred role: {role.value.replace('_', ' ')}."
        return f"Inferred role: {role.value.replace('_', ' ')}. Signals: {'; '.join(reasons[:3])}."

    def _suffix_match(self, value: str, suffixes: tuple[str, ...]) -> bool:
        return any(value.endswith(suffix) for suffix in suffixes)

    def confidence(self, result: TableClassification):
        return named_confidence(result.confidence_score, result.confidence_reasons)
