"""
Flask web server for health optimization site.

Serves generated report HTML, blog posts, landing pages, assessment forms,
and admin views. Deployed on Render (or locally).
"""

from __future__ import annotations

import gzip
import hashlib
import hmac
import io
import json
import logging
import secrets
import time
from datetime import datetime, date, timezone
from pathlib import Path
from xml.sax.saxutils import escape as _xml_escape

import httpx
from flask import (
    Flask,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    Response,
    send_from_directory,
    session,
    url_for,
)
from werkzeug.exceptions import HTTPException

from src.config import settings
from src.seo.cluster_topology import build_cluster_ctx, all_seo_paths
from src.storage_remote import (
    fetch_report_html,
    supabase_storage_enabled,
    supabase_storage_read_enabled,
)


# ═══════════════════════════════════════════════════════════════════════
#  App Setup
# ═══════════════════════════════════════════════════════════════════════

_STATIC_DIR = Path(__file__).resolve().parent / "static"
_STATIC_DIR.mkdir(parents=True, exist_ok=True)

app = Flask(
    __name__,
    static_folder=str(_STATIC_DIR),
    static_url_path="/static",
)
app.secret_key = settings.admin_key or "fallback-dev-key"
app.jinja_env.globals.update(
    site_name=settings.site_name,
    site_url=settings.site_url,
    ga_id=getattr(settings, "google_analytics_id", ""),
    current_year=datetime.now().year,
)

logger = logging.getLogger(__name__)

OUTPUT_DIR = settings.output_dir

# ═══════════════════════════════════════════════════════════════════════
#  Gzip After-Request Middleware
# ═══════════════════════════════════════════════════════════════════════

GZIP_MIME_PREFIXES = (
    "text/",
    "application/json",
    "application/xml",
    "application/javascript",
    "application/ld+json",
    "image/svg+xml",
)
GZIP_MIN_BYTES = 500


@app.after_request
def _gzip_response(response: Response) -> Response:
    """Gzip-compress eligible responses when the client advertises support."""
    try:
        if response.direct_passthrough:
            return response
        if response.status_code < 200 or response.status_code >= 300:
            return response
        if "Content-Encoding" in response.headers:
            return response
        if "gzip" not in (request.headers.get("Accept-Encoding", "") or "").lower():
            return response

        mimetype = (response.mimetype or "").lower()
        if not any(mimetype.startswith(p) for p in GZIP_MIME_PREFIXES):
            return response

        data = response.get_data()
        if len(data) < GZIP_MIN_BYTES:
            return response

        buf = io.BytesIO()
        with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=6) as gz:
            gz.write(data)
        compressed = buf.getvalue()

        response.set_data(compressed)
        response.headers["Content-Encoding"] = "gzip"
        response.headers["Content-Length"] = str(len(compressed))
        existing_vary = response.headers.get("Vary", "")
        if "Accept-Encoding" not in existing_vary:
            response.headers["Vary"] = (existing_vary + ", Accept-Encoding").lstrip(", ")
    except Exception as exc:
        logger.warning("gzip middleware skipped due to error: %s", exc)
    return response


# ═══════════════════════════════════════════════════════════════════════
#  Report Cache (Supabase Storage / local fallback)
# ═══════════════════════════════════════════════════════════════════════

BUTTONDOWN_API_URL = "https://api.buttondown.com/v1/subscribers"

_REPORT_CACHE: dict = {"html": None, "fetched_at": 0.0}
_REPORT_CACHE_TTL_SECONDS = 60


def _get_report_html() -> str | None:
    """Return rendered report HTML from Supabase Storage (cached) or local disk."""
    if supabase_storage_read_enabled():
        now = time.time()
        if _REPORT_CACHE["html"] and now - _REPORT_CACHE["fetched_at"] < _REPORT_CACHE_TTL_SECONDS:
            return _REPORT_CACHE["html"]
        html = fetch_report_html()
        if html:
            _REPORT_CACHE["html"] = html
            _REPORT_CACHE["fetched_at"] = now
            return html
        if _REPORT_CACHE["html"]:
            return _REPORT_CACHE["html"]

    report = OUTPUT_DIR / "report.html"
    if report.exists():
        return report.read_text(encoding="utf-8")
    return None


# ═══════════════════════════════════════════════════════════════════════
#  Nav Page Cache
# ═══════════════════════════════════════════════════════════════════════

_NAV_CACHE_PATHS = frozenset({
    "/briefing",
    "/programs",
    "/tools",
    "/results",
    "/faq",
    "/about",
    "/pricing",
})
_NAV_PAGE_CACHE: dict[str, dict] = {}
_NAV_PAGE_CACHE_TTL_SECONDS = 90


def _normalize_cache_path(path: str) -> str:
    if not path:
        return "/"
    normalized = path.rstrip("/")
    return normalized or "/"


def _serve_nav_page_cache(path: str) -> str | None:
    """Return cached HTML for a nav page, or None if stale/missing."""
    key = _normalize_cache_path(path)
    entry = _NAV_PAGE_CACHE.get(key)
    if entry and (time.time() - entry["ts"]) < _NAV_PAGE_CACHE_TTL_SECONDS:
        return entry["html"]
    return None


def _store_nav_page_cache(path: str, html: str) -> None:
    """Store rendered HTML in the nav page cache."""
    key = _normalize_cache_path(path)
    if key in _NAV_CACHE_PATHS:
        _NAV_PAGE_CACHE[key] = {"html": html, "ts": time.time()}


# ═══════════════════════════════════════════════════════════════════════
#  Stripe Webhook Helpers
# ═══════════════════════════════════════════════════════════════════════

_STRIPE_NOTIFIED_SESSION_IDS: set[str] = set()


def _stripe_signature_valid(payload: bytes, signature_header: str | None) -> bool:
    """Verify Stripe's signed webhook payload without requiring stripe-python."""
    secret = (settings.stripe_webhook_secret or "").strip()
    if not secret or not signature_header:
        return False

    parts: dict[str, list[str]] = {}
    for item in signature_header.split(","):
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        parts.setdefault(key, []).append(value)

    timestamps = parts.get("t") or []
    signatures = parts.get("v1") or []
    if not timestamps or not signatures:
        return False

    try:
        timestamp = int(timestamps[0])
    except ValueError:
        return False

    if abs(time.time() - timestamp) > 300:
        logger.warning("Stripe webhook rejected: signature timestamp outside tolerance")
        return False

    signed_payload = f"{timestamp}.".encode("utf-8") + payload
    expected = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, sig) for sig in signatures)


def _format_usd_minor_units(amount: int | None, currency: str | None) -> str:
    if amount is None:
        return "Unknown"
    currency_code = (currency or "usd").upper()
    if currency_code == "USD":
        return f"${amount / 100:,.2f}"
    return f"{amount} {currency_code}"


def _order_email_recipient() -> str:
    recipient = (settings.order_notification_email or "").strip()
    if recipient:
        return recipient
    seo_recipient = (settings.seo_email_recipient or "").strip()
    if seo_recipient and seo_recipient != "<RECIPIENT_EMAIL>":
        return seo_recipient
    return ""


