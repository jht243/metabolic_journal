import enum
import uuid
from datetime import datetime, date
from threading import Lock

from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Text,
    Float,
    Date,
    DateTime,
    Enum,
    Boolean,
    JSON,
    LargeBinary,
    UniqueConstraint,
    ForeignKey,
)
from sqlalchemy import inspect as sa_inspect, text as sa_text
from sqlalchemy.orm import declarative_base, sessionmaker

from src.config import settings

Base = declarative_base()


def _snake_case(name: str) -> str:
    out = []
    for i, ch in enumerate(name):
        if ch.isupper() and i > 0 and not name[i - 1].isupper():
            out.append("_")
        out.append(ch.lower())
    return "".join(out)


def _enum_values(enum_cls):
    return Enum(
        enum_cls,
        values_callable=lambda x: [e.value for e in x],
        name=_snake_case(enum_cls.__name__),
    )


# ── Enums ─────────────────────────────────────────────────────────────


class ContentSource(str, enum.Enum):
    PUBMED = "pubmed"
    CLINICAL_GUIDELINES = "clinical_guidelines"
    FDA = "fda"
    NIH = "nih"
    GOOGLE_NEWS = "google_news"
    MANUAL = "manual"
    LLM_GENERATED = "llm_generated"


class CredibilityTier(str, enum.Enum):
    PEER_REVIEWED = "peer_reviewed"
    CLINICAL_GUIDELINE = "clinical_guideline"
    INSTITUTIONAL = "institutional"
    EDITORIAL = "editorial"


class ContentStatus(str, enum.Enum):
    SCRAPED = "scraped"
    ANALYZED = "analyzed"
    APPROVED = "approved"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class AssessmentStatus(str, enum.Enum):
    STARTED = "started"
    COMPLETED = "completed"
    REVIEWED = "reviewed"
    PROTOCOL_SENT = "protocol_sent"


