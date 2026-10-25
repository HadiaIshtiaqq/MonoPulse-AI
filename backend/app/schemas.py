from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class Platform(str, Enum):
    INSTAGRAM = "instagram"
    LINKEDIN = "linkedin"
    X = "x"
    FACEBOOK = "facebook"


class Tier(str, Enum):
    FREE = "FREE"
    PREMIUM = "PREMIUM"


class CampaignStatus(str, Enum):
    GENERATING = "GENERATING"
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"


class PostStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    PUBLISHED = "PUBLISHED"


class Product(BaseModel):
    name: str
    price: str = ""  # exactly as displayed on the site, currency included
    url: str = ""
    image_url: str = ""
    category: str = ""


class BrandKit(BaseModel):
    id: str = Field(default_factory=new_id)
    source_input: str
    source_type: str = "website"  # website | handle
    website_url: str | None = None
    name: str
    tagline: str = ""
    description: str = ""
    value_props: list[str] = []
    industry: str = ""
    location: str = ""
    keywords: list[str] = []
    primary_color: str = "#2563EB"
    secondary_color: str = "#0F172A"
    accent_color: str = "#F59E0B"
    palette: list[str] = []
    logo_url: str | None = None
    logo_path: str | None = None
    brand_voice_prompt: str = ""
    products: list[Product] = []
    images: list[str] = []  # photos from the brand's own site (URLs)


class TrendItem(BaseModel):
    title: str
    url: str = ""
    snippet: str = ""
    published_date: str | None = None
    query: str = ""


class ContentPillar(BaseModel):
    name: str
    description: str = ""


class CampaignStrategy(BaseModel):
    positioning: str = ""
    audience: str = ""
    voice_rules: list[str] = []
    pillars: list[ContentPillar] = []
    weekly_themes: list[str] = []


class Background(BaseModel):
    source: str  # stock | upload | website
    path: str  # local file used by the renderer
    thumb_url: str = ""
    credit: str = ""
    credit_url: str = ""
    license: str = ""


class Slide(BaseModel):
    headline: str = ""
    body: str = ""
    background: Background | None = None


class SocialPost(BaseModel):
    id: str = Field(default_factory=new_id)
    campaign_id: str
    group_id: str = ""  # versions of the same post for different platforms share this
    day: int
    platform: Platform
    pillar: str = ""
    headline: str = ""
    caption: str = ""
    cta: str = ""
    hashtags: list[str] = []
    alt_text: str = ""
    seo_keywords: list[str] = []
    trend_title: str | None = None
    trend_url: str | None = None
    product: Product | None = None
    layout: str = "bold"  # bold | split | quote | photo
    format: str = "single"  # single | carousel
    slides: list[Slide] = []  # carousel pages after the cover
    background: Background | None = None
    text_position: str = "auto"  # auto | top | center | bottom
    text_scale: float = 1.0
    image_url: str | None = None
    image_urls: list[str] = []  # every rendered page (1 for single posts)
    publish_at: datetime
    status: PostStatus = PostStatus.DRAFT
    published_via: str | None = None  # direct | webhook | manual
    publish_error: str | None = None
    remote_id: str | None = None
    remote_url: str | None = None
    is_humanized: bool = False
    original_caption: str | None = None
    ai_tell_before: float | None = None
    ai_tell_after: float | None = None


class Campaign(BaseModel):
    id: str = Field(default_factory=new_id)
    source_input: str = ""  # the website or handle the campaign was created from
    brand: BrandKit | None = None
    target_month: str = ""
    start_date: date
    days: int
    platforms: list[Platform]
    status: CampaignStatus = CampaignStatus.GENERATING
    strategy: CampaignStrategy | None = None
    trends: list[TrendItem] = []
    posts: list[SocialPost] = []
    mode: str = "live"  # live | demo (no API keys -> deterministic fallbacks)
    timings: dict[str, float] = {}
    research_ids: list[str] = []
    created_at: datetime = Field(default_factory=now_utc)