def _order_from_address() -> str | None:
    addr = (settings.order_from_email or "").strip()
    if addr:
        return f"{settings.site_name} <{addr}>"
    return None


def _create_consultation_booking(stripe_session: dict) -> str | None:
    """Persist a ConsultationBooking row from Stripe session and return the assessment token."""
    from src.models import ConsultationBooking, BookingStatus, SessionLocal, init_db

    init_db()
    customer_details = stripe_session.get("customer_details") or {}
    customer_email = customer_details.get("email") or stripe_session.get("customer_email") or ""
    if not customer_email:
        logger.error("Cannot create booking: no customer email in Stripe session")
        return None

    token = secrets.token_urlsafe(32)
    db = SessionLocal()
    try:
        booking = ConsultationBooking(
            stripe_session_id=stripe_session.get("id") or "unknown",
            amount_total=stripe_session.get("amount_total"),
            currency=stripe_session.get("currency"),
            email=customer_email,
            name=customer_details.get("name") or "Unknown",
            phone=customer_details.get("phone") or "",
            booking_type="consultation",
            status=BookingStatus.CONFIRMED,
        )
        db.add(booking)
        db.commit()
        logger.info("Created consultation booking id=%s for %s", booking.id, customer_email)
        return token
    except Exception as exc:
        db.rollback()
        logger.exception("Failed to create consultation booking: %s", exc)
        return None
    finally:
        db.close()


def _send_booking_notification(stripe_session: dict) -> bool:
    """Email the site owner when a consultation booking payment completes."""
    from src.newsletter import send_email

    recipient = _order_email_recipient()
    if not recipient:
        logger.error("Booking notification skipped: ORDER_NOTIFICATION_EMAIL not set")
        return False

    customer_details = stripe_session.get("customer_details") or {}
    customer_name = customer_details.get("name") or "Unknown"
    customer_email = customer_details.get("email") or "Unknown"
    amount = _format_usd_minor_units(stripe_session.get("amount_total"), stripe_session.get("currency"))

    subject = f"New consultation booking – {amount}"
    html = f"""
    <h2>New Consultation Booking</h2>
    <p>A customer completed checkout for a health consultation.</p>
    <table cellpadding="6" cellspacing="0" style="border-collapse:collapse;">
      <tr><td><strong>Amount</strong></td><td>{_xml_escape(amount)}</td></tr>
      <tr><td><strong>Customer</strong></td><td>{_xml_escape(customer_name)}</td></tr>
      <tr><td><strong>Email</strong></td><td>{_xml_escape(customer_email)}</td></tr>
    </table>
    """

    provider = (settings.order_email_provider or "resend").strip().lower()
    from_addr = _order_from_address()
    try:
        send_email(
            subject=subject,
            html=html,
            to=recipient,
            provider=provider,
            from_addr=from_addr,
        )
        logger.info("Booking notification sent to %s", recipient)
        return True
    except Exception as exc:
        logger.exception("Failed to send booking notification: %s", exc)
        return False


# ═══════════════════════════════════════════════════════════════════════
#  HTML Stub Helper
# ═══════════════════════════════════════════════════════════════════════

