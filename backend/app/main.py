from __future__ import annotations

import asyncio
import contextlib
import csv
import hmac
import io
import json
import logging
import shutil
import zipfile
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, mcp_server, publishing
from .agents import humanizer, memory, photos, pipeline, renderer, research, strategist
from .agents.formatter import HASHTAG_COUNT, enforce_limits, normalize_hashtags
from .llm import LLMError, router
from .publishing import share_links
from .schemas import (
    AutoPublishRequest,
    BrandUpdateRequest,
    Campaign,
    CampaignStatus,
    CreateCampaignRequest,
    CreateResearchTaskRequest,
    HumanizeRequest,
    PostStatus,
    ResearchTask,
    RewriteRequest,
    SetBackgroundRequest,
    SocialPost,
    UpdatePostRequest,
)
from .store import store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    for t in store.research.values():
        if t.status == "running":
            t.status = "retry"  # the server restarted mid-run
    workers = [asyncio.create_task(research.worker()), asyncio.create_task(publishing.scheduler())]
    yield
    for w in workers:
        w.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await w


app = FastAPI(title="MonoPlus", version="0.4.0", lifespan=lifespan)
app.include_router(mcp_server.router)  # /mcp authenticates itself (Bearer token), see mcp_server._authorized

OPEN_PATHS = {"/api/health", "/api/access"}


@app.middleware("http")
async def require_access_key(request: Request, call_next):
    """With MONOPLUS_ACCESS_KEY set, every API call must carry it. /media stays public because
    Instagram and other platforms download post images from there."""
    path = request.url.path
    if config.ACCESS_KEY and path.startswith("/api/") and path not in OPEN_PATHS and request.method != "OPTIONS":
        given = request.headers.get("x-access-key") or request.query_params.get("key") or ""
        if not hmac.compare_digest(given.encode(), config.ACCESS_KEY.encode()):
            return JSONResponse({"detail": "Access key required."}, status_code=401)
    return await call_next(request)


app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"],
                   expose_headers=["Mcp-Session-Id"])
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
def access(request: Request) -> dict:
    """Tells the UI whether a key is needed and whether the one it holds is right."""
    given = request.headers.get("x-access-key") or ""
    ok = not config.ACCESS_KEY or hmac.compare_digest(given.encode(), config.ACCESS_KEY.encode())
    return {"required": bool(config.ACCESS_KEY), "ok": ok}


@app.get("/api/health")
def health() -> dict:
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
    campaign, job = pipeline.start(req)
    return {"campaign_id": campaign.id, "job_id": job.id}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
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
def list_campaigns() -> list[dict]:
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
def get_campaign(campaign_id: str) -> Campaign:
    return _campaign(campaign_id)


@app.post("/api/campaigns/{campaign_id}/approve-all")
def approve_all(campaign_id: str) -> Campaign:
    c = _campaign(campaign_id)
    for p in c.posts:
        if p.status is PostStatus.DRAFT:
            p.status = PostStatus.APPROVED
    c.status = CampaignStatus.APPROVED
    store.save()
    return c


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
    store.save()
    return c


@app.get("/api/campaigns/{campaign_id}/export")
def export_campaign(campaign_id: str):
    """ZIP of every image plus a CSV with captions, hashtags and schedule, ready for any scheduler."""
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
        z.writestr("posts.csv", rows.getvalue())
        credits = sorted({p.background.credit for p in c.posts if p.background and p.background.source == "stock"})
        if credits:
            z.writestr("photo-credits.txt", "\n".join(credits) + "\n")
    buf.seek(0)
    slug = "".join(ch if ch.isalnum() else "-" for ch in (c.brand.name if c.brand else "campaign")).strip("-").lower() or "campaign"
    return StreamingResponse(buf, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{slug}-monoplus.zip"'})


@app.get("/api/upcoming")
def upcoming(days: int = Query(7, ge=1, le=60)) -> list[dict]:
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
        post.caption = req.caption
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
    store.save()
    return post


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
    store.save()
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
    post.caption, post.ai_tell_after, post.is_humanized = res.text, res.after, True
    store.save()
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
    post.caption, post.ai_tell_after = res.text, res.after
    post.hashtags = normalize_hashtags(post.hashtags, HASHTAG_COUNT[post.platform])
    enforce_limits(post)
    if headline != post.headline:
        post.headline = headline
        await _rerender(campaign, post)
    store.save()
    return post


@app.get("/api/posts/{post_id}/share")
def share_post(post_id: str) -> dict:
    _, post = _post(post_id)
    return share_links(post)


@app.post("/api/posts/{post_id}/mark-published")
def mark_published(post_id: str) -> SocialPost:
    _, post = _post(post_id)
    post.status, post.published_via, post.publish_error = PostStatus.PUBLISHED, "manual", None
    store.save()
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
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)[:300]})}\n\n"
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
