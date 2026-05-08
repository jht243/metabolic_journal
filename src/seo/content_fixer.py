"""SEO content auto-fixer.

Applies only the fixes that are safe to automate on LandingPage-backed
content pages: missing H1s and thin body copy. Tool and hub/index pages
that are not backed by LandingPage rows are ignored.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from html import unescape

import httpx
from openai import OpenAI

from src.config import settings
from src.models import LandingPage, SessionLocal, init_db
from src.seo.audit import AuditReport

logger = logging.getLogger(__name__)

_MAX_FIXES_PER_RUN = 5
_ANY_TAG_RE = re.compile(r"<[^>]+>")
_ALLOWED_TAGS_RE = re.compile(
    r"<\s*/?\s*(h1|h2|h3|h4|p|ul|ol|li|strong|em|b|i|blockquote|a|table|thead|tbody|tr|th|td)(\s+[^>]*)?\s*/?\s*>",
    re.IGNORECASE,
)


def _sanitize_body_html(html: str) -> str:
    """Keep only the conservative tag set used by generated landing pages."""
    if not html:
        return ""

    def replace(match: re.Match) -> str:
        tag = match.group(0)
        if _ALLOWED_TAGS_RE.fullmatch(tag):
            return tag
        return ""

    return _ANY_TAG_RE.sub(replace, html)


def _count_words(html: str) -> int:
    text = unescape(_ANY_TAG_RE.sub(" ", html or ""))
    return len(re.findall(r"\b[\w'-]+\b", text))


def _web_search(query: str, *, max_results: int = 5) -> list[dict[str, str]]:
    """Best-effort DuckDuckGo HTML search with no API key."""
    try:
        resp = httpx.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            headers={"User-Agent": "MetabolicJournal-SEOFixer/1.0"},
            timeout=10,
            follow_redirects=True,
        )
        if resp.status_code != 200:
            logger.warning("web_search: DuckDuckGo returned %d for %r", resp.status_code, query)
            return []

        results: list[dict[str, str]] = []
        for match in re.finditer(
            r'class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>.*?'
            r'class="result__snippet"[^>]*>(.*?)</(?:a|td|div)',
            resp.text,
            re.DOTALL,
        ):
            url = unescape(match.group(1))
            title = unescape(re.sub(r"<[^>]+>", "", match.group(2))).strip()
            snippet = unescape(re.sub(r"<[^>]+>", "", match.group(3))).strip()
            if title and snippet:
                results.append({"title": title, "snippet": snippet, "url": url})
            if len(results) >= max_results:
                break
        return results
    except Exception as exc:
        logger.warning("web_search failed for %r: %s", query, exc)
        return []


def _premium_call(client: OpenAI, *, system: str, user: str, max_tokens: int = 3000) -> tuple[str, dict]:
    """Call the configured premium model and return raw JSON plus usage."""
    model = settings.openai_premium_model
    is_reasoning_model = model.startswith(("gpt-5", "o1", "o3"))
    kwargs = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "response_format": {"type": "json_object"},
    }
    if is_reasoning_model:
        kwargs["max_completion_tokens"] = max_tokens
    else:
        kwargs["max_tokens"] = max_tokens
        kwargs["temperature"] = 0.35

    response = client.chat.completions.create(**kwargs)
    raw = response.choices[0].message.content or "{}"
    usage = getattr(response, "usage", None)
    input_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
    output_tokens = getattr(usage, "completion_tokens", 0) if usage else 0
    cost = (
        (input_tokens or 0) / 1_000_000 * settings.llm_premium_input_price_per_mtok
        + (output_tokens or 0) / 1_000_000 * settings.llm_premium_output_price_per_mtok
    )
    return raw, {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": round(cost, 4),
        "model": model,
    }


_SYSTEM_PROMPT = """You are a senior evidence-based health editor for The Metabolic Journal. You are fixing SEO issues on existing landing pages.

Write in plain English for patients and health-conscious readers. Be precise, clinically careful, and avoid diagnosis or treatment promises. Use the supplied web search snippets only as grounding context, and keep medical advice conservative.

Return one JSON object only. Use HTML limited to h1, h2, h3, p, ul, ol, li, strong, em, a, blockquote, and table tags."""


def _fix_missing_h1(client: OpenAI, page: LandingPage, search_results: list[dict[str, str]]) -> dict | None:
    search_context = "\n".join(f"- {r['title']}: {r['snippet']}" for r in search_results)
    if not search_context:
        search_context = "No search results available."

    prompt = f"""This LandingPage rendered without an H1. Generate a clear H1 and a short opening paragraph to prepend to the page body.

PAGE TITLE: {page.title}
PAGE SUMMARY: {page.summary or "(none)"}
PAGE PATH: {page.canonical_path}
PAGE TYPE: {page.page_type}
CURRENT WEB SEARCH RESULTS:
{search_context}

