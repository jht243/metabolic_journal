"""Automated SEO audit engine.

Crawls the Flask app through its test client, extracts SEO signals with a
single-pass HTML parser, and returns a structured report for CLI, CI, and
daily pipeline use. The crawler is intentionally local-only: no HTTP server,
no network calls, and no external parser dependency.
"""
from __future__ import annotations

import json
import logging
import re
from collections import defaultdict, deque
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_TITLE_MIN = 20
_TITLE_MAX = 70
_DESC_MIN = 50
_DESC_MAX = 160
_SKIP_EXTENSIONS = frozenset(
    (
        ".pdf",
        ".xml",
        ".txt",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".svg",
        ".ico",
        ".css",
        ".js",
        ".woff",
        ".woff2",
        ".ttf",
        ".eot",
        ".map",
        ".webp",
        ".avif",
        ".mp4",
        ".webm",
    )
)


@dataclass
class Finding:
    """A single audit finding."""

    path: str
    severity: str
    category: str
    message: str

    def __str__(self) -> str:
        return f"[{self.severity.upper():7s}] {self.category:18s} {self.path}  {self.message}"

    def to_dict(self) -> dict[str, str]:
        return {
            "path": self.path,
            "severity": self.severity,
            "category": self.category,
            "message": self.message,
        }


@dataclass
class PageAudit:
    """SEO signals and findings for one crawled page."""

    path: str
    status_code: int
    title: str = ""
    title_length: int = 0
    meta_description: str = ""
    meta_description_length: int = 0
    canonical: str = ""
    robots: str = ""
    og_title: str = ""
    og_description: str = ""
    og_image: str = ""
    h1_count: int = 0
    h1_text: str = ""
    h1_texts: list[str] = field(default_factory=list)
    heading_levels: list[int] = field(default_factory=list)
    jsonld_count: int = 0
    jsonld_types: list[str] = field(default_factory=list)
    internal_links: list[tuple[str, str]] = field(default_factory=list)
    body_word_count: int = 0
    has_cluster_nav: bool = False
    findings: list[Finding] = field(default_factory=list)

    @property
    def word_count(self) -> int:
        return self.body_word_count

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "status_code": self.status_code,
            "title": self.title,
            "title_length": self.title_length,
            "meta_description": self.meta_description,
            "meta_description_length": self.meta_description_length,
            "canonical": self.canonical,
            "robots": self.robots,
            "og_title": self.og_title,
            "og_description": self.og_description,
            "og_image": self.og_image,
            "h1_count": self.h1_count,
            "h1_texts": self.h1_texts,
            "heading_levels": self.heading_levels,
            "jsonld_count": self.jsonld_count,
            "jsonld_types": self.jsonld_types,
            "internal_link_count": len(self.internal_links),
            "body_word_count": self.body_word_count,
            "has_cluster_nav": self.has_cluster_nav,
            "findings": [f.to_dict() for f in self.findings],
        }


@dataclass
class AuditReport:
    """Full SEO audit report."""

    pages_crawled: int = 0
    pages_ok: int = 0
    page_audits: list[PageAudit] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "error"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "warning"]

    @property
    def info(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "info"]

    def summary(self) -> str:
        lines = [
            f"SEO Audit: {self.pages_crawled} pages crawled, {self.pages_ok} clean",
            f"  Errors:   {len(self.errors)}",
            f"  Warnings: {len(self.warnings)}",
            f"  Info:     {len(self.info)}",
        ]
        if self.errors:
            lines.extend(["", "Errors:"])
            lines.extend(f"  {f}" for f in self.errors[:20])
        if self.warnings:
            lines.extend(["", "Warnings:"])
            lines.extend(f"  {f}" for f in self.warnings[:30])
            remaining = len(self.warnings) - 30
            if remaining > 0:
                lines.append(f"  ... and {remaining} more warnings")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "pages_crawled": self.pages_crawled,
            "pages_ok": self.pages_ok,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "info_count": len(self.info),
            "findings": [f.to_dict() for f in self.findings],
            "page_audits": [p.to_dict() for p in self.page_audits],
        }


