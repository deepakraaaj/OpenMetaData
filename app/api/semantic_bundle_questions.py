from __future__ import annotations


def _clean(value: object) -> str:
    return str(value or "").strip()


def _dedupe_strings(values: list[object], limit: int | None = None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = _clean(value)
        lowered = cleaned.lower()
        if not cleaned or lowered in seen:
            continue
        seen.add(lowered)
        out.append(cleaned)
        if limit is not None and len(out) >= limit:
            break
    return out


def _pick_table_choice(table_choices: list[dict], keywords: tuple[str, ...]) -> str:
    for choice in table_choices:
        label = _clean(choice.get("label")).lower()
        if any(keyword in label for keyword in keywords):
            return _clean(choice.get("label"))
    return ""


def _question_kind(item: dict) -> str:
    if list(item.get("candidate_options") or []):
        return "select"
    if _clean(item.get("type")) == "status_semantics":
        return "textarea"
    return "text"


def _question_choices(item: dict) -> list[dict]:
    options = list(item.get("candidate_options") or [])
    if options:
        return [
            {
                "label": _clean(option.get("label")),
                "value": _clean(option.get("value")),
                "description": _clean(option.get("description")),
                "is_best_guess": bool(option.get("is_best_guess")),
                "is_fallback": bool(option.get("is_fallback")),
            }
            for option in options
            if _clean(option.get("label"))
        ]
    if _clean(item.get("type")) != "chatbot_exposure":
        return []
    return [
        {"label": "yes", "value": "yes"},
        {"label": "no", "value": "no"},
        {"label": "review", "value": "review"},
    ]


def _question_evidence(item: dict) -> list[str]:
    evidence = list(item.get("evidence") or [])
    best_guess = _clean(item.get("best_guess")) or _clean(item.get("suggested_answer"))
    if best_guess:
        evidence = [f"System belief: {best_guess}", *evidence]
    return _dedupe_strings(
        evidence + [item.get("table"), item.get("column")],
        limit=8,
    )


def _question_label(item: dict) -> str:
    return _clean(item.get("decision_prompt")) or _clean(item.get("question"))


def _is_meaningful_enum_entry(item: dict) -> bool:
    column_name = _clean(item.get("column_name")).lower()
    if not column_name or column_name == "id" or column_name.endswith("_id"):
        return False
    if column_name in {"name", "title", "description", "notes", "comment", "comments"}:
        return False
    if any(token in column_name for token in ("date", "time", "timestamp", "created", "updated", "deleted")):
        return False

    values = _dedupe_strings(
        list(item.get("enum_values") or []) + list(item.get("sample_values") or []),
        limit=8,
    )
    if len(values) < 2 or len(values) > 8:
        return False

    business_like_name = any(
        token in column_name for token in ("status", "state", "priority", "type", "category", "flag", "reason", "stage")
    )
    compact_values = all(len(value) <= 20 and ":" not in value and "/" not in value for value in values)
    return bool(item.get("status_like")) or business_like_name or compact_values


def build_semantic_bundle_questions(bundle: dict[str, dict]) -> list[dict]:
    schema = dict(bundle.get("schema_context.json") or {})
    semantics = dict(bundle.get("business_semantics.json") or {})
    relationships = dict(bundle.get("relationship_map.json") or {})
    enums = dict(bundle.get("enum_dictionary.json") or {})
    patterns = dict(bundle.get("query_patterns.json") or {})

    tables = list(schema.get("tables") or [])
    glossary = list(semantics.get("glossary") or [])
    unresolved = list(semantics.get("unresolved_questions") or [])
    relationship_questions = list(relationships.get("review_questions") or [])
    enum_entries = list(enums.get("entries") or [])
    pattern_entries = list(patterns.get("patterns") or [])
    review_hints = list(patterns.get("review_hints") or [])

    review_scope_tables = [
        item
        for item in tables
        if bool(item.get("selected")) or bool(item.get("needs_review"))
    ] or tables

    table_choices = [
        {
            "label": _clean(item.get("table_name")),
            "hint": _clean(item.get("description")),
        }
        for item in review_scope_tables
        if _clean(item.get("table_name"))
    ]
    primary_table = _clean((semantics.get("table_roles") or {}).get("primary_table")) or (
        table_choices[0]["label"] if table_choices else ""
    )
    people_table = _clean((semantics.get("table_roles") or {}).get("people_table")) or _pick_table_choice(
        table_choices,
        ("user", "person", "employee", "staff", "technician", "driver", "agent", "member"),
    )
    location_table = _clean((semantics.get("table_roles") or {}).get("location_table")) or _pick_table_choice(
        table_choices,
        ("location", "facility", "site", "branch", "warehouse", "area", "region", "store"),
    )

    sections: list[dict] = [
        {
            "id": "domain-purpose",
            "title": "Domain Purpose",
            "description": "Confirm the business scope and main entities before SQL patterns are learned.",
            "questions": [
                {
                    "id": "scope",
                    "label": "What is this application mainly used for?",
                    "kind": "textarea",
                    "bundle_file": "business_semantics.json",
                    "field_path": ["scope"],
                    "suggested_answer": _clean(semantics.get("scope")),
                    "evidence": _dedupe_strings([
                        f"Source: {schema.get('source_name', '')}",
                        f"DB type: {schema.get('database', {}).get('db_type', '')}",
                    ]),
                },
                {
                    "id": "key-entities",
                    "label": "What do users call the main records in this app?",
                    "kind": "tags",
                    "bundle_file": "business_semantics.json",
                    "field_path": ["key_entities"],
                    "suggested_answer": list(semantics.get("key_entities") or []),
                    "evidence": _dedupe_strings([item["label"] for item in table_choices[:6]]),
                },
            ],
        },
        {
            "id": "table-roles",
            "title": "Table Roles",
            "description": "Pick the operational tables the assistant should prioritize.",
            "questions": [
                {
                    "id": "primary-table",
                    "label": "Which table is the main operational record table?",
                    "kind": "select",
                    "bundle_file": "business_semantics.json",
                    "field_path": ["table_roles", "primary_table"],
                    "choices": table_choices,
                    "suggested_answer": primary_table,
                    "evidence": _dedupe_strings([
                        f"{item.get('table_name')}: rows={item.get('estimated_row_count')}"
                        for item in review_scope_tables[:8]
                    ]),
                },
                {
                    "id": "people-table",
                    "label": "Which table represents people or users in this domain?",
                    "kind": "select",
                    "bundle_file": "business_semantics.json",
                    "field_path": ["table_roles", "people_table"],
                    "choices": table_choices,
                    "suggested_answer": people_table,
                    "evidence": _dedupe_strings(
                        [
                            item["label"]
                            for item in table_choices
                            if any(
                                keyword in item["label"].lower()
                                for keyword in ("user", "person", "employee", "staff", "technician", "driver", "agent")
                            )
                        ],
                        limit=6,
                    ),
                },
                {
                    "id": "location-table",
                    "label": "Which table represents facilities, locations, or service areas?",
                    "kind": "select",
                    "bundle_file": "business_semantics.json",
                    "field_path": ["table_roles", "location_table"],
                    "choices": table_choices,
                    "suggested_answer": location_table,
                    "evidence": _dedupe_strings(
                        [
                            item["label"]
                            for item in table_choices
                            if any(
                                keyword in item["label"].lower()
                                for keyword in ("location", "facility", "site", "branch", "warehouse", "area", "region")
                            )
                        ],
                        limit=6,
                    ),
                },
                {
                    "id": "tenant-scope",
                    "label": "Which tenant/company field should TAG always filter on?",
                    "kind": "table-column-select",
                    "bundle_file": "schema_context.json",
                    "field_path": ["table_roles", "tenant_scope"],
                    "choices": [
                        {
                            "table_name": item.get("table_name"),
                            "columns": list(item.get("tenant_scope_candidates") or []),
                        }
                        for item in review_scope_tables
                        if list(item.get("tenant_scope_candidates") or [])
                    ],
                    "suggested_answer": "",
                    "evidence": _dedupe_strings([
                        f"{item.get('table_name')}: {', '.join(item.get('tenant_scope_candidates') or [])}"
                        for item in review_scope_tables
                        if item.get("tenant_scope_candidates")
                    ], limit=8),
                },
            ],
        },
        {
            "id": "business-language",
            "title": "Business Language",
            "description": "Refine glossary terms and resolve unknown business meanings.",
            "questions": [
                {
                    "id": f"glossary-{index}",
                    "label": f"What should '{item.get('term')}' mean in the assistant?",
                    "kind": "text",
                    "bundle_file": "business_semantics.json",
                    "field_path": ["glossary", index, "meaning"],
                    "suggested_answer": _clean(item.get("meaning")),
                    "evidence": _dedupe_strings(
                        list(item.get("related_tables") or []) + list(item.get("related_columns") or []),
                        limit=6,
                    ),
                }
                for index, item in enumerate(glossary[:12])
                if _clean(item.get("term"))
            ],
        },
        {
            "id": "review-hints",
            "title": "Table And Column Meaning",
            "description": "Confirm the labels and meanings the assistant should use for important tables and columns.",
            "questions": [
                {
                    "id": f"review-hint-{index}",
                    "label": _question_label(item)
                    or (
                        f"What does `{item.get('table')}.{item.get('column')}` mean?"
                        if _clean(item.get("column"))
                        else f"What does `{item.get('table')}` represent in business language?"
                    ),
                    "kind": _question_kind(item),
                    "bundle_file": "query_patterns.json",
                    "field_path": ["review_hints", index, "answer"],
                    "suggested_answer": item.get("answer") if item.get("answer") not in (None, "") else item.get("best_guess") or item.get("suggested_answer"),
                    "choices": _question_choices(item),
                    "evidence": _question_evidence(item),
                }
                for index, item in enumerate(review_hints[:12])
                if _clean(item.get("table")) or _clean(item.get("question"))
            ],
        },
        {
            "id": "business-rules",
            "title": "Business Rules",
            "description": "Answer the operational questions the LLM cannot infer safely from schema alone.",
            "questions": [
                {
                    "id": f"unresolved-{index}",
                    "label": _question_label(item),
                    "kind": _question_kind(item),
                    "bundle_file": "business_semantics.json",
                    "field_path": ["unresolved_questions", index, "answer"],
                    "suggested_answer": item.get("answer") if item.get("answer") not in (None, "") else item.get("best_guess") or item.get("suggested_answer"),
                    "choices": _question_choices(item),
                    "evidence": _question_evidence(item),
                }
                for index, item in enumerate(unresolved[:12])
                if _clean(item.get("question"))
                and _clean(item.get("type")) not in {"table_business_meaning", "column_business_meaning"}
            ],
        },
        {
            "id": "enum-meaning",
            "title": "Statuses And Enums",
            "description": "Map status, priority, type, and compact categorical values to business labels the LLM cannot infer reliably.",
            "questions": [
                {
                    "id": f"enum-{index}",
                    "label": f"What should `{item.get('table_name')}.{item.get('column_name')}` values mean?",
                    "kind": "textarea",
                    "bundle_file": "enum_dictionary.json",
                    "field_path": ["entries", index, "business_meaning"],
                    "suggested_answer": _clean(item.get("business_meaning")),
                    "evidence": _dedupe_strings(
                        list(item.get("enum_values") or []) + list(item.get("sample_values") or []),
                        limit=6,
                    ),
                }
                for index, item in enumerate(enum_entries[:16])
                if _is_meaningful_enum_entry(item)
            ],
        },
        {
            "id": "query-patterns",
            "title": "Real Questions",
            "description": "Add the real questions users ask so retrieval and SQL generation match production language.",
            "questions": [
                {
                    "id": f"pattern-{index}",
                    "label": f"Which real questions should map to intent '{item.get('intent')}'?",
                    "kind": "tags",
                    "bundle_file": "query_patterns.json",
                    "field_path": ["patterns", index, "question_examples"],
                    "suggested_answer": list(item.get("question_examples") or []),
                    "evidence": _dedupe_strings(
                        list(item.get("preferred_tables") or []) + list(item.get("safe_filters") or []),
                        limit=8,
                    ),
                }
                for index, item in enumerate(pattern_entries[:12])
            ]
            + [
                {
                    "id": "additional-real-questions",
                    "label": "What other real user questions should the assistant understand?",
                    "kind": "tags",
                    "bundle_file": "query_patterns.json",
                    "field_path": ["additional_examples"],
                    "suggested_answer": [],
                    "evidence": _dedupe_strings([
                        str(item.get("intent") or "").strip()
                        for item in pattern_entries[:8]
                        if str(item.get("intent") or "").strip()
                    ]),
                }
            ],
        },
        {
            "id": "relationships",
            "title": "Join Validation",
            "description": "Confirm business joins, especially non-FK joins the LLM cannot safely invent.",
            "questions": [
                {
                    "id": f"relationship-{index}",
                    "label": _question_label(item) or str(item.get("question") or "").strip(),
                    "kind": "select" if _question_choices(item) else "boolean",
                    "bundle_file": "relationship_map.json",
                    "field_path": ["review_questions", index, "answer"],
                    "suggested_answer": item.get("answer") if item.get("answer") not in (None, "") else item.get("best_guess"),
                    "choices": _question_choices(item),
                    "evidence": _question_evidence(item) or _dedupe_strings([item.get("suggested_join")], limit=1),
                }
                for index, item in enumerate(relationship_questions[:12])
                if _clean(item.get("question"))
            ],
        },
    ]

    return [section for section in sections if section.get("questions")]
