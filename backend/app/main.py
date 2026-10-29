from __future__ import annotations

import asyncio
import contextlib
import csv
import hmac
import hashlib
import io
import json
import logging
import random
import re
import shutil
import uuid
import zipfile
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, connections, mcp_server, media_gc, publishing, ratelimit
from .agents import (
    avatar, calendar, humanizer, lang, memory, occasions, photos, pipeline, reels, renderer, research, speech, strategist, ugc, ugc_video,
    variety,
)
from .agents.formatter import HASHTAG_COUNT, enforce_limits, normalize_hashtags
from .llm import LLMError, router
from .publishing import share_links
from .redact import install_log_redaction, redact
from .schemas import (
    AutoPublishRequest,
    BrandUpdateRequest,
    Campaign,
    CampaignStatus,
    CompetitorResearchRequest,
    CreateCampaignRequest,
    CreateResearchTaskRequest,
    HumanizeRequest,
    Platform,
    PostStatus,
    ReelRequest,
    ReelScene,
    ResearchTask,
    RewriteRequest,
    SetBackgroundRequest,
    SocialPost,
    UgcAd,
    UpdatePostRequest,
    new_id,
)
from .store import store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not config.ACCESS_KEY:
        logging.getLogger("monoplus").warning(
            "MONOPLUS_ACCESS_KEY is not set: anyone who can reach this server can use it. Fine on your own machine; "
            "set a key before putting it online.")
    for t in store.research.values():
        if t.status == "running":
            t.status = "retry"  # the server restarted mid-run
    from .social import browser

    browser.move_old_profile()
    workers = [asyncio.create_task(research.worker()), asyncio.create_task(publishing.scheduler())]
    workers.append(asyncio.create_task(asyncio.to_thread(media_gc.cleanup)))  # tidy up old renders once at start
    if store.settings.browser_publish:  # scheduled browser posts need to know where you're signed in
        if browser.available():
            workers.append(asyncio.create_task(browser.poster.status()))
    yield
    for w in workers:
        w.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await w


install_log_redaction()  # before anything logs: keys never reach a log line
connections.load()  # keys you saved in the app (Connections) join the ones from .env

app = FastAPI(title="MonoPlus", version="0.4.0", lifespan=lifespan)
app.include_router(mcp_server.router)  # /mcp authenticates itself (Bearer token), see mcp_server._authorized

OPEN_PATHS = {"/api/health", "/api/access", "/api/access/login", "/api/access/logout"}
ACCESS_COOKIE = "monoplus_access"
# Calls that act on your social accounts or this computer's browser: allowed from this computer, or with the access key.
ACCOUNT_PATHS = re.compile(r"^/api/(connections(/.*)?|browser(/.*)?|posts/[^/]+/(browser-post|publish|mark-published)|publishing(/.*)?|maintenance/.*)$")
LOCAL_CLIENTS = {"127.0.0.1", "::1", "localhost", "testclient"}


def _client_host(request: Request) -> str:
    if config.TRUST_PROXY and request.headers.get("x-forwarded-for"):
        return request.headers["x-forwarded-for"].split(",")[0].strip()
    return request.client.host if request.client else ""


def _session_token() -> str:
    """What the access cookie holds: derived from the key, so the key itself never sits in the browser."""
    return hmac.new(config.ACCESS_KEY.encode(), b"monoplus-session-v1", hashlib.sha256).hexdigest()


def _given_key(request: Request) -> str:
    # Header or cookie only: a key in the address (?key=) would be written to access logs and browser history.
    return request.headers.get("x-access-key") or ""


def _key_ok(given: str) -> bool:
    return bool(config.ACCESS_KEY) and bool(given) and hmac.compare_digest(given.encode(), config.ACCESS_KEY.encode())


def _authorised(request: Request) -> bool:
    cookie = request.cookies.get(ACCESS_COOKIE) or ""
    return _key_ok(_given_key(request)) or (bool(config.ACCESS_KEY) and bool(cookie)
                                            and hmac.compare_digest(cookie.encode(), _session_token().encode()))


@app.middleware("http")
async def require_access_key(request: Request, call_next):
    """With MONOPLUS_ACCESS_KEY set, every API call must carry it. /media stays public because
    Instagram and other platforms download post images from there."""
    path = request.url.path
    if config.ACCESS_KEY and path.startswith("/api/") and path not in OPEN_PATHS and request.method != "OPTIONS":
        if not _authorised(request):
            return JSONResponse({"detail": "Access key required."}, status_code=401)
    if ACCOUNT_PATHS.match(path) and request.method != "OPTIONS" and not _authorised(request) \
            and _client_host(request) not in LOCAL_CLIENTS:
        # Without a key, nobody else on the network can post to your accounts or drive your browser.
        return JSONResponse({"detail": "Posting to your accounts only works from the computer MonoPlus runs on, "
                                       "or with the access key (MONOPLUS_ACCESS_KEY)."}, status_code=403)
    if config.RATE_LIMITS:
        client = _client_host(request) or "anon"  # X-Forwarded-For only counts behind a trusted proxy
        hit = ratelimit.limiter.check(client, request.method, path)
        if hit:
            bucket, wait = hit
            return JSONResponse({"detail": f"{ratelimit.FRIENDLY[bucket]} Please try again in {wait} seconds."},
                                status_code=429, headers={"Retry-After": str(wait)})
    return await call_next(request)


app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"], allow_credentials=True,
                   expose_headers=["Mcp-Session-Id"])


@app.exception_handler(HTTPException)
async def redacted_http_error(request: Request, exc: HTTPException) -> JSONResponse:
    """Error messages often carry an upstream error's text: no key or token ever rides along to the page."""
    detail = redact(exc.detail) if isinstance(exc.detail, str) else exc.detail
    return JSONResponse({"detail": detail}, status_code=exc.status_code, headers=getattr(exc, "headers", None))


@app.exception_handler(Exception)
async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    """A crash is logged (redacted) for the owner; the page only hears that something went wrong."""
    logging.getLogger("monoplus").exception("unexpected error on %s %s", request.method, request.url.path)
    return JSONResponse({"detail": "Something went wrong on our side. Please try again."}, status_code=500)
app.mount("/media", StaticFiles(directory=config.MEDIA_DIR), name="media")

_tasks: set[asyncio.Task] = set()

for _c in store.campaigns.values():
    if _c.status is CampaignStatus.GENERATING:
        _c.status = CampaignStatus.FAILED  # the server restarted mid-run


def _spawn(coro) -> None:
    task = asyncio.create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse(config.PUBLIC_APP_URL)


@app.get("/api/access")
async def access(request: Request) -> dict:
    """Tells the UI whether a key is needed and whether the one it holds is right."""
    return {"required": bool(config.ACCESS_KEY), "ok": not config.ACCESS_KEY or _authorised(request)}


class AccessLogin(BaseModel):
    key: str


@app.post("/api/access/login")
def access_login(req: AccessLogin, request: Request) -> JSONResponse:
    """Check the key and keep it in an httpOnly cookie: page scripts (and anything injected into
    the page) can't read it, unlike a key kept in the browser's local storage."""
    if config.ACCESS_KEY and not _key_ok(req.key.strip()):
        return JSONResponse({"ok": False}, status_code=401)
    resp = JSONResponse({"ok": True})
    if config.ACCESS_KEY:
        resp.set_cookie(ACCESS_COOKIE, _session_token(), httponly=True, samesite="lax", max_age=60 * 60 * 24 * 30,
                        secure=request.url.scheme == "https")
    return resp


@app.post("/api/access/logout")
def access_logout() -> JSONResponse:
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(ACCESS_COOKIE)
    return resp