class _SEOParser(HTMLParser):
    """Single-pass parser for SEO-relevant HTML signals."""

    def __init__(self) -> None:
        super().__init__()
        self.title = ""
        self.meta_description = ""
        self.canonical = ""
        self.robots = ""
        self.og_title = ""
        self.og_description = ""
        self.og_image = ""
        self.h1_texts: list[str] = []
        self.heading_levels: list[int] = []
        self.jsonld_blocks: list[Any] = []
        self.internal_links: list[tuple[str, str]] = []
        self.has_cluster_nav = False

        self._in_title = False
        self._title_parts: list[str] = []
        self._in_h1 = False
        self._h1_parts: list[str] = []
        self._in_jsonld = False
        self._jsonld_parts: list[str] = []
        self._in_a = False
        self._a_href = ""
        self._a_parts: list[str] = []
        self._in_body = False
        self._body_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attr = {k.lower(): (v or "") for k, v in attrs}

        if tag == "title":
            self._in_title = True
            self._title_parts = []
        elif tag == "meta":
            name = attr.get("name", "").lower()
            prop = attr.get("property", "").lower()
            content = attr.get("content", "")
            if name == "description":
                self.meta_description = content
            elif name == "robots":
                self.robots = content
            elif prop == "og:title":
                self.og_title = content
            elif prop == "og:description":
                self.og_description = content
            elif prop == "og:image":
                self.og_image = content
        elif tag == "link":
            rel = attr.get("rel", "").lower()
            if rel == "canonical":
                self.canonical = attr.get("href", "")
        elif tag == "script":
            if attr.get("type", "").lower() == "application/ld+json":
                self._in_jsonld = True
                self._jsonld_parts = []
        elif tag == "body":
            self._in_body = True
        elif tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            level = int(tag[1])
            self.heading_levels.append(level)
            if tag == "h1":
                self._in_h1 = True
                self._h1_parts = []
        elif tag == "a":
            href = attr.get("href", "")
            if href:
                self._in_a = True
                self._a_href = href
                self._a_parts = []
        elif tag in {"nav", "aside", "section", "div"}:
            cls = attr.get("class", "")
            if "cluster-nav" in cls or "cluster_nav" in cls:
                self.has_cluster_nav = True

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "title" and self._in_title:
            self._in_title = False
            self.title = " ".join("".join(self._title_parts).split())
        elif tag == "h1" and self._in_h1:
            self._in_h1 = False
            h1 = " ".join("".join(self._h1_parts).split())
            if h1:
                self.h1_texts.append(h1)
        elif tag == "script" and self._in_jsonld:
            self._in_jsonld = False
            raw = "".join(self._jsonld_parts).strip()
            if raw:
                try:
                    self.jsonld_blocks.append(json.loads(raw))
                except json.JSONDecodeError:
                    pass
        elif tag == "a" and self._in_a:
            self._in_a = False
            anchor = " ".join("".join(self._a_parts).split())
            self.internal_links.append((self._a_href, anchor))
            self._a_href = ""
            self._a_parts = []
        elif tag == "body":
            self._in_body = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_parts.append(data)
        if self._in_h1:
            self._h1_parts.append(data)
        if self._in_jsonld:
            self._jsonld_parts.append(data)
        if self._in_a:
            self._a_parts.append(data)
        if self._in_body and data.strip():
            self._body_parts.append(data.strip())

    @property
    def body_word_count(self) -> int:
        text = " ".join(self._body_parts)
        return len(re.findall(r"\b[\w'-]+\b", text))


def _extract_jsonld_types(blocks: list[Any]) -> list[str]:
    types: list[str] = []

    def visit(obj: Any) -> None:
        if isinstance(obj, dict):
            value = obj.get("@type")
            if isinstance(value, list):
                types.extend(str(v) for v in value if v)
            elif value:
                types.append(str(value))
            graph = obj.get("@graph")
            if isinstance(graph, list):
                for item in graph:
                    visit(item)
        elif isinstance(obj, list):
            for item in obj:
                visit(item)

    for block in blocks:
        visit(block)
    return types


def _add(page: PageAudit, severity: str, category: str, message: str) -> None:
    page.findings.append(Finding(page.path, severity, category, message))


