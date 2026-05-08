#!/usr/bin/env python3
"""Semrush keyword research for two topic clusters:
  1. Bones / bone density (menopause-related)
  2. Understanding blood test results

Outputs a text report + JSON to output/semrush/.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.seo.semrush import SemrushClient

BONE_SEEDS = [
    "bone density",
    "bone density menopause",
    "osteoporosis menopause",
    "bone loss menopause",
    "how to increase bone density",
    "bone density test",
    "DEXA scan",
    "calcium for bone health",
    "vitamin D bone density",
    "weight bearing exercise bones",
    "osteopenia",
    "osteopenia menopause",
    "bone density after menopause",
    "bone health supplements",
    "bone density food",
    "perimenopause bone loss",
    "estrogen bone density",
    "bone density score",
    "T score bone density",
    "best exercises for bone density",
]

BLOOD_TEST_SEEDS = [
    "understanding blood test results",
    "blood test results explained",
    "how to read blood work",
    "CBC blood test",
    "complete blood count",
    "metabolic panel results",
    "comprehensive metabolic panel",
    "what do blood test numbers mean",
    "normal blood test ranges",
    "blood work interpretation",
    "low white blood cell count",
    "high cholesterol blood test",
    "A1C test results",
    "thyroid blood test results",
    "liver function test results",
    "kidney function blood test",
    "CRP blood test",
    "iron blood test results",
    "vitamin D blood test",
    "blood sugar levels chart",
]

ALL_SEEDS = BONE_SEEDS + BLOOD_TEST_SEEDS


def main() -> int:
    client = SemrushClient()

    results: dict = {
        "metadata": {
            "date": datetime.now().isoformat(),
            "topics": {
                "bone_density_menopause": BONE_SEEDS,
                "blood_test_results": BLOOD_TEST_SEEDS,
            },
        },
        "seed_overviews": {},
        "related": [],
        "questions": [],
    }

    # 1 — Seed keyword overview (batch)
    print(f"\n[1/3] Batch keyword overview for {len(ALL_SEEDS)} seeds …")
    try:
        batches = [ALL_SEEDS[i:i + 100] for i in range(0, len(ALL_SEEDS), 100)]
        for batch in batches:
            rows = client.keyword_overview_batch(batch)
            for row in rows:
                kw = row.get("Keyword", "")
                if kw:
                    results["seed_overviews"][kw.lower()] = row
            time.sleep(0.5)
        print(f"  Got metrics for {len(results['seed_overviews'])} seeds")
    except Exception as exc:
        print(f"  Batch failed ({exc}), falling back to individual lookups")
        for seed in ALL_SEEDS:
            try:
                data = client.keyword_overview(seed)
                if data:
                    results["seed_overviews"][seed.lower()] = data[0]
                time.sleep(0.3)
            except Exception as e2:
                print(f"  Skipping '{seed}': {e2}")

    # 2 — Related keywords
    print(f"\n[2/3] Expanding related keywords …")
    seen_r: set[str] = set()
    for i, seed in enumerate(ALL_SEEDS):
        topic = "bone_density" if seed in BONE_SEEDS else "blood_tests"
        print(f"  [{i+1}/{len(ALL_SEEDS)}] {seed}")
        try:
            related = client.related_keywords(seed, limit=50)
            for row in related:
                kw = row.get("Keyword", "").lower()
                if kw and kw not in seen_r:
                    seen_r.add(kw)
                    row["_seed"] = seed
                    row["_topic"] = topic
                    results["related"].append(row)
            time.sleep(0.3)
        except Exception as exc:
            print(f"    related failed: {exc}")
    print(f"  Unique related keywords: {len(results['related'])}")

    # 3 — Question keywords
    print(f"\n[3/3] Fetching question keywords …")
    seen_q: set[str] = set()
    for i, seed in enumerate(ALL_SEEDS):
        topic = "bone_density" if seed in BONE_SEEDS else "blood_tests"
        print(f"  [{i+1}/{len(ALL_SEEDS)}] {seed}")
        try:
            questions = client.phrase_questions(seed, limit=50)
            for row in questions:
                kw = row.get("Keyword", "").lower()
                if kw and kw not in seen_q:
                    seen_q.add(kw)
                    row["_seed"] = seed
                    row["_topic"] = topic
                    results["questions"].append(row)
            time.sleep(0.3)
        except Exception as exc:
            print(f"    questions failed: {exc}")
    print(f"  Unique question keywords: {len(results['questions'])}")

    # ── Build report ─────────────────────────────────────────────
    intent_map = {"0": "info", "1": "nav", "2": "comm", "3": "trans"}
    lines: list[str] = []
    lines.append("=" * 90)
    lines.append("KEYWORD RESEARCH: BONE DENSITY + BLOOD TEST RESULTS")
    lines.append(f"Generated: {results['metadata']['date']}")
    lines.append("=" * 90)

    for topic_key, topic_label, seeds in [
        ("bone_density", "BONE DENSITY / MENOPAUSE", BONE_SEEDS),
        ("blood_tests", "UNDERSTANDING BLOOD TEST RESULTS", BLOOD_TEST_SEEDS),
    ]:
        lines.append(f"\n{'━' * 90}")
        lines.append(f"  TOPIC: {topic_label}")
        lines.append(f"{'━' * 90}")

        # Seed overview table
        lines.append(f"\n  ── Seed Keyword Metrics ──")
        lines.append(f"  {'Keyword':<42} {'Vol':>8} {'KD':>4} {'CPC':>7} {'Comp':>6} {'Intent'}")
        lines.append("  " + "-" * 80)
        for seed in seeds:
            row = results["seed_overviews"].get(seed.lower(), {})
            vol = row.get("Search Volume", "?")
            kd = row.get("Keyword Difficulty", "?")
            cpc = row.get("CPC", "?")
            comp = row.get("Competition", "?")
            intent = intent_map.get(str(row.get("Intent", "?")), str(row.get("Intent", "?")))
            lines.append(f"  {seed:<42} {vol:>8} {kd:>4} {cpc:>7} {comp:>6} {intent}")

        # Top related keywords by volume (filtered to this topic)
        topic_related = [
            r for r in results["related"] if r.get("_topic") == topic_key
        ]
        topic_related.sort(
            key=lambda r: int(r.get("Search Volume", "0") or "0"),
            reverse=True,
        )
        if topic_related:
            lines.append(f"\n  ── Top Related Keywords ({len(topic_related)} unique) ──")
            lines.append(f"  {'Keyword':<50} {'Vol':>8} {'KD':>4} {'CPC':>7} {'Intent'}")
            lines.append("  " + "-" * 85)
            for row in topic_related[:60]:
                intent = intent_map.get(
                    str(row.get("Intent", "?")),
                    str(row.get("Intent", "?")),
                )
                lines.append(
                    f"  {row.get('Keyword', ''):<50} "
                    f"{row.get('Search Volume', '?'):>8} "
                    f"{row.get('Keyword Difficulty', '?'):>4} "
                    f"{row.get('CPC', '?'):>7} "
                    f"{intent}"
                )

        # "Winnable" keywords: KD <= 40, volume >= 100
        winnable = []
        for row in topic_related:
            try:
                kd_val = int(row.get("Keyword Difficulty", "100") or "100")
                vol_val = int(row.get("Search Volume", "0") or "0")
            except (ValueError, TypeError):
                continue
            if kd_val <= 40 and vol_val >= 100:
                winnable.append(row)

        if winnable:
            lines.append(f"\n  ── WINNABLE Keywords (KD ≤ 40 & Vol ≥ 100) — {len(winnable)} found ──")
            lines.append(f"  {'Keyword':<50} {'Vol':>8} {'KD':>4} {'CPC':>7} {'Intent'}")
            lines.append("  " + "-" * 85)
            for row in winnable[:40]:
                intent = intent_map.get(
                    str(row.get("Intent", "?")),
                    str(row.get("Intent", "?")),
                )
                lines.append(
                    f"  {row.get('Keyword', ''):<50} "
                    f"{row.get('Search Volume', '?'):>8} "
                    f"{row.get('Keyword Difficulty', '?'):>4} "
                    f"{row.get('CPC', '?'):>7} "
                    f"{intent}"
                )

        # Question keywords for this topic
        topic_questions = [
            r for r in results["questions"] if r.get("_topic") == topic_key
        ]
        topic_questions.sort(
            key=lambda r: int(r.get("Search Volume", "0") or "0"),
            reverse=True,
        )
        if topic_questions:
            lines.append(f"\n  ── Question Keywords ({len(topic_questions)} unique) ──")
            for row in topic_questions[:40]:
                vol = row.get("Search Volume", "?")
                kd = row.get("Keyword Difficulty", "?")
                lines.append(f"  [{vol:>8}] [KD:{kd:>3}] {row.get('Keyword', '')}")

        # Winnable questions
        winnable_q = []
        for row in topic_questions:
            try:
                kd_val = int(row.get("Keyword Difficulty", "100") or "100")
                vol_val = int(row.get("Search Volume", "0") or "0")
            except (ValueError, TypeError):
                continue
            if kd_val <= 40 and vol_val >= 50:
                winnable_q.append(row)

        if winnable_q:
            lines.append(f"\n  ── WINNABLE Question Keywords (KD ≤ 40 & Vol ≥ 50) — {len(winnable_q)} found ──")
            for row in winnable_q[:30]:
                vol = row.get("Search Volume", "?")
                kd = row.get("Keyword Difficulty", "?")
                lines.append(f"  [{vol:>8}] [KD:{kd:>3}] {row.get('Keyword', '')}")

    # Summary
    bone_related = [r for r in results["related"] if r.get("_topic") == "bone_density"]
    blood_related = [r for r in results["related"] if r.get("_topic") == "blood_tests"]
    bone_questions = [r for r in results["questions"] if r.get("_topic") == "bone_density"]
    blood_questions = [r for r in results["questions"] if r.get("_topic") == "blood_tests"]

    lines.append(f"\n{'=' * 90}")
    lines.append("SUMMARY")
    lines.append(f"  Seeds analyzed:                {len(results['seed_overviews'])}")
    lines.append(f"  Bone density related kws:      {len(bone_related)}")
    lines.append(f"  Bone density questions:        {len(bone_questions)}")
    lines.append(f"  Blood test related kws:        {len(blood_related)}")
    lines.append(f"  Blood test questions:          {len(blood_questions)}")
    lines.append(f"  Total unique keywords found:   {len(results['related']) + len(results['questions'])}")
    lines.append("=" * 90)

    report = "\n".join(lines)
    print("\n" + report)

    # Save outputs
    out_dir = Path(ROOT) / "output" / "semrush"
    out_dir.mkdir(parents=True, exist_ok=True)
    dated = datetime.now().strftime("%Y-%m-%d")

    report_path = out_dir / f"bone-bloodtest-keywords-{dated}.txt"
    report_path.write_text(report, encoding="utf-8")
    print(f"\nReport saved to {report_path}")

    json_path = out_dir / f"bone-bloodtest-keywords-{dated}.json"
    json_path.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print(f"JSON data saved to {json_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
