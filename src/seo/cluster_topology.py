"""
Internal-linking topic-cluster topology for the health optimization site.

Single source of truth for which page belongs to which cluster, the hub
page for each cluster, and the canonical anchor text for every internal link.

Clusters are validated by Semrush keyword data (see output/semrush/):
  - Metabolism:  599 keywords, 3.1M combined volume
  - Hormones:   749 keywords, 5.6M combined volume
  - Recovery:   603 keywords, 8.8M combined volume
  - Testing:     14 keywords, 110K combined volume (cross-cluster)

Public API:
    cluster_for(path)       -> Cluster | None
    other_members(path)     -> list[ClusterLink]
    pillar_link_for(path)   -> ClusterLink | None
    build_cluster_ctx(path) -> dict  (for Jinja templates)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# Canonical anchor text for every page in the cluster topology.
# Every internal link uses these exact phrases for consistent topical signal.
_ANCHOR: dict[str, str] = {
    # ── Peptides hub + spokes ──
    "/peptides": "Peptide therapy — what peptides are, how they work, and which ones to consider",
    "/peptide-therapy": "Peptide therapy: what it is, how it works, and who it's for",
    "/peptides/bpc-157": "BPC-157: healing peptide benefits, dosage, and safety",
    "/peptides/ipamorelin": "Ipamorelin: growth hormone peptide benefits, dosage & results",
    "/peptides/sermorelin": "Sermorelin: anti-aging growth hormone therapy guide",
    "/peptides/cjc-1295": "CJC-1295: GHRH analog benefits, dosage, and stacking guide",
    "/peptides/tb-500": "TB-500 (Thymosin Beta-4): tissue repair peptide guide",
    "/peptides/epithalon": "Epithalon: the longevity peptide — research, benefits & dosage",
    "/peptides/semax": "Semax: cognitive peptide — nootropic effects and research",
    "/peptides/selank": "Selank: anti-anxiety peptide — effects, research & dosage",
    "/peptides/healing": "Peptides for healing: tissue repair, injury recovery & inflammation",
    "/peptides/muscle-growth": "Peptides for muscle growth: best options, stacks & protocols",
    "/peptides/anti-aging": "Longevity peptides: anti-aging options and the research behind them",
    "/compare/bpc-157-vs-tb-500": "BPC-157 vs TB-500: tissue repair peptides compared",
    "/faq/are-peptides-legal": "Are peptides legal? FDA status, research chemicals & what's allowed",
    "/tools/peptide-finder": "Peptide Finder — personalized peptide recommendations based on your goals",

    # ── Metabolism hub + spokes ──
    "/metabolic-health": "Metabolic health — insulin resistance, blood sugar, body composition",
    "/insulin-resistance": "What is insulin resistance? Causes, symptoms & how to reverse it",
    "/metabolic-syndrome": "Metabolic syndrome — diagnosis, risks, and treatment",
    "/symptoms/insulin-resistance": "Insulin resistance symptoms: 12 warning signs",
    "/symptoms/blood-sugar-crash": "Blood sugar crash: why it happens and how to stop it",
    "/symptoms/glucose-spikes": "Glucose spikes after eating: causes and what to do",
    "/symptoms/fatigue-after-eating": "Fatigue after eating: why food makes you tired",
    "/symptoms/hypoglycemia": "Hypoglycemia symptoms: low blood sugar warning signs",
    "/guides/reverse-insulin-resistance": "How to reverse insulin resistance naturally",
    "/guides/slow-metabolism": "Slow metabolism: myths, causes, and what actually works",
    "/guides/visceral-fat": "Visceral fat: why it's dangerous and how to lose it",
    "/guides/lose-belly-fat": "How to lose belly fat: evidence-based approaches",
    "/guides/glp1-plateau": "GLP-1 weight loss plateau: what to do when Ozempic stops working",
    "/guides/ozempic-weight-loss": "Ozempic and GLP-1 for weight loss: results, timelines, and what to expect",
    "/labs/insulin-resistance-testing": "How to test for insulin resistance: labs that matter",
    "/why-am-i/tired-all-the-time": "Why am I so tired all the time?",

    # ── Hormones hub + spokes ──
    "/hormone-optimization": "Hormone optimization — testosterone, thyroid, cortisol, estrogen",
    "/hormone-optimization/menopause": "Menopause, fatigue, weight gain, and metabolic health",
    "/hormone-optimization/perimenopause": "Perimenopause symptoms, fatigue, and early hormone changes",
    "/low-testosterone": "Low testosterone in men: symptoms, causes, and treatment",
    "/hormone-imbalance": "Hormone imbalance: symptoms, causes, and how to fix it",
    "/thyroid-symptoms": "Thyroid symptoms: hypothyroidism vs hyperthyroidism and what your labs mean",
    "/symptoms/high-cortisol": "High cortisol symptoms: signs your stress hormones are too high",
    "/symptoms/perimenopause": "Perimenopause symptoms: the complete guide",
    "/symptoms/perimenopause-fatigue": "Perimenopause fatigue: causes and energy solutions",
    "/symptoms/brain-fog": "Brain fog: hormonal causes and how to clear it",
    "/causes/low-testosterone": "What causes low testosterone? Root causes explained",
    "/causes/low-libido": "Low libido: causes in men and women",
    "/faq/testosterone-myths": "Does X lower testosterone? Common myths debunked",
    "/guides/increase-testosterone": "How to increase testosterone naturally",
    "/guides/lower-cortisol": "How to lower cortisol levels naturally",
    "/guides/menopause-weight-gain": "Menopause weight gain: why it happens and what to do",
    "/guides/hormonal-weight-gain": "Hormonal weight gain: estrogen, progesterone, and what to do about it",
    "/guides/balance-hormones": "How to balance hormones naturally: evidence-based guide",
    "/conditions/hypothyroidism": "Hypothyroidism: causes, symptoms, and treatment guide",
    "/conditions/cortisol-imbalance": "Cortisol imbalance: testing, symptoms, and protocol",
    "/conditions/cushings-syndrome": "Cushing's syndrome: symptoms, diagnosis, and treatment",
    "/conditions/pcos": "PCOS and hormone imbalance: what you need to know",

    # ── Recovery hub + spokes ──
    "/sleep-recovery": "Sleep and recovery — fatigue, sleep quality, HRV, stress recovery",
    "/sleep-recovery/sleep-apnea": "Sleep apnea, fatigue, weight gain, and metabolic risk",
    "/chronic-fatigue": "Chronic fatigue: causes beyond just sleep",
    "/symptoms/sleep-apnea": "Sleep apnea symptoms: signs you're not breathing at night",
    "/symptoms/waking-up-tired": "Waking up tired every day? Here's why",
    "/symptoms/sleep-inertia": "Sleep inertia: why you feel groggy when you wake up",
    "/symptoms/afternoon-energy-crash": "Afternoon energy crash: causes and how to prevent it",
    "/conditions/chronic-fatigue-syndrome": "Chronic fatigue syndrome (ME/CFS): what we know",
    "/guides/poor-sleep-quality": "Poor sleep quality: root causes and evidence-based fixes",
    "/guides/low-hrv": "Low HRV: what it means and how to improve it",
    "/guides/cortisol-and-sleep": "Cortisol and sleep: how stress hormones wreck your rest",
    "/compare/sleep-apnea-treatments": "Sleep apnea treatment options compared",
    "/conditions/upper-airway-resistance": "Upper airway resistance syndrome (UARS): symptoms, diagnosis, and treatment",
    "/guides/burnout-recovery": "Burnout recovery: signs, stages, and how to bounce back",
    "/biomarkers/heart-rate-variability": "What is HRV and why does it matter for recovery?",

    # ── Testing & Biomarkers hub + spokes ──
    "/lab-testing": "Lab testing and biomarkers — hormone panels, metabolic labs, optimal ranges",
    "/labs/hormone-testing": "Hormone testing: which labs to order and what they mean",
    "/biomarkers/fasting-insulin": "Fasting insulin levels: what's optimal and why it matters",
    "/biomarkers/free-testosterone": "Free testosterone levels: ranges by age and what's optimal",
    "/biomarkers/cortisol-levels": "Cortisol levels: normal range and what high or low means",
    "/biomarkers/shbg": "SHBG (sex hormone binding globulin): what your levels mean",
    "/biomarkers/testosterone-by-age": "Testosterone levels by age: what's normal and what's optimal",

    # ── Tools ──
    "/tools": "Health optimization tools and calculators",
    "/tools/energy-assessment": "Energy optimization assessment",
    "/tools/metabolic-score": "Metabolic health score calculator",
    "/tools/hormone-checker": "Hormone symptom checker",
    "/tools/sleep-score": "Sleep recovery score",
    "/tools/insulin-resistance-calculator": "Insulin resistance risk calculator",

    # ── Core product pages ──
    "/assessment": "Free clinical health assessment",
    "/programs": "Health optimization programs",
    "/programs/metabolic": "Metabolic health program",
    "/programs/hormones": "Hormone optimization program",
    "/programs/recovery": "Sleep and recovery program",
    "/guides/metabolic": "Metabolic Health Guide",
    "/guides/hormones": "Hormone Health Guide",
    "/guides/recovery": "Sleep & Recovery Guide",
}


@dataclass(frozen=True)
class ClusterLink:
    """One link in a cluster nav block."""
    path: str
    anchor: str
    description: str = ""


@dataclass(frozen=True)
class Cluster:
    """A topic cluster: one hub (pillar) + N spoke pages.

    `members` does NOT include the hub — templates render the hub
    distinctly and other members alongside.
    """
    key: str
    name: str
    pillar: ClusterLink
    members: tuple[ClusterLink, ...]
    summary: str = ""

    def all_paths(self) -> tuple[str, ...]:
        return (self.pillar.path,) + tuple(m.path for m in self.members)


def _ck(path: str, description: str = "") -> ClusterLink:
    """Construct a ClusterLink from a path using the canonical anchor."""
    return ClusterLink(
        path=path,
        anchor=_ANCHOR.get(path, path.split("/")[-1].replace("-", " ").title()),
        description=description,
    )


# ──────────────────────────────────────────────────────────────────────
# The four Semrush-validated clusters
# ──────────────────────────────────────────────────────────────────────

CLUSTERS: dict[str, Cluster] = {
    "peptides": Cluster(
        key="peptides",
        name="Peptide Therapy",
        summary=(
            "Peptide therapy for healing, muscle growth, cognitive enhancement, "
            "and longevity — evidence-based profiles for BPC-157, ipamorelin, "
            "sermorelin, TB-500, epithalon, semax, and more."
        ),
        pillar=_ck(
            "/peptides",
            "Peptide therapy guide — what peptides are, how they work, and which to consider.",
        ),
        members=(
            _ck("/peptide-therapy", "What peptide therapy is, how it works, and how to access it."),
            _ck("/peptides/bpc-157", "BPC-157 benefits, dosage, research, and tissue repair mechanism."),
            _ck("/peptides/ipamorelin", "Ipamorelin for growth hormone release, body composition, and recovery."),
            _ck("/peptides/sermorelin", "Sermorelin therapy for HGH stimulation, aging, and body composition."),
            _ck("/peptides/cjc-1295", "CJC-1295 dosage, benefits, and how to stack with ipamorelin."),
            _ck("/peptides/tb-500", "TB-500 for injury repair, inflammation, and tissue regeneration."),
            _ck("/peptides/epithalon", "Epithalon's telomere and longevity research — what the evidence shows."),
            _ck("/peptides/semax", "Semax for focus, neuroprotection, and BDNF upregulation."),
            _ck("/peptides/selank", "Selank for anxiety, mood stability, and cognitive calm."),
            _ck("/peptides/healing", "Which peptides help with healing — BPC-157, TB-500, and the wolverine stack."),
            _ck("/peptides/muscle-growth", "Best peptides for muscle growth, recovery, and performance."),
            _ck("/peptides/anti-aging", "Longevity peptides — epithalon, GHK-Cu, and the anti-aging research."),
            _ck("/compare/bpc-157-vs-tb-500", "BPC-157 vs TB-500: differences, use cases, and how to stack."),
            _ck("/faq/are-peptides-legal", "Peptide legality: FDA status, research chemical regulations, and what's allowed."),
            _ck("/tools/peptide-finder", "Answer 6 questions to get personalized peptide recommendations."),
        ),
    ),

    "metabolism": Cluster(
        key="metabolism",
        name="Metabolic Health",
        summary=(
            "Insulin resistance, blood sugar regulation, body composition, "
            "and metabolic syndrome — the root causes of weight gain, energy "
            "crashes, and metabolic dysfunction."
        ),
        pillar=_ck(
            "/metabolic-health",
            "Guide to insulin resistance, blood sugar, and metabolic optimization.",
        ),
        members=(
            _ck("/insulin-resistance", "What insulin resistance is, how to test for it, and how to reverse it."),
            _ck("/metabolic-syndrome", "The five diagnostic criteria and what they mean for your health."),
            _ck("/symptoms/insulin-resistance", "12 clinical warning signs, from acanthosis nigricans to post-meal fatigue."),
            _ck("/symptoms/blood-sugar-crash", "Reactive hypoglycemia: causes, symptoms, and how to stabilize glucose."),
            _ck("/symptoms/glucose-spikes", "Why blood sugar spikes after eating and what to do about it."),
            _ck("/symptoms/fatigue-after-eating", "Post-meal fatigue explained — insulin, glucose, and the gut-brain axis."),
            _ck("/symptoms/hypoglycemia", "Low blood sugar warning signs and when to seek medical attention."),
            _ck("/guides/reverse-insulin-resistance", "Evidence-based dietary and lifestyle interventions (3-16 week timeline)."),
            _ck("/guides/slow-metabolism", "Why metabolism slows, what's myth vs reality, and what the evidence says."),
            _ck("/guides/visceral-fat", "Visceral vs subcutaneous fat — why waist circumference matters more than BMI."),
            _ck("/guides/lose-belly-fat", "What clinical research says about reducing abdominal adiposity."),
            _ck("/guides/glp1-plateau", "Why GLP-1 medications plateau and what metabolic factors to address."),
            _ck("/guides/ozempic-weight-loss", "Ozempic results, timelines, side effects, and what to do when it stops working."),
            _ck("/labs/insulin-resistance-testing", "Fasting insulin, HOMA-IR, and triglyceride-to-HDL ratio explained."),
            _ck("/tools/metabolic-score", "Calculate your metabolic health score using AHA/NHLBI criteria."),
            _ck("/tools/insulin-resistance-calculator", "Estimate insulin resistance risk using HOMA-IR and surrogate markers."),
        ),
    ),

    "hormones": Cluster(
        key="hormones",
        name="Hormone Optimization",
        summary=(
            "Testosterone, estrogen, thyroid, and cortisol — comprehensive "
            "hormone testing and evidence-based protocols for men and women."
        ),
        pillar=_ck(
            "/hormone-optimization",
            "Guide to testosterone, thyroid, cortisol, and reproductive hormones.",
        ),
        members=(
            _ck("/hormone-optimization/menopause", "Menopause symptoms, body composition, testing, and treatment paths."),
            _ck("/hormone-optimization/perimenopause", "Early-transition fatigue, weight gain, sleep disruption, and symptom triage."),
            _ck("/low-testosterone", "Symptoms, causes, and treatment options for low T in men."),
            _ck("/hormone-imbalance", "How hormonal imbalances present differently in men and women."),
            _ck("/thyroid-symptoms", "Hypothyroidism vs hyperthyroidism — symptoms and what labs reveal."),
            _ck("/symptoms/high-cortisol", "Chronic stress signs: weight gain, insomnia, anxiety, impaired recovery."),
            _ck("/symptoms/perimenopause", "The complete symptom list — hot flashes affect ~80% of women."),
            _ck("/symptoms/perimenopause-fatigue", "Why perimenopause causes fatigue and what to do about it."),
            _ck("/symptoms/brain-fog", "Hormonal causes of cognitive sluggishness — thyroid, cortisol, estrogen."),
            _ck("/causes/low-testosterone", "Root causes: age, obesity, sleep, medications, chronic illness."),
            _ck("/causes/low-libido", "Hormonal, metabolic, and lifestyle causes of low sex drive."),
            _ck("/faq/testosterone-myths", "Does masturbation, alcohol, soy, or ejaculation lower testosterone?"),
            _ck("/guides/increase-testosterone", "Evidence-based lifestyle, nutrition, and supplementation strategies."),
            _ck("/guides/lower-cortisol", "How to reduce cortisol through targeted interventions."),
            _ck("/guides/menopause-weight-gain", "Hormonal shifts, metabolic changes, and what the evidence says."),
            _ck("/guides/hormonal-weight-gain", "How estrogen, progesterone, and cortisol drive weight gain."),
            _ck("/guides/balance-hormones", "Evidence-based dietary and lifestyle strategies for hormone balance."),
            _ck("/conditions/hypothyroidism", "Subclinical to overt hypothyroidism — testing beyond TSH alone."),
            _ck("/conditions/cortisol-imbalance", "AM/PM cortisol patterns, flat curves, and clinical significance."),
            _ck("/conditions/cushings-syndrome", "Cushing's syndrome: symptoms, diagnosis, and treatment."),
            _ck("/conditions/pcos", "PCOS, insulin resistance, and the hormonal cascade."),
            _ck("/biomarkers/cortisol-levels", "Cortisol levels: normal range, AM/PM patterns, and what they mean."),
            _ck("/tools/hormone-checker", "Map your symptoms to testosterone, thyroid, cortisol, and estrogen pathways."),
        ),
    ),

    "recovery": Cluster(
        key="recovery",
        name="Sleep & Recovery",
        summary=(
            "Chronic fatigue, poor sleep, low HRV, and impaired stress "
            "recovery — the physiological root causes, not just sleep hygiene."
        ),
        pillar=_ck(
            "/sleep-recovery",
            "Guide to sleep quality, fatigue, HRV, and stress recovery.",
        ),
        members=(
            _ck("/sleep-recovery/sleep-apnea", "Connect sleep apnea to fatigue, weight gain, testing, and treatment options."),
            _ck("/chronic-fatigue", "Causes of persistent fatigue beyond sleep — iron, thyroid, inflammation."),
            _ck("/symptoms/sleep-apnea", "OSA warning signs: snoring, witnessed apneas, daytime sleepiness."),
            _ck("/symptoms/waking-up-tired", "Why 7-8 hours isn't enough when sleep quality is poor."),
            _ck("/symptoms/sleep-inertia", "Morning grogginess — circadian, cortisol, and sleep-stage causes."),
            _ck("/symptoms/afternoon-energy-crash", "The 2-4 PM slump: blood sugar, cortisol, and circadian factors."),
            _ck("/conditions/chronic-fatigue-syndrome", "ME/CFS: diagnostic criteria, current research, and management."),
            _ck("/guides/poor-sleep-quality", "Root causes and evidence-based fixes beyond sleep hygiene."),
            _ck("/guides/low-hrv", "What low HRV means and how to improve autonomic recovery."),
            _ck("/guides/cortisol-and-sleep", "The cortisol-melatonin axis and 'wired but tired' patterns."),
            _ck("/compare/sleep-apnea-treatments", "CPAP, oral appliances, positional therapy, surgery — compared."),
            _ck("/conditions/upper-airway-resistance", "UARS: the missed diagnosis between snoring and sleep apnea."),
            _ck("/guides/burnout-recovery", "Burnout signs, stages, and evidence-based recovery strategies."),
            _ck("/biomarkers/heart-rate-variability", "HRV science: what it measures and why it matters for recovery."),
            _ck("/tools/sleep-score", "Assess sleep quality using elements from PSQI and Epworth scales."),
            _ck("/tools/energy-assessment", "Evaluate energy across metabolic, hormonal, and recovery domains."),
            _ck("/why-am-i/tired-all-the-time", "The metabolic, hormonal, and recovery causes of chronic tiredness."),
        ),
    ),

    "testing": Cluster(
        key="testing",
        name="Testing & Biomarkers",
        summary=(
            "Lab testing guides and biomarker reference pages — which tests "
            "to order, what optimal ranges look like, and what your results mean."
        ),
        pillar=_ck(
            "/lab-testing",
            "Guide to lab testing, panels, biomarkers, and optimal ranges.",
        ),
        members=(
            _ck("/labs/hormone-testing", "Which hormones to test, when to draw blood, and how to interpret results."),
            _ck("/labs/insulin-resistance-testing", "Fasting insulin, HOMA-IR, and triglyceride-to-HDL ratio."),
            _ck("/biomarkers/fasting-insulin", "Optimal <7 μIU/mL vs standard 'normal' <25 — why the gap matters."),
            _ck("/biomarkers/free-testosterone", "Age-adjusted ranges and why free T matters more than total."),
            _ck("/biomarkers/shbg", "How SHBG affects bioavailable testosterone and estrogen."),
            _ck("/biomarkers/testosterone-by-age", "Reference ranges by decade and the difference between normal and optimal."),
            _ck("/biomarkers/heart-rate-variability", "HRV as a recovery and autonomic health marker."),
        ),
    ),
}


# Cross-cluster links: pages that bridge two clusters
_CROSS_CLUSTER: dict[str, list[str]] = {
    "/why-am-i/tired-all-the-time": ["recovery", "metabolism", "hormones"],
    "/guides/cortisol-and-sleep": ["recovery", "hormones"],
    "/symptoms/brain-fog": ["hormones", "metabolism"],
    "/labs/insulin-resistance-testing": ["testing", "metabolism"],
    "/biomarkers/heart-rate-variability": ["testing", "recovery"],
    "/conditions/cortisol-imbalance": ["hormones", "recovery"],
    "/hormone-optimization/menopause": ["hormones", "metabolism", "recovery"],
    "/hormone-optimization/perimenopause": ["hormones", "metabolism", "recovery"],
    "/sleep-recovery/sleep-apnea": ["recovery", "metabolism", "hormones"],
}


# Path-prefix → cluster key. Most-specific prefix first.
_PATH_TO_CLUSTER: tuple[tuple[str, str], ...] = (
    # Metabolism
    ("/metabolic-health", "metabolism"),
    ("/insulin-resistance", "metabolism"),
    ("/metabolic-syndrome", "metabolism"),
    ("/symptoms/insulin-resistance", "metabolism"),
    ("/symptoms/blood-sugar-crash", "metabolism"),
    ("/symptoms/glucose-spikes", "metabolism"),
    ("/symptoms/fatigue-after-eating", "metabolism"),
    ("/symptoms/hypoglycemia", "metabolism"),
    ("/guides/reverse-insulin-resistance", "metabolism"),
    ("/guides/slow-metabolism", "metabolism"),
    ("/guides/visceral-fat", "metabolism"),
    ("/guides/lose-belly-fat", "metabolism"),
    ("/guides/glp1-plateau", "metabolism"),
    ("/guides/ozempic-weight-loss", "metabolism"),
    ("/labs/insulin-resistance-testing", "metabolism"),
    ("/why-am-i/tired-all-the-time", "recovery"),
    ("/tools/metabolic-score", "metabolism"),
    ("/tools/insulin-resistance-calculator", "metabolism"),

    # Hormones
    ("/hormone-optimization/menopause", "hormones"),
    ("/hormone-optimization/perimenopause", "hormones"),
    ("/hormone-optimization", "hormones"),
    ("/low-testosterone", "hormones"),
    ("/hormone-imbalance", "hormones"),
    ("/thyroid-symptoms", "hormones"),
    ("/symptoms/high-cortisol", "hormones"),
    ("/symptoms/perimenopause", "hormones"),
    ("/symptoms/perimenopause-fatigue", "hormones"),
    ("/symptoms/brain-fog", "hormones"),
    ("/causes/low-testosterone", "hormones"),
    ("/causes/low-libido", "hormones"),
    ("/faq/testosterone-myths", "hormones"),
    ("/guides/increase-testosterone", "hormones"),
    ("/guides/lower-cortisol", "hormones"),
    ("/guides/menopause-weight-gain", "hormones"),
    ("/guides/hormonal-weight-gain", "hormones"),
    ("/guides/balance-hormones", "hormones"),
    ("/conditions/hypothyroidism", "hormones"),
    ("/conditions/cortisol-imbalance", "hormones"),
    ("/conditions/cushings-syndrome", "hormones"),
    ("/conditions/pcos", "hormones"),
    ("/biomarkers/cortisol-levels", "hormones"),
    ("/tools/hormone-checker", "hormones"),

    # Recovery
    ("/sleep-recovery/sleep-apnea", "recovery"),
    ("/sleep-recovery", "recovery"),
    ("/chronic-fatigue", "recovery"),
    ("/symptoms/sleep-apnea", "recovery"),
    ("/symptoms/waking-up-tired", "recovery"),
    ("/symptoms/sleep-inertia", "recovery"),
    ("/symptoms/afternoon-energy-crash", "recovery"),
    ("/conditions/chronic-fatigue-syndrome", "recovery"),
    ("/guides/poor-sleep-quality", "recovery"),
    ("/guides/low-hrv", "recovery"),
    ("/guides/cortisol-and-sleep", "recovery"),
    ("/compare/sleep-apnea-treatments", "recovery"),
    ("/conditions/upper-airway-resistance", "recovery"),
    ("/guides/burnout-recovery", "recovery"),
    ("/biomarkers/heart-rate-variability", "recovery"),
    ("/tools/sleep-score", "recovery"),
    ("/tools/energy-assessment", "recovery"),

    # Testing & Biomarkers
    ("/lab-testing", "testing"),
    ("/labs/hormone-testing", "testing"),
    ("/biomarkers/fasting-insulin", "testing"),
    ("/biomarkers/free-testosterone", "testing"),
    ("/biomarkers/cortisol-levels", "hormones"),
    ("/biomarkers/shbg", "testing"),
    ("/biomarkers/testosterone-by-age", "testing"),

    ("/guides/metabolic", "metabolism"),
    ("/guides/hormones", "hormones"),
    ("/guides/recovery", "recovery"),

    # Peptides
    ("/peptides", "peptides"),
    ("/peptide-therapy", "peptides"),
    ("/tools/peptide-finder", "peptides"),
    ("/compare/bpc-157-vs-tb-500", "peptides"),
    ("/compare/tesamorelin-vs-sermorelin", "peptides"),
    ("/compare/sarms-vs-peptides", "peptides"),
    ("/faq/are-peptides-legal", "peptides"),

    # Broad prefix fallbacks (last resort)
    ("/peptides/", "peptides"),
    ("/symptoms/", "metabolism"),
    ("/guides/", "metabolism"),
    ("/conditions/", "hormones"),
    ("/causes/", "hormones"),
    ("/faq/", "hormones"),
    ("/compare/", "recovery"),
    ("/biomarkers/", "testing"),
    ("/labs/", "testing"),
    ("/why-am-i/", "metabolism"),
)


# ──────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────


def cluster_for(path: str) -> Optional[Cluster]:
    """Return the Cluster a given URL path belongs to, or None."""
    if not path:
        return None
    norm = "/" + path.lstrip("/").rstrip("/")
    if norm == "":
        norm = "/"
    for prefix, key in _PATH_TO_CLUSTER:
        if norm == prefix.rstrip("/") or norm.startswith(prefix):
            return CLUSTERS.get(key)
    return None


def other_members(path: str, *, limit: int = 10) -> list[ClusterLink]:
    """Return the cluster's other members (excluding `path` itself)."""
    cluster = cluster_for(path)
    if cluster is None:
        return []
    norm = "/" + path.lstrip("/").rstrip("/")
    out: list[ClusterLink] = []
    for m in cluster.members:
        if m.path == norm:
            continue
        out.append(m)
        if len(out) >= limit:
            break
    return out