def _check_page(path: str, parser: _SEOParser, status_code: int) -> PageAudit:
    page = PageAudit(
        path=path,
        status_code=status_code,
        title=parser.title,
        title_length=len(parser.title),
        meta_description=parser.meta_description,
        meta_description_length=len(parser.meta_description),
        canonical=parser.canonical,
        robots=parser.robots,
        og_title=parser.og_title,
        og_description=parser.og_description,
        og_image=parser.og_image,
        h1_count=len(parser.h1_texts),
        h1_text=parser.h1_texts[0] if parser.h1_texts else "",
        h1_texts=parser.h1_texts,
        heading_levels=parser.heading_levels,
        jsonld_count=len(parser.jsonld_blocks),
        jsonld_types=_extract_jsonld_types(parser.jsonld_blocks),
        internal_links=parser.internal_links,
        body_word_count=parser.body_word_count,
        has_cluster_nav=parser.has_cluster_nav,
    )

    if status_code != 200:
        _add(page, "error", "http", f"HTTP {status_code}")
        return page

    if not page.title:
        _add(page, "error", "meta", "Missing <title> tag")
    elif len(page.title) < _TITLE_MIN:
        _add(page, "warning", "meta", f"Title too short ({len(page.title)} chars, min {_TITLE_MIN})")
    elif len(page.title) > _TITLE_MAX:
        _add(page, "warning", "meta", f"Title too long ({len(page.title)} chars, max {_TITLE_MAX})")

    if not page.meta_description:
        _add(page, "warning", "meta", "Missing meta description")
    elif len(page.meta_description) < _DESC_MIN:
        _add(page, "warning", "meta", f"Meta description too short ({len(page.meta_description)} chars)")
    elif len(page.meta_description) > _DESC_MAX:
        _add(page, "warning", "meta", f"Meta description too long ({len(page.meta_description)} chars)")

    if not page.canonical:
        _add(page, "warning", "meta", "Missing canonical URL")
    if not page.og_title:
        _add(page, "warning", "meta", "Missing og:title")
    if not page.og_image:
        _add(page, "warning", "meta", "Missing og:image")

    if page.h1_count == 0:
        _add(page, "error", "heading", "No H1 tag found")
    elif page.h1_count > 1:
        _add(page, "warning", "heading", f"Multiple H1 tags ({page.h1_count})")

    for previous, current in zip(page.heading_levels, page.heading_levels[1:]):
        if current > previous + 1:
            _add(page, "warning", "heading", f"Skipped heading level: H{previous} -> H{current}")
            break

    if page.jsonld_count == 0:
        _add(page, "warning", "structured_data", "No JSON-LD structured data")

    if page.body_word_count < 100:
        _add(page, "info", "content", f"Thin content ({page.body_word_count} words)")

    return page


def _normalize_path(href: str, *, allowed_hosts: set[str]) -> str | None:
    href = (href or "").strip()
    if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
        return None
    parsed = urlparse(href)
    if parsed.scheme and parsed.scheme not in {"http", "https"}:
        return None
    if parsed.netloc and parsed.netloc not in allowed_hosts:
        return None
    path = parsed.path or "/"
    if not path.startswith("/"):
        return None
    lower = path.lower()
    if any(lower.endswith(ext) for ext in _SKIP_EXTENSIONS):
        return None
    if lower.startswith(("/static/", "/api/", "/admin", "/webhooks/", "/health")):
        return None
    return path.rstrip("/") or "/"


def _seed_paths() -> list[str]:
    seeds = {
        "/",
        "/guides",
        "/programs",
        "/assessment",
        "/pricing",
        "/about",
        "/results",
        "/faq",
        "/doctors",
        "/briefing",
        "/tools",
    }
    try:
        from src.seo.cluster_topology import CLUSTERS

        for cluster in CLUSTERS.values():
            for path in cluster.all_paths():
                seeds.add(path)
    except Exception as exc:
        logger.warning("Could not load cluster topology seeds: %s", exc)
    return sorted(seeds)


def _sitemap_paths(client: Any) -> set[str]:
    paths: set[str] = set()
    for sitemap in ("/sitemap-primary.xml", "/sitemap-content.xml", "/sitemap-tools.xml"):
        try:
            resp = client.get(sitemap)
        except Exception as exc:
            logger.warning("Could not fetch %s during audit: %s", sitemap, exc)
            continue
        if resp.status_code != 200:
            continue
        text = resp.get_data(as_text=True)
        for match in re.finditer(r"<loc>https?://[^<]+?(/[^<]*)</loc>", text):
            path = match.group(1).split("?", 1)[0].split("#", 1)[0]
            if not any(path.lower().endswith(ext) for ext in _SKIP_EXTENSIONS):
                paths.add(path.rstrip("/") or "/")
    return paths


