from __future__ import annotations

from datetime import datetime, timezone
import html
from pathlib import Path
import shutil

from app.api.semantic_bundle_questions import build_semantic_bundle_questions
from app.artifacts.semantic_bundle import SEMANTIC_BUNDLE_FILES
from app.models.artifacts import LLMContextPackage
from app.models.questionnaire import QuestionnaireBundle
from app.models.semantic import SemanticSourceModel
from app.models.technical import SourceTechnicalMetadata
from app.utils.files import ensure_dir
from app.utils.serialization import read_json, write_json

CHATBOT_PACKAGE_VERSION = 1
CHATBOT_PACKAGE_DIRNAME = "chatbot_package"


def _normalize_name(value: str) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


def _copy_file_if_exists(source: Path, destination: Path) -> None:
    if source.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def _copy_tree_if_exists(source: Path, destination: Path) -> None:
    if not source.exists():
        return
    shutil.copytree(source, destination, dirs_exist_ok=True)


def _dedupe_strings(values: list[str], limit: int | None = None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = str(value or "").strip()
        lowered = cleaned.lower()
        if not cleaned or lowered in seen:
            continue
        seen.add(lowered)
        out.append(cleaned)
        if limit is not None and len(out) >= limit:
            break
    return out


class ChatbotPackageExporter:
    def export(
        self,
        *,
        semantic: SemanticSourceModel,
        technical: SourceTechnicalMetadata,
        questionnaire: QuestionnaireBundle | None,
        context_package: LLMContextPackage,
        source_output_dir: Path,
        semantic_bundle_dir: Path,
        tag_bundle_dir: Path | None = None,
        domain_groups: dict[str, list[str]] | None = None,
        domain_name: str | None = None,
    ) -> Path:
        domain = _normalize_name(domain_name or semantic.domain or semantic.source_name)
        package_dir = source_output_dir / CHATBOT_PACKAGE_DIRNAME
        visuals_dir = package_dir / "visuals"
        questions_dir = package_dir / "questions"
        runtime_dir = package_dir / "runtime"
        reference_dir = package_dir / "reference"
        semantic_copy_dir = package_dir / "semantic_bundle"
        tag_copy_root = package_dir / "tag_bundle"

        ensure_dir(visuals_dir)
        ensure_dir(questions_dir)
        ensure_dir(runtime_dir)
        ensure_dir(reference_dir)
        ensure_dir(semantic_copy_dir)
        ensure_dir(tag_copy_root)

        bundle = self._load_bundle(semantic_bundle_dir)
        sections = build_semantic_bundle_questions(bundle)
        question_payload = {
            "source_name": semantic.source_name,
            "domain_name": domain,
            "sections": sections,
        }
        write_json(questions_dir / "semantic_bundle_questions.json", question_payload)
        if questionnaire is not None:
            write_json(questions_dir / "questionnaire.json", questionnaire)

        write_json(runtime_dir / "llm_context_package.json", context_package)
        if domain_groups:
            write_json(
                runtime_dir / "domain_groups.json",
                {
                    "source_name": semantic.source_name,
                    "groups": domain_groups,
                },
            )

        _copy_file_if_exists(source_output_dir / "technical_metadata.json", reference_dir / "technical_metadata.json")
        _copy_file_if_exists(source_output_dir / "normalized_metadata.json", reference_dir / "normalized_metadata.json")
        _copy_file_if_exists(source_output_dir / "semantic_model.json", reference_dir / "semantic_model.json")
        _copy_file_if_exists(source_output_dir / "llm_context_package.json", reference_dir / "llm_context_package.json")
        _copy_file_if_exists(source_output_dir / "questionnaire.json", reference_dir / "questionnaire.json")
        _copy_file_if_exists(source_output_dir / "domain_groups.json", reference_dir / "domain_groups.json")
        _copy_tree_if_exists(source_output_dir / "artifacts", reference_dir / "artifacts")
        _copy_tree_if_exists(semantic_bundle_dir, semantic_copy_dir)

        tag_relative_dir = ""
        if tag_bundle_dir and tag_bundle_dir.exists():
            tag_target_dir = tag_copy_root / tag_bundle_dir.name
            _copy_tree_if_exists(tag_bundle_dir, tag_target_dir)
            tag_relative_dir = str(tag_target_dir.relative_to(package_dir))

        generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        question_count = sum(len(section.get("questions") or []) for section in sections)
        table_count = sum(len(schema.tables) for schema in technical.schemas)
        db_type = getattr(technical.db_type, "value", technical.db_type)
        (package_dir / "README.md").write_text(
            self._readme_text(
                source_name=semantic.source_name,
                domain=domain,
                question_count=question_count,
                tag_relative_dir=tag_relative_dir,
            ),
            encoding="utf-8",
        )
        (visuals_dir / "overview.html").write_text(
            self._overview_html(
                semantic=semantic,
                technical=technical,
                sections=sections,
                context_package=context_package,
                domain_groups=domain_groups or {},
                questionnaire=questionnaire,
                tag_relative_dir=tag_relative_dir,
            ),
            encoding="utf-8",
        )
        inventory = self._inventory(package_dir)
        manifest = {
            "package_type": "chatbot_onboarding_package",
            "version": CHATBOT_PACKAGE_VERSION,
            "generated_at": generated_at,
            "source_name": semantic.source_name,
            "domain_name": domain,
            "summary": {
                "db_type": str(db_type),
                "database_name": technical.database_name,
                "table_count": table_count,
                "key_entity_count": len(semantic.key_entities),
                "question_count": question_count,
                "domain_group_count": len(domain_groups or {}),
                "review_mode": semantic.review_mode.value,
                "review_debt_count": len(semantic.review_debt),
                "publish_blocker_count": sum(1 for item in semantic.review_debt if item.publish_blocker),
            },
            "entrypoints": {
                "visual_summary": "visuals/overview.html",
                "semantic_bundle_questions": "questions/semantic_bundle_questions.json",
                "questionnaire": "questions/questionnaire.json" if questionnaire is not None else "",
                "llm_context": "runtime/llm_context_package.json",
                "domain_groups": "runtime/domain_groups.json" if domain_groups else "",
                "semantic_bundle": "semantic_bundle",
                "tag_bundle": tag_relative_dir,
            },
            "next_steps": [
                "Review visuals/overview.html and questions/semantic_bundle_questions.json with a business user.",
                "Update semantic_bundle/*.json or answer the questionnaire gaps before publishing.",
                "Copy the reviewed semantic_bundle into TAG-Implementation/app/domains/<domain>/semantic_bundle/ or use the publish API.",
                "Merge the reviewed tag_bundle overlay files into the target TAG domain before runtime testing.",
                "Reindex the TAG semantic store after publish so the chatbot uses the reviewed metadata.",
            ],
            "inventory": inventory,
        }
        write_json(package_dir / "manifest.json", manifest)
        manifest["inventory"] = self._inventory(package_dir)
        write_json(package_dir / "manifest.json", manifest)
        return package_dir

    def _load_bundle(self, semantic_bundle_dir: Path) -> dict[str, dict]:
        bundle: dict[str, dict] = {}
        for filename in (*SEMANTIC_BUNDLE_FILES, "bundle_manifest.json"):
            path = semantic_bundle_dir / filename
            if path.exists():
                payload = read_json(path)
                bundle[filename] = dict(payload) if isinstance(payload, dict) else {}
        return bundle

    def _inventory(self, package_dir: Path) -> list[str]:
        return [
            str(path.relative_to(package_dir))
            for path in sorted(package_dir.rglob("*"))
            if path.is_file()
        ]

    def _readme_text(
        self,
        *,
        source_name: str,
        domain: str,
        question_count: int,
        tag_relative_dir: str,
    ) -> str:
        tag_line = f"- `{tag_relative_dir}/` contains the TAG overlay bundle.\n" if tag_relative_dir else ""
        return (
            f"# Chatbot Package: {source_name}\n\n"
            "This folder collects the artifacts needed to review and activate a database-backed chatbot domain.\n\n"
            "## What is inside\n\n"
            "- `visuals/overview.html` is the human-friendly review summary.\n"
            f"- `questions/semantic_bundle_questions.json` contains {question_count} schema-grounded questions for the reviewer.\n"
            "- `runtime/llm_context_package.json` is the compact context package for LLM grounding.\n"
            "- `semantic_bundle/` is the reviewed retrieval bundle to publish into TAG.\n"
            f"{tag_line}"
            "- `reference/` keeps the raw OpenMetaData outputs for traceability.\n\n"
            "## Recommended flow\n\n"
            "1. Review the overview HTML with the business user.\n"
            "2. Answer the schema-grounded questions.\n"
            "3. Finalize the semantic bundle and TAG overlay.\n"
            f"4. Publish into `TAG-Implementation/app/domains/{domain}/` and reindex the runtime.\n"
        )

    def _overview_html(
        self,
        *,
        semantic: SemanticSourceModel,
        technical: SourceTechnicalMetadata,
        sections: list[dict],
        context_package: LLMContextPackage,
        domain_groups: dict[str, list[str]],
        questionnaire: QuestionnaireBundle | None,
        tag_relative_dir: str,
    ) -> str:
        source_name = html.escape(semantic.source_name)
        domain = html.escape(str(semantic.domain or semantic.source_name))
        description = html.escape(str(semantic.description or "No domain description available."))
        table_count = sum(len(schema.tables) for schema in technical.schemas)
        selected_count = sum(1 for table in semantic.tables if table.selected)
        review_count = sum(1 for table in semantic.tables if table.needs_review)
        review_debt_count = len(semantic.review_debt)
        publish_blocker_count = sum(1 for item in semantic.review_debt if item.publish_blocker)
        question_count = sum(len(section.get("questions") or []) for section in sections)
        db_type = html.escape(str(getattr(technical.db_type, "value", technical.db_type)))
        key_entities = self._render_tag_list(semantic.key_entities[:10], fallback="No key entities inferred.")
        matched_tables = self._render_tag_list(context_package.matched_tables[:12], fallback="No matched tables.")
        safe_joins = self._render_list(context_package.safe_joins[:10], fallback="No safe joins captured yet.")
        top_questions = self._render_question_sections(sections[:4])
        grouped_tables = self._render_domain_groups(domain_groups)
        questionnaire_items = self._render_list(
            [question.question for question in (questionnaire.questions[:10] if questionnaire else [])],
            fallback="No raw questionnaire items.",
        )
        tag_bundle_link = (
            f'<a href="../{html.escape(tag_relative_dir)}/bundle_manifest.json">Open TAG overlay bundle</a>'
            if tag_relative_dir
            else "<span>No TAG overlay bundle exported.</span>"
        )

        return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{source_name} Chatbot Package</title>
    <style>
      :root {{
        color-scheme: light;
        --bg: #f5f1e8;
        --panel: #fffdf8;
        --ink: #1f1a14;
        --muted: #6f655b;
        --line: #d7cfc2;
        --accent: #125b50;
        --accent-soft: #d8ece8;
        --warning: #8f4b1d;
      }}
      * {{ box-sizing: border-box; }}
      body {{
        margin: 0;
        font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
        background:
          radial-gradient(circle at top left, rgba(18, 91, 80, 0.12), transparent 30%),
          linear-gradient(180deg, #f8f5ed 0%, var(--bg) 100%);
        color: var(--ink);
      }}
      main {{
        width: min(1200px, calc(100vw - 32px));
        margin: 0 auto;
        padding: 32px 0 64px;
      }}
      .hero {{
        background: linear-gradient(135deg, rgba(18, 91, 80, 0.08), rgba(255, 253, 248, 0.95));
        border: 1px solid var(--line);
        border-radius: 24px;
        padding: 28px;
        box-shadow: 0 18px 50px rgba(31, 26, 20, 0.08);
      }}
      .eyebrow {{
        margin: 0 0 10px;
        color: var(--accent);
        font-size: 0.8rem;
        font-weight: 700;
        letter-spacing: 0.08em;
        text-transform: uppercase;
      }}
      h1, h2, h3 {{
        font-family: "Space Grotesk", "Segoe UI", sans-serif;
        margin: 0 0 12px;
      }}
      h1 {{ font-size: clamp(2rem, 4vw, 3rem); }}
      p {{ margin: 0; line-height: 1.6; }}
      .lede {{
        max-width: 75ch;
        color: var(--muted);
      }}
      .summary-grid,
      .content-grid {{
        display: grid;
        gap: 16px;
        margin-top: 20px;
      }}
      .summary-grid {{
        grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
      }}
      .content-grid {{
        grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      }}
      .card {{
        background: var(--panel);
        border: 1px solid var(--line);
        border-radius: 20px;
        padding: 20px;
        box-shadow: 0 12px 30px rgba(31, 26, 20, 0.06);
      }}
      .stat {{
        font-size: 1.9rem;
        font-weight: 700;
      }}
      .muted {{
        color: var(--muted);
      }}
      .pill-list {{
        display: flex;
        flex-wrap: wrap;
        gap: 10px;
      }}
      .pill {{
        padding: 8px 12px;
        border-radius: 999px;
        background: var(--accent-soft);
        color: var(--accent);
        font-weight: 600;
      }}
      ul {{
        margin: 12px 0 0;
        padding-left: 18px;
      }}
      li + li {{
        margin-top: 8px;
      }}
      .question-block + .question-block {{
        margin-top: 18px;
        padding-top: 18px;
        border-top: 1px solid var(--line);
      }}
      .artifact-links {{
        display: flex;
        flex-wrap: wrap;
        gap: 10px;
        margin-top: 12px;
      }}
      a {{
        color: var(--accent);
        font-weight: 600;
        text-decoration: none;
      }}
      a:hover {{
        text-decoration: underline;
      }}
      .warning {{
        color: var(--warning);
        font-weight: 600;
      }}
      @media (max-width: 720px) {{
        main {{
          width: min(100vw - 20px, 100%);
          padding-top: 20px;
        }}
        .hero,
        .card {{
          border-radius: 18px;
          padding: 18px;
        }}
      }}
    </style>
  </head>
  <body>
    <main>
      <section class="hero">
        <p class="eyebrow">Chatbot Onboarding Package</p>
        <h1>{source_name}</h1>
        <p class="lede">{description}</p>
        <div class="summary-grid">
          <article class="card">
            <p class="muted">Domain</p>
            <div class="stat">{domain}</div>
          </article>
          <article class="card">
            <p class="muted">Tables</p>
            <div class="stat">{table_count}</div>
          </article>
          <article class="card">
            <p class="muted">Selected</p>
            <div class="stat">{selected_count}</div>
          </article>
          <article class="card">
            <p class="muted">Needs Review</p>
            <div class="stat">{review_count}</div>
          </article>
          <article class="card">
            <p class="muted">Review Debt</p>
            <div class="stat">{review_debt_count}</div>
          </article>
          <article class="card">
            <p class="muted">Publish Blockers</p>
            <div class="stat">{publish_blocker_count}</div>
          </article>
          <article class="card">
            <p class="muted">DB Type</p>
            <div class="stat">{db_type}</div>
          </article>
          <article class="card">
            <p class="muted">Review Questions</p>
            <div class="stat">{question_count}</div>
          </article>
        </div>
      </section>

      <section class="content-grid">
        <article class="card">
          <h2>Key Entities</h2>
          <div class="pill-list">{key_entities}</div>
        </article>
        <article class="card">
          <h2>LLM Context</h2>
          <p class="muted">Tables already prioritized for grounding.</p>
          <div class="pill-list">{matched_tables}</div>
        </article>
        <article class="card">
          <h2>Safe Joins</h2>
          {safe_joins}
        </article>
        <article class="card">
          <h2>Artifacts</h2>
          <p class="muted">Use these entry points to review and publish the package.</p>
          <div class="artifact-links">
            <a href="../manifest.json">Open package manifest</a>
            <a href="../questions/semantic_bundle_questions.json">Open review questions</a>
            <a href="../runtime/llm_context_package.json">Open LLM context</a>
            <a href="../semantic_bundle/bundle_manifest.json">Open semantic bundle</a>
            {tag_bundle_link}
          </div>
        </article>
      </section>

      <section class="content-grid">
        <article class="card">
          <h2>Grouped Tables</h2>
          {grouped_tables}
        </article>
        <article class="card">
          <h2>Questions To Ask The User</h2>
          {top_questions}
        </article>
      </section>

      <section class="content-grid">
        <article class="card">
          <h2>Raw Questionnaire</h2>
          {questionnaire_items}
        </article>
        <article class="card">
          <h2>Next Steps</h2>
          <ul>
            <li>Review the questions with the business owner and correct weak table meanings or joins.</li>
            <li>Finalize the semantic bundle before publishing it into the TAG domain folder.</li>
            <li>Merge the TAG overlay bundle carefully. <span class="warning">Do not overwrite manual domain rules blindly.</span></li>
            <li>Reindex TAG after publish so the chatbot starts using the reviewed metadata.</li>
          </ul>
        </article>
      </section>
    </main>
  </body>
</html>
"""

    def _render_tag_list(self, values: list[str], fallback: str) -> str:
        items = _dedupe_strings(values)
        if not items:
            return f'<span class="muted">{html.escape(fallback)}</span>'
        return "".join(f'<span class="pill">{html.escape(item)}</span>' for item in items)

    def _render_list(self, values: list[str], fallback: str) -> str:
        items = _dedupe_strings(values)
        if not items:
            return f'<p class="muted">{html.escape(fallback)}</p>'
        rendered = "".join(f"<li>{html.escape(item)}</li>" for item in items)
        return f"<ul>{rendered}</ul>"

    def _render_domain_groups(self, domain_groups: dict[str, list[str]]) -> str:
        if not domain_groups:
            return '<p class="muted">No domain groups captured yet.</p>'
        blocks: list[str] = []
        for label, tables in domain_groups.items():
            group_tags = self._render_tag_list(list(tables), fallback="No tables")
            blocks.append(
                f'<div class="question-block"><h3>{html.escape(label)}</h3><div class="pill-list">{group_tags}</div></div>'
            )
        return "".join(blocks)

    def _render_question_sections(self, sections: list[dict]) -> str:
        if not sections:
            return '<p class="muted">No semantic review questions generated.</p>'
        blocks: list[str] = []
        for section in sections:
            title = html.escape(str(section.get("title") or "Review"))
            description = html.escape(str(section.get("description") or ""))
            questions = [
                html.escape(str(question.get("label") or ""))
                for question in list(section.get("questions") or [])[:5]
                if str(question.get("label") or "").strip()
            ]
            question_list = self._render_list(questions, fallback="No questions in this section.")
            blocks.append(
                f'<div class="question-block"><h3>{title}</h3><p class="muted">{description}</p>{question_list}</div>'
            )
        return "".join(blocks)
