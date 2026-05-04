from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    database_url: str = "sqlite:///./metabolic_health.db"
    storage_dir: Path = Path("./storage")
    output_dir: Path = Path("./output")

    log_level: str = "INFO"

    # ── LLM Analysis ────────────────────────────────────────────────
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    openai_narrative_model: str = "gpt-4o-mini"
    analysis_min_relevance: int = 5
    report_lookback_days: int = 120
    llm_call_budget_per_run: int = 200
    llm_input_price_per_mtok: float = 2.50
    llm_output_price_per_mtok: float = 10.00

    openai_premium_model: str = "gpt-5.2"
    llm_premium_input_price_per_mtok: float = 5.00
    llm_premium_output_price_per_mtok: float = 15.00

    # ── Newsletter ──────────────────────────────────────────────────
    newsletter_provider: str = "console"
    newsletter_from_email: str = ""
    newsletter_api_key: str = ""
    subscriber_list_path: str = "subscribers.json"
    seo_email_provider: str = "resend"
    seo_email_recipient: str = "<RECIPIENT_EMAIL>"
    seo_email_subject: str = "SEO Updates <SITE_NAME>"
    resend_api_key: str = ""

    # ── Stripe / Payments ───────────────────────────────────────────
    stripe_webhook_secret: str = ""
    stripe_consultation_payment_link_id: str = ""
    order_notification_email: str = ""
    order_email_provider: str = "resend"
    order_from_email: str = ""

    # ── Admin ───────────────────────────────────────────────────────
    admin_token: str = ""
    admin_key: str = ""
    admin_password: str = ""

    # ── Google Analytics ───────────────────────────────────────────
    # GA4 measurement ID (e.g. G-XXXXXXXXXX). Leave blank to disable.
    google_analytics_id: str = ""

    # ── Google Reporting (GA4 + Search Console) ─────────────────────
    google_reporting_sa_json: str = ""
    google_reporting_sa_file: str = ""
    google_reporting_ga4_property_id: str = ""
    google_reporting_gsc_site_url: str = ""
    google_reporting_output_dir: Path = Path("./output/google_reporting")
    google_reporting_ga_lookback_days: int = 30
    google_reporting_gsc_lookback_days: int = 90

    # ── Buttondown (subscriber signup) ──────────────────────────────
    buttondown_api_key: str = ""

    # ── Supabase Storage ────────────────────────────────────────────
    supabase_url: str = ""
    supabase_service_key: str = ""
    supabase_report_bucket: str = "reports"
    supabase_report_object_key: str = "report.html"

    # ── Server ──────────────────────────────────────────────────────
    server_port: int = 8080

    # ── SEO / Site Identity ─────────────────────────────────────────
    site_url: str = "https://localhost:5001"
    site_name: str = "Metabolic Health"
    site_owner_org: str = "Metabolic Health"
    site_locale: str = "en_US"

    @property
    def canonical_site_url(self) -> str:
        """Customer-facing base URL for emails, links, and SEO."""
        u = (self.site_url or "").strip().rstrip("/")
        if not u or "onrender.com" in u.lower():
            return "https://localhost:5001"
        return u

    # ── Blog / Content Generation ───────────────────────────────────
    blog_gen_budget_per_run: int = 6
    blog_gen_min_relevance: int = 5
    blog_gen_lookback_days: int = 14
    blog_gen_max_words: int = 900

    # ── Content Intake ──────────────────────────────────────────────
    google_news_daily_cap: int = 6
    content_scraper_timeout_seconds: int = 30
    content_scraper_max_retries: int = 3

    # ── SEO: Semrush API ────────────────────────────────────────────
    semrush_api_key: str = ""
    semrush_database: str = "us"

    # ── Backlink Outreach ───────────────────────────────────────────
    resend_outreach_from: str = ""
    resend_outreach_reply_to: str = ""
    outreach_min_score: int = 65
    outreach_batch_size: int = 50
    outreach_delay_seconds: int = 30
    outreach_daily_limit: int = 5
    outreach_start_date: str = ""

    # ── Distribution: IndexNow ──────────────────────────────────────
    indexnow_key: str = ""

    # ── Distribution: Google Indexing API ────────────────────────────
    google_indexing_sa_json: str = ""
    google_indexing_sa_file: str = ""
    google_indexing_lookback_days: int = 7
    google_indexing_max_per_run: int = 50

    # ── Distribution: Internet Archive ──────────────────────────────
    internet_archive_access_key: str = ""
    internet_archive_secret_key: str = ""
    internet_archive_collection: str = "opensource"
    internet_archive_max_per_run: int = 5

    # ── Distribution: Zenodo ────────────────────────────────────────
    zenodo_access_token: str = ""
    zenodo_use_sandbox: bool = False
    zenodo_community: str = ""
    zenodo_max_per_run: int = 3

    # ── Distribution: OSF ───────────────────────────────────────────
    osf_access_token: str = ""
    osf_project_node_id: str = ""
    osf_preprint_provider: str = "osf"
    osf_subject_id: str = ""
    osf_license_name: str = "CC-By Attribution 4.0 International"
    osf_max_per_run: int = 3

    # ── Distribution: Bluesky ───────────────────────────────────────
    bluesky_handle: str = ""
    bluesky_app_password: str = ""
    bluesky_lookback_days: int = 2
    bluesky_max_per_run: int = 5


settings = Settings()

# Ensure directories exist
settings.storage_dir.mkdir(parents=True, exist_ok=True)
settings.output_dir.mkdir(parents=True, exist_ok=True)
settings.google_reporting_output_dir.mkdir(parents=True, exist_ok=True)