@app.get("/api/health")
async def health() -> dict:
    return {
        "ok": True,
        "mode": "live" if config.llm_enabled() else "demo",
        "ai_provider": router.provider if config.llm_enabled() else None,
        "nebius": bool(config.NEBIUS_API_KEY),
        "bedrock": config.AWS_BEDROCK_ENABLED,
        "tavily": config.tavily_enabled(),
        "free_search": config.FREE_SEARCH,
        "pexels": bool(config.PEXELS_API_KEY),
        "mcp_endpoint": f"{config.PUBLIC_API_URL}/mcp",
        "design_version": config.DESIGN_VERSION,
        "protected": bool(config.ACCESS_KEY),
    }


@app.get("/api/models")
async def list_models() -> dict:
    """Lists the models your Nebius Token Factory key can see (to verify MODEL_* ids)."""
    if not router.enabled:
        raise HTTPException(400, "NEBIUS_API_KEY not set")
    try:
        models = await router._get_client().models.list()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"Token Factory error: {exc}") from exc
    return {"models": sorted(m.id for m in models.data if "nemotron" in m.id.lower() or "nvidia" in m.id.lower())}


@app.get("/api/telemetry")
def telemetry() -> dict:
    return router.telemetry()


# --------------------------------------------------------------------------- campaigns


@app.post("/api/campaigns", status_code=202)
async def create_campaign(req: CreateCampaignRequest) -> dict:
    bad = [r for r in req.research_ids if r not in store.research or store.research[r].status != "completed"]
    if bad:
        raise HTTPException(422, "Only completed research can be attached to a campaign.")
    try:
        campaign, job = pipeline.start(req)
    except pipeline.Busy as exc:
        raise HTTPException(429, str(exc), headers={"Retry-After": "120"}) from exc
    return {"campaign_id": campaign.id, "job_id": job.id}


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str) -> dict:
    job = store.jobs.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    campaign = store.campaigns.get(job.campaign_id)
    out = job.model_dump(mode="json")
    if campaign and campaign.brand:
        out["brand"] = campaign.brand.model_dump(mode="json")
    if campaign:
        out["trends"] = [t.model_dump(mode="json") for t in campaign.trends]
        out["elapsed"] = campaign.timings
    return out


@app.get("/api/campaigns")
async def list_campaigns() -> list[dict]:
    items = sorted(store.campaigns.values(), key=lambda c: c.created_at, reverse=True)
    return [
        {
            "id": c.id,
            "name": c.brand.name if c.brand else "…",
            "website": c.brand.website_url if c.brand else None,
            "status": c.status,
            "posts": len(c.posts),
            "approved": sum(p.status is not PostStatus.DRAFT for p in c.posts),
            "published": sum(p.status is PostStatus.PUBLISHED for p in c.posts),
            "platforms": c.platforms,
            "start_date": c.start_date.isoformat(),
            "days": c.days,
            "primary_color": c.brand.primary_color if c.brand else None,
            "accent_color": c.brand.accent_color if c.brand else None,
            "thumbnails": [p.image_url for p in c.posts[:4] if p.image_url],
            "created_at": c.created_at.isoformat(),
        }
        for c in items
    ]


def _campaign(campaign_id: str) -> Campaign:
    c = store.campaigns.get(campaign_id)
    if not c:
        raise HTTPException(404, "campaign not found")
    return c


@app.get("/api/campaigns/{campaign_id}")
async def get_campaign(campaign_id: str) -> Campaign:
    return _campaign(campaign_id)


@app.post("/api/campaigns/{campaign_id}/approve-all")
def approve_all(campaign_id: str) -> dict:
    """Approve every draft. Returns the campaign and which posts changed, so it can be undone."""
    c = _campaign(campaign_id)
    changed = []
    for p in c.posts:
        if p.status is PostStatus.DRAFT:
            p.status = PostStatus.APPROVED
            changed.append(p.id)
    c.status = CampaignStatus.APPROVED
    store.save(c)
    return {**c.model_dump(mode="json"), "approved_ids": changed}


class UndoApprovalRequest(BaseModel):
    post_ids: list[str]


@app.post("/api/campaigns/{campaign_id}/undo-approve")
def undo_approve(campaign_id: str, req: UndoApprovalRequest) -> Campaign:
    """Put posts approved by mistake back to draft (posts already published are left alone)."""
    c = _campaign(campaign_id)
    ids = set(req.post_ids)
    for p in c.posts:
        if p.id in ids and p.status is PostStatus.APPROVED:
            p.status = PostStatus.DRAFT
    if any(p.status is PostStatus.DRAFT for p in c.posts):
        c.status = CampaignStatus.DRAFT
    store.save(c)
    return c


@app.post("/api/campaigns/{campaign_id}/redraw")
async def redraw_campaign(campaign_id: str) -> Campaign:
    """Draw every post again with the newest designs, keeping its words, photos and layout."""
    c = _campaign(campaign_id)
    if not c.brand or c.status is CampaignStatus.GENERATING:
        raise HTTPException(409, "This campaign isn't ready to redraw yet.")
    await renderer.render_posts(c.brand, c.posts)
    c.design_version = config.DESIGN_VERSION
    store.save(c)
    return c


@app.post("/api/maintenance/cleanup")
async def cleanup_media() -> dict:
    """Delete media files nothing uses any more (older than two days)."""
    return await asyncio.to_thread(media_gc.cleanup)


@app.delete("/api/campaigns/{campaign_id}", status_code=204)
def delete_campaign(campaign_id: str) -> None:
    c = _campaign(campaign_id)
    for f in config.MEDIA_DIR.glob(f"{c.id}_*"):  # rendered PNGs and their JPEG publishing copies
        f.unlink(missing_ok=True)
    del store.campaigns[campaign_id]
    store.save()


