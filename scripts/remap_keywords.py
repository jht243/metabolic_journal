"""Comprehensive keyword classifier: maps all Semrush keywords to site pages."""
import json, csv, re
from collections import Counter

with open("output/semrush/health-keyword-research-2026-05-03.json") as f:
    raw = json.load(f)

keywords = []
seen = set()
for item in raw.get("related", []) + raw.get("questions", []):
    kw = item.get("Keyword", "").strip().lower()
    vol = int(item.get("Search Volume", 0))
    kd = int(item.get("Keyword Difficulty Index", 0))
    cpc = str(item.get("CPC", "0"))
    if kw and vol > 0 and kw not in seen:
        seen.add(kw)
        keywords.append({"keyword": kw, "volume": vol, "kd": kd, "cpc": cpc})

for seed, data in raw.get("seed_overviews", {}).items():
    kw = seed.strip().lower()
    if kw not in seen and isinstance(data, dict):
        vol = int(data.get("Search Volume", 0))
        kd = int(data.get("Keyword Difficulty Index", 0))
        cpc = str(data.get("CPC", "0"))
        if vol > 0:
            seen.add(kw)
            keywords.append({"keyword": kw, "volume": vol, "kd": kd, "cpc": cpc})


OFF_TOPIC_PATTERNS = [
    "meditat", "yoga", "mindfulness", "hiit", "pilates", "creatine",
    "magnesium", "ashwagandha", "mental health tip", "trauma",
    "fat guy", "fat woman", "fat women", "8 sleep", "me em",
    "u relax", "anabolism", "dexcom", "malai", "lot less",
    "sit ups", "beer belly", "love handles", "glucose goddess",
    "happily exhausted", "high when", "a of me", "c/o me",
    "beating overcoming", "why you always lying", "morning medical",
    "men's growth", "center for emotional", "how to alleviate nervousness",
    "how to reduce nervousness", "dinner exam", "drop the pounds",
    "reddit", "potbelly closest", "pot belly", "weighing machine",
    "3.2 independent", "body balancing drops", "autozone",
    "five pounds of fat", "all from me", "how o",
    "pregnancy test", "testes produce", "testes secrete",
]

EXACT_OFF = {
    "belly", "relax", "metabolic", "hormone", "bmr bmr",
    "visceral visceral", "sleep sleep deprivation", "sleep deprivation and",
    "sleep deprivation sleep", "fatigue meaning", "libido meaning",
    "insulin resistance insulin", "how to lose lose weight",
    "how to weight loss quickly", "hormones hormones", "twin",
    "groggy groggy", "thyroid thyroid thyroid", "how o",
    "hormonal", "hormonal changes", "relieving", "stressful",
    "stressed", "night time", "bedtime", "prandial", "postprandial",
    "hypo", "calming", "cfs", "me.", "me'", ".me", "me this is me",
    "is me", "me]", "\u043c\u0435", "define me", "coping", "coping skills",
    "coping mechanism", "coping skills for anxiety",
    "anxiety coping strategies", "obstructive", "sugar high",
    "sugar control", "crash sugared", "oestrogen",
    "3 pm", "mid afternoon", "how to fast", "fat burning",
    "fat loss", "imbalance meaning", "estrogen meaning",
    "estrogen definition", "hormonal belly before and after",
    "harmon in balance", "what are hormonal",
}


