#!/usr/bin/env python3
"""Analyze Semrush keyword data and produce SEO page recommendations.

Reads the JSON output from health_keyword_research.py and produces:
1. Validated hub clusters with keyword depth
2. 30-50 prioritized SEO page recommendations
3. Programmatic template scoring
4. Tool/calculator demand validation
5. Internal linking plan
"""

import json
import os
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def load_data():
    p = Path(ROOT) / "output" / "semrush" / "health-keyword-research-2026-05-03.json"
    with open(p) as f:
        return json.load(f)

def safe_int(v, default=0):
    try: return int(v)
    except: return default

def safe_float(v, default=0.0):
    try: return float(v)
    except: return default

INTENT_MAP = {"0": "informational", "1": "navigational", "2": "commercial", "3": "transactional"}

# Keyword -> cluster assignment rules
CLUSTER_RULES = {
    "metabolism": [
        "insulin", "glucose", "blood sugar", "metabolic", "metabolism",
        "belly fat", "visceral fat", "weight loss", "calorie", "bmr",
        "basal metabolic", "glp-1", "ozempic", "wegovy", "semaglutide",
        "diabetic", "hypoglycemia", "glycemic", "a1c", "hemoglobin a1c",
        "carb", "keto", "fasting",
    ],
    "hormones": [
        "testosterone", "estrogen", "progesterone", "hormone", "hormonal",
        "thyroid", "hypothyroid", "hyperthyroid", "hashimoto", "graves",
        "cortisol", "cushing", "menopause", "perimenopause", "libido",
        "pcos", "endocrine", "adrenal", "dhea", "shbg", "sex hormone",
    ],
    "recovery": [
        "sleep", "insomnia", "fatigue", "tired", "exhausted", "apnea",
        "hrv", "heart rate variability", "stress", "recovery", "rest",
        "circadian", "melatonin", "waking up", "brain fog", "lethargy",
        "energy crash", "afternoon",
    ],
    "testing": [
        "lab test", "blood test", "panel", "biomarker", "test kit",
        "at home test", "testing", "levels", "check", "measure",
        "normal range", "optimal", "reference range",
    ],
}

def assign_cluster(keyword: str) -> str:
    kw = keyword.lower()
    scores = {}
    for cluster, terms in CLUSTER_RULES.items():
        scores[cluster] = sum(1 for t in terms if t in kw)
    best = max(scores, key=scores.get)
    if scores[best] == 0:
        return "uncategorized"
    return best

