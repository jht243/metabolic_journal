"""
Programmatic SEO page generator for the health optimization site.

Generates structured LandingPage content for all pages defined in the
cluster topology. Each page type (symptom, guide, condition, biomarker,
comparison, lab, cause, why-am-i, hub) has a template that produces:
  - title, subtitle, summary
  - body_html (intro paragraph)
  - sections_json (structured content sections)
  - faq_json (FAQ schema-ready Q&A pairs)
  - keywords_json, cluster, canonical_path

Usage:
    python3 scripts/generate_seo_pages.py [--dry-run] [--page-type symptom] [--slug insulin-resistance]
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.seo.cluster_topology import CLUSTERS, _ANCHOR, _PATH_TO_CLUSTER


# ──────────────────────────────────────────────────────────────────────
# Page content definitions by path
# ──────────────────────────────────────────────────────────────────────

@dataclass
class PageContent:
    page_key: str
    page_type: str
    title: str
    subtitle: str
    summary: str
    body_html: str
    sections: list[dict]
    faqs: list[dict]
    keywords: list[str]
    cluster: str
    canonical_path: str

    def word_count(self) -> int:
        import re
        text = re.sub(r"<[^>]+>", " ", self.body_html)
        for s in self.sections:
            text += " " + re.sub(r"<[^>]+>", " ", s.get("content", ""))
        for f in self.faqs:
            text += " " + f.get("answer", "")
        return len(text.split())


# Structured content for each page. Organized by cluster.
PAGES: dict[str, PageContent] = {}


def _register(path: str, page_type: str, cluster: str, title: str, subtitle: str,
              summary: str, body_html: str, sections: list[dict],
              faqs: list[dict], keywords: list[str]):
    key = f"{page_type}-{path.strip('/').replace('/', '-')}"
    PAGES[path] = PageContent(
        page_key=key, page_type=page_type, title=title, subtitle=subtitle,
        summary=summary, body_html=body_html, sections=sections, faqs=faqs,
        keywords=keywords, cluster=cluster, canonical_path=path,
    )


# ══════════════════════════════════════════════════════════════════════
# METABOLISM CLUSTER
# ══════════════════════════════════════════════════════════════════════

_register(
    path="/metabolic-health",
    page_type="hub",
    cluster="metabolism",
    title="Metabolic Health: Insulin Resistance, Blood Sugar & Body Composition",
    subtitle="The root cause of weight gain, energy crashes, and metabolic dysfunction",
    summary="Over 40% of US adults have insulin resistance, and only 6.8% meet all five criteria for optimal metabolic health. Understanding your metabolic status is the foundation for sustainable weight loss, stable energy, and disease prevention.",
    body_html="""<p>Metabolic health refers to how efficiently your body processes and uses energy from food. The five clinical markers — waist circumference, blood pressure, fasting glucose, triglycerides, and HDL cholesterol — determine whether your metabolism is functioning optimally or heading toward dysfunction.</p>
