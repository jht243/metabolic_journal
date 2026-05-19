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
import os
import secrets
import time
from datetime import datetime, date, timezone
from pathlib import Path
from urllib.parse import urlencode
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

# SEO metadata for core pages that don't use _landing_page_seo()
_CORE_PAGE_SEO: dict[str, dict[str, str]] = {
    "/": {
        "title": f"Evidence-Based Metabolic & Hormone Health | {settings.site_name}",
        "description": "Free tools, guides, and evidence-based resources for optimizing your metabolism, hormones, and recovery. Take our assessment to get personalized insights.",
    },
    "/about": {
        "title": f"About Us | {settings.site_name}",
        "description": "Learn about our mission to make metabolic and hormonal health accessible through evidence-based education, free tools, and expert guidance.",
    },
    "/assessment": {
        "title": f"Free Metabolic Health Assessment | {settings.site_name}",
        "description": "Take our free 5-minute assessment to understand your metabolic health risks, hormone balance, and get personalized recommendations.",
    },
    "/assessment/quiz": {
        "title": f"Metabolic Health Quiz | {settings.site_name}",
        "description": "Answer a few questions about your symptoms, lifestyle, and goals to receive a personalized metabolic health action plan.",
    },
    "/book": {
        "title": f"Book a Specialist Consultation | {settings.site_name}",
        "description": "Connect with hormone and metabolic health specialists for personalized guidance on your lab results, symptoms, and treatment options.",
    },
    "/briefing": {
        "title": f"Health Briefings & Articles | {settings.site_name}",
        "description": "In-depth articles on metabolic health, hormone optimization, peptide therapy, and recovery — grounded in current clinical research.",
    },
    "/doctors": {
        "title": f"Find a Metabolic Health Specialist | {settings.site_name}",
        "description": "Browse vetted specialists in hormone therapy, metabolic health, and functional medicine. Book a consultation matched to your concerns.",
    },
    "/faq": {
        "title": f"Frequently Asked Questions | {settings.site_name}",
        "description": "Answers to common questions about metabolic health, hormone testing, insulin resistance, peptide therapy, and our assessment tools.",
    },
    "/guides": {
        "title": f"Health Optimization Guides | {settings.site_name}",
        "description": "Comprehensive guides on metabolic health, hormone balance, and recovery — from understanding biomarkers to actionable lifestyle protocols.",
    },
    "/guides/hormones": {
        "title": f"Hormone Health Guide | {settings.site_name}",
        "description": "Understand testosterone, estrogen, thyroid, and cortisol: what optimal levels look like, symptoms of imbalance, and evidence-based interventions.",
    },
    "/guides/metabolic": {
        "title": f"Metabolic Health Guide | {settings.site_name}",
        "description": "Master insulin resistance, blood sugar regulation, and metabolic dysfunction — key biomarkers, optimal ranges, and proven interventions.",
    },
    "/guides/recovery": {
        "title": f"Recovery & Sleep Guide | {settings.site_name}",
        "description": "Optimize sleep, HRV, and recovery with evidence-based protocols for better energy, cognitive function, and metabolic health.",
    },
    "/how-it-works": {
        "title": f"How It Works | {settings.site_name}",
        "description": "Learn how our metabolic health platform helps you understand your body through assessments, biomarker tracking, and specialist connections.",
    },
    "/pricing": {
        "title": f"Plans & Pricing | {settings.site_name}",
        "description": "Explore our free tools and premium options for metabolic health optimization, hormone tracking, and specialist consultations.",
    },
    "/programs": {
        "title": f"Health Programs | {settings.site_name}",
        "description": "Structured programs for metabolic health, hormone optimization, and recovery — combining education, tools, and expert guidance.",
    },
    "/recommendations": {
        "title": f"Personalized Recommendations | {settings.site_name}",
        "description": "Get evidence-based recommendations for supplements, lifestyle changes, and specialist referrals based on your metabolic health profile.",
    },
    "/results": {
        "title": f"Member Results & Case Studies | {settings.site_name}",
        "description": "Real outcomes from members who improved their metabolic health, hormone balance, and energy through our evidence-based approach.",
    },
    "/tools": {
        "title": f"Free Health Tools & Calculators | {settings.site_name}",
        "description": "Free calculators and tools for insulin resistance, metabolic score, hormone levels, sleep quality, and peptide research.",
    },
}


@app.context_processor
def _inject_default_seo():
    """Provide fallback SEO dict and JSON-LD for pages that don't explicitly pass one."""
    path = request.path.rstrip("/") or "/"
    core = _CORE_PAGE_SEO.get(path)
    if core:
        base = settings.canonical_site_url
        canonical = f"{base}{path}"
        seo = {
            "title": core["title"],
            "description": core["description"],
            "canonical": canonical,
            "site_name": settings.site_name,
            "site_url": base,
            "locale": settings.site_locale,
            "og_image": f"{base}/static/og-image.png",
            "og_type": "website",
        }
        jsonld_obj = {
            "@context": "https://schema.org",
            "@type": "WebPage",
            "name": core["title"],
            "description": core["description"],
            "url": canonical,
            "publisher": {
                "@type": "Organization",
                "name": settings.site_name,
                "url": base,
            },
        }
        return {"seo": seo, "jsonld": json.dumps(jsonld_obj)}
    return {}


_LANDING_SEO_OVERRIDES = {
    "/hormone-optimization/menopause": {
        "title": "Menopause Fatigue & Weight Gain Guide",
        "description": (
            "Understand menopause fatigue, belly fat, brain fog, insomnia, "
            "and weight gain through hormones, metabolism, sleep, and labs."
        ),
    },
    "/hormone-optimization/perimenopause": {
        "title": "Perimenopause Symptoms & Fatigue Guide",
        "description": (
            "A symptom-first perimenopause guide for fatigue, weight gain, "
            "poor sleep, brain fog, labs, and hormone-metabolic next steps."
        ),
    },
    "/sleep-recovery/sleep-apnea": {
        "title": "Sleep Apnea Fatigue & Weight Gain Guide",
        "description": (
            "Connect sleep apnea symptoms, waking tired, CPAP alternatives, "
            "home sleep testing, weight gain, and metabolic risk."
        ),
    },
    # ── CTR-optimized overrides for top-performing pages (May 2026 GSC data) ──
    "/peptides/weight-loss": {
        "title": "Best Peptides for Weight Loss in 2026 (Ranked)",
        "description": (
            "Evidence-based ranking of weight-loss peptides — from FDA-approved "
            "semaglutide (14.9% avg loss) to research compounds. Compare mechanisms, "
            "results, costs, and access."
        ),
    },
    "/peptides/aod-9604": {
        "title": "AOD-9604 Peptide: Does It Work? (2026 Evidence Review)",
        "description": (
            "Honest AOD-9604 review: Phase III trial results, why it failed, "
            "what the research actually shows, and which peptides work better "
            "for fat loss. Updated for 2026."
        ),
    },
    "/peptides/igf-1-lr3": {
        "title": "IGF-1 LR3: Mechanism, Dosing, Side Effects & Research Guide",
        "description": (
            "Complete IGF-1 LR3 guide covering how it differs from standard IGF-1, "
            "the research on muscle growth and fat loss, dosing protocols, "
            "and important safety considerations."
        ),
    },
    "/compare/cjc-1295-ipamorelin-stack": {
        "title": "CJC-1295 + Ipamorelin Stack: Protocol & Results",
        "description": (
            "The #1 prescribed GH peptide stack explained — how CJC-1295 and "
            "ipamorelin synergize for 2-5x more growth hormone, exact dosing "
            "protocol, timing, and real-world results."
        ),
    },
    "/peptides/hgh": {
        "title": "HGH Peptides vs Synthetic HGH: Complete Comparison Guide",
        "description": (
            "How growth hormone peptides (ipamorelin, sermorelin, CJC-1295) "
            "compare to synthetic HGH — efficacy, safety, cost, legality, "
            "and which approach is right for your goals."
        ),
    },
    "/peptides/glp-1": {
        "title": "GLP-1 Peptides Explained: Semaglutide, Tirzepatide & Beyond",
        "description": (
            "How GLP-1 receptor agonists work for weight loss and metabolic health. "
            "Compare semaglutide vs tirzepatide vs retatrutide — mechanisms, "
            "results, and what's coming next."
        ),
    },
    "/peptides/nad": {
        "title": "NAD+ Peptides for Longevity: NMN, NR & What Actually Works",
        "description": (
            "Evidence review of NAD+ precursors and peptides for aging and "
            "cellular health. What the research shows about NMN, NR, and "
            "NAD+ IV therapy for longevity."
        ),
    },
    "/guides/how-to-reconstitute-peptides": {
        "title": "How to Reconstitute Peptides: Guide + Calculator",
        "description": (
            "Clear instructions for reconstituting lyophilized peptides with "
            "bacteriostatic water. Includes dosing calculator, mixing ratios, "
            "storage tips, and common mistakes to avoid."
        ),
    },
    "/biomarkers/testosterone-by-age": {
        "title": "Testosterone Levels by Age: Normal vs Optimal Ranges (Chart)",
        "description": (
            "Detailed testosterone level chart by age for men 20-80+. "
            "Compare your total and free T against both lab reference ranges "
            "and optimal functional ranges. Updated 2026 data."
        ),
    },
    "/symptoms/sleep-inertia": {
        "title": "Sleep Inertia: Why You Feel Groggy Waking Up (And How to Fix It)",
        "description": (
            "The science behind morning grogginess explained. Learn what causes "
            "sleep inertia, how long it lasts, and 7 evidence-based strategies "
            "to wake up feeling alert."
        ),
    },
    "/peptides/wolverine-stack": {
        "title": "Wolverine Stack (BPC-157 + TB-500): Protocol & Recovery Guide",
        "description": (
            "Complete guide to the BPC-157 + TB-500 healing stack. Dosing protocol, "
            "reconstitution, injection sites, expected timeline, and the research "
            "behind peptide-assisted tissue repair."
        ),
    },
    "/compare/aod-9604-vs-hgh-fragment": {
        "title": "AOD-9604 vs HGH Fragment 176-191: Same Peptide?",
        "description": (
            "AOD-9604 and HGH Fragment 176-191 share a core sequence but differ "
            "in structure and research outcomes. See the evidence-based comparison "
            "of mechanisms, efficacy, and safety."
        ),
    },
    "/compare/hgh-peptides-vs-hgh": {
        "title": "HGH Peptides vs Synthetic HGH: Full Comparison",
        "description": (
            "Should you choose GH-releasing peptides or synthetic HGH? Compare "
            "efficacy, safety profiles, cost, legality, and which approach fits "
            "your goals. Evidence-based analysis."
        ),
    },
    "/compare/glp1-vs-peptides": {
        "title": "GLP-1 Drugs vs Weight-Loss Peptides Compared",
        "description": (
            "FDA-approved GLP-1 medications vs research peptides for weight loss. "
            "Compare semaglutide, tirzepatide against AOD-9604, CJC-1295 stacks "
            "— efficacy, safety, cost, and access."
        ),
    },
    "/tools/insulin-resistance-calculator": {
        "title": "Insulin Resistance Calculator: HOMA-IR & TG/HDL Ratio (Free)",
        "description": (
            "Free insulin resistance calculator using HOMA-IR and triglyceride-to-HDL "
            "ratio. Enter your lab values to assess metabolic risk with clinical "
            "interpretation of your results."
        ),
    },
}

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


@app.before_request
def _serve_from_nav_cache():
    """Serve cached HTML for static nav pages to reduce TTFB."""
    path = _normalize_cache_path(request.path)
    if path in _NAV_CACHE_PATHS and request.method == "GET":
        cached = _serve_nav_page_cache(path)
        if cached is not None:
            return Response(cached, content_type="text/html; charset=utf-8")


@app.after_request
def _populate_nav_cache(response: Response) -> Response:
    """Cache HTML responses for nav pages on first render."""
    if request.method == "GET" and response.status_code == 200:
        path = _normalize_cache_path(request.path)
        if path in _NAV_CACHE_PATHS:
            ct = (response.content_type or "").lower()
            if "text/html" in ct and "Content-Encoding" not in response.headers:
                _store_nav_page_cache(path, response.get_data(as_text=True))
    return response


@app.after_request
def _static_cache_headers(response: Response) -> Response:
    """Set long cache headers for immutable static assets (fonts, icons)."""
    if request.path.startswith("/static/"):
        if request.path.endswith((".woff2", ".woff", ".ttf")):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        elif request.path.endswith((".ico", ".svg", ".png", ".webp")):
            response.headers["Cache-Control"] = "public, max-age=604800"
    return response


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
    "/",
    "/briefing",
    "/programs",
    "/tools",
    "/results",
    "/faq",
    "/about",
    "/pricing",
    "/assessment",
    "/how-it-works",
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
            to=recipient,
            subject=subject,
            html_body=html,
            provider_name=provider,
            from_override=from_addr,
        )
        logger.info("Booking notification sent to %s", recipient)
        return True
    except Exception as exc:
        logger.exception("Failed to send booking notification: %s", exc)
        return False


def _send_doctor_request_notification(
    *,
    name: str,
    email: str,
    concern: str,
    location: str,
    preferences: str,
    source: str,
    result_context: str,
    submitted_at: str,
) -> bool:
    """Email the site owner when someone requests a specialist match."""
    from src.newsletter import send_email

    recipient = _order_email_recipient()
    if not recipient:
        logger.info("Doctor request notification skipped: notification email not set")
        return False

    subject = f"New specialist appointment request - {concern or 'general'}"
    html = f"""
    <h2>New Specialist Appointment Request</h2>
    <table cellpadding="6" cellspacing="0" style="border-collapse:collapse;">
      <tr><td><strong>Name</strong></td><td>{_xml_escape(name or 'Unknown')}</td></tr>
      <tr><td><strong>Email</strong></td><td>{_xml_escape(email)}</td></tr>
      <tr><td><strong>Concern</strong></td><td>{_xml_escape(concern or 'general')}</td></tr>
      <tr><td><strong>Location / Telehealth</strong></td><td>{_xml_escape(location or 'Not provided')}</td></tr>
      <tr><td><strong>Source</strong></td><td>{_xml_escape(source or 'unknown')}</td></tr>
      <tr><td><strong>Result Context</strong></td><td>{_xml_escape(result_context or 'None')}</td></tr>
      <tr><td><strong>Submitted</strong></td><td>{_xml_escape(submitted_at)}</td></tr>
    </table>
    <p><strong>Notes</strong></p>
    <p>{_xml_escape(preferences or 'None')}</p>
    """

    provider = (settings.order_email_provider or "resend").strip().lower()
    from_addr = _order_from_address()
    try:
        send_email(
            to=recipient,
            subject=subject,
            html_body=html,
            provider_name=provider,
            from_override=from_addr,
        )
        logger.info("Doctor request notification sent to %s", recipient)
        return True
    except Exception as exc:
        logger.exception("Failed to send doctor request notification: %s", exc)
        return False


def _send_feedback_notification(
    *,
    feedback: str,
    page_url: str,
    user_agent: str,
    submitted_at: datetime,
) -> bool:
    """Email the site owner when a visitor sends product feedback."""
    from src.newsletter import send_email

    recipient = "jonathan@pipelinemarketing.io"
    site_name = "Metabolic Journal"
    submitted_date = submitted_at.date().isoformat()
    submitted_iso = submitted_at.isoformat()
    subject = f"New Metabolic Journal feedback - {submitted_date}"
    html = f"""
    <h2>New Feedback</h2>
    <table cellpadding="6" cellspacing="0" style="border-collapse:collapse;">
      <tr><td><strong>Date</strong></td><td>{_xml_escape(submitted_iso)}</td></tr>
      <tr><td><strong>Site</strong></td><td>{_xml_escape(site_name)}</td></tr>
      <tr><td><strong>Page URL</strong></td><td>{_xml_escape(page_url or 'Not provided')}</td></tr>
      <tr><td><strong>User Agent</strong></td><td>{_xml_escape(user_agent or 'Not provided')}</td></tr>
    </table>
    <p><strong>Feedback</strong></p>
    <p>{_xml_escape(feedback)}</p>
    """

    provider = (settings.order_email_provider or settings.seo_email_provider or "resend").strip().lower()
    from_addr = _order_from_address()
    try:
        result = send_email(
            to=recipient,
            subject=subject,
            html_body=html,
            provider_name=provider,
            from_override=from_addr,
        )
        if result.get("success"):
            logger.info("Feedback notification sent to %s", recipient)
            return True
        logger.error("Feedback notification failed: %s", result)
        return False
    except Exception as exc:
        logger.exception("Failed to send feedback notification: %s", exc)
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


def _landing_page_seo(page) -> dict:
    """Build SERP metadata for generated SEO landing pages."""
    base = settings.canonical_site_url
    canonical_path = getattr(page, "canonical_path", request.path) or request.path
    canonical = f"{base}{canonical_path}"
    override = _LANDING_SEO_OVERRIDES.get(canonical_path, {})
    title = (override.get("title") or getattr(page, "title", "") or settings.site_name).strip()
    description = (
        override.get("description")
        or getattr(page, "summary", None)
        or getattr(page, "subtitle", None)
        or ""
    ).strip()
    if len(description) > 160:
        description = description[:157].rsplit(" ", 1)[0].rstrip(" ,.;:") + "..."

    keywords = getattr(page, "keywords_json", None) or []
    if isinstance(keywords, str):
        keywords = [k.strip() for k in keywords.split(",") if k.strip()]

    raw_section = (getattr(page, "page_type", "") or "Health").title()
    section = "Guide" if raw_section == "Hub" else raw_section

    suffix = f" | {settings.site_name}"
    full_title = f"{title}{suffix}"
    if len(full_title) > 60:
        full_title = title[:60] if len(title) > 60 else title

    return {
        "title": full_title,
        "description": description,
        "keywords": ", ".join(keywords) if keywords else "",
        "canonical": canonical,
        "site_name": settings.site_name,
        "site_url": base,
        "locale": settings.site_locale,
        "og_image": f"{base}/static/og-image.png",
        "og_type": "article",
        "section": section,
        "article_tags": keywords[:10],
    }


def _landing_page_jsonld(page, seo: dict) -> str:
    """Generate Article JSON-LD for a landing page (+ HowTo for guides)."""
    import re
    article = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": seo.get("title", ""),
        "description": seo.get("description", ""),
        "url": seo.get("canonical", ""),
        "image": seo.get("og_image", ""),
        "publisher": {
            "@type": "Organization",
            "name": settings.site_name,
            "url": settings.canonical_site_url,
        },
    }

    page_type = getattr(page, "page_type", "")
    sections = getattr(page, "sections_json", None) or []
    if page_type == "guide" and sections:
        for section in sections:
            content = section.get("content", "")
            if "<ol>" in content:
                steps_html = re.findall(r"<li>(.*?)</li>", content, re.DOTALL)
                if len(steps_html) >= 3:
                    howto_steps = []
                    for i, step_html in enumerate(steps_html, 1):
                        step_text = re.sub(r"<[^>]+>", "", step_html).strip()
                        howto_steps.append({
                            "@type": "HowToStep",
                            "position": i,
                            "text": step_text,
                        })
                    howto = {
                        "@context": "https://schema.org",
                        "@type": "HowTo",
                        "name": seo.get("title", ""),
                        "description": seo.get("description", ""),
                        "step": howto_steps,
                    }
                    return json.dumps([article, howto])

    return json.dumps(article)