@app.patch("/api/campaigns/{campaign_id}/brand")
async def update_brand(campaign_id: str, req: BrandUpdateRequest) -> Campaign:
    """Edit the brand kit (name, colours, logo, voice) and re-render every post with it."""
    c = _campaign(campaign_id)
    if not c.brand:
        raise HTTPException(409, "campaign has no brand kit yet")
    kit = c.brand
    for field in ("name", "tagline", "primary_color", "secondary_color", "accent_color", "brand_voice_prompt"):
        value = getattr(req, field)
        if value is not None:
            setattr(kit, field, value.upper() if field.endswith("_color") else value.strip())
    if req.remove_logo:
        kit.logo_path = None
    elif req.logo_upload_id:
        try:
            src = photos.upload_path(req.logo_upload_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        dest = config.MEDIA_DIR / f"logo_{kit.id}{src.suffix}"
        shutil.copyfile(src, dest)
        kit.logo_path, kit.logo_url = str(dest), f"/media/{dest.name}"
    await renderer.render_posts(kit, c.posts)
    store.save(c)
    return c


@app.get("/api/campaigns/{campaign_id}/export")
def export_campaign(campaign_id: str):
    """ZIP of every image and reel plus a CSV with captions, hashtags and schedule, ready for any scheduler."""
    c = _campaign(campaign_id)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        rows = io.StringIO()
        w = csv.writer(rows)
        w.writerow(["date", "time_utc", "platform", "format", "status", "headline", "caption", "hashtags", "images", "alt_text"])
        for p in sorted(c.posts, key=lambda x: x.publish_at):
            names = []
            for i, url in enumerate(p.image_urls or ([p.image_url] if p.image_url else [])):
                src = config.MEDIA_DIR / url.split("?")[0].removeprefix("/media/")
                if src.exists():
                    name = f"{p.publish_at:%Y-%m-%d}_{p.platform.value}_{p.id[:6]}{'' if i == 0 else f'_{i + 1}'}.png"
                    z.write(src, f"images/{name}")
                    names.append(name)
            w.writerow([f"{p.publish_at:%Y-%m-%d}", f"{p.publish_at:%H:%M}", p.platform.value, p.format, p.status.value,
                        p.headline, p.caption, " ".join(p.hashtags), ";".join(names), p.alt_text])
        for url in sorted({p.video_url.split("?")[0] for p in c.posts if p.video_url}):
            src = config.MEDIA_DIR / url.removeprefix("/media/")
            post = next(p for p in c.posts if p.video_url and p.video_url.startswith(url))
            if src.exists():
                z.write(src, f"reels/{post.publish_at:%Y-%m-%d}_{(post.group_id or post.id)[:6]}.mp4")
        z.writestr("posts.csv", rows.getvalue())
        credits = sorted({p.background.credit for p in c.posts if p.background and p.background.source == "stock"})
        if credits:
            z.writestr("photo-credits.txt", "\n".join(credits) + "\n")
    buf.seek(0)
    slug = "".join(ch if ch.isalnum() else "-" for ch in (c.brand.name if c.brand else "campaign")).strip("-").lower() or "campaign"
    return StreamingResponse(buf, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{slug}-monoplus.zip"'})


@app.get("/api/upcoming")
async def upcoming(days: int = Query(7, ge=1, le=60)) -> list[dict]:
    """Posts scheduled in the next N days across all campaigns, soonest first."""
    now = datetime.now(timezone.utc)
    end = now + timedelta(days=days)
    out = []
    for c in store.campaigns.values():
        for p in c.posts:
            if p.status is not PostStatus.PUBLISHED and now - timedelta(hours=12) <= p.publish_at <= end:
                out.append({"campaign_id": c.id, "brand": c.brand.name if c.brand else "", "post": p.model_dump(mode="json")})
    return sorted(out, key=lambda x: x["post"]["publish_at"])[:50]


# --------------------------------------------------------------------------- posts


def _post(post_id: str) -> tuple[Campaign, SocialPost]:
    found = store.find_post(post_id)
    if not found:
        raise HTTPException(404, "post not found")
    return found


CAPTION_HISTORY = 8


def _set_caption(post: SocialPost, text: str) -> None:
    """Change the caption, keeping the one it replaces in the post's history."""
    if text != post.caption and post.caption.strip():
        post.caption_history = [post.caption, *[c for c in post.caption_history if c not in (post.caption, text)]][:CAPTION_HISTORY]
    post.caption = text


async def _rerender(campaign: Campaign, post: SocialPost) -> None:
    if campaign.brand:
        await asyncio.to_thread(renderer.render_post, campaign.brand, post)


@app.patch("/api/posts/{post_id}")
async def update_post(post_id: str, req: UpdatePostRequest) -> SocialPost:
    campaign, post = _post(post_id)
    rerender = False
    if req.headline is not None and req.headline != post.headline:
        post.headline, rerender = req.headline[:90], True
    if req.layout is not None and req.layout in renderer.LAYOUTS and req.layout != post.layout:
        if req.layout in renderer.PHOTO_LAYOUTS and not post.background:
            raise HTTPException(422, "Pick a background photo first.")
        if req.layout == "duo" and not post.gallery:
            raise HTTPException(422, "The duo layout needs a second product photo; it's set up for \"this or that\" posts.")
        post.layout, rerender = req.layout, True
    if req.text_position is not None and req.text_position in renderer.POSITIONS:
        post.text_position, rerender = req.text_position, True
    if req.text_scale is not None:
        post.text_scale, rerender = round(req.text_scale, 2), True
    if req.slides is not None and post.format == "carousel":
        post.slides = [s for s in req.slides if s.headline or s.body][:8]
        rerender = True
    if req.clear_background:
        post.background = None
        if post.layout == "photo":
            post.layout = "bold"
        rerender = True
    if req.caption is not None:
        _set_caption(post, req.caption)
        post.ai_tell_after = humanizer.ai_tell_score(req.caption)
    if req.cta is not None:
        post.cta, rerender = req.cta[:120], rerender or post.format == "carousel"
    if req.hashtags is not None:
        post.hashtags = normalize_hashtags(req.hashtags, 30)
    if req.publish_at is not None:
        post.publish_at = req.publish_at
        post.day = (req.publish_at.date() - campaign.start_date).days
    if req.status is not None:
        post.status = req.status
        if req.status is PostStatus.APPROVED:
            post.publish_error = None
    if rerender:
        await _rerender(campaign, post)
    store.save(campaign)
    return post


MAX_DESIGN_JSON = 600_000
MAX_DESIGN_PAGES = 10


class DesignSaveRequest(BaseModel):
    design: dict
    pages: list[str]  # data:image/png;base64,… one per page, as the editor exported them


@app.put("/api/posts/{post_id}/design")
async def save_design(post_id: str, req: DesignSaveRequest) -> SocialPost:
    """Keep a design made in the editor: its layers (to edit again later) and its exported pages,
    which become the post's images."""
    campaign, post = _post(post_id)
    if not 1 <= len(req.pages) <= MAX_DESIGN_PAGES:
        raise HTTPException(422, f"A design has 1 to {MAX_DESIGN_PAGES} pages.")
    if len(json.dumps(req.design)) > MAX_DESIGN_JSON:
        raise HTTPException(422, "That design is too large to save. Remove a few elements and try again.")
    try:
        urls = await asyncio.to_thread(photos.save_design_pages, post, req.pages)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    post.design = req.design
    post.image_url, post.image_urls = urls[0], urls
    store.save(campaign)
    return post


@app.delete("/api/posts/{post_id}/design")
async def reset_design(post_id: str) -> SocialPost:
    """Back to the automatic design (your editor layers are forgotten)."""
    campaign, post = _post(post_id)
    post.design = None
    await _rerender(campaign, post)
    store.save(campaign)
    return post


class DesignPhotoRequest(BaseModel):
    url: str = ""
    stock_id: str = ""


@app.post("/api/posts/{post_id}/design/photo")
async def design_photo(post_id: str, req: DesignPhotoRequest) -> dict:
    """One of the brand's own web photos, saved here so the editor can draw it (and export it:
    a canvas can't export pictures loaded straight from another site)."""
    campaign, _ = _post(post_id)
    kit = campaign.brand
    if req.stock_id:  # a free stock photo from the editor's search
        try:
            return {"url": (await photos.to_background(req.stock_id)).thumb_url}
        except KeyError as exc:
            raise HTTPException(404, "That photo isn't available any more. Search again.") from exc
    allowed = set(kit.images if kit else []) | {p.image_url for p in (kit.products if kit else []) if p.image_url}
    if req.url.startswith("/media/"):
        return {"url": req.url}
    if req.url not in allowed:
        raise HTTPException(422, "Pick one of the brand's photos.")
    try:
        bg = await photos.website_background(req.url, credit=f"Photo from {kit.name}")
    except Exception as exc:  # noqa: BLE001 - download or decode failure
        raise HTTPException(502, f"Couldn't get that photo: {exc}") from exc
    return {"url": bg.thumb_url}


@app.post("/api/posts/{post_id}/background")
async def set_background(post_id: str, req: SetBackgroundRequest) -> SocialPost:
    campaign, post = _post(post_id)
    try:
        if req.source == "stock":
            if not req.photo_id:
                raise HTTPException(422, "photo_id is required")
            post.background = await photos.to_background(req.photo_id)
        elif req.source == "website":
            kit = campaign.brand
            product = next((p for p in (kit.products if kit else []) if p.image_url and p.image_url == req.image_url), None)
            if not kit or not req.image_url or (not product and req.image_url not in kit.images):
                raise HTTPException(422, "Pick one of the photos found on your website.")
            post.background = await photos.website_background(req.image_url, credit=f"Photo from {kit.name}",
                                                              credit_url=product.url if product else "")
        else:
            if not req.upload_id:
                raise HTTPException(422, "upload_id is required")
            post.background = photos.background_from_upload(req.upload_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - download/decoding failures
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(502, f"Couldn't use that photo: {exc}") from exc
    post.layout = "photo"
    await _rerender(campaign, post)
    store.save(campaign)
    return post


class PostHumanizeRequest(BaseModel):
    mode: str = "standard"


@app.post("/api/posts/{post_id}/humanize")
async def humanize_post(post_id: str, req: PostHumanizeRequest | None = None):
    campaign, post = _post(post_id)
    mode = (req.mode if req else "standard") if (req and req.mode in ("light", "standard", "deep")) else "standard"
    kit = campaign.brand
    res = await humanizer.humanize(post.caption, voice=kit.brand_voice_prompt if kit else "", threshold=0, mode=mode,
                                   protect=[kit.name] if kit else None)
    post.original_caption = post.original_caption or post.caption
    _set_caption(post, res.text)
    post.ai_tell_after, post.is_humanized = res.after, True
    store.save(campaign)
    return {"post": post, "used_llm": res.used_llm, "before": res.before, "after": res.after,
            "patterns_before": res.patterns_before, "patterns_after": res.patterns_after,
            "steps": [asdict(s) for s in res.steps]}


REWRITE_SYSTEM = """Rewrite this social post caption in the requested tone for the same brand and platform.
Keep the facts and the call to action. Plain, specific language; no AI clichés; no hashtags.
Return JSON: {"headline": "<= 7 words", "caption": "..."}"""


@app.post("/api/posts/{post_id}/rewrite")
async def rewrite_post(post_id: str, req: RewriteRequest) -> SocialPost:
    campaign, post = _post(post_id)
    kit = campaign.brand
    if not router.enabled:
        raise HTTPException(503, "Tone rewrites need NEBIUS_API_KEY (Nemotron). You can still edit the caption by hand.")
    if not kit:
        raise HTTPException(409, "campaign has no brand kit yet")
    try:
        user = (f"Brand: {strategist.brand_brief(kit)}\nPlatform: {post.platform.value}\n"
                f"Tone: {req.tone}\nHeadline: {post.headline}\nCaption:\n{post.caption}")
        data = await router.complete_json("rewrite", REWRITE_SYSTEM, user, temperature=0.9, max_tokens=900)
        caption = str(data.get("caption") or post.caption)
        headline = str(data.get("headline") or post.headline)[:90]
    except (LLMError, AttributeError) as exc:
        raise HTTPException(502, f"rewrite failed: {exc}") from exc
    res = await humanizer.humanize(caption, voice=kit.brand_voice_prompt, use_llm=False, protect=[kit.name])
    _set_caption(post, res.text)
    post.ai_tell_after = res.after
    post.hashtags = normalize_hashtags(post.hashtags, HASHTAG_COUNT[post.platform])
    enforce_limits(post)
    if headline != post.headline:
        post.headline = headline
        await _rerender(campaign, post)
    store.save(campaign)
    return post


# Reels rendering in the background: {job id: {"status", "result" | "error", "code", "at"}}. Kept in
# memory for an hour, which is plenty for the page that asked to collect its reel.
REEL_JOBS: dict[str, dict] = {}
_reel_tasks: set[asyncio.Task] = set()


@app.post("/api/posts/{post_id}/reel")
async def make_reel(post_id: str, req: ReelRequest | None = None, background: bool = False):
    """A 9:16 motion video of the post for Instagram Reels, YouTube Shorts, TikTok and Facebook Reels,
    shared by every platform version of the post. Send `scenes` to render the owner's edits;
    leave them out to write a fresh script. With ?background=true it answers at once with a job
    id to poll at /api/reel-jobs/{id}, so a long render never holds a request open."""
    campaign, post = _post(post_id)
    if not background:
        return await _render_reel(campaign, post, req)
    if sum(j["status"] == "running" for j in REEL_JOBS.values()) >= config.REEL_RENDERS + reels.MAX_WAITING:
        raise HTTPException(429, "Lots of reels are being made right now. Please try again in a minute.", headers={"Retry-After": "60"})
    if any(j["status"] == "running" and j.get("post_id") == post.id for j in REEL_JOBS.values()):
        raise HTTPException(409, "This post's reel is already being made. It'll be ready in a moment.")
    now = datetime.now(timezone.utc)
    for k in [k for k, j in REEL_JOBS.items() if now - j["at"] > timedelta(hours=1)]:
        REEL_JOBS.pop(k, None)
    job_id = new_id()
    REEL_JOBS[job_id] = {"status": "running", "post_id": post.id, "at": now}

    async def run() -> None:
        try:
            result = await _render_reel(campaign, post, req)
            REEL_JOBS[job_id].update(status="done", result=jsonable_encoder(result))
        except HTTPException as exc:
            REEL_JOBS[job_id].update(status="error", error=exc.detail, code=exc.status_code)
        except Exception as exc:  # noqa: BLE001 - reported to the page that's waiting
            logging.getLogger(__name__).exception("reel job %s failed", job_id)
            REEL_JOBS[job_id].update(status="error", error=f"The reel couldn't be made ({type(exc).__name__}).", code=500)

    task = asyncio.create_task(run())
    _reel_tasks.add(task)
    task.add_done_callback(_reel_tasks.discard)
    return JSONResponse({"job_id": job_id, "status": "running"}, status_code=202)


@app.get("/api/reel-jobs/{job_id}")
async def reel_job(job_id: str) -> dict:
    job = REEL_JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "That reel job has finished and been cleared, or never existed. Make the reel again.")
    return {k: v for k, v in job.items() if k != "at"}


async def _render_reel(campaign: Campaign, post: SocialPost, req: ReelRequest | None) -> dict:
    try:
        info = await reels.make_reel(campaign, post, req.scenes if req else None, req.style if req else None,
                                     req.options if req else None, req.topic if req else None, req.occasion if req else None,
                                     req.trend if req else None)
    except reels.ReelEditError as exc:
        raise HTTPException(422, str(exc)) from exc
    except reels.ReelBusy as exc:
        raise HTTPException(429, str(exc), headers={"Retry-After": "60"}) from exc
    except reels.ReelInProgress as exc:
        raise HTTPException(409, str(exc)) from exc
    except reels.ReelError as exc:
        raise HTTPException(503, str(exc)) from exc
    store.save(campaign)
    return {"post": post, **info}


# --------------------------------------------------------------------------- UGC ads

UGC_JOBS: dict[str, dict] = {}
_ugc_tasks: set[asyncio.Task] = set()


def _products(c: Campaign) -> list:
    return [p for p in (c.brand.products if c.brand else []) if p.image_url][:40]


@app.get("/api/campaigns/{campaign_id}/ugc")
async def ugc_overview(campaign_id: str) -> dict:
    """What a UGC ad can be made from: the brand's products with photos, the formats, the ads made so far."""
    c = _campaign(campaign_id)
    if not c.brand:
        raise HTTPException(409, "This campaign has no brand kit yet.")
    return {"formats": ugc.formats_for(c.brand), "heygen": ugc.heygen_ready(), "voice": speech.tts_available(),
            "voices": speech.voice_list(), "languages": [{"key": k, "label": v} for k, v in ugc.SCRIPT_LANGUAGES.items()],
            "presenters": [{"key": ch.key, "name": ch.name, "gender": ch.gender, "preview": f"/api/ugc/presenters/{ch.key}.png"}
                           for ch in avatar.CHARACTERS],
            "listening": speech.whisper_available(),
            "looks": [{"key": k, "label": v} for k, v in ugc_video.LOOK_LABELS.items()],
            "captions": [{"key": k, "label": v} for k, v in ugc_video.CAPTION_LABELS.items()],
            "products": [{"index": i, "name": strategist.display_name(c.brand, p), "price": p.price, "image": p.image_url}
                         for i, p in enumerate(_products(c))],
            "ads": [a.model_dump(mode="json") for a in reversed(c.ugc_ads)]}


class UgcScriptRequest(BaseModel):
    product: int
    format: str = "pov"
    language: str = "en"  # en | ur | roman


def _ugc_product(c: Campaign, index: int):
    items = _products(c)
    if not 0 <= index < len(items):
        raise HTTPException(404, "Pick one of the brand's products.")
    return items[index]


@app.post("/api/campaigns/{campaign_id}/ugc/script")
async def ugc_script(campaign_id: str, req: UgcScriptRequest) -> dict:
    c = _campaign(campaign_id)
    if not c.brand:
        raise HTTPException(409, "This campaign has no brand kit yet.")
    if req.format not in ugc.FORMATS:
        raise HTTPException(422, "Unknown format.")
    language = req.language if req.language in ugc.SCRIPT_LANGUAGES else "en"
    lines, used = await ugc.write_script(c.brand, _ugc_product(c, req.product), req.format, language)
    return {"lines": lines, "used_llm": used}


class UgcMakeRequest(BaseModel):
    product: int
    format: str = "pov"
    lines: list[str]
    engine: str = "builtin"  # builtin (product video) | presenter (free AI presenter) | person (your own video) | avatar (HeyGen)
    avatar_id: str = ""
    avatar_name: str = ""
    look: str = ""  # product video layout; "" = a different one each time
    caption: str = ""  # caption style; "" = a different one each time
    voice: bool = False  # a free AI voice reads the script (product video)
    voice_key: str = ""  # which voice (speech.VOICES); "" = one that fits the script's language and the presenter
    character: str = ""  # the free presenter (avatar.CHARACTERS)
    language: str = "en"  # the script's language (en | ur | roman), for the end card
    footage: str = ""  # the uploaded video, for engine "person"


@app.post("/api/campaigns/{campaign_id}/ugc", status_code=202)
async def make_ugc(campaign_id: str, req: UgcMakeRequest) -> dict:
    """Start making a UGC ad in the background; poll /api/ugc-jobs/{id}."""
    c = _campaign(campaign_id)
    if not c.brand:
        raise HTTPException(409, "This campaign has no brand kit yet.")
    product = _ugc_product(c, req.product)
    lines = [line.strip()[:140] for line in req.lines if line.strip()][:8]
    if not lines:
        raise HTTPException(422, "Write at least one line.")
    if req.engine not in ("builtin", "presenter", "person", "avatar"):
        raise HTTPException(422, "Unknown way to make the ad.")
    footage = None
    if req.engine == "person":
        try:
            footage = photos.upload_path(req.footage)
        except KeyError as exc:
            raise HTTPException(404, "Record or upload your video first.") from exc
    if req.voice_key and req.voice_key not in speech.VOICES:
        raise HTTPException(422, "Unknown voice.")
    if ((req.voice and req.engine == "builtin") or req.engine == "presenter") and not speech.tts_available():
        raise HTTPException(409, "The AI voice isn't installed on this computer: pip install piper-tts")
    if req.engine == "avatar":
        if not ugc.heygen_ready():
            raise HTTPException(409, "Connect HeyGen on the Connections page to use AI presenters.")
        if not req.avatar_id:
            raise HTTPException(422, "Pick a presenter.")
    if sum(j["status"] == "running" for j in UGC_JOBS.values()) >= config.REEL_RENDERS + reels.MAX_WAITING:
        raise HTTPException(429, "Lots of videos are being made right now. Please try again in a minute.", headers={"Retry-After": "60"})
    job_id = new_id()
    UGC_JOBS[job_id] = {"status": "running", "step": "Getting the product photo", "at": datetime.now(timezone.utc)}

    async def run() -> None:
        job = UGC_JOBS[job_id]
        try:
            photo = await photos.website_background(product.image_url, credit=f"Photo from {c.brand.name}") \
                if not product.image_url.startswith("/media/") else None
            path = photo.path if photo else str(config.MEDIA_DIR / product.image_url.split("?")[0].removeprefix("/media/"))
            token = uuid.uuid4().hex[:8]
            out, poster = config.MEDIA_DIR / f"ugc_{c.id}_{token}.mp4", config.MEDIA_DIR / f"ugc_{c.id}_{token}.jpg"
            f = ugc.facts(c.brand, product)
            end = (f["name"], f["price"], ugc.END_CTA.get(req.language, ugc.END_CTA["en"]))
            look = caption = ""
            script = lines
            if req.engine == "avatar":
                job["step"] = "HeyGen is filming your presenter (a few minutes)"
                seconds = await ugc.heygen_video(path, req.avatar_id, " ".join(lines), out, poster,
                                                 on_progress=lambda s: job.update(step=s))
            elif req.engine == "person":
                job["step"] = "Listening to your video and adding captions"
                caption = req.caption if req.caption in ugc_video.CAPTIONS else random.choice(["outline", "box", "pop"])
                async with reels.render_slots():
                    seconds, script = await reels.render.run_in_worker(
                        ugc_video.make_person_ad, c.brand, str(footage), lines, path, [f["name"], f["price"]], out, poster,
                        caption, int(token, 16) % 997, end)
            elif req.engine == "presenter":
                character = avatar.BY_KEY.get(req.character) or avatar.CHARACTERS[0]
                voice = req.voice_key or _voice_for(lines, character.gender)
                mix = ugc_video.choose_mix(len(lines), int(token, 16) % 99991, caption=req.caption)
                caption = mix.caption
                job["step"] = f"{character.name} is recording the voice and filming"
                async with reels.render_slots():
                    seconds = await reels.render.run_in_worker(
                        avatar.make_presenter_ad, c.brand, path, lines, voice, character.key, out, poster, mix, end, (f["name"], f["price"]))
            else:
                last = next((a for a in reversed(c.ugc_ads) if a.engine == "builtin"), None)
                mix = ugc_video.choose_mix(len(lines), int(token, 16) % 99991, req.look, req.caption,
                                           avoid={"look": last.look, "caption": last.caption} if last else None)
                look, caption = mix.look, mix.caption
                job["step"] = "Recording the voice, then filming" if req.voice else "Filming and captioning"
                async with reels.render_slots():
                    seconds = await reels.render.run_in_worker(ugc_video.make_product_ad, c.brand, path, lines, out, poster, mix,
                                                               (req.voice_key or _voice_for(lines, "female")) if req.voice else "", end)
            ad = UgcAd(product=strategist.display_name(c.brand, product), format=req.format, engine=req.engine, script=script,
                       video_url=f"/media/{out.name}", poster_url=f"/media/{poster.name}" if poster.exists() else "",
                       seconds=seconds, avatar=req.avatar_name if req.engine == "avatar" else
                       (avatar.BY_KEY.get(req.character) or avatar.CHARACTERS[0]).name if req.engine == "presenter" else "",
                       look=look, caption=caption, voice=(req.voice and req.engine == "builtin") or req.engine == "presenter")
            c.ugc_ads.append(ad)
            store.save(c)
            job.update(status="done", result=ad.model_dump(mode="json"))
        except (ugc.UgcError, ugc_video.VideoError, speech.SpeechError, reels.ReelError, httpx.HTTPError, ValueError, OSError) as exc:
            job.update(status="error", error=redact(str(exc))[:300])
        except Exception as exc:  # noqa: BLE001 - reported to the page that's waiting
            logging.getLogger(__name__).exception("ugc job %s failed", job_id)
            job.update(status="error", error=f"The video couldn't be made ({type(exc).__name__}).")

    task = asyncio.create_task(run())
    _ugc_tasks.add(task)
    task.add_done_callback(_ugc_tasks.discard)
    return {"job_id": job_id, "status": "running"}


def _voice_for(lines: list[str], gender: str) -> str:
    """A voice that fits the script: Urdu script gets an Urdu voice, everything else an American one."""
    urdu = any(lang.ARABIC.search(line) for line in lines)
    if urdu:
        return "ur-pk-aegis" if gender == "female" else "ur-pk-fasih"
    return "en-us-ljspeech" if gender == "female" else "en-us-john"


@app.get("/api/ugc/presenters/{key}.png")
async def presenter_preview(key: str):
    """A portrait of a free presenter, drawn once and kept."""
    ch = avatar.BY_KEY.get(key)
    if not ch:
        raise HTTPException(404, "Unknown presenter.")
    path = config.MEDIA_DIR / f"presenter_{key}.png"
    if not path.exists():
        await asyncio.to_thread(lambda: avatar.preview(ch).save(path))
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})


