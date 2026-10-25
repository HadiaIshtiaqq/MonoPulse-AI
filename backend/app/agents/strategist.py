"""Agent 3: Strategy & copywriting (Nemotron 3 Ultra).

One Ultra call builds the campaign strategy; the calendar is then split into batches
that are written concurrently so a 30-day package stays fast.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass

from .. import config
from ..llm import LLMError, router
from ..schemas import BrandKit, CampaignStrategy, ContentPillar, Platform, Product, TrendItem

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
    product: Product | None = None  # the real product this post features
    slide_products: tuple[Product, ...] = ()  # carousel pages, one product each
    group: int = 0  # the post idea; every platform's version of it shares this


def product_brief(p: Product) -> dict:
    return {k: v for k, v in {"name": p.name, "price": p.price, "collection": p.category}.items() if v}


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
            "products_on_site": [product_brief(p) for p in kit.products[:12]],
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


def varied(products: list[Product]) -> list[Product]:
    """Interleave products so the same item name (often a generic type like "3-Piece Set")
    doesn't run several posts in a row."""
    groups: dict[str, list[Product]] = {}
    for p in products:
        groups.setdefault(p.name.lower(), []).append(p)
    out: list[Product] = []
    while any(groups.values()):
        for key in list(groups):
            if groups[key]:
                out.append(groups[key].pop(0))
    return out