def _db_landing_page_or_stub(page_key: str, page_type: str, title: str) -> Response:
    """Serve a LandingPage from static dict first (instant), then DB, then stub."""
    cluster_ctx = build_cluster_ctx(request.path)

    # 1) Try static content first — zero latency, no network
    try:
        from scripts.generate_seo_pages import PAGES as _STATIC_PAGES
        static = _STATIC_PAGES.get(request.path)
        if static:
            class _StaticPage:
                pass
            sp = _StaticPage()
            sp.title = static.title
            sp.subtitle = static.subtitle
            sp.summary = static.summary
            sp.body_html = static.body_html
            sp.sections_json = static.sections
            sp.faq_json = static.faqs
            sp.keywords_json = static.keywords
            sp.cluster = static.cluster
            sp.canonical_path = static.canonical_path
            sp.page_type = static.page_type
            sp.reviewed_by = getattr(static, "reviewed_by", None) or "Metabolic Journal Medical Advisory Board"
            sp.reviewed_at = getattr(static, "reviewed_at", None) or "2026-05-01"
            from src.seo.internal_links import inject_internal_links
            sp.body_html = inject_internal_links(sp.body_html, request.path)
            if sp.sections_json:
                sp.sections_json = [
                    {**s, "content": inject_internal_links(s.get("content", ""), request.path)}
                    for s in sp.sections_json
                ]
            seo = _landing_page_seo(sp)
            return Response(
                render_template(
                    "landing_page.html.j2",
                    page=sp,
                    cluster_ctx=cluster_ctx,
                    seo=seo,
                    jsonld=_landing_page_jsonld(sp, seo),
                ),
                content_type="text/html; charset=utf-8",
            )
    except Exception as exc:
        logger.warning("Static page lookup failed for %s: %s", request.path, exc)

    # 2) Fall back to database
    try:
        from src.models import LandingPage, SessionLocal, init_db
        init_db()
        db = SessionLocal()
        try:
            page = db.query(LandingPage).filter_by(page_key=page_key).first()
            if page:
                from src.seo.internal_links import inject_internal_links
                page.body_html = inject_internal_links(page.body_html or "", request.path)
                if page.sections_json:
                    page.sections_json = [
                        {**s, "content": inject_internal_links(s.get("content", ""), request.path)}
                        for s in page.sections_json
                    ]
                if not page.reviewed_by:
                    page.reviewed_by = "Metabolic Journal Medical Advisory Board"
                    page.reviewed_at = "2026-05-01"
                seo = _landing_page_seo(page)
                return Response(
                    render_template(
                        "landing_page.html.j2",
                        page=page,
                        cluster_ctx=cluster_ctx,
                        seo=seo,
                        jsonld=_landing_page_jsonld(page, seo),
                    ),
                    content_type="text/html; charset=utf-8",
                )
        finally:
            db.close()
    except Exception as exc:
        logger.warning("DB lookup failed for landing page %s: %s", page_key, exc)

    # 3) Stub fallback
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
    seo = _landing_page_seo(fake)
    return Response(
        render_template(
            "landing_page.html.j2",
            page=fake,
            cluster_ctx=cluster_ctx,
            seo=seo,
            jsonld=_landing_page_jsonld(fake, seo),
        ),
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
        "body_html": """
<h2>What Is Insulin Resistance?</h2>

<p>Insulin resistance is a condition in which your cells — primarily in muscle, liver, and fat tissue — become progressively less responsive to the hormone insulin. When this happens, your pancreas compensates by producing <strong>more insulin</strong> to force glucose into cells. For years or even decades, this compensatory hyperinsulinemia keeps your blood sugar in the "normal" range, which is exactly why standard blood tests miss it.</p>

<p>Insulin resistance is not a binary state. It exists on a spectrum: from mild postprandial hyperinsulinemia (excessive insulin after meals) to full-blown metabolic syndrome and eventually type 2 diabetes. The critical insight is that <strong>insulin rises long before glucose does</strong>. By the time fasting glucose is elevated, you may have been insulin resistant for 10–15 years.</p>

<blockquote>
<p>"Hyperinsulinemia precedes hyperglycemia by as much as 24 years. Measuring glucose alone to detect metabolic disease is like measuring smoke damage to detect a fire — by the time you see it, the house has been burning for years." — Dr. Joseph Kraft, <em>Diabetes Epidemic and You</em></p>
</blockquote>

<p>According to NHANES data analyzed by researchers at the University of North Carolina, approximately <strong>88% of American adults</strong> have at least one marker of metabolic dysfunction. Only 12% are considered metabolically healthy by all five criteria (waist circumference, fasting glucose, HbA1c, blood pressure, and lipid ratios). This is not a niche condition — it is the dominant health crisis of our time.</p>

<h2>How Insulin Resistance Develops: The Underlying Mechanism</h2>

<p>Understanding how insulin resistance develops is essential for reversing it. The process involves several interconnected pathways:</p>

<h3>1. Chronic Hyperinsulinemia and Receptor Downregulation</h3>

<p>When cells are continuously exposed to high levels of insulin — driven by frequent eating, high glycemic loads, and sedentary behavior — they downregulate their insulin receptors. Think of it like hearing loss from chronic loud noise exposure: the signal doesn't get weaker, but the receiver becomes less sensitive. This forces the pancreas to produce even more insulin, creating a vicious cycle.</p>

<h3>2. Visceral Fat Accumulation and Inflammatory Signaling</h3>

<p>Visceral adipose tissue (the fat surrounding your organs, not subcutaneous fat under your skin) is metabolically active. It secretes pro-inflammatory cytokines — including TNF-alpha, IL-6, and resistin — that directly impair insulin signaling in muscle and liver cells. Visceral fat also releases free fatty acids into the portal vein, driving hepatic insulin resistance and fatty liver disease. This is why <strong>waist circumference</strong> is a better predictor of metabolic risk than BMI.</p>

<h3>3. Hepatic Insulin Resistance and De Novo Lipogenesis</h3>

<p>When the liver becomes insulin resistant, it fails to suppress glucose production even when insulin is elevated. Simultaneously, high insulin drives <em>de novo lipogenesis</em> — the conversion of excess carbohydrates into triglycerides. This produces the characteristic lipid pattern of metabolic syndrome: <strong>high triglycerides, low HDL, and small dense LDL particles</strong> (pattern B). Non-alcoholic fatty liver disease (NAFLD) — now affecting roughly 25% of the global population — is fundamentally a disease of hepatic insulin resistance.</p>

<h3>4. Mitochondrial Dysfunction and Oxidative Stress</h3>

<p>Insulin-resistant muscle cells show reduced mitochondrial density and impaired oxidative phosphorylation. This means they are less efficient at burning fatty acids for fuel, leading to intramyocellular lipid accumulation that further worsens insulin signaling. Chronic oxidative stress damages cell membranes, proteins, and DNA, accelerating the progression from insulin resistance to overt diabetes.</p>

<h2>The Progression: From Insulin Resistance to Prediabetes to Type 2 Diabetes</h2>

<p>Metabolic disease follows a predictable trajectory, and understanding where you are on this path determines what interventions are most effective:</p>

<ol>
<li><strong>Stage 1 — Compensated Insulin Resistance:</strong> Fasting glucose and HbA1c appear normal. Fasting insulin is elevated (>7 µIU/mL). Postprandial insulin spikes are excessive. This stage can last 10–20 years. Standard blood panels will not detect it.</li>
<li><strong>Stage 2 — Impaired Glucose Tolerance (Prediabetes):</strong> The pancreas begins to falter. Fasting glucose rises to 100–125 mg/dL, and/or HbA1c reaches 5.7–6.4%. Postprandial glucose exceeds 140 mg/dL at the 2-hour mark. Beta-cell function has declined approximately 50% by this stage.</li>
<li><strong>Stage 3 — Type 2 Diabetes:</strong> Fasting glucose ≥126 mg/dL and/or HbA1c ≥6.5%. Beta-cell dysfunction is significant, and the capacity for insulin secretion is progressively lost. Microvascular complications (retinopathy, nephropathy, neuropathy) may already be present at diagnosis.</li>
<li><strong>Stage 4 — Advanced T2D with Complications:</strong> Insulin dependence may develop as beta-cell mass is lost. Cardiovascular disease risk is dramatically elevated. End-organ damage progresses.</li>
</ol>

<div class="callout-box">
<h3>Key Takeaway</h3>
<p>The earlier you intervene, the more reversible the damage. Stage 1 and Stage 2 are largely reversible through dietary, exercise, and lifestyle changes. By Stage 3, reversal is still possible but requires more aggressive intervention. Don't wait for a diabetes diagnosis — test your fasting insulin now.</p>
</div>

<h2>Why Standard Blood Tests Miss Insulin Resistance</h2>

<p>If you've had a routine annual physical, your doctor likely ordered a basic metabolic panel or comprehensive metabolic panel. These tests include <strong>fasting glucose</strong> and sometimes <strong>HbA1c</strong>. Here's the problem: these tests only detect the <em>downstream consequences</em> of insulin resistance, not the condition itself.</p>

<p>Dr. Joseph Kraft, a pathologist who performed over 14,000 insulin assays at St. Joseph Hospital in Chicago, identified five distinct insulin response patterns during oral glucose tolerance tests (OGTT). He demonstrated that many patients with completely normal fasting glucose had wildly abnormal insulin responses — what he termed <strong>"diabetes in situ"</strong> or occult diabetes. In his dataset, up to 75% of people with normal glucose tolerance already showed pathological insulin patterns.</p>

<p>The standard reference ranges for fasting glucose (70–99 mg/dL) and HbA1c (<5.7%) were established based on population averages — not on optimal metabolic health. As the population has become increasingly metabolically unhealthy, these ranges have shifted upward, normalizing values that would have been considered concerning decades ago.</p>

<blockquote>
<p>"Normal" lab ranges reflect the 95th percentile of a sick population. An optimal fasting insulin of 2–5 µIU/mL is very different from the lab reference range of 2–25 µIU/mL. The fact that 25 µIU/mL doesn't get flagged doesn't mean it's healthy — it means a lot of people are insulin resistant.</p>
</blockquote>

<h2>The Metabolic Health Blood Panel: Which Tests to Get</h2>

<p>To truly assess your metabolic health, you need tests that measure <em>insulin</em>, not just glucose. Here is the comprehensive metabolic panel that every adult should request:</p>

<table>
<thead>
<tr>
<th>Biomarker</th>
<th>Standard "Normal" Range</th>
<th>Optimal Range</th>
<th>Why It Matters</th>
</tr>
</thead>
<tbody>
<tr>
<td><strong>Fasting Insulin</strong></td>
<td>2–25 µIU/mL</td>
<td>2–5 µIU/mL</td>
<td>The single most important test for early IR detection. Elevated insulin is the earliest sign.</td>
</tr>
<tr>
<td><strong>HOMA-IR</strong></td>
<td>&lt;2.5</td>
<td>&lt;1.0</td>
<td>Calculated from fasting insulin × fasting glucose ÷ 405. Gold standard surrogate for insulin sensitivity.</td>
</tr>
<tr>
<td><strong>Fasting Glucose</strong></td>
<td>70–99 mg/dL</td>
<td>75–89 mg/dL</td>
<td>Elevated only after significant beta-cell dysfunction. A lagging indicator.</td>
</tr>
<tr>
<td><strong>HbA1c</strong></td>
<td>&lt;5.7%</td>
<td>4.8–5.2%</td>
<td>Reflects 90-day average blood sugar. Can be affected by RBC turnover, anemias, and hemoglobin variants.</td>
</tr>
<tr>
<td><strong>Triglycerides</strong></td>
<td>&lt;150 mg/dL</td>
<td>&lt;80 mg/dL</td>
<td>Elevated triglycerides reflect hepatic de novo lipogenesis driven by insulin resistance.</td>
</tr>
<tr>
<td><strong>Triglyceride/HDL Ratio</strong></td>
<td>&lt;3.5</td>
<td>&lt;1.0</td>
<td>The best lipid-based proxy for insulin resistance. Ratio &gt;3.0 is strongly correlated with small dense LDL.</td>
</tr>
<tr>
<td><strong>HDL Cholesterol</strong></td>
<td>&gt;40 mg/dL (men), &gt;50 (women)</td>
<td>&gt;60 mg/dL</td>
<td>Low HDL is driven by the same insulin-resistant lipid metabolism that raises triglycerides.</td>
</tr>
<tr>
<td><strong>hs-CRP</strong></td>
<td>&lt;3.0 mg/L</td>
<td>&lt;0.5 mg/L</td>
<td>Marker of systemic inflammation. Chronic low-grade inflammation is both a cause and consequence of IR.</td>
</tr>
<tr>
<td><strong>Uric Acid</strong></td>
<td>3.5–7.2 mg/dL (men)</td>
<td>&lt;5.5 mg/dL</td>
<td>Elevated by fructose metabolism and insulin-driven renal retention. Predicts metabolic syndrome independently.</td>
</tr>
<tr>
<td><strong>GGT</strong></td>
<td>0–65 U/L</td>
<td>&lt;20 U/L</td>
<td>Sensitive early marker of fatty liver and hepatic insulin resistance, often elevated before ALT.</td>
</tr>
<tr>
<td><strong>Fasting C-Peptide</strong></td>
<td>0.8–3.1 ng/mL</td>
<td>0.8–1.8 ng/mL</td>
<td>Produced 1:1 with insulin but not cleared by the liver. More stable measure of pancreatic insulin output.</td>
</tr>
</tbody>
</table>

<h3>HOMA-IR: The Gold Standard Surrogate Test for Insulin Resistance</h3>

<p><strong>HOMA-IR</strong> (Homeostatic Model Assessment of Insulin Resistance) is calculated using a simple formula:</p>

<p><strong>HOMA-IR = (Fasting Insulin µIU/mL × Fasting Glucose mg/dL) ÷ 405</strong></p>

<p>A HOMA-IR score below 1.0 indicates excellent insulin sensitivity. Scores between 1.0 and 1.9 suggest early insulin resistance. Scores above 2.0 indicate significant insulin resistance, and scores above 2.9 are strongly associated with metabolic syndrome. This single calculation, derived from a standard blood draw, provides more metabolic information than fasting glucose or HbA1c alone.</p>

<p>Most labs do not automatically calculate HOMA-IR, but if you have your fasting insulin and fasting glucose values, you can calculate it yourself. Importantly, both tests must be drawn <strong>fasting</strong> (12–14 hours with water only) for the calculation to be valid.</p>

<h2>How to Know If You Have Insulin Resistance: Signs and Symptoms</h2>

<p>Beyond lab tests, insulin resistance often produces recognizable clinical signs. You may have insulin resistance if you experience several of the following:</p>

<ul>
<li><strong>Weight loss resistance</strong> — difficulty losing weight despite caloric restriction, particularly abdominal fat</li>
<li><strong>Post-meal fatigue</strong> — feeling sleepy, foggy, or needing to nap after eating, especially carbohydrate-heavy meals</li>
<li><strong>Carbohydrate cravings</strong> — intense hunger 2–3 hours after meals, driven by reactive hypoglycemia from insulin overshoot</li>
<li><strong>Acanthosis nigricans</strong> — dark, velvety skin patches on the neck, armpits, or groin (a direct effect of hyperinsulinemia on skin cells)</li>
<li><strong>Skin tags</strong> — small soft growths, particularly around the neck and armpits, correlated with insulin resistance in clinical studies</li>
<li><strong>Waist-to-hip ratio &gt;0.9 (men) or &gt;0.85 (women)</strong> — indicating visceral fat accumulation</li>
<li><strong>High blood pressure</strong> — insulin promotes sodium retention and sympathetic nervous system activation</li>
<li><strong>PCOS symptoms (women)</strong> — irregular periods, hirsutism, acne, and infertility are driven by hyperinsulinemia stimulating ovarian androgen production</li>
<li><strong>Elevated liver enzymes</strong> — ALT or GGT elevation may indicate non-alcoholic fatty liver disease</li>
<li><strong>Gout or elevated uric acid</strong> — insulin impairs renal uric acid excretion</li>
</ul>

<div class="callout-box">
<h3>Self-Assessment Checklist</h3>
<p>If you have 3 or more of the signs listed above, request a fasting insulin and HOMA-IR test from your doctor. If your doctor is unfamiliar with fasting insulin testing, an endocrinologist or functional medicine physician can order it. You can also order it yourself through direct-to-consumer lab services.</p>
</div>

<h2>Best Diet for Insulin Resistance: Evidence-Based Approaches</h2>

<p>Dietary intervention is the single most powerful tool for reversing insulin resistance. The research supports several approaches, and the best one for you depends on your current metabolic status, preferences, and adherence capacity.</p>

<h3>Low-Carbohydrate and Ketogenic Diets</h3>

<p>Carbohydrate restriction directly reduces the glycemic load that drives insulin secretion. The Virta Health clinical trial (2018, published in <em>Diabetes Therapy</em>) demonstrated that a well-formulated ketogenic diet sustained over 2 years produced:</p>

<ul>
<li>HbA1c reduction of 0.9% (from 7.6% to 6.3%) at 1 year</li>
<li>60% of participants reversed their diabetes diagnosis (HbA1c &lt;6.5% off medications)</li>
<li>94% of participants reduced or eliminated insulin therapy</li>
<li>Significant improvements in triglycerides, HDL, hs-CRP, and liver enzymes</li>
</ul>

<p>A practical low-carb approach for insulin resistance targets <strong>50–100g of net carbohydrates per day</strong>, emphasizing non-starchy vegetables, quality proteins, and healthy fats including olive oil, avocado, nuts, and fatty fish. More aggressive ketogenic approaches (&lt;20–30g net carbs) may be appropriate for those with HbA1c above 6.0% or HOMA-IR above 3.0.</p>

<h3>Mediterranean Diet</h3>

<p>The PREDIMED trial — a landmark randomized controlled trial with over 7,400 participants — demonstrated that a Mediterranean diet supplemented with extra-virgin olive oil or nuts reduced the incidence of type 2 diabetes by 40% compared to a low-fat control diet. The Mediterranean pattern emphasizes:</p>

<ul>
<li>Extra-virgin olive oil as the primary fat source (≥4 tablespoons/day in the trial)</li>
<li>Fatty fish 2–3 times per week (sardines, mackerel, salmon)</li>
<li>Abundant non-starchy vegetables and leafy greens</li>
<li>Nuts and seeds (particularly walnuts and almonds)</li>
<li>Moderate legume consumption</li>
<li>Minimal refined grains, seed oils, and added sugars</li>
</ul>

<p>For those who find strict carbohydrate restriction difficult to sustain, a Mediterranean approach that naturally limits refined carbohydrates while emphasizing anti-inflammatory fats and polyphenol-rich foods is a strong evidence-based alternative.</p>

<h3>Time-Restricted Eating and Intermittent Fasting</h3>

<p>Time-restricted eating (TRE) — confining all food intake to a window of 8–10 hours — leverages circadian biology to improve insulin sensitivity. Research from the Salk Institute has demonstrated that TRE improves metabolic markers independent of calorie reduction. A 2022 study in <em>Cell Metabolism</em> found that an 8-hour eating window (early in the day) reduced fasting insulin, HOMA-IR, and inflammatory markers in adults with metabolic syndrome.</p>

<p>Key principles for TRE with insulin resistance:</p>

<ul>
<li>Eat your largest meal earlier in the day — insulin sensitivity peaks in the morning and declines after 3 PM</li>
<li>Stop eating at least 3 hours before sleep — late-night eating impairs glucose disposal and melatonin antagonizes insulin</li>
<li>A 16:8 protocol (16 hours fasting, 8 hours eating) is well-tolerated and effective for most people</li>
<li>Extended fasting (24–72 hours) has stronger effects on insulin levels but should be supervised by a physician, particularly if you are on medications</li>
</ul>

<blockquote>
<p>The combination of a lower-carbohydrate dietary pattern with time-restricted eating produces synergistic effects on insulin sensitivity. A 2023 meta-analysis in <em>Obesity Reviews</em> found that combining carbohydrate restriction with TRE reduced HOMA-IR by an average of 1.4 points — roughly double the effect of either strategy alone.</p>
</blockquote>

<h2>Exercise for Insulin Resistance: What the Research Shows</h2>

<p>Exercise improves insulin sensitivity through mechanisms that are partially independent of weight loss: increased GLUT4 transporter expression, improved mitochondrial function, reduced intramyocellular lipids, and decreased visceral fat. The type, intensity, and timing of exercise all matter.</p>

<h3>Resistance Training (Non-Negotiable)</h3>

<p>Skeletal muscle is the largest glucose disposal site in the body. Building and maintaining muscle mass directly increases your metabolic "sink" for glucose. A meta-analysis of 24 randomized controlled trials (published in <em>Sports Medicine</em>, 2022) found that resistance training reduced HOMA-IR by 0.64 points on average, with effects persisting for 24–48 hours after each session.</p>

<p>Recommended protocol:</p>
<ul>
<li>3–4 sessions per week targeting all major muscle groups</li>
<li>Compound movements (squats, deadlifts, rows, presses) that recruit the most muscle mass</li>
<li>Progressive overload — gradually increasing weight or reps over time</li>
<li>8–12 reps per set at 65–80% of one-rep max for hypertrophy; lower reps with heavier weight also effective</li>
</ul>

<h3>Zone 2 Cardio (Aerobic Base Building)</h3>

<p>Zone 2 exercise — the intensity at which you can still hold a conversation but are breathing noticeably harder — targets mitochondrial biogenesis and fat oxidation. Research by Dr. Iñigo San-Millán at the University of Colorado has shown that Zone 2 training specifically improves mitochondrial function in a way that higher-intensity exercise does not replicate.</p>

<ul>
<li>150–180 minutes per week (e.g., 3–4 sessions of 40–50 minutes)</li>
<li>Walking, cycling, swimming, rowing — any sustained movement at conversational pace</li>
<li>Heart rate roughly 60–70% of max (180 minus your age is a rough guide)</li>
</ul>

<h3>Post-Meal Walking</h3>

<p>A simple 10–15 minute walk after meals reduces postprandial glucose excursions by 30–50%, according to a 2022 meta-analysis in <em>Sports Medicine</em>. This is one of the highest-yield metabolic interventions available, requiring no equipment and minimal time. The mechanism is straightforward: contracting muscles absorb glucose from the bloodstream via insulin-independent GLUT4 translocation.</p>

<div class="callout-box">
<h3>Minimum Effective Exercise Protocol for Insulin Resistance</h3>
<p>If you do nothing else: walk for 15 minutes after each meal (45 min/day total) and perform 2 full-body resistance training sessions per week. This combination addresses both acute postprandial glucose management and long-term insulin sensitivity through increased muscle mass. Build from there.</p>
</div>

<h2>Supplements for Insulin Resistance: What the Evidence Supports</h2>

<p>Supplements are not a substitute for dietary and exercise interventions, but several have meaningful clinical evidence supporting their use as adjuncts. The following have the strongest data:</p>

<h3>Berberine</h3>

<p>Berberine activates AMPK (the same metabolic pathway targeted by metformin) and has been shown in multiple RCTs to reduce fasting glucose by 15–20 mg/dL, HbA1c by 0.5–0.9%, and HOMA-IR significantly. A 2021 meta-analysis of 46 trials found effects comparable to metformin for glucose and HbA1c reduction. Standard dosing is <strong>500mg two to three times daily with meals</strong>. Note: berberine can interact with medications metabolized by CYP3A4, CYP2D6, and CYP2C9 enzymes — consult your physician if you take prescription medications.</p>

<h3>Magnesium</h3>

<p>Magnesium is a cofactor in over 300 enzymatic reactions, including insulin signaling and glucose metabolism. NHANES data shows that approximately 50% of Americans consume less than the estimated average requirement for magnesium. A meta-analysis of 18 RCTs found that magnesium supplementation reduced fasting glucose by 4.6 mg/dL and improved HOMA-IR in those with hypomagnesemia. Preferred forms: <strong>magnesium glycinate</strong> (best absorbed, least GI side effects) or <strong>magnesium threonate</strong> (crosses blood-brain barrier). Dosage: 200–400mg elemental magnesium daily.</p>

<h3>Chromium</h3>

<p>Chromium enhances insulin receptor signaling and has modest but consistent effects on glucose metabolism. A Cochrane review found that chromium picolinate at <strong>200–1000 µg/day</strong> improved HbA1c by approximately 0.6% in people with type 2 diabetes. Effects are most pronounced in those with documented chromium deficiency or poor metabolic control. Chromium picolinate is the best-studied form.</p>

<h3>Omega-3 Fatty Acids (EPA/DHA)</h3>

<p>Omega-3s reduce inflammation, lower triglycerides, and improve cell membrane fluidity (which affects insulin receptor function). The REDUCE-IT trial demonstrated that high-dose EPA (4g/day icosapent ethyl) reduced cardiovascular events by 25% in statin-treated patients with elevated triglycerides. For metabolic health, target <strong>2–4g combined EPA+DHA daily</strong> from high-quality fish oil or algae-derived sources. Prioritize EPA-dominant formulations for anti-inflammatory effects.</p>

<h3>Additional Evidence-Based Supplements</h3>

<table>
<thead>
<tr>
<th>Supplement</th>
<th>Dose</th>
<th>Primary Mechanism</th>
<th>Evidence Level</th>
</tr>
</thead>
<tbody>
<tr>
<td>Alpha-lipoic acid</td>
<td>600mg/day</td>
<td>Antioxidant, GLUT4 translocation</td>
<td>Moderate (multiple RCTs)</td>
</tr>
<tr>
<td>Vitamin D</td>
<td>2000–5000 IU/day (titrate to 50–70 ng/mL)</td>
<td>Beta-cell function, insulin signaling</td>
<td>Moderate</td>
</tr>
<tr>
<td>Inositol (myo + D-chiro)</td>
<td>4g myo + 100mg D-chiro/day</td>
<td>Insulin second messenger system</td>
<td>Strong (especially in PCOS)</td>
</tr>
<tr>
<td>Ceylon cinnamon</td>
<td>1–3g/day</td>
<td>Insulin receptor potentiation</td>
<td>Modest</td>
</tr>
<tr>
<td>Apple cider vinegar</td>
<td>1–2 tbsp before meals</td>
<td>Delays gastric emptying, reduces glucose spike</td>
<td>Modest (small studies)</td>
</tr>
</tbody>
</table>

<h2>Metabolic Syndrome: Diagnosis and the Five Criteria</h2>

<p>Metabolic syndrome is diagnosed when <strong>three or more</strong> of the following five criteria are present (ATP III definition, endorsed by the AHA/NHLBI):</p>

<ol>
<li><strong>Waist circumference</strong> ≥40 inches (102 cm) in men or ≥35 inches (88 cm) in women</li>
<li><strong>Triglycerides</strong> ≥150 mg/dL (or on medication for elevated triglycerides)</li>
<li><strong>HDL cholesterol</strong> &lt;40 mg/dL in men or &lt;50 mg/dL in women (or on medication)</li>
<li><strong>Blood pressure</strong> ≥130/85 mmHg (or on antihypertensive medication)</li>
<li><strong>Fasting glucose</strong> ≥100 mg/dL (or on medication for elevated glucose)</li>
</ol>

<p>Metabolic syndrome affects approximately 35% of American adults and is the strongest predictor of cardiovascular disease, type 2 diabetes, non-alcoholic fatty liver disease, and certain cancers (including breast, colon, and endometrial). Importantly, you can meet metabolic syndrome criteria while having a "normal" BMI — this phenotype, sometimes called <strong>metabolically obese normal weight (MONW)</strong>, affects an estimated 20–30% of normal-weight adults and is frequently missed on routine physicals.</p>

<h2>Visceral Fat and Weight Loss Resistance: Breaking the Cycle</h2>

<p>If you've been unable to lose weight despite eating less and exercising more, insulin resistance may be the missing piece. Chronically elevated insulin is a <em>fat-storage signal</em> — it inhibits hormone-sensitive lipase (the enzyme that releases fat from adipose tissue) and upregulates lipoprotein lipase (which drives fat storage). In practical terms: <strong>you cannot effectively burn body fat when insulin is chronically elevated</strong>.</p>

<p>This explains why caloric restriction alone often fails for insulin-resistant individuals. Eating 1,200 calories of high-glycemic foods can produce more insulin — and therefore more fat-storage signaling — than eating 2,000 calories of lower-carbohydrate foods. The hormonal context of your calories matters as much as the quantity.</p>

<p>Strategies to break weight loss resistance:</p>

<ul>
<li>Prioritize insulin reduction over calorie reduction — lower carbohydrate intake and extend fasting windows</li>
<li>Measure your waist circumference weekly (more informative than scale weight for visceral fat loss)</li>
<li>Prioritize sleep — even one night of sleep deprivation (4 hours) reduces insulin sensitivity by 25% (University of Chicago study)</li>
<li>Manage cortisol — chronic stress elevates cortisol, which promotes visceral fat deposition and antagonizes insulin</li>
<li>Build muscle — increased lean mass raises basal metabolic rate and glucose disposal capacity</li>
</ul>

<h2>When to See a Doctor: Red Flags and Specialist Referrals</h2>

<p>While many aspects of metabolic health can be improved through self-directed lifestyle changes, certain situations require medical supervision:</p>

<ul>
<li><strong>Fasting glucose consistently above 126 mg/dL or HbA1c above 6.5%</strong> — this meets diagnostic criteria for type 2 diabetes and warrants medical management</li>
<li><strong>HOMA-IR above 3.0 with symptoms</strong> — significant insulin resistance that may benefit from pharmacological support (metformin, GLP-1 agonists)</li>
<li><strong>PCOS with fertility concerns</strong> — insulin-lowering interventions (inositol, metformin, dietary changes) can restore ovulation, but require monitoring</li>
<li><strong>Elevated liver enzymes with imaging findings</strong> — hepatic steatosis (fatty liver) may require evaluation for NASH and fibrosis staging</li>
<li><strong>Rapid, unexplained weight loss</strong> — in the context of known insulin resistance, this can indicate beta-cell failure and progression toward insulin-dependent diabetes</li>
<li><strong>Cardiovascular symptoms</strong> — chest pain, shortness of breath, or claudication in the context of metabolic syndrome warrants cardiovascular risk assessment</li>
</ul>

<h3>Which Type of Doctor to See</h3>

<p>Your primary care physician can order all the tests listed in this guide. However, if you need specialized support:</p>

<ul>
<li><strong>Endocrinologist:</strong> best for complex diabetes management, insulin-dependent cases, and hormonal interactions (thyroid, PCOS, adrenal)</li>
<li><strong>Functional or integrative medicine physician:</strong> often more willing to test fasting insulin, optimize (not just normalize) biomarkers, and emphasize lifestyle-first approaches</li>
<li><strong>Registered dietitian (with low-carb or metabolic health expertise):</strong> for structured dietary guidance, meal planning, and behavior change support</li>
<li><strong>Cardiologist (preventive):</strong> if you have metabolic syndrome with elevated cardiovascular risk markers (coronary calcium score, Lp(a), apoB)</li>
</ul>

<p style="margin-top:20px;"><a class="btn-primary" href="/book?concern=metabolic&source=guide-metabolic-referral">Book An Appointment With A Specialist →</a></p>

<div class="callout-box">
<h3>Your Next Steps</h3>
<p>1. Order a fasting insulin test and calculate your HOMA-IR. 2. Measure your waist circumference and waist-to-hip ratio. 3. Review the optimal ranges table above — not the standard lab ranges. 4. Start with one dietary change: eliminate liquid sugar (soda, juice, sweetened coffee) for 30 days. 5. Add a 15-minute walk after your largest meal. These five steps cost little, require no prescription, and can produce measurable changes in your metabolic biomarkers within 4–8 weeks.</p>
</div>

<h2>Understanding Your Lab Results: A Practical Framework</h2>

<p>When you receive your blood work, don't just look at whether values are flagged as "High" or "Low." Use the optimal ranges in this guide to assess where you truly stand. Here's how to interpret the most important patterns:</p>

<h3>Pattern 1: High Insulin, Normal Glucose</h3>
<p>This is early insulin resistance — your pancreas is working overtime to keep glucose in range. Action: dietary carbohydrate reduction and exercise are highly effective at this stage. This is the ideal time to intervene.</p>

<h3>Pattern 2: High Triglycerides, Low HDL</h3>
<p>A triglyceride/HDL ratio above 2.0 (and especially above 3.0) is a reliable marker of insulin resistance and atherogenic dyslipidemia. This pattern indicates hepatic insulin resistance and is driven primarily by refined carbohydrates and excess fructose, not dietary fat. Action: reduce carbohydrate intake, eliminate fructose-containing beverages, increase omega-3 intake.</p>

<h3>Pattern 3: Elevated hs-CRP with Metabolic Markers</h3>
<p>If hs-CRP is above 1.0 mg/L alongside insulin resistance markers, chronic systemic inflammation is present. This accelerates endothelial damage and cardiovascular risk. Action: emphasize anti-inflammatory dietary patterns (Mediterranean, omega-3-rich foods), optimize sleep, address visceral fat.</p>

<h3>Pattern 4: Rising HbA1c with Normal Fasting Glucose</h3>
<p>This suggests significant postprandial glucose excursions — your fasting glucose is fine, but you're spiking after meals. A continuous glucose monitor (CGM) for 2–4 weeks can reveal these patterns and help you identify your personal trigger foods. Action: reduce glycemic load of meals, add protein and fat to carbohydrate-containing meals, walk after eating.</p>

<blockquote>
<p>Metabolic health is not about perfection — it's about trajectory. Small, consistent improvements in insulin sensitivity compound over months and years. A 20% reduction in HOMA-IR translates to meaningful reductions in cardiovascular risk, cancer risk, and neurodegenerative risk. Test, intervene, retest in 90 days, and adjust.</p>
</blockquote>
""",
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
        "description": "Understand what hormones do, how testosterone, estrogen, thyroid, and cortisol affect daily health, and when symptoms may deserve a closer medical look.",
        "body_html": """
<h2>Understanding Your Hormones: The Master Regulators of Health</h2>

<p>Hormones are substances made by organs called endocrine glands. Each hormone helps regulate one or more processes in the body: insulin helps regulate blood sugar, thyroid hormones help regulate energy and metabolism, and testosterone supports libido, muscle, bone, mood, and immune function.</p>

<p>Hormones need to be present in the right amounts. Too much or too little can cause symptoms, so the body uses feedback systems to adjust hormone production up or down. This guide starts with the basics, then moves into the deeper details — lab testing, free versus bound hormones, optimal ranges, and common treatment decisions.</p>

<h3>Start With the Big Picture</h3>

<ul>
<li><strong>Male hormones:</strong> Testosterone and related androgens — hormones in the testosterone family — affect sex drive, erectile function, muscle mass, bone strength, mood, red blood cell production, and immune function.</li>
<li><strong>Female hormones:</strong> Estrogen, progesterone, and testosterone affect menstrual cycles, fertility, libido, mood, sleep, bone density, muscle, and the menopause transition.</li>
<li><strong>Thyroid hormones:</strong> T4 and T3 affect energy, body temperature, heart rate, digestion, hair and skin, mood, and how quickly cells use fuel.</li>
</ul>

<p>This guide provides a comprehensive, evidence-based framework for understanding hormone health. Whether you're a man experiencing unexplained fatigue, a woman navigating perimenopause, or anyone trying to decode confusing lab results, you'll find actionable information grounded in current endocrinology research and clinical guidelines from the Endocrine Society, the American Thyroid Association (ATA), and the North American Menopause Society (NAMS).</p>

<blockquote>
<p><strong>Key insight:</strong> Hormones do not operate in isolation. Thyroid problems can affect testosterone. Stress hormones can affect thyroid signaling. Sex hormone-binding globulin (SHBG), a liver-made carrier protein, changes how much testosterone and estrogen are bioavailable — meaning available for tissues to use. Understanding these connections is what separates effective treatment from symptom chasing.</p>
</blockquote>

<h2>Signs of Low Testosterone in Men</h2>

<p>Testosterone is the best-known androgen, a family of hormones involved in male sexual development and many adult functions in both men and women. Testosterone deficiency (hypogonadism) affects an estimated 20-40% of men over 45, yet the majority remain undiagnosed. The Endocrine Society's 2018 clinical practice guidelines define testosterone deficiency as total testosterone consistently below 300 ng/dL combined with symptoms — but many men experience meaningful symptoms well above this threshold.</p>

<h3>Classic Symptoms of Low Testosterone</h3>

<ul>
<li><strong>Fatigue and reduced vitality</strong> — not just tiredness, but a pervasive lack of drive and energy that doesn't improve with sleep</li>
<li><strong>Reduced muscle mass and strength</strong> — difficulty maintaining muscle despite consistent training</li>
<li><strong>Increased body fat</strong> — particularly visceral abdominal fat, where aromatase, an enzyme that can convert testosterone into estrogen, can further suppress testosterone balance</li>
<li><strong>Low libido and erectile dysfunction</strong> — often the symptom that finally prompts testing</li>
<li><strong>Cognitive decline</strong> — brain fog, difficulty concentrating, impaired memory</li>
<li><strong>Mood changes</strong> — irritability, depressed mood, reduced motivation</li>
<li><strong>Sleep disturbances</strong> — both poor sleep quality and sleep apnea (which further suppresses testosterone)</li>
<li><strong>Decreased bone mineral density</strong> — testosterone is critical for bone health in men</li>
</ul>

<h3>Why Total Testosterone Alone Is Misleading</h3>

<p>Approximately 98% of circulating testosterone is bound — either tightly to sex hormone-binding globulin (SHBG) or loosely to albumin. Only free testosterone (about 2-3% of total) is bioavailable, meaning available for tissues to use. It works by activating androgen receptors, which are docking sites on cells that respond to testosterone and related hormones. A man with a total testosterone of 550 ng/dL but elevated SHBG may have less bioavailable testosterone than someone with a total of 400 ng/dL and low SHBG.</p>

<div class="callout-box">
<h3>Action Step: The Minimum Male Hormone Panel</h3>
<p>Request these labs (drawn between 7-10 AM, fasting): Total testosterone, free testosterone (equilibrium dialysis, not analog), SHBG, estradiol (sensitive assay), LH, FSH, prolactin, and a CBC. This distinguishes primary (testicular) from secondary (pituitary) hypogonadism and identifies aromatization issues, where testosterone is being converted into estradiol.</p>
</div>

<h3>Testosterone in Women</h3>

<p>Women need testosterone for many of the same reasons men do: muscle mass, bone strength, libido, immune function, mood, energy, and cognitive function. Low testosterone in women can be missed because many standard panels do not include it, and measuring low female levels accurately requires the right assay and an experienced clinician.</p>

<p>The specific numbers matter less for most readers than the principle: testing should be interpreted in context, with symptoms, menstrual or menopause status, medications, and assay quality all considered. Post-menopausal women who report loss of libido, persistent fatigue, or loss of muscle tone despite adequate estrogen therapy may benefit from testosterone assessment using a sensitive assay (LC-MS/MS).</p>

<h2>Thyroid Problems: Why TSH Alone Isn't Enough</h2>

<p>Thyroid dysfunction is one of the most common — and most commonly missed — endocrine disorders. Hypothyroidism means the body does not have enough active thyroid hormone for its needs, most often because the thyroid gland is not producing enough hormone. Worldwide, iodine deficiency is the leading cause; in the United States and other iodine-sufficient regions, Hashimoto's thyroiditis — an autoimmune condition that slowly damages thyroid cells — is the leading cause.</p>

<p>The standard screening approach of testing only TSH (thyroid-stimulating hormone) can still miss some thyroid problems because it assumes that the hypothalamic-pituitary-thyroid axis is functioning normally and that the body is converting and using thyroid hormone appropriately.</p>

<h3>Understanding Thyroid Physiology</h3>

<p>The thyroid gland produces primarily T4 (thyroxine), along with smaller amounts of T3 (triiodothyronine). T4 is often described as a storage hormone because much of it must be converted to T3 — the more active form — by deiodinase enzymes in peripheral tissues. This conversion is not the main cause of most hypothyroidism, but it can influence symptoms and lab patterns. It requires adequate selenium, zinc, and iron, and can be impaired by cortisol excess, inflammation, caloric restriction, and certain medications.</p>

<h3>When TSH Is Normal But You Still Feel Hypothyroid</h3>

<p>Several clinical scenarios can produce hypothyroid symptoms despite a "normal" TSH (0.45-4.5 mIU/L on most lab ranges). These are not the most common causes of hypothyroidism, but they are reasons a symptomatic patient may need more than a TSH-only screen:</p>

<ul>
<li><strong>Poor T4-to-T3 conversion</strong> — TSH may be normal because T4 is adequate, but active T3 is low</li>
<li><strong>Elevated reverse T3 (rT3)</strong> — stress, illness, and caloric restriction shift conversion toward inactive rT3</li>
<li><strong>Hashimoto's thyroiditis</strong> — autoimmune inflammation causes fluctuating thyroid output; TPO antibodies can be elevated for years before TSH becomes abnormal</li>
<li><strong>Central hypothyroidism</strong> — pituitary dysfunction produces inappropriately normal TSH despite low thyroid hormones</li>
<li><strong>Suboptimal TSH within reference range</strong> — a TSH of 3.5 mIU/L is "normal" but may reflect early thyroid failure in someone whose personal setpoint is 1.2</li>
</ul>

<table>
<thead>
<tr>
<th>Thyroid Marker</th>
<th>Standard Reference Range</th>
<th>Optimal Functional Range</th>
<th>Clinical Significance</th>
</tr>
</thead>
<tbody>
<tr>
<td>TSH</td>
<td>0.45–4.5 mIU/L</td>
<td>0.5–2.0 mIU/L</td>
<td>Pituitary signal; elevated = gland underperforming</td>
</tr>
<tr>
<td>Free T4</td>
<td>0.8–1.8 ng/dL</td>
<td>1.1–1.5 ng/dL</td>
<td>Storage hormone; shows gland output</td>
</tr>
<tr>
<td>Free T3</td>
<td>2.3–4.2 pg/mL</td>
<td>3.0–4.0 pg/mL</td>
<td>Active hormone; shows conversion efficiency</td>
</tr>
<tr>
<td>Reverse T3</td>
<td>8–25 ng/dL</td>
<td>&lt;15 ng/dL</td>
<td>Elevated = conversion blockade (stress, inflammation)</td>
</tr>
<tr>
<td>TPO Antibodies</td>
<td>&lt;35 IU/mL</td>
<td>&lt;9 IU/mL</td>
<td>Elevated = autoimmune thyroid disease (Hashimoto's)</td>
</tr>
<tr>
<td>Thyroglobulin Ab</td>
<td>&lt;40 IU/mL</td>
<td>&lt;4 IU/mL</td>
<td>Second marker for Hashimoto's; sometimes positive when TPO is negative</td>
</tr>
</tbody>
</table>

<blockquote>
<p><strong>Clinical pearl:</strong> The American Thyroid Association acknowledges that the upper limit of "normal" TSH remains controversial. The 2012 ATA guidelines note that 95% of healthy individuals without thyroid disease have a TSH below 2.5 mIU/L. Many endocrinologists now treat symptomatic patients with TSH above 2.5, particularly if antibodies are positive.</p>
</blockquote>

<div class="callout-box">
<h3>Action Step: The Complete Thyroid Panel</h3>
<p>Don't accept "thyroid is fine" based on TSH alone. Request: TSH, free T4, free T3, reverse T3, TPO antibodies, and thyroglobulin antibodies. If your provider refuses, direct-to-consumer lab testing is available through services like Quest or Ulta Labs for $100-150.</p>
</div>

<h2>Understanding Cortisol Dysregulation</h2>

<p>Cortisol — often mischaracterized as simply the "stress hormone" — is essential for life. It regulates blood sugar, blood pressure, immune function, and the sleep-wake cycle. Problems arise when cortisol rhythms become disrupted: either chronically elevated (Cushing's pattern), chronically low (adrenal insufficiency), or — most commonly — dysregulated in pattern (high at night, low in the morning).</p>

<h3>The HPA Axis and Chronic Stress</h3>

<p>The hypothalamic-pituitary-adrenal (HPA) axis governs cortisol production. Under chronic stress, this axis can become dysregulated in predictable stages:</p>

<ol>
<li><strong>Stage 1 — Elevated cortisol:</strong> High output, often with disrupted diurnal rhythm. Symptoms: anxiety, insomnia, weight gain (especially abdominal), elevated blood sugar, impaired immunity.</li>
<li><strong>Stage 2 — Mixed pattern:</strong> Cortisol may be high at some times and low at others. The body struggles to maintain appropriate rhythms. Symptoms: wired-but-tired feeling, energy crashes, afternoon fatigue followed by second wind at night.</li>
<li><strong>Stage 3 — Low cortisol output:</strong> HPA axis downregulation results in blunted cortisol response. Symptoms: profound fatigue, inability to handle stress, orthostatic hypotension, salt cravings, slow recovery from illness or exercise.</li>
</ol>

<h3>How Cortisol Disrupts Other Hormones</h3>

<p>Cortisol dysregulation has far-reaching effects on the endocrine system:</p>

<ul>
<li><strong>Thyroid:</strong> Elevated cortisol inhibits TSH secretion and impairs T4-to-T3 conversion, increasing reverse T3</li>
<li><strong>Testosterone:</strong> Cortisol and testosterone are inversely related. Chronic cortisol elevation suppresses GnRH, reducing LH and downstream testosterone production</li>
<li><strong>Progesterone:</strong> Under stress, the body preferentially converts pregnenolone to cortisol rather than progesterone ("pregnenolone steal" — a simplified model, but clinically observed)</li>
<li><strong>Insulin:</strong> Cortisol promotes gluconeogenesis and insulin resistance, driving metabolic dysfunction</li>
</ul>

<h3>Testing Cortisol Properly</h3>

<p>A single morning serum cortisol is a poor screening tool because cortisol fluctuates dramatically throughout the day. The gold standard for assessing HPA axis function is a 4-point salivary cortisol test (or DUTCH urine test), measuring cortisol upon waking, mid-morning, afternoon, and evening. This reveals the cortisol curve — far more informative than any single value.</p>

<h2>Perimenopause and Menopause: What's Actually Happening</h2>

<p>Perimenopause — the transition period before menopause — typically begins in the mid-40s but can start as early as the late 30s. It is defined by irregular ovarian function, not by the absence of periods. Many women experience significant symptoms for 4-8 years before their final menstrual period.</p>

<h3>The Hormonal Shifts of Perimenopause</h3>

<p>Contrary to popular belief, perimenopause does not begin with a simple decline in estrogen. The early perimenopausal transition is characterized by:</p>

<ul>
<li><strong>Erratic estrogen fluctuations</strong> — estrogen can spike to levels higher than normal reproductive years before crashing. These swings — not low estrogen — drive many early symptoms.</li>
<li><strong>Declining progesterone</strong> — as ovulation becomes less consistent, progesterone drops first. This creates a relative estrogen excess even as overall estrogen trends downward.</li>
<li><strong>Rising FSH</strong> — as ovarian reserve declines, FSH increases in an attempt to stimulate follicle development. FSH &gt;25 IU/L on day 3 suggests diminished ovarian reserve.</li>
<li><strong>Testosterone decline</strong> — ovarian testosterone production decreases by approximately 50% between ages 20 and 40, contributing to reduced libido and energy.</li>
</ul>

<h3>Symptoms by Phase</h3>

<table>
<thead>
<tr>
<th>Phase</th>
<th>Typical Duration</th>
<th>Hormonal Pattern</th>
<th>Common Symptoms</th>
</tr>
</thead>
<tbody>
<tr>
<td>Early Perimenopause</td>
<td>2-4 years</td>
<td>Erratic estrogen, low progesterone, normal-high FSH</td>
<td>Shorter cycles, heavier bleeding, breast tenderness, anxiety, insomnia, PMS intensification</td>
</tr>
<tr>
<td>Late Perimenopause</td>
<td>1-3 years</td>
<td>Declining estrogen, absent progesterone, high FSH</td>
<td>Skipped periods, hot flashes, night sweats, vaginal dryness, joint pain, brain fog</td>
</tr>
<tr>
<td>Menopause (post-final period)</td>
<td>Permanent</td>
<td>Low estrogen (&lt;30 pg/mL), absent progesterone, high FSH (&gt;40)</td>
<td>Vasomotor symptoms (80% of women), genitourinary syndrome, bone loss acceleration, cardiovascular risk increase</td>
</tr>
</tbody>
</table>

<blockquote>
<p><strong>NAMS position (2022):</strong> Hormone therapy remains the most effective treatment for vasomotor symptoms and genitourinary syndrome of menopause. For women under 60 or within 10 years of menopause onset, the benefits of HRT generally outweigh the risks. The "timing hypothesis" — starting HRT early provides cardiovascular protection — is supported by the WHI reanalysis and subsequent studies.</p>
</blockquote>

<h3>Estrogen Dominance: A Functional Concept</h3>

<p>Estrogen dominance refers to an imbalance in the estrogen-to-progesterone ratio — not necessarily absolute estrogen excess. It commonly occurs in early perimenopause (when progesterone drops first), with obesity (adipose tissue produces estrogen via aromatase), with environmental xenoestrogen exposure, or with impaired estrogen detoxification (sluggish liver methylation).</p>

<p>Symptoms of relative estrogen excess include: heavy or prolonged periods, fibroids, breast tenderness, weight gain (hips and thighs), mood swings, headaches, and fluid retention.</p>

<div class="callout-box">
<h3>Action Step: Perimenopause Assessment</h3>
<p>If you're a woman over 38 experiencing cycle changes, new anxiety, sleep disruption, or PMS intensification, request: estradiol, progesterone (day 19-21 if still cycling), FSH, LH, DHEA-S, total and free testosterone, and a full thyroid panel. Track symptoms with cycle timing for 2-3 months before your appointment to provide data your provider can act on.</p>
</div>

<h2>The Complete Hormone Panel: What to Test and When</h2>

<p>Most hormone problems are missed because providers test too few markers, test at the wrong time, or rely on overly broad reference ranges. Here's what a comprehensive hormone assessment looks like:</p>

<h3>For Men</h3>

<table>
<thead>
<tr>
<th>Biomarker</th>
<th>Standard Range</th>
<th>Optimal Range</th>
<th>Notes</th>
</tr>
</thead>
<tbody>
<tr>
<td>Total Testosterone</td>
<td>264–916 ng/dL</td>
<td>500–900 ng/dL</td>
<td>Draw 7-10 AM fasting; confirm low on 2 occasions</td>
</tr>
<tr>
<td>Free Testosterone</td>
<td>5–21 pg/mL</td>
<td>9–25 pg/mL</td>
<td>Equilibrium dialysis preferred over calculated</td>
</tr>
<tr>
<td>SHBG</td>
<td>10–57 nmol/L</td>
<td>20–40 nmol/L</td>
<td>High = less bioavailable T; low = metabolic syndrome risk</td>
</tr>
<tr>
<td>Estradiol (sensitive)</td>
<td>10–40 pg/mL</td>
<td>20–35 pg/mL</td>
<td>Too high = aromatization; too low = joint/bone issues</td>
</tr>
<tr>
<td>LH</td>
<td>1.8–8.6 mIU/mL</td>
<td>3–6 mIU/mL</td>
<td>Low LH + low T = secondary hypogonadism</td>
</tr>
<tr>
<td>FSH</td>
<td>1.5–12.4 mIU/mL</td>
<td>2–8 mIU/mL</td>
<td>Elevated = primary testicular failure</td>
</tr>
<tr>
<td>DHEA-S</td>
<td>80–560 μg/dL</td>
<td>250–450 μg/dL</td>
<td>Adrenal androgen precursor; declines with age</td>
</tr>
<tr>
<td>Prolactin</td>
<td>4–15 ng/mL</td>
<td>4–10 ng/mL</td>
<td>Elevated suppresses GnRH → low testosterone</td>
</tr>
</tbody>
</table>

<h3>For Women (Premenopausal)</h3>

<table>
<thead>
<tr>
<th>Biomarker</th>
<th>Standard Range</th>
<th>Optimal Range</th>
<th>Notes</th>
</tr>
</thead>
<tbody>
<tr>
<td>Estradiol</td>
<td>Varies by cycle phase</td>
<td>Follicular: 30-100 pg/mL; Mid-cycle: 100-400; Luteal: 50-250</td>
<td>Draw on day 3 (baseline) or day 19-21 (peak luteal)</td>
</tr>
<tr>
<td>Progesterone</td>
<td>&gt;1 ng/mL (luteal)</td>
<td>&gt;10 ng/mL (day 19-21)</td>
<td>Confirms ovulation occurred; low = anovulatory cycle</td>
</tr>
<tr>
<td>Total Testosterone</td>
<td>8–60 ng/dL</td>
<td>15–70 ng/dL</td>
<td>LC-MS/MS assay critical for accuracy at low levels</td>
</tr>
<tr>
<td>Free Testosterone</td>
<td>0.3–5.2 pg/mL</td>
<td>1.0–6.5 pg/mL</td>
<td>Better symptom correlation than total</td>
</tr>
<tr>
<td>DHEA-S</td>
<td>65–380 μg/dL</td>
<td>150–300 μg/dL</td>
<td>Adrenal androgen marker; relates to energy and libido</td>
</tr>
<tr>
<td>SHBG</td>
<td>18–144 nmol/L</td>
<td>40–80 nmol/L</td>
<td>Oral contraceptives dramatically raise SHBG</td>
</tr>
<tr>
<td>FSH</td>
<td>3.5–12.5 (follicular)</td>
<td>&lt;10 mIU/mL (day 3)</td>
<td>Rising day-3 FSH = diminished ovarian reserve</td>
</tr>
</tbody>
</table>

<h2>SHBG: The Hidden Controller of Hormone Balance</h2>

<p>Sex hormone-binding globulin (SHBG) is a protein produced by the liver that binds testosterone and estrogen, rendering them biologically inactive. SHBG is one of the most important — and most overlooked — markers in hormone assessment because it determines how much of your total hormone production is actually available to your tissues.</p>

<h3>What Raises SHBG</h3>
<ul>
<li>Oral estrogen (birth control pills, oral HRT) — can raise SHBG 2-4x</li>
<li>Hyperthyroidism</li>
<li>Low caloric intake and low body fat</li>
<li>Aging</li>
<li>Liver disease (cirrhosis)</li>
<li>Anticonvulsant medications</li>
</ul>

<h3>What Lowers SHBG</h3>
<ul>
<li>Insulin resistance and obesity</li>
<li>Hypothyroidism</li>
<li>Androgens (testosterone, DHEA)</li>
<li>PCOS — low SHBG is a hallmark finding</li>
<li>Growth hormone excess</li>
<li>Nephrotic syndrome</li>
</ul>

<blockquote>
<p><strong>Clinical significance:</strong> A woman with "normal" total testosterone but SHBG of 120 nmol/L (from oral contraceptives) may have almost no bioavailable testosterone — explaining her loss of libido, flat mood, and reduced muscle tone. Switching from oral to transdermal estrogen can reduce SHBG and restore testosterone bioavailability without changing the testosterone level itself.</p>
</blockquote>

<h2>The Thyroid-Cortisol-Testosterone Axis</h2>

<p>These three hormone systems are deeply interconnected, and dysfunction in one almost always affects the others. This is why treating a single hormone in isolation often fails — or creates new problems.</p>

<h3>How the Axis Works</h3>

<ul>
<li><strong>Thyroid → Testosterone:</strong> Hypothyroidism increases SHBG production and reduces GnRH pulsatility, lowering bioavailable testosterone. Many men with "low T" actually have subclinical hypothyroidism as the root cause.</li>
<li><strong>Cortisol → Thyroid:</strong> Chronic cortisol elevation inhibits TSH secretion, reduces T4-to-T3 conversion (by inhibiting 5'-deiodinase), and increases reverse T3. Stress-induced hypothyroid symptoms are common but won't respond to levothyroxine alone.</li>
<li><strong>Cortisol → Testosterone:</strong> The HPA axis and HPG (hypothalamic-pituitary-gonadal) axis are mutually inhibitory. High CRH (corticotropin-releasing hormone) directly suppresses GnRH. This is why chronically stressed men develop low testosterone and why overtraining syndrome causes hormonal collapse.</li>
<li><strong>Testosterone → Cortisol:</strong> Adequate testosterone improves stress resilience and cortisol recovery. Low testosterone creates a vicious cycle where impaired stress tolerance leads to more cortisol, which further suppresses testosterone.</li>
</ul>

<div class="callout-box">
<h3>Clinical Implication</h3>
<p>If you have low testosterone AND subclinical hypothyroidism AND signs of cortisol dysregulation, treating the testosterone alone (with TRT) without addressing thyroid and adrenal function typically provides incomplete relief and may require escalating doses. Address the upstream cause first: cortisol → thyroid → testosterone, in that order.</p>
</div>

<h2>How to Read Your Hormone Labs</h2>

<p>Understanding your lab results requires more than comparing numbers to reference ranges. Here are the principles that experienced endocrinologists use:</p>

<h3>Reference Ranges Are Not Optimal Ranges</h3>

<p>Laboratory reference ranges are typically defined as the central 95% of a tested population. This population includes people with undiagnosed illness, obesity, and advancing age. A "normal" result may simply mean you're no worse than the average person in a population where metabolic disease is the norm.</p>

<h3>Context Matters More Than Numbers</h3>

<ul>
<li><strong>Timing:</strong> Testosterone peaks at 7-8 AM and can drop 30% by afternoon. A 2 PM draw may read "low" when morning levels are normal.</li>
<li><strong>Fasting state:</strong> Glucose and insulin affect SHBG and testosterone acutely. Always test fasting.</li>
<li><strong>Cycle day (women):</strong> Estradiol, progesterone, FSH, and LH vary dramatically across the menstrual cycle. Day 3 and day 19-21 are standard testing windows.</li>
<li><strong>Medication effects:</strong> Biotin supplements interfere with immunoassay-based thyroid tests (falsely low TSH, falsely high T4/T3). Stop biotin 48 hours before testing.</li>
<li><strong>Illness and stress:</strong> Acute illness suppresses TSH and testosterone (sick euthyroid syndrome). Don't test during illness.</li>
</ul>

<h3>Patterns to Look For</h3>

<ol>
<li><strong>High TSH + low free T4 + high antibodies</strong> = Hashimoto's hypothyroidism — needs treatment and immune support</li>
<li><strong>Normal TSH + low free T3 + high reverse T3</strong> = conversion problem — address stress, nutrient deficiencies, inflammation</li>
<li><strong>Low total T + low LH/FSH</strong> = secondary hypogonadism — evaluate pituitary, medications, sleep apnea</li>
<li><strong>Low total T + high LH/FSH</strong> = primary hypogonadism — testicular issue, consider karyotype if young</li>
<li><strong>Normal total T + high SHBG + low free T</strong> = binding problem — address thyroid, liver, or switch from oral estrogen</li>
<li><strong>Low progesterone + irregular cycles + age &gt;38</strong> = early perimenopause — consider cyclic progesterone</li>
</ol>

<h2>Natural Ways to Balance Hormones</h2>

<p>Before considering hormone replacement, lifestyle and nutritional interventions can meaningfully shift hormone levels. These approaches have clinical evidence supporting their efficacy:</p>

<h3>Sleep: The Non-Negotiable Foundation</h3>

<p>Sleep is the single most impactful modifiable factor for hormone health. Testosterone is produced primarily during deep sleep; just one week of 5-hour nights reduces testosterone by 10-15% in young men (JAMA, 2011). Cortisol rhythm depends on consistent sleep-wake timing. Growth hormone secretion occurs almost exclusively during slow-wave sleep.</p>

<ul>
<li>Target 7-9 hours of sleep per night with consistent timing (within 30 minutes daily)</li>
<li>Screen for sleep apnea — prevalence in men with low testosterone is &gt;40%</li>
<li>Prioritize sleep quality: dark room, cool temperature (65-68°F), no alcohol within 3 hours of bed</li>
</ul>

<h3>Resistance Training</h3>

<p>Compound resistance exercises (squats, deadlifts, presses) acutely increase testosterone and growth hormone. More importantly, regular strength training improves insulin sensitivity — which lowers SHBG and increases bioavailable testosterone. The evidence supports 3-4 sessions per week of moderate-to-heavy resistance training. Avoid chronic overtraining, which has the opposite effect via cortisol elevation.</p>

<h3>Nutrition for Hormone Optimization</h3>

<ul>
<li><strong>Adequate protein:</strong> 0.7-1.0 g/lb bodyweight supports androgen synthesis and preserves muscle mass</li>
<li><strong>Dietary fat:</strong> Extremely low-fat diets (&lt;20% of calories) reduce testosterone. Include sources of monounsaturated (olive oil, avocado) and saturated fat (eggs, butter) — cholesterol is the precursor to all steroid hormones</li>
<li><strong>Cruciferous vegetables:</strong> DIM (diindolylmethane) and sulforaphane support estrogen detoxification via Phase II liver metabolism</li>
<li><strong>Zinc-rich foods:</strong> Oysters, red meat, pumpkin seeds — zinc is required for testosterone synthesis and thyroid hormone conversion</li>
<li><strong>Selenium sources:</strong> Brazil nuts (1-3 daily provides ~200 mcg), fish, eggs — required for deiodinase enzymes that convert T4 to T3</li>
<li><strong>Avoid excessive caloric restriction:</strong> Prolonged deficits suppress thyroid (T3 drops), testosterone, and reproductive hormones</li>
</ul>

<h3>Stress Management and the HPA Axis</h3>

<p>Cortisol-reducing practices with clinical evidence include:</p>

<ul>
<li><strong>Mindfulness meditation:</strong> 8-week MBSR programs reduce salivary cortisol by 20-25% (Psychoneuroendocrinology, 2017)</li>
<li><strong>Deep breathing / vagal tone exercises:</strong> 5-10 minutes of slow breathing (5.5 breaths/minute) measurably reduces cortisol within 20 minutes</li>
<li><strong>Nature exposure:</strong> 20+ minutes outdoors reduces cortisol (Forest Bathing research, International Journal of Environmental Research, 2019)</li>
<li><strong>Limiting caffeine:</strong> Caffeine after noon extends cortisol half-life and disrupts sleep architecture — the cascading effect impairs overnight testosterone production</li>
</ul>

<h2>Evidence-Based Supplements for Hormone Support</h2>

<p>Supplementation can be helpful when specific nutrient deficiencies are contributing to hormone dysfunction. The evidence is strongest for:</p>

<h3>Ashwagandha (Withania somnifera)</h3>

<p>A systematic review and meta-analysis (Journal of Ethnopharmacology, 2021) found that ashwagandha supplementation (300-600 mg of standardized root extract daily) significantly reduces cortisol, improves testosterone in men, and enhances subjective stress resilience. The best-studied extract is KSM-66 at 600 mg/day. Effects typically manifest within 8-12 weeks.</p>

<h3>Zinc</h3>

<p>Zinc deficiency is common (estimated 12% of US adults, higher in athletes and vegans) and directly impairs testosterone synthesis. Supplementation (30 mg zinc picolinate or citrate daily) restores testosterone in deficient individuals. Note: long-term zinc supplementation above 40 mg/day can deplete copper — consider a 15:1 zinc-to-copper ratio.</p>

<h3>Selenium</h3>

<p>Critical for thyroid hormone conversion (T4 → T3) via selenoprotein deiodinases. Also reduces TPO antibodies in Hashimoto's (European Thyroid Journal, 2017). Dose: 200 mcg/day from selenomethionine or 1-3 Brazil nuts daily. Do not exceed 400 mcg/day (toxicity threshold).</p>

<h3>Vitamin D</h3>

<p>Vitamin D functions more like a hormone than a vitamin. Deficiency (below 30 ng/mL) is associated with lower testosterone, impaired thyroid function, and increased autoimmune thyroid disease. The Endocrine Society recommends maintaining levels of 40-60 ng/mL. Most adults need 2,000-5,000 IU daily to achieve optimal levels; dose based on blood levels, not guesswork.</p>

<h3>Magnesium</h3>

<p>Involved in 600+ enzymatic reactions, including steroid hormone synthesis and SHBG binding. Magnesium deficiency (common with modern agriculture) increases SHBG, reduces free testosterone, and impairs sleep quality. Dose: 200-400 mg of magnesium glycinate or threonate at bedtime. Glycinate form has the best bioavailability and a calming effect on sleep.</p>

<div class="callout-box">
<h3>Supplement Priority Order</h3>
<p>Before adding supplements, fix foundations first: sleep, nutrition, stress. Then address confirmed deficiencies via testing. Priority: (1) Vitamin D — test 25-OH-D and dose accordingly, (2) Magnesium — most adults benefit, (3) Zinc — especially if low testosterone or poor immunity, (4) Selenium — especially if thyroid antibodies are elevated, (5) Ashwagandha — if cortisol is a primary driver. Don't supplement blindly.</p>
</div>

<h2>When Hormone Replacement Therapy Makes Sense</h2>

<p>Lifestyle optimization has limits. When hormone levels are genuinely deficient — not just suboptimal — and symptoms significantly impair quality of life, hormone replacement therapy (HRT) can be transformative.</p>

<h3>Testosterone Replacement in Men</h3>

<p>The Endocrine Society (2018) recommends testosterone therapy for men with consistently low total testosterone (&lt;300 ng/dL on two morning measurements) combined with symptoms. Options include:</p>

<ul>
<li><strong>Topical testosterone (gel/cream):</strong> Daily application, provides stable levels, allows dose titration. First-line for most patients.</li>
<li><strong>Intramuscular injections (cypionate/enanthate):</strong> Weekly or biweekly. Lower cost but creates peaks and troughs unless using subcutaneous microdosing protocols.</li>
<li><strong>Clomiphene citrate:</strong> Off-label for younger men who want to preserve fertility. Stimulates endogenous production by blocking estrogen feedback at the pituitary.</li>
</ul>

<p>Monitoring requirements: PSA, hematocrit (TRT raises red blood cells), lipids, and estradiol every 3-6 months initially.</p>

<h3>Menopause Hormone Therapy (MHT)</h3>

<p>NAMS (2022) endorses hormone therapy as first-line for vasomotor symptoms in women under 60 or within 10 years of menopause. Evidence-based options include:</p>

<ul>
<li><strong>Transdermal estradiol (patch or gel):</strong> 0.025-0.1 mg/day. Preferred over oral because it avoids first-pass liver metabolism, doesn't raise SHBG or clotting factors, and has a more favorable cardiovascular profile.</li>
<li><strong>Micronized progesterone (Prometrium):</strong> 100-200 mg at bedtime for women with a uterus. Oral micronized progesterone has anxiolytic and sleep-promoting effects. Preferred over synthetic progestins (medroxyprogesterone) based on safety data.</li>
<li><strong>Vaginal estrogen:</strong> For genitourinary syndrome of menopause (dryness, painful intercourse, recurrent UTIs). Minimal systemic absorption; safe even in women for whom systemic HRT is contraindicated.</li>
<li><strong>Testosterone for women:</strong> Low-dose transdermal testosterone (300 mcg/day, roughly 1/10th male dose) for hypoactive sexual desire disorder. Supported by international consensus (Global Consensus Statement on Testosterone Therapy for Women, 2019).</li>
</ul>

<h3>Thyroid Hormone Replacement</h3>

<p>Standard treatment for hypothyroidism is levothyroxine (T4 monotherapy). However, approximately 10-15% of patients remain symptomatic despite "normalized" TSH. For these patients, the ATA acknowledges that combination T4/T3 therapy (levothyroxine plus liothyronine) or natural desiccated thyroid (NDT, such as Armour Thyroid) may provide benefit — though evidence remains mixed and guidelines recommend individualized trials.</p>

<h2>Endocrinologist vs. Functional Medicine: How to Choose</h2>

<p>Choosing the right provider depends on your situation:</p>

<h3>See a Conventional Endocrinologist When:</h3>
<ul>
<li>You suspect serious pathology (pituitary tumor, Cushing's disease, Graves' disease, primary adrenal insufficiency)</li>
<li>You need formal diagnosis for insurance purposes</li>
<li>You have Type 1 diabetes, thyroid cancer, or other conditions requiring specialist management</li>
<li>You want established protocols with long-term safety data</li>
</ul>

<h3>Consider Functional or Integrative Medicine When:</h3>
<ul>
<li>Standard workup is "normal" but you have persistent symptoms</li>
<li>You want comprehensive testing (full panels, not just screening markers)</li>
<li>You want to explore root causes before committing to lifelong HRT</li>
<li>You're interested in combining lifestyle, nutrition, and targeted supplementation</li>
<li>You want a provider who orders optimal-range interpretation, not just disease-exclusion</li>
</ul>

<div class="callout-box">
<h3>Red Flags in Hormone Providers</h3>
<p>Beware of providers who: prescribe testosterone without baseline labs or follow-up monitoring, refuse to check free T3 or reverse T3 for symptomatic thyroid patients, dismiss perimenopause symptoms in women under 50, push expensive proprietary supplements without evidence, or put everyone on bioidentical hormones without individual assessment. Good hormone medicine is personalized, evidence-based, and monitored.</p>
</div>

<p style="margin-top:20px;"><a class="btn-primary" href="/book?concern=hormones&source=guide-hormones-referral">Book An Appointment With A Specialist →</a></p>

<h2>Frequently Missed Diagnoses in Hormone Health</h2>

<h3>Subclinical Hypothyroidism</h3>
<p>TSH 2.5-10 mIU/L with normal T4 affects 4-10% of adults. Many providers won't treat until TSH exceeds 10, but symptomatic patients with TSH &gt;4.0 — particularly with positive antibodies — often benefit from low-dose levothyroxine (25-50 mcg). The evidence supports treating this population when symptoms are present (BMJ, 2019 systematic review).</p>

<h3>Secondary Hypogonadism from Medications</h3>
<p>Opioids, SSRIs, spironolactone, finasteride, and corticosteroids all suppress testosterone through different mechanisms. Many men on chronic opioid therapy have testosterone below 200 ng/dL yet are never tested. Always review the medication list when evaluating low testosterone.</p>

<h3>PCOS as a Metabolic Disorder</h3>
<p>Polycystic ovary syndrome affects 8-13% of reproductive-age women and is fundamentally an insulin resistance condition that drives excess ovarian androgen production. The diagnostic criteria (Rotterdam) require 2 of 3: oligo/anovulation, clinical or biochemical hyperandrogenism, and polycystic ovarian morphology on ultrasound. First-line treatment should address insulin resistance (metformin, inositol, low-glycemic nutrition) rather than simply masking symptoms with oral contraceptives.</p>

<h3>Relative Adrenal Insufficiency</h3>
<p>Patients with chronically blunted cortisol output (not Addison's disease, but HPA axis suppression from chronic stress, previous prednisone use, or pituitary dysfunction) present with profound fatigue, inability to tolerate exercise, salt cravings, and postural lightheadedness. Morning cortisol below 10 mcg/dL warrants further evaluation with an ACTH stimulation test.</p>

<h2>Building Your Hormone Health Action Plan</h2>

<p>Optimizing hormonal health is not a single intervention — it's a systematic process of testing, identifying root causes, implementing changes, and retesting to verify progress.</p>

<ol>
<li><strong>Get comprehensive baseline labs</strong> — use the panels described above, not just screening markers</li>
<li><strong>Identify the primary driver</strong> — is it cortisol dysregulation, thyroid conversion, SHBG, nutrient deficiency, or genuinely low production?</li>
<li><strong>Address foundations first</strong> — sleep, nutrition, stress management, exercise, toxic exposure reduction</li>
<li><strong>Target specific deficiencies</strong> — supplement confirmed deficiencies (vitamin D, zinc, selenium, magnesium) for 8-12 weeks</li>
<li><strong>Retest and reassess</strong> — repeat labs after 10-12 weeks of lifestyle intervention</li>
<li><strong>Consider HRT if indicated</strong> — when levels remain low despite optimized foundations, replacement therapy is appropriate and effective</li>
<li><strong>Monitor long-term</strong> — hormones change with age, stress, and life circumstances. Annual comprehensive testing helps catch drift early</li>
</ol>

<blockquote>
<p><strong>The goal of hormone optimization is not to achieve artificially high numbers</strong> — it's to restore hormonal signaling to a level where your body functions as it should: clear thinking, restorative sleep, healthy body composition, stable mood, adequate libido, and resilience to stress. The numbers serve the symptoms, not the other way around.</p>
</blockquote>
""",
        "targets": [
            "Low testosterone symptoms in men: fatigue, reduced muscle mass, low libido, and erectile dysfunction",
            "Thyroid symptoms such as fatigue, weight gain, cold intolerance, brain fog, and hair loss",
            "Cortisol rhythm problems linked with anxiety, insomnia, weight gain, and poor stress recovery",
            "Perimenopause symptoms such as hot flashes, night sweats, mood changes, and irregular periods",
            "Menopause-related changes in sleep, temperature regulation, bone health, and body composition",
            "Low libido and sexual dysfunction in men and women",
            "Brain fog and cognitive changes linked to hormonal shifts",
        ],
        "process": [
            "How major hormone systems affect one another — explained in plain language before the technical details",
            "Which hormone labs doctors may use for testosterone, thyroid, cortisol, estrogen, progesterone, and SHBG",
            "Why single-marker screening (TSH alone, total testosterone alone) misses dysfunction",
            "How to think about normal vs. optimal ranges without getting lost in units",
            "Evidence-based approaches: lifestyle, nutrition, supplementation, and when HRT makes sense",
            "How to find the right endocrinologist or hormone specialist",
        ],
        "biomarkers": [
            "Total testosterone (overall testosterone production)",
            "Free testosterone (the portion available for tissues to use)",
            "Estradiol / E2 (a primary estrogen; interpretation varies by cycle phase and menopause status)",
            "TSH (the pituitary signal asking the thyroid to make hormone)",
            "Free T3 (the more active thyroid hormone)",
            "Free T4 (the main hormone produced by the thyroid gland)",
            "DHEA-S (an adrenal androgen precursor)",
            "SHBG (Sex Hormone Binding Globulin — affects how much sex hormone is available to tissues)",
            "AM Cortisol (a morning snapshot of the stress-hormone system)",
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
            {"q": "My doctor tested TSH and said my thyroid is fine. Could something still be off?", "a": "Yes. TSH alone can miss some thyroid patterns. A fuller thyroid picture often includes TSH plus free T4, free T3, and thyroid antibodies. Most hypothyroidism comes from low thyroid gland output — worldwide often iodine deficiency, and in the U.S. often Hashimoto's thyroiditis — but some symptomatic patients also have conversion or medication-related issues that a TSH-only screen may not clarify."},
            {"q": "Do I need to see a doctor after reading this?", "a": "It depends on what you find. The guide helps you understand what's normal, what's optimal, and what may need medical attention. If your symptoms are significant, we recommend connecting with a specialist — and we can help match you with one."},
        ],
    },
    "recovery": {
        "name": "Sleep & Recovery Guide",
        "slug": "recovery",
        "description": "Go beyond sleep hygiene tips. This guide covers the physiological root causes of poor sleep, chronic fatigue, and low HRV — including nutrient deficiencies, cortisol dysregulation, and thyroid dysfunction.",
        "body_html": """
<h2>Why Am I Always Tired? The Question Millions Are Asking Wrong</h2>

<p>If you've Googled "why am I always tired" — welcome. You're one of roughly 20 million Americans who will search some version of that phrase this year. And if the answers you've found so far boil down to "get more sleep, drink more water, and manage stress," you already know something is missing.</p>

<p>Here's the uncomfortable truth: <strong>most fatigue is not caused by poor sleep habits</strong>. It's caused by physiological dysfunction — disrupted cortisol rhythms, nutrient depletions, subclinical thyroid problems, undiagnosed sleep apnea, or autonomic nervous system imbalance — that no amount of blue-light blocking glasses or chamomile tea will fix.</p>

<p>This guide is different from what you'll find on Healthline or WebMD. We won't just list symptoms. We'll walk you through the exact lab markers, wearable data patterns, and clinical decision points that separate someone who's "just tired" from someone with a treatable medical condition. We'll give you the thresholds your doctor probably isn't using, and the evidence behind each recommendation.</p>

<blockquote>
<p><strong>Key insight:</strong> In a 2019 analysis of over 12,000 patients presenting with fatigue as a chief complaint, nearly 40% had at least one identifiable, correctable cause found on targeted lab work — most commonly iron deficiency (even without anemia), vitamin D insufficiency, or thyroid dysfunction. The problem wasn't that these conditions were rare. It was that the right tests weren't ordered.</p>
</blockquote>

<h2>Sleep Architecture: What Actually Happens When You Sleep</h2>

<p>Before we can discuss why your sleep isn't working, you need to understand what working sleep looks like. Sleep is not a single, uniform state. It's a tightly orchestrated cycle of distinct neurological stages, each serving different recovery functions.</p>

<h3>The Four Stages of Sleep</h3>

<p>Every night, your brain cycles through four stages approximately every 90 minutes, completing 4–6 full cycles:</p>

<ul>
<li><strong>N1 (Light Sleep):</strong> The transition from wakefulness. Lasts 1–5 minutes per cycle. Muscle tone decreases, and theta waves appear on EEG. Easy to wake from. Should constitute only 2–5% of total sleep time.</li>
<li><strong>N2 (Intermediate Sleep):</strong> The workhorse stage. Sleep spindles and K-complexes appear — brief bursts of neural activity critical for <strong>memory consolidation</strong> and sensory gating. N2 should make up 45–55% of your night. This is when your brain decides what information from the day to keep and what to discard.</li>
<li><strong>N3 (Deep Sleep / Slow-Wave Sleep):</strong> The physical recovery stage. Delta waves dominate. Growth hormone surges. The glymphatic system activates, flushing metabolic waste — including amyloid-beta, a protein implicated in Alzheimer's disease — from the brain at rates 10–20x higher than during wakefulness. <strong>If you feel physically wrecked despite sleeping 8 hours, you likely aren't getting enough N3.</strong> Target: 15–25% of total sleep for adults under 40; this naturally declines with age.</li>
<li><strong>REM (Rapid Eye Movement):</strong> The emotional and cognitive recovery stage. Vivid dreaming. Emotional memory processing. Creative problem-solving consolidation. REM is also when your brain prunes and reorganizes neural connections. Target: 20–25% of total sleep time. REM-dominant cycles occur later in the night, which is why cutting sleep short by even 60–90 minutes disproportionately slashes your REM.</li>
</ul>

<div class="callout-box">
<h3>Why This Matters for Your Wearable Data</h3>
<p>When your Oura ring or Whoop strap reports low deep sleep, it's telling you that N3 — your physical repair stage — is compromised. Common causes include alcohol within 3 hours of sleep (reduces N3 by up to 30%), elevated resting heart rate, and sleep apnea. Low REM, meanwhile, often signals early-morning cortisol surges, alcohol use, or REM-suppressing medications like SSRIs and beta-blockers.</p>
</div>

<h3>Why Sleep Duration Alone Is Misleading</h3>

<p>Here's what most sleep advice gets wrong: duration is a poor proxy for quality. A 2022 study in <em>Sleep Medicine Reviews</em> found that <strong>sleep efficiency</strong> (the percentage of time in bed actually spent asleep) and <strong>stage distribution</strong> predicted next-day cognitive performance and subjective fatigue far better than total hours slept. Someone sleeping 6.5 hours with 22% deep sleep and 24% REM will typically outperform — and feel far better than — someone sleeping 8 hours with 10% deep and 15% REM.</p>

<h2>The Real Causes of Poor Sleep Quality</h2>

<p>Sleep hygiene — dark room, cool temperature, consistent bedtime — is necessary but rarely sufficient. It's the equivalent of telling someone with diabetes to "eat less sugar." Technically not wrong, but it misses the underlying mechanism. Here are the physiological drivers that actually determine whether you wake up restored or wrecked.</p>

<h2>Cortisol and Sleep: The Wired-But-Tired Pattern</h2>

<p>If you're exhausted all day but suddenly feel alert at 10 PM, you don't have a discipline problem. You likely have a <strong>cortisol rhythm inversion</strong> — and it's one of the most common and most overlooked causes of chronic sleep disruption.</p>

<h3>How the Cortisol-Melatonin Axis Should Work</h3>

<p>In a healthy circadian rhythm, cortisol peaks within 30–45 minutes of waking (the <strong>cortisol awakening response</strong>, or CAR), remains moderately elevated through midday, and gradually tapers through the afternoon and evening. As cortisol falls, melatonin rises — triggered by diminishing light exposure acting on the suprachiasmatic nucleus (SCN). This is a hormonal seesaw: cortisol up, melatonin down, and vice versa.</p>

<p>Chronic stress, irregular sleep schedules, excessive evening screen exposure, and certain dietary patterns can flatten or invert this curve. The result is a pattern clinicians call <strong>"wired but tired"</strong>:</p>

<ul>
<li>Low morning cortisol → you can't wake up, need caffeine to function, feel foggy until 10–11 AM</li>
<li>Blunted midday cortisol → the <strong>afternoon energy crash</strong>, typically between 2–4 PM</li>
<li>Elevated evening cortisol → racing thoughts at bedtime, difficulty initiating sleep, second wind at night</li>
<li>Suppressed melatonin → delayed sleep onset, difficulty maintaining sleep in the early morning hours</li>
</ul>

<h3>Testing Your Cortisol Rhythm</h3>

<p>A single-point morning serum cortisol (standard in most doctor's offices) is nearly useless for detecting rhythm disruption. You need a <strong>four-point salivary cortisol test</strong> — taken at waking, noon, evening, and bedtime — or a <strong>DUTCH (Dried Urine Test for Comprehensive Hormones)</strong> test, which adds cortisol metabolites and melatonin metabolites for a complete picture.</p>

<blockquote>
<p><strong>Clinical note:</strong> The cortisol awakening response (CAR) — the spike in cortisol 30–45 minutes post-waking — is emerging as one of the most clinically useful markers for HPA axis function. A blunted CAR (less than 50% rise from baseline) is associated with burnout, depression, chronic fatigue syndrome, and post-traumatic stress. If your provider isn't measuring this, ask specifically.</p>
</blockquote>

<h2>Nutrient Deficiencies That Cause Fatigue and Insomnia</h2>

<p>This is where the conversation gets clinical — and where most online advice falls dangerously short. Multiple nutrient deficiencies directly impair sleep quality, energy production, and autonomic recovery. The critical issue: <strong>standard lab reference ranges define "deficiency" as the bottom 2.5% of the population, not the level at which you'll feel and function well.</strong></p>

<h3>Key Nutrient Thresholds for Sleep and Energy</h3>

<table>
<thead>
<tr>
<th>Nutrient</th>
<th>Standard "Normal" Range</th>
<th>Optimal Range for Energy &amp; Sleep</th>
<th>Symptoms When Suboptimal</th>
</tr>
</thead>
<tbody>
<tr>
<td><strong>Ferritin</strong></td>
<td>12–150 ng/mL (women), 12–300 ng/mL (men)</td>
<td>&gt;50 ng/mL (ideally 70–100)</td>
<td>Fatigue, restless legs, hair loss, exercise intolerance, poor thermoregulation</td>
</tr>
<tr>
<td><strong>Vitamin D (25-OH)</strong></td>
<td>30–100 ng/mL</td>
<td>40–60 ng/mL</td>
<td>Fatigue, muscle weakness, mood changes, impaired immune function, poor sleep quality</td>
</tr>
<tr>
<td><strong>RBC Magnesium</strong></td>
<td>4.2–6.8 mg/dL</td>
<td>5.5–6.5 mg/dL</td>
<td>Insomnia, muscle cramps, anxiety, heart palpitations, constipation</td>
</tr>
<tr>
<td><strong>Vitamin B12</strong></td>
<td>200–900 pg/mL</td>
<td>&gt;500 pg/mL</td>
<td>Fatigue, brain fog, tingling/numbness, depression, poor memory</td>
</tr>
<tr>
<td><strong>Folate (RBC)</strong></td>
<td>&gt;280 ng/mL</td>
<td>&gt;600 ng/mL</td>
<td>Fatigue, irritability, poor concentration, depressive symptoms</td>
</tr>
<tr>
<td><strong>Iron Saturation</strong></td>
<td>15–55%</td>
<td>25–45%</td>
<td>Fatigue, shortness of breath, cold intolerance, poor exercise recovery</td>
</tr>
</tbody>
</table>

<div class="callout-box">
<h3>The Ferritin Problem</h3>
<p>A ferritin of 15 ng/mL is technically "normal" by most lab standards. But research from the <em>Journal of Clinical Sleep Medicine</em> (2019) shows that ferritin levels below 50 ng/mL are strongly associated with restless leg syndrome, increased periodic limb movements during sleep, and reduced sleep efficiency. If you've been told your iron is "fine" but you're fatigued with disrupted sleep, ask for a ferritin recheck and push for levels above 50.</p>
</div>

<h3>Why Serum Magnesium Is Nearly Worthless</h3>

<p>Only 1% of your body's magnesium is in the bloodstream. Serum magnesium will remain normal until you're severely depleted, because your body pulls from bone and tissue stores to maintain blood levels. <strong>Order RBC (red blood cell) magnesium instead.</strong> An estimated 50–80% of Americans are functionally magnesium-insufficient — and magnesium is required for over 300 enzymatic reactions, including GABA receptor activation (calming neurotransmitter), melatonin synthesis, and muscle relaxation.</p>

<h2>The Thyroid-Fatigue Connection Your Doctor Might Be Missing</h2>

<p>Thyroid dysfunction is the second most common endocrine disorder worldwide and one of the most under-tested causes of fatigue and sleep disruption. The problem isn't that thyroid disease is rare — it's that most screening is incomplete.</p>

<h3>Why TSH Alone Isn't Enough</h3>

<p>Standard practice tests only TSH (thyroid-stimulating hormone). If it's between 0.5–4.5 mIU/L, you're told your thyroid is "normal." But this misses two critical scenarios:</p>

<ol>
<li><strong>Subclinical hypothyroidism:</strong> TSH between 2.5–4.5 mIU/L with symptoms. The American Thyroid Association's upper limit of "normal" was lowered to 2.5 in their 2017 guidelines, but most labs haven't updated their reference ranges.</li>
<li><strong>Low T3 syndrome (euthyroid sick syndrome):</strong> Normal TSH, normal T4, but low free T3. T3 is the active thyroid hormone — the one that actually drives your metabolism, energy, and body temperature. You can have adequate T4 production but impaired conversion to T3 (often caused by stress, caloric restriction, selenium deficiency, or chronic inflammation).</li>
</ol>

<p>A complete thyroid assessment requires: <strong>TSH, free T4, free T3, reverse T3, TPO antibodies, and thyroglobulin antibodies</strong>. If fatigue is your chief complaint, accept nothing less.</p>

<h2>Understanding HRV and Recovery: Your Autonomic Nervous System Report Card</h2>

<p>Heart rate variability (HRV) has become the single most accessible window into your body's recovery status, thanks to wearable devices. But most people don't understand what it actually measures, what their numbers mean, or when to be concerned.</p>

<h3>What HRV Actually Measures</h3>

<p>HRV is the variation in time between consecutive heartbeats, measured in milliseconds. Despite what the name suggests, <strong>higher variability is better</strong>. A high HRV indicates that your autonomic nervous system (ANS) is flexible — able to dynamically shift between sympathetic (fight-or-flight) and parasympathetic (rest-and-digest) states. A low HRV means your ANS is "stuck" — typically in a sympathetic-dominant state — with reduced capacity to recover.</p>

<h3>What Good vs. Bad HRV Looks Like</h3>

<table>
<thead>
<tr>
<th>Metric</th>
<th>Poor Recovery</th>
<th>Moderate Recovery</th>
<th>Strong Recovery</th>
</tr>
</thead>
<tbody>
<tr>
<td><strong>RMSSD (ms)</strong></td>
<td>&lt;20</td>
<td>20–50</td>
<td>&gt;50</td>
</tr>
<tr>
<td><strong>Oura HRV (ms)</strong></td>
<td>Below personal baseline by &gt;15%</td>
<td>Within 10% of baseline</td>
<td>At or above baseline</td>
</tr>
<tr>
<td><strong>Whoop Recovery (%)</strong></td>
<td>&lt;33% (red)</td>
<td>34–66% (yellow)</td>
<td>&gt;67% (green)</td>
</tr>
<tr>
<td><strong>Resting HR (bpm)</strong></td>
<td>&gt;10 above personal baseline</td>
<td>3–10 above baseline</td>
<td>At or below baseline</td>
</tr>
</tbody>
</table>

<blockquote>
<p><strong>Critical caveat:</strong> HRV is <em>highly</em> individual. A 25-year-old endurance athlete might baseline at 80–120 ms RMSSD, while a healthy 55-year-old might baseline at 25–40 ms. Comparing your HRV to someone else's is meaningless. The only comparison that matters is against your own 30-day rolling average.</p>
</blockquote>

<h3>Patterns to Watch For</h3>

<ul>
<li><strong>Chronically low HRV + elevated resting HR:</strong> Sympathetic overdrive. Common causes: overtraining, chronic stress, sleep apnea, illness, alcohol use.</li>
<li><strong>HRV dropping over weeks/months:</strong> A gradual downtrend suggests accumulated physiological stress. Could indicate overtraining syndrome, developing illness, worsening sleep quality, or increasing life stress.</li>
<li><strong>Paradoxically high HRV + fatigue:</strong> Can indicate parasympathetic dominance (seen in overtraining syndrome, depression, and certain autonomic disorders). High HRV isn't always good.</li>
<li><strong>Respiratory sinus arrhythmia (RSA) absent:</strong> If your HRV doesn't increase with slow, deep breathing, consider autonomic dysfunction evaluation.</li>
</ul>

<h2>Interpreting Your Wearable Sleep Data: Oura, Whoop, Apple Watch, and Garmin</h2>

<p>Wearable sleep trackers have democratized sleep data — but they've also created a generation of people anxious about their sleep scores. Here's how to use this data productively without falling into <strong>orthosomnia</strong> (anxiety about sleep data that itself worsens sleep).</p>

<h3>What Wearables Get Right — and Wrong</h3>

<p>Consumer wearables use accelerometry and photoplethysmography (PPG) to estimate sleep stages. Compared to polysomnography (the clinical gold standard), they are:</p>

<ul>
<li><strong>Good at:</strong> Total sleep time (±20 min), sleep onset detection, resting heart rate, HRV trends over time</li>
<li><strong>Moderate at:</strong> REM detection (tends to overestimate), wake detection</li>
<li><strong>Poor at:</strong> Distinguishing N2 from N3 (deep sleep), detecting brief arousals, respiratory events, and periodic limb movements</li>
</ul>

<p>The practical implication: <strong>trust the trends, not the nightly absolutes</strong>. If your Oura ring says you got 45 minutes of deep sleep last night, that specific number may be off by 30%. But if it says your deep sleep has declined by 40% over the past three months, that trend is clinically meaningful and worth investigating.</p>

<div class="callout-box">
<h3>The Alcohol Test</h3>
<p>Want to see how accurate your wearable is at detecting sleep quality changes? Have two or more alcoholic drinks after 7 PM and compare that night's data to your baseline. You should see: elevated resting heart rate (+5–15 bpm), suppressed HRV (−20–40%), reduced deep sleep, and a lower overall sleep or readiness score. If your wearable doesn't detect these changes, it may not be sensitive enough to guide recovery decisions.</p>
</div>

<h2>Obstructive Sleep Apnea: The Most Common Undiagnosed Sleep Disorder</h2>

<p>An estimated <strong>80% of moderate-to-severe obstructive sleep apnea (OSA) cases in the United States are undiagnosed</strong>, according to the American Academy of Sleep Medicine (AASM). OSA isn't just about snoring. It's a condition where your airway partially or fully collapses during sleep, triggering repeated arousals, oxygen desaturation, and sympathetic nervous system activation — dozens or even hundreds of times per night — that you typically don't remember.</p>

<h3>Risk Factors and Screening</h3>

<p>Classical risk factors include obesity, male sex, neck circumference &gt;17 inches (men) or &gt;16 inches (women), and age over 50. But OSA also affects lean individuals — especially those with:</p>

<ul>
<li>Retrognathia (recessed jaw) or a narrow palate</li>
<li>Large tongue relative to airway (Mallampati class III/IV)</li>
<li>Chronic nasal congestion or deviated septum</li>
<li>Family history of OSA</li>
<li>Hypothyroidism (causes tissue edema in the upper airway)</li>
</ul>

<h3>Symptoms Beyond Snoring</h3>

<p>Many people with OSA don't snore loudly. Watch for these under-recognized symptoms:</p>

<ul>
<li>Waking with a dry mouth or sore throat</li>
<li>Morning headaches (from nocturnal CO2 retention)</li>
<li>Nocturia (waking to urinate 2+ times per night — OSA increases atrial natriuretic peptide)</li>
<li>Bruxism (teeth grinding — a reflex to reopen the airway)</li>
<li>Resistant hypertension (blood pressure that doesn't respond to 3+ medications)</li>
<li>Sudden drops in blood oxygen on wearable data (SpO2 dipping below 90%)</li>
</ul>

<h3>When to Get a Sleep Study</h3>

<p>The AASM recommends polysomnography or a home sleep apnea test (HSAT) for anyone with:</p>

<ol>
<li>An Epworth Sleepiness Scale score ≥10 (excessive daytime sleepiness)</li>
<li>STOP-BANG score ≥3 (validated OSA screening questionnaire)</li>
<li>Witnessed apneas (partner reports breathing pauses)</li>
<li>Treatment-resistant hypertension</li>
<li>Atrial fibrillation with daytime sleepiness</li>
</ol>

<p>Home sleep tests are more convenient but less sensitive — they can miss mild OSA and cannot detect central sleep apnea. If your HSAT is negative but clinical suspicion is high, <strong>insist on an in-lab polysomnography</strong>.</p>

<blockquote>
<p><strong>Wearable clue:</strong> If your Oura, Apple Watch, or Garmin consistently shows SpO2 dips below 92% during sleep — or your breathing regularity metric is frequently flagged — this is a strong signal to pursue formal sleep apnea testing. Wearables cannot diagnose OSA, but they can tell you to stop ignoring it.</p>
</blockquote>

<h2>Best Supplements for Sleep: What the Evidence Actually Shows</h2>

<p>The sleep supplement market is a $2.2 billion industry, and most of it is marketing noise. Here's what rigorous clinical evidence supports, what's promising but unproven, and what's a waste of money.</p>

<h3>Evidence-Based Sleep Supplements</h3>

<table>
<thead>
<tr>
<th>Supplement</th>
<th>Effective Dose</th>
<th>Evidence Level</th>
<th>Mechanism</th>
<th>Best For</th>
</tr>
</thead>
<tbody>
<tr>
<td><strong>Magnesium Glycinate</strong></td>
<td>200–400 mg elemental Mg, 60 min before bed</td>
<td>Strong (multiple RCTs)</td>
<td>GABA-A receptor agonism, NMDA antagonism, cortisol modulation</td>
<td>Sleep onset, muscle relaxation, anxiety-related insomnia</td>
</tr>
<tr>
<td><strong>L-Theanine</strong></td>
<td>200–400 mg, 30–60 min before bed</td>
<td>Moderate (several RCTs)</td>
<td>Increases alpha brain waves, boosts GABA, glycine, and dopamine</td>
<td>Anxious/racing thoughts at bedtime, difficulty unwinding</td>
</tr>
<tr>
<td><strong>Glycine</strong></td>
<td>3 g, 60 min before bed</td>
<td>Moderate (2–3 RCTs)</td>
<td>Lowers core body temperature via peripheral vasodilation, NMDA co-agonist</td>
<td>Difficulty with sleep onset, improving subjective sleep quality</td>
</tr>
<tr>
<td><strong>Apigenin</strong></td>
<td>50 mg, 30–60 min before bed</td>
<td>Emerging (preclinical + anecdotal)</td>
<td>Binds benzodiazepine site on GABA-A receptors (mild anxiolytic)</td>
<td>Mild anxiety, difficulty relaxing at night</td>
</tr>
<tr>
<td><strong>Tart Cherry Extract</strong></td>
<td>480 mg (or 8 oz juice), 60 min before bed</td>
<td>Moderate (several RCTs)</td>
<td>Natural source of melatonin + anti-inflammatory anthocyanins</td>
<td>Older adults, mild insomnia, exercise recovery</td>
</tr>
</tbody>
</table>

<h3>What About Melatonin?</h3>

<p>Melatonin is the most popular sleep supplement — and the most misunderstood. Key points:</p>

<ul>
<li><strong>It's a timing signal, not a sedative.</strong> Melatonin tells your body <em>when</em> to sleep, not <em>how</em> to sleep. It's most effective for circadian misalignment (jet lag, shift work, delayed sleep phase) — not for general insomnia.</li>
<li><strong>Most people take far too much.</strong> Physiological doses are 0.3–0.5 mg. The 5–10 mg tablets common in stores are 10–30x the physiological dose and can cause grogginess, vivid dreams, and — paradoxically — disrupt sleep architecture.</li>
<li><strong>Quality control is abysmal.</strong> A 2017 study in the <em>Journal of Clinical Sleep Medicine</em> found that actual melatonin content in supplements ranged from 83% less to 478% more than what the label stated. Some even contained serotonin, an unlisted controlled substance.</li>
</ul>

<div class="callout-box">
<h3>A Practical Sleep Supplement Stack</h3>
<p>If you're looking for a single protocol to start with, this combination has the broadest evidence base and safety profile: <strong>200–400 mg magnesium glycinate + 200 mg L-theanine</strong>, taken 60 minutes before bed. Add 3 g glycine if sleep onset is the primary issue. This stack targets GABA activation, cortisol reduction, and core temperature drop — the three main physiological prerequisites for sleep initiation. Cycle off for one week every 8 weeks to assess baseline.</p>
</div>

<h2>Lifestyle Protocols That Actually Move the Needle</h2>

<p>We're putting this section after the clinical content intentionally. These interventions work — but they work best when underlying deficiencies and disorders have been addressed first.</p>

<h3>Temperature: The Most Underrated Sleep Lever</h3>

<p>Your core body temperature must drop by approximately 1–1.5°C (2–3°F) to initiate sleep. This is not optional — it's a physiological requirement controlled by your hypothalamus. Strategies to facilitate this drop:</p>

<ul>
<li><strong>Bedroom temperature:</strong> 65–67°F (18–19°C). Data from a 2024 study tracking 11 million nights of sleep found that ambient temperatures above 77°F reduced sleep duration by an average of 14 minutes per night, with steeper effects in adults over 65.</li>
<li><strong>Hot shower or bath 90 minutes before bed:</strong> Counterintuitively, warming the body's surface triggers peripheral vasodilation, which <em>accelerates</em> core heat loss. Studies show this reduces sleep onset latency by an average of 10 minutes.</li>
<li><strong>Cooling mattress pads:</strong> Devices like the Eight Sleep or ChiliPad that actively cool the sleep surface have shown meaningful improvements in deep sleep percentage and HRV in controlled trials.</li>
</ul>

<h3>Light Exposure: Timing Is Everything</h3>

<p>Light is the most powerful zeitgeber (time-giver) for your circadian system. The protocol is simple but non-negotiable:</p>

<ul>
<li><strong>Morning (within 30 minutes of waking):</strong> 10+ minutes of direct outdoor light exposure. Even on overcast days, outdoor light provides 10,000–50,000 lux vs. ~500 lux from indoor lighting. This sets the cortisol awakening response and anchors your circadian clock.</li>
<li><strong>Evening (2–3 hours before bed):</strong> Dim lights to below 50 lux. Switch to warm, low-intensity lighting. Blue-blocking glasses help, but reducing total light intensity matters more. A 2019 study in <em>PNAS</em> showed that even dim room light in the evening suppressed melatonin onset by 90 minutes compared to candlelight conditions.</li>
</ul>

<h3>Caffeine Timing: The 10-Hour Rule</h3>

<p>Caffeine has a half-life of 5–7 hours (longer with certain CYP1A2 gene variants). But the <em>quarter-life</em> — the time for 75% to clear — is 10–12 hours. That means a 2 PM coffee still has 25% of its caffeine circulating at midnight. A 2023 meta-analysis in <em>Sleep Medicine Reviews</em> confirmed that caffeine consumed within 8.8 hours of bedtime significantly reduced total sleep time and sleep efficiency, even when subjects reported no difficulty falling asleep.</p>

<p><strong>Practical rule:</strong> Set a hard caffeine cutoff at least 10 hours before your target bedtime. If you sleep at 10:30 PM, last caffeine by 12:30 PM. If you're a slow metabolizer (you know who you are), push it to before noon.</p>

<h2>Exercise and Recovery: How Training Affects Sleep</h2>

<p>Exercise is one of the most powerful interventions for sleep quality — but the relationship is bidirectional and more nuanced than "just work out more."</p>

<h3>What the Research Shows</h3>

<ul>
<li><strong>Aerobic exercise</strong> (30+ minutes of moderate-intensity activity) improves sleep onset latency, total sleep time, and deep sleep percentage. Effects are strongest when exercise occurs 4–8 hours before bedtime.</li>
<li><strong>Resistance training</strong> improves sleep quality comparably to aerobic exercise, with additional benefits for anxiety and subjective sleep satisfaction (a 2022 meta-analysis in <em>Sports Medicine</em> pooled 13 RCTs).</li>
<li><strong>High-intensity exercise within 2 hours of sleep</strong> can impair sleep onset in some individuals by elevating core temperature and sympathetic tone. However, a 2023 Cochrane review found this effect is smaller than previously believed and highly individual.</li>
</ul>

<h3>Overtraining and Sleep Disruption</h3>

<p>Paradoxically, <strong>too much exercise — or too much intensity without adequate recovery — destroys sleep quality</strong>. Signs of overtraining-related sleep disruption:</p>

<ul>
<li>Elevated resting heart rate (5+ bpm above baseline for 3+ consecutive days)</li>
<li>Falling HRV trend despite consistent sleep duration</li>
<li>Difficulty falling asleep despite physical exhaustion</li>
<li>Waking in the early morning hours (3–4 AM) and being unable to return to sleep (nocturnal cortisol spikes)</li>
<li>Declining performance despite maintained training volume</li>
</ul>

<p>If your wearable data shows this pattern, the prescription is counterintuitive: <strong>train less, sleep more, and wait for HRV to stabilize for 5+ consecutive days before resuming full training load.</strong></p>

<h2>When to See a Sleep Medicine Specialist</h2>

<p>Self-optimization has limits. Here are the clear signals that it's time to involve a board-certified sleep medicine physician:</p>

<ol>
<li><strong>Persistent insomnia lasting more than 3 months</strong> despite implementing sleep hygiene, addressing nutrient deficiencies, and managing stress. First-line treatment is <strong>Cognitive Behavioral Therapy for Insomnia (CBT-I)</strong>, which is more effective than medication in the long term (AASM clinical practice guidelines, 2021).</li>
<li><strong>Suspected sleep apnea:</strong> Snoring, witnessed apneas, morning headaches, or SpO2 dips on wearable data.</li>
<li><strong>Excessive daytime sleepiness</strong> that interferes with driving, work, or daily activities, particularly if sleep duration and quality appear adequate.</li>
<li><strong>Restless legs or periodic limb movements</strong> — especially with ferritin below 75 ng/mL (the threshold used by sleep medicine specialists, not the general lab reference range).</li>
<li><strong>Parasomnias:</strong> Sleepwalking, sleep talking, REM sleep behavior disorder (acting out dreams — this warrants urgent evaluation as it can be an early marker for neurodegenerative conditions).</li>
<li><strong>Shift work sleep disorder:</strong> If you work night shifts or rotating shifts and standard circadian strategies aren't providing sufficient relief.</li>
</ol>

<div class="callout-box">
<h3>How to Find a Sleep Medicine Specialist</h3>
<p>Look for a physician who is <strong>board-certified in sleep medicine</strong> by the American Board of Medical Specialties (ABMS). You can verify certification at <strong>certificationmatters.org</strong>. Sleep medicine is a subspecialty — doctors can come from backgrounds in pulmonology, neurology, psychiatry, or internal medicine. For complex cases involving both sleep and fatigue, a neurologist or internist with sleep medicine fellowship training often provides the most comprehensive evaluation.</p>
</div>

<p style="margin-top:20px;"><a class="btn-primary" href="/book?concern=sleep&source=guide-recovery-referral">Book An Appointment With A Specialist →</a></p>

<h2>Putting It All Together: A Decision Framework for Chronic Fatigue</h2>

<p>If you've read this far, you now understand that fatigue and poor sleep rarely have a single cause. Here's the systematic approach we recommend:</p>

<ol>
<li><strong>Get the right labs:</strong> Ferritin, vitamin D (25-OH), RBC magnesium, B12, complete thyroid panel (TSH, free T3, free T4, reverse T3, TPO antibodies), and a four-point salivary cortisol or DUTCH test. Compare results to optimal ranges, not just standard reference ranges.</li>
<li><strong>Screen for sleep apnea:</strong> Complete the STOP-BANG questionnaire. If you score 3+, or if you have any risk factors plus unrefreshing sleep, get a sleep study.</li>
<li><strong>Track with a wearable:</strong> Use 30 days of baseline data to establish your personal norms for HRV, resting heart rate, deep sleep, and REM. Then use trends — not individual nights — to assess interventions.</li>
<li><strong>Address deficiencies first:</strong> Correct any nutrient deficiencies identified in step 1. This alone resolves symptoms in roughly 30–40% of people with unexplained fatigue.</li>
<li><strong>Layer in lifestyle protocols:</strong> Temperature, light exposure, caffeine timing, exercise timing. Give each intervention 2–3 weeks before evaluating.</li>
<li><strong>Consider targeted supplements:</strong> Magnesium glycinate + L-theanine as a baseline. Add glycine for sleep onset issues. If cortisol dysregulation is confirmed, work with a practitioner on adaptogen protocols.</li>
<li><strong>Escalate when needed:</strong> If 8–12 weeks of optimization don't resolve symptoms, see a sleep medicine specialist. Persistent fatigue despite adequate sleep quality and normal labs warrants further workup for conditions like chronic fatigue syndrome, autonomic dysfunction, or idiopathic hypersomnia.</li>
</ol>

<blockquote>
<p><strong>The bottom line:</strong> Chronic fatigue and poor sleep quality are symptoms, not diagnoses. Behind every case of "I'm just tired" is a specific, identifiable mechanism — and in most cases, it can be measured, addressed, and resolved. The key is stopping the guesswork and starting with the right data.</p>
</blockquote>
""",
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
@app.route("/guides/metabolic", defaults={"slug": "metabolic"})
@app.route("/guides/hormones", defaults={"slug": "hormones"})
@app.route("/guides/recovery", defaults={"slug": "recovery"})
def program_detail(slug: str):
    program = _PROGRAM_DATA.get(slug)
    if not program:
        abort(404)
    cluster_ctx = build_cluster_ctx(f"/guides/{slug}")
    return render_template("program_detail.html.j2", program=program, cluster_ctx=cluster_ctx)


@app.route("/assessment")
def assessment_landing():
    return render_template("assessment_landing.html.j2")


@app.route("/assessment/start")
def assessment_start():
    return redirect("/assessment/quiz")


@app.route("/assessment/quiz")
def assessment_quiz():
    return render_template("assessment_quiz.html.j2")


@app.route("/pricing")
def pricing():
    return render_template("pricing.html.j2")


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
    allowed_concerns = {"metabolic", "hormones", "sleep", "fatigue", "general"}
    concern = (request.args.get("concern") or "general").strip().lower()
    if concern not in allowed_concerns:
        concern = "general"
    return render_template(
        "doctors.html.j2",
        selected_concern=concern,
        source=(request.args.get("source") or "direct").strip(),
        result_context=(request.args.get("result_context") or "").strip(),
    )


@app.route("/book/confirmation")
def doctor_request_confirmation():
    return render_template("doctor_request_confirmation.html.j2")


# ═══════════════════════════════════════════════════════════════════════
#  ROUTES — Blog (Briefing)
# ═══════════════════════════════════════════════════════════════════════

@app.route("/briefing")
def briefing_index():
    from scripts.generate_seo_pages import PAGES as _STATIC_PAGES
    from src.seo.cluster_topology import CLUSTERS

    articles_by_cluster: dict[str, list] = {}
    for cluster_key, cluster in CLUSTERS.items():
        items = []
        for member in cluster.members:
            page = _STATIC_PAGES.get(member.path)
            if page:
                items.append({
                    "path": member.path,
                    "title": page.title,
                    "summary": page.summary,
                    "cluster": cluster_key,
                    "page_type": page.page_type,
                })
        articles_by_cluster[cluster_key] = items

    return render_template(
        "blog_index.html.j2",
        posts=[],
        articles_by_cluster=articles_by_cluster,
        clusters=CLUSTERS,
    )


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
    "hormone-optimization/menopause": "Menopause, Fatigue & Weight Gain",
    "hormone-optimization/perimenopause": "Perimenopause Symptoms, Fatigue & Weight Gain",
    "sleep-recovery": "Sleep & Recovery",
    "sleep-recovery/sleep-apnea": "Sleep Apnea, Fatigue & Weight Gain",
    "lab-testing": "Lab Testing & Biomarkers",
    "peptides": "Peptide Therapy — BPC-157, Ipamorelin, Sermorelin & More",
    "peptide-therapy": "Peptide Therapy: What It Is, How It Works, and Who It's For",
    "symptoms": "Metabolic & Hormonal Symptoms",
    "biomarkers": "Key Biomarkers for Metabolic Health",
    "conditions": "Conditions Linked to Metabolic Dysfunction",
    "causes": "Root Causes of Hormonal Imbalance",
    "labs": "Lab Tests for Metabolic & Hormone Health",
    "compare": "Treatment Comparisons",
    "why-am-i": "Why Am I...? Symptom Explainers",
}