SAMPLE_LINES = {
    "en": "Hi! This is how I'd sound in your ad.", "ur": "السلام علیکم! آپ کے اشتہار میں میری آواز ایسی ہوگی۔",
    "it": "Ciao! Ecco come suonerei nel tuo annuncio.", "es": "¡Hola! Así sonaría en tu anuncio.", "fr": "Bonjour ! Voici ma voix dans votre publicité.",
    "de": "Hallo! So klinge ich in deiner Anzeige.", "pt": "Olá! É assim que eu soaria no seu anúncio.", "ru": "Привет! Так я буду звучать в вашей рекламе.",
    "fa": "سلام! صدای من در تبلیغ شما این‌گونه است.", "ne": "नमस्ते! तपाईंको विज्ञापनमा मेरो आवाज यस्तो हुनेछ।", "te": "నమస్తే! మీ ప్రకటనలో నా స్వరం ఇలా ఉంటుంది.",
}


@app.get("/api/ugc/voices/{key}/sample.wav")
async def voice_sample(key: str):
    """A few seconds of a voice, to hear it before choosing (made once, then kept)."""
    v = speech.VOICES.get(key)
    if not v:
        raise HTTPException(404, "Unknown voice.")
    if not speech.tts_available():
        raise HTTPException(409, "The voices aren't installed on this computer: pip install piper-tts")
    path = config.MEDIA_DIR / f"voice_sample_{v.key}.wav"
    if not path.exists():
        try:
            await asyncio.to_thread(speech.speak, [SAMPLE_LINES.get(v.language, SAMPLE_LINES["en"])], path, v.key)
        except (speech.SpeechError, httpx.HTTPError, OSError) as exc:
            raise HTTPException(502, f"That voice couldn't be loaded: {exc}") from exc
    return FileResponse(path, media_type="audio/wav", headers={"Cache-Control": "public, max-age=86400"})


