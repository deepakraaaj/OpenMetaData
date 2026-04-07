from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import shutil

from app.models.questionnaire import QuestionnaireBundle
from app.models.semantic import GlossaryTerm, QueryPattern, SemanticSourceModel
from app.models.technical import ColumnProfile, SourceTechnicalMetadata, TableProfile
from app.utils.files import ensure_dir
from app.utils.serialization import write_json

SEMANTIC_BUNDLE_VERSION = 1
SEMANTIC_BUNDLE_DIRNAME = "semantic_bundle"
SEMANTIC_BUNDLE_FILES = (
    "schema_context.json",
    "business_semantics.json",
    "relationship_map.json",
    "enum_dictionary.json",
    "query_patterns.json",
)


def _normalize_name(value: str) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


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


class SemanticBundleExporter:
    def build(
        self,
        *,
        semantic: SemanticSourceModel,
        technical: SourceTechnicalMetadata,
        questionnaire: QuestionnaireBundle | None = None,
        domain_name: str | None = None,
    ) -> dict[str, dict]:
        domain = _normalize_name(domain_name or semantic.domain or semantic.source_name)
        technical_tables = self._technical_tables(technical)
        generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

        bundle = {
            "schema_context.json": self._schema_context_payload(
                semantic=semantic,
                technical=technical,
                technical_tables=technical_tables,
                domain=domain,
                generated_at=generated_at,
            ),
            "business_semantics.json": self._business_semantics_payload(
                semantic=semantic,
                questionnaire=questionnaire,
                domain=domain,
                generated_at=generated_at,
            ),
            "relationship_map.json": self._relationship_map_payload(
                semantic=semantic,
                technical=technical,
                questionnaire=questionnaire,
                technical_tables=technical_tables,
                domain=domain,
                generated_at=generated_at,
            ),
            "enum_dictionary.json": self._enum_dictionary_payload(
                semantic=semantic,
                technical=technical,
                domain=domain,
                generated_at=generated_at,
            ),
            "query_patterns.json": self._query_patterns_payload(
                semantic=semantic,
                questionnaire=questionnaire,
                domain=domain,
                generated_at=generated_at,
            ),
        }
        return bundle

    def write(
        self,
        *,
        semantic: SemanticSourceModel,
        technical: SourceTechnicalMetadata,
        questionnaire: QuestionnaireBundle | None,
        source_output_dir: Path,
        domain_name: str | None = None,
    ) -> Path:
        bundle = self.build(
            semantic=semantic,
            technical=technical,
            questionnaire=questionnaire,
            domain_name=domain_name,
        )
        bundle_dir = source_output_dir / SEMANTIC_BUNDLE_DIRNAME
        ensure_dir(bundle_dir)
        for filename, payload in bundle.items():
            write_json(bundle_dir / filename, payload)
        write_json(
            bundle_dir / "bundle_manifest.json",
            {
                "bundle_type": "tag_semantic_bundle",
                "version": SEMANTIC_BUNDLE_VERSION,
                "files": list(SEMANTIC_BUNDLE_FILES),
                "notes": [
                    "These files are the human-editable semantic retrieval source of truth for TAG.",
                    "Review and edit them before publishing into a TAG domain folder.",
                ],
            },
        )
        return bundle_dir

    def publish(
        self,
        *,
        bundle_dir: Path,
        target_domain_dir: Path,
    ) -> Path:
        semantic_dir = target_domain_dir / SEMANTIC_BUNDLE_DIRNAME
        ensure_dir(semantic_dir)
        for filename in (*SEMANTIC_BUNDLE_FILES, "bundle_manifest.json"):
            source = bundle_dir / filename
            if source.exists():
                shutil.copy2(source, semantic_dir / filename)
        return semantic_dir

    def _technical_tables(self, technical: SourceTechnicalMetadata) -> dict[str, TableProfile]:
        tables: dict[str, TableProfile] = {}
        for schema in technical.schemas:
            for table in schema.tables:
                tables[table.table_name] = table
        return tables

    def _schema_context_payload(
        self,
        *,
        semantic: SemanticSourceModel,
        technical: SourceTechnicalMetadata,
        technical_tables: dict[str, TableProfile],
        domain: str,
        generated_at: str,
    ) -> dict:
        tables: list[dict] = []
        for semantic_table in semantic.tables:
            technical_table = technical_tables.get(semantic_table.table_name)
            technical_columns = {column.name: column for column in (technical_table.columns if technical_table else [])}
            tenant_candidates = [
                column.name
                for column in technical_columns.values()
                if column.name.lower() in {"company_id", "tenant_id", "organization_id", "org_id", "account_id"}
            ]
            tables.append(
                {
                    "table_name": semantic_table.table_name,
                    "label": str(semantic_table.likely_entity or _humanize(semantic_table.table_name)).strip(),
                    "description": str(
                        semantic_table.business_meaning or technical_table.description if technical_table else ""
                    ).strip()
                    or f"{_humanize(semantic_table.table_name)} records",
                    "schema_name": technical_table.schema_name if technical_table else "",
                    "estimated_row_count": technical_table.estimated_row_count if technical_table else None,
                    "primary_key": list(technical_table.primary_key if technical_table else []),
                    "tenant_scope_candidates": tenant_candidates,
                    "status_columns": list(technical_table.status_columns if technical_table else []),
                    "timestamp_columns": list(technical_table.timestamp_columns if technical_table else []),
                    "important_columns": [
                        {
                            "column_name": column_name,
                            "description": self._column_description(
                                semantic_table=semantic_table,
                                technical_column=technical_columns.get(column_name),
                            ),
                            "data_type": technical_columns.get(column_name).data_type if technical_columns.get(column_name) else "",
                            "nullable": technical_columns.get(column_name).nullable if technical_columns.get(column_name) else True,
                        }
                        for column_name in _dedupe_keep_order(
                            list(semantic_table.important_columns)
                            + [column.column_name for column in semantic_table.columns[:8]]
                        )[:16]
                    ],
                }
            )

        return {
            "version": SEMANTIC_BUNDLE_VERSION,
            "source_name": semantic.source_name,
            "domain_name": domain,
            "generated_at": generated_at,
            "database": {
                "db_type": str(technical.db_type),
                "database_name": technical.database_name,
                "connectivity_ok": technical.connectivity_ok,
                "source_summary": technical.source_summary,
            },
            "tables": tables,
        }

    def _business_semantics_payload(
        self,
        *,
        semantic: SemanticSourceModel,
        questionnaire: QuestionnaireBundle | None,
        domain: str,
        generated_at: str,
    ) -> dict:
        glossary = []
        for term in semantic.glossary:
            glossary.append(
                {
                    "term": term.term,
                    "meaning": term.meaning,
                    "synonyms": list(term.synonyms),
                    "related_tables": list(term.related_tables),
                    "related_columns": list(term.related_columns),
                }
            )

        unresolved = []
        if questionnaire:
            for question in questionnaire.questions:
                if question.type in {"table_business_meaning", "column_business_meaning", "relationship_validation"}:
                    continue
                if question.answer not in (None, "", []):
                    continue
                unresolved.append(
                    {
                        "type": question.type,
                        "question": question.question,
                        "table": question.table,
                        "column": question.column,
                        "suggested_answer": question.suggested_answer,
                        "answer": question.answer,
                    }
                )

        entities = []
        for entity in semantic.canonical_entities:
            entities.append(
                {
                    "entity_name": entity.entity_name,
                    "description": entity.description,
                    "mapped_source_tables": list(entity.mapped_source_tables),
                    "mapped_columns": list(entity.mapped_columns),
                }
            )

        return {
            "version": SEMANTIC_BUNDLE_VERSION,
            "source_name": semantic.source_name,
            "domain_name": domain,
            "generated_at": generated_at,
            "scope": str(semantic.description or f"{semantic.source_name} business operations").strip(),
            "key_entities": list(semantic.key_entities),
            "approved_use_cases": list(semantic.approved_use_cases),
            "sensitive_areas": list(semantic.sensitive_areas),
            "glossary": glossary,
            "canonical_entities": entities,
            "unresolved_questions": unresolved[:24],
        }

    def _relationship_map_payload(
        self,
        *,
        semantic: SemanticSourceModel,
        technical: SourceTechnicalMetadata,
        questionnaire: QuestionnaireBundle | None,
        technical_tables: dict[str, TableProfile],
        domain: str,
        generated_at: str,
    ) -> dict:
        relationships: list[dict] = []

        for table in semantic.tables:
            for join in table.valid_joins:
                relationships.append(
                    {
                        "kind": "semantic_validated_join",
                        "table": table.table_name,
                        "join": join,
                        "confidence": table.confidence.score,
                    }
                )

        for table in technical_tables.values():
            for fk in table.foreign_keys:
                if not fk.constrained_columns or not fk.referred_columns:
                    continue
                relationships.append(
                    {
                        "kind": "foreign_key",
                        "table": table.table_name,
                        "related_table": fk.referred_table,
                        "join": (
                            f"{table.table_name}.{fk.constrained_columns[0]} = "
                            f"{fk.referred_table}.{fk.referred_columns[0]}"
                        ),
                        "confidence": 1.0,
                    }
                )
            for candidate in table.candidate_joins:
                relationships.append(
                    {
                        "kind": "candidate_join",
                        "table": table.table_name,
                        "related_table": candidate.right_table,
                        "join": (
                            f"{candidate.left_table}.{candidate.left_column} = "
                            f"{candidate.right_table}.{candidate.right_column}"
                        ),
                        "confidence": candidate.confidence,
                        "reasons": list(candidate.reasons),
                    }
                )

        review_questions = []
        if questionnaire:
            for question in questionnaire.questions:
                if question.type != "relationship_validation":
                    continue
                review_questions.append(
                    {
                        "question": question.question,
                        "left_table": question.left_table,
                        "right_table": question.right_table,
                        "suggested_join": question.suggested_join,
                        "answer": question.answer,
                    }
                )

        return {
            "version": SEMANTIC_BUNDLE_VERSION,
            "source_name": semantic.source_name,
            "domain_name": domain,
            "generated_at": generated_at,
            "relationships": relationships,
            "review_questions": review_questions,
        }

    def _enum_dictionary_payload(
        self,
        *,
        semantic: SemanticSourceModel,
        technical: SourceTechnicalMetadata,
        domain: str,
        generated_at: str,
    ) -> dict:
        semantic_column_lookup: dict[tuple[str, str], tuple[str, list[str]]] = {}
        for table in semantic.tables:
            for column in table.columns:
                semantic_column_lookup[(table.table_name, column.column_name)] = (
                    str(column.business_meaning or "").strip(),
                    list(column.example_values),
                )

        entries: list[dict] = []
        for schema in technical.schemas:
            for table in schema.tables:
                for column in table.columns:
                    if not column.enum_values and not column.is_status_like and not column.sample_values:
                        continue
                    business_meaning, semantic_examples = semantic_column_lookup.get(
                        (table.table_name, column.name),
                        ("", []),
                    )
                    entries.append(
                        {
                            "table_name": table.table_name,
                            "column_name": column.name,
                            "data_type": column.data_type,
                            "business_meaning": business_meaning,
                            "enum_values": list(column.enum_values),
                            "sample_values": list(column.sample_values or semantic_examples)[:20],
                            "status_like": column.is_status_like,
                        }
                    )

        return {
            "version": SEMANTIC_BUNDLE_VERSION,
            "source_name": semantic.source_name,
            "domain_name": domain,
            "generated_at": generated_at,
            "entries": entries,
        }

    def _query_patterns_payload(
        self,
        *,
        semantic: SemanticSourceModel,
        questionnaire: QuestionnaireBundle | None,
        domain: str,
        generated_at: str,
    ) -> dict:
        patterns = [self._pattern_payload(pattern) for pattern in semantic.query_patterns]
        review_hints = []
        if questionnaire:
            for question in questionnaire.questions:
                if question.type not in {"table_business_meaning", "column_business_meaning"}:
                    continue
                review_hints.append(
                    {
                        "question": question.question,
                        "table": question.table,
                        "column": question.column,
                        "suggested_answer": question.suggested_answer,
                        "answer": question.answer,
                    }
                )

        return {
            "version": SEMANTIC_BUNDLE_VERSION,
            "source_name": semantic.source_name,
            "domain_name": domain,
            "generated_at": generated_at,
            "patterns": patterns,
            "learned_queries": [],
            "review_hints": review_hints[:24],
        }

    def _pattern_payload(self, pattern: QueryPattern) -> dict:
        return {
            "intent": pattern.intent,
            "question_examples": list(pattern.question_examples),
            "preferred_tables": list(pattern.preferred_tables),
            "required_joins": list(pattern.required_joins),
            "safe_filters": list(pattern.safe_filters),
            "optional_sql_template": pattern.optional_sql_template,
            "rendering_guidance": pattern.rendering_guidance,
        }

    def _column_description(
        self,
        *,
        semantic_table,
        technical_column: ColumnProfile | None,
    ) -> str:
        if technical_column is None:
            return ""
        for column in semantic_table.columns:
            if column.column_name == technical_column.name and str(column.business_meaning or "").strip():
                return str(column.business_meaning).strip()
        return f"{_humanize(technical_column.name)} ({technical_column.data_type})"


__all__ = [
    "SEMANTIC_BUNDLE_DIRNAME",
    "SEMANTIC_BUNDLE_FILES",
    "SEMANTIC_BUNDLE_VERSION",
    "SemanticBundleExporter",
]