<p>Most people discover metabolic problems only after symptoms become severe: unexplained weight gain, energy crashes after meals, brain fog, or a pre-diabetes diagnosis. By that point, insulin resistance has typically been developing for years.</p>
<p>Our approach identifies metabolic dysfunction early using lab panels that go beyond standard bloodwork — including fasting insulin, HOMA-IR, and triglyceride-to-HDL ratio — then creates personalized protocols targeting the specific mechanisms driving your metabolic issues.</p>""",
    sections=[
        {"heading": "What Is Metabolic Health?", "content": "<p>Metabolic health is defined by five biomarkers established by the AHA/NHLBI: waist circumference (&lt;35\" women, &lt;40\" men), triglycerides (&lt;150 mg/dL), HDL cholesterol (&gt;40 mg/dL men, &gt;50 mg/dL women), blood pressure (&lt;120/80 mmHg), and fasting glucose (&lt;100 mg/dL). A 2022 JACC study found only 6.8% of US adults are optimal across all five.</p>"},
        {"heading": "The Insulin Resistance Connection", "content": "<p>Insulin resistance is the central driver of metabolic dysfunction. When cells become resistant to insulin's signal, the pancreas compensates by producing more insulin. This hyperinsulinemia promotes fat storage (especially visceral fat), raises triglycerides, lowers HDL, increases blood pressure, and eventually causes blood sugar to rise. Standard labs often miss early insulin resistance because fasting glucose stays normal until the pancreas can no longer compensate — which can take 10-15 years.</p>"},
        {"heading": "Signs Your Metabolism Needs Attention", "content": "<ul><li>Weight gain concentrated around the midsection</li><li>Energy crashes 1-3 hours after meals</li><li>Cravings for sugar or refined carbohydrates</li><li>Difficulty losing weight despite calorie restriction</li><li>Brain fog, especially after eating</li><li>Elevated fasting glucose (90-99 mg/dL, even within 'normal' range)</li><li>High triglyceride-to-HDL ratio (&gt;2.0)</li><li>Skin tags or acanthosis nigricans (dark skin patches)</li></ul>"},
        {"heading": "How We Test Metabolic Health", "content": "<p>Our metabolic panel includes markers most standard checkups miss: <strong>fasting insulin</strong> (optimal &lt;7 μIU/mL, not just &lt;25), <strong>HOMA-IR</strong> (insulin resistance index, optimal &lt;1.0), <strong>HbA1c</strong> (3-month glucose average), <strong>triglyceride-to-HDL ratio</strong>, <strong>fasting glucose</strong>, and <strong>lipid particle testing</strong>. We also assess waist-to-hip ratio and body composition to evaluate visceral fat distribution.</p>"},
    ],
    faqs=[
        {"question": "What is the difference between metabolic health and metabolism?", "answer": "Metabolism refers to all chemical processes in your body that convert food to energy. Metabolic health is a clinical assessment of how well those processes function, measured by five specific biomarkers: waist circumference, blood pressure, fasting glucose, triglycerides, and HDL cholesterol."},
        {"question": "Can you be metabolically unhealthy at a normal weight?", "answer": "Yes. Research shows approximately 30% of normal-weight adults have metabolic dysfunction — sometimes called 'metabolically obese normal weight' (MONW). Visceral fat around organs, not just total body weight, drives metabolic risk. This is why we measure waist circumference and body composition, not just BMI."},
        {"question": "How long does it take to reverse insulin resistance?", "answer": "With targeted dietary changes, exercise, and sleep optimization, measurable improvements in insulin sensitivity typically appear within 3-16 weeks. A 2019 study in Diabetes Care showed significant HOMA-IR improvement within 8 weeks of a structured intervention. Full reversal depends on severity and adherence."},
        {"question": "Why doesn't my doctor test fasting insulin?", "answer": "Standard metabolic panels include fasting glucose and HbA1c but typically not fasting insulin. This means insulin resistance can develop silently for years — fasting glucose may stay under 100 mg/dL while insulin climbs to 15-20+ μIU/mL as the pancreas compensates. Functional and integrative approaches test insulin directly for earlier detection."},
    ],
    keywords=["metabolic health", "insulin resistance", "blood sugar", "body composition", "metabolic syndrome", "fasting insulin", "HOMA-IR"],
)

_register(
    path="/symptoms/insulin-resistance",
    page_type="symptom",
    cluster="metabolism",
    title="12 Insulin Resistance Symptoms You Shouldn't Ignore",
    subtitle="The warning signs that your body is losing insulin sensitivity",
    summary="Insulin resistance affects over 100 million Americans, but most don't know they have it because standard tests don't catch it early. These 12 symptoms can indicate your body is struggling with insulin sensitivity.",
    body_html="""<p>Insulin resistance develops gradually, often over a decade or more before blood sugar rises enough to trigger a diagnosis. The symptoms below are clinical indicators that insulin signaling may be impaired — long before fasting glucose crosses the pre-diabetic threshold of 100 mg/dL.</p>""",
    sections=[
        {"heading": "Early Warning Signs", "content": "<ol><li><strong>Weight gain around the midsection</strong> — Visceral fat accumulation is both a cause and consequence of insulin resistance. Waist circumference &gt;35\" (women) or &gt;40\" (men) is a key diagnostic criterion.</li><li><strong>Energy crashes after meals</strong> — Post-meal fatigue (postprandial somnolence) results from exaggerated insulin spikes followed by reactive glucose drops.</li><li><strong>Sugar and carbohydrate cravings</strong> — Impaired glucose uptake by cells triggers hunger signals despite adequate calorie intake.</li><li><strong>Difficulty losing weight</strong> — Elevated insulin blocks fat oxidation (lipolysis), making stored fat resistant to calorie restriction alone.</li></ol>"},
        {"heading": "Physical Signs", "content": "<ol start='5'><li><strong>Acanthosis nigricans</strong> — Dark, velvety patches in skin folds (neck, armpits, groin). High insulin stimulates skin cell and melanocyte growth.</li><li><strong>Skin tags</strong> — Small flesh-colored growths, especially around the neck. Studies show a strong correlation with insulin resistance.</li><li><strong>Increased hunger (polyphagia)</strong> — Cells starved for glucose despite high blood sugar levels send persistent hunger signals.</li><li><strong>Frequent urination and thirst</strong> — These appear as blood sugar rises above the renal threshold (~180 mg/dL).</li></ol>"},
        {"heading": "Systemic Symptoms", "content": "<ol start='9'><li><strong>Brain fog and difficulty concentrating</strong> — The brain is highly insulin-sensitive; insulin resistance impairs cerebral glucose metabolism.</li><li><strong>Fatigue unrelated to sleep</strong> — Impaired cellular energy production despite adequate rest.</li><li><strong>High blood pressure</strong> — Insulin resistance promotes sodium retention and sympathetic nervous system activation.</li><li><strong>Elevated triglycerides with low HDL</strong> — A triglyceride-to-HDL ratio above 2.0 is one of the strongest surrogate markers for insulin resistance.</li></ol>"},
        {"heading": "When to Get Tested", "content": "<p>If you recognize three or more of these symptoms, testing is warranted. Request: <strong>fasting insulin</strong> (optimal &lt;7 μIU/mL), <strong>fasting glucose</strong>, <strong>HbA1c</strong>, <strong>HOMA-IR</strong> (calculated from insulin and glucose), and a <strong>lipid panel with triglyceride-to-HDL ratio</strong>. Don't rely on fasting glucose alone — it's the last marker to become abnormal.</p>"},
    ],
    faqs=[
        {"question": "Can you have insulin resistance with normal blood sugar?", "answer": "Yes, this is extremely common. Fasting glucose can remain under 100 mg/dL for 10-15 years while insulin levels steadily climb. The pancreas compensates by producing more insulin, masking the problem. This is why fasting insulin and HOMA-IR are critical tests that most standard panels miss."},
        {"question": "What is the best test for insulin resistance?", "answer": "The gold standard is the hyperinsulinemic-euglycemic clamp, but it's impractical for clinical use. The best practical tests are fasting insulin (optimal <7 μIU/mL) and HOMA-IR (optimal <1.0). A triglyceride-to-HDL ratio above 2.0 is also a strong surrogate marker."},
        {"question": "Is insulin resistance the same as pre-diabetes?", "answer": "Not exactly. Insulin resistance is the underlying mechanism; pre-diabetes is a diagnostic category based on blood sugar levels (fasting glucose 100-125 mg/dL or HbA1c 5.7-6.4%). You can have significant insulin resistance years before blood sugar rises enough to qualify as pre-diabetes."},
    ],
    keywords=["insulin resistance symptoms", "signs of insulin resistance", "insulin resistance warning signs", "acanthosis nigricans", "weight gain insulin resistance"],
)

_register(
    path="/symptoms/blood-sugar-crash",
    page_type="symptom",
    cluster="metabolism",
    title="Blood Sugar Crash: Why It Happens and How to Stop It",
    subtitle="Reactive hypoglycemia, glucose regulation, and energy stability",
    summary="Blood sugar crashes — technically reactive hypoglycemia — occur when blood glucose drops rapidly after a spike. Understanding the mechanism is key to preventing the energy rollercoaster.",
    body_html="""<p>A blood sugar crash (reactive or postprandial hypoglycemia) occurs when glucose drops below ~70 mg/dL or falls rapidly from a post-meal spike. Symptoms include shakiness, sweating, anxiety, brain fog, and intense hunger — typically 1-4 hours after eating. While occasional crashes are common, frequent episodes may indicate impaired glucose regulation or early insulin resistance.</p>""",
    sections=[
        {"heading": "Why Blood Sugar Crashes Happen", "content": "<p>After a high-glycemic meal, blood sugar spikes rapidly, triggering a large insulin release. In insulin-sensitive individuals, this overshoots — glucose is cleared from the blood faster than the liver can compensate via glycogenolysis. In insulin-resistant individuals, the pancreas overcompensates with excess insulin, causing a sharper drop. Contributing factors include: meal composition (high refined carbs, low fiber/protein/fat), meal timing, alcohol consumption, and individual variations in insulin secretion.</p>"},
        {"heading": "Symptoms of a Blood Sugar Crash", "content": "<ul><li>Shakiness, trembling, or internal vibration feeling</li><li>Sudden sweating (especially cold sweats)</li><li>Rapid heartbeat or palpitations</li><li>Intense hunger or sudden cravings</li><li>Anxiety, irritability, or mood swings</li><li>Brain fog, difficulty concentrating</li><li>Dizziness or lightheadedness</li><li>Fatigue or weakness</li></ul>"},
        {"heading": "How to Prevent Blood Sugar Crashes", "content": "<p><strong>Meal composition:</strong> Pair carbohydrates with protein, healthy fats, and fiber. A 2021 study in BMJ Nutrition, Prevention & Health found that protein-first eating reduced post-meal glucose spikes by up to 40%.</p><p><strong>Meal timing:</strong> Avoid long gaps between meals (>5-6 hours). Consider smaller, more frequent meals if crashes are frequent.</p><p><strong>Movement:</strong> A 10-15 minute walk after meals has been shown to reduce post-meal glucose peaks by 30-50%.</p><p><strong>Sleep:</strong> Poor sleep (even one night) increases insulin resistance by up to 25%, making glucose regulation less stable the next day.</p>"},
    ],
    faqs=[
        {"question": "How low does blood sugar have to drop to be a crash?", "answer": "Clinically, hypoglycemia is defined as blood glucose below 70 mg/dL. However, symptoms can occur during a rapid drop even if glucose doesn't reach that threshold — a rapid decline from 140 to 80 mg/dL can feel like a crash even though 80 is technically normal."},
        {"question": "Are blood sugar crashes dangerous?", "answer": "For most people without diabetes, reactive hypoglycemia is uncomfortable but not dangerous. However, frequent crashes can indicate insulin dysregulation that may progress to insulin resistance or type 2 diabetes. Severe hypoglycemia below 54 mg/dL requires medical attention."},
        {"question": "Should I use a CGM to track blood sugar crashes?", "answer": "Continuous glucose monitors (CGMs) can be very informative for identifying patterns. They show the magnitude and timing of glucose spikes and dips throughout the day, helping identify which meals and behaviors trigger crashes. CGM data paired with food logging reveals your personal glycemic response."},
    ],
    keywords=["blood sugar crash", "reactive hypoglycemia", "blood sugar drop after eating", "glucose crash symptoms", "postprandial hypoglycemia"],
)

_register(
    path="/symptoms/glucose-spikes",
    page_type="symptom",
    cluster="metabolism",
    title="Glucose Spikes After Eating: Causes and What to Do",
    subtitle="Why your blood sugar surges post-meal and how to flatten the curve",
    summary="Post-meal glucose spikes above 140 mg/dL are associated with increased cardiovascular risk and metabolic dysfunction — even in people without diabetes.",
    body_html="""<p>Post-meal (postprandial) glucose spikes occur when blood sugar rises significantly after eating. While some rise is normal, spikes exceeding 140 mg/dL or rising more than 40-50 mg/dL above fasting levels indicate suboptimal glucose handling. CGM studies show that even non-diabetic individuals regularly spike above 140 mg/dL — a threshold associated with endothelial damage and oxidative stress.</p>""",
    sections=[
        {"heading": "What Causes Post-Meal Glucose Spikes", "content": "<p>The primary drivers are meal composition (refined carbohydrates digest rapidly), eating speed, glycemic load, individual insulin response, and metabolic fitness. A 2015 Cell study demonstrated that identical foods produce vastly different glycemic responses between individuals — driven by gut microbiome composition, genetics, and metabolic status.</p>"},
        {"heading": "Evidence-Based Strategies to Reduce Spikes", "content": "<ul><li><strong>Food order:</strong> Eat vegetables and protein before carbohydrates. A Cornell study showed this reduces glucose spikes by ~37%.</li><li><strong>Post-meal movement:</strong> A 10-minute walk lowers peak glucose by 30-50%.</li><li><strong>Vinegar before meals:</strong> 1 tablespoon of apple cider vinegar in water before a meal can reduce post-meal glucose by 20-30% (European Journal of Clinical Nutrition).</li><li><strong>Fiber first:</strong> Starting meals with fiber-rich vegetables creates a gel-like barrier in the intestine, slowing glucose absorption.</li><li><strong>Sleep optimization:</strong> Just one night of poor sleep (4 hours) increases next-day glucose spikes by 25%.</li></ul>"},
    ],
    faqs=[
        {"question": "What is a normal glucose spike after eating?", "answer": "In metabolically healthy individuals, blood sugar typically rises 20-40 mg/dL after a meal and returns to baseline within 2 hours. Spikes above 140 mg/dL or that take more than 3 hours to normalize suggest impaired glucose tolerance."},
        {"question": "Do glucose spikes cause weight gain?", "answer": "Indirectly, yes. Large glucose spikes trigger proportionally large insulin responses. Elevated insulin promotes fat storage and inhibits fat burning. Over time, repeated high-insulin episodes can contribute to insulin resistance and preferential visceral fat accumulation."},
    ],
    keywords=["glucose spikes", "blood sugar spike after eating", "postprandial glucose", "glucose spike symptoms", "how to prevent blood sugar spikes"],
)

_register(
    path="/symptoms/fatigue-after-eating",
    page_type="symptom",
    cluster="metabolism",
    title="Fatigue After Eating: Why Food Makes You Tired",
    subtitle="Post-meal energy crashes and what they reveal about your metabolism",
    summary="Consistent fatigue after meals — postprandial somnolence — often signals blood sugar dysregulation, insulin resistance, or food sensitivities rather than normal digestion.",
    body_html="""<p>While mild drowsiness after a large meal is physiologically normal (parasympathetic activation during digestion), consistent fatigue that impairs function after most meals is not. Post-meal fatigue lasting 1-3 hours, brain fog, difficulty concentrating, or the need to nap after eating may indicate your body is struggling with glucose regulation.</p>""",
    sections=[
        {"heading": "The Metabolic Causes", "content": "<p>The most common metabolic cause is a glucose rollercoaster: a rapid spike followed by an insulin overshoot and reactive dip. This pattern is characteristic of early insulin resistance, where the pancreas releases more insulin than needed. Other metabolic contributors include impaired mitochondrial function, food sensitivities (especially gluten, dairy, or histamine), and disrupted gut-brain signaling.</p>"},
        {"heading": "When Post-Meal Fatigue Needs Investigation", "content": "<ul><li>Fatigue occurs after most meals, not just large ones</li><li>You need to lie down or nap after eating</li><li>Fatigue lasts more than 30-60 minutes</li><li>Accompanied by brain fog or difficulty concentrating</li><li>You experience shakiness or anxiety 1-3 hours later</li><li>The pattern is worse with carbohydrate-heavy meals</li></ul>"},
    ],
    faqs=[
        {"question": "Is it normal to feel tired after eating?", "answer": "Mild drowsiness after a large meal is normal — blood flow shifts to the digestive system, and serotonin/melatonin precursors from food have a mild sedative effect. But consistent fatigue after moderate meals, or fatigue severe enough to impair function, is not normal and warrants investigation."},
        {"question": "What labs should I get for post-meal fatigue?", "answer": "Key tests include fasting insulin, fasting glucose, HbA1c, HOMA-IR, a comprehensive metabolic panel, thyroid panel (TSH, free T3, free T4), iron/ferritin, vitamin D, and a food sensitivity panel. A CGM (continuous glucose monitor) worn for 2 weeks can provide direct evidence of post-meal glucose patterns."},
    ],
    keywords=["fatigue after eating", "tired after eating", "postprandial somnolence", "food coma", "sleepy after meals"],
)


# ══════════════════════════════════════════════════════════════════════
# HORMONES CLUSTER — Key Pages
# ══════════════════════════════════════════════════════════════════════

_register(
    path="/hormone-optimization",
    page_type="hub",
    cluster="hormones",
    title="Hormone Optimization: Testosterone, Thyroid, Cortisol & Estrogen",
    subtitle="Lab-driven protocols for hormonal balance and peak performance",
    summary="Hormonal imbalances affect mood, energy, body composition, libido, and cognitive function. Comprehensive testing beyond basic panels reveals the full picture — and targeted protocols restore optimal function.",
    body_html="""<p>The endocrine system is an interconnected network: testosterone, estrogen, progesterone, thyroid hormones (T3/T4), cortisol, DHEA, and insulin all influence each other. A problem in one system cascades across others — which is why treating symptoms in isolation often fails.</p>