@app.route("/metabolic-health")
@app.route("/hormone-optimization")
@app.route("/hormone-optimization/menopause")
@app.route("/hormone-optimization/perimenopause")
@app.route("/sleep-recovery")
@app.route("/sleep-recovery/sleep-apnea")
@app.route("/lab-testing")
@app.route("/peptides")
@app.route("/peptide-therapy")
@app.route("/symptoms")
@app.route("/biomarkers")
@app.route("/conditions")
@app.route("/causes")
@app.route("/labs")
@app.route("/compare")
@app.route("/why-am-i")
def hub_page():
    slug = request.path.lstrip("/")
    title = _HUB_PAGES.get(slug, slug.replace("-", " ").title())
    return _db_landing_page_or_stub(page_key=f"hub-{slug}", page_type="hub", title=title)


@app.route("/recommendations")
def recommendations_page():
    return render_template("recommendations.html.j2")


# ═══════════════════════════════════════════════════════════════════════
#  ROUTES — Peptide Profile Pages
# ═══════════════════════════════════════════════════════════════════════

_PEPTIDE_PROFILES = {
    "bpc-157": "BPC-157: Benefits, Dosage, Side Effects & Research",
    "ipamorelin": "Ipamorelin: Growth Hormone Peptide Guide",
    "sermorelin": "Sermorelin: Anti-Aging GH Therapy Guide",
    "cjc-1295": "CJC-1295: GHRH Analog Benefits & Dosage",
    "tb-500": "TB-500 (Thymosin Beta-4): Tissue Repair Guide",
    "epithalon": "Epithalon: Longevity Peptide Research & Dosage",
    "semax": "Semax: Cognitive Peptide & Nootropic Guide",
    "selank": "Selank: Anti-Anxiety Peptide Guide",
    "tesamorelin": "Tesamorelin: FDA-Approved GH Peptide Guide",
    "healing": "Peptides for Healing: Tissue Repair & Recovery",
    "muscle-growth": "Peptides for Muscle Growth: Best Options & Protocols",
    "anti-aging": "Longevity Peptides: Anti-Aging Research & Guide",
    "weight-loss": "Peptides for Weight Loss: GLP-1, Tesamorelin & What Works",
    "nad": "NAD+ Peptides and Therapy: Benefits, Injections & Research",
    "glp-1": "GLP-1 Peptides: Semaglutide, Tirzepatide, Retatrutide & How They Work",
    "hgh": "HGH Peptides vs. Human Growth Hormone: What's the Difference?",
    "skin": "Peptides for Skin: GHK-Cu, Collagen Peptides & What Actually Works",
    "collagen": "Collagen Peptides: Benefits, Types & What the Research Shows",
    "igf-1-lr3": "IGF-1 LR3: Mechanism, Risks, and What the Research Actually Shows",
    "wolverine-stack": "The Wolverine Stack: BPC-157 + TB-500 Protocol for Injury Recovery",
    "aod-9604": "AOD-9604: The Fat-Loss Peptide That Failed Phase III (And What Works Instead)",
}