def _cross_page_findings(
    page_audits: list[PageAudit],
    *,
    crawled_paths: set[str],
    inbound_links: dict[str, int],
    sitemap_paths: set[str],
) -> list[Finding]:
    findings: list[Finding] = []
    audits_by_path = {page.path.rstrip("/") or "/": page for page in page_audits}

    try:
        from src.seo.cluster_topology import CLUSTERS, cluster_for

        for key, cluster in CLUSTERS.items():
            for path in cluster.all_paths():
                norm = path.rstrip("/") or "/"
                if norm not in crawled_paths:
                    findings.append(
                        Finding(norm, "warning", "cluster", f"Cluster '{key}' member not reached during crawl")
                    )
                    continue
                page = audits_by_path.get(norm)
                if page and cluster_for(norm) and not page.has_cluster_nav:
                    findings.append(
                        Finding(norm, "warning", "cluster", f"Cluster '{key}' member missing cluster nav block")
                    )
    except Exception as exc:
        findings.append(Finding("*", "error", "cluster", f"Could not import cluster_topology: {exc}"))

    for path in sorted(sitemap_paths):
        if path not in crawled_paths:
            findings.append(Finding(path, "warning", "sitemap", "In sitemap but not reached during crawl"))

    hub_pages = {
        "/",
        "/guides",
        "/programs",
        "/assessment",
        "/tools",
        "/briefing",
        "/metabolic-health",
        "/hormone-optimization",
        "/sleep-recovery",
        "/lab-testing",
    }
    for path in sorted(hub_pages):
        norm = path.rstrip("/") or "/"
        if norm in crawled_paths and inbound_links.get(norm, 0) < 2:
            findings.append(
                Finding(
                    norm,
                    "warning",
                    "link",
                    f"Hub page has only {inbound_links.get(norm, 0)} inbound internal links",
                )
            )

    return findings


def run_audit(
    *,
    max_pages: int = 200,
    follow_links: bool = True,
    seed_urls: list[str] | None = None,
) -> AuditReport:
    """Run the local SEO audit and return an AuditReport."""
    from src.config import settings
    from src.models import init_db

    init_db()

    from server import app

    site_host = urlparse(settings.canonical_site_url).netloc
    allowed_hosts = {host for host in {site_host, f"www.{site_host}", "localhost", "127.0.0.1"} if host}
    queue: deque[str] = deque(seed_urls or _seed_paths())
    queued = {p.rstrip("/") or "/" for p in queue}
    crawled: set[str] = set()
    inbound_links: dict[str, int] = defaultdict(int)
    page_audits: list[PageAudit] = []
    sitemap_paths: set[str] = set()

    with app.test_client() as client:
        sitemap_paths = _sitemap_paths(client)
        for path in sitemap_paths:
            if path not in queued:
                queue.append(path)
                queued.add(path)

        while queue and len(page_audits) < max_pages:
            path = queue.popleft()
            norm = path.rstrip("/") or "/"
            if norm in crawled:
                continue
            crawled.add(norm)

            try:
                resp = client.get(path, follow_redirects=False)
            except Exception as exc:
                page = PageAudit(path=norm, status_code=0)
                page.findings.append(Finding(norm, "error", "crawl", f"Failed to fetch: {exc}"))
                page_audits.append(page)
                continue

            if resp.status_code in {301, 302, 303, 307, 308}:
                target = _normalize_path(resp.headers.get("Location", ""), allowed_hosts=allowed_hosts)
                if target and target not in crawled and target not in queued:
                    queue.append(target)
                    queued.add(target)
                continue

            html = resp.get_data(as_text=True) if resp.status_code == 200 else ""
            parser = _SEOParser()
            if html:
                try:
                    parser.feed(html)
                except Exception as exc:
                    logger.warning("Parse error on %s: %s", norm, exc)

            page = _check_page(norm, parser, resp.status_code)
            page_audits.append(page)

            for href, anchor in page.internal_links:
                target = _normalize_path(href, allowed_hosts=allowed_hosts)
                if not target:
                    continue
                inbound_links[target] += 1
                if follow_links and target not in crawled and target not in queued:
                    queue.append(target)
                    queued.add(target)

    report = AuditReport(
        pages_crawled=len(page_audits),
        pages_ok=sum(1 for page in page_audits if page.status_code == 200 and not page.findings),
        page_audits=page_audits,
    )

    for page in page_audits:
        report.findings.extend(page.findings)

    report.findings.extend(
        _cross_page_findings(
            page_audits,
            crawled_paths=crawled,
            inbound_links=inbound_links,
            sitemap_paths=sitemap_paths,
        )
    )
    return report