<p>Standard bloodwork typically includes only TSH and total testosterone (if you're lucky). These miss subclinical thyroid dysfunction, low free testosterone masked by high SHBG, cortisol dysregulation, and estrogen dominance. Our comprehensive panels test 15-25 hormonal markers to identify the actual root cause.</p>""",
    sections=[
        {"heading": "The Hormones That Matter", "content": "<p><strong>Testosterone:</strong> Declines ~1-2% per year after age 30 in men. Women also produce testosterone (at lower levels) and symptoms of deficiency overlap with menopause. Key markers: total T, free T, SHBG, estradiol, LH/FSH.</p><p><strong>Thyroid:</strong> Affects every cell in the body. TSH alone misses ~30% of thyroid dysfunction. Full panel: TSH, free T3, free T4, reverse T3, TPO antibodies, thyroglobulin antibodies.</p><p><strong>Cortisol:</strong> The stress hormone. Chronic elevation impairs sleep, promotes visceral fat, breaks down muscle, and suppresses testosterone and thyroid function. Testing should include AM cortisol and ideally a 4-point saliva curve.</p><p><strong>Estrogen & Progesterone:</strong> Fluctuations during perimenopause (which can begin 8-10 years before menopause) cause fatigue, weight gain, mood changes, and sleep disruption.</p>"},
        {"heading": "Who Benefits from Hormone Optimization", "content": "<ul><li>Men over 30 with declining energy, libido, or muscle mass</li><li>Women in perimenopause or menopause experiencing fatigue, weight gain, or mood changes</li><li>Anyone with chronic fatigue unresponsive to lifestyle changes</li><li>People with thyroid symptoms despite 'normal' TSH</li><li>Athletes with impaired recovery or stalled performance</li><li>Those with unexplained weight gain, brain fog, or mood disorders</li></ul>"},
    ],
    faqs=[
        {"question": "At what age should I start monitoring hormones?", "answer": "For men, baseline testing at 30 is valuable since testosterone begins declining. For women, hormone monitoring becomes important at perimenopause onset (typically early-to-mid 40s, but can begin in late 30s). Anyone with symptoms at any age should be tested — hormonal dysfunction isn't exclusively age-related."},
        {"question": "Is hormone optimization the same as HRT?", "answer": "Not necessarily. Hormone optimization starts with identifying the root cause of imbalance (stress, sleep, nutrition, body composition) and using lifestyle interventions first. Hormone replacement therapy (HRT) is one tool in the toolkit, appropriate when lifestyle optimization alone is insufficient and clinical criteria are met."},
        {"question": "How often should hormones be retested?", "answer": "We recommend retesting 8-12 weeks after starting a new protocol, then quarterly during the first year, then biannually once stable. Some markers like cortisol may need more frequent monitoring during active protocol adjustments."},
    ],
    keywords=["hormone optimization", "testosterone", "thyroid", "cortisol", "hormone imbalance", "hormone testing", "endocrine health"],
)