def cross_cluster_links(path: str) -> list[ClusterLink]:
    """Return links from other clusters for pages that bridge topics."""
    norm = "/" + path.lstrip("/").rstrip("/")
    cluster_keys = _CROSS_CLUSTER.get(norm, [])
    primary = cluster_for(path)
    links: list[ClusterLink] = []
    for key in cluster_keys:
        if primary and key == primary.key:
            continue
        cluster = CLUSTERS.get(key)
        if cluster:
            links.append(cluster.pillar)
    return links


def pillar_link_for(path: str) -> Optional[ClusterLink]:
    """Return the hub link for the given page's cluster, or None if
    the page IS the hub."""
    cluster = cluster_for(path)
    if cluster is None:
        return None
    norm = "/" + path.lstrip("/").rstrip("/")
    if cluster.pillar.path == norm:
        return None
    return cluster.pillar


def build_cluster_ctx(path: str, *, limit: int = 10) -> dict:
    """One-shot helper returning the dict templates need for cluster nav."""
    cluster = cluster_for(path)
    if cluster is None:
        return {"cluster": None, "pillar": None, "others": [], "is_pillar": False, "cross_links": []}
    pillar = pillar_link_for(path)
    return {
        "cluster": cluster,
        "pillar": pillar,
        "others": other_members(path, limit=limit),
        "is_pillar": pillar is None,
        "cross_links": cross_cluster_links(path),
    }


def all_seo_paths() -> list[str]:
    """Return every path registered in the cluster topology — useful for
    sitemap generation and link auditing."""
    paths: list[str] = []
    for cluster in CLUSTERS.values():
        paths.append(cluster.pillar.path)
        for m in cluster.members:
            paths.append(m.path)
    return sorted(set(paths))
