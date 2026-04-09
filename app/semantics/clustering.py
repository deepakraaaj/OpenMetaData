from __future__ import annotations

from collections import Counter, defaultdict, deque
from dataclasses import dataclass

from app.models.review import TableRole
from app.models.semantic import DomainCluster, SemanticSourceModel, SemanticTable
from app.semantics.classification import TableClassification, build_relationship_graph
from app.semantics.confidence import clamp_score, named_confidence
from app.semantics.ml_assist import NoOpSchemaMLAssist, SchemaMLAssist
from app.utils.text import snake_to_words, tokenize, unique_non_empty

_ROLE_GENERIC_TOKENS = {
    "data",
    "record",
    "records",
    "info",
    "detail",
    "details",
    "table",
    "main",
    "mapping",
    "log",
    "history",
    "config",
    "system",
}
_DOMAIN_LABEL_HINTS = {
    "access": "Users & Access",
    "alert": "Alerts & Monitoring",
    "billing": "Billing / Commercial",
    "company": "Billing / Commercial",
    "commercial": "Billing / Commercial",
    "customer": "Billing / Commercial",
    "dispatch": "Trip Operations",
    "driver": "Users & Access",
    "fleet": "Vehicle Management",
    "geo": "Telemetry",
    "geofence": "Telemetry",
    "gps": "Telemetry",
    "location": "Trip Operations",
    "payment": "Billing / Commercial",
    "permission": "Users & Access",
    "role": "Users & Access",
    "telemetry": "Telemetry",
    "trip": "Trip Operations",
    "user": "Users & Access",
    "vehicle": "Vehicle Management",
}
_SYSTEM_DOMAIN = "Configuration / Internal"


@dataclass(frozen=True)
class DomainClusterResult:
    cluster_name: str
    member_tables: list[str]
    anchor_tables: list[str]
    inferred_business_meaning: str
    confidence_score: float
    confidence_reasons: list[str]
    requires_review: bool
    review_reason: str | None
    evidence: list[str]

    def to_model(self) -> DomainCluster:
        return DomainCluster(
            cluster_name=self.cluster_name,
            member_tables=list(self.member_tables),
            anchor_tables=list(self.anchor_tables),
            inferred_business_meaning=self.inferred_business_meaning,
            confidence=named_confidence(self.confidence_score, self.confidence_reasons),
            requires_review=self.requires_review,
            review_reason=self.review_reason,
            evidence=list(self.evidence),
        )