class ResearchInsights(BaseModel):
    verified_trend: str = ""
    pricing_gap: str = ""
    feature_insights: str = ""
    audience_insight: str = ""
    content_angles: list[str] = []
    confidence: int = 0
    confidence_rationale: str = ""
    opportunity: int = 0


class ResearchSource(BaseModel):
    id: int
    title: str
    url: str
    kind: str = "web"
    published_at: str | None = None


class ResearchTask(BaseModel):
    id: str = Field(default_factory=new_id)
    topic: str
    region: str = ""
    campaign_id: str | None = None
    status: str = "pending"  # pending | running | retry | completed | failed
    attempts: int = 0
    report: str | None = None
    insights: ResearchInsights | None = None
    sources: list[ResearchSource] = []
    error: str | None = None
    created_at: datetime = Field(default_factory=now_utc)
    started_at: datetime | None = None
    completed_at: datetime | None = None


class MemoryEntry(BaseModel):
    id: str = Field(default_factory=new_id)
    kind: str = "research"
    ref_id: str = ""
    title: str
    content: str
    created_at: datetime = Field(default_factory=now_utc)


class CreateResearchTaskRequest(BaseModel):
    topic: str = Field(min_length=3, max_length=300)
    region: str = Field(default="", max_length=100)
    campaign_id: str | None = None


class JobStep(BaseModel):
    key: str
    label: str
    status: str = "pending"  # pending | running | done | skipped | error
    detail: str = ""
    seconds: float | None = None


class Job(BaseModel):
    id: str = Field(default_factory=new_id)
    campaign_id: str
    status: str = "running"  # running | done | error
    steps: list[JobStep] = []
    error: str | None = None
    created_at: datetime = Field(default_factory=now_utc)


class CreateCampaignRequest(BaseModel):
    input: str = Field(min_length=2, description="Website URL or @social handle")
    platforms: list[Platform] = [Platform.INSTAGRAM, Platform.LINKEDIN, Platform.X]
    days: int = Field(default=30, ge=1, le=31)
    start_date: date | None = None
    posts_per_day: int = Field(default=1, ge=1, le=3)
    research_ids: list[str] = Field(default=[], max_length=3)


class UpdatePostRequest(BaseModel):
    headline: str | None = None
    caption: str | None = None
    cta: str | None = None
    hashtags: list[str] | None = None
    publish_at: datetime | None = None
    status: PostStatus | None = None
    layout: str | None = None
    slides: list[Slide] | None = None
    text_position: str | None = None
    text_scale: float | None = Field(default=None, ge=0.6, le=1.5)
    clear_background: bool = False


class SetBackgroundRequest(BaseModel):
    source: str = Field(pattern="^(stock|upload|website)$")
    photo_id: str | None = None  # stock: id from /api/photos/search
    upload_id: str | None = None  # upload: id from /api/uploads
    image_url: str | None = None  # website: one of the brand kit's own product or site photos


class BrandUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=80)
    tagline: str | None = Field(default=None, max_length=140)
    primary_color: str | None = Field(default=None, pattern="^#[0-9A-Fa-f]{6}$")
    secondary_color: str | None = Field(default=None, pattern="^#[0-9A-Fa-f]{6}$")
    accent_color: str | None = Field(default=None, pattern="^#[0-9A-Fa-f]{6}$")
    brand_voice_prompt: str | None = Field(default=None, max_length=600)
    logo_upload_id: str | None = None
    remove_logo: bool = False


class AppSettings(BaseModel):
    auto_publish: bool = False
    webhook_secret: str = Field(default_factory=lambda: uuid.uuid4().hex)


class AutoPublishRequest(BaseModel):
    enabled: bool


class RewriteRequest(BaseModel):
    tone: str = Field(default="casual", max_length=40)


class HumanizeRequest(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    use_llm: bool = True
    mode: str = Field(default="standard", pattern="^(light|standard|deep)$")
    protect: list[str] = []


class LLMCallRecord(BaseModel):
    tier: str
    model: str
    purpose: str
    ok: bool
    latency_ms: int
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    error: str | None = None
    at: datetime = Field(default_factory=now_utc)