@app.route("/peptides/<slug>")
def peptide_profile_page(slug: str):
    title = _PEPTIDE_PROFILES.get(slug, slug.replace("-", " ").title())
    page_key = f"guide-peptides-{slug}"
    cluster_ctx = build_cluster_ctx(f"/peptides/{slug}")
    return _db_landing_page_or_stub(page_key=page_key, page_type="guide", title=title)


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
        "cluster": "recovery",
        "description": "Evaluate your energy levels across metabolic, hormonal, and recovery domains. Based on validated clinical symptom scales, this assessment identifies which systems may be contributing to fatigue, brain fog, or low performance.",
        "inputs": ["Age and sex", "Energy patterns throughout the day", "Sleep quality and duration", "Exercise habits and recovery", "Stress levels", "Dietary patterns", "Current symptoms"],
        "outputs": ["Overall energy score (0-100)", "Metabolic health risk indicator", "Hormonal health risk indicator", "Recovery quality indicator", "Recommended lab panel based on your symptoms", "Personalized next steps"],
    },
    "metabolic-score": {
        "name": "Metabolic Health Score Calculator",
        "slug": "metabolic-score",
        "cluster": "metabolism",
        "description": "Estimate your metabolic health status using the five criteria defined by the AHA/NHLBI: waist circumference, triglycerides, HDL cholesterol, blood pressure, and fasting glucose. Research published in the Journal of the American College of Cardiology found only ~7% of US adults meet optimal levels for all five markers.",
        "inputs": ["Waist circumference (inches)", "Triglycerides (mg/dL) — if known", "HDL cholesterol (mg/dL) — if known", "Blood pressure (systolic/diastolic)", "Fasting glucose (mg/dL) — if known", "Age and sex"],
        "outputs": ["Metabolic health score (0-5 criteria met)", "Risk category (optimal, at-risk, metabolic syndrome)", "Which markers need attention", "Recommended lab tests for markers you don't know", "Comparison to population averages by age group"],
    },
    "hormone-checker": {
        "name": "Hormone Symptom Checker",
        "slug": "hormone-checker",
        "cluster": "hormones",
        "description": "Identify which hormonal systems may be driving your symptoms. Maps your reported symptoms to testosterone, estrogen, thyroid, cortisol, and other hormonal pathways using clinically validated symptom-to-hormone associations from endocrinology literature.",
        "inputs": ["Age, sex, and menstrual status (if applicable)", "Fatigue patterns", "Weight and body composition changes", "Mood and cognitive symptoms", "Sexual health symptoms", "Hair, skin, and temperature changes", "Menstrual irregularities (women)"],
        "outputs": ["Likelihood scores for: low testosterone, thyroid dysfunction, cortisol dysregulation, estrogen imbalance, DHEA decline", "Gender-specific hormone panel recommendation", "Symptom-to-hormone mapping explanation", "Suggested next steps"],
    },
    "sleep-score": {
        "name": "Sleep Recovery Score",
        "slug": "sleep-score",
        "cluster": "recovery",
        "description": "Assess your sleep quality and recovery capacity beyond just hours in bed. Incorporates elements from validated sleep assessment tools (Pittsburgh Sleep Quality Index, Epworth Sleepiness Scale) to evaluate sleep onset, continuity, architecture, and daytime impact.",
        "inputs": ["Typical bedtime and wake time", "Time to fall asleep", "Number of nighttime awakenings", "How refreshed you feel on waking (1-10)", "Daytime sleepiness level", "Snoring or breathing issues", "Caffeine and alcohol use", "Wearable sleep data (optional)"],
        "outputs": ["Sleep quality score (0-100)", "Sleep efficiency estimate", "Sleep apnea risk indicator (based on STOP-BANG screening criteria)", "Recovery capacity rating", "Recommended lab tests (cortisol, ferritin, thyroid, vitamin D)", "Actionable recommendations"],
    },
    "insulin-resistance-calculator": {
        "name": "Insulin Resistance Risk Calculator",
        "slug": "insulin-resistance-calculator",
        "cluster": "metabolism",
        "description": "Estimate your insulin resistance risk using surrogate markers validated in clinical research. The gold standard test (hyperinsulinemic euglycemic clamp) is impractical for routine use, but HOMA-IR, triglyceride-to-HDL ratio, and waist circumference provide reliable clinical estimates per ADA guidelines.",
        "inputs": ["Fasting insulin (μIU/mL) — if known", "Fasting glucose (mg/dL) — if known", "Triglycerides (mg/dL) — if known", "HDL cholesterol (mg/dL) — if known", "Waist circumference (inches)", "Age, sex, and ethnicity", "Family history of type 2 diabetes", "Physical activity level"],
        "outputs": ["HOMA-IR score (if fasting insulin and glucose provided; optimal <1.5, insulin resistant >2.9)", "Triglyceride-to-HDL ratio (optimal <2.0; >3.0 signals insulin resistance)", "Clinical risk category (low, moderate, high)", "Which additional labs to order if data is incomplete", "Evidence-based recommendations"],
    },
    "peptide-finder": {
        "name": "Peptide Finder",
        "slug": "peptide-finder",
        "cluster": "peptides",
        "description": "Answer 6 questions about your primary goal, health status, and preferences to get personalized peptide recommendations ranked by relevance. Based on the clinical research profiles of 12 therapeutic peptides.",
        "inputs": ["Primary goal (healing/recovery, muscle & performance, cognitive, anti-aging, weight & body composition, anxiety & stress)", "Age range", "Experience level with peptides", "Preferred administration route (injectable vs non-injectable)", "Budget range", "Any relevant health conditions or considerations"],
        "outputs": ["Top 2–3 peptide recommendations with rationale", "Evidence summary for each recommended peptide", "Suggested starting protocol (dose range, timing, cycle length)", "Notes on access and legal status", "Links to detailed peptide profile pages"],
        "interactive": True,
    },
}