class BusinessDomainClusterer:
    def __init__(self, ml_assist: SchemaMLAssist | None = None) -> None:
        self.ml_assist = ml_assist or NoOpSchemaMLAssist()

    def cluster(
        self,
        *,
        normalized,
        technical,
        semantic: SemanticSourceModel,
        classifications: dict[str, TableClassification],
        groups: dict[str, list[str]] | None = None,
    ) -> list[DomainClusterResult]:
        adjacency, _inbound, _outbound = build_relationship_graph(normalized, technical)
        if groups:
            return self._clusters_from_groups(groups, semantic.tables, classifications, adjacency)
        return self._connected_component_clusters(semantic.tables, classifications, adjacency)

    def groups_from_clusters(self, clusters: list[DomainClusterResult]) -> dict[str, list[str]]:
        return {
            cluster.cluster_name: list(cluster.member_tables)
            for cluster in clusters
            if cluster.member_tables
        }

    def _clusters_from_groups(
        self,
        groups: dict[str, list[str]],
        semantic_tables: list[SemanticTable],
        classifications: dict[str, TableClassification],
        adjacency: dict[str, set[str]],
    ) -> list[DomainClusterResult]:
        semantic_map = {table.table_name: table for table in semantic_tables}
        clusters: list[DomainClusterResult] = []
        for label, members in groups.items():
            ordered_members = [table_name for table_name in members if table_name in semantic_map]
            if not ordered_members:
                continue
            clusters.append(self._build_cluster(label, ordered_members, semantic_map, classifications, adjacency))
        return sorted(clusters, key=lambda item: (-len(item.member_tables), item.cluster_name.lower()))

    def _connected_component_clusters(
        self,
        semantic_tables: list[SemanticTable],
        classifications: dict[str, TableClassification],
        adjacency: dict[str, set[str]],
    ) -> list[DomainClusterResult]:
        semantic_map = {table.table_name: table for table in semantic_tables}
        remaining = sorted(semantic_map.keys())
        visited: set[str] = set()
        clusters: list[DomainClusterResult] = []

        for table_name in remaining:
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
            label = self._component_label(component, semantic_map, classifications, adjacency)
            clusters.append(self._build_cluster(label, sorted(component), semantic_map, classifications, adjacency))

        return sorted(clusters, key=lambda item: (-len(item.member_tables), item.cluster_name.lower()))

    def _component_label(
        self,
        component: list[str],
        semantic_tables: dict[str, SemanticTable],
        classifications: dict[str, TableClassification],
        adjacency: dict[str, set[str]],
    ) -> str:
        technical_count = sum(
            1
            for table_name in component
            if classifications.get(table_name)
            and classifications[table_name].role in {TableRole.log_event, TableRole.history_audit, TableRole.config_system}
        )
        if technical_count and technical_count >= max(1, int(len(component) * 0.6)):
            return _SYSTEM_DOMAIN

        token_scores: Counter[str] = Counter()
        for table_name in component:
            semantic_table = semantic_tables.get(table_name)
            for token in tokenize(table_name):
                if token and token not in _ROLE_GENERIC_TOKENS:
                    token_scores[token] += 1
            likely_entity = str(getattr(semantic_table, "likely_entity", "") or "").strip().lower()
            for token in tokenize(likely_entity):
                if token and token not in _ROLE_GENERIC_TOKENS:
                    token_scores[token] += 2

        for token, _count in token_scores.most_common(5):
            mapped = _DOMAIN_LABEL_HINTS.get(token)
            if mapped:
                return mapped

        anchors = self._anchor_tables(component, classifications, adjacency)
        if anchors:
            anchor_label = str(getattr(semantic_tables.get(anchors[0]), "likely_entity", "") or "").strip()
            if anchor_label:
                return f"{anchor_label} Operations"
            return f"{snake_to_words(anchors[0]).title()} Domain"
        return "Other"

    def _build_cluster(
        self,
        label: str,
        member_tables: list[str],
        semantic_tables: dict[str, SemanticTable],
        classifications: dict[str, TableClassification],
        adjacency: dict[str, set[str]],
    ) -> DomainClusterResult:
        normalized_label = self._normalized_label(label, member_tables, classifications)
        anchors = self._anchor_tables(member_tables, classifications, adjacency)
        member_set = set(member_tables)
        internal_edges = 0
        total_edges = 0
        role_mix: Counter[TableRole] = Counter()
        for table_name in member_tables:
            neighbors = adjacency.get(table_name, set())
            total_edges += len(neighbors)
            internal_edges += sum(1 for neighbor in neighbors if neighbor in member_set)
            classification = classifications.get(table_name)
            if classification is not None:
                role_mix[classification.role] += 1
        cohesion = internal_edges / max(total_edges, 1)
        avg_table_confidence = sum(
            classifications.get(table_name).confidence_score
            for table_name in member_tables
            if classifications.get(table_name) is not None
        ) / max(sum(1 for table_name in member_tables if classifications.get(table_name) is not None), 1)
        naming_consistency = self._naming_consistency(member_tables)
        score = clamp_score(0.38 + avg_table_confidence * 0.34 + cohesion * 0.18 + naming_consistency * 0.12)

        ml_suggestion = self.ml_assist.suggest_cluster(
            member_tables=member_tables,
            features={
                "label": normalized_label,
                "anchors": anchors,
                "cohesion": cohesion,
                "role_mix": {role.value: count for role, count in role_mix.items()},
            },
        )
        ml_reasons: list[str] = []
        if ml_suggestion and ml_suggestion.cluster_name:
            ml_conf = clamp_score(ml_suggestion.confidence or 0.0)
            if ml_conf >= 0.82 and score < 0.7:
                normalized_label = str(ml_suggestion.cluster_name).strip() or normalized_label
                score = clamp_score(max(score, ml_conf * 0.9))
                ml_reasons.append("local ML assist adjusted the cluster label")

        requires_review = score < 0.72 or normalized_label in {"Other", _SYSTEM_DOMAIN} or len(role_mix) >= 4
        review_reason = None
        if requires_review:
            if normalized_label == _SYSTEM_DOMAIN:
                review_reason = "Most tables in this cluster look technical or internal. Confirm the exclusion scope."
            elif len(role_mix) >= 4:
                review_reason = "This cluster mixes several table roles. Confirm the business grouping before using it downstream."
            else:
                review_reason = "Cluster label confidence is moderate. Confirm the domain grouping before relying on it."

        evidence = unique_non_empty(
            [
                f"anchors: {', '.join(anchors[:3])}" if anchors else "",
                f"internal connectivity={cohesion:.2f}",
                f"role mix: {', '.join(f'{role.value}={count}' for role, count in role_mix.most_common(3))}" if role_mix else "",
                f"member count={len(member_tables)}",
            ]
            + ml_reasons
        )
        confidence_reasons = unique_non_empty(
            [
                f"{len(member_tables)} table(s) clustered together",
                f"internal connectivity={cohesion:.2f}",
                f"naming consistency={naming_consistency:.2f}",
            ]
            + ml_reasons
        )
        return DomainClusterResult(
            cluster_name=normalized_label,
            member_tables=member_tables,
            anchor_tables=anchors,
            inferred_business_meaning=self._cluster_meaning(normalized_label, anchors, role_mix),
            confidence_score=score,
            confidence_reasons=confidence_reasons,
            requires_review=requires_review,
            review_reason=review_reason,
            evidence=evidence,
        )

    def _anchor_tables(
        self,
        member_tables: list[str],
        classifications: dict[str, TableClassification],
        adjacency: dict[str, set[str]],
    ) -> list[str]:
        return [
            name
            for name in sorted(
                member_tables,
                key=lambda table_name: (
                    -self._anchor_score(table_name, classifications, adjacency),
                    table_name,
                ),
            )[:3]
        ]

    def _anchor_score(
        self,
        table_name: str,
        classifications: dict[str, TableClassification],
        adjacency: dict[str, set[str]],
    ) -> float:
        classification = classifications.get(table_name)
        if classification is None:
            return 0.0
        role_weight = 0.35 if classification.role in {TableRole.core_entity, TableRole.transaction} else 0.2
        return (
            role_weight
            + classification.impact_score * 0.35
            + classification.business_relevance * 0.2
            + min(len(adjacency.get(table_name, set())) * 0.05, 0.15)
        )

    def _cluster_meaning(
        self,
        cluster_name: str,
        anchor_tables: list[str],
        role_mix: Counter[TableRole],
    ) -> str:
        if cluster_name == _SYSTEM_DOMAIN:
            return "Configuration, logs, audit trails, or internal support tables."
        if anchor_tables:
            anchor_text = ", ".join(anchor_tables[:3])
            return f"Business area centered on {anchor_text}."
        if role_mix:
            dominant_role = role_mix.most_common(1)[0][0].value.replace("_", " ")
            return f"Cluster of {dominant_role} tables that likely belong to the same business domain."
        return "Related business tables inferred from schema structure."

    def _naming_consistency(self, member_tables: list[str]) -> float:
        token_scores: Counter[str] = Counter()
        for table_name in member_tables:
            for token in tokenize(table_name):
                if token and token not in _ROLE_GENERIC_TOKENS:
                    token_scores[token] += 1
        if not token_scores:
            return 0.25
        dominant = token_scores.most_common(1)[0][1]
        return clamp_score(0.22 + dominant / max(len(member_tables), 1) * 0.58)

    def _normalized_label(
        self,
        label: str,
        member_tables: list[str],
        classifications: dict[str, TableClassification],
    ) -> str:
        text = " ".join(str(label or "").replace("_", " ").split()).strip()
        lowered = text.lower()
        if not text:
            return _SYSTEM_DOMAIN if self._mostly_technical(member_tables, classifications) else "Other"
        if lowered in {"misc", "miscellaneous", "technical", "system", "internal", "other"}:
            return _SYSTEM_DOMAIN if self._mostly_technical(member_tables, classifications) else "Other"
        return text

    def _mostly_technical(
        self,
        member_tables: list[str],
        classifications: dict[str, TableClassification],
    ) -> bool:
        technical_roles = {TableRole.log_event, TableRole.history_audit, TableRole.config_system}
        technical_count = sum(
            1
            for table_name in member_tables
            if classifications.get(table_name) and classifications[table_name].role in technical_roles
        )
        return technical_count >= max(1, int(len(member_tables) * 0.6))