_register(
    path="/low-testosterone",
    page_type="condition",
    cluster="hormones",
    title="Low Testosterone in Men: Symptoms, Causes & Treatment",
    subtitle="Understanding male hypogonadism — testing, diagnosis, and evidence-based treatment",
    summary="Testosterone deficiency affects an estimated 20-40% of men over 45, but only ~5% are diagnosed and treated. Low T impacts energy, mood, body composition, libido, cognitive function, and cardiovascular health.",
    body_html="""<p>Testosterone is the primary male sex hormone, critical for muscle mass, bone density, red blood cell production, fat distribution, libido, mood, and cognitive function. The Endocrine Society defines low testosterone as total T below 300 ng/dL — but functional medicine practitioners recognize that symptoms often begin at levels well above this threshold, particularly when free testosterone is low.</p>""",
    sections=[
        {"heading": "Symptoms of Low Testosterone", "content": "<ul><li>Decreased energy and fatigue</li><li>Reduced libido and sexual function</li><li>Loss of muscle mass and strength</li><li>Increased body fat, especially abdominal</li><li>Brain fog and difficulty concentrating</li><li>Depressed mood or irritability</li><li>Decreased bone density</li><li>Sleep disturbances</li><li>Reduced body and facial hair growth</li><li>Gynecomastia (breast tissue development)</li></ul>"},
        {"heading": "What Causes Low T", "content": "<p><strong>Primary hypogonadism:</strong> The testes produce insufficient testosterone (testicular causes — injury, infection, genetic conditions like Klinefelter syndrome).</p><p><strong>Secondary hypogonadism:</strong> The hypothalamus or pituitary gland doesn't signal properly (obesity, chronic illness, medications, pituitary tumors, head trauma). This is far more common.</p><p><strong>Lifestyle factors:</strong> Obesity (aromatase in fat tissue converts T to estrogen), chronic stress (cortisol suppresses testosterone), poor sleep (&lt;5 hours reduces T by 10-15% — JAMA 2011), alcohol excess, and certain medications (opioids, corticosteroids, statins).</p>"},
        {"heading": "Testing Beyond Total Testosterone", "content": "<p>Total testosterone alone is insufficient. A comprehensive panel includes: <strong>Total testosterone</strong> (drawn before 10 AM), <strong>Free testosterone</strong> (the bioavailable fraction), <strong>SHBG</strong> (sex hormone binding globulin — when elevated, it binds testosterone, reducing free T), <strong>Estradiol</strong> (elevated estrogen can mimic low T symptoms), <strong>LH and FSH</strong> (distinguishes primary from secondary hypogonadism), <strong>Prolactin</strong>, <strong>DHEA-S</strong>, and <strong>Cortisol</strong>.</p>"},
        {"heading": "Treatment Options", "content": "<p>Treatment follows a hierarchy: <strong>1) Lifestyle optimization</strong> — resistance training (increases T 15-20%), sleep optimization, stress management, weight loss (losing 10% body weight can increase T by 100+ ng/dL), zinc and vitamin D supplementation if deficient. <strong>2) Medications</strong> — Clomiphene citrate (stimulates endogenous production, preserves fertility), hCG, or aromatase inhibitors for appropriate candidates. <strong>3) TRT</strong> — Testosterone replacement therapy when lifestyle and medications are insufficient, with ongoing monitoring of hematocrit, PSA, and estradiol.</p>"},
    ],
    faqs=[
        {"question": "What testosterone level is considered low?", "answer": "The Endocrine Society threshold is 300 ng/dL for total testosterone. However, symptoms can occur at higher levels — especially when free testosterone is low (below 50 pg/mL) due to elevated SHBG. Optimal total T for most men is 500-900 ng/dL; optimal free T is 100-150 pg/mL."},
        {"question": "Does testosterone replacement therapy have risks?", "answer": "TRT can suppress natural production and fertility (exogenous testosterone signals the brain to stop stimulating the testes). Other potential effects include polycythemia (elevated red blood cells), acne, sleep apnea worsening, and testicular atrophy. Monitoring hematocrit, PSA, and estradiol every 3-6 months mitigates risks."},
        {"question": "Can low testosterone be reversed naturally?", "answer": "In many cases, yes — especially secondary hypogonadism caused by obesity, stress, poor sleep, or nutritional deficiencies. Weight loss, resistance training, sleep optimization (7-9 hours), stress management, and correcting zinc/vitamin D/magnesium deficiencies can increase testosterone 100-200+ ng/dL in some men."},
    ],
    keywords=["low testosterone", "low T symptoms", "testosterone deficiency", "male hypogonadism", "testosterone levels by age", "low testosterone treatment"],
)


