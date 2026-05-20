#!/usr/bin/env python3
"""Find competitor keyword gaps using Ahrefs API v3.

Compares Ahrefs organic keyword exports for competitor domains against
TARGET_KEYWORD_INVENTORY.md, then writes CSV, JSON, and Markdown reports.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INVENTORY = ROOT / "TARGET_KEYWORD_INVENTORY.md"
DEFAULT_OUTPUT_DIR = ROOT / "output" / "ahrefs"

DEFAULT_COMPETITORS = [
    "honehealth.com",
    "innerbody.com",
    "levelshealth.com",
    "everlywell.com",
    "insidetracker.com",
    "verywellhealth.com",
    "healthline.com",
    "medicalnewstoday.com",
]

TOPIC_TERMS = [
    "a1c",
    "aod",
    "apnea",
    "belly fat",
    "biomarker",
    "blood sugar",
    "blood test",
    "bone density",
    "bpc",
    "cbc",
    "cjc",
    "collagen",
    "cortisol",
    "crp",
    "dexa",
    "epithalon",
    "fatigue",
    "ferritin",
    "free testosterone",
    "glp",
    "glucose",
    "growth hormone",
    "hgh",
    "homa",
    "hormone",
    "hrv",
    "igf",
    "insulin",
    "ipamorelin",
    "iron",
    "lab result",
    "libido",
    "menopause",
    "metabolic",
    "mpv",
    "nad",
    "osteopenia",
    "osteoporosis",
    "peptide",
    "perimenopause",
    "semaglutide",
    "sermorelin",
    "shbg",
    "sleep",
    "tb 500",
    "tb-500",
    "tesamorelin",
    "testosterone",
    "thyroid",
    "tirzepatide",
    "vitamin d",
    "wbc",
    "weight loss",
]


def normalize_keyword(value: str) -> str:
    value = value.lower().replace("+", " plus ")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def parse_inventory(path: Path) -> tuple[set[str], dict[str, list[str]]]:
    tracked: set[str] = set()
    by_url: dict[str, list[str]] = defaultdict(list)
    row_re = re.compile(r"^\|\s*`(?P<url>[^`]+)`\s*\|\s*(?P<primary>[^|]+?)\s*\|\s*(?P<supporting>[^|]*)\|")
    for line in path.read_text(encoding="utf-8").splitlines():
        match = row_re.match(line)
        if not match:
            continue
        url = match.group("url").strip()
        terms = [match.group("primary").strip()]
        terms.extend(term.strip() for term in match.group("supporting").split(";") if term.strip())
        for term in terms:
            normalized = normalize_keyword(term)
            if normalized:
                tracked.add(normalized)
                by_url[url].append(term)
    return tracked, dict(by_url)


def topic_match(keyword: str) -> bool:
    normalized = normalize_keyword(keyword)
    return any(term in normalized for term in TOPIC_TERMS)


def get_number(row: dict[str, Any], *keys: str) -> int:
    for key in keys:
        value = row.get(key)
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return 0


def fetch_organic_keywords(
    *,
    api_key: str,
    target: str,
    report_date: str,
    country: str,
    mode: str,
    limit: int,
) -> list[dict[str, Any]]:
    params = {
        "target": target,
        "mode": mode,
        "country": country.lower(),
        "date": report_date,
        "limit": str(limit),
        "order_by": "volume:desc",
        "select": ",".join(
            [
                "keyword",
                "volume",
                "keyword_difficulty",
                "best_position",
                "best_position_url",
                "sum_traffic",
                "is_commercial",
                "is_transactional",
                "is_informational",
                "serp_features",
            ]
        ),
        "output": "json",
    }
    url = "https://api.ahrefs.com/v3/site-explorer/organic-keywords?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "User-Agent": "metabolic-journal-keyword-gap/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Ahrefs returned HTTP {exc.code} for {target}: {body[:500]}") from exc
    rows = payload.get("keywords")
    if not isinstance(rows, list):
        raise RuntimeError(f"Unexpected Ahrefs response for {target}: {payload}")
    return rows


def classify_gap(keyword: str, tracked: set[str]) -> str:
    normalized = normalize_keyword(keyword)
    if normalized in tracked:
        return "tracked"
    words = set(normalized.split())
    for existing in tracked:
        existing_words = set(existing.split())
        if len(words) >= 3 and len(existing_words) >= 3:
            overlap = len(words & existing_words) / max(len(words), len(existing_words))
            if overlap >= 0.75:
                return "near-match"
    return "gap"


def format_cpc_cents(value: Any) -> str:
    if value in (None, ""):
        return ""
    try:
        return f"{int(value) / 100:.2f}"
    except (TypeError, ValueError):
        return ""


def write_reports(
    *,
    rows: list[dict[str, Any]],
    raw_by_competitor: dict[str, list[dict[str, Any]]],
    tracked_count: int,
    args: argparse.Namespace,
) -> dict[str, Path]:
    DEFAULT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = date.today().isoformat()
    base = DEFAULT_OUTPUT_DIR / f"keyword-gaps-{stamp}"
    csv_path = base.with_suffix(".csv")
    json_path = base.with_suffix(".json")
    md_path = base.with_suffix(".md")

    fieldnames = [
        "keyword",
        "volume",
        "keyword_difficulty",
        "best_position",
        "competitor",
        "best_position_url",
        "sum_traffic",
        "is_commercial",
        "is_transactional",
        "is_informational",
        "serp_features",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})

    payload = {
        "metadata": {
            "generated_at": stamp,
            "inventory": str(args.inventory),
            "tracked_keyword_count": tracked_count,
            "competitors": args.competitors,
            "country": args.country,
            "date": args.date,
            "limit_per_competitor": args.limit,
            "topic_filtered": not args.no_topic_filter,
            "gap_count": len(rows),
        },
        "gaps": rows,
        "raw_counts": {domain: len(items) for domain, items in raw_by_competitor.items()},
    }
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = [
        "# Ahrefs Keyword Gap Report",
        "",
        f"Generated: {stamp}",
        f"Inventory keywords: {tracked_count}",
        f"Competitors: {', '.join(args.competitors)}",
        f"Country/date: {args.country.upper()} / {args.date}",
        f"Topic filter: {'off' if args.no_topic_filter else 'on'}",
        f"Total gaps: {len(rows)}",
        "",
        "## Top Gaps by Search Volume",
        "",
        "| Keyword | Volume | KD | Competitor | Position | URL | Intent |",
        "|---|---:|---:|---|---:|---|---|",
    ]
    for row in rows[:75]:
        intent = ", ".join(
            label
            for label, key in [
                ("commercial", "is_commercial"),
                ("transactional", "is_transactional"),
                ("informational", "is_informational"),
            ]
            if row.get(key)
        )
        lines.append(
            "| {keyword} | {volume} | {kd} | {competitor} | {position} | {url} | {intent} |".format(
                keyword=str(row.get("keyword", "")).replace("|", "\\|"),
                volume=row.get("volume", 0),
                kd=row.get("keyword_difficulty", ""),
                competitor=row.get("competitor", ""),
                position=row.get("best_position", ""),
                url=row.get("best_position_url", ""),
                intent=intent,
            )
        )

    lines.extend(["", "## Source Counts", ""])
    for competitor, items in raw_by_competitor.items():
        lines.append(f"- {competitor}: {len(items)} organic keyword rows pulled")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"csv": csv_path, "json": json_path, "markdown": md_path}


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Ahrefs competitor keyword gap analysis")
    p.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    p.add_argument("--competitors", default=",".join(DEFAULT_COMPETITORS))
    p.add_argument("--country", default="us")
    p.add_argument("--date", default=date.today().isoformat())
    p.add_argument("--limit", type=int, default=1000)
    p.add_argument("--mode", default="subdomains", choices=["exact", "prefix", "domain", "subdomains"])
    p.add_argument("--min-volume", type=int, default=100)
    p.add_argument("--max-kd", type=int, default=70)
    p.add_argument("--no-topic-filter", action="store_true")
    return p


def main() -> int:
    args = parser().parse_args()
    api_key = os.getenv("AHREFS_API_KEY", "").strip()
    if not api_key:
        print("AHREFS_API_KEY is required", file=sys.stderr)
        return 2
    args.competitors = [domain.strip() for domain in args.competitors.split(",") if domain.strip()]
    tracked, _ = parse_inventory(args.inventory)
    if not tracked:
        print(f"No tracked keywords found in {args.inventory}", file=sys.stderr)
        return 2

    raw_by_competitor: dict[str, list[dict[str, Any]]] = {}
    merged: dict[str, dict[str, Any]] = {}
    for competitor in args.competitors:
        print(f"Fetching {competitor}...")
        rows = fetch_organic_keywords(
            api_key=api_key,
            target=competitor,
            report_date=args.date,
            country=args.country,
            mode=args.mode,
            limit=args.limit,
        )
        raw_by_competitor[competitor] = rows
        for row in rows:
            keyword = str(row.get("keyword") or "").strip()
            if not keyword:
                continue
            if classify_gap(keyword, tracked) != "gap":
                continue
            if not args.no_topic_filter and not topic_match(keyword):
                continue
            volume = get_number(row, "volume", "volume_merged")
            kd = get_number(row, "keyword_difficulty", "keyword_difficulty_merged")
            if volume < args.min_volume:
                continue
            if kd and kd > args.max_kd:
                continue
            normalized = normalize_keyword(keyword)
            existing = merged.get(normalized)
            candidate = {
                "keyword": keyword,
                "volume": volume,
                "keyword_difficulty": kd,
                "best_position": get_number(row, "best_position"),
                "competitor": competitor,
                "best_position_url": row.get("best_position_url") or "",
                "sum_traffic": get_number(row, "sum_traffic", "sum_traffic_merged"),
                "is_commercial": bool(row.get("is_commercial")),
                "is_transactional": bool(row.get("is_transactional")),
                "is_informational": bool(row.get("is_informational")),
                "serp_features": ",".join(row.get("serp_features") or []),
            }
            if existing is None or candidate["volume"] > existing["volume"]:
                merged[normalized] = candidate
        time.sleep(0.3)

    gaps = sorted(
        merged.values(),
        key=lambda item: (int(item.get("volume") or 0), int(item.get("sum_traffic") or 0)),
        reverse=True,
    )
    paths = write_reports(rows=gaps, raw_by_competitor=raw_by_competitor, tracked_count=len(tracked), args=args)
    print(f"Found {len(gaps)} gaps")
    for kind, path in paths.items():
        print(f"{kind}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
