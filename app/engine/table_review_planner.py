from __future__ import annotations

from collections import defaultdict

from app.models.common import NamedConfidence
from app.models.decision import DecisionActor, DecisionStatus, RiskLevel
from app.models.review import (
    DomainReviewGroup,
    ReviewQueueItem,
    TableRole,
    TableSelectionSummary,
)
from app.models.semantic import DomainCluster, SemanticSourceModel, SemanticTable, TableReviewStatus
from app.models.state import KnowledgeState
from app.models.technical import SourceTechnicalMetadata
from app.semantics.classification import TableClassification, TableClassifier
from app.semantics.clustering import BusinessDomainClusterer, DomainClusterResult
from app.semantics.confidence import clamp_score, named_confidence, weighted_confidence
from app.utils.text import unique_non_empty

_SYSTEM_DOMAIN = "Configuration / Internal"
_ANNOTATION_FIELDS = (
    "domain",
    "role",
    "selected",
    "selected_by_default",
    "recommended_selected",
    "review_decision",
    "needs_review",
    "requires_review",
    "reason_for_classification",
    "classification_reason",
    "selection_reason",
    "review_reason",
    "related_tables",
    "impact_score",
    "business_relevance",
    "naming_clarity",
    "graph_connectivity",
    "confidence",
)