_TOOL_SLUGS = {slug: data["name"] for slug, data in _TOOLS.items()}


def _tool_page_seo(tool: dict) -> dict:
    """Build SERP metadata for interactive calculator pages."""
    base = settings.canonical_site_url
    canonical = f"{base}/tools/{tool['slug']}"
    description = (tool.get("description") or "").strip()
    if len(description) > 160:
        description = description[:157].rsplit(" ", 1)[0].rstrip(" ,.;:") + "..."

    keywords = [
        tool["name"],
        tool["slug"].replace("-", " "),
        "health calculator",
        "metabolic health tool",
    ]

    suffix = f" | {settings.site_name}"
    full_title = f"{tool['name']}{suffix}"
    if len(full_title) > 70:
        full_title = tool["name"][:70] if len(tool["name"]) > 70 else tool["name"]

    return {
        "title": full_title,
        "description": description,
        "keywords": ", ".join(keywords),
        "canonical": canonical,
        "site_name": settings.site_name,
        "site_url": base,
        "locale": settings.site_locale,
        "og_image": f"{base}/static/og-image.png",
        "og_type": "website",
    }


@app.route("/tools")
def tools_index():
    return render_template("tools_index.html.j2")


@app.route("/tools/<slug>")
def tool_page(slug: str):
    tool = _TOOLS.get(slug)
    if not tool:
        abort(404)
    seo = _tool_page_seo(tool)
    jsonld_obj = {
        "@context": "https://schema.org",
        "@type": "WebApplication",
        "name": tool["name"],
        "description": seo.get("description", ""),
        "url": seo.get("canonical", ""),
        "applicationCategory": "HealthApplication",
        "publisher": {
            "@type": "Organization",
            "name": settings.site_name,
            "url": settings.canonical_site_url,
        },
    }
    cluster = tool.get("cluster", "")
    return render_template(
        "tool_page.html.j2", tool=tool, seo=seo, jsonld=json.dumps(jsonld_obj), cluster=cluster
    )


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
#  ROUTES — API: Feedback
# ═══════════════════════════════════════════════════════════════════════

