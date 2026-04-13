from __future__ import annotations

import fnmatch
import re
from collections import defaultdict
from dataclasses import dataclass, field

from app.discovery.service import build_source_name, parse_connection_url
from app.models.common import DatabaseType
from app.models.simple_onboarding import (
    SimpleOnboardingArtifact,
    SimpleOnboardingRelationship,
    SimpleOnboardingRequest,
    SimpleOnboardingResponse,
    SimpleOnboardingTable,
)
from app.models.source import DiscoveredSource
from app.models.technical import SourceTechnicalMetadata, TableProfile
from app.onboard.introspection import DatabaseIntrospector
from app.repositories.filesystem import WorkspaceRepository
from app.services.database import redacted_url
from app.utils.serialization import write_json
from app.utils.text import tokenize


def _dedupe_keep_order(values: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = str(value or "").strip()
        normalized = cleaned.lower()
        if not cleaned or normalized in seen:
            continue
        seen.add(normalized)
        output.append(cleaned)
    return output


def _humanize(identifier: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", " ", str(identifier or "")).strip().lower()
    return " ".join(part for part in text.split() if part)


def _tokens(*values: str) -> set[str]:
    tokens: set[str] = set()
    for value in values:
        tokens.update(tokenize(str(value or "")))
    return tokens


def _join_natural(items: list[str]) -> str:
    values = [str(item or "").strip() for item in items if str(item or "").strip()]
    if not values:
        return ""
    if len(values) == 1:
        return values[0]
    if len(values) == 2:
        return f"{values[0]} and {values[1]}"
    return f"{', '.join(values[:-1])}, and {values[-1]}"


@dataclass
class _SimpleTableProfile:
    schema_name: str
    table_name: str
    columns: list[str]
    foreign_keys: list[SimpleOnboardingRelationship] = field(default_factory=list)
    incoming_tables: list[str] = field(default_factory=list)

    @property
    def related_tables(self) -> list[str]:
        related = [relationship.to_table for relationship in self.foreign_keys]
        related.extend(self.incoming_tables)
        return sorted(_dedupe_keep_order(related))


class SimpleOnboardingService:
    _NOISE_TERMS = {
        "audit",
        "cache",
        "history",
        "jobrun",
        "log",
        "logs",
        "migration",
        "migrations",
        "schema",
        "session",
        "temp",
        "tmp",
        "token",
    }
    _BRIDGE_TERMS = {
        "association",
        "bridge",
        "junction",
        "link",
        "links",
        "mapping",
        "mappings",
        "relation",
        "relations",
        "xref",
    }
    _HOUSEKEEPING_COLUMNS = {
        "created_at",
        "updated_at",
        "deleted_at",
        "created_by",
        "updated_by",
        "tenant_id",
        "company_id",
        "organization_id",
        "organisation_id",
        "org_id",
        "is_active",
        "is_deleted",
        "version",
    }
    _DATE_TERMS = {"date", "datetime", "time", "timestamp", "scheduled", "due", "created", "updated", "occurred"}
    _STATUS_TERMS = {"state", "status", "priority", "severity", "stage", "phase", "condition", "outcome"}
    _CATEGORY_RULES = (
        (
            "Core Operations",
            {
                "case",
                "cases",
                "dispatch",
                "event",
                "events",
                "incident",
                "incidents",
                "job",
                "jobs",
                "order",
                "orders",
                "request",
                "requests",
                "schedule",
                "schedules",
                "service",
                "task",
                "tasks",
                "ticket",
                "tickets",
                "transaction",
                "transactions",
                "trip",
                "trips",
                "visit",
                "visits",
                "work",
            },
        ),
        (
            "People & Teams",
            {
                "assignee",
                "employee",
                "employees",
                "member",
                "members",
                "operator",
                "operators",
                "people",
                "person",
                "staff",
                "team",
                "teams",
                "technician",
                "technicians",
                "user",
                "users",
            },
        ),
        (
            "Locations & Facilities",
            {
                "address",
                "addresses",
                "branch",
                "branches",
                "building",
                "buildings",
                "facility",
                "facilities",
                "location",
                "locations",
                "region",
                "regions",
                "site",
                "sites",
                "warehouse",
                "warehouses",
                "zone",
                "zones",
            },
        ),
        (
            "Customers & Accounts",
            {
                "account",
                "accounts",
                "client",
                "clients",
                "company",
                "companies",
                "contact",
                "contacts",
                "customer",
                "customers",
                "partner",
                "partners",
                "supplier",
                "suppliers",
                "vendor",
                "vendors",
            },
        ),
        (
            "Assets & Inventory",
            {
                "asset",
                "assets",
                "catalog",
                "catalogs",
                "equipment",
                "inventory",
                "item",
                "items",
                "machine",
                "machines",
                "material",
                "materials",
                "part",
                "parts",
                "product",
                "products",
                "sku",
                "stock",
            },
        ),
        (
            "Finance & Billing",
            {
                "amount",
                "amounts",
                "bill",
                "billing",
                "budget",
                "budgets",
                "cost",
                "costs",
                "expense",
                "expenses",
                "finance",
                "financial",
                "invoice",
                "invoices",
                "payment",
                "payments",
                "price",
                "prices",
                "quote",
                "quotes",
                "revenue",
                "tax",
                "taxes",
            },
        ),
        (
            "Reference Data",
            {
                "category",
                "categories",
                "code",
                "codes",
                "dictionary",
                "enum",
                "label",
                "labels",
                "lookup",
                "master",
                "reference",
                "setting",
                "settings",
                "status",
                "statuses",
                "type",
                "types",
            },
        ),
    )

    def __init__(self, repository: WorkspaceRepository | None = None) -> None:
        self.repository = repository
        self.introspector = DatabaseIntrospector()

    def build(self, request: SimpleOnboardingRequest) -> SimpleOnboardingResponse:
        connection = parse_connection_url(request.db_url)
        if connection.type == DatabaseType.unknown:
            raise ValueError("Unsupported or invalid database URL.")

        if request.schema_name:
            connection.schema_name = request.schema_name

        source_name = build_source_name(connection, preferred_name=request.source_name or None)
        source = DiscoveredSource(
            name=source_name,
            connection=connection,
            description=request.description or f"Simple onboarding for {source_name}",
            approved_use_cases=["simple_onboarding"],
        )
        technical = self.introspector.introspect_source(source)
        if not technical.connectivity_ok:
            detail = technical.connectivity_notes[0] if technical.connectivity_notes else "Failed to read database schema."
            raise ValueError(detail)

        response = self.build_from_metadata(
            metadata=technical,
            request=request,
            source_name=source_name,
            database_target=redacted_url(connection) or source_name,
        )

        if self.repository is not None:
            self.repository.upsert_discovered_source(source)
            self.repository.save_technical_metadata(technical)
            if request.persist_artifact:
                artifact_path = self.repository.source_dir(source_name) / "simple_onboarding.json"
                write_json(artifact_path, response.artifact)
                response.artifact_path = artifact_path.as_posix()

        return response

    def build_from_metadata(
        self,
        *,
        metadata: SourceTechnicalMetadata,
        request: SimpleOnboardingRequest,
        source_name: str,
        database_target: str,
    ) -> SimpleOnboardingResponse:
        profiles = self._profiles(metadata)
        if not profiles:
            raise ValueError("No tables found in the target database.")

        categories: dict[str, str] = {}
        descriptions: dict[str, str] = {}
        scores: dict[str, int] = {}
        suggested_selection: dict[str, bool] = {}
        reasons: dict[str, str] = {}

        for profile in profiles:
            category = self._categorize(profile)
            description = self._describe(profile, category)
            score = self._business_score(profile, category)
            suggested = self._suggest_selection(profile, category, score, request.selection_mode)
            categories[profile.table_name] = category
            descriptions[profile.table_name] = description
            scores[profile.table_name] = score
            suggested_selection[profile.table_name] = suggested
            reasons[profile.table_name] = self._selection_reason(profile, category, suggested)

        selected_set = self._resolve_selected_tables(
            profiles=profiles,
            categories=categories,
            suggested_selection=suggested_selection,
            request=request,
        )
        selected_tables = sorted(selected_set)
        ignored_tables = sorted(profile.table_name for profile in profiles if profile.table_name not in selected_set)
        category_groups = self._group_tables([profile.table_name for profile in profiles], categories)
        selected_groups = self._group_tables(selected_tables, categories)
        relationships = self._selected_relationships(profiles, selected_set)

        tables = [
            SimpleOnboardingTable(
                name=profile.table_name,
                schema_name=profile.schema_name,
                category=categories[profile.table_name],
                description=descriptions[profile.table_name],
                selected=profile.table_name in selected_set,
                suggested_action="select" if suggested_selection[profile.table_name] else "ignore",
                selection_reason=reasons[profile.table_name],
                business_score=scores[profile.table_name],
                columns=profile.columns,
                related_tables=profile.related_tables,
            )
            for profile in sorted(profiles, key=lambda item: (item.schema_name, item.table_name))
        ]

        artifact = SimpleOnboardingArtifact(
            categories=selected_groups,
            selected_tables=selected_tables,
            table_descriptions={table_name: descriptions[table_name] for table_name in selected_tables},
            relationships=relationships,
            business_context=str(request.business_context or "").strip(),
            metrics=[],
        )

        return SimpleOnboardingResponse(
            source_name=source_name,
            database_target=database_target,
            total_tables=len(profiles),
            selection_mode=request.selection_mode,
            categories=category_groups,
            selected_tables=selected_tables,
            ignored_tables=ignored_tables,
            tables=tables,
            artifact=artifact,
        )

    def _profiles(self, metadata: SourceTechnicalMetadata) -> list[_SimpleTableProfile]:
        profiles: list[_SimpleTableProfile] = []
        by_name: dict[str, _SimpleTableProfile] = {}

        for schema in metadata.schemas:
            for table in schema.tables:
                relationships = [
                    SimpleOnboardingRelationship(
                        from_table=table.table_name,
                        from_columns=list(foreign_key.constrained_columns),
                        to_table=foreign_key.referred_table,
                        to_columns=list(foreign_key.referred_columns),
                    )
                    for foreign_key in table.foreign_keys
                    if foreign_key.referred_table
                ]
                profile = _SimpleTableProfile(
                    schema_name=table.schema_name,
                    table_name=table.table_name,
                    columns=[column.name for column in table.columns],
                    foreign_keys=relationships,
                )
                profiles.append(profile)
                by_name[profile.table_name] = profile

        for profile in profiles:
            for relationship in profile.foreign_keys:
                target = by_name.get(relationship.to_table)
                if target is None:
                    continue
                target.incoming_tables.append(profile.table_name)

        for profile in profiles:
            profile.incoming_tables = sorted(_dedupe_keep_order(profile.incoming_tables))

        return profiles

    def _categorize(self, profile: _SimpleTableProfile) -> str:
        if self._is_noise(profile):
            return "System Records"
        if self._is_bridge(profile):
            return "Reference Data"

        table_tokens = _tokens(profile.table_name)
        column_tokens = _tokens(*profile.columns)
        best_category = ""
        best_score = -1

        for category, keywords in self._CATEGORY_RULES:
            score = (len(table_tokens & keywords) * 4) + len(column_tokens & keywords)
            if category == "Reference Data" and self._is_lookup(profile):
                score += 3
            if score > best_score:
                best_score = score
                best_category = category

        if best_score > 0:
            return best_category
        if self._is_lookup(profile):
            return "Reference Data"
        return "Core Operations"

    def _describe(self, profile: _SimpleTableProfile, category: str) -> str:
        label = _humanize(profile.table_name)
        business_columns = [_humanize(column) for column in self._business_columns(profile)[:3]]
        related_tables = [_humanize(table_name) for table_name in profile.related_tables[:2]]

        if self._is_noise(profile):
            return "System-generated records that are usually safe to ignore for business Q&A."
        if self._is_bridge(profile) and len(related_tables) >= 2:
            return f"Connects {related_tables[0]} and {related_tables[1]} records."
        if category == "People & Teams":
            return "Stores people and team records used for ownership, assignment, or approvals."
        if category == "Locations & Facilities":
            return "Stores site or location records used to place operational activity."
        if category == "Customers & Accounts":
            return "Stores customer, company, or account records used across business workflows."
        if category == "Assets & Inventory":
            return "Tracks assets, inventory, or product records used by operational teams."
        if category == "Finance & Billing":
            return "Tracks billing, cost, payment, or other financial records."
        if category == "Reference Data":
            return f"Reference data for {label} used to classify other business records."
        if business_columns:
            return f"Tracks {label} records, including {_join_natural(business_columns)}."
        if related_tables:
            return f"Tracks {label} records linked to {_join_natural(related_tables)}."
        return f"Tracks {label} records for day-to-day business activity."

    def _business_score(self, profile: _SimpleTableProfile, category: str) -> int:
        if self._is_noise(profile):
            return 0

        score = 18
        if category == "Core Operations":
            score += 38
        elif category == "Reference Data":
            score += 12
        else:
            score += 26

        if self._is_lookup(profile):
            score += 5
        if self._is_bridge(profile):
            score -= 8

        score += min(16, len(profile.foreign_keys) * 4)
        score += min(16, len(profile.incoming_tables) * 4)
        score += min(12, len(self._business_columns(profile)) * 2)
        if self._has_semantic_columns(profile):
            score += 8

        return max(0, min(100, score))

    def _suggest_selection(
        self,
        profile: _SimpleTableProfile,
        category: str,
        score: int,
        selection_mode: str,
    ) -> bool:
        if self._is_noise(profile):
            return False

        threshold = 32 if selection_mode == "review" else 48
        if category == "Reference Data" and profile.incoming_tables:
            threshold -= 6
        if category == "Reference Data" and self._has_semantic_columns(profile):
            threshold -= 6
        if self._is_bridge(profile) and selection_mode == "ai":
            threshold += 6
        return score >= threshold

    def _selection_reason(self, profile: _SimpleTableProfile, category: str, suggested: bool) -> str:
        if self._is_noise(profile):
            return "Looks like system, audit, migration, or temporary data."

        reasons: list[str] = []
        if category == "Core Operations":
            reasons.append("Looks like a main business workflow table.")
        elif category == "Reference Data":
            reasons.append("Looks like supporting reference data.")
        else:
            reasons.append(f"Fits the {category.lower()} group.")

        if profile.incoming_tables:
            reasons.append("Referenced by other business tables.")
        if self._is_bridge(profile):
            reasons.append("Mostly links records between tables.")
        elif self._business_columns(profile):
            preview = _join_natural([_humanize(column) for column in self._business_columns(profile)[:2]])
            reasons.append(f"Has business fields such as {preview}.")
        if not suggested:
            reasons.append("Recommended to ignore by the current selection mode.")
        return " ".join(reasons)

    def _resolve_selected_tables(
        self,
        *,
        profiles: list[_SimpleTableProfile],
        categories: dict[str, str],
        suggested_selection: dict[str, bool],
        request: SimpleOnboardingRequest,
    ) -> set[str]:
        known_tables = {profile.table_name for profile in profiles}

        if request.selected_tables:
            return {table_name for table_name in request.selected_tables if table_name in known_tables}

        selected = {table_name for table_name, should_select in suggested_selection.items() if should_select}
        include_categories = {value.lower() for value in request.include_categories}
        exclude_categories = {value.lower() for value in request.exclude_categories}

        for table_name, category in categories.items():
            normalized = category.lower()
            if normalized in include_categories:
                selected.add(table_name)
            if normalized in exclude_categories and table_name in selected:
                selected.remove(table_name)

        for pattern in request.bulk_include_patterns:
            selected.update(self._match_patterns(known_tables, pattern))
        for pattern in request.bulk_exclude_patterns:
            selected.difference_update(self._match_patterns(known_tables, pattern))

        selected.update(table_name for table_name in request.include_tables if table_name in known_tables)
        selected.difference_update(table_name for table_name in request.exclude_tables if table_name in known_tables)
        return selected

    @staticmethod
    def _match_patterns(table_names: set[str], pattern: str) -> set[str]:
        normalized = str(pattern or "").strip().lower()
        if not normalized:
            return set()
        if not any(token in normalized for token in "*?[]"):
            normalized = f"*{normalized}*"
        return {table_name for table_name in table_names if fnmatch.fnmatch(table_name.lower(), normalized)}

    def _selected_relationships(
        self,
        profiles: list[_SimpleTableProfile],
        selected_tables: set[str],
    ) -> list[SimpleOnboardingRelationship]:
        relationships: list[SimpleOnboardingRelationship] = []
        seen: set[tuple[str, tuple[str, ...], str, tuple[str, ...]]] = set()

        for profile in profiles:
            if profile.table_name not in selected_tables:
                continue
            for relationship in profile.foreign_keys:
                if relationship.to_table not in selected_tables:
                    continue
                key = (
                    relationship.from_table,
                    tuple(relationship.from_columns),
                    relationship.to_table,
                    tuple(relationship.to_columns),
                )
                if key in seen:
                    continue
                seen.add(key)
                relationships.append(relationship)

        relationships.sort(key=lambda item: (item.from_table, item.to_table, ",".join(item.from_columns)))
        return relationships

    @staticmethod
    def _group_tables(table_names: list[str], categories: dict[str, str]) -> dict[str, list[str]]:
        grouped: dict[str, list[str]] = defaultdict(list)
        for table_name in sorted(table_names):
            category = categories.get(table_name)
            if not category:
                continue
            grouped[category].append(table_name)
        return {category: names for category, names in sorted(grouped.items())}

    def _is_noise(self, profile: _SimpleTableProfile) -> bool:
        tokens = _tokens(profile.table_name)
        return bool(tokens & self._NOISE_TERMS) or profile.table_name.lower().startswith(("tmp_", "temp_"))

    def _is_bridge(self, profile: _SimpleTableProfile) -> bool:
        tokens = _tokens(profile.table_name)
        if tokens & self._BRIDGE_TERMS:
            return True
        return len(profile.foreign_keys) >= 2 and len(self._business_columns(profile)) <= 2 and len(profile.columns) <= 8

    def _is_lookup(self, profile: _SimpleTableProfile) -> bool:
        if self._is_noise(profile) or self._is_bridge(profile):
            return False
        column_names = {name.lower() for name in profile.columns}
        key_columns = {"name", "label", "code", "title", "type", "category", "status", "condition", "outcome"}
        # Increased cardinality support for lookup tables as well
        if len(profile.columns) <= 5 and column_names & key_columns:
            return True
        return len(profile.columns) <= 4 and profile.incoming_tables and not profile.foreign_keys

    def _business_columns(self, profile: _SimpleTableProfile) -> list[str]:
        columns: list[str] = []
        for name in profile.columns:
            lowered = name.lower()
            if lowered == "id" or lowered.endswith("_id"):
                continue
            if lowered in self._HOUSEKEEPING_COLUMNS:
                continue
            columns.append(name)
        return columns

    def _has_semantic_columns(self, profile: _SimpleTableProfile) -> bool:
        column_tokens = _tokens(*profile.columns)
        return bool(column_tokens & self._DATE_TERMS) or bool(column_tokens & self._STATUS_TERMS)