class BookingStatus(str, enum.Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    NO_SHOW = "no_show"


class HealthCluster(str, enum.Enum):
    METABOLISM = "metabolism"
    HORMONES = "hormones"
    RECOVERY = "recovery"
    TESTING = "testing"


class ProspectCategory(str, enum.Enum):
    HEALTH_BLOG = "health_blog"
    MEDICAL_PRACTICE = "medical_practice"
    WELLNESS_BRAND = "wellness_brand"
    FITNESS_NUTRITION = "fitness_nutrition"
    RESEARCH = "research"
    REJECT = "reject"


class EmailStatus(str, enum.Enum):
    NOT_FOUND = "not_found"
    FOUND = "found"
    VERIFIED = "verified"
    BOUNCED = "bounced"


class OutreachStatus(str, enum.Enum):
    PENDING = "pending"
    QUEUED = "queued"
    SENT = "sent"
    REPLIED = "replied"
    CONVERTED = "converted"
    DECLINED = "declined"


class ReplyStatus(str, enum.Enum):
    PENDING = "pending"
    OPENED = "opened"
    REPLIED = "replied"
    BOUNCED = "bounced"


class BacklinkStatus(str, enum.Enum):
    ACTIVE = "active"
    REMOVED = "removed"
    NOT_FOUND = "not_found"


# ── Content Models ────────────────────────────────────────────────────


class Article(Base):
    """Health articles from external sources (PubMed, FDA, NIH, Google News, etc.)."""

    __tablename__ = "articles"
    __table_args__ = (UniqueConstraint("source", "source_url", name="uq_article_source_url"),)

    id = Column(Integer, primary_key=True, autoincrement=True)

    source = Column(_enum_values(ContentSource), nullable=False, index=True)
    source_url = Column(String(1000), nullable=False)
    source_name = Column(String(200), nullable=True)
    credibility = Column(_enum_values(CredibilityTier), default=CredibilityTier.EDITORIAL)

    headline = Column(Text, nullable=False)
    published_date = Column(Date, nullable=False, index=True)
    body_text = Column(Text, nullable=True)
    article_type = Column(String(100), nullable=True)

    cluster = Column(_enum_values(HealthCluster), nullable=True, index=True)
    extra_metadata = Column(JSON, nullable=True)

    analysis_json = Column(JSON, nullable=True)
    status = Column(_enum_values(ContentStatus), default=ContentStatus.SCRAPED)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class BlogPost(Base):
    """LLM-generated long-form health content tied to a source article or
    generated as standalone SEO content."""

    __tablename__ = "blog_posts"
    __table_args__ = (
        UniqueConstraint("source_table", "source_id", name="uq_blog_source"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)

    source_table = Column(String(50), nullable=False, index=True)
    source_id = Column(Integer, nullable=False, index=True)

    slug = Column(String(200), nullable=False, unique=True, index=True)
    title = Column(Text, nullable=False)
    subtitle = Column(Text, nullable=True)
    summary = Column(Text, nullable=True)
    body_html = Column(Text, nullable=False)

    social_hook = Column(Text, nullable=True)
    og_image_bytes = Column(LargeBinary, nullable=True)

    primary_cluster = Column(String(80), nullable=True, index=True)
    clusters_json = Column(JSON, nullable=True)
    keywords_json = Column(JSON, nullable=True)
    related_slugs_json = Column(JSON, nullable=True)
    takeaways_json = Column(JSON, nullable=True)

    word_count = Column(Integer, nullable=True)
    reading_minutes = Column(Integer, nullable=True)

    published_date = Column(Date, nullable=False, index=True)
    canonical_source_url = Column(String(1000), nullable=True)

    # Medical review tracking for E-E-A-T
    reviewed_by = Column(String(200), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    medical_disclaimer = Column(Boolean, default=True)

    llm_model = Column(String(100), nullable=True)
    llm_input_tokens = Column(Integer, nullable=True)
    llm_output_tokens = Column(Integer, nullable=True)
    llm_cost_usd = Column(Float, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class LandingPage(Base):
    """Evergreen SEO landing pages — hub pages, symptom explainers,
    protocol guides, lab guides, tool pages. Generated with the premium
    LLM model and stored as pre-rendered HTML."""

    __tablename__ = "landing_pages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    page_key = Column(String(120), nullable=False, unique=True, index=True)
    page_type = Column(String(40), nullable=False, index=True)

    title = Column(Text, nullable=False)
    subtitle = Column(Text, nullable=True)
    summary = Column(Text, nullable=True)
    body_html = Column(Text, nullable=False)
    keywords_json = Column(JSON, nullable=True)
    sections_json = Column(JSON, nullable=True)
    faq_json = Column(JSON, nullable=True)

    cluster = Column(String(80), nullable=True, index=True)
    canonical_path = Column(String(200), nullable=False)
    word_count = Column(Integer, nullable=True)

    reviewed_by = Column(String(200), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)

    llm_model = Column(String(120), nullable=True)
    llm_input_tokens = Column(Integer, nullable=True)
    llm_output_tokens = Column(Integer, nullable=True)
    llm_cost_usd = Column(Float, nullable=True)

    last_generated_at = Column(DateTime, default=datetime.utcnow, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ── Assessment & Protocol Models ──────────────────────────────────────


class Assessment(Base):
    """Multi-step health assessment intake. Captures symptoms, goals,
    demographics, and health history. Links to optional lab results
    and protocol delivery."""

    __tablename__ = "assessments"

    id = Column(Integer, primary_key=True, autoincrement=True)

    token = Column(String(64), nullable=False, unique=True, index=True)
    email = Column(String(255), nullable=False, index=True)
    name = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=True)

    # Structured assessment data saved incrementally
    demographics_json = Column(JSON, nullable=True)
    symptoms_json = Column(JSON, nullable=True)
    goals_json = Column(JSON, nullable=True)
    health_history_json = Column(JSON, nullable=True)
    lifestyle_json = Column(JSON, nullable=True)
    medications_json = Column(JSON, nullable=True)

    # Computed scores from the assessment
    metabolic_score = Column(Float, nullable=True)
    hormone_score = Column(Float, nullable=True)
    recovery_score = Column(Float, nullable=True)
    overall_score = Column(Float, nullable=True)

    primary_cluster = Column(_enum_values(HealthCluster), nullable=True, index=True)
    recommended_program = Column(String(120), nullable=True)

    status = Column(_enum_values(AssessmentStatus), default=AssessmentStatus.STARTED, index=True)
    completed_at = Column(DateTime, nullable=True)

    # UTM / attribution
    utm_source = Column(String(200), nullable=True)
    utm_medium = Column(String(200), nullable=True)
    utm_campaign = Column(String(200), nullable=True)
    landing_page = Column(String(500), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class LabResult(Base):
    """Lab panel results linked to an assessment. Stores individual
    biomarker values with reference ranges and interpretation."""

    __tablename__ = "lab_results"

    id = Column(Integer, primary_key=True, autoincrement=True)

    assessment_id = Column(
        Integer,
        ForeignKey("assessments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    panel_type = Column(String(80), nullable=False, index=True)
    lab_date = Column(Date, nullable=True)
    lab_provider = Column(String(200), nullable=True)

    results_json = Column(JSON, nullable=False)
    interpretation_json = Column(JSON, nullable=True)
    flags_json = Column(JSON, nullable=True)

    reviewed_by = Column(String(200), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Protocol(Base):
    """Personalized health protocol generated from assessment + labs.
    Contains supplement recommendations, lifestyle changes, and
    optional Rx referrals."""

    __tablename__ = "protocols"

    id = Column(Integer, primary_key=True, autoincrement=True)

    assessment_id = Column(
        Integer,
        ForeignKey("assessments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    program_type = Column(String(80), nullable=False, index=True)
    version = Column(Integer, nullable=False, default=1)

    supplements_json = Column(JSON, nullable=True)
    lifestyle_json = Column(JSON, nullable=True)
    nutrition_json = Column(JSON, nullable=True)
    exercise_json = Column(JSON, nullable=True)
    rx_referrals_json = Column(JSON, nullable=True)
    monitoring_json = Column(JSON, nullable=True)

    summary_html = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)

    created_by = Column(String(200), nullable=True)
    approved_by = Column(String(200), nullable=True)
    approved_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ConsultationBooking(Base):
    """Tracks consultation bookings from assessment completions or
    direct booking CTAs."""

    __tablename__ = "consultation_bookings"

    id = Column(Integer, primary_key=True, autoincrement=True)

    assessment_id = Column(Integer, ForeignKey("assessments.id"), nullable=True, index=True)
    email = Column(String(255), nullable=False, index=True)
    name = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=True)

    booking_type = Column(String(80), nullable=False, index=True)
    preferred_date = Column(DateTime, nullable=True)
    scheduled_date = Column(DateTime, nullable=True)
    notes = Column(Text, nullable=True)

    status = Column(_enum_values(BookingStatus), default=BookingStatus.PENDING, index=True)

    # Stripe payment (if applicable)
    stripe_session_id = Column(String(255), nullable=True, unique=True)
    amount_total = Column(Integer, nullable=True)
    currency = Column(String(10), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ── Distribution & Operations ─────────────────────────────────────────


class DistributionLog(Base):
    """Tracks outbound distribution events (Google Indexing, IndexNow,
    Bluesky, etc.). One row per (url, channel) attempt."""

    __tablename__ = "distribution_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)

    channel = Column(String(40), nullable=False, index=True)
    url = Column(String(1000), nullable=False, index=True)

    entity_type = Column(String(40), nullable=True)
    entity_id = Column(Integer, nullable=True)

    success = Column(Boolean, nullable=False, default=False, index=True)
    response_code = Column(Integer, nullable=True)
    response_snippet = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class Subscriber(Base):
    """Newsletter subscribers collected from the site."""

    __tablename__ = "subscribers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), nullable=False, unique=True, index=True)
    name = Column(String(255), nullable=True)
    source = Column(String(80), nullable=True, index=True)
    interests_json = Column(JSON, nullable=True)
    confirmed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class ScrapeLog(Base):
    """Tracks every content scrape attempt for diagnostics."""

    __tablename__ = "scrape_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source = Column(_enum_values(ContentSource), nullable=False)
    scrape_date = Column(Date, nullable=False)
    success = Column(Boolean, nullable=False)
    entries_found = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


# ── Outreach Models (kept from original) ──────────────────────────────


class Prospect(Base):
    """A domain/page for backlink outreach."""

    __tablename__ = "outreach_prospects"
    __table_args__ = (
        UniqueConstraint("domain", "source_url", name="uq_outreach_domain_source"),
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    domain = Column(String(255), nullable=False, index=True)
    source_url = Column(String(1000), nullable=False, index=True)
    competitor_linked_to = Column(String(255), nullable=True, index=True)
    competitor_target_url = Column(String(1000), nullable=True)
    anchor_text = Column(Text, nullable=True)
    source_page_title = Column(Text, nullable=True)
    category = Column(
        _enum_values(ProspectCategory),
        default=ProspectCategory.HEALTH_BLOG,
        index=True,
    )
    site_type = Column(String(80), nullable=True, index=True)
    link_opportunity = Column(String(80), nullable=True, index=True)
    email_angle = Column(String(120), nullable=True)
    email_template_key = Column(String(80), nullable=True, index=True)
    reject_reason = Column(Text, nullable=True)
    source_page_topic = Column(String(255), nullable=True)
    is_resource_page = Column(Boolean, nullable=True)
    site_language = Column(String(10), nullable=True, index=True)
    authority_score = Column(Integer, nullable=True)
    competitor_count = Column(Integer, nullable=False, default=1)
    score = Column(Integer, nullable=False, default=0, index=True)
    recommended_target_url = Column(String(1000), nullable=True)
    reason_to_link = Column(Text, nullable=True)
    contact_email = Column(String(255), nullable=True, index=True)
    email_status = Column(_enum_values(EmailStatus), default=EmailStatus.NOT_FOUND, index=True)
    outreach_status = Column(_enum_values(OutreachStatus), default=OutreachStatus.PENDING, index=True)
    page_text_snippet = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class OutreachEmail(Base):
    """Generated outreach sequence for a prospect."""

    __tablename__ = "outreach_emails"
    __table_args__ = (
        UniqueConstraint("prospect_id", "sequence_num", name="uq_outreach_email_sequence"),
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    prospect_id = Column(
        String(36),
        ForeignKey("outreach_prospects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sequence_num = Column(Integer, nullable=False, default=1, index=True)
    subject = Column(Text, nullable=False)
    body = Column(Text, nullable=False)
    sent_at = Column(DateTime, nullable=True, index=True)
    resend_message_id = Column(String(255), nullable=True)
    reply_status = Column(_enum_values(ReplyStatus), default=ReplyStatus.PENDING, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class BacklinkRecord(Base):
    """Weekly backlink checks for outreach prospects."""

    __tablename__ = "outreach_backlinks"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    prospect_id = Column(
        String(36),
        ForeignKey("outreach_prospects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_url = Column(String(1000), nullable=False, index=True)
    target_url = Column(String(1000), nullable=True)
    anchor_text = Column(Text, nullable=True)
    rel = Column(String(255), nullable=True)
    first_seen = Column(DateTime, nullable=True)
    status = Column(_enum_values(BacklinkStatus), default=BacklinkStatus.NOT_FOUND, index=True)
    last_checked_at = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ── Engine & Session ──────────────────────────────────────────────────

engine = create_engine(settings.database_url, echo=False)
SessionLocal = sessionmaker(bind=engine)
_init_lock = Lock()
_db_initialized = False


def init_db(*, force: bool = False):
    """Create tables once per process. Silently skips if DB is unreachable."""
    global _db_initialized
    if _db_initialized and not force:
        return
    with _init_lock:
        if _db_initialized and not force:
            return
        try:
            Base.metadata.create_all(engine)
            _ensure_columns()
            _db_initialized = True
        except Exception:
            pass


def _ensure_columns() -> None:
    """Add columns introduced after initial table creation."""
    insp = sa_inspect(engine)
    dialect = engine.dialect.name

    blob_type = "BYTEA" if dialect == "postgresql" else "BLOB"
    json_type = "JSONB" if dialect == "postgresql" else "TEXT"

    additions = [
        ("blog_posts", "social_hook", "TEXT"),
        ("blog_posts", "og_image_bytes", blob_type),
        ("blog_posts", "takeaways_json", json_type),
        ("blog_posts", "reviewed_by", "VARCHAR(200)"),
        ("blog_posts", "reviewed_at", "TIMESTAMP"),
        ("blog_posts", "medical_disclaimer", "BOOLEAN"),
        ("landing_pages", "faq_json", json_type),
        ("landing_pages", "reviewed_by", "VARCHAR(200)"),
        ("landing_pages", "reviewed_at", "TIMESTAMP"),
    ]

    for table_name, column_name, column_type in additions:
        if table_name not in insp.get_table_names():
            continue
        existing = {c["name"] for c in insp.get_columns(table_name)}
        if column_name in existing:
            continue
        with engine.begin() as conn:
            conn.execute(
                sa_text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")
            )