def classify(kw):
    k = kw.lower().strip()

    for pat in OFF_TOPIC_PATTERNS:
        if pat in k:
            return ("--", "OFF-TOPIC", "SKIP")
    if k in EXACT_OFF:
        return ("--", "OFF-TOPIC", "SKIP")

    # === GLP-1 / OZEMPIC ===
    if any(x in k for x in ["ozempic", "semaglutide", "zepbound", "wegovy",
                              "glp-1 ra", "glp-1 drug"]):
        return ("metabolism", "/guides/ozempic-weight-loss")

    # === METABOLISM ===
    if any(x in k for x in ["insulin resistance", "insulin sensitivity", "ir diet"]):
        if "symptom" in k or "sign" in k:
            return ("metabolism", "/symptoms/insulin-resistance")
        if "test" in k or "diagnos" in k:
            return ("metabolism", "/labs/insulin-resistance-testing")
        if "reverse" in k or "fix" in k or "cure" in k or "treat" in k:
            return ("metabolism", "/guides/reverse-insulin-resistance")
        return ("metabolism", "/insulin-resistance")

    if any(x in k for x in ["what is insulin", "what does insulin do",
                              "the hormone insulin", "how does insulin work",
                              "how to lower insulin", "insulin levels",
                              "what produces insulin", "where is insulin produced",
                              "what organ produces insulin", "high insulin",
                              "is insulin a hormone"]):
        return ("metabolism", "/insulin-resistance")

    if k in ("insulin", "insulina", "insuline"):
        return ("metabolism", "/insulin-resistance")

    if any(x in k for x in ["what causes diabetes", "type 2 diabetes",
                              "get rid of diabetes", "how to get sugar diabetes"]):
        return ("metabolism", "/insulin-resistance")

    if any(x in k for x in ["pre diabetic", "prediabetic", "pre diabetes",
                              "fasting insulin test", "fasting blood sugar",
                              "fasting glucose"]):
        return ("metabolism", "/labs/insulin-resistance-testing")

    if any(x in k for x in ["metabolic syndrome", "metabolic disease",
                              "metabolic disorder", "disorder metabolism",
                              "metabolic dysfunction", "metabolic issues"]):
        return ("metabolism", "/metabolic-syndrome")

    if any(x in k for x in ["belly fat", "lose belly", "abdominal fat", "stomach fat",
                              "tummy fat", "lose tummy", "burn fat belly",
                              "reduce the fat belly", "can you lose tummy",
                              "belly burning", "how can i reduce tummy",
                              "how do i lose tummy", "how can you lose tummy",
                              "how can i burn fat belly"]):
        return ("metabolism", "/guides/lose-belly-fat")

    if "visceral fat" in k or "subcutaneous fat" in k or ("visceral" in k and len(k) > 10):
        return ("metabolism", "/guides/visceral-fat")

    if any(x in k for x in ["hypoglycemia", "hypoglycemic", "low blood sugar",
                              "blood sugar low", "low sugar symptom", "sign of low sugar",
                              "low glucose", "glucose deficiency",
                              "sugar level low", "when your sugar level is low",
                              "signs blood sugar low", "what to eat when blood sugar",
                              "diabetic shock", "low sugar symptoms"]):
        return ("metabolism", "/symptoms/hypoglycemia")

    if any(x in k for x in ["blood sugar crash", "sugar crash",
                              "how to crash blood sugar",
                              "what causes blood sugar to crash",
                              "why does my blood sugar keep crash"]):
        return ("metabolism", "/symptoms/blood-sugar-crash")

    if any(x in k for x in ["glucose spike", "high blood sugar", "blood sugar spike",
                              "blood glucose increase", "signs of high blood sugar",
                              "symptoms of high blood sugar", "high glucose",
                              "glucose high", "symptoms of high bgl",
                              "hyperglycemia", "high sugar symptom",
                              "signs and symptoms of high sugar",
                              "what is the cause of high sugar", "diabetic levels high",
                              "sugar limits in blood", "glucose levels high",
                              "blood high glucose", "high glucose in blood",
                              "sugar and blood", "dawn phenomenon", "somogyi",
                              "high in blood sugar", "blood sugar blood",
                              "does honey spike", "does stevia spike",
                              "does oatmeal spike", "does brown sugar spike",
                              "does natural sugar spike", "does xylitol spike",
                              "what foods spike glucose", "what causes spikes in glucose",
                              "what spikes glucose", "quick spike in blood glucose",
                              "can produce a quick spike", "blood sugar after eating",
                              "blood sugar levels after eating", "blood glucose",
                              "symptoms of hyperglycemia", "what is hyperglycemia"]):
        return ("metabolism", "/symptoms/glucose-spikes")

    if any(x in k for x in ["fatigue after eating", "tired after eating",
                              "sleepy after eating", "food coma",
                              "why do i get sleepy after i eat",
                              "why do i get tired after i eat",
                              "how long does fatigue last after eating"]):
        return ("metabolism", "/symptoms/fatigue-after-eating")

    if any(x in k for x in ["lower blood sugar", "lower sugar", "reduce blood sugar",
                              "reduce sugar level", "lower glucose",
                              "how to lower glucose", "how to prevent blood sugar",
                              "lessen blood sugar", "get blood sugar levels down",
                              "food to lessen blood sugar", "blood sugar decrease"]):
        return ("metabolism", "/guides/reverse-insulin-resistance")

    if any(x in k for x in ["slow metabolism", "weight loss resistance",
                              "why am i not losing weight",
                              "fast metabolism", "increase metabolism",
                              "boost metabolism", "speed up metabolism",
                              "metabolism booster", "metabolism boosting",
                              "metabolic rate", "what is metabolism",
                              "metabolism definition", "high metabolism",
                              "metabolism meaning", "define metabolism",
                              "metabolic fitness", "highest metabolism",
                              "slow down metabolism", "speed up your metabolism",
                              "speed up my metabolism", "increase your metabolism",
                              "does metabolism slow", "when does metabolism slow",
                              "what age does metabolism", "what slows down metabolism",
                              "does not eating slow", "how to know if your metabolism",
                              "what foods slow down metabolism", "what is slowed metabolism",
                              "why is my metabolism", "increase my metabolism",
                              "how do you slow down", "how do i know if my metabolism",
                              "how to boost a metabolism", "how i increase my metabolism",
                              "reset your metabolism", "how can i slow down my metabolism",
                              "how do i slow down my metabolism",
                              "how to slow down metabolism for skinny",
                              "how to slow down my metabolism"]):
        return ("metabolism", "/guides/slow-metabolism")

    if "glp" in k and ("plateau" in k or k == "glp-1 plateau"):
        return ("metabolism", "/guides/glp1-plateau")

    if any(x in k for x in ["lose weight", "weight loss", "fastest way to lose",
                              "lose body fat", "how to lose fat",
                              "fast weight reduction", "get thinner",
                              "fat burner", "weight reduce", "lost weight quickly",
                              "how to burn fat", "get skinny", "how can i get thin",
                              "losing weight", "how do you get thinner",
                              "how to drop 30 pounds", "anaerobic exercise and fat"]):
        if "belly" in k or "tummy" in k:
            return ("metabolism", "/guides/lose-belly-fat")
        return ("metabolism", "/metabolic-health")

    if any(x in k for x in ["calorie deficit", "what is a calorie",
                              "cardio deficit"]):
        return ("metabolism", "/metabolic-health")

    if "bmr" in k or "basal metabolic" in k or "metabolic basal" in k:
        return ("metabolism", "/metabolic-health")

    if "metabolic health" in k or k == "metabolism" or "what does metabolic mean" in k or "what does metabolism mean" in k:
        return ("metabolism", "/metabolic-health")

    if any(x in k for x in ["diabetic diet", "diabetes diet", "diet plan for sugar",
                              "best snacks for diabetic", "glycemic disease"]):
        return ("metabolism", "/metabolic-health")

    if "gut health" in k and "metabolism" in k:
        return ("metabolism", "/metabolic-health")

    # === HORMONES ===
    if "cushing" in k or "hypercortisol" in k or "symptoms of hypercorticism" in k:
        return ("hormones", "/conditions/cushings-syndrome")

    if any(x in k for x in ["high cortisol", "cortisol symptom", "cortisol face",
                              "cortisol belly"]):
        return ("hormones", "/conditions/cushings-syndrome")

    if any(x in k for x in ["lower cortisol", "reduce cortisol", "cortisol detox",
                              "desintoxication cortisol", "decrease cortisol",
                              "cortisol lowering", "cortisol triggering",
                              "control cortisol", "get rid of cortisol",
                              "cortisol hormone reduction"]):
        return ("hormones", "/guides/lower-cortisol")

    if "cortisol level" in k or "check cortisol" in k or "cortisol test" in k:
        return ("hormones", "/biomarkers/cortisol-levels")

    if "cortisol" in k and "sleep" in k:
        return ("recovery", "/guides/cortisol-and-sleep")

    if "cortisol imbalance" in k:
        return ("hormones", "/conditions/cortisol-imbalance")

    if any(x in k for x in ["what is cortisol", "what does cortisol",
                              "cortisol is a steroid", "que es el cortisol",
                              "cortisol definition", "stress hormone"]):
        return ("hormones", "/conditions/cortisol-imbalance")

    if k in ("cortisol", "low cortisol"):
        return ("hormones", "/conditions/cortisol-imbalance")

    if any(x in k for x in ["hypothyroid", "hashimoto", "myxedema", "underactive thyroid",
                              "low thyroid", "low tsh"]):
        return ("hormones", "/conditions/hypothyroidism")

    if any(x in k for x in ["hyperthyroid", "overactive thyroid", "graves disease",
                              "graves'", "hyperactive thyroid"]):
        return ("hormones", "/thyroid-symptoms")

    if any(x in k for x in ["thyroid symptom", "thyroid sign", "thyroid problem",
                              "thyroid disease", "thyroid gland", "thyroid test",
                              "thyroid issue", "thyroid function", "diseases thyroid",
                              "thyroid stimulating", "what does the thyroid do",
                              "symptoms of thyroids", "swollen thyroid",
                              "tiroides", "thyroid nodule", "thyroid cancer",
                              "thyroid eye disease", "thyroid storm",
                              "thyroid disorder", "thyroid medication",
                              "problems of the thyroid", "bad thyroid"]):
        return ("hormones", "/thyroid-symptoms")

    if k in ("thyroid", "tiroidism", "iodine deficiency symptoms"):
        return ("hormones", "/thyroid-symptoms")

    # Testosterone myths FAQ
    if any(x in k for x in ["does masturbat", "does ejaculat", "does alcohol lower testosterone",
                              "does soy lower testosterone", "does soybeans lower",
                              "does nicotine lower testosterone", "does weed lower testosterone",
                              "does vasectomy lower testosterone", "does finasteride lower",
                              "does jerking off lower", "do receipts lower testosterone",
                              "does masterbat", "lower testosterone in women",
                              "lower testosterone in men", "how to lower testosterone"]):
        return ("hormones", "/faq/testosterone-myths")

    if any(x in k for x in ["testosterone replacement", "trt", "testosterone therapy",
                              "how to get testosterone"]):
        return ("hormones", "/low-testosterone")

    if any(x in k for x in ["increase testosterone", "boost testosterone",
                              "raise testosterone", "heighten testosterone",
                              "boost for testosterone"]):
        return ("hormones", "/guides/increase-testosterone")

    if any(x in k for x in ["low testosterone", "low t "]) or k == "low t":
        return ("hormones", "/low-testosterone")

    if any(x in k for x in ["testosterone symptom", "signs of low testosterone",
                              "testosterone low in male", "men low in testosterone"]):
        return ("hormones", "/low-testosterone")

    if any(x in k for x in ["testosterone test", "check testosterone",
                              "how to test testosterone", "testosterone levels",
                              "free testosterone", "normal testosterone"]):
        return ("testing", "/biomarkers/free-testosterone")

    if k in ("testosterone", "hypogonadism", "testosterona",
             "hypogonadotropic hypogonadism", "male hypogonadism",
             "testosterone lower", "hypogonadism in male"):
        return ("hormones", "/low-testosterone")

    # Perimenopause / menopause
    if any(x in k for x in ["perimenopause", "premenopausal", "peri menopausal",
                              "pre menopausal", "perimenopausal", "peri menopause",
                              "pre menopause", "perimenapause", "premenopause"]):
        if "fatigue" in k or "tired" in k:
            return ("hormones", "/symptoms/perimenopause-fatigue")
        if "weight" in k:
            return ("hormones", "/guides/menopause-weight-gain")
        return ("hormones", "/symptoms/perimenopause")

    if any(x in k for x in ["menopause weight", "meno belly", "menopause belly",
                              "stomach menopause", "menopausal weight",
                              "stop menopausal weight"]):
        return ("hormones", "/guides/menopause-weight-gain")

    if any(x in k for x in ["menopause fatigue", "menopause tired",
                              "does menopause make you tired", "menopause and fatigue",
                              "sudden crashing fatigue female"]):
        return ("hormones", "/symptoms/perimenopause-fatigue")

    if "menopause fuzzy" in k or "fuzzy brain and menopause" in k:
        return ("hormones", "/symptoms/brain-fog")

    if any(x in k for x in ["first sign of menopause", "signs of menopause",
                              "best diet for menopause"]):
        return ("hormones", "/symptoms/perimenopause")

    # Hormonal weight gain
    if any(x in k for x in ["hormonal weight gain", "does estrogen cause weight",
                              "does progesterone cause weight", "does oestrogen cause weight",
                              "can estrogen cause weight", "does hrt cause weight",
                              "estrogen weight gain", "hormonal belly",
                              "get rid of hormonal belly", "why am i gaining weight",
                              "why am i picking up weight", "why do i gain weight",
                              "gaining weight on", "weight gain for ladies"]):
        return ("hormones", "/guides/hormonal-weight-gain")

    # Balance hormones
    if any(x in k for x in ["balance hormone", "balance your hormone",
                              "balance the hormone", "regulate hormone",
                              "how to balance hormone", "hormonal disbalance",
                              "hormone balance", "hormone irregularity",
                              "treatment for unbalanced", "hormone disorder",
                              "signs of hormonal problem", "hormonal fluctuation",
                              "hormones in balance", "hormones for women",
                              "hormone balance for women", "what causes an imbalance",
                              "what are hormones imbalance"]):
        return ("hormones", "/guides/balance-hormones")

    # Brain fog
    if any(x in k for x in ["brain fog", "brain cloud", "cognitive sluggish",
                              "memory loss", "brainfog", "fogginess", "mental fog",
                              "foggy brain", "foggy head", "head feels fuzzy",
                              "brain dog", "what causes mental fog",
                              "dementia in women", "signs of senility",
                              "early symptoms of dementia"]):
        return ("hormones", "/symptoms/brain-fog")

    # Libido
    if any(x in k for x in ["libido", "labido", "lobido", "lipido", "labedo",
                              "lebido", "libito", "horny", "sexual appetite",
                              "sexual desire", "hsdd", "sex drive",
                              "low sex drive", "hypo sexual", "hypoactive desire"]):
        return ("hormones", "/causes/low-libido")

    # Hormone imbalance
    if any(x in k for x in ["hormone imbalance", "hormonal imbalance",
                              "imbalance hormone", "stress hormone",
                              "female hormone", "signs of low estrogen",
                              "low estrogen", "weird symptoms of low estrogen",
                              "estrogen imbalance", "high estrogen",
                              "hrt", "bioidentical", "bio identical",
                              "fda-approved bioidentical"]):
        return ("hormones", "/hormone-imbalance")

    if any(x in k for x in ["estradiol", "estrogen level", "estrogen test"]):
        return ("testing", "/labs/hormone-testing")

    if any(x in k for x in ["hormone test", "check hormone", "hormone blood",
                              "hormone doctor", "hormone panel", "hormonal test",
                              "hormone tracking", "get hormones tested",
                              "test hormone levels", "test my hormone",
                              "test your hormone", "how to test hormone",
                              "how are hormone levels tested",
                              "can you test hormone", "hormonstorung test"]):
        return ("testing", "/labs/hormone-testing")

    # === RECOVERY ===
    if "upper airway resistance" in k:
        return ("recovery", "/conditions/upper-airway-resistance")

    if any(x in k for x in ["sleep apnea", "sleep apnoea", "sleep apnia",
                              "sleep.apnea", "obstructive sleep"]):
        if "treatment" in k or "treat" in k or "cure" in k or "cpap" in k:
            return ("recovery", "/compare/sleep-apnea-treatments")
        return ("recovery", "/symptoms/sleep-apnea")

    if any(x in k for x in ["apnea", "osa symptom", "define apnea",
                              "apnea meaning", "what is apnea", "apnea del",
                              "can apnea kill", "apnea test", "apnea sleep",
                              "osa medical", "what is osa",
                              "difficulty breathing when lying",
                              "my airway"]):
        return ("recovery", "/symptoms/sleep-apnea")

    if k in ("apnea", "osa"):
        return ("recovery", "/symptoms/sleep-apnea")

    # Burnout
    if any(x in k for x in ["burnout", "burn out", "burnt out",
                              "signs of burnout", "burnout symptom",
                              "burnout meaning"]):
        return ("recovery", "/guides/burnout-recovery")

    if "sleep inertia" in k or k == "groggy":
        return ("recovery", "/sleep-recovery")

    if any(x in k for x in ["sleep disorder", "sleep problem", "sleeping problem",
                              "treat sleep", "sleep medicine"]):
        return ("recovery", "/sleep-recovery")

    if "sleep deprivation" in k or "sleep deprived" in k:
        return ("recovery", "/sleep-recovery")

    if any(x in k for x in ["can't sleep", "cant sleep", "fall asleep",
                              "insomnia", "go to sleep", "how to sleep"]):
        return ("recovery", "/guides/poor-sleep-quality")

    if any(x in k for x in ["sleep hygiene", "poor sleep", "sleep quality",
                              "better sleep", "more deep sleep", "sleep fast",
                              "sleep faster", "sleep schedule", "sleep cycle",
                              "hours of sleep", "why do i sleep so much",
                              "why am i sleeping so much",
                              "what causes poor quality sleep",
                              "what is poor quality sleep"]):
        return ("recovery", "/guides/poor-sleep-quality")

    # Waking up tired
    if any(x in k for x in ["waking up tired", "wake up tired",
                              "why do i wake up at 3am", "wake up when tired",
                              "how to wake up early", "still tired after waking",
                              "tired after waking", "tired when waking",
                              "less tired when waking", "less tired after waking",
                              "not be tired after waking", "not be tired when waking",
                              "not feel tired after waking", "not feel tired when waking",
                              "stop being tired after waking", "stop waking up so tired",
                              "normal to be tired after waking",
                              "normal to feel tired after waking",
                              "normal to feel tired when waking",
                              "does waking up", "can waking up",
                              "why am i waking up so tired",
                              "still tired after sleeping",
                              "why am i still tired after",
                              "why i feel tired after waking"]):
        return ("recovery", "/symptoms/waking-up-tired")

    # CFS / ME
    if any(x in k for x in ["chronic fatigue syndrome", "myalgic encephalomyelitis",
                              "me/cfs", "mecfs", "me cfs", "me fatigue syndrome",
                              "illness m e", "treat cfs", "what is me",
                              "me myalgic", "cfs meaning", "chronic cfs",
                              "fatigue chronic fatigue", "cfs symptom",
                              "cfs therapy", "drugs for cfs", "cfs exhaustion",
                              "encephalomyelitis", "does chronic pain cause fatigue",
                              "can chronic pain cause fatigue",
                              "can chronic sinusitis cause fatigue"]):
        return ("recovery", "/conditions/chronic-fatigue-syndrome")

    # Why am I so tired
    if any(x in k for x in ["why am i so tired", "why am i tired",
                              "why am i always tired", "i'm tired",
                              "why am j so tired", "why would i be so tired",
                              "im tired", "i am tired", "so so so tired",
                              "why i feel so tired", "why am i feeling so tired",
                              "why do i feel so tired",
                              "why do i feel tired all the time",
                              "why am i feeling sleepy all the time"]):
        return ("recovery", "/why-am-i/tired-all-the-time")

    # Chronic fatigue
    if any(x in k for x in ["chronic fatigue", "always tired", "constant fatigue",
                              "tired all the time", "extreme fatigue",
                              "fatigue causes", "tiredness fatigue",
                              "lack of energy", "feeling tired",
                              "what is fatigue", "what does fatigue",
                              "fatigue definition", "fatigue symptoms",
                              "symptoms of exhaustion", "what is lethargy",
                              "fighting weakness", "drowsiness", "drowsy",
                              "what causes fatigue", "fatigue a symptom",
                              "what are the causes of tiredness",
                              "fatigue tiredness body", "headache sickness tiredness",
                              "tired fatigue headache", "tired tiredness",
                              "feeling very tired", "excessive tiredness",
                              "so tired", "tired fast", "tired tired",
                              "getting sleepy", "how to stop being tired",
                              "sleepy how to wake", "how to wake yourself",
                              "fatigue doctor", "always feel tired",
                              "feel tired and weak", "feeling drowsy",
                              "all the time feeling sleepy"]):
        return ("recovery", "/chronic-fatigue")

    if k in ("exhausted", "exhaustion", "lethargy", "fatigue", "burnout",
             "fatigued", "lathargic", "tired"):
        return ("recovery", "/chronic-fatigue")

    # HRV
    if any(x in k for x in ["hrv", "heart rate variability"]):
        if "low" in k or "improve" in k or "increase" in k:
            return ("recovery", "/guides/low-hrv")
        return ("recovery", "/biomarkers/heart-rate-variability")

    # Stress management
    if any(x in k for x in ["stress manage", "stress technique", "dealing with stress",
                              "reduce stress", "stress reduction", "manage stress",
                              "method of managing", "what is stress",
                              "chronic stress", "reduce anxiety",
                              "how to calm down", "destress", "how to do relax",
                              "stress and anxiety", "activity to relieve",
                              "how to relax", "how to relieve stress",
                              "stress relief", "stress recovery",
                              "how stress affects"]):
        return ("recovery", "/sleep-recovery")

    if k in ("sleep", "sleeping", "stress"):
        return ("recovery", "/sleep-recovery")

    if "energy crash" in k or "afternoon crash" in k or "afternoon slump" in k or "energy levels crash" in k:
        return ("recovery", "/symptoms/afternoon-energy-crash")

    if "low energy" in k:
        return ("recovery", "/tools/energy-assessment")

    # === TESTING ===
    if any(x in k for x in ["lab test", "blood test", "blood panel", "blood work",
                              "labcorp"]):
        return ("testing", "/lab-testing")

    return None


