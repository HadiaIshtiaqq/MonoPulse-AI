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
    was_price: str = ""  # the regular price when the product is on sale
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
    country: str = ""  # ISO code, e.g. "PK"; drives the seasonal calendar and trend searches
    segments: list[str] = []  # who the products are for, e.g. ["men", "women", "kids"]
    offerings: list[str] = []  # what it offers when the site lists no products, e.g. ["Special order cakes"]
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


class ReelScene(BaseModel):
    """One scene of a post's reel, as the owner can edit it."""
    kind: str = "product"  # hook | product | fact | cta
    text: str = ""
    sub: str = ""  # price under a product, the website on the end card
    photo: str = ""  # /media/... file the scene shows ("" = brand colour)
    tag: str = ""  # its place in the story: "Tip 2", "#1", "A"


class ReelOptions(BaseModel):
    """How a reel looks beyond its style: colours, pace and lettering."""
    palette: str = ""  # brand | midnight | pastel | complement | mono | sunset | ocean | forest | berry | custom; "" = rotate
    color: str = ""  # the main colour for the custom palette, #RRGGBB
    pace: str = "normal"  # relaxed | normal | snappy
    case: str = "auto"  # auto (the style decides) | normal | upper
    language: str = "en"  # en | roman (Roman Urdu) | ur (Urdu) | mix (English + Roman Urdu)


class ReelRequest(BaseModel):
    scenes: list[ReelScene] | None = None  # omitted: write a new script from scratch
    options: ReelOptions | None = None  # omitted: keep the reel's options (a fresh script rotates the palette)
    topic: str | None = None  # products | countdown | tips | poll | story | occasion; omitted: fits the post
    occasion: str | None = None  # eid_fitr | mothers | independence | sale | ... for an occasion reel
    trend: str | None = None  # pov | sign | rate | wait | local, for a trending-format reel
    style: str | None = None  # cinematic | punch | showcase | magazine | scrapbook; omitted: pick one


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
    compare: Product | None = None  # the second product in a "this or that" post
    kind: str = "spotlight"  # spotlight | carousel | duo | tip | quote | sale | moment | question
    layout: str = "bold"  # bold | split | quote | photo
    format: str = "single"  # single | carousel
    slides: list[Slide] = []  # carousel pages after the cover
    background: Background | None = None
    gallery: list[Background] = []  # extra photos (the second product of a duo)
    text_position: str = "auto"  # auto | top | center | bottom
    text_scale: float = 1.0
    image_url: str | None = None
    image_urls: list[str] = []  # every rendered page (1 for single posts)
    video_url: str | None = None  # a 9:16 reel made from the post (Instagram Reels, Shorts, TikTok)
    video_poster: str | None = None
    reel_scenes: list[ReelScene] = []  # the reel's script and photos, so it can be edited and re-rendered
    reel_style: str = ""  # the reel's visual style, so a campaign's reels rotate through different looks
    reel_options: ReelOptions = ReelOptions()  # the palette (as used), pace and lettering
    reel_topic: str = ""  # what the reel is about: products | countdown | tips | poll | story | occasion
    reel_occasion: str = ""  # the occasion an occasion reel celebrates
    occasion: str = ""  # a greeting post's occasion ("Eid al-Fitr")
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
    design_version: int = 0  # the post-design version its images were drawn with (config.DESIGN_VERSION)
    strategy: CampaignStrategy | None = None
    trends: list[TrendItem] = []
    posts: list[SocialPost] = []
    mode: str = "live"  # live | demo (no API keys -> deterministic fallbacks)
    timings: dict[str, float] = {}
    research_ids: list[str] = []
    content_mix: dict = {}  # post types, layouts and repeated headlines (see variety.variety_report)
    competitor_task_id: str | None = None  # the competitor analysis started with this campaign
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


class CompetitorProfile(BaseModel):
    name: str
    url: str = ""
    tagline: str = ""
    price_range: str = ""
    median_price: float = 0
    currency: str = ""
    products_seen: int = 0
    on_sale: int = 0
    best_discount: int = 0
    lines: list[str] = []
    segments: list[str] = []
    claims: list[str] = []  # service promises on the site: delivery, returns, cash on delivery…
    socials: list[str] = []  # platforms the site links to
    sample_products: list[Product] = []
    found_via: str = ""  # how the agent found it
    reachable: bool = True
    note: str = ""


class Recommendation(BaseModel):
    title: str
    why: str = ""
    how: str = ""


class PlanWeek(BaseModel):
    week: int
    focus: str
    actions: list[str] = []


class CompetitorReport(BaseModel):
    brand: CompetitorProfile | None = None
    competitors: list[CompetitorProfile] = []
    summary: str = ""
    position: list[str] = []  # where the brand stands against them, in facts
    strengths: list[str] = []
    gaps: list[str] = []
    recommendations: list[Recommendation] = []
    plan: list[PlanWeek] = []
    content_ideas: list[str] = []
    method: str = "rules"  # rules | model (who wrote the advice)


class ResearchTask(BaseModel):
    id: str = Field(default_factory=new_id)
    topic: str
    kind: str = "question"  # question | competitors
    brand_url: str = ""  # competitors: the brand's website
    competitor_urls: list[str] = []  # competitors: ones the user named, analysed first
    region: str = ""
    campaign_id: str | None = None
    progress: list[str] = []  # what the agent has done so far, for a live view
    competitors: CompetitorReport | None = None
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


class CompetitorResearchRequest(BaseModel):
    url: str | None = Field(default=None, max_length=500)  # the brand's website, or…
    campaign_id: str | None = None  # …a campaign whose brand to analyse
    competitor_urls: list[str] = Field(default=[], max_length=8)  # competitors you already know (optional)


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
    browser_publish: bool = False  # scheduled posts may go out through MonoPlus's signed-in browser
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