def _stub_page(title: str, heading: str | None = None, body: str = "") -> str:
    """Return a minimal HTML shell for stub pages."""
    h = heading or title
    site = _xml_escape(settings.site_name)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_xml_escape(title)} | {site}</title>
  <style>
    body {{ font-family: system-ui, sans-serif; max-width: 720px; margin: 2rem auto; padding: 0 1rem; color: #1a1a2e; }}
    h1 {{ color: #16213e; }}
    a {{ color: #0f3460; }}
    .badge {{ display: inline-block; padding: 0.25em 0.75em; background: #e2e8f0; border-radius: 4px; font-size: 0.875rem; }}
  </style>
</head>
<body>
  <nav><a href="/">{site}</a></nav>
  <h1>{_xml_escape(h)}</h1>
  {body if body else '<p class="badge">Coming soon</p>'}
</body>
</html>"""


def _db_landing_page_or_stub(page_key: str, page_type: str, title: str) -> Response:
    """Serve a LandingPage from DB using the landing_page template, or stub."""
    cluster_ctx = build_cluster_ctx(request.path)
    try:
        from src.models import LandingPage, SessionLocal, init_db
        init_db()
        db = SessionLocal()
        try:
            page = db.query(LandingPage).filter_by(page_key=page_key).first()
            if page:
                return Response(
                    render_template("landing_page.html.j2", page=page, cluster_ctx=cluster_ctx),
                    content_type="text/html; charset=utf-8",
                )
        finally:
            db.close()
    except Exception as exc:
        logger.warning("DB lookup failed for landing page %s: %s", page_key, exc)

    class _FakePage:
        pass
    fake = _FakePage()
    fake.title = title
    fake.subtitle = None
    fake.summary = None
    fake.body_html = "<p>Content coming soon.</p>"
    fake.sections_json = None
    fake.faq_json = None
    fake.cluster = page_type if page_type in ("metabolism", "hormones", "recovery", "testing") else None
    fake.canonical_path = request.path
    fake.keywords_json = None
    fake.page_type = page_type
    return Response(
        render_template("landing_page.html.j2", page=fake, cluster_ctx=cluster_ctx),
        content_type="text/html; charset=utf-8",
    )


# ═══════════════════════════════════════════════════════════════════════
#  Admin Auth Helpers
# ═══════════════════════════════════════════════════════════════════════

def _admin_authenticated() -> bool:
    return session.get("admin_auth") is True


def _require_admin():
    if not _admin_authenticated():
        return redirect("/admin")
    return None


# ═══════════════════════════════════════════════════════════════════════
#  ROUTES — Health Check
# ═══════════════════════════════════════════════════════════════════════

@app.route("/health")
def health_check():
    return jsonify({"status": "ok", "ts": time.time()})


# ═══════════════════════════════════════════════════════════════════════
#  ROUTES — Core Pages
# ═══════════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    """Homepage — render the health optimization homepage."""
    try:
        from src.models import BlogPost, SessionLocal, init_db
        init_db()
        db = SessionLocal()
        try:
            posts = db.query(BlogPost).order_by(BlogPost.published_date.desc()).limit(6).all()
            return render_template("home.html.j2", posts=posts)
        except Exception:
            return render_template("home.html.j2", posts=[])
        finally:
            db.close()
    except Exception:
        return render_template("home.html.j2", posts=[])


@app.route("/how-it-works")
def how_it_works():
    return render_template("how_it_works.html.j2")


@app.route("/programs")
@app.route("/guides")
def programs():
    return render_template("programs.html.j2")


_PROGRAM_DATA = {
    "metabolic": {
        "name": "Metabolic Health Guide",
        "slug": "metabolic",
        "description": "Understand insulin resistance, blood sugar dysregulation, and metabolic dysfunction — which biomarkers matter, what optimal ranges look like, and what the research says about effective interventions. Based on ADA diagnostic guidelines and peer-reviewed research.",
        "targets": [
            "Insulin resistance and hyperinsulinemia",
            "Blood sugar dysregulation (reactive hypoglycemia, glucose spikes)",
            "Elevated visceral adiposity (waist >40\" men / >35\" women)",
            "Metabolic syndrome (3+ of: high waist circumference, high triglycerides, low HDL, high blood pressure, high fasting glucose)",
            "Weight loss resistance despite caloric deficit",
            "Post-meal fatigue and energy crashes",
            "Acanthosis nigricans (darkened skin patches on neck, armpits)",
        ],
        "process": [
            "How insulin resistance develops — and why standard tests miss it for 10-15 years",
            "The biomarkers that matter: fasting insulin, HOMA-IR, triglyceride-to-HDL ratio, HbA1c, hs-CRP, uric acid",
            "Optimal vs. 'normal' reference ranges — and why the difference matters",
            "Evidence-based dietary, exercise, and supplementation approaches (with clinical trial data)",
            "How to read and interpret your own metabolic lab results",
            "When to see a specialist — and what type of doctor to look for",
        ],
        "biomarkers": [
            "Fasting insulin (optimal <7 μIU/mL; standard range <25)",
            "Fasting glucose (optimal 72-85 mg/dL)",
            "HbA1c (optimal <5.4%; prediabetes 5.7-6.4%)",
            "HOMA-IR (optimal <1.5; >2.9 indicates insulin resistance)",
            "Triglycerides (optimal <100 mg/dL)",
            "Triglyceride-to-HDL ratio (optimal <2.0; >3.0 signals insulin resistance)",
            "hs-CRP (optimal <1.0 mg/L; metabolic inflammation marker)",
            "Uric acid (elevated levels correlate with metabolic syndrome)",
        ],
        "who_for": [
            "Gaining weight despite consistent diet and exercise",
            "Experiencing energy crashes after meals, especially carb-heavy meals",
            "Diagnosed with prediabetes or metabolic syndrome",
            "Family history of type 2 diabetes or cardiovascular disease",
            "Waist circumference above 40\" (men) or 35\" (women)",
            "Darkened skin patches on neck or armpits (acanthosis nigricans)",
            "Plateauing on GLP-1 medications (semaglutide, tirzepatide)",
        ],
        "faq": [
            {"q": "How is this different from a diet plan?", "a": "This guide focuses on the biomarker evidence — fasting insulin, HOMA-IR, triglyceride-to-HDL ratio — that identifies the specific metabolic dysfunction behind your symptoms. Understanding the root cause helps you and your doctor choose the right intervention, not just a generic caloric deficit."},
            {"q": "Do I need to be diabetic?", "a": "No. Insulin resistance typically develops 10-15 years before blood sugar becomes abnormal enough for a diabetes diagnosis. Standard fasting glucose tests miss early insulin resistance because the pancreas compensates by producing more insulin. This guide shows you what to test earlier."},
            {"q": "Can I use this without a doctor?", "a": "You can learn a lot from the guide alone — especially understanding your lab results and what optimal ranges mean. But for personalized treatment decisions, we recommend working with a doctor. We can help you find one who specializes in metabolic health."},
            {"q": "What if my doctor says my labs are 'normal'?", "a": "Standard reference ranges are based on population averages, which includes a large percentage of metabolically unhealthy people. This guide explains the difference between 'normal' and optimal. For example, fasting insulin under 25 μIU/mL is 'normal' but optimal is under 7."},
        ],
    },
    "hormones": {
        "name": "Hormone Health Guide",
        "slug": "hormones",
        "description": "Learn how testosterone, estrogen, thyroid, and cortisol work together — and what to do when they don't. Covers lab testing, optimal ranges, common misdiagnoses, and evidence-based approaches. Grounded in Endocrine Society guidelines.",
        "targets": [
            "Low testosterone (men: fatigue, reduced muscle mass, low libido, erectile dysfunction)",
            "Thyroid dysfunction (hypothyroidism symptoms: fatigue, weight gain, cold intolerance, brain fog, hair loss)",
            "Cortisol dysregulation (anxiety, insomnia, weight gain, impaired stress recovery)",
            "Perimenopause symptoms (hot flashes, night sweats, mood changes, irregular periods — affects women typically starting in mid-40s)",
            "Menopause-related changes (vasomotor symptoms affect ~80% of women)",
            "Low libido and sexual dysfunction in men and women",
            "Brain fog and cognitive changes linked to hormonal shifts",
        ],
        "process": [
            "How hormones interact — the thyroid-cortisol-testosterone axis explained",
            "The full hormone panel: total/free testosterone, estradiol, DHEA-S, SHBG, TSH, free T3/T4, cortisol, FSH, LH",
            "Why single-marker screening (TSH alone, total testosterone alone) misses dysfunction",
            "Optimal vs. standard reference ranges — age-adjusted and gender-specific",
            "Evidence-based approaches: lifestyle, nutrition, supplementation, and when HRT makes sense",
            "How to find the right endocrinologist or hormone specialist",
        ],
        "biomarkers": [
            "Total testosterone (men optimal 500-900 ng/dL; women 15-70 ng/dL)",
            "Free testosterone (men optimal 9-25 pg/mL; often low even when total is 'normal')",
            "Estradiol / E2 (varies by menstrual phase; postmenopause <30 pg/mL)",
            "TSH (optimal 1.0-2.5 mIU/L; standard range 0.4-4.5 but subclinical hypothyroidism often missed)",
            "Free T3 (optimal 3.0-4.0 pg/mL; the active thyroid hormone)",
            "Free T4 (optimal 1.1-1.5 ng/dL)",
            "DHEA-S (age-dependent; declines ~2-3% per year after age 30)",
            "SHBG (Sex Hormone Binding Globulin — high SHBG reduces bioavailable testosterone)",
            "AM Cortisol (optimal 10-18 μg/dL morning; low suggests adrenal insufficiency, high suggests chronic stress response)",
        ],
        "who_for": [
            "Unexplained fatigue not resolved by improving sleep or nutrition",
            "Losing muscle mass or gaining fat despite regular exercise",
            "Low sex drive, erectile dysfunction, or sexual dysfunction",
            "Perimenopause or menopause symptoms: hot flashes, night sweats, mood changes, vaginal dryness",
            "Suspected thyroid issues: weight gain, cold intolerance, hair thinning, constipation, depression",
            "Brain fog, difficulty concentrating, or memory changes",
            "Mood swings, anxiety, or irritability that worsened with age",
        ],
        "faq": [
            {"q": "Is this about hormone replacement therapy (HRT)?", "a": "Not exclusively. This guide covers the full picture — from understanding your lab results to lifestyle interventions to when HRT may be appropriate. We explain the evidence for and against HRT so you can have an informed conversation with your doctor."},
            {"q": "Is this relevant for both men and women?", "a": "Yes. Hormone panels and optimal ranges are gender-specific, and the guide covers both. Men's sections emphasize testosterone, SHBG, and estradiol. Women's sections include estradiol, progesterone, FSH, and menstrual cycle timing."},
            {"q": "My doctor tested TSH and said my thyroid is fine. Could something still be off?", "a": "Yes. TSH alone misses subclinical thyroid dysfunction. A complete thyroid picture requires TSH plus free T3 and free T4. You can have a 'normal' TSH with low free T3 — a common cause of fatigue and weight gain that standard screening misses."},
            {"q": "Do I need to see a doctor after reading this?", "a": "It depends on what you find. The guide helps you understand what's normal, what's optimal, and what may need medical attention. If your symptoms are significant, we recommend connecting with a specialist — and we can help match you with one."},
        ],
    },
    "recovery": {
        "name": "Sleep & Recovery Guide",
        "slug": "recovery",
        "description": "Go beyond sleep hygiene tips. This guide covers the physiological root causes of poor sleep, chronic fatigue, and low HRV — including nutrient deficiencies, cortisol dysregulation, and thyroid dysfunction.",
        "targets": [
            "Poor sleep quality despite adequate sleep duration",
            "Chronic fatigue (persistent, unexplained tiredness lasting >6 months)",
            "Low HRV (heart rate variability) indicating impaired autonomic recovery",
            "Suspected obstructive sleep apnea (snoring, witnessed apneas, daytime sleepiness)",
            "Waking up unrefreshed despite 7-8 hours of sleep",
            "Afternoon energy crashes (2-4 PM slump)",
            "Stress-related sleep disruption (cortisol-melatonin axis imbalance — 'wired but tired')",
        ],
        "process": [
            "Why 'sleep hygiene' alone doesn't fix most sleep problems",
            "The biomarkers behind fatigue: cortisol, ferritin, vitamin D, RBC magnesium, thyroid, B12",
            "Understanding your wearable data: HRV, resting heart rate, sleep stages, and what they mean",
            "Optimal vs. standard ranges — why a ferritin of 15 is 'normal' but not enough",
            "Evidence-based approaches for each root cause (deficiency, dysregulation, structural)",
            "When to get a sleep study — and how to find the right sleep medicine doctor",
        ],
        "biomarkers": [
            "Cortisol AM/PM (morning optimal 10-18 μg/dL; evening should drop significantly — flat cortisol curve indicates chronic stress)",
            "Ferritin (optimal >40-50 ng/mL for energy; deficiency common even when CBC looks normal)",
            "Vitamin D / 25-OH (optimal 40-60 ng/mL; <20 is deficient, 20-30 is insufficient)",
            "TSH / Free T3 / Free T4 (subclinical thyroid dysfunction is a top missed cause of fatigue)",
            "RBC Magnesium (optimal 5.0-6.5 mg/dL; serum magnesium misses 80% of deficiency)",
            "Vitamin B12 (optimal >500 pg/mL; deficiency causes fatigue, cognitive issues)",
            "hs-CRP (systemic inflammation marker — chronic inflammation impairs sleep architecture)",
            "CBC + iron studies (rule out anemia as fatigue cause)",
        ],
        "who_for": [
            "Tired despite sleeping 7-8 hours per night",
            "Difficulty falling asleep or staying asleep",
            "Low HRV or poor recovery scores on wearable devices (Oura, Whoop, Apple Watch, Garmin)",
            "Snoring, gasping at night, or witnessed breathing pauses during sleep",
            "High stress with poor stress recovery — 'wired but tired' pattern",
            "Afternoon energy crashes requiring caffeine to function",
            "Brain fog or cognitive sluggishness that worsens throughout the day",
        ],
        "faq": [
            {"q": "Do I need a sleep study?", "a": "Not necessarily. Many fatigue cases are caused by nutrient deficiencies, thyroid dysfunction, or cortisol dysregulation — not sleep apnea. This guide helps you figure out which root cause is most likely. If symptoms suggest sleep apnea (snoring, witnessed apneas, BMI >30), we recommend a home sleep test."},
            {"q": "What wearables does this guide cover?", "a": "We explain how to interpret data from Oura Ring, Whoop, Apple Watch, Garmin, Fitbit, or any device that tracks HRV, resting heart rate, and sleep stages. Wearable trends provide context that single lab snapshots can't."},
            {"q": "Is this just sleep hygiene advice?", "a": "No. We investigate the physiological root causes of poor sleep and recovery — cortisol dysregulation, thyroid dysfunction, iron/ferritin deficiency, magnesium depletion, vitamin D insufficiency. Sleep hygiene matters, but it doesn't fix a flat cortisol curve or a ferritin of 15."},
            {"q": "My ferritin is 'normal' — could it still be causing fatigue?", "a": "Yes. Standard lab ranges flag ferritin as low only below 12-15 ng/mL. But clinical research shows many people feel significantly better with ferritin above 40-50 ng/mL. This is one of the most commonly missed causes of unexplained fatigue."},
        ],
    },
}

@app.route("/programs/<slug>")
@app.route("/guides/<slug>")
def program_detail(slug: str):
    program = _PROGRAM_DATA.get(slug)
    if not program:
        abort(404)
    return render_template("program_detail.html.j2", program=program)


@app.route("/assessment")
def assessment_landing():
    return render_template("assessment_landing.html.j2")


@app.route("/assessment/start")
def assessment_start():
    """Create a new assessment token and redirect to the form."""
    try:
        from src.models import Assessment, AssessmentStatus, SessionLocal, init_db
        init_db()
        token = secrets.token_urlsafe(32)
        db = SessionLocal()
        try:
            assessment = Assessment(
                token=token,
                email="",
                status=AssessmentStatus.STARTED,
            )
            db.add(assessment)
            db.commit()
            return redirect(f"/assessment/{token}")
        except Exception as exc:
            db.rollback()
            logger.exception("Failed to create assessment: %s", exc)
            return redirect("/assessment?error=db")
        finally:
            db.close()
    except Exception as exc:
        logger.warning("Assessment start failed (no DB): %s", exc)
        return redirect("/assessment?error=unavailable")


@app.route("/assessment/<token>")
def assessment_form(token: str):
    try:
        from src.models import Assessment, SessionLocal, init_db
        init_db()
        db = SessionLocal()
        try:
            assessment = db.query(Assessment).filter_by(token=token).first()
            if not assessment:
                abort(404)
            return render_template("assessment_form.html.j2", assessment=assessment, token=token)
        finally:
            db.close()
    except Exception as exc:
        logger.warning("Assessment form DB error for %s: %s", token, exc)
        abort(404)


@app.route("/assessment/<token>/save", methods=["POST"])
def assessment_save(token: str):
    """Save incremental assessment progress (partial form data)."""
    from src.models import Assessment, SessionLocal, init_db

    init_db()
    db = SessionLocal()
    try:
        assessment = db.query(Assessment).filter_by(token=token).first()
        if not assessment:
            return jsonify({"error": "Assessment not found"}), 404

        data = request.get_json(silent=True) or {}

        field_map = {
            "email": "email",
            "name": "name",
            "phone": "phone",
            "demographics": "demographics_json",
            "symptoms": "symptoms_json",
            "goals": "goals_json",
            "health_history": "health_history_json",
            "lifestyle": "lifestyle_json",
            "medications": "medications_json",
        }
        for json_key, col in field_map.items():
            if json_key in data:
                setattr(assessment, col, data[json_key])

        if "utm_source" in data:
            assessment.utm_source = data["utm_source"]
        if "utm_medium" in data:
            assessment.utm_medium = data["utm_medium"]
        if "utm_campaign" in data:
            assessment.utm_campaign = data["utm_campaign"]

        db.commit()
        return jsonify({"ok": True, "token": token})
    except Exception as exc:
        db.rollback()
        logger.exception("Failed to save assessment %s: %s", token, exc)
        return jsonify({"error": "Save failed"}), 500
    finally:
        db.close()


@app.route("/assessment/<token>/submit", methods=["POST"])
def assessment_submit(token: str):
    """Mark the assessment as completed."""
    from src.models import Assessment, AssessmentStatus, SessionLocal, init_db

    init_db()
    db = SessionLocal()
    try:
        assessment = db.query(Assessment).filter_by(token=token).first()
        if not assessment:
            return jsonify({"error": "Assessment not found"}), 404

        data = request.get_json(silent=True) or {}
        for json_key, col in {
            "email": "email",
            "name": "name",
            "phone": "phone",
            "demographics": "demographics_json",
            "symptoms": "symptoms_json",
            "goals": "goals_json",
            "health_history": "health_history_json",
            "lifestyle": "lifestyle_json",
            "medications": "medications_json",
        }.items():
            if json_key in data:
                setattr(assessment, col, data[json_key])

        assessment.status = AssessmentStatus.COMPLETED
        assessment.completed_at = datetime.now(timezone.utc)
        db.commit()

        return jsonify({"ok": True, "token": token, "status": "completed"})
    except Exception as exc:
        db.rollback()
        logger.exception("Failed to submit assessment %s: %s", token, exc)
        return jsonify({"error": "Submit failed"}), 500
    finally:
        db.close()


@app.route("/pricing")
@app.route("/recommendations")
def recommendations():
    return render_template("recommendations.html.j2")


@app.route("/about")
def about():
    return render_template("about.html.j2")


@app.route("/results")
def results():
    return render_template("results.html.j2", case_studies=[])


@app.route("/faq")
def faq():
    return render_template("faq.html.j2", faqs=[])


@app.route("/book")
@app.route("/doctors")
def doctors():
    return render_template("doctors.html.j2")


# ═══════════════════════════════════════════════════════════════════════
#  ROUTES — Blog (Briefing)
# ═══════════════════════════════════════════════════════════════════════

@app.route("/briefing")
def briefing_index():
    try:
        from src.models import BlogPost, SessionLocal, init_db
        init_db()
        db = SessionLocal()
        try:
            posts = (
                db.query(BlogPost)
                .order_by(BlogPost.published_date.desc())
                .limit(50)
                .all()
            )
            return render_template("blog_index.html.j2", posts=posts)
        finally:
            db.close()
    except Exception as exc:
        logger.warning("Briefing index DB error: %s", exc)
        return render_template("blog_index.html.j2", posts=[])


@app.route("/briefing/<slug>")
def briefing_post(slug: str):
    try:
        from src.models import BlogPost, SessionLocal, init_db
        init_db()
        db = SessionLocal()
        try:
            post = db.query(BlogPost).filter_by(slug=slug).first()
            if not post:
                abort(404)
            return render_template("blog_post.html.j2", post=post)
        finally:
            db.close()
    except Exception as exc:
        logger.warning("Briefing post DB error for %s: %s", slug, exc)
        abort(404)


@app.route("/briefing/feed.xml")
def briefing_rss():
    try:
        from src.models import BlogPost, SessionLocal, init_db
        init_db()
        db = SessionLocal()
        try:
            posts = (
                db.query(BlogPost)
                .order_by(BlogPost.published_date.desc())
                .limit(25)
                .all()
            )
            base = settings.canonical_site_url
            items_xml = ""
            for p in posts:
                pub_date = p.published_date.strftime("%a, %d %b %Y 00:00:00 GMT") if p.published_date else ""
                items_xml += f"""<item>
  <title>{_xml_escape(p.title)}</title>
  <link>{_xml_escape(base)}/briefing/{_xml_escape(p.slug)}</link>
  <description>{_xml_escape(p.summary or '')}</description>
  <pubDate>{pub_date}</pubDate>
  <guid>{_xml_escape(base)}/briefing/{_xml_escape(p.slug)}</guid>
</item>\n"""

            rss = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
<channel>
  <title>{_xml_escape(settings.site_name)} – Health Briefing</title>
  <link>{_xml_escape(base)}/briefing</link>
  <description>Health optimization insights and research briefings.</description>
  <language>{_xml_escape(settings.site_locale.replace('_', '-'))}</language>
  <atom:link href="{_xml_escape(base)}/briefing/feed.xml" rel="self" type="application/rss+xml"/>
{items_xml}</channel>
</rss>"""
            return Response(rss, content_type="application/rss+xml; charset=utf-8")
        finally:
            db.close()
    except Exception:
        rss = """<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>Health Briefing</title></channel></rss>"""
        return Response(rss, content_type="application/rss+xml; charset=utf-8")


@app.route("/og/briefing/<slug>.png")
def briefing_og_image(slug: str):
    """Serve the pre-generated OG image for a blog post."""
    try:
        from src.models import BlogPost, SessionLocal, init_db
        init_db()
        db = SessionLocal()
        try:
            post = db.query(BlogPost).filter_by(slug=slug).first()
            if not post or not post.og_image_bytes:
                abort(404)
            return Response(post.og_image_bytes, content_type="image/png")
        finally:
            db.close()
    except Exception:
        abort(404)


# ═══════════════════════════════════════════════════════════════════════
#  ROUTES — SEO Hub Pages
# ═══════════════════════════════════════════════════════════════════════

_HUB_PAGES = {
    "metabolic-health": "Metabolic Health",
    "hormone-optimization": "Hormone Optimization",
    "sleep-recovery": "Sleep & Recovery",
    "lab-testing": "Lab Testing & Biomarkers",
}


@app.route("/metabolic-health")
@app.route("/hormone-optimization")
@app.route("/sleep-recovery")
@app.route("/lab-testing")
def hub_page():
    slug = request.path.lstrip("/")
    title = _HUB_PAGES.get(slug, slug.replace("-", " ").title())
    return _db_landing_page_or_stub(page_key=f"hub-{slug}", page_type="hub", title=title)


# ═══════════════════════════════════════════════════════════════════════
#  ROUTES — Top-level SEO Landing Pages
# ═══════════════════════════════════════════════════════════════════════

_TOP_LEVEL_SEO = {
    "insulin-resistance": ("metabolism", "Insulin Resistance: Causes, Symptoms & How to Reverse It"),
    "metabolic-syndrome": ("metabolism", "Metabolic Syndrome: Diagnosis, Risks & Treatment"),
    "low-testosterone": ("hormones", "Low Testosterone in Men: Symptoms, Causes & Treatment"),
    "hormone-imbalance": ("hormones", "Hormone Imbalance: Symptoms, Causes & How to Fix It"),
    "thyroid-symptoms": ("hormones", "Thyroid Symptoms: Hypothyroidism vs Hyperthyroidism"),
    "chronic-fatigue": ("recovery", "Chronic Fatigue: Causes Beyond Just Sleep"),
}


@app.route("/insulin-resistance")
@app.route("/metabolic-syndrome")
@app.route("/low-testosterone")
@app.route("/hormone-imbalance")
@app.route("/thyroid-symptoms")
@app.route("/chronic-fatigue")
def top_level_seo_page():
    slug = request.path.lstrip("/")
    cluster, title = _TOP_LEVEL_SEO.get(slug, ("metabolism", slug.replace("-", " ").title()))
    return _db_landing_page_or_stub(page_key=f"seo-{slug}", page_type=cluster, title=title)


# ═══════════════════════════════════════════════════════════════════════
#  ROUTES — SEO Spoke Pages (dynamic landing pages from DB)
# ═══════════════════════════════════════════════════════════════════════

_SPOKE_PREFIXES = {
    "symptoms": "symptom",
    "guides": "guide",
    "conditions": "condition",
    "causes": "cause",
    "compare": "comparison",
    "biomarkers": "biomarker",
    "labs": "lab",
    "why-am-i": "why-am-i",
    "faq": "faq",
}


@app.route("/symptoms/<slug>")
@app.route("/guides/<slug>")
@app.route("/conditions/<slug>")
@app.route("/causes/<slug>")
@app.route("/compare/<slug>")
@app.route("/biomarkers/<slug>")
@app.route("/labs/<slug>")
@app.route("/why-am-i/<slug>")
@app.route("/faq/<slug>")
def spoke_page(slug: str):
    prefix = request.path.split("/")[1]
    page_type = _SPOKE_PREFIXES.get(prefix, prefix)
    page_key = f"{page_type}-{slug}"
    title = slug.replace("-", " ").title()
    return _db_landing_page_or_stub(page_key=page_key, page_type=page_type, title=title)


# ═══════════════════════════════════════════════════════════════════════
#  ROUTES — Tool Pages
# ═══════════════════════════════════════════════════════════════════════

_TOOLS = {
    "energy-assessment": {
        "name": "Energy Optimization Assessment",
        "slug": "energy-assessment",
        "description": "Evaluate your energy levels across metabolic, hormonal, and recovery domains. Based on validated clinical symptom scales, this assessment identifies which systems may be contributing to fatigue, brain fog, or low performance.",
        "inputs": ["Age and sex", "Energy patterns throughout the day", "Sleep quality and duration", "Exercise habits and recovery", "Stress levels", "Dietary patterns", "Current symptoms"],
        "outputs": ["Overall energy score (0-100)", "Metabolic health risk indicator", "Hormonal health risk indicator", "Recovery quality indicator", "Recommended lab panel based on your symptoms", "Personalized next steps"],
    },
    "metabolic-score": {
        "name": "Metabolic Health Score Calculator",
        "slug": "metabolic-score",
        "description": "Estimate your metabolic health status using the five criteria defined by the AHA/NHLBI: waist circumference, triglycerides, HDL cholesterol, blood pressure, and fasting glucose. Research published in the Journal of the American College of Cardiology found only ~7% of US adults meet optimal levels for all five markers.",
        "inputs": ["Waist circumference (inches)", "Triglycerides (mg/dL) — if known", "HDL cholesterol (mg/dL) — if known", "Blood pressure (systolic/diastolic)", "Fasting glucose (mg/dL) — if known", "Age and sex"],
        "outputs": ["Metabolic health score (0-5 criteria met)", "Risk category (optimal, at-risk, metabolic syndrome)", "Which markers need attention", "Recommended lab tests for markers you don't know", "Comparison to population averages by age group"],
    },
    "hormone-checker": {
        "name": "Hormone Symptom Checker",
        "slug": "hormone-checker",
        "description": "Identify which hormonal systems may be driving your symptoms. Maps your reported symptoms to testosterone, estrogen, thyroid, cortisol, and other hormonal pathways using clinically validated symptom-to-hormone associations from endocrinology literature.",
        "inputs": ["Age, sex, and menstrual status (if applicable)", "Fatigue patterns", "Weight and body composition changes", "Mood and cognitive symptoms", "Sexual health symptoms", "Hair, skin, and temperature changes", "Menstrual irregularities (women)"],
        "outputs": ["Likelihood scores for: low testosterone, thyroid dysfunction, cortisol dysregulation, estrogen imbalance, DHEA decline", "Gender-specific hormone panel recommendation", "Symptom-to-hormone mapping explanation", "Suggested next steps"],
    },
    "sleep-score": {
        "name": "Sleep Recovery Score",
        "slug": "sleep-score",
        "description": "Assess your sleep quality and recovery capacity beyond just hours in bed. Incorporates elements from validated sleep assessment tools (Pittsburgh Sleep Quality Index, Epworth Sleepiness Scale) to evaluate sleep onset, continuity, architecture, and daytime impact.",
        "inputs": ["Typical bedtime and wake time", "Time to fall asleep", "Number of nighttime awakenings", "How refreshed you feel on waking (1-10)", "Daytime sleepiness level", "Snoring or breathing issues", "Caffeine and alcohol use", "Wearable sleep data (optional)"],
        "outputs": ["Sleep quality score (0-100)", "Sleep efficiency estimate", "Sleep apnea risk indicator (based on STOP-BANG screening criteria)", "Recovery capacity rating", "Recommended lab tests (cortisol, ferritin, thyroid, vitamin D)", "Actionable recommendations"],
    },
    "insulin-resistance-calculator": {
        "name": "Insulin Resistance Risk Calculator",
        "slug": "insulin-resistance-calculator",
        "description": "Estimate your insulin resistance risk using surrogate markers validated in clinical research. The gold standard test (hyperinsulinemic euglycemic clamp) is impractical for routine use, but HOMA-IR, triglyceride-to-HDL ratio, and waist circumference provide reliable clinical estimates per ADA guidelines.",
        "inputs": ["Fasting insulin (μIU/mL) — if known", "Fasting glucose (mg/dL) — if known", "Triglycerides (mg/dL) — if known", "HDL cholesterol (mg/dL) — if known", "Waist circumference (inches)", "Age, sex, and ethnicity", "Family history of type 2 diabetes", "Physical activity level"],
        "outputs": ["HOMA-IR score (if fasting insulin and glucose provided; optimal <1.5, insulin resistant >2.9)", "Triglyceride-to-HDL ratio (optimal <2.0; >3.0 signals insulin resistance)", "Clinical risk category (low, moderate, high)", "Which additional labs to order if data is incomplete", "Evidence-based recommendations"],
    },
}

_TOOL_SLUGS = {slug: data["name"] for slug, data in _TOOLS.items()}


@app.route("/tools")
def tools_index():
    return render_template("tools_index.html.j2")


@app.route("/tools/<slug>")
def tool_page(slug: str):
    tool = _TOOLS.get(slug)
    if not tool:
        abort(404)
    return render_template("tool_page.html.j2", tool=tool)


# ═══════════════════════════════════════════════════════════════════════
#  ROUTES — Admin
# ═══════════════════════════════════════════════════════════════════════

@app.route("/admin", methods=["GET", "POST"])
def admin_login():
    if request.method == "GET":
        if _admin_authenticated():
            return redirect("/admin/assessments")
        return Response(
            _stub_page("Admin Login", body="""
            <form method="post">
              <label>Password: <input type="password" name="password"></label>
              <button type="submit">Login</button>
            </form>"""),
            content_type="text/html; charset=utf-8",
        )

    password = (request.form.get("password") or "").strip()
    expected = (settings.admin_password or "").strip()
    if not expected or not hmac.compare_digest(password, expected):
        return Response(
            _stub_page("Admin Login", body='<p style="color:red;">Invalid password.</p><form method="post"><label>Password: <input type="password" name="password"></label><button type="submit">Login</button></form>'),
            status=401,
            content_type="text/html; charset=utf-8",
        )

    session["admin_auth"] = True
    return redirect("/admin/assessments")


@app.route("/admin/assessments")
def admin_assessments():
    guard = _require_admin()
    if guard:
        return guard

    from src.models import Assessment, SessionLocal, init_db

    init_db()
    db = SessionLocal()
    try:
        assessments = (
            db.query(Assessment)
            .order_by(Assessment.created_at.desc())
            .limit(100)
            .all()
        )
        if not assessments:
            body = "<p>No assessments yet.</p>"
        else:
            rows = ""
            for a in assessments:
                rows += f"""<tr>
                  <td>{a.id}</td>
                  <td>{_xml_escape(a.email or '')}</td>
                  <td>{_xml_escape(a.name or '')}</td>
                  <td>{_xml_escape(a.status.value if a.status else '')}</td>
                  <td>{a.created_at}</td>
                  <td><a href="/assessment/{_xml_escape(a.token)}">View</a></td>
                </tr>"""
            body = f"""<table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse;">
              <thead><tr><th>ID</th><th>Email</th><th>Name</th><th>Status</th><th>Created</th><th>Link</th></tr></thead>
              <tbody>{rows}</tbody>
            </table>"""
        return Response(
            _stub_page("Assessments – Admin", body=body),
            content_type="text/html; charset=utf-8",
        )
    finally:
        db.close()


@app.route("/admin/regen-report", methods=["POST"])
def admin_regen_report():
    guard = _require_admin()
    if guard:
        return guard

    _REPORT_CACHE["html"] = None
    _REPORT_CACHE["fetched_at"] = 0.0
    _NAV_PAGE_CACHE.clear()
    logger.info("Report cache cleared by admin")
    return jsonify({"ok": True, "message": "Report cache cleared"})


# ═══════════════════════════════════════════════════════════════════════
#  ROUTES — API: Newsletter Subscribe
# ═══════════════════════════════════════════════════════════════════════

@app.route("/api/subscribe", methods=["POST"])
def api_subscribe():
    """Accept a newsletter signup and forward to Buttondown."""
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    if not email or "@" not in email:
        return jsonify({"error": "A valid email is required."}), 400

    api_key = (settings.buttondown_api_key or "").strip()
    if not api_key:
        logger.warning("Subscribe request ignored: BUTTONDOWN_API_KEY not set")
        return jsonify({"ok": True, "note": "Subscription recorded locally."})

    try:
        resp = httpx.post(
            BUTTONDOWN_API_URL,
            json={"email": email, "tags": ["website"]},
            headers={"Authorization": f"Token {api_key}"},
            timeout=10,
        )
        if resp.status_code in (200, 201):
            logger.info("Subscribed %s via Buttondown", email)
            return jsonify({"ok": True})
        if resp.status_code == 409:
            return jsonify({"ok": True, "note": "Already subscribed."})
        logger.warning("Buttondown returned %s: %s", resp.status_code, resp.text[:300])
        return jsonify({"ok": True, "note": "Subscription may be pending."})
    except Exception as exc:
        logger.exception("Buttondown API error: %s", exc)
        return jsonify({"ok": True, "note": "Subscription recorded."})


# ═══════════════════════════════════════════════════════════════════════
#  ROUTES — Lead Magnet Download
# ═══════════════════════════════════════════════════════════════════════

_LEAD_MAGNETS = {
    "metabolic-guide": {
        "name": "The Metabolic Health Lab Guide",
        "description": "15 lab markers your doctor isn't testing — and what optimal ranges actually look like.",
    },
    "hormone-guide": {
        "name": "Hormone Optimization Starter Guide",
        "description": "How to interpret your hormone panel and what to ask your doctor for.",
    },
    "sleep-recovery-guide": {
        "name": "Sleep & Recovery Protocol",
        "description": "Evidence-based strategies for improving sleep quality beyond basic hygiene.",
    },
}


@app.route("/api/lead-magnet", methods=["POST"])
def api_lead_magnet():
    """Capture lead magnet email and record in subscriber list with tag."""
    email = (request.form.get("email") or "").strip().lower()
    magnet = (request.form.get("magnet") or "").strip()

    if not email or "@" not in email:
        return redirect("/assessment?error=invalid-email")

    magnet_info = _LEAD_MAGNETS.get(magnet, {})
    tag = f"lead-magnet-{magnet}" if magnet else "lead-magnet"

    try:
        from src.models import Subscriber, SessionLocal, init_db
        init_db()
        db = SessionLocal()
        try:
            existing = db.query(Subscriber).filter_by(email=email).first()
            if existing:
                existing.tags = list(set((existing.tags or []) + [tag]))
            else:
                sub = Subscriber(email=email, tags=[tag])
                db.add(sub)
            db.commit()
        finally:
            db.close()
    except Exception as exc:
        logger.warning("Lead magnet DB save failed: %s", exc)

    api_key = (settings.buttondown_api_key or "").strip()
    if api_key:
        try:
            httpx.post(
                BUTTONDOWN_API_URL,
                json={"email": email, "tags": ["website", tag]},
                headers={"Authorization": f"Token {api_key}"},
                timeout=10,
            )
        except Exception:
            pass

    return redirect(f"/lead-magnet/thank-you?magnet={magnet}")


@app.route("/api/doctor-request", methods=["POST"])
def api_doctor_request():
    """Capture doctor matching request and add to subscriber list."""
    name = (request.form.get("name") or "").strip()
    email = (request.form.get("email") or "").strip().lower()
    concern = (request.form.get("concern") or "").strip()
    preferences = (request.form.get("preferences") or "").strip()

    if not email or "@" not in email:
        return redirect("/doctors?error=invalid-email")

    tag = f"doctor-request-{concern}" if concern else "doctor-request"

    try:
        from src.models import Subscriber, SessionLocal, init_db
        init_db()
        db = SessionLocal()
        try:
            existing = db.query(Subscriber).filter_by(email=email).first()
            if existing:
                existing.tags = list(set((existing.tags or []) + [tag, "doctor-request"]))
            else:
                sub = Subscriber(email=email, tags=[tag, "doctor-request"])
                db.add(sub)
            db.commit()
        finally:
            db.close()
    except Exception as exc:
        logger.warning("Doctor request DB save failed: %s", exc)

    return redirect("/doctors?submitted=true")


@app.route("/lead-magnet/thank-you")
def lead_magnet_thank_you():
    magnet = request.args.get("magnet", "")
    info = _LEAD_MAGNETS.get(magnet, {"name": "Your Free Guide", "description": ""})
    return render_template("lead_magnet_thanks.html.j2", magnet=info, magnet_slug=magnet)


# ═══════════════════════════════════════════════════════════════════════
#  ROUTES — Stripe Webhook (Consultation Bookings)
# ═══════════════════════════════════════════════════════════════════════

@app.route("/webhooks/stripe", methods=["POST"])
def stripe_webhook():
    payload = request.get_data()
    sig_header = request.headers.get("Stripe-Signature")

    if not _stripe_signature_valid(payload, sig_header):
        logger.warning("Stripe webhook: invalid signature")
        abort(400)

    try:
        event = json.loads(payload)
    except (json.JSONDecodeError, ValueError):
        logger.warning("Stripe webhook: invalid JSON")
        abort(400)

    event_type = event.get("type", "")
    logger.info("Stripe webhook received: %s", event_type)

    if event_type == "checkout.session.completed":
        stripe_session = (event.get("data") or {}).get("object") or {}
        session_id = stripe_session.get("id") or ""

        if session_id in _STRIPE_NOTIFIED_SESSION_IDS:
            logger.info("Stripe session %s already processed, skipping", session_id)
            return jsonify({"ok": True})

        _STRIPE_NOTIFIED_SESSION_IDS.add(session_id)

        if len(_STRIPE_NOTIFIED_SESSION_IDS) > 5000:
            excess = list(_STRIPE_NOTIFIED_SESSION_IDS)[:2500]
            for sid in excess:
                _STRIPE_NOTIFIED_SESSION_IDS.discard(sid)

        _create_consultation_booking(stripe_session)
        _send_booking_notification(stripe_session)

    return jsonify({"ok": True})


# ═══════════════════════════════════════════════════════════════════════
#  ROUTES — Sitemap, News Sitemap, Robots.txt
# ═══════════════════════════════════════════════════════════════════════

_STATIC_SITEMAP_PATHS = [
    "/",
    "/how-it-works",
    "/guides",
    "/guides/metabolic",
    "/guides/hormones",
    "/guides/recovery",
    "/assessment",
    "/recommendations",
    "/about",
    "/results",
    "/faq",
    "/doctors",
    "/briefing",
    "/tools",
    "/tools/energy-assessment",
    "/tools/metabolic-score",
    "/tools/hormone-checker",
    "/tools/sleep-score",
    "/tools/insulin-resistance-calculator",
] + all_seo_paths()


@app.route("/sitemap.xml")
def sitemap():
    base = settings.canonical_site_url
    today = date.today().isoformat()

    urls_xml = ""
    for path in _STATIC_SITEMAP_PATHS:
        priority = "1.0" if path == "/" else "0.8"
        urls_xml += f"""<url>
  <loc>{_xml_escape(base)}{path}</loc>
  <lastmod>{today}</lastmod>
  <priority>{priority}</priority>
</url>\n"""

    try:
        from src.models import BlogPost, LandingPage, SessionLocal, init_db
        init_db()
        db = SessionLocal()
        try:
            posts = db.query(BlogPost.slug, BlogPost.published_date).order_by(BlogPost.published_date.desc()).all()
            for slug, pub_date in posts:
                lastmod = pub_date.isoformat() if pub_date else today
                urls_xml += f"""<url>
  <loc>{_xml_escape(base)}/briefing/{_xml_escape(slug)}</loc>
  <lastmod>{lastmod}</lastmod>
  <priority>0.7</priority>
</url>\n"""

            pages = db.query(LandingPage.canonical_path, LandingPage.last_generated_at).all()
            for canonical_path, gen_at in pages:
                lastmod = gen_at.strftime("%Y-%m-%d") if gen_at else today
                urls_xml += f"""<url>
  <loc>{_xml_escape(base)}{_xml_escape(canonical_path)}</loc>
  <lastmod>{lastmod}</lastmod>
  <priority>0.7</priority>
</url>\n"""
        finally:
            db.close()
    except Exception as exc:
        logger.warning("Sitemap DB lookup failed: %s", exc)

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{urls_xml}</urlset>"""
    return Response(xml, content_type="application/xml; charset=utf-8")


@app.route("/news-sitemap.xml")
def news_sitemap():
    base = settings.canonical_site_url
    pub_name = _xml_escape(settings.site_name)
    lang = settings.site_locale[:2] if settings.site_locale else "en"

    articles_xml = ""
    try:
        from src.models import BlogPost, SessionLocal, init_db
        init_db()
        db = SessionLocal()
        try:
            posts = (
                db.query(BlogPost)
                .order_by(BlogPost.published_date.desc())
                .limit(50)
                .all()
            )
            for p in posts:
                pub_date = p.published_date.isoformat() if p.published_date else date.today().isoformat()
                articles_xml += f"""<url>
  <loc>{_xml_escape(base)}/briefing/{_xml_escape(p.slug)}</loc>
  <news:news>
    <news:publication>
      <news:name>{pub_name}</news:name>
      <news:language>{lang}</news:language>
    </news:publication>
    <news:publication_date>{pub_date}</news:publication_date>
    <news:title>{_xml_escape(p.title)}</news:title>
  </news:news>
</url>\n"""
        finally:
            db.close()
    except Exception as exc:
        logger.warning("News sitemap DB lookup failed: %s", exc)

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">
{articles_xml}</urlset>"""
    return Response(xml, content_type="application/xml; charset=utf-8")


@app.route("/robots.txt")
def robots_txt():
    base = settings.canonical_site_url
    body = f"""User-agent: *
Allow: /

Sitemap: {base}/sitemap.xml
Sitemap: {base}/news-sitemap.xml
"""
    return Response(body, content_type="text/plain; charset=utf-8")


# ═══════════════════════════════════════════════════════════════════════
#  Error Handlers
# ═══════════════════════════════════════════════════════════════════════

@app.errorhandler(404)
def not_found(e):
    return Response(
        _stub_page("Page Not Found", body="<p>The page you requested does not exist.</p><p><a href='/'>Go home</a></p>"),
        status=404,
        content_type="text/html; charset=utf-8",
    )


@app.errorhandler(500)
def server_error(e):
    return Response(
        _stub_page("Server Error", body="<p>Something went wrong. Please try again later.</p>"),
        status=500,
        content_type="text/html; charset=utf-8",
    )


# ═══════════════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger.info("Starting server on port %s", settings.server_port)
    app.run(host="0.0.0.0", port=settings.server_port, debug=False)