Return JSON with:
- h1: string, 35-80 chars, descriptive and matching the page topic
- body_prefix: string, HTML containing one <h1> and one short <p>"""

    try:
        raw, usage = _premium_call(client, system=_SYSTEM_PROMPT, user=prompt, max_tokens=700)
        data = json.loads(raw)
        return {
            "h1": str(data.get("h1", "")).strip(),
            "body_prefix": _sanitize_body_html(str(data.get("body_prefix", ""))),
            "usage": usage,
        }
    except Exception as exc:
        logger.warning("fix_missing_h1 failed for %s: %s", page.canonical_path, exc)
        return None


def _fix_thin_content(
    client: OpenAI,
    page: LandingPage,
    current_word_count: int,
    search_results: list[dict[str, str]],
) -> dict | None:
    search_context = "\n".join(f"- {r['title']}: {r['snippet']}" for r in search_results)
    if not search_context:
        search_context = "No search results available."

    prompt = f"""This LandingPage has thin content ({current_word_count} words). Expand the COMPLETE body to 400-600 words.

Keep any useful existing content, add practical sections grounded in the search results, and preserve a cautious medical tone.

PAGE TITLE: {page.title}
PAGE SUMMARY: {page.summary or "(none)"}
PAGE PATH: {page.canonical_path}
PAGE TYPE: {page.page_type}
CURRENT BODY:
{(page.body_html or "")[:2500]}

CURRENT WEB SEARCH RESULTS:
{search_context}

Return JSON with:
- body_html: string, complete expanded HTML body
- word_count: integer"""

    try:
        raw, usage = _premium_call(client, system=_SYSTEM_PROMPT, user=prompt, max_tokens=3200)
        data = json.loads(raw)
        body = _sanitize_body_html(str(data.get("body_html", "")))
        word_count = _count_words(body)
        if word_count < current_word_count:
            logger.warning(
                "fix_thin_content for %s produced fewer words (%d vs %d); skipping",
                page.canonical_path,
                word_count,
                current_word_count,
            )
            return None
        return {"body_html": body, "word_count": word_count, "usage": usage}
    except Exception as exc:
        logger.warning("fix_thin_content failed for %s: %s", page.canonical_path, exc)
        return None


def _find_landing_page(db, path: str) -> LandingPage | None:
    norm = "/" + path.lstrip("/").rstrip("/")
    return db.query(LandingPage).filter(LandingPage.canonical_path == norm).first()


def fix_content_issues(report: AuditReport, *, max_fixes: int = _MAX_FIXES_PER_RUN) -> dict:
    """Apply budget-capped fixes for LandingPage-backed audit findings."""
    if not settings.openai_api_key:
        return {"status": "skipped", "reason": "no OpenAI API key", "fixed": 0}

    missing_h1_paths: list[str] = []
    thin_content_paths: list[tuple[str, int]] = []

    for page in report.page_audits:
        if page.status_code != 200:
            continue
        for finding in page.findings:
            if finding.severity == "error" and finding.category == "heading" and "No H1" in finding.message:
                missing_h1_paths.append(page.path)
            if finding.category == "content" and "Thin content" in finding.message and page.body_word_count < 200:
                thin_content_paths.append((page.path, page.body_word_count))

    if not missing_h1_paths and not thin_content_paths:
        return {"status": "ok", "fixed": 0, "reason": "no fixable issues"}

    init_db()
    db = SessionLocal()
    client = OpenAI(api_key=settings.openai_api_key)
    fixed = 0
    skipped = 0
    total_cost = 0.0
    details: list[dict] = []

    try:
        for path in missing_h1_paths:
            if fixed >= max_fixes:
                break
            page = _find_landing_page(db, path)
            if page is None:
                skipped += 1
                continue

            query = f"metabolic health {page.title or page.page_key} latest evidence 2026"
            result = _fix_missing_h1(client, page, _web_search(query))
            if not result or not result.get("body_prefix"):
                skipped += 1
                continue

            page.body_html = result["body_prefix"] + "\n" + (page.body_html or "")
            page.word_count = _count_words(page.body_html)
            page.updated_at = datetime.utcnow()
            db.commit()

            cost = float(result["usage"]["cost_usd"])
            total_cost += cost
            fixed += 1
            details.append({"path": path, "fix": "missing_h1", "h1": result.get("h1", ""), "cost_usd": cost})

        for path, word_count in thin_content_paths:
            if fixed >= max_fixes:
                break
            page = _find_landing_page(db, path)
            if page is None or word_count >= 200:
                skipped += 1
                continue

            query = f"metabolic health {page.title or page.page_key} latest evidence 2026"
            result = _fix_thin_content(client, page, word_count, _web_search(query))
            if not result or not result.get("body_html"):
                skipped += 1
                continue

            page.body_html = result["body_html"]
            page.word_count = result["word_count"]
            page.updated_at = datetime.utcnow()
            db.commit()

            cost = float(result["usage"]["cost_usd"])
            total_cost += cost
            fixed += 1
            details.append(
                {
                    "path": path,
                    "fix": "thin_content",
                    "old_words": word_count,
                    "new_words": result["word_count"],
                    "cost_usd": cost,
                }
            )

        return {
            "status": "ok",
            "fixed": fixed,
            "skipped": skipped,
            "total_cost_usd": round(total_cost, 4),
            "details": details,
        }
    except Exception as exc:
        logger.exception("content fixer failed: %s", exc)
        try:
            db.rollback()
        except Exception:
            pass
        return {"status": "error", "error": str(exc), "fixed": fixed}
    finally:
        db.close()