# ══════════════════════════════════════════════════════════════════════
# RECOVERY CLUSTER — Key Pages
# ══════════════════════════════════════════════════════════════════════

_register(
    path="/sleep-recovery",
    page_type="hub",
    cluster="recovery",
    title="Sleep & Recovery: Fatigue, Sleep Quality, HRV & Stress Recovery",
    subtitle="The physiological root causes of poor recovery — not just sleep hygiene tips",
    summary="Chronic fatigue, poor sleep quality, and impaired stress recovery have metabolic and hormonal root causes that sleep hygiene alone cannot fix. Lab testing reveals the underlying dysfunction.",
    body_html="""<p>Recovery is when your body repairs, rebuilds, and recharges. It encompasses sleep quality (not just duration), autonomic nervous system balance (measured by HRV), cortisol rhythm, and cellular repair processes. When recovery systems fail, every other health domain suffers — metabolism slows, hormones dysregulate, inflammation increases, and cognitive function declines.</p>
<p>Most recovery advice focuses on sleep hygiene — dark room, cool temperature, consistent bedtime. While important, these tips don't address the physiological reasons why sleep quality may be poor: cortisol dysregulation, thyroid dysfunction, iron deficiency, sleep-disordered breathing, or chronic sympathetic overdrive.</p>""",
    sections=[
        {"heading": "Why Sleep Duration Isn't Enough", "content": "<p>You can spend 8 hours in bed and still wake exhausted if sleep architecture is disrupted. Deep sleep (N3) is when growth hormone peaks and tissue repair occurs. REM sleep consolidates memory and emotional processing. Conditions that fragment sleep — sleep apnea, cortisol surges, blood sugar drops, chronic pain — reduce these restorative stages even when total sleep time appears adequate.</p>"},
        {"heading": "HRV: Your Recovery Metric", "content": "<p>Heart rate variability (HRV) measures the variation in time between heartbeats, reflecting autonomic nervous system balance. Higher HRV indicates good parasympathetic tone and recovery capacity. Low HRV correlates with chronic stress, overtraining, inflammation, poor sleep, and increased cardiovascular risk. Tracking HRV trends (via wearables like Whoop, Oura, or Apple Watch) provides an objective daily recovery metric.</p>"},
        {"heading": "The Cortisol-Sleep Connection", "content": "<p>Cortisol should follow a diurnal rhythm: highest in the morning (cortisol awakening response), declining throughout the day, and lowest at night. Disruptions — elevated nighttime cortisol, flat diurnal curves, or absent morning peaks — directly impair sleep onset, sleep maintenance, and sleep quality. Testing with a 4-point salivary cortisol reveals your specific pattern.</p>"},
    ],
    faqs=[
        {"question": "Why do I wake up tired after 8 hours of sleep?", "answer": "Common causes include: sleep apnea (affects ~15-30% of men and 10-15% of women, many undiagnosed), fragmented sleep architecture (normal total time but reduced deep sleep), cortisol dysregulation (elevated nighttime cortisol disrupts restorative sleep stages), iron deficiency (ferritin below 50 impairs sleep quality), and thyroid dysfunction."},
        {"question": "What is a good HRV score?", "answer": "HRV is highly individual — age, fitness, genetics all play roles. Rather than comparing to population averages, track your own baseline and trends. Generally: consistently declining HRV suggests overtraining or chronic stress; HRV well below your personal average on a given day indicates poor recovery. Population medians: ages 20-30 ~50-70ms, ages 30-40 ~40-60ms, ages 40-50 ~30-50ms (rMSSD)."},
        {"question": "Can cortisol testing really help with sleep problems?", "answer": "Yes. A 4-point salivary cortisol test reveals whether your cortisol rhythm is normal, elevated at night (making it hard to fall asleep), elevated in the early morning hours (causing 3-4 AM waking), or flat (contributing to morning fatigue). This information directly guides treatment — which differs significantly based on the pattern."},
    ],
    keywords=["sleep recovery", "poor sleep quality", "chronic fatigue", "HRV", "heart rate variability", "cortisol and sleep", "waking up tired"],
)