MAX_FOOTAGE_BYTES = 300 * 1024 * 1024
MAX_FOOTAGE_SECONDS = 180
FOOTAGE_TYPES = (".mp4", ".mov", ".webm", ".m4v", ".mkv")


@app.post("/api/ugc/footage")
async def upload_footage(file: UploadFile = File(...)) -> dict:
    """A real person's clip (recorded in the app or filmed on a phone) for a UGC ad. Kept like other
    uploads (two weeks unless an ad uses it)."""
    ext = Path(file.filename or "").suffix.lower()
    if ext not in FOOTAGE_TYPES and not (file.content_type or "").startswith("video/"):
        raise HTTPException(422, "That isn't a video file (MP4, MOV or WebM).")
    name = f"up_footage_{uuid.uuid4().hex[:12]}{ext if ext in FOOTAGE_TYPES else '.webm'}"
    path = config.MEDIA_DIR / name
    size = 0
    with open(path, "wb") as fh:
        while chunk := await file.read(1 << 20):
            size += len(chunk)
            if size > MAX_FOOTAGE_BYTES:
                break
            fh.write(chunk)
    if size > MAX_FOOTAGE_BYTES:
        path.unlink(missing_ok=True)
        raise HTTPException(413, "Videos are limited to 300 MB.")
    try:
        seconds = await asyncio.to_thread(ugc_video.probe_duration, str(path))
    except ugc_video.VideoError as exc:
        path.unlink(missing_ok=True)
        raise HTTPException(422, str(exc)) from exc
    if seconds > MAX_FOOTAGE_SECONDS:
        path.unlink(missing_ok=True)
        raise HTTPException(422, "Keep it under 3 minutes: UGC ads work best at 15 to 45 seconds.")
    return {"id": name, "url": f"/media/{name}", "seconds": round(seconds, 1)}


