from __future__ import annotations

import shutil
from pathlib import Path

from app.models.questionnaire import QuestionnaireBundle
from app.models.semantic import SemanticSourceModel, SemanticTable
from app.models.technical import SourceTechnicalMetadata
from app.utils.files import ensure_dir
from app.utils.serialization import write_json


def _dedupe_keep_order(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = str(value or "").strip()
        lowered = cleaned.lower()
        if not cleaned or lowered in seen:
            continue
        seen.add(lowered)
        out.append(cleaned)
    return out


def _humanize(value: str) -> str:
    return " ".join(str(value or "").replace("_", " ").split())


class TagBundleExporter:
    def export(
        self,
        *,
        semantic: SemanticSourceModel,
        technical: SourceTechnicalMetadata,
        questionnaire: QuestionnaireBundle | None,
        source_output_dir: Path,
        domain_name: str | None = None,
        include_raw_exports: bool = True,
    ) -> Path:
        domain = str(domain_name or semantic.domain or semantic.source_name).strip().lower().replace(" ", "_")
        bundle_dir = source_output_dir / "tag_bundle" / domain
        generated_dir = bundle_dir / "generated"
        review_dir = bundle_dir / "review"
        reference_dir = bundle_dir / "openmetadata_exports"

        ensure_dir(generated_dir)
        ensure_dir(review_dir)
        if include_raw_exports:
            ensure_dir(reference_dir)

        capabilities = self._capabilities_payload(semantic)
        domain_knowledge = self._domain_knowledge_payload(semantic, questionnaire)
        manifest_review = self._manifest_review_payload(semantic, technical)
        bundle_manifest = {
            "bundle_type": "tag_domain_overlay",
            "source_name": semantic.source_name,
            "domain_name": domain,
            "copy_into_tag_domain_folder": True,
            "copy_targets": [
                "generated/capabilities.json",
                "generated/domain_knowledge.json",
            ],
            "review_before_merge": [
                "review/manifest.tables.review.json",
            ],
            "notes": [
                "This bundle is designed to be produced independently by OpenMetaData and copied into a TAG domain folder.",
                "The generated overlay improves semantic understanding and help text without automatically replacing manual CRUD rules.",
                "Review the manifest tables file before merging it into TAG because TAG treats generated manifest tables as a full tables override.",
            ],
        }

        write_json(bundle_dir / "bundle_manifest.json", bundle_manifest)
        write_json(generated_dir / "capabilities.json", capabilities)
        write_json(generated_dir / "domain_knowledge.json", domain_knowledge)
        write_json(review_dir / "manifest.tables.review.json", manifest_review)
        (bundle_dir / "README.md").write_text(
            self._readme_text(domain=domain, source_name=semantic.source_name),
            encoding="utf-8",
        )

        if include_raw_exports:
            for filename in (
                "technical_metadata.json",
                "semantic_model.json",
                "questionnaire.json",
                "llm_context_package.json",
                "normalized_metadata.json",
            ):
                source_file = source_output_dir / filename
                if source_file.exists():
                    shutil.copy2(source_file, reference_dir / filename)

        return bundle_dir

    def _capabilities_payload(self, semantic: SemanticSourceModel) -> dict:
        examples = self._example_queries(semantic)
        categorized: dict[str, list[str]] = {}
        for table in semantic.tables[:8]:
            label = str(table.likely_entity or _humanize(table.table_name) or "Tables").strip()
            questions = [
                str(item or "").strip()
                for item in table.common_business_questions
                if str(item or "").strip()
            ]
            if questions:
                categorized[label] = questions[:4]
        if not categorized and examples:
            categorized["Examples"] = examples[:6]

        description = str(semantic.description or "").strip()
        if not description:
            domain = str(semantic.domain or semantic.source_name).strip()
            description = f"I help explain and query {domain} data."

        return {
            "review_mode": semantic.review_mode.value,
            "description": description,
            "categorized_examples": categorized,
            "examples": examples[:10],
            "tables_description": {
                table.table_name: str(table.business_meaning or f"{_humanize(table.table_name)} records").strip()
                for table in semantic.tables
            },
        }

    def _domain_knowledge_payload(
        self,
        semantic: SemanticSourceModel,
        questionnaire: QuestionnaireBundle | None,
    ) -> dict:
        business_terms = {
            term.term: term.meaning
            for term in semantic.glossary
            if str(term.term or "").strip() and str(term.meaning or "").strip()
        }
        example_queries = self._example_queries(semantic)

        categorized_examples: dict[str, list[str]] = {}
        for pattern in semantic.query_patterns[:10]:
            key = str(pattern.intent or "Queries").strip() or "Queries"
            values = [str(item or "").strip() for item in pattern.question_examples if str(item or "").strip()]
            if values:
                categorized_examples[key] = values[:4]
        if not categorized_examples and example_queries:
            categorized_examples["Queries"] = example_queries[:6]

        workflows: list[dict] = []
        if questionnaire:
            for question in questionnaire.questions[:12]:
                if question.type not in {"relationship_validation", "table_business_meaning", "column_business_meaning"}:
                    continue
                label = str(question.question or "").strip()
                if not label:
                    continue
                workflows.append(
                    {
                        "workflow_id": f"review_{question.type}",
                        "label": label[:120],
                        "table": str(question.table or question.left_table or semantic.tables[0].table_name if semantic.tables else ""),
                        "operation": "review",
                        "trigger_phrases": [],
                        "required_fields": [],
                        "reasoning": "Review prompt carried over from OpenMetaData questionnaire output.",
                        "confidence": 40,
                    }
                )

        scope = str(semantic.description or "").strip()
        if not scope:
            scope = f"{semantic.source_name} business operations"

        return {
            "review_mode": semantic.review_mode.value,
            "scope": scope,
            "primary_entities": _dedupe_keep_order(
                [str(item or "").strip().lower() for item in semantic.key_entities if str(item or "").strip()]
            )[:10],
            "business_terms": business_terms,
            "business_rules": [
                {
                    "rule_name": rule.rule_name,
                    "description": rule.description,
                    "enforcement_level": rule.enforcement_level,
                    "related_tables": list(rule.related_tables),
                    "related_columns": list(rule.related_columns),
                }
                for rule in semantic.business_rules
            ],
            "example_queries": example_queries[:10],
            "categorized_examples": categorized_examples,
            "review_debt": [
                {
                    "title": item.title,
                    "table_name": item.table_name,
                    "decision_status": item.decision_status.value,
                    "risk_level": item.risk_level.value,
                    "publish_blocker": item.publish_blocker,
                }
                for item in semantic.review_debt[:24]
            ],
            "workflows": workflows[:8],
            "reasoning_profile": {
                "name": "OpenMetaData semantic overlay",
                "behavior_summary": "Prefer metadata-backed answers, ask one clarification if a business meaning or join is ambiguous, and do not guess when evidence is weak.",
                "rules": [
                    "metadata first",
                    "answer directly",
                    "one clarification if blocked",
                    "say when business meaning is unknown",
                    "avoid inventing joins or status meanings",
                    "plain text",
                ],
                "response_modes": {
                    "default": "direct answer, short and evidence-backed",
                    "help": "brief help plus a few example queries",
                    "count": "no guessing without query evidence",
                    "lookup": "no guessing without query evidence",
                },
                "evidence_sources": [
                    "openmetadata_semantic_model",
                    "openmetadata_technical_metadata",
                    "approved_tag_domain_config",
                ],
                "clarification_policy": "Ask one targeted question when business meaning, status semantics, or join validity is ambiguous.",
                "abstention_policy": "If metadata is missing or confidence is low, say so and stop instead of inventing an answer.",
            },
        }

    def _manifest_review_payload(
        self,
        semantic: SemanticSourceModel,
        technical: SourceTechnicalMetadata,
    ) -> dict:
        technical_tables = {
            table.table_name: table
            for schema in technical.schemas
            for table in schema.tables
        }
        manifest_tables: dict[str, dict] = {}
        for semantic_table in semantic.tables:
            technical_table = technical_tables.get(semantic_table.table_name)
            important_column_names = _dedupe_keep_order(
                list(semantic_table.important_columns)
                + [column.column_name for column in semantic_table.columns[:8]]
            )[:12]
            joins = {}
            if technical_table:
                for fk in technical_table.foreign_keys:
                    if not fk.constrained_columns or not fk.referred_columns:
                        continue
                    joins[fk.referred_table] = (
                        f"{semantic_table.table_name}.{fk.constrained_columns[0]} = "
                        f"{fk.referred_table}.{fk.referred_columns[0]}"
                    )

            manifest_tables[semantic_table.table_name] = {
                "description": str(
                    semantic_table.business_meaning or f"{_humanize(semantic_table.table_name)} records"
                ).strip(),
                "decision_status": semantic_table.decision_status.value if semantic_table.decision_status else None,
                "decision_actor": semantic_table.decision_actor.value if semantic_table.decision_actor else None,
                "risk_level": semantic_table.risk_level.value if semantic_table.risk_level else None,
                "review_debt": semantic_table.review_debt,
                "publish_blocker": semantic_table.publish_blocker,
                "needs_acknowledgement": semantic_table.needs_acknowledgement,
                "primary_key": technical_table.primary_key[0] if technical_table and technical_table.primary_key else "id",
                "joins": joins,
                "important_columns": {
                    column_name: {
                        "description": self._column_description(semantic_table, column_name),
                    }
                    for column_name in important_column_names
                },
                "aliases": _dedupe_keep_order(
                    [
                        _humanize(semantic_table.table_name),
                        _humanize(str(semantic_table.likely_entity or "")),
                    ]
                ),
                "review_notes": [
                    "Generated by OpenMetaData for review before merging into TAG.",
                    "Do not overwrite manual TAG CRUD operations or table rules blindly.",
                ],
            }

        return {
            "tables": manifest_tables,
        }

    def _column_description(self, table: SemanticTable, column_name: str) -> str:
        for column in table.columns:
            if column.column_name == column_name:
                return str(column.business_meaning or f"{_humanize(column_name)} ({column.technical_type})").strip()
        return _humanize(column_name)

    def _example_queries(self, semantic: SemanticSourceModel) -> list[str]:
        examples: list[str] = []
        for pattern in semantic.query_patterns:
            examples.extend(
                [str(item or "").strip() for item in pattern.question_examples if str(item or "").strip()]
            )
        for table in semantic.tables:
            examples.extend(
                [str(item or "").strip() for item in table.common_business_questions if str(item or "").strip()]
            )
        return _dedupe_keep_order(examples)

    def _readme_text(self, *, domain: str, source_name: str) -> str:
        return f"""# TAG Bundle for `{domain}`

This folder was generated by OpenMetaData for source `{source_name}`.

## Safe copy path

Copy these files into your TAG domain folder:

- `generated/capabilities.json`
- `generated/domain_knowledge.json`

Example target:

```text
TAG-Implementation/app/domains/{domain}/generated/
```

## Review-only file

`review/manifest.tables.review.json` contains generated table descriptions, joins, and important columns.

Review that file before merging anything into TAG's `schema_manifest.json` or `generated/manifest/tables.json`, because TAG treats manifest table overlays as a full tables override.

## Raw source exports

`openmetadata_exports/` contains the original OpenMetaData JSON files for traceability and manual review.
"""