# ══════════════════════════════════════════════════════════════════════
# TESTING CLUSTER — Key Pages
# ══════════════════════════════════════════════════════════════════════

_register(
    path="/lab-testing",
    page_type="hub",
    cluster="testing",
    title="Lab Testing & Biomarkers: Hormone Panels, Metabolic Labs & Optimal Ranges",
    subtitle="The tests your doctor doesn't run — and why they matter",
    summary="Standard bloodwork misses the early warning signs. Comprehensive panels with functional optimal ranges — not just 'normal' ranges — reveal the metabolic and hormonal dysfunction behind your symptoms.",
    body_html="""<p>The gap between 'normal' and 'optimal' lab ranges is where most people suffer. A fasting insulin of 20 μIU/mL is technically 'normal' (reference range: 2.6-24.9) but clinically indicates significant insulin resistance. A TSH of 4.0 is 'within range' but may represent subclinical hypothyroidism with real symptoms.</p>
<p>Our testing philosophy uses functional optimal ranges based on clinical research — tighter ranges where symptoms and disease risk are minimal — rather than statistical reference ranges derived from a broadly unhealthy population.</p>""",
    sections=[
        {"heading": "Why Standard Ranges Aren't Enough", "content": "<p>'Normal' lab ranges are statistical constructs — they represent the middle 95% of the population tested at that lab. Since the average American has insulin resistance, is overweight, and is metabolically unhealthy, 'normal' ranges include a lot of dysfunction. Functional optimal ranges are based on clinical outcomes research: at what level do symptoms disappear and disease risk minimize?</p><p><strong>Examples of the gap:</strong></p><ul><li>Fasting insulin: 'normal' &lt;25 μIU/mL → optimal &lt;7 μIU/mL</li><li>TSH: 'normal' 0.5-4.5 mIU/L → optimal 0.5-2.0 mIU/L</li><li>Ferritin: 'normal' 12-300 ng/mL (men) → optimal 50-150 ng/mL</li><li>Vitamin D: 'normal' 30-100 ng/mL → optimal 50-80 ng/mL</li><li>Free T3: 'normal' 2.0-4.4 pg/mL → optimal 3.0-4.0 pg/mL</li></ul>"},
        {"heading": "Our Core Lab Panels", "content": "<p><strong>Metabolic Panel:</strong> Fasting insulin, fasting glucose, HbA1c, HOMA-IR, comprehensive metabolic panel, lipid panel with particle size, hs-CRP, uric acid, homocysteine.</p><p><strong>Hormone Panel (Men):</strong> Total testosterone, free testosterone, SHBG, estradiol, LH, FSH, DHEA-S, prolactin, PSA.</p><p><strong>Hormone Panel (Women):</strong> Estradiol, progesterone, total testosterone, free testosterone, SHBG, DHEA-S, LH, FSH (cycle-day specific timing).</p><p><strong>Thyroid Panel:</strong> TSH, free T3, free T4, reverse T3, TPO antibodies, thyroglobulin antibodies.</p><p><strong>Recovery Panel:</strong> AM cortisol (or 4-point salivary), iron/ferritin/TIBC, vitamin D, magnesium (RBC), B12/folate, complete blood count.</p>"},
    ],
    faqs=[
        {"question": "How much does comprehensive lab testing cost?", "answer": "Our Comprehensive Analysis ($499) includes a full panel of 15-25 biomarkers, clinician interpretation, and a personalized protocol. Many individual tests are covered by insurance with CPT codes, and we provide a requisition form you can take to Quest or LabCorp. HSA/FSA funds are eligible."},
        {"question": "Can I use my own lab results?", "answer": "Yes. If you have recent bloodwork (within 3 months), we can review your existing results using our functional optimal ranges. However, most people find their standard panels are missing key markers like fasting insulin, free testosterone, free T3, or cortisol that we'd recommend adding."},
        {"question": "How often should I retest?", "answer": "We recommend a full retest 8-12 weeks after starting a new protocol, then quarterly for the first year, then biannually once results are stable. Some markers (like iron/ferritin during supplementation) may need more frequent monitoring."},
    ],
    keywords=["lab testing", "hormone panel", "metabolic labs", "optimal lab ranges", "functional lab ranges", "fasting insulin test", "comprehensive blood panel"],
)