@app.get("/api/ugc-jobs/{job_id}")
async def ugc_job(job_id: str) -> dict:
    job = UGC_JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "That video job has finished and been cleared. Make it again.")
    return {k: v for k, v in job.items() if k != "at"}


@app.get("/api/ugc/avatars")
async def ugc_avatars() -> list[dict]:
    if not ugc.heygen_ready():
        raise HTTPException(409, "Connect HeyGen on the Connections page to use AI presenters.")
    try:
        return await ugc.heygen_avatars()
    except ugc.UgcError as exc:
        raise HTTPException(502, str(exc)) from exc


@app.delete("/api/campaigns/{campaign_id}/ugc/{ad_id}", status_code=204)
async def delete_ugc(campaign_id: str, ad_id: str) -> None:
    c = _campaign(campaign_id)
    c.ugc_ads = [a for a in c.ugc_ads if a.id != ad_id]
    store.save(c)


class UgcAttachRequest(BaseModel):
    post_id: str


@app.post("/api/campaigns/{campaign_id}/ugc/{ad_id}/attach")
async def attach_ugc(campaign_id: str, ad_id: str, req: UgcAttachRequest) -> SocialPost:
    """Use the ad as a post's video (it then posts as a Reel / video, like a made reel)."""
    c = _campaign(campaign_id)
    ad = next((a for a in c.ugc_ads if a.id == ad_id), None)
    post = next((p for p in c.posts if p.id == req.post_id), None)
    if not ad or not post:
        raise HTTPException(404, "Ad or post not found.")
    for p in c.posts:
        if p.id == post.id or (post.group_id and p.group_id == post.group_id):
            p.video_url, p.video_poster = ad.video_url, ad.poster_url or None
    store.save(c)
    return post


@app.get("/api/reel-styles")
def reel_styles() -> list[dict]:
    return reels.style_list()