@app.route("/api/feedback", methods=["POST"])
def api_feedback():
    """Accept desktop feedback submissions and email them to the site owner."""
    data = request.get_json(silent=True) or {}
    feedback = (data.get("feedback") or "").strip()
    page_url = (data.get("page_url") or "").strip()

    if not feedback:
        return jsonify({"error": "Feedback is required."}), 400
    if len(feedback) > 2000:
        return jsonify({"error": "Feedback must be 2000 characters or fewer."}), 400

    submitted_at = datetime.now(timezone.utc)
    sent = _send_feedback_notification(
        feedback=feedback,
        page_url=page_url,
        user_agent=request.headers.get("User-Agent", ""),
        submitted_at=submitted_at,
    )
    if not sent:
        return jsonify({"error": "Could not send feedback."}), 502

    return jsonify({"ok": True})


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
                interests = set(existing.interests_json or [])
                interests.add(tag)
                existing.interests_json = sorted(interests)
                existing.source = existing.source or "lead-magnet"
            else:
                sub = Subscriber(email=email, source="lead-magnet", interests_json=[tag])
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
    location = (request.form.get("location") or "").strip()
    preferences = (request.form.get("preferences") or "").strip()
    source = (request.form.get("source") or "direct").strip()
    result_context = (request.form.get("result_context") or "").strip()
    submitted_at = datetime.now(timezone.utc).isoformat()

    if not email or "@" not in email:
        return redirect(
            "/book?"
            + urlencode(
                {
                    "concern": concern or "general",
                    "source": source or "direct",
                    "result_context": result_context,
                    "error": "invalid-email",
                }
            )
        )

    tag = f"doctor-request-{concern}" if concern else "doctor-request"

    try:
        from src.models import ConsultationBooking, BookingStatus, Subscriber, SessionLocal, init_db
        init_db()
        db = SessionLocal()
        try:
            existing = db.query(Subscriber).filter_by(email=email).first()
            if existing:
                interests = set(existing.interests_json or [])
                interests.update([tag, "doctor-request"])
                existing.interests_json = sorted(interests)
                existing.source = existing.source or "doctor-request"
            else:
                sub = Subscriber(
                    email=email,
                    name=name,
                    source="doctor-request",
                    interests_json=[tag, "doctor-request"],
                )
                db.add(sub)
            notes = json.dumps(
                {
                    "concern": concern,
                    "location": location,
                    "preferences": preferences,
                    "source": source,
                    "result_context": result_context,
                    "submitted_at": submitted_at,
                },
                ensure_ascii=True,
            )
            db.add(
                ConsultationBooking(
                    email=email,
                    name=name,
                    booking_type=f"specialist-{concern or 'general'}",
                    notes=notes,
                    status=BookingStatus.PENDING,
                )
            )
            db.commit()
        finally:
            db.close()
    except Exception as exc:
        logger.warning("Doctor request DB save failed: %s", exc)

    logger.info(
        "Doctor request submitted: concern=%s source=%s result_context=%s email=%s",
        concern or "general",
        source or "direct",
        result_context or "none",
        email,
    )
    _send_doctor_request_notification(
        name=name,
        email=email,
        concern=concern,
        location=location,
        preferences=preferences,
        source=source,
        result_context=result_context,
        submitted_at=submitted_at,
    )

    return redirect("/book/confirmation")


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

