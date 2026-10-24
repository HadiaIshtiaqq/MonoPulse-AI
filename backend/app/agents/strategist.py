"""Agent 3: Strategy & copywriting (Nemotron 3 Ultra).

One Ultra call builds the campaign strategy; the calendar is then split into batches
that are written concurrently so a 30-day package stays fast.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass

from .. import config
from ..llm import LLMError, router
from ..schemas import BrandKit, CampaignStrategy, ContentPillar, Platform, TrendItem

log = logging.getLogger(__name__)

PLATFORM_RULES = {
    Platform.INSTAGRAM: "Instagram: 300-700 characters, hook in the first line, short paragraphs with line breaks, no hashtags in the body.",
    Platform.LINKEDIN: "LinkedIn: 500-1100 characters, open with a specific observation or number, practical and credible, no hashtags in the body.",
    Platform.X: "X: under 240 characters total including CTA, one sharp idea, no hashtags in the body.",
    Platform.FACEBOOK: "Facebook: 200-500 characters, conversational and community-minded, ask a question, no hashtags in the body.",
}


CAROUSEL_PLATFORMS = {Platform.INSTAGRAM, Platform.LINKEDIN}


@dataclass
class Slot:
    day: int
    platform: Platform
    pillar: str
    theme: str
    trend: TrendItem | None
    format: str = "single"


def brand_brief(kit: BrandKit) -> str:
    return json.dumps(
        {
            "name": kit.name,
            "tagline": kit.tagline,
            "industry": kit.industry,
            "location": kit.location,
            "description": kit.description[:500],
            "value_props": kit.value_props,
            "keywords": kit.keywords,
            "voice": kit.brand_voice_prompt,
            "website": kit.website_url,
        },
        ensure_ascii=False,
    )


def trend_brief(trends: list[TrendItem]) -> str:
    return "\n".join(f"- {t.title}: {t.snippet[:220]}" for t in trends[:10]) or "(no live trends available)"


# --------------------------------------------------------------------------- strategy

STRATEGY_SYSTEM = """You are the strategy director of a small social media agency.
Plan a content campaign for the brand below, using the live trends where they genuinely fit.
Return JSON:
{
  "positioning": "one sentence: who it's for, what it does, why it's different",
  "audience": "one sentence describing the ideal customer specifically",
  "voice_rules": ["5 concrete do/don't rules for how this brand writes"],
  "pillars": [{"name": "2-3 words", "description": "one sentence"}],   // exactly 4 pillars
  "weekly_themes": ["one theme per week, each tied to a trend or season where possible"]
}"""


async def build_strategy(kit: BrandKit, trends: list[TrendItem], weeks: int, research: str = "") -> CampaignStrategy:
    if router.enabled:
        try:
            user = f"BRAND:\n{brand_brief(kit)}\n\nLIVE TRENDS:\n{trend_brief(trends)}\n\n"
            if research:
                user += f"MARKET RESEARCH (use these findings to shape pillars and themes):\n{research}\n\n"
            user += f"Weeks in campaign: {weeks}"
            data = await router.complete_json("strategy", STRATEGY_SYSTEM, user, temperature=0.6, max_tokens=1500)
            strategy = CampaignStrategy(
                positioning=str(data.get("positioning", "")),
                audience=str(data.get("audience", "")),
                voice_rules=[str(r) for r in data.get("voice_rules", [])][:6],
                pillars=[ContentPillar(name=str(p.get("name", "")), description=str(p.get("description", "")))
                         for p in data.get("pillars", []) if isinstance(p, dict)][:4],
                weekly_themes=[str(t) for t in data.get("weekly_themes", [])][:weeks],
            )
            if strategy.pillars:
                while len(strategy.weekly_themes) < weeks:
                    strategy.weekly_themes.append(strategy.pillars[len(strategy.weekly_themes) % len(strategy.pillars)].name)
                return strategy
        except (LLMError, AttributeError, TypeError) as exc:
            log.warning("strategy generation failed, using fallback: %s", exc)
    return fallback_strategy(kit, trends, weeks)


def fallback_strategy(kit: BrandKit, trends: list[TrendItem], weeks: int) -> CampaignStrategy:
    vp = kit.value_props or [kit.tagline or kit.name]
    pillars = [
        ContentPillar(name="Behind the Scenes", description=f"How {kit.name} actually does the work."),
        ContentPillar(name="Customer Wins", description="Real outcomes and stories from customers."),
        ContentPillar(name="Quick Tips", description=f"Useful advice for people interested in {kit.industry.lower() or 'what we do'}."),
        ContentPillar(name="Offers & News", description=f"What's new: {vp[0][:80]}"),
    ]
    themes = [t.title[:70] for t in trends[:weeks]]
    while len(themes) < weeks:
        themes.append(pillars[len(themes) % 4].name)
    return CampaignStrategy(
        positioning=f"{kit.name}: {kit.tagline or vp[0]}",
        audience=f"People {('in ' + kit.location) if kit.location else 'nearby'} looking for {kit.industry.lower() or 'a business they can trust'}.",
        voice_rules=["Be specific, not generic", "Talk like a person, not a press release", "One idea per post",
                     "Lead with the customer's problem", "End with a clear next step"],
        pillars=pillars,
        weekly_themes=themes,
    )


# --------------------------------------------------------------------------- slots


def plan_slots(strategy: CampaignStrategy, trends: list[TrendItem], platforms: list[Platform], days: int, per_day: int) -> list[Slot]:
    pillars = [p.name for p in strategy.pillars] or ["General"]
    slots: list[Slot] = []
    i = 0
    for day in range(days):
        for k in range(per_day):
            platform = platforms[(day * per_day + k) % len(platforms)]
            theme = strategy.weekly_themes[min(day // 7, len(strategy.weekly_themes) - 1)] if strategy.weekly_themes else ""
            # Roughly every third post rides a live trend.
            trend = trends[(i // 3) % len(trends)] if trends and i % 3 == 0 else None
            # Carousels get the most saves and shares on Instagram and LinkedIn; roughly one in four posts there.
            fmt = "carousel" if platform in CAROUSEL_PLATFORMS and i % 4 == 2 else "single"
            slots.append(Slot(day=day, platform=platform, pillar=pillars[i % len(pillars)], theme=theme, trend=trend, format=fmt))
            i += 1
    return slots


# --------------------------------------------------------------------------- copywriting

COPY_SYSTEM = """You are a senior social copywriter writing for one small business.
Write one post per slot. Sound like the owner: specific details, plain words, no corporate filler.
Each post must fit its platform rules. When a slot includes a trend, connect it to the brand naturally
(don't force it, and never misstate the news).
Slots with "format": "carousel" are swipeable multi-image posts: also return "slides", 3 to 5 pages that each teach
one concrete step, tip or fact (headline <= 8 words, body <= 35 words). The caption then introduces the carousel.
Return a JSON array, one object per slot, in the same order:
[{"slot": <slot index>, "headline": "<= 7 words for the image overlay", "caption": "...", "cta": "short call to action",
  "slides": [{"headline": "...", "body": "..."}]  // carousel slots only
}]"""


async def write_batch(kit: BrandKit, strategy: CampaignStrategy, slots: list[Slot], offset: int, research: str = "") -> list[dict]:
    slot_desc = []
    for j, s in enumerate(slots):
        entry = {"slot": offset + j, "platform": s.platform.value, "format": s.format, "pillar": s.pillar, "weekly_theme": s.theme}
        if s.trend:
            entry["trend"] = f"{s.trend.title} - {s.trend.snippet[:200]}"
        slot_desc.append(entry)
    rules = "\n".join(PLATFORM_RULES[p] for p in {s.platform for s in slots})
    user = (
        f"BRAND:\n{brand_brief(kit)}\n\nSTRATEGY:\n{strategy.model_dump_json()}\n\n"
        f"PLATFORM RULES:\n{rules}\n\n"
        + (f"MARKET RESEARCH (draw on these findings and content angles where they fit):\n{research}\n\n" if research else "")
        + f"SLOTS:\n{json.dumps(slot_desc, ensure_ascii=False)}"
    )
    data = await router.complete_json("copywriting", COPY_SYSTEM, user, temperature=0.85, max_tokens=4000)
    if isinstance(data, dict):
        data = data.get("posts") or data.get("items") or []
    return [d for d in data if isinstance(d, dict)]


async def write_all(kit: BrandKit, strategy: CampaignStrategy, slots: list[Slot], research: str = "") -> list[dict]:
    """Return one copy dict per slot (headline, caption, cta)."""
    results: list[dict | None] = [None] * len(slots)
    if router.enabled:
        size = max(1, config.COPY_BATCH_SIZE)
        batches = [(i, slots[i : i + size]) for i in range(0, len(slots), size)]
        outs = await asyncio.gather(*(write_batch(kit, strategy, b, off, research) for off, b in batches), return_exceptions=True)
        for (off, batch), out in zip(batches, outs):
            if isinstance(out, BaseException):
                log.warning("copy batch at %s failed: %s", off, out)
                continue
            for j, item in enumerate(out[: len(batch)]):
                idx = item.get("slot", off + j)
                idx = idx if isinstance(idx, int) and off <= idx < off + len(batch) else off + j
                if item.get("caption"):
                    results[idx] = item
    out = []
    for i, r in enumerate(results):
        copy = r or fallback_copy(kit, slots[i])
        if slots[i].format == "carousel":
            slides = clean_slides(copy.get("slides"))
            copy["slides"] = slides if len(slides) >= 2 else fallback_slides(kit)
        out.append(copy)
    return out


def clean_slides(raw) -> list[dict]:
    slides = []
    for s in raw if isinstance(raw, list) else []:
        if isinstance(s, dict) and (s.get("headline") or s.get("body")):
            slides.append({"headline": str(s.get("headline", ""))[:90], "body": str(s.get("body", ""))[:320]})
    return slides[:6]


def fallback_slides(kit: BrandKit) -> list[dict]:
    """Demo-mode carousel pages built from the brand's own value props."""
    props = [p.rstrip(".") for p in (kit.value_props or [])][:3] or [kit.tagline or kit.name]
    slides = [{"headline": p[:60], "body": f"{p}. Ask about it next time you're in, or see more at {kit.website_url or 'our page'}."}
              for p in props]
    slides.append({"headline": "Save this for later", "body": f"Questions about any of these? Ask the {kit.name} team, we read every message."})
    return slides


def fallback_copy(kit: BrandKit, slot: Slot) -> dict:
    """Template copy for demo mode (no API key) or failed batches. Deliberately written in
    the generic 'raw LLM draft' style so the humanizer has something to fix in demos."""
    vp = kit.value_props[slot.day % len(kit.value_props)] if kit.value_props else kit.tagline or kit.name
    name, industry = kit.name, (kit.industry or "our industry").lower()
    trend_line = f" With everyone talking about {slot.trend.title.rstrip('.')}, it's the perfect time to rethink your approach." if slot.trend else ""
    templates = {
        "Behind the Scenes": (
            "Meet the team behind the magic",
            f"In today's fast-paced world, it is important to know who you are working with. At {name}, we take pride in every detail — {vp.lower().rstrip('.')}.{trend_line} Furthermore, we believe great work starts with great people.",
        ),
        "Customer Wins": (
            "Real results, real customers",
            f"Our customers do not just get a service — they get a partner. {vp.rstrip('.')}. That is why people keep coming back to {name}!{trend_line} Ready to elevate your experience?",
        ),
        "Quick Tips": (
            f"One {industry} tip you can use today",
            f"Looking to unlock the full potential of {industry}? Here is a quick tip from the {name} team: start small, stay consistent, and ask questions early.{trend_line} Small changes add up fast!",
        ),
        "Offers & News": (
            f"New at {name}"[:40],
            f"Exciting news! {vp.rstrip('.')}. We are thrilled to offer a seamless experience from start to finish.{trend_line} Do not miss out!",
        ),
    }
    headline, caption = templates.get(slot.pillar, templates["Customer Wins"])
    if slot.format == "carousel":
        headline = f"{min(4, len(kit.value_props) or 1) + 1} things to know about {name}"[:60]
        caption = f"Swipe through for a few things we wish more people knew about {industry}. {caption}"
    if slot.platform is Platform.X:
        caption = caption.split(". ")[0] + "."
    return {"headline": headline, "caption": caption, "cta": "Visit us today" if kit.location else "Learn more at the link in bio"}