@app.get("/api/posts/{post_id}/reel/options")
def reel_options(post_id: str) -> dict:
    """Everything a reel can be: its topics (and which this post can use), the occasions (the ones
    near this post first, with their festive colours) and colour palettes worked out from the brand."""
    campaign, post = _post(post_id)
    kit = campaign.brand
    if not kit:
        raise HTTPException(409, "campaign has no brand kit yet")
    usable = reels.available_topics(campaign, post)
    near = {occasions.find(m.name).key: m.label() for m in calendar.upcoming(kit.country, post.publish_at.date(), 21, lead=0)
            if occasions.find(m.name)}
    occ = occasions.occasion_list(kit.country)
    for o in occ:
        o["soon"] = near.get(o["key"], "")
    occ.sort(key=lambda o: not o["soon"])
    return {
        "topics": [{"key": k, "label": label, "blurb": blurb, "available": k in usable} for k, (label, blurb) in reels.TOPICS.items()],
        "suggested_topic": reels.default_topic(campaign, post),
        "occasions": occ,
        "suggested_occasion": reels.post_occasion(campaign, post) or next((o["key"] for o in occ if o["soon"]), ""),
        "palettes": reels.palette_list(kit),
        "styles": reels.style_list(),
        "languages": [{"key": k, "label": v} for k, v in lang.LANGUAGES.items()],
        "trends": [{"key": k, "label": lang.TRENDS[k]["label"].format(city=(kit.location or "").split(",")[0].strip())}
                   for k in reels.trend_formats(kit)],
    }


class CaptionLanguageRequest(BaseModel):
    language: str


CAPTION_LANGUAGE_SYSTEM = """Rewrite this social media caption for the same brand and platform in the requested language.
Roman Urdu means Urdu written in Latin letters, casual, the way people in Pakistan text and post. Urdu means Urdu script.
"English + Roman Urdu" means English with natural Roman Urdu phrases mixed in. Keep every fact, price and product name
exactly; don't add offers or claims. You may open with one short, natural line in the style that's trending in Pakistani
feeds if it fits. No hashtags. Return JSON: {"caption": "..."}"""


@app.post("/api/posts/{post_id}/caption-language")
async def caption_language(post_id: str, req: CaptionLanguageRequest) -> dict:
    """The caption in English, Roman Urdu, Urdu or a mix. With Nemotron it's rewritten in the language;
    without, a trending opener and closer in that language frame the existing caption."""
    campaign, post = _post(post_id)
    kit = campaign.brand
    if req.language not in lang.LANGUAGES:
        raise HTTPException(422, f"Language must be one of: {', '.join(lang.LANGUAGES.values())}.")
    base = post.original_caption or post.caption
    rewritten = False
    if router.enabled and kit:
        try:
            data = await router.complete_json("rewrite", CAPTION_LANGUAGE_SYSTEM,
                                              f"Brand: {kit.name}\nPlatform: {post.platform.value}\nLanguage: {lang.LANGUAGES[req.language]}\n"
                                              f"Caption:\n{base}", temperature=0.7, max_tokens=900)
            text = str(data.get("caption") or "").strip() if isinstance(data, dict) else ""
            if text and not humanizer.missing_facts(base, text, [kit.name]):
                _set_caption(post, humanizer.rule_pass(text) if req.language != "ur" else text)
                rewritten = True
        except (LLMError, AttributeError) as exc:
            logging.getLogger(__name__).info("caption language rewrite fell back: %s", exc)
    if not rewritten:
        p = lang.pools(req.language)
        if p == "en":
            _set_caption(post, base)
        else:
            seed = sum(map(ord, post.id))
            _set_caption(post, f"{variety.pick(lang.OPENERS[p], seed)}\n\n{base}\n\n{variety.pick(lang.CLOSERS[p], seed)}")
    post.original_caption = post.original_caption or base
    store.save(campaign)
    return {"post": post, "rewritten": rewritten}


class ReelHumanizeRequest(BaseModel):
    scenes: list[ReelScene]


@app.post("/api/posts/{post_id}/reel/humanize")
async def humanize_reel(post_id: str, req: ReelHumanizeRequest) -> dict:
    """Make a reel's words sound like a person wrote them, without rendering."""
    campaign, _ = _post(post_id)
    if not campaign.brand:
        raise HTTPException(409, "campaign has no brand kit yet")
    scenes, info = await reels.humanize_scenes(campaign.brand, req.scenes[: reels.MAX_SCENES])
    return {"scenes": scenes, **info}


@app.get("/api/posts/{post_id}/reel/photos")
def reel_photos(post_id: str) -> list[dict]:
    """Photos a reel scene can use: the campaign's, then the brand's product and website photos."""
    campaign, _ = _post(post_id)
    return reels.photo_choices(campaign)


@app.get("/api/posts/{post_id}/share")
def share_post(post_id: str) -> dict:
    _, post = _post(post_id)
    return share_links(post)


@app.post("/api/posts/{post_id}/mark-published")
def mark_published(post_id: str) -> SocialPost:
    campaign, post = _post(post_id)
    post.status, post.published_via, post.publish_error = PostStatus.PUBLISHED, "manual", None
    store.save(campaign)
    return post


@app.post("/api/posts/{post_id}/publish")
async def publish_now(post_id: str) -> SocialPost:
    """Post directly to the platform through its official API."""
    campaign, post = _post(post_id)
    if post.status is PostStatus.PUBLISHED:
        raise HTTPException(409, "This post is already published.")
    if not publishing.can_publish(post.platform):
        raise HTTPException(400, f"{post.platform.value.title()} isn't connected for direct posting yet.")
    try:
        return await publishing.publish_post(post, campaign)
    except publishing.PublishError as exc:
        raise HTTPException(502, str(exc)) from exc


class BrowserSettingRequest(BaseModel):
    enabled: bool


class BrowserPostRequest(BaseModel):
    submit: bool = False  # False fills the composer in for you to check and press Post
    media: str = "images"  # images | reel


class MetaConnectRequest(BaseModel):
    token: str
    app_id: str = ""
    app_secret: str = ""


class KeysRequest(BaseModel):
    nebius_api_key: str | None = None
    tavily_api_key: str | None = None
    heygen_api_key: str | None = None


@app.get("/api/connections")
async def get_connections() -> dict:
    """What's connected (never the keys themselves)."""
    return connections.status()