_SITEMAP_PRIMARY = [
    ("/", "1.0", "daily"),
    ("/guides", "0.9", "weekly"),
    ("/guides/metabolic", "0.9", "weekly"),
    ("/guides/hormones", "0.9", "weekly"),
    ("/guides/recovery", "0.9", "weekly"),
    ("/metabolic-health", "0.9", "weekly"),
    ("/hormone-optimization", "0.9", "weekly"),
    ("/sleep-recovery", "0.9", "weekly"),
    ("/lab-testing", "0.9", "weekly"),
    ("/peptides", "0.9", "weekly"),
    ("/peptide-therapy", "0.8", "monthly"),
    ("/symptoms", "0.9", "weekly"),
    ("/biomarkers", "0.9", "weekly"),
    ("/conditions", "0.9", "weekly"),
    ("/causes", "0.8", "weekly"),
    ("/labs", "0.8", "weekly"),
    ("/compare", "0.8", "weekly"),
    ("/why-am-i", "0.8", "weekly"),
    ("/recommendations", "0.8", "weekly"),
    ("/assessment", "0.8", "monthly"),
    ("/how-it-works", "0.8", "monthly"),
    ("/about", "0.7", "monthly"),
    ("/tools", "0.7", "monthly"),
]

_SITEMAP_PEPTIDES = [
    ("/peptides/bpc-157", "0.8", "monthly"),
    ("/peptides/ipamorelin", "0.8", "monthly"),
    ("/peptides/sermorelin", "0.8", "monthly"),
    ("/peptides/cjc-1295", "0.7", "monthly"),
    ("/peptides/tb-500", "0.7", "monthly"),
    ("/peptides/epithalon", "0.7", "monthly"),
    ("/peptides/semax", "0.7", "monthly"),
    ("/peptides/selank", "0.7", "monthly"),
    ("/peptides/tesamorelin", "0.7", "monthly"),
    ("/peptides/healing", "0.7", "monthly"),
    ("/peptides/muscle-growth", "0.7", "monthly"),
    ("/peptides/anti-aging", "0.7", "monthly"),
    ("/compare/bpc-157-vs-tb-500", "0.7", "monthly"),
    ("/compare/tesamorelin-vs-sermorelin", "0.7", "monthly"),
    ("/compare/sarms-vs-peptides", "0.7", "monthly"),
    ("/faq/are-peptides-legal", "0.7", "monthly"),
    ("/tools/peptide-finder", "0.7", "monthly"),
    # New pages from keyword gap analysis
    ("/peptides/weight-loss", "0.8", "monthly"),
    ("/peptides/nad", "0.7", "monthly"),
    ("/peptides/glp-1", "0.8", "monthly"),
    ("/peptides/hgh", "0.7", "monthly"),
    ("/peptides/skin", "0.7", "monthly"),
    ("/peptides/collagen", "0.7", "monthly"),
    # Gap pages — May 2026 keyword analysis
    ("/compare/cjc-1295-ipamorelin-stack", "0.8", "monthly"),
    ("/guides/how-to-reconstitute-peptides", "0.7", "monthly"),
    ("/peptides/igf-1-lr3", "0.7", "monthly"),
    ("/peptides/wolverine-stack", "0.7", "monthly"),
    ("/peptides/aod-9604", "0.7", "monthly"),
]