_register(
    path="/biomarkers/fasting-insulin",
    page_type="biomarker",
    cluster="testing",
    title="Fasting Insulin Levels: What's Optimal and Why It Matters",
    subtitle="The most important metabolic marker your doctor probably isn't testing",
    summary="Fasting insulin is the earliest indicator of metabolic dysfunction — rising years before fasting glucose becomes abnormal. Understanding your fasting insulin level is critical for preventing type 2 diabetes and metabolic syndrome.",
    body_html="""<p>Fasting insulin measures how much insulin your pancreas needs to produce to keep blood sugar in the normal range. When insulin resistance develops, the pancreas compensates by producing more insulin. This hyperinsulinemia can persist for 10-15 years before fasting glucose rises above 100 mg/dL — making fasting insulin the earliest detectable marker of metabolic dysfunction.</p>""",
    sections=[
        {"heading": "Fasting Insulin Reference Ranges", "content": "<table><tr><th>Level (μIU/mL)</th><th>Interpretation</th></tr><tr><td>&lt;5</td><td>Optimal insulin sensitivity</td></tr><tr><td>5-7</td><td>Good — low risk</td></tr><tr><td>7-10</td><td>Mild insulin resistance — early warning</td></tr><tr><td>10-15</td><td>Moderate insulin resistance — intervention recommended</td></tr><tr><td>15-25</td><td>Significant insulin resistance — active protocol needed</td></tr><tr><td>&gt;25</td><td>Severe insulin resistance — urgent clinical attention</td></tr></table><p>Note: Most lab 'normal' ranges list 2.6-24.9 μIU/mL as the reference range, which means a level of 20 — indicating significant insulin resistance — would be reported as 'normal.'</p>"},
        {"heading": "HOMA-IR: The Insulin Resistance Index", "content": "<p>HOMA-IR is calculated as: (fasting insulin × fasting glucose) / 405. It provides a standardized metric for insulin resistance severity.</p><ul><li>&lt;1.0: Optimal insulin sensitivity</li><li>1.0-1.5: Early insulin resistance</li><li>1.5-2.5: Moderate insulin resistance</li><li>&gt;2.5: Significant insulin resistance</li><li>&gt;3.0: Consistent with metabolic syndrome</li></ul>"},
    ],
    faqs=[
        {"question": "Why doesn't standard bloodwork include fasting insulin?", "answer": "Standard metabolic panels focus on fasting glucose and HbA1c — markers that become abnormal late in the disease process. Fasting insulin isn't part of routine screening guidelines because the clinical establishment focuses on diagnosing diabetes, not preventing it. Functional and integrative practitioners include it because it detects dysfunction 10-15 years earlier."},
        {"question": "How do I get my fasting insulin tested?", "answer": "You can request it from your doctor (CPT code 83525), order it through our comprehensive panel, or use a direct-to-consumer lab service. The test requires a 12-hour overnight fast. Blood should ideally be drawn before 10 AM."},
    ],
    keywords=["fasting insulin", "fasting insulin levels", "optimal fasting insulin", "HOMA-IR", "insulin resistance test", "fasting insulin normal range"],
)