@app.put("/api/connections/meta")
async def connect_meta(req: MetaConnectRequest) -> dict:
    """Connect Instagram and the Facebook Page through Meta's official API: no browser sign-in, no captchas."""
    try:
        result = await connections.connect_meta(req.token, req.app_id, req.app_secret)
    except connections.ConnectionError_ as exc:
        raise HTTPException(400, str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Couldn't reach Meta: {exc}") from exc
    return {**connections.status(), "result": result}


@app.put("/api/connections/keys")
async def save_keys(req: KeysRequest) -> dict:
    """Save the Nemotron (Nebius) and Tavily keys, each checked with its service first."""
    try:
        if req.nebius_api_key:
            await connections.check_nebius(req.nebius_api_key)
            connections.save(NEBIUS_API_KEY=req.nebius_api_key.strip())
        if req.tavily_api_key:
            await connections.check_tavily(req.tavily_api_key)
            connections.save(TAVILY_API_KEY=req.tavily_api_key.strip())
        if req.heygen_api_key:
            await ugc.heygen_check(req.heygen_api_key)
            connections.save(HEYGEN_API_KEY=req.heygen_api_key.strip())
    except ugc.UgcError as exc:
        raise HTTPException(400, str(exc)) from exc
    except connections.ConnectionError_ as exc:
        raise HTTPException(400, str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Couldn't reach the service: {exc}") from exc
    return connections.status()


@app.delete("/api/connections/{name}")
def disconnect(name: str) -> dict:
    if name not in ("meta", "nebius", "tavily", "heygen"):
        raise HTTPException(404, "Unknown connection.")
    connections.disconnect(name)
    return connections.status()


@app.get("/api/browser")
async def browser_status() -> dict:
    """Which platforms MonoPlus's own browser is signed in to."""
    from .social import browser

    if not browser.available():
        return {"available": False, "signed_in": {}, "scheduled": store.settings.browser_publish}
    try:
        signed_in = await browser.poster.status()
    except Exception as exc:  # noqa: BLE001 - e.g. a window already open, or no display on a server
        return {"available": True, "error": browser.explain(exc), "signed_in": browser.poster.signed_in,
                "scheduled": store.settings.browser_publish}
    return {"available": True, "signed_in": signed_in, "needs_check": browser.poster.needs_check, "signing_in": browser.poster.signing_in(), "browser": browser.poster.channel,
            "scheduled": store.settings.browser_publish and store.settings.auto_publish}


@app.post("/api/browser/login/{platform}")
async def browser_login(platform: Platform) -> dict:
    """Open the platform's sign-in page in MonoPlus's browser window; you sign in there yourself."""
    from .social import browser

    if not browser.available():
        raise HTTPException(503, "Posting from the browser needs Playwright: pip install playwright && python -m playwright install chromium")
    try:
        how = await browser.poster.login(platform)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, browser.explain(exc)) from exc
    name = platform.value.title()
    if how == "plain":
        return {"opened": True, "note": f"A Chrome window opened on {name}'s sign-in page. Sign in there (answer any check it shows), "
                                        "then close that window: MonoPlus notices the sign-in once it's closed."}
    return {"opened": True, "note": f"A browser window opened on {name}'s sign-in page. Sign in there, then come back."}


@app.post("/api/browser/sign-out")
async def browser_sign_out() -> dict:
    """Forget every sign-in MonoPlus's browser holds (it deletes the browser profile)."""
    from .social import browser

    if browser.available():
        try:
            await browser.poster.sign_out()
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(503, browser.explain(exc)) from exc
    store.settings.browser_publish = False
    store.save()
    return {"signed_out": True}


@app.put("/api/browser/scheduled")
def browser_scheduled(req: BrowserSettingRequest) -> dict:
    """Let approved posts go out at their scheduled time through the signed-in browser. Turning it on
    turns on auto-posting too: ticking "post automatically" and having nothing happen helps no one."""
    store.settings.browser_publish = req.enabled
    if req.enabled:
        store.settings.auto_publish = True
    store.save()
    return {"scheduled": store.settings.browser_publish, "auto_publish": store.settings.auto_publish}


@app.post("/api/posts/{post_id}/browser-post")
async def post_with_browser(post_id: str, req: BrowserPostRequest) -> dict:
    """Open the platform in MonoPlus's signed-in browser with this post's images (or reel) and caption,
    and with submit=true press Post too."""
    campaign, post = _post(post_id)
    if post.status is PostStatus.PUBLISHED and req.submit:
        raise HTTPException(409, "This post is already published.")
    try:
        message = await publishing.browser_post(post, req.submit, req.media)
    except publishing.PublishError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"post": post, "message": message}


@app.get("/api/publishing")
def publishing_status() -> dict:
    """Which platforms can be posted to directly, and whether auto-publish is on. No secrets."""
    return {"connected": publishing.connections(), "webhook": bool(config.PUBLISH_WEBHOOK_URL),
            "auto_publish": store.settings.auto_publish}


@app.put("/api/publishing/auto")
def set_auto_publish(req: AutoPublishRequest) -> dict:
    store.settings.auto_publish = req.enabled
    store.save()
    return publishing_status()


# --------------------------------------------------------------------------- photos & uploads


@app.get("/api/photos/search")
async def photo_search(q: str = Query(..., min_length=2, max_length=100), orientation: str = Query("square", pattern="^(square|portrait|landscape)$")) -> dict:
    results = await photos.search(q, orientation)
    return {"source": "pexels" if config.PEXELS_API_KEY else "openverse", "photos": [p.as_dict() for p in results]}


@app.post("/api/uploads", status_code=201)
async def upload_image(file: UploadFile = File(...)) -> dict:
    data = await file.read(photos.MAX_UPLOAD_BYTES + 1)
    try:
        return await asyncio.to_thread(photos.save_upload, data)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


# --------------------------------------------------------------------------- research


@app.get("/api/research/stream")
async def research_stream(
    q: str = Query(..., min_length=3, max_length=300),
    region: str = Query("", max_length=100),
    campaign_id: str | None = None,
):
    """Live research as server-sent events. The run is saved as a research task so it can be reused."""
    if campaign_id and campaign_id not in store.campaigns:
        raise HTTPException(404, "campaign not found")
    # Created as running so the background queue worker never picks up a live run.
    task = ResearchTask(topic=q.strip(), region=region.strip(), campaign_id=campaign_id, status="running")
    store.research[task.id] = task

    async def events():
        yield f"data: {json.dumps({'type': 'task', 'id': task.id})}\n\n"
        try:
            async for ev in research.execute(task):
                yield f"data: {json.dumps(ev, ensure_ascii=False, default=str)}\n\n"
        except Exception as exc:  # noqa: BLE001 - surfaced to the client
            yield f"data: {json.dumps({'type': 'error', 'message': redact(exc)[:300]})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/research/tasks")
def list_research() -> list[ResearchTask]:
    return sorted(store.research.values(), key=lambda t: t.created_at, reverse=True)


@app.post("/api/research/tasks", status_code=201)
def queue_research(req: CreateResearchTaskRequest) -> ResearchTask:
    if req.campaign_id and req.campaign_id not in store.campaigns:
        raise HTTPException(404, "campaign not found")
    task = ResearchTask(topic=req.topic.strip(), region=req.region.strip(), campaign_id=req.campaign_id)
    store.research[task.id] = task
    store.save()
    return task


@app.post("/api/research/competitors", status_code=201)
async def research_competitors(req: CompetitorResearchRequest) -> ResearchTask:
    """Start a competitor analysis for a brand (by website, or a campaign's brand). It runs in
    the background; poll GET /api/research/tasks/{id} for progress and the report."""
    campaign = store.campaigns.get(req.campaign_id) if req.campaign_id else None
    if req.campaign_id and not (campaign and campaign.brand):
        raise HTTPException(404, "campaign not found")
    url = (campaign.brand.website_url if campaign else None) or (req.url or "").strip()
    if not url:
        raise HTTPException(422, "Give the brand's website, or pick a campaign.")
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"
    name = campaign.brand.name if campaign else urlparse(url).netloc.removeprefix("www.")
    task = ResearchTask(topic=f"Competitors of {name}", kind="competitors", brand_url=url, campaign_id=req.campaign_id,
                        competitor_urls=[u.strip() for u in req.competitor_urls if u.strip()][:8])
    store.research[task.id] = task
    store.save()
    research.start_now(task.id)
    return task


@app.get("/api/research/tasks/{task_id}")
def get_research(task_id: str) -> ResearchTask:
    task = store.research.get(task_id)
    if not task:
        raise HTTPException(404, "research not found")
    return task


@app.delete("/api/research/tasks/{task_id}", status_code=204)
def delete_research(task_id: str) -> None:
    if store.research.pop(task_id, None) is None:
        raise HTTPException(404, "research not found")
    for c in store.campaigns.values():
        if task_id in c.research_ids:
            c.research_ids.remove(task_id)
    store.save()


@app.get("/api/research/memory")
def research_memory(q: str = Query("trends", max_length=200)) -> list[dict]:
    return memory.recall(q, 10)


# --------------------------------------------------------------------------- tools


@app.post("/api/humanize")
async def humanize_text(req: HumanizeRequest) -> dict:
    res = await humanizer.humanize(req.text, use_llm=req.use_llm, threshold=0, mode=req.mode, protect=req.protect)
    return {"text": res.text, "before": res.before, "after": res.after, "used_llm": res.used_llm, "mode": res.mode,
            "patterns_before": res.patterns_before, "patterns_after": res.patterns_after, "steps": [asdict(s) for s in res.steps]}