def analyze():
    data = load_data()
    seeds = data["seed_overviews"]
    related = data["related"]
    questions = data["questions"]
    comp_gaps = data["competitor_gaps"]

    # ─── 1. Build master keyword list ───────────────────────────────
    all_kws = {}

    for kw, row in seeds.items():
        all_kws[kw] = {
            "keyword": kw,
            "volume": safe_int(row.get("Search Volume")),
            "kd": safe_int(row.get("Keyword Difficulty Index")),
            "cpc": safe_float(row.get("CPC")),
            "competition": safe_float(row.get("Competition")),
            "intent": INTENT_MAP.get(str(row.get("Intent", "")), str(row.get("Intent", ""))),
            "source": "seed",
            "category": row.get("_category", ""),
            "cluster": assign_cluster(kw),
        }

    for row in related:
        kw = row.get("Keyword", "").lower()
        if not kw: continue
        vol = safe_int(row.get("Search Volume"))
        if kw not in all_kws or vol > all_kws[kw]["volume"]:
            all_kws[kw] = {
                "keyword": kw,
                "volume": vol,
                "kd": safe_int(row.get("Keyword Difficulty Index")),
                "cpc": safe_float(row.get("CPC")),
                "competition": safe_float(row.get("Competition")),
                "intent": INTENT_MAP.get(str(row.get("Intent", "")), str(row.get("Intent", ""))),
                "source": "related",
                "category": row.get("_category", ""),
                "cluster": assign_cluster(kw),
            }

    for row in questions:
        kw = row.get("Keyword", "").lower()
        if not kw: continue
        vol = safe_int(row.get("Search Volume"))
        if kw not in all_kws or vol > all_kws[kw]["volume"]:
            all_kws[kw] = {
                "keyword": kw,
                "volume": vol,
                "kd": safe_int(row.get("Keyword Difficulty Index")),
                "cpc": safe_float(row.get("CPC")),
                "competition": safe_float(row.get("Competition")),
                "intent": INTENT_MAP.get(str(row.get("Intent", "")), str(row.get("Intent", ""))),
                "source": "question",
                "category": row.get("_category", ""),
                "cluster": assign_cluster(kw),
            }

    print(f"Total unique keywords in master list: {len(all_kws)}")

    # ─── 2. Cluster validation ──────────────────────────────────────
    clusters = defaultdict(list)
    for kw_data in all_kws.values():
        clusters[kw_data["cluster"]].append(kw_data)

    print("\n" + "=" * 80)
    print("HUB CLUSTER VALIDATION")
    print("=" * 80)
    for cluster_name, kws in sorted(clusters.items(), key=lambda x: -sum(k["volume"] for k in x[1])):
        total_vol = sum(k["volume"] for k in kws)
        avg_kd = sum(k["kd"] for k in kws) / max(len(kws), 1)
        avg_cpc = sum(k["cpc"] for k in kws) / max(len(kws), 1)
        high_vol = [k for k in kws if k["volume"] >= 1000]
        mid_vol = [k for k in kws if 100 <= k["volume"] < 1000]
        valid = len(kws) >= 10 and total_vol >= 500
        print(f"\n{'✓' if valid else '✗'} {cluster_name.upper()}")
        print(f"  Keywords: {len(kws)} | Combined volume: {total_vol:,}")
        print(f"  Avg KD: {avg_kd:.0f} | Avg CPC: ${avg_cpc:.2f}")
        print(f"  High-vol (1K+): {len(high_vol)} | Mid-vol (100-999): {len(mid_vol)}")
        top5 = sorted(kws, key=lambda k: -k["volume"])[:5]
        for t in top5:
            print(f"    [{t['volume']:>8,}] KD:{t['kd']:>3} ${t['cpc']:.2f} {t['keyword']}")

    # ─── 3. SEO page recommendations ───────────────────────────────
    print("\n" + "=" * 80)
    print("SEO PAGE RECOMMENDATIONS")
    print("=" * 80)

    page_candidates = []

    # Strategy: identify page-worthy keywords (volume >= 500, or commercial intent with lower vol)
    for kw_data in all_kws.values():
        vol = kw_data["volume"]
        kd = kw_data["kd"]
        cpc = kw_data["cpc"]
        intent = kw_data["intent"]

        # Score: higher volume, lower KD, higher CPC (commercial value)
        vol_score = min(vol / 5000, 10)
        kd_penalty = max(0, (kd - 30) / 10)  # penalize KD > 30
        cpc_bonus = min(cpc * 2, 5)  # commercial value
        intent_bonus = 3 if intent in ("commercial", "transactional") else 0

        score = vol_score - kd_penalty + cpc_bonus + intent_bonus

        if vol >= 200 or (cpc >= 2.0 and vol >= 50):
            page_candidates.append({**kw_data, "page_score": score})

    page_candidates.sort(key=lambda p: -p["page_score"])

    # Deduplicate by picking the best keyword per topic cluster
    seen_slugs = set()
    pages = []

    PAGE_TEMPLATES = []

    # Manually curated high-priority pages based on data
    curated_pages = [
        # ── METABOLISM HUB + SPOKES ──
        {"title": "What Is Insulin Resistance? Causes, Symptoms & How to Reverse It", "primary_kw": "insulin resistance", "type": "hub_spoke", "template": "root_cause_guide", "cluster": "metabolism", "slug": "/insulin-resistance"},
        {"title": "Insulin Resistance Symptoms: 12 Warning Signs", "primary_kw": "insulin resistance symptoms", "type": "spoke", "template": "symptom_explainer", "cluster": "metabolism", "slug": "/symptoms/insulin-resistance"},
        {"title": "How to Reverse Insulin Resistance Naturally", "primary_kw": "how to reverse insulin resistance", "type": "spoke", "template": "protocol_page", "cluster": "metabolism", "slug": "/guides/reverse-insulin-resistance"},
        {"title": "How to Test for Insulin Resistance: Labs That Matter", "primary_kw": "how to test for insulin resistance", "type": "spoke", "template": "lab_guide", "cluster": "metabolism", "slug": "/labs/insulin-resistance-testing"},
        {"title": "What Is Metabolic Syndrome? Complete Guide", "primary_kw": "metabolic syndrome", "type": "spoke", "template": "root_cause_guide", "cluster": "metabolism", "slug": "/metabolic-syndrome"},
        {"title": "Blood Sugar Crash: Why It Happens & How to Stop It", "primary_kw": "blood sugar crash", "type": "spoke", "template": "symptom_explainer", "cluster": "metabolism", "slug": "/symptoms/blood-sugar-crash"},
        {"title": "Glucose Spikes After Eating: Causes & What to Do", "primary_kw": "glucose spikes", "type": "spoke", "template": "symptom_explainer", "cluster": "metabolism", "slug": "/symptoms/glucose-spikes"},
        {"title": "Fatigue After Eating: Why Food Makes You Tired", "primary_kw": "fatigue after eating", "type": "spoke", "template": "symptom_explainer", "cluster": "metabolism", "slug": "/symptoms/fatigue-after-eating"},
        {"title": "Slow Metabolism: Myths, Causes & What Actually Works", "primary_kw": "slow metabolism", "type": "spoke", "template": "root_cause_guide", "cluster": "metabolism", "slug": "/guides/slow-metabolism"},
        {"title": "Visceral Fat: Why It's Dangerous & How to Lose It", "primary_kw": "visceral fat", "type": "spoke", "template": "root_cause_guide", "cluster": "metabolism", "slug": "/guides/visceral-fat"},
        {"title": "How to Lose Belly Fat: Evidence-Based Approaches", "primary_kw": "how to lose belly fat", "type": "spoke", "template": "protocol_page", "cluster": "metabolism", "slug": "/guides/lose-belly-fat"},
        {"title": "Hypoglycemia Symptoms: Low Blood Sugar Warning Signs", "primary_kw": "hypoglycemia symptoms", "type": "spoke", "template": "symptom_explainer", "cluster": "metabolism", "slug": "/symptoms/hypoglycemia"},
        {"title": "Why Am I So Tired All the Time?", "primary_kw": "why am i so tired all the time", "type": "spoke", "template": "symptom_explainer", "cluster": "metabolism", "slug": "/why-am-i/tired-all-the-time"},
        {"title": "GLP-1 Weight Loss Plateau: What to Do When Ozempic Stops Working", "primary_kw": "glp-1 plateau", "type": "spoke", "template": "protocol_page", "cluster": "metabolism", "slug": "/guides/glp1-plateau"},

        # ── HORMONES HUB + SPOKES ──
        {"title": "Low Testosterone in Men: Symptoms, Causes & Treatment", "primary_kw": "low testosterone", "type": "hub_spoke", "template": "root_cause_guide", "cluster": "hormones", "slug": "/low-testosterone"},
        {"title": "What Causes Low Testosterone? Root Causes Explained", "primary_kw": "what causes low testosterone", "type": "spoke", "template": "root_cause_guide", "cluster": "hormones", "slug": "/causes/low-testosterone"},
        {"title": "How to Increase Testosterone Naturally", "primary_kw": "how to increase testosterone", "type": "spoke", "template": "protocol_page", "cluster": "hormones", "slug": "/guides/increase-testosterone"},
        {"title": "Hormone Imbalance: Symptoms, Causes & How to Fix It", "primary_kw": "hormone imbalance", "type": "hub_spoke", "template": "root_cause_guide", "cluster": "hormones", "slug": "/hormone-imbalance"},
        {"title": "Thyroid Symptoms: Hypo vs Hyper & What Your Labs Mean", "primary_kw": "thyroid symptoms", "type": "hub_spoke", "template": "symptom_explainer", "cluster": "hormones", "slug": "/thyroid-symptoms"},
        {"title": "Hypothyroidism: Causes, Symptoms & Treatment Guide", "primary_kw": "hypothyroidism", "type": "spoke", "template": "root_cause_guide", "cluster": "hormones", "slug": "/conditions/hypothyroidism"},
        {"title": "High Cortisol Symptoms: Signs Your Stress Hormones Are Too High", "primary_kw": "high cortisol symptoms", "type": "spoke", "template": "symptom_explainer", "cluster": "hormones", "slug": "/symptoms/high-cortisol"},
        {"title": "How to Lower Cortisol Levels Naturally", "primary_kw": "how to lower cortisol", "type": "spoke", "template": "protocol_page", "cluster": "hormones", "slug": "/guides/lower-cortisol"},
        {"title": "Menopause Weight Gain: Why It Happens & What to Do", "primary_kw": "menopause weight gain", "type": "spoke", "template": "root_cause_guide", "cluster": "hormones", "slug": "/guides/menopause-weight-gain"},
        {"title": "Perimenopause Symptoms: The Complete Guide", "primary_kw": "perimenopause symptoms", "type": "spoke", "template": "symptom_explainer", "cluster": "hormones", "slug": "/symptoms/perimenopause"},
        {"title": "Perimenopause Fatigue: Causes & Energy Solutions", "primary_kw": "perimenopause fatigue", "type": "spoke", "template": "symptom_explainer", "cluster": "hormones", "slug": "/symptoms/perimenopause-fatigue"},
        {"title": "Low Libido: Causes in Men and Women", "primary_kw": "low libido", "type": "spoke", "template": "root_cause_guide", "cluster": "hormones", "slug": "/causes/low-libido"},
        {"title": "Brain Fog: Hormonal Causes & How to Clear It", "primary_kw": "brain fog", "type": "spoke", "template": "symptom_explainer", "cluster": "hormones", "slug": "/symptoms/brain-fog"},
        {"title": "Cortisol Imbalance: Testing, Symptoms & Protocol", "primary_kw": "cortisol imbalance", "type": "spoke", "template": "root_cause_guide", "cluster": "hormones", "slug": "/conditions/cortisol-imbalance"},
        {"title": "PCOS & Hormone Imbalance: What You Need to Know", "primary_kw": "pcos", "type": "spoke", "template": "root_cause_guide", "cluster": "hormones", "slug": "/conditions/pcos"},

        # ── RECOVERY HUB + SPOKES ──
        {"title": "Chronic Fatigue: Causes Beyond Just Sleep", "primary_kw": "chronic fatigue", "type": "hub_spoke", "template": "root_cause_guide", "cluster": "recovery", "slug": "/chronic-fatigue"},
        {"title": "Chronic Fatigue Syndrome (ME/CFS): What We Know", "primary_kw": "chronic fatigue syndrome", "type": "spoke", "template": "root_cause_guide", "cluster": "recovery", "slug": "/conditions/chronic-fatigue-syndrome"},
        {"title": "Sleep Apnea Symptoms: Signs You're Not Breathing at Night", "primary_kw": "sleep apnea symptoms", "type": "spoke", "template": "symptom_explainer", "cluster": "recovery", "slug": "/symptoms/sleep-apnea"},
        {"title": "Sleep Apnea Treatment Options Compared", "primary_kw": "sleep apnea treatment", "type": "spoke", "template": "treatment_comparison", "cluster": "recovery", "slug": "/compare/sleep-apnea-treatments"},
        {"title": "Waking Up Tired Every Day? Here's Why", "primary_kw": "waking up tired", "type": "spoke", "template": "symptom_explainer", "cluster": "recovery", "slug": "/symptoms/waking-up-tired"},
        {"title": "Poor Sleep Quality: Root Causes & Evidence-Based Fixes", "primary_kw": "poor sleep quality", "type": "spoke", "template": "root_cause_guide", "cluster": "recovery", "slug": "/guides/poor-sleep-quality"},
        {"title": "What Is HRV & Why Does It Matter for Recovery?", "primary_kw": "heart rate variability", "type": "spoke", "template": "lab_guide", "cluster": "recovery", "slug": "/biomarkers/heart-rate-variability"},
        {"title": "Low HRV: What It Means & How to Improve It", "primary_kw": "low hrv", "type": "spoke", "template": "protocol_page", "cluster": "recovery", "slug": "/guides/low-hrv"},
        {"title": "Cortisol and Sleep: How Stress Hormones Wreck Your Rest", "primary_kw": "cortisol and sleep", "type": "spoke", "template": "root_cause_guide", "cluster": "recovery", "slug": "/guides/cortisol-and-sleep"},
        {"title": "Sleep Inertia: Why You Feel Groggy When You Wake Up", "primary_kw": "sleep inertia", "type": "spoke", "template": "symptom_explainer", "cluster": "recovery", "slug": "/symptoms/sleep-inertia"},
        {"title": "Afternoon Energy Crash: Causes & How to Prevent It", "primary_kw": "afternoon energy crash", "type": "spoke", "template": "symptom_explainer", "cluster": "recovery", "slug": "/symptoms/afternoon-energy-crash"},

        # ── TESTING & BIOMARKERS ──
        {"title": "Hormone Testing: Which Labs to Order & What They Mean", "primary_kw": "hormone testing", "type": "hub_spoke", "template": "lab_guide", "cluster": "testing", "slug": "/labs/hormone-testing"},
        {"title": "Fasting Insulin Levels: What's Optimal & Why It Matters", "primary_kw": "fasting insulin levels", "type": "spoke", "template": "lab_guide", "cluster": "testing", "slug": "/biomarkers/fasting-insulin"},
        {"title": "Free Testosterone Levels: Ranges by Age & What's Optimal", "primary_kw": "free testosterone levels", "type": "spoke", "template": "lab_guide", "cluster": "testing", "slug": "/biomarkers/free-testosterone"},
        {"title": "Cortisol Levels: Normal Range & What High/Low Means", "primary_kw": "cortisol levels", "type": "spoke", "template": "lab_guide", "cluster": "testing", "slug": "/biomarkers/cortisol-levels"},
        {"title": "SHBG (Sex Hormone Binding Globulin): What Your Levels Mean", "primary_kw": "sex hormone binding globulin", "type": "spoke", "template": "lab_guide", "cluster": "testing", "slug": "/biomarkers/shbg"},
        {"title": "Testosterone Levels by Age: What's Normal & What's Optimal", "primary_kw": "testosterone levels by age chart", "type": "spoke", "template": "lab_guide", "cluster": "testing", "slug": "/biomarkers/testosterone-by-age"},
    ]

    # Enrich curated pages with Semrush data
    for page in curated_pages:
        kw = page["primary_kw"].lower()
        kw_data = all_kws.get(kw, {})
        page["volume"] = kw_data.get("volume", 0)
        page["kd"] = kw_data.get("kd", 0)
        page["cpc"] = kw_data.get("cpc", 0.0)
        page["competition"] = kw_data.get("competition", 0.0)
        page["intent"] = kw_data.get("intent", "unknown")

        # Find supporting keywords (related kws that could go on this page)
        slug_terms = set(page["primary_kw"].lower().split())
        supporting = []
        for r in related + questions:
            rkw = r.get("Keyword", "").lower()
            overlap = len(slug_terms & set(rkw.split()))
            if overlap >= 1 and rkw != kw:
                supporting.append({
                    "keyword": rkw,
                    "volume": safe_int(r.get("Search Volume")),
                    "source": r.get("_category", ""),
                })
        supporting.sort(key=lambda s: -s["volume"])
        page["supporting_keywords"] = supporting[:8]
        page["combined_volume"] = page["volume"] + sum(s["volume"] for s in page["supporting_keywords"])

    # Sort by combined volume
    curated_pages.sort(key=lambda p: -p["combined_volume"])

    # Print
    for i, page in enumerate(curated_pages, 1):
        print(f"\n{'─' * 80}")
        print(f"PAGE {i}: {page['title']}")
        print(f"{'─' * 80}")
        print(f"  URL:              {page['slug']}")
        print(f"  Primary keyword:  {page['primary_kw']}")
        print(f"  Volume:           {page['volume']:,}/mo")
        print(f"  KD:               {page['kd']}")
        print(f"  CPC:              ${page['cpc']:.2f}")
        print(f"  Intent:           {page['intent']}")
        print(f"  Cluster:          {page['cluster']}")
        print(f"  Template:         {page['template']}")
        print(f"  Combined volume:  {page['combined_volume']:,}/mo")
        if page["supporting_keywords"]:
            print(f"  Supporting keywords:")
            for sk in page["supporting_keywords"]:
                print(f"    [{sk['volume']:>8,}] {sk['keyword']}")

    # ─── 4. Programmatic template analysis ──────────────────────────
    print("\n" + "=" * 80)
    print("PROGRAMMATIC SEO TEMPLATE ANALYSIS")
    print("=" * 80)

    templates = {
        "symptom_explainer": {"pattern": "symptoms/", "kws": [], "desc": "/symptoms/{condition}"},
        "root_cause_guide": {"pattern": "causes/|guides/|conditions/", "kws": [], "desc": "/guides/{topic}"},
        "lab_guide": {"pattern": "biomarkers/|labs/", "kws": [], "desc": "/biomarkers/{marker}"},
        "why_am_i": {"pattern": "why am i|why do i", "kws": [], "desc": "/why-am-i/{symptom}"},
        "how_to": {"pattern": "how to", "kws": [], "desc": "/guides/how-to-{action}"},
    }

    for kw_data in all_kws.values():
        kw = kw_data["keyword"]
        if kw.startswith("why am i") or kw.startswith("why do i"):
            templates["why_am_i"]["kws"].append(kw_data)
        elif kw.startswith("how to"):
            templates["how_to"]["kws"].append(kw_data)
        elif any(w in kw for w in ["symptom", "signs of", "warning sign"]):
            templates["symptom_explainer"]["kws"].append(kw_data)
        elif any(w in kw for w in ["test", "level", "range", "panel", "lab", "biomarker"]):
            templates["lab_guide"]["kws"].append(kw_data)

    for name, tmpl in templates.items():
        kws = tmpl["kws"]
        total_vol = sum(k["volume"] for k in kws)
        avg_kd = sum(k["kd"] for k in kws) / max(len(kws), 1)
        print(f"\n  {name}")
        print(f"    Pattern: {tmpl['desc']}")
        print(f"    Matching keywords: {len(kws)}")
        print(f"    Combined volume: {total_vol:,}")
        print(f"    Avg KD: {avg_kd:.0f}")
        top3 = sorted(kws, key=lambda k: -k["volume"])[:5]
        for t in top3:
            print(f"      [{t['volume']:>8,}] KD:{t['kd']:>3} {t['keyword']}")

    # ─── 5. Tool demand validation ──────────────────────────────────
    print("\n" + "=" * 80)
    print("TOOL / CALCULATOR DEMAND VALIDATION")
    print("=" * 80)

    tools = [
        {
            "name": "Insulin Resistance Risk Calculator",
            "target_kw": "insulin resistance",
            "related_kws": ["insulin resistance symptoms", "how to test for insulin resistance", "insulin resistance test"],
            "slug": "/tools/insulin-resistance-calculator",
        },
        {
            "name": "Hormone Symptom Checker",
            "target_kw": "hormone imbalance",
            "related_kws": ["hormone imbalance symptoms", "hormone testing", "signs of hormone imbalance"],
            "slug": "/tools/hormone-checker",
        },
        {
            "name": "Metabolic Health Score Calculator",
            "target_kw": "metabolic health",
            "related_kws": ["metabolic syndrome", "metabolic age", "basal metabolic rate"],
            "slug": "/tools/metabolic-score",
        },
        {
            "name": "Sleep Recovery Score",
            "target_kw": "poor sleep quality",
            "related_kws": ["sleep quality", "hrv", "sleep score", "sleep hygiene"],
            "slug": "/tools/sleep-score",
        },
        {
            "name": "Energy Optimization Assessment",
            "target_kw": "why am i so tired all the time",
            "related_kws": ["chronic fatigue", "fatigue after eating", "afternoon energy crash", "low energy"],
            "slug": "/tools/energy-assessment",
        },
    ]

    for tool in tools:
        target_data = all_kws.get(tool["target_kw"].lower(), {})
        related_vol = sum(all_kws.get(rk.lower(), {}).get("volume", 0) for rk in tool["related_kws"])
        print(f"\n  {tool['name']}")
        print(f"    URL: {tool['slug']}")
        print(f"    Target keyword: {tool['target_kw']} (vol: {target_data.get('volume', 0):,})")
        print(f"    Related keyword volume: {related_vol:,}")
        print(f"    Combined demand: {target_data.get('volume', 0) + related_vol:,}")

    # ─── 6. Save structured output ──────────────────────────────────
    output = {
        "generated": datetime.now().isoformat(),
        "summary": {
            "total_keywords": len(all_kws),
            "total_related": len(related),
            "total_questions": len(questions),
            "total_competitor_gaps": len(comp_gaps),
        },
        "clusters": {},
        "pages": curated_pages,
        "tools": tools,
    }

    for cluster_name, kws in clusters.items():
        output["clusters"][cluster_name] = {
            "keyword_count": len(kws),
            "combined_volume": sum(k["volume"] for k in kws),
            "avg_kd": sum(k["kd"] for k in kws) / max(len(kws), 1),
            "top_keywords": [
                {"keyword": k["keyword"], "volume": k["volume"], "kd": k["kd"]}
                for k in sorted(kws, key=lambda k: -k["volume"])[:20]
            ],
        }

    out_path = Path(ROOT) / "output" / "semrush" / "seo-strategy-2026-05-03.json"
    out_path.write_text(json.dumps(output, indent=2, default=str), encoding="utf-8")
    print(f"\n\nStrategy JSON saved to {out_path}")

    return output


if __name__ == "__main__":
    analyze()