# --- Run classification ---
rows = []
for k in sorted(keywords, key=lambda x: x["volume"], reverse=True):
    result = classify(k["keyword"])
    if result:
        cluster, page, status = result if len(result) == 3 else (result[0], result[1], "LIVE")
        rows.append({**k, "cluster": cluster, "target_page": page, "status": status})
    else:
        rows.append({**k, "cluster": "?", "target_page": "UNMAPPED", "status": "GAP"})

with open("output/keyword-page-mapping.json", "w") as f:
    json.dump(rows, f, indent=2)

with open("output/keyword-page-mapping.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["keyword", "volume", "kd", "cpc", "cluster", "target_page", "status"])
    w.writeheader()
    w.writerows(rows)

live = [r for r in rows if r["status"] == "LIVE"]
skip = [r for r in rows if r["status"] == "SKIP"]
gap = [r for r in rows if r["status"] == "GAP"]

print(f"Total keywords: {len(rows)}")
print(f"  LIVE (mapped): {len(live)}")
print(f"  SKIP (off-topic): {len(skip)}")
print(f"  GAP (unmapped): {len(gap)}")
print(f"  Coverage: {len(live)/(len(live)+len(gap))*100:.1f}%")

print("\n=== CLUSTER SUMMARY ===")
for c in ["metabolism", "hormones", "recovery", "testing"]:
    cluster_kws = [r for r in live if r["cluster"] == c]
    pages = sorted(set(r["target_page"] for r in cluster_kws))
    total_vol = sum(r["volume"] for r in cluster_kws)
    print(f"\n  {c.upper()}: {len(cluster_kws)} kws -> {len(pages)} pages, {total_vol:,} vol")
    for pg in pages:
        pg_kws = [r for r in cluster_kws if r["target_page"] == pg]
        pv = sum(r["volume"] for r in pg_kws)
        print(f"    {pg:50s} {len(pg_kws):4d} kws  {pv:>12,} vol")

if gap:
    print(f"\n=== REMAINING GAPS: {len(gap)} keywords, {sum(r['volume'] for r in gap):,} vol ===")
    for r in sorted(gap, key=lambda x: -x["volume"])[:40]:
        print(f"  {r['volume']:>8,}  {r['keyword']}")