class TableReviewPlanner:
    def __init__(
        self,
        classifier: TableClassifier | None = None,
        clusterer: BusinessDomainClusterer | None = None,
    ) -> None:
        self.classifier = classifier or TableClassifier()
        self.clusterer = clusterer or BusinessDomainClusterer()

    def annotate(
        self,
        *,
        normalized,
        technical: SourceTechnicalMetadata | None,
        semantic: SemanticSourceModel,
        state: KnowledgeState | None = None,
        domain_groups: dict[str, list[str]] | None = None,
    ) -> None:
        classifications = self.classifier.classify_all(
            normalized=normalized,
            technical=technical,
            semantic=semantic,
        )
        clusters = self.clusterer.cluster(
            normalized=normalized,
            technical=technical,
            semantic=semantic,
            classifications=classifications,
            groups=domain_groups,
        )
        semantic.domain_clusters = [cluster.to_model() for cluster in clusters]
        self._update_source_domain(semantic, clusters)

        cluster_by_table: dict[str, DomainClusterResult] = {}
        for cluster in clusters:
            for table_name in cluster.member_tables:
                cluster_by_table[table_name] = cluster

        for table in semantic.tables:
            classification = classifications.get(table.table_name)
            if classification is None:
                continue
            cluster = cluster_by_table.get(table.table_name)
            self._annotate_table(table=table, classification=classification, cluster=cluster)

        if state is None:
            return

        semantic_tables = {table.table_name: table for table in semantic.tables}
        for table_name, state_table in state.tables.items():
            semantic_table = semantic_tables.get(table_name)
            if semantic_table is None:
                continue
            self._copy_annotations(semantic_table, state_table)

        self.refresh_state_view(state)

    def refresh_state_view(self, state: KnowledgeState) -> None:
        tables = sorted(state.tables.values(), key=lambda table: table.table_name)
        gaps_by_table: dict[str, int] = defaultdict(int)
        for gap in state.unresolved_gaps:
            table_name = str(gap.target_entity or "").strip()
            if table_name:
                gaps_by_table[table_name] += 1

        existing_groups = {group.domain: group for group in state.domain_groups}
        detected_domains = unique_non_empty(
            [table.domain or _SYSTEM_DOMAIN for table in tables if str(table.domain or "").strip()]
        )
        state.review_summary = TableSelectionSummary(
            analyzed_table_count=len(tables),
            selected_count=sum(1 for table in tables if table.selected),
            excluded_count=sum(1 for table in tables if not table.selected),
            review_count=sum(
                1
                for table in tables
                if table.review_status == TableReviewStatus.pending
                and (table.requires_review or gaps_by_table.get(table.table_name, 0) > 0)
            ),
            high_confidence_count=sum(1 for table in tables if table.confidence.label == "high"),
            medium_confidence_count=sum(1 for table in tables if table.confidence.label == "medium"),
            low_confidence_count=sum(1 for table in tables if table.confidence.label == "low"),
            detected_domains=detected_domains,
            auto_accepted_count=sum(1 for table in tables if table.decision_status == DecisionStatus.auto_accepted),
            user_confirmed_count=sum(1 for table in tables if table.decision_status == DecisionStatus.user_confirmed),
            user_overridden_count=sum(1 for table in tables if table.decision_status == DecisionStatus.user_overridden),
            deferred_review_count=sum(1 for table in tables if table.decision_status == DecisionStatus.deferred_review),
            publish_blocked_count=sum(1 for table in tables if table.decision_status == DecisionStatus.publish_blocked),
            warning_ack_required_count=sum(1 for table in tables if table.decision_status == DecisionStatus.warning_ack_required),
            review_debt_count=len(state.review_debt),
        )
        state.domain_groups = self._state_domain_groups(tables, existing_groups)
        state.review_queue = self._state_review_queue(tables, gaps_by_table)

    def groups_from_semantic(self, semantic: SemanticSourceModel) -> dict[str, list[str]]:
        if semantic.domain_clusters:
            return self.clusterer.groups_from_clusters(
                [
                    DomainClusterResult(
                        cluster_name=cluster.cluster_name,
                        member_tables=list(cluster.member_tables),
                        anchor_tables=list(cluster.anchor_tables),
                        inferred_business_meaning=str(cluster.inferred_business_meaning or "").strip(),
                        confidence_score=cluster.confidence.score,
                        confidence_reasons=list(cluster.confidence.rationale),
                        requires_review=cluster.requires_review,
                        review_reason=cluster.review_reason,
                        evidence=list(cluster.evidence),
                    )
                    for cluster in semantic.domain_clusters
                ]
            )

        grouped: dict[str, list[str]] = defaultdict(list)
        for table in semantic.tables:
            grouped[table.domain or _SYSTEM_DOMAIN].append(table.table_name)
        return {label: sorted(set(members)) for label, members in grouped.items() if members}

    def _annotate_table(
        self,
        *,
        table: SemanticTable,
        classification: TableClassification,
        cluster: DomainClusterResult | None,
    ) -> None:
        domain = cluster.cluster_name if cluster is not None else (table.domain or _SYSTEM_DOMAIN)
        cluster_confidence = (
            named_confidence(cluster.confidence_score, cluster.confidence_reasons)
            if cluster is not None
            else named_confidence(0.52, [f"defaulted to {domain}"])
        )
        combined_rationale = unique_non_empty(
            [
                classification.classification_reason,
                classification.selection_plan.selection_reason,
                f"cluster: {cluster.inferred_business_meaning}" if cluster and cluster.inferred_business_meaning else "",
                f"related to {', '.join(classification.related_tables[:3])}" if classification.related_tables else "",
            ]
        )

        table.domain = domain
        table.role = classification.role
        table.selected_by_default = classification.selection_plan.recommended_selected
        table.recommended_selected = classification.selection_plan.recommended_selected
        table.review_decision = classification.selection_plan.review_decision
        table.requires_review = classification.selection_plan.requires_review or bool(cluster and cluster.requires_review)
        table.classification_reason = classification.classification_reason
        table.selection_reason = classification.selection_plan.selection_reason
        table.review_reason = classification.selection_plan.review_reason or (cluster.review_reason if cluster else None)
        table.reason_for_classification = self._table_summary_reason(table, classification, cluster)
        table.related_tables = list(classification.related_tables[:12])
        table.impact_score = classification.impact_score
        table.business_relevance = classification.business_relevance
        table.naming_clarity = classification.naming_clarity
        table.graph_connectivity = classification.graph_connectivity
        table.confidence = weighted_confidence(
            [
                (0.3, table.confidence.score),
                (0.45, classification.confidence_score),
                (0.25, cluster_confidence.score),
            ],
            list(table.confidence.rationale[:2]) + combined_rationale + list(cluster_confidence.rationale[:2]),
        )

        if table.review_status == TableReviewStatus.confirmed:
            table.selected = True
            table.needs_review = False
            return
        if table.review_status == TableReviewStatus.skipped:
            table.selected = False
            table.needs_review = False
            return

        table.selected = classification.selection_plan.recommended_selected
        table.needs_review = table.requires_review

    def _copy_annotations(self, source: SemanticTable, target: SemanticTable) -> None:
        for field_name in _ANNOTATION_FIELDS:
            setattr(target, field_name, getattr(source, field_name))

    def _update_source_domain(
        self,
        semantic: SemanticSourceModel,
        clusters: list[DomainClusterResult],
    ) -> None:
        if semantic.domain:
            return
        ranked = [
            cluster
            for cluster in clusters
            if cluster.cluster_name != _SYSTEM_DOMAIN
        ]
        if not ranked:
            return
        ranked.sort(
            key=lambda item: (
                -len(item.member_tables),
                -item.confidence_score,
                item.cluster_name.lower(),
            )
        )
        semantic.domain = ranked[0].cluster_name

    def _table_summary_reason(
        self,
        table: SemanticTable,
        classification: TableClassification,
        cluster: DomainClusterResult | None,
    ) -> str:
        parts = [
            classification.selection_plan.selection_reason,
            classification.classification_reason,
            f"domain={cluster.cluster_name}" if cluster else f"domain={table.domain or _SYSTEM_DOMAIN}",
            f"anchors={', '.join(cluster.anchor_tables[:2])}" if cluster and cluster.anchor_tables else "",
        ]
        if classification.related_tables:
            parts.append(f"related to {', '.join(classification.related_tables[:3])}")
        return ". ".join(unique_non_empty(parts))

    def _state_domain_groups(
        self,
        tables: list[SemanticTable],
        existing_groups: dict[str, DomainReviewGroup],
    ) -> list[DomainReviewGroup]:
        grouped: dict[str, list[SemanticTable]] = defaultdict(list)
        for table in tables:
            grouped[table.domain or _SYSTEM_DOMAIN].append(table)

        results: list[DomainReviewGroup] = []
        for domain, members in grouped.items():
            existing = existing_groups.get(domain)
            ordered = sorted(
                members,
                key=lambda table: (
                    not table.selected,
                    table.review_status != TableReviewStatus.pending,
                    table.table_name,
                ),
            )
            domain_confidence = weighted_confidence(
                [
                    (
                        0.7,
                        sum(table.confidence.score for table in ordered) / max(len(ordered), 1),
                    ),
                    (0.3, existing.confidence.score if existing is not None else 0.0),
                ],
                list(existing.confidence.rationale[:2]) if existing is not None else [f"{len(ordered)} table(s) in this domain"],
            )
            anchor_tables = list(existing.anchor_tables) if existing and existing.anchor_tables else self._domain_anchors(ordered)
            review_reason = (
                existing.review_reason
                if existing and existing.review_reason
                else next((table.review_reason for table in ordered if table.review_reason), None)
            )
            requires_review = bool(existing and existing.requires_review) or any(table.requires_review for table in ordered)
            results.append(
                DomainReviewGroup(
                    domain=domain,
                    tables=[table.table_name for table in ordered],
                    core_tables=[
                        table.table_name
                        for table in ordered
                        if table.role in {TableRole.core_entity, TableRole.transaction} and table.selected
                    ][:3],
                    anchor_tables=anchor_tables,
                    selected_count=sum(1 for table in ordered if table.selected),
                    excluded_count=sum(1 for table in ordered if not table.selected),
                    review_count=sum(
                        1
                        for table in ordered
                        if table.review_status == TableReviewStatus.pending and table.requires_review
                    ),
                    inferred_business_meaning=(
                        existing.inferred_business_meaning
                        if existing and existing.inferred_business_meaning
                        else self._domain_meaning(domain, anchor_tables, ordered)
                    ),
                    requires_review=requires_review,
                    review_reason=review_reason,
                    confidence=domain_confidence,
                    review_debt_count=sum(1 for table in ordered if table.review_debt),
                    publish_blocker_count=sum(1 for table in ordered if table.publish_blocker),
                    warning_ack_required_count=sum(1 for table in ordered if table.needs_acknowledgement),
                )
            )
        return sorted(
            results,
            key=lambda item: (-item.selected_count, -len(item.tables), item.domain.lower()),
        )

    def _state_review_queue(
        self,
        tables: list[SemanticTable],
        gaps_by_table: dict[str, int],
    ) -> list[ReviewQueueItem]:
        queued: list[tuple[float, ReviewQueueItem]] = []
        for table in tables:
            if table.review_status != TableReviewStatus.pending:
                continue
            open_gap_count = gaps_by_table.get(table.table_name, 0)
            if not table.requires_review and open_gap_count <= 0:
                continue
            ambiguity = clamp_score(
                max(
                    0.18,
                    1.0 - table.confidence.score + (0.12 if table.role == TableRole.unknown else 0.0),
                )
            )
            priority = round(
                max(
                    table.impact_score * ambiguity * max(table.business_relevance, 0.22),
                    (0.08 * open_gap_count) + (0.05 if table.selected else 0.0),
                ),
                4,
            )
            queued.append(
                (
                    priority,
                    ReviewQueueItem(
                        table_name=table.table_name,
                        domain=table.domain,
                        role=table.role,
                        confidence=table.confidence,
                        selected=table.selected,
                        open_gap_count=open_gap_count,
                        reason_for_classification=table.reason_for_classification,
                        selection_reason=table.selection_reason,
                        review_reason=table.review_reason,
                        impact_score=table.impact_score,
                        business_relevance=table.business_relevance,
                        related_tables=list(table.related_tables[:8]),
                        decision_status=table.decision_status or DecisionStatus.deferred_review,
                        decision_actor=table.decision_actor or DecisionActor.rule_default,
                        risk_level=table.risk_level or RiskLevel.medium,
                        policy_reason=table.policy_reason,
                        review_debt=table.review_debt,
                        publish_blocker=table.publish_blocker,
                        needs_acknowledgement=table.needs_acknowledgement,
                    ),
                )
            )
        return [
            item
            for _priority, item in sorted(
                queued,
                key=lambda entry: (
                    -entry[0],
                    entry[1].table_name.lower(),
                ),
            )
        ]

    def _domain_anchors(self, members: list[SemanticTable]) -> list[str]:
        ranked = sorted(
            members,
            key=lambda table: (
                -(table.impact_score * 0.45 + table.business_relevance * 0.35 + table.confidence.score * 0.2),
                table.table_name,
            ),
        )
        return [table.table_name for table in ranked[:3]]

    def _domain_meaning(
        self,
        domain: str,
        anchor_tables: list[str],
        members: list[SemanticTable],
    ) -> str:
        if domain == _SYSTEM_DOMAIN:
            return "Configuration, logs, audit trails, or internal support tables."
        if anchor_tables:
            return f"Business area centered on {', '.join(anchor_tables[:3])}."
        dominant_role = sorted(
            (table.role for table in members),
            key=lambda role: (
                -sum(1 for item in members if item.role == role),
                role.value,
            ),
        )
        if dominant_role:
            return f"Cluster of {dominant_role[0].value.replace('_', ' ')} tables."
        return "Related business tables inferred from schema structure."
