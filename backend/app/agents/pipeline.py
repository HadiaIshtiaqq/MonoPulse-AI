"""Orchestrates the multi-agent DAG:

ingest -> trends -> strategy (Ultra) -> copy (Ultra, batched in parallel)
       -> humanize (rules + Ultra) -> format/SEO (Nano) -> render (Pillow)
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import date, datetime, time as dtime, timedelta, timezone

from .. import config
from ..schemas import Campaign, CampaignStatus, Job, JobStep, Slide, SocialPost
from ..scraper.ingestor import ingest
from ..store import store
from . import formatter, humanizer, photos, renderer, research, strategist, trends

log = logging.getLogger(__name__)

STEPS = [
    ("ingest", "Reading your site & building the brand kit"),
    ("trends", "Checking today's news & trends"),
    ("strategy", "Planning the content strategy"),
    ("copy", "Writing the posts"),
    ("humanize", "Making the copy sound human"),
    ("format", "Hashtags & SEO"),
    ("render", "Designing the visuals"),
]

_running: set[asyncio.Task] = set()


def start(req) -> tuple[Campaign, Job]:
    """Create a campaign from a CreateCampaignRequest and generate it in the background.

    Shared by the web API and the MCP server so both behave identically.
    """
    platforms = list(dict.fromkeys(req.platforms)) or list(renderer.SIZES)
    campaign = Campaign(start_date=req.start_date or date.today(), days=req.days,
                        platforms=platforms, research_ids=list(dict.fromkeys(req.research_ids)))
    job = new_job(campaign.id)
    store.campaigns[campaign.id] = campaign
    store.jobs[job.id] = job
    task = asyncio.get_running_loop().create_task(run_campaign(job, campaign, req.input, req.posts_per_day))
    _running.add(task)
    task.add_done_callback(_running.discard)
    return campaign, job

# Best-practice posting hour (local) per platform.
POST_HOUR = {"instagram": 11, "linkedin": 9, "x": 13, "facebook": 15}


GRAPHIC_LAYOUTS = ["bold", "split", "quote"]


async def attach_stock_photos(kit, posts: list[SocialPost]) -> int:
    """With a Pexels key, give roughly every third single post a licensed photo background.

    Openverse is too slow (tens of seconds per search) to sit inside campaign generation, so
    without Pexels the user adds photos per post from the editor instead.
    """
    if not config.PEXELS_API_KEY:
        return 0
    targets = [p for i, p in enumerate(posts) if p.format == "single" and i % 3 == 1]
    if not targets:
        return 0
    query = " ".join(filter(None, [kit.industry, (kit.keywords or [""])[0]])) or kit.name
    try:
        found = await photos.search(query, "portrait")
    except Exception:  # noqa: BLE001 - photos are decoration; never fail the campaign
        return 0
    attached = 0
    for post, photo in zip(targets, found):
        try:
            post.background = await photos.to_background(photo.id)
            post.layout = "photo"
            attached += 1
        except Exception:  # noqa: BLE001
            continue
    return attached


def new_job(campaign_id: str) -> Job:
    return Job(campaign_id=campaign_id, steps=[JobStep(key=k, label=l) for k, l in STEPS])


class StepTimer:
    def __init__(self, job: Job, campaign: Campaign, key: str) -> None:
        self.step = next(s for s in job.steps if s.key == key)
        self.campaign, self.key = campaign, key

    def __enter__(self) -> "StepTimer":
        self.step.status = "running"
        self.t0 = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        elapsed = round(time.perf_counter() - self.t0, 2)
        self.step.seconds = elapsed
        self.campaign.timings[self.key] = elapsed
        if exc_type:
            self.step.status = "error"
            self.step.detail = str(exc)[:200]
        elif self.step.status == "running":
            self.step.status = "done"


async def run_campaign(job: Job, campaign: Campaign, raw_input: str, posts_per_day: int) -> None:
    t_start = time.perf_counter()
    campaign.mode = "live" if config.llm_enabled() else "demo"
    try:
        with StepTimer(job, campaign, "ingest") as st:
            campaign.brand = await ingest(raw_input, search_fn=trends.search if config.search_enabled() else None)
            st.step.detail = f"{campaign.brand.name} · {campaign.brand.industry or 'industry unknown'}"
        kit = campaign.brand

        with StepTimer(job, campaign, "trends") as st:
            if config.search_enabled():
                campaign.trends = await trends.gather_trends(kit)
                st.step.detail = f"{len(campaign.trends)} live items" if campaign.trends else "no fresh news found"
            else:
                st.step.status, st.step.detail = "skipped", "live search turned off"

        weeks = max(1, (campaign.days + 6) // 7)
        findings = research.campaign_context(campaign.research_ids)
        with StepTimer(job, campaign, "strategy") as st:
            campaign.strategy = await strategist.build_strategy(kit, campaign.trends, weeks, findings)
            st.step.detail = ", ".join(p.name for p in campaign.strategy.pillars)
            if findings:
                st.step.detail += f" · using {len(campaign.research_ids)} research report(s)"

        with StepTimer(job, campaign, "copy") as st:
            slots = strategist.plan_slots(campaign.strategy, campaign.trends, campaign.platforms, campaign.days, posts_per_day)
            copies = await strategist.write_all(kit, campaign.strategy, slots, findings)
            posts = []
            for i, (slot, copy) in enumerate(zip(slots, copies)):
                day = campaign.start_date + timedelta(days=slot.day)
                hour = POST_HOUR.get(slot.platform.value, 12) + (i % posts_per_day) * 3
                posts.append(
                    SocialPost(
                        campaign_id=campaign.id,
                        day=slot.day,
                        platform=slot.platform,
                        pillar=slot.pillar,
                        headline=str(copy.get("headline", ""))[:90],
                        caption=str(copy.get("caption", "")),
                        cta=str(copy.get("cta", ""))[:120],
                        trend_title=slot.trend.title if slot.trend else None,
                        trend_url=slot.trend.url if slot.trend else None,
                        layout=GRAPHIC_LAYOUTS[i % len(GRAPHIC_LAYOUTS)],
                        format=slot.format,
                        slides=[Slide(**s) for s in copy.get("slides", [])] if slot.format == "carousel" else [],
                        publish_at=datetime.combine(day, dtime(hour=min(hour, 21)), tzinfo=timezone.utc),
                    )
                )
            campaign.posts = posts
            carousels = sum(p.format == "carousel" for p in posts)
            st.step.detail = f"{len(posts)} drafts" + (f" · {carousels} carousels" if carousels else "")

        with StepTimer(job, campaign, "humanize") as st:
            results = await asyncio.gather(
                *(humanizer.humanize(p.caption, voice=kit.brand_voice_prompt, protect=[kit.name]) for p in campaign.posts)
            )
            for post, res in zip(campaign.posts, results):
                post.original_caption = post.caption
                post.caption = res.text
                post.ai_tell_before, post.ai_tell_after = res.before, res.after
                post.is_humanized = True
            if results:
                avg_b = sum(r.before for r in results) / len(results)
                avg_a = sum(r.after for r in results) / len(results)
                st.step.detail = f"AI-tell score {avg_b:.0f} → {avg_a:.0f}"

        with StepTimer(job, campaign, "format"):
            await formatter.format_posts(kit, campaign.posts)

        with StepTimer(job, campaign, "render") as st:
            with_photos = await attach_stock_photos(kit, campaign.posts)
            await renderer.render_posts(kit, campaign.posts)
            pages = sum(len(p.image_urls) for p in campaign.posts)
            st.step.detail = f"{pages} images" + (f" · {with_photos} with stock photos" if with_photos else "")

        campaign.status = CampaignStatus.DRAFT
        campaign.target_month = campaign.start_date.strftime("%Y-%m")
        job.status = "done"
    except Exception as exc:  # noqa: BLE001 - reported to the UI via the job
        log.exception("campaign %s failed", campaign.id)
        campaign.status = CampaignStatus.FAILED
        job.status = "error"
        job.error = f"{type(exc).__name__}: {exc}"[:300]
    finally:
        campaign.timings["total"] = round(time.perf_counter() - t_start, 2)
        store.save()