# ══════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Generate SEO landing page content")
    parser.add_argument("--dry-run", action="store_true", help="Print page summaries without writing to DB")
    parser.add_argument("--page-type", type=str, help="Only generate pages of this type")
    parser.add_argument("--path", type=str, help="Only generate a specific path")
    parser.add_argument("--output-json", type=str, help="Write all pages to a JSON file instead of DB")
    args = parser.parse_args()

    pages_to_generate = PAGES

    if args.path:
        if args.path in PAGES:
            pages_to_generate = {args.path: PAGES[args.path]}
        else:
            print(f"Path {args.path} not found. Available: {list(PAGES.keys())}")
            return
    elif args.page_type:
        pages_to_generate = {k: v for k, v in PAGES.items() if v.page_type == args.page_type}

    print(f"Generating {len(pages_to_generate)} pages...")

    if args.output_json:
        output = {}
        for path, page in pages_to_generate.items():
            output[path] = {
                "page_key": page.page_key,
                "page_type": page.page_type,
                "title": page.title,
                "subtitle": page.subtitle,
                "summary": page.summary,
                "body_html": page.body_html,
                "sections_json": page.sections,
                "faq_json": page.faqs,
                "keywords_json": page.keywords,
                "cluster": page.cluster,
                "canonical_path": page.canonical_path,
                "word_count": page.word_count(),
            }
            print(f"  {path}: {page.title} ({page.word_count()} words)")
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        with open(args.output_json, "w") as f:
            json.dump(output, f, indent=2)
        print(f"\nWritten to {args.output_json}")
        return

    if args.dry_run:
        for path, page in pages_to_generate.items():
            print(f"  [{page.page_type:10s}] {path:45s}  {page.title[:60]}  ({page.word_count()} words)")
        print(f"\n{len(pages_to_generate)} pages ready. Use --output-json or remove --dry-run to write.")
        return

    from src.models import LandingPage, SessionLocal, init_db
    init_db()
    db = SessionLocal()
    try:
        created = 0
        updated = 0
        for path, page in pages_to_generate.items():
            existing = db.query(LandingPage).filter_by(page_key=page.page_key).first()
            if existing:
                existing.title = page.title
                existing.subtitle = page.subtitle
                existing.summary = page.summary
                existing.body_html = page.body_html
                existing.sections_json = page.sections
                existing.faq_json = page.faqs
                existing.keywords_json = page.keywords
                existing.cluster = page.cluster
                existing.canonical_path = page.canonical_path
                existing.word_count = page.word_count()
                updated += 1
                print(f"  Updated: {path}")
            else:
                lp = LandingPage(
                    page_key=page.page_key,
                    page_type=page.page_type,
                    title=page.title,
                    subtitle=page.subtitle,
                    summary=page.summary,
                    body_html=page.body_html,
                    sections_json=page.sections,
                    faq_json=page.faqs,
                    keywords_json=page.keywords,
                    cluster=page.cluster,
                    canonical_path=page.canonical_path,
                    word_count=page.word_count(),
                )
                db.add(lp)
                created += 1
                print(f"  Created: {path}")
        db.commit()
        print(f"\nDone: {created} created, {updated} updated.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