def plan_slots(strategy: CampaignStrategy, trends: list[TrendItem], platforms: list[Platform], days: int, per_day: int,
               products: list[Product] | None = None) -> list[Slot]:
    """One post idea per day (or per_day of them), each in a version for every platform.

    The versions share the idea, product, pillar and trend; copy, image size and format are
    made for each platform (a carousel idea is a carousel on Instagram and LinkedIn, a single
    image on X and Facebook)."""
    pillars = [p.name for p in strategy.pillars] or ["General"]
    catalogue = varied([p for p in (products or []) if p.image_url] or list(products or []))
    platforms = list(dict.fromkeys(platforms))
    slots: list[Slot] = []
    i = 0
    for day in range(days):
        for _ in range(per_day):
            theme = strategy.weekly_themes[min(day // 7, len(strategy.weekly_themes) - 1)] if strategy.weekly_themes else ""
            # Roughly every third idea rides a live trend.
            trend = trends[(i // 3) % len(trends)] if trends and i % 3 == 0 else None
            # Carousels get the most saves and shares on Instagram and LinkedIn; every third idea.
            carousel_idea = i % 3 == 1
            product = catalogue[i % len(catalogue)] if catalogue else None
            extra = tuple(catalogue[(i + j) % len(catalogue)] for j in range(1, min(4, len(catalogue)))) if len(catalogue) > 1 else ()
            for platform in platforms:
                fmt = "carousel" if carousel_idea and platform in CAROUSEL_PLATFORMS else "single"
                slots.append(Slot(day=day, platform=platform, pillar=pillars[i % len(pillars)], theme=theme, trend=trend,
                                  format=fmt, product=product, slide_products=extra if fmt == "carousel" else (), group=i))
            i += 1
    return slots


# --------------------------------------------------------------------------- copywriting

COPY_SYSTEM = """You are a senior social copywriter writing for one small business.
Write one post per slot. Sound like the owner: specific details, plain words, no corporate filler.
Each post must fit its platform rules. When a slot includes a trend, connect it to the brand naturally
(don't force it, and never misstate the news).
Slots with "format": "carousel" are swipeable multi-image posts: also return "slides", 3 to 5 pages that each teach
one concrete step, tip or fact (headline <= 8 words, body <= 35 words). The caption then introduces the carousel.
Slots that share a "group" are the same post published on different platforms: keep the same idea, product and image
headline (use an identical "headline" across the group), but write each caption natively for its platform, never
copy-pasted: Instagram opens with a hook and ends with "link in bio"; Facebook is conversational and asks a question;
LinkedIn is professional, a little longer and about the craft, quality or business; X is one short, sharp line.
When a slot has a "product", the post features that exact product, shown in the photo: use its real name, and its price
exactly as given. When a carousel slot has "slide_products", write exactly one slide per listed product, in order.
Never invent products, prices, discounts or claims that aren't in the brief.
Return a JSON array, one object per slot, in the same order:
[{"slot": <slot index>, "headline": "<= 7 words for the image overlay", "caption": "...", "cta": "short call to action",
  "slides": [{"headline": "...", "body": "..."}]  // carousel slots only
}]"""


async def write_batch(kit: BrandKit, strategy: CampaignStrategy, slots: list[Slot], offset: int, research: str = "") -> list[dict]:
    slot_desc = []
    for j, s in enumerate(slots):
        entry = {"slot": offset + j, "group": s.group, "platform": s.platform.value, "format": s.format, "pillar": s.pillar,
                 "weekly_theme": s.theme}
        if s.trend:
            entry["trend"] = f"{s.trend.title} - {s.trend.snippet[:200]}"
        if s.product:
            entry["product"] = product_brief(s.product)
        if s.slide_products:
            entry["slide_products"] = [product_brief(p) for p in s.slide_products]
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


def group_batches(slots: list[Slot], size: int) -> list[tuple[int, list[Slot]]]:
    """Split slots into batches of about `size`, never splitting a post's platform versions,
    so the model writes all versions of one idea together and keeps them consistent."""
    batches: list[tuple[int, list[Slot]]] = []
    start = 0
    while start < len(slots):
        end = start
        while end < len(slots):
            group_end = end
            while group_end < len(slots) and slots[group_end].group == slots[end].group:
                group_end += 1
            if end > start and group_end - start > size:
                break
            end = group_end
        batches.append((start, slots[start:end]))
        start = end
    return batches


async def write_all(kit: BrandKit, strategy: CampaignStrategy, slots: list[Slot], research: str = "") -> list[dict]:
    """Return one copy dict per slot (headline, caption, cta)."""
    results: list[dict | None] = [None] * len(slots)
    if router.enabled:
        batches = group_batches(slots, max(1, config.COPY_BATCH_SIZE))
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
        slot = slots[i]
        copy = r or fallback_copy(kit, slot)
        if slot.format == "carousel":
            slides = clean_slides(copy.get("slides"))
            if slot.slide_products:
                # One page per product, so each page can carry that product's photo.
                slides = slides[: len(slot.slide_products)] if len(slides) >= len(slot.slide_products) else product_slides(slot.slide_products)
            copy["slides"] = slides if len(slides) >= 2 else fallback_slides(kit)
        out.append(copy)
    # One idea, one image headline: every version of the same format shows the same words on
    # the image (a carousel cover and a single image of the same idea can differ).
    shared: dict[tuple[int, str], str] = {}
    for slot, copy in zip(slots, out):
        if copy.get("headline"):
            shared.setdefault((slot.group, slot.format), copy["headline"])
    for slot, copy in zip(slots, out):
        copy["headline"] = shared.get((slot.group, slot.format), copy.get("headline", ""))
    return out


def product_slides(products) -> list[dict]:
    slides = []
    for p in products:
        body = " · ".join(x for x in (p.category, p.price) if x)
        slides.append({"headline": short_name(p.name), "body": body or "Now on our website."})
    return slides


def clean_slides(raw) -> list[dict]:
    slides = []
    for s in raw if isinstance(raw, list) else []:
        if isinstance(s, dict) and (s.get("headline") or s.get("body")):
            slides.append({"headline": str(s.get("headline", ""))[:90], "body": str(s.get("body", ""))[:320]})
    return slides[:6]


def fallback_slides(kit: BrandKit) -> list[dict]:
    """Demo-mode carousel pages built from the brand's own value props."""
    props = [p.rstrip(".") for p in (kit.value_props or [])][:3] or [kit.tagline or kit.name]
    site = (kit.website_url or "").split("//")[-1].strip("/") or "our page"
    slides = [{"headline": p[:60], "body": f"Ask about {p if len(p.split()) <= 4 else 'this'} next time you're in, or see more at {site}."}
              for p in props]
    slides.append({"headline": "Save this for later", "body": f"Questions about any of these? Ask the {kit.name} team, we read every message."})
    return slides


def shop_link(kit: BrandKit, p: Product) -> str:
    url = (p.url or kit.website_url or "").split("?")[0]
    return url.split("//")[-1].rstrip("/")


def short_name(name: str, max_words: int = 6) -> str:
    """A product name short enough for an image headline, cut at a natural break rather
    than mid-word ("3 Piece Printed Cotton Linen Suit with Dupatta" -> "...Linen Suit")."""
    base = re.split(r"\s+(?:with|for|in|by)\s+|\s+[-|–—:]\s+|\s*\(", name, maxsplit=1, flags=re.I)[0].strip() or name
    words = base.split()
    return " ".join(words[:max_words]) if len(words) > max_words else base


def product_angle(kit: BrandKit, slot: Slot, p: Product) -> tuple[str, str]:
    """(image headline, the idea in one sentence): what every platform version of a post shares."""
    name, brand = short_name(p.name), kit.name
    coll = f" from our {p.category} collection" if p.category else ""
    fashion = "fashion" in kit.industry.lower()
    pillar = slot.pillar.lower()
    if slot.format == "carousel":
        n = len(slot.slide_products) + 1
        return (f"{n} pieces worth a closer look" if fashion else f"{n} favourites from {brand}",
                f"A few favourites from {brand}, starting with the {name}{coll}")
    if "behind" in pillar:
        return f"The making of the {name}", f"Every detail of the {name}{coll} was chosen on purpose"
    if "customer" in pillar:
        return "Everyone's asking about this one", f"The {name}{coll} is the piece people keep asking us about"
    if "tip" in pillar:
        return (f"How to wear the {name}" if fashion else f"Getting the most from the {name}",
                f"Keep everything else simple and let the {name}{coll} lead")
    return f"New in: {name}", f"The {name}{coll} is new at {brand}"


def fallback_product_copy(kit: BrandKit, slot: Slot, p: Product) -> dict:
    """Template copy for a post that features one real product, written for its platform."""
    headline, idea = product_angle(kit, slot, p)
    price = f" {p.price}." if p.price else ""
    link = shop_link(kit, p)
    carousel = slot.format == "carousel"
    if slot.platform is Platform.INSTAGRAM:
        close = "Swipe to see them all, then tell us your favourite." if carousel else "Save this post for later."
        caption, cta = f"{idea}.{price}\n\n{close}", "Shop via the link in bio"
    elif slot.platform is Platform.FACEBOOK:
        close = "Which one would you pick?" if carousel else "Have you seen it in person yet? Tell us in the comments."
        caption, cta = f"{idea}.{price} {close}", (f"Shop it here: {link}" if link else f"Shop {kit.name} online")
    elif slot.platform is Platform.LINKEDIN:
        close = ("We put a few favourites from the collection together. Swipe through and tell us which you'd choose."
                 if carousel else "We'd love to hear what you think of it.")
        caption = f"What's new at {kit.name}: {idea[0].lower()}{idea[1:]}.{price}\n\n{close}"
        cta = f"See the collection: {link}" if link else f"Find {kit.name} online"
    else:
        caption, cta = f"{idea}.{price}", link or kit.name
    return {"headline": headline[:60], "caption": caption, "cta": cta}


def adapt_to_platform(kit: BrandKit, platform: Platform, caption: str) -> tuple[str, str]:
    """Give generic (non-product) copy each platform's own shape and call to action."""
    site = (kit.website_url or "").split("//")[-1].strip("/")
    if platform is Platform.X:
        return caption.split(". ")[0].rstrip(".") + ".", site or kit.name
    if platform is Platform.LINKEDIN:
        return f"From the {kit.name} team: {caption}\n\nWe'd love to hear how you approach this.", (f"Learn more: {site}" if site else "")
    if platform is Platform.FACEBOOK:
        return f"{caption} What do you think? Tell us in the comments.", ("Visit us today" if kit.location else f"Visit {site}" if site else "")
    return f"{caption}\n\nSave this for later.", ("Visit us today" if kit.location else "Learn more at the link in bio")


def fallback_copy(kit: BrandKit, slot: Slot) -> dict:
    """Template copy for demo mode (no API key) or failed batches. Deliberately written in
    the generic 'raw LLM draft' style so the humanizer has something to fix in demos."""
    if slot.product:
        return fallback_product_copy(kit, slot, slot.product)
    props = [p.strip().rstrip(".") for p in kit.value_props if p.strip()] or [kit.tagline or kit.name]
    vp = props[slot.day % len(props)]
    # Short value props scraped from menus/nav ("Kale Caesar") are products; longer ones are claims.
    is_product = len(vp.split()) <= 4
    thing = f"our {vp}" if is_product and vp.lower() != kit.name.lower() else "what we do"
    claim = vp if not is_product else (kit.tagline or f"{kit.name} keeps things simple")
    name, industry = kit.name, (kit.industry or "small business").lower()
    where = f" in {kit.location.split(',')[0]}" if kit.location else ""
    trend = f" Have you seen the news: “{slot.trend.title.rstrip('.')}”? Here's our take." if slot.trend else ""
    variants = {
        "Behind the Scenes": [
            ("Meet the team behind the magic",
             f"In today's fast-paced world, it is important to know who you are working with. Every day at {name}{where} starts early, and {thing} gets the same care whether it's the first order or the fiftieth.{trend}"),
            ("How we actually do it",
             f"People ask how we keep {thing} consistent. Honestly? Boring routines, checked twice. {claim}.{trend}"),
            (f"A morning at {name}"[:40],
             f"Before the doors open at {name}, there's a checklist nobody sees. It's why {thing} turns out the way it does.{trend}"),
        ],
        "Customer Wins": [
            ("Real results, real customers",
             f"Our customers do not just get a service, they get people who remember their name. {claim}. That's why so many come back to {name}.{trend}"),
            ("What regulars keep telling us",
             f"The nicest thing we heard this week? “I keep coming back for {thing}.” We'll take it.{trend}"),
            ("Why people choose us",
             f"No gimmicks, just {thing} done properly. {claim}.{trend}"),
        ],
        "Quick Tips": [
            (f"One {industry} tip for this week"[:60],
             f"Quick tip from the {name} team: start small, stay consistent, and ask questions early. It works in {industry} and pretty much everywhere else.{trend}"),
            ("Save this for later",
             f"Getting the most out of {thing}: ask what's freshest, try one new thing a month, and tell us what you think. We read every message.{trend}"),
            ("The mistake we see most",
             f"The most common {industry} mistake? Trying to do everything at once. Pick one thing and do it well. That's how we built {name}.{trend}"),
        ],
        "Offers & News": [
            (f"New at {name}"[:40],
             f"Exciting news! We've been working on {thing} and it's finally ready. Come and see what's new at {name}{where}.{trend}"),
            ("This week only",
             f"Something new this week at {name}: {thing}, done our way. Ask us about it next time you're in.{trend}"),
            ("You asked, we listened",
             f"You asked for more of {thing}, so that's exactly what we did. Thank you for the ideas, keep them coming.{trend}"),
        ],
    }
    options = variants.get(slot.pillar, variants["Customer Wins"])
    headline, caption = options[slot.day % len(options)]
    if slot.format == "carousel":
        headline = f"{min(4, len(props)) + 1} things to know about {name}"[:60]
        caption = f"Swipe through for a few things we wish more people knew about {industry}. {caption}"
    caption, cta = adapt_to_platform(kit, slot.platform, caption)
    return {"headline": headline, "caption": caption, "cta": cta}
