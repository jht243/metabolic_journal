#!/usr/bin/env python3
"""Run Semrush keyword research for the metabolic health optimization site.

Usage:
    python scripts/health_keyword_research.py
    python scripts/health_keyword_research.py --json
    python scripts/health_keyword_research.py --competitors levelshealth.com,parsleyhealth.com

Requires SEMRUSH_API_KEY env var (or set in .env).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.config import settings
from src.seo.semrush import SemrushClient, KeywordOpportunity, format_report

METABOLISM_SEEDS = [
    "insulin resistance",
    "weight loss resistance",
    "blood sugar crash",
    "belly fat",
    "slow metabolism",
    "glucose spikes",
    "fatigue after eating",
    "metabolic health",
    "GLP-1 plateau",
]

HORMONE_SEEDS = [
    "low testosterone",
    "hormone imbalance",
    "menopause weight gain",
    "perimenopause fatigue",
    "thyroid symptoms",
    "cortisol imbalance",
    "low libido",
    "brain fog hormones",
    "hormone testing",
]

RECOVERY_SEEDS = [
    "chronic fatigue",
    "waking up tired",
    "poor sleep quality",
    "sleep apnea symptoms",
    "fatigue despite sleep",
    "cortisol and sleep",
    "stress recovery",
    "low HRV",
    "afternoon energy crash",
]

BONE_DENSITY_SEEDS = [
    "bone density",
    "how to increase bone density",
    "osteopenia",
    "osteoporosis",
    "DEXA scan",
    "bone density test",
    "calcium rich foods",
    "weight bearing exercises",
    "bone health supplements",
    "T score bone density",
    "bone density after menopause",
    "can osteopenia be reversed",
]

ALL_SEEDS = METABOLISM_SEEDS + HORMONE_SEEDS + RECOVERY_SEEDS + BONE_DENSITY_SEEDS

DEFAULT_COMPETITORS = [
    "levelshealth.com",
    "parsleyhealth.com",
    "everlywell.com",
    "insidetracker.com",
    "honehealth.com",
]


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Semrush keyword research for metabolic health site")
    p.add_argument(
        "--competitors",
        default=",".join(DEFAULT_COMPETITORS),
        help="Comma-separated competitor domains for gap analysis",
    )
    p.add_argument("--limit", type=int, default=100, help="Max organic keywords per competitor")
    p.add_argument("--output", default="", help="Write report to this file")
    p.add_argument("--json", action="store_true", help="Also save raw JSON data")
    return p


def run_health_keyword_research(
    *,
    competitor_domains: list[str] | None = None,
    limit: int = 100,
) -> dict:
    """Run full keyword research across all health seed terms."""
    client = SemrushClient()
    results: dict = {
        "metadata": {
            "date": datetime.now().isoformat(),
            "seed_count": len(ALL_SEEDS),
            "categories": {
                "metabolism": METABOLISM_SEEDS,
                "hormones": HORMONE_SEEDS,
                "recovery": RECOVERY_SEEDS,
                "bone_density": BONE_DENSITY_SEEDS,
            },
        },
        "seed_overviews": {},
        "related": [],
        "questions": [],
        "serp_features": {},
        "competitor_organic": {},
        "competitor_gaps": [],
    }

    # 1. Batch keyword overview for all seeds
    print(f"\n[1/5] Fetching keyword overview for {len(ALL_SEEDS)} seed terms...")
    try:
        batches = [ALL_SEEDS[i:i+100] for i in range(0, len(ALL_SEEDS), 100)]
        all_overview = []
        for batch in batches:
            all_overview.extend(client.keyword_overview_batch(batch))
            time.sleep(0.5)
        for row in all_overview:
            kw = row.get("Keyword", "")
            if kw:
                results["seed_overviews"][kw.lower()] = row
        print(f"  Got metrics for {len(results['seed_overviews'])} seeds")
    except Exception as exc:
        print(f"  WARNING: Batch overview failed: {exc}")
        for seed in ALL_SEEDS:
            try:
                data = client.keyword_overview(seed)
                if data:
                    results["seed_overviews"][seed.lower()] = data[0]
                time.sleep(0.3)
            except Exception as e2:
                print(f"  Skipping '{seed}': {e2}")

    # 2. Related keywords + questions for each seed
    print(f"\n[2/5] Expanding related keywords and questions for each seed...")
    seen_related: set[str] = set()
    seen_questions: set[str] = set()

    for i, seed in enumerate(ALL_SEEDS):
        category = (
            "metabolism" if seed in METABOLISM_SEEDS
            else "hormones" if seed in HORMONE_SEEDS
            else "bone_density" if seed in BONE_DENSITY_SEEDS
            else "recovery"
        )
        print(f"  [{i+1}/{len(ALL_SEEDS)}] {seed} ({category})")

        try:
            related = client.related_keywords(seed, limit=50)
            for row in related:
                kw = row.get("Keyword", "").lower()
                if kw and kw not in seen_related:
                    seen_related.add(kw)
                    row["_seed"] = seed
                    row["_category"] = category
                    results["related"].append(row)
            time.sleep(0.3)
        except Exception as exc:
            print(f"    Related failed: {exc}")

        try:
            questions = client.phrase_questions(seed, limit=50)
            for row in questions:
                kw = row.get("Keyword", "").lower()
                if kw and kw not in seen_questions:
                    seen_questions.add(kw)
                    row["_seed"] = seed
                    row["_category"] = category
                    results["questions"].append(row)
            time.sleep(0.3)
        except Exception as exc:
            print(f"    Questions failed: {exc}")

    print(f"  Total unique related keywords: {len(results['related'])}")
    print(f"  Total unique question keywords: {len(results['questions'])}")

    # 3. SERP features for top seeds
    print(f"\n[3/5] Checking SERP features for seed terms...")
    try:
        serp_batch = client.keyword_overview_batch(ALL_SEEDS[:27])
        for row in serp_batch:
            kw = row.get("Keyword", "")
            results["serp_features"][kw.lower()] = {
                "keyword": kw,
                "volume": row.get("Search Volume", ""),
                "kd": row.get("Keyword Difficulty", ""),
                "cpc": row.get("CPC", ""),
                "intent": row.get("Intent", ""),
                "serp_features": row.get("SERP Features by Keyword", row.get("Number of Results", "")),
            }
    except Exception as exc:
        print(f"  SERP features batch failed: {exc}")

    # 4. Competitor organic keywords
    if competitor_domains:
        print(f"\n[4/5] Analyzing {len(competitor_domains)} competitors...")
        for comp in competitor_domains:
            print(f"  {comp}...")
            try:
                kws = client.domain_organic_keywords(comp, limit=limit, sort="tr_desc")
                results["competitor_organic"][comp] = kws
                print(f"    Found {len(kws)} keywords")
                time.sleep(0.5)
            except Exception as exc:
                print(f"    Failed: {exc}")
                results["competitor_organic"][comp] = []

        # 5. Competitor gap: keywords they rank for in health topics
        print(f"\n[5/5] Identifying competitor keyword gaps...")
        health_terms = {
            "metabolic", "metabolism", "insulin", "glucose", "blood sugar",
            "hormone", "testosterone", "estrogen", "thyroid", "cortisol",
            "menopause", "perimenopause", "sleep", "fatigue", "energy",
            "weight loss", "belly fat", "libido", "brain fog", "HRV",
        }
        for comp, kws in results["competitor_organic"].items():
            for row in kws:
                kw = row.get("Keyword", "").lower()
                if any(term in kw for term in health_terms):
                    row["_competitor"] = comp
                    results["competitor_gaps"].append(row)
        print(f"  Total health-relevant competitor keywords: {len(results['competitor_gaps'])}")
    else:
        print("\n[4/5] Skipping competitor analysis (no competitors specified)")
        print("[5/5] Skipping gap analysis")

    return results


def format_health_report(results: dict) -> str:
    """Format the health keyword research as a readable report."""
    lines: list[str] = []
    lines.append("=" * 80)
    lines.append("METABOLIC HEALTH KEYWORD RESEARCH — SEMRUSH REPORT")
    lines.append(f"Generated: {results['metadata']['date']}")
    lines.append("=" * 80)

    # Seed overview
    overviews = results.get("seed_overviews", {})
    if overviews:
        lines.append(f"\n{'─' * 80}")
        lines.append("SEED KEYWORD OVERVIEW")
        lines.append(f"{'─' * 80}")
        lines.append(f"  {'Keyword':<35} {'Vol':>8} {'KD':>4} {'CPC':>7} {'Comp':>6} {'Intent'}")
        lines.append("  " + "-" * 80)

        intent_map = {"0": "info", "1": "nav", "2": "comm", "3": "trans"}

        for category, seeds in results["metadata"]["categories"].items():
            lines.append(f"\n  ── {category.upper()} ──")
            for seed in seeds:
                row = overviews.get(seed.lower(), {})
                vol = row.get("Search Volume", "?")
                kd = row.get("Keyword Difficulty", "?")
                cpc = row.get("CPC", "?")
                comp = row.get("Competition", "?")
                intent_raw = str(row.get("Intent", "?"))
                intent = intent_map.get(intent_raw, intent_raw)
                lines.append(
                    f"  {seed:<35} {vol:>8} {kd:>4} {cpc:>7} {comp:>6} {intent}"
                )

    # Top related keywords by volume
    related = results.get("related", [])
    if related:
        sorted_related = sorted(
            related,
            key=lambda r: int(r.get("Search Volume", "0") or "0"),
            reverse=True,
        )
        lines.append(f"\n{'─' * 80}")
        lines.append(f"TOP RELATED KEYWORDS ({len(related)} unique)")
        lines.append(f"{'─' * 80}")
        lines.append(f"  {'Keyword':<45} {'Vol':>8} {'KD':>4} {'CPC':>7} {'Cat':<12} {'Intent'}")
        lines.append("  " + "-" * 95)
        for row in sorted_related[:80]:
            intent_raw = str(row.get("Intent", "?"))
            intent = intent_map.get(intent_raw, intent_raw) if "intent_map" in dir() else intent_raw
            lines.append(
                f"  {row.get('Keyword', ''):<45} "
                f"{row.get('Search Volume', '?'):>8} "
                f"{row.get('Keyword Difficulty', '?'):>4} "
                f"{row.get('CPC', '?'):>7} "
                f"{row.get('_category', '?'):<12} "
                f"{intent}"
            )

    # Top question keywords
    questions = results.get("questions", [])
    if questions:
        sorted_q = sorted(
            questions,
            key=lambda r: int(r.get("Search Volume", "0") or "0"),
            reverse=True,
        )
        lines.append(f"\n{'─' * 80}")
        lines.append(f"QUESTION KEYWORDS ({len(questions)} unique)")
        lines.append(f"{'─' * 80}")
        for row in sorted_q[:60]:
            vol = row.get("Search Volume", "?")
            cat = row.get("_category", "?")
            lines.append(f"  [{vol:>8}] [{cat:<10}] {row.get('Keyword', '')}")

    # Competitor gaps
    gaps = results.get("competitor_gaps", [])
    if gaps:
        sorted_gaps = sorted(
            gaps,
            key=lambda r: int(r.get("Search Volume", "0") or "0"),
            reverse=True,
        )
        lines.append(f"\n{'─' * 80}")
        lines.append(f"COMPETITOR HEALTH KEYWORDS ({len(gaps)} total)")
        lines.append(f"{'─' * 80}")
        lines.append(f"  {'Keyword':<40} {'Vol':>8} {'Pos':>4} {'Competitor'}")
        lines.append("  " + "-" * 75)
        for row in sorted_gaps[:60]:
            lines.append(
                f"  {row.get('Keyword', ''):<40} "
                f"{row.get('Search Volume', '?'):>8} "
                f"{row.get('Position', '?'):>4} "
                f"{row.get('_competitor', '?')}"
            )

    # Summary
    lines.append(f"\n{'=' * 80}")
    lines.append("SUMMARY")
    lines.append(f"  Seed terms analyzed:          {len(overviews)}")
    lines.append(f"  Unique related keywords:      {len(related)}")
    lines.append(f"  Unique question keywords:     {len(questions)}")
    lines.append(f"  Competitor health keywords:   {len(gaps)}")
    lines.append(f"  Competitors analyzed:         {len(results.get('competitor_organic', {}))}")
    lines.append("=" * 80)

    return "\n".join(lines)


def main() -> int:
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    args = _parser().parse_args()

    if not settings.semrush_api_key:
        print(
            "ERROR: SEMRUSH_API_KEY is not set.\n"
            "  Add it to .env:  SEMRUSH_API_KEY=your_key_here",
            file=sys.stderr,
        )
        return 1

    competitors = [c.strip() for c in args.competitors.split(",") if c.strip()] or None

    print("╔══════════════════════════════════════════════════════════════╗")
    print("║  METABOLIC HEALTH — SEMRUSH KEYWORD RESEARCH               ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print(f"\nSeed terms: {len(ALL_SEEDS)}")
    print(f"  Metabolism: {len(METABOLISM_SEEDS)}")
    print(f"  Hormones:   {len(HORMONE_SEEDS)}")
    print(f"  Recovery:   {len(RECOVERY_SEEDS)}")
    if competitors:
        print(f"Competitors: {competitors}")

    results = run_health_keyword_research(
        competitor_domains=competitors,
        limit=args.limit,
    )

    report = format_health_report(results)
    print("\n" + report)

    out_dir = Path(ROOT) / "output" / "semrush"
    out_dir.mkdir(parents=True, exist_ok=True)

    dated = datetime.now().strftime("%Y-%m-%d")
    report_path = Path(args.output) if args.output else out_dir / f"health-keyword-research-{dated}.txt"
    report_path.write_text(report, encoding="utf-8")
    print(f"\nReport saved to {report_path}")

    if args.json:
        json_data = {
            "metadata": results["metadata"],
            "seed_overviews": results["seed_overviews"],
            "related": results["related"],
            "questions": results["questions"],
            "serp_features": results["serp_features"],
            "competitor_organic": {
                k: v[:50] for k, v in results.get("competitor_organic", {}).items()
            },
            "competitor_gaps": results["competitor_gaps"],
        }
        json_path = out_dir / f"health-keyword-research-{dated}.json"
        json_path.write_text(json.dumps(json_data, indent=2, default=str), encoding="utf-8")
        print(f"JSON data saved to {json_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