_SITEMAP_TOOLS = [
    ("/tools/energy-assessment", "0.6", "monthly"),
    ("/tools/metabolic-score", "0.6", "monthly"),
    ("/tools/hormone-checker", "0.6", "monthly"),
    ("/tools/sleep-score", "0.6", "monthly"),
    ("/tools/insulin-resistance-calculator", "0.6", "monthly"),
    ("/tools/peptide-finder", "0.7", "monthly"),
    ("/results", "0.4", "monthly"),
    ("/faq", "0.4", "monthly"),
    ("/doctors", "0.4", "monthly"),
]


def _build_urlset(entries, lastmod_by_path: dict[str, str] | None = None) -> str:
    base = _xml_escape(settings.canonical_site_url)
    urls = ""
    for path, priority, freq, lastmod in _with_lastmods(entries, lastmod_by_path):
        urls += f"""<url>
  <loc>{base}{path}</loc>
  <lastmod>{lastmod}</lastmod>
  <changefreq>{freq}</changefreq>
  <priority>{priority}</priority>
</url>\n"""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{urls}</urlset>"""


def _default_sitemap_lastmod() -> str:
    raw = os.getenv("SITEMAP_DEFAULT_LASTMOD", "2026-05-01").strip()
    try:
        return date.fromisoformat(raw).isoformat()
    except ValueError:
        logger.warning("sitemap: invalid SITEMAP_DEFAULT_LASTMOD=%r, using fallback", raw)
        return "2026-05-01"


def _to_sitemap_date(value, fallback: str | None = None) -> str:
    if value is None:
        return fallback or _default_sitemap_lastmod()
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return fallback or _default_sitemap_lastmod()
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).date().isoformat()
        except ValueError:
            try:
                return date.fromisoformat(raw[:10]).isoformat()
            except ValueError:
                return fallback or _default_sitemap_lastmod()
    return fallback or _default_sitemap_lastmod()


def _landing_page_lastmods() -> dict[str, str]:
    try:
        from src.models import LandingPage, SessionLocal, init_db
        init_db()
        db = SessionLocal()
        try:
            rows = (
                db.query(
                    LandingPage.canonical_path,
                    LandingPage.updated_at,
                    LandingPage.last_generated_at,
                    LandingPage.created_at,
                )
                .all()
            )
            return {
                (path or "").rstrip("/") or "/": _to_sitemap_date(
                    updated_at or last_generated_at or created_at
                )
                for path, updated_at, last_generated_at, created_at in rows
                if path
            }
        finally:
            db.close()
    except Exception as exc:
        logger.warning("sitemap: could not load landing page lastmod dates: %s", exc)
        return {}


def _with_lastmods(entries, lastmod_by_path: dict[str, str] | None = None):
    lastmod_by_path = lastmod_by_path or {}
    fallback = _default_sitemap_lastmod()
    for entry in entries:
        if len(entry) >= 4:
            path, priority, freq, lastmod = entry[:4]
            yield path, priority, freq, _to_sitemap_date(lastmod, fallback)
        else:
            path, priority, freq = entry
            yield path, priority, freq, lastmod_by_path.get(path, fallback)


def _latest_lastmod(entries, lastmod_by_path: dict[str, str] | None = None) -> str:
    dates = [lastmod for *_rest, lastmod in _with_lastmods(entries, lastmod_by_path)]
    return max(dates) if dates else _default_sitemap_lastmod()


def _primary_sitemap_entries() -> list[tuple[str, str, str]]:
    seo_paths = all_seo_paths()
    entries = list(_SITEMAP_PRIMARY)
    existing_paths = {path for path, _, _ in entries}
    for path in seo_paths:
        if path in existing_paths or path.startswith("/tools/"):
            continue
        entries.append((path, "0.8", "weekly"))
        existing_paths.add(path)
    return entries


def _content_sitemap_entries():
    entries: list[tuple[str, str, str, str]] = []
    adapter = app.url_map.bind("")
    try:
        from src.models import BlogPost, SessionLocal, init_db
        init_db()
        db = SessionLocal()
        try:
            posts = (
                db.query(
                    BlogPost.slug,
                    BlogPost.updated_at,
                    BlogPost.published_date,
                    BlogPost.created_at,
                )
                .order_by(BlogPost.published_date.desc())
                .all()
            )
            for slug, updated_at, published_date, created_at in posts:
                path = f"/briefing/{slug}"
                try:
                    adapter.match(path)
                    lastmod = _to_sitemap_date(updated_at or published_date or created_at)
                    entries.append((path, "0.7", "weekly", lastmod))
                except Exception:
                    logger.warning("sitemap: %s has no matching route, skipping", path)
        finally:
            db.close()
    except Exception:
        pass
    if not entries:
        entries.append(("/briefing", "0.6", "weekly", _default_sitemap_lastmod()))
    return entries


@app.route("/sitemap.xml")
def sitemap_index():
    base = _xml_escape(settings.canonical_site_url)
    landing_lastmods = _landing_page_lastmods()
    primary_lastmod = _latest_lastmod(_primary_sitemap_entries(), landing_lastmods)
    content_lastmod = _latest_lastmod(_content_sitemap_entries())
    peptides_lastmod = _latest_lastmod(_SITEMAP_PEPTIDES, landing_lastmods)
    tools_lastmod = _latest_lastmod(_SITEMAP_TOOLS, landing_lastmods)
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap>
    <loc>{base}/sitemap-primary.xml</loc>
    <lastmod>{primary_lastmod}</lastmod>
  </sitemap>
  <sitemap>
    <loc>{base}/sitemap-content.xml</loc>
    <lastmod>{content_lastmod}</lastmod>
  </sitemap>
  <sitemap>
    <loc>{base}/sitemap-peptides.xml</loc>
    <lastmod>{peptides_lastmod}</lastmod>
  </sitemap>
  <sitemap>
    <loc>{base}/sitemap-tools.xml</loc>
    <lastmod>{tools_lastmod}</lastmod>
  </sitemap>
</sitemapindex>"""
    return Response(xml, content_type="application/xml; charset=utf-8")


@app.route("/sitemap-primary.xml")
def sitemap_primary():
    return Response(
        _build_urlset(_primary_sitemap_entries(), _landing_page_lastmods()),
        content_type="application/xml; charset=utf-8",
    )


@app.route("/sitemap-content.xml")
def sitemap_content():
    return Response(_build_urlset(_content_sitemap_entries()), content_type="application/xml; charset=utf-8")


@app.route("/sitemap-peptides.xml")
def sitemap_peptides():
    return Response(
        _build_urlset(_SITEMAP_PEPTIDES, _landing_page_lastmods()),
        content_type="application/xml; charset=utf-8",
    )


@app.route("/sitemap-tools.xml")
def sitemap_tools():
    return Response(
        _build_urlset(_SITEMAP_TOOLS, _landing_page_lastmods()),
        content_type="application/xml; charset=utf-8",
    )


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
"""
    return Response(body, content_type="text/plain; charset=utf-8")


# ═══════════════════════════════════════════════════════════════════════
#  IndexNow — instant search engine notification
# ═══════════════════════════════════════════════════════════════════════

_INDEXNOW_KEY = "4cc1bd5a92d14002ba49f4f01765fd34"


@app.route("/4cc1bd5a92d14002ba49f4f01765fd34.txt")
def indexnow_key_file():
    return Response(_INDEXNOW_KEY, content_type="text/plain; charset=utf-8")


@app.route("/indexnow-submit", methods=["POST"])
def indexnow_submit():
    """Submit all important URLs to IndexNow (Bing, Yandex, Naver)."""
    import requests as _req

    base = settings.canonical_site_url
    host = base.replace("https://", "").replace("http://", "")

    seen: set[str] = set()
    url_list: list[str] = []
    for path, _, _ in _SITEMAP_PRIMARY:
        if path not in seen:
            seen.add(path)
            url_list.append(f"{base}{path}")
    for path in all_seo_paths():
        if path not in seen:
            seen.add(path)
            url_list.append(f"{base}{path}")
    for path, _, _ in _SITEMAP_TOOLS:
        if path not in seen:
            seen.add(path)
            url_list.append(f"{base}{path}")

    payload = {
        "host": host,
        "key": _INDEXNOW_KEY,
        "keyLocation": f"{base}/{_INDEXNOW_KEY}.txt",
        "urlList": url_list,
    }

    results = {}
    for engine in ["api.indexnow.org", "www.bing.com", "yandex.com"]:
        try:
            r = _req.post(
                f"https://{engine}/indexnow",
                json=payload,
                headers={"Content-Type": "application/json; charset=utf-8"},
                timeout=10,
            )
            results[engine] = {"status": r.status_code, "body": r.text[:200]}
        except Exception as exc:
            results[engine] = {"status": "error", "body": str(exc)[:200]}

    return jsonify({"urls_submitted": len(url_list), "results": results})


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
