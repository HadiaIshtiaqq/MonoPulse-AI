"""Agent 3: Strategy & copywriting (Nemotron 3 Ultra).

One Ultra call builds the campaign strategy; the calendar is then split into batches
that are written concurrently so a 30-day package stays fast.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, replace

from collections import Counter
from datetime import date, timedelta

from .. import config
from ..llm import LLMError, router
from ..scraper.products import looks_like_menu, strip_codes
from ..schemas import BrandKit, CampaignStrategy, ContentPillar, Platform, Product, TrendItem
from . import calendar, occasions, variety
from .calendar import COUNTRY_NAMES
from .playbooks import TERMS, WHO, amount, brand_facts, join_words, playbook_for, playbook_key, tidy_price

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
    kind: str = "spotlight"  # the post type (see variety.KIND_LABELS)
    compare: Product | None = None  # second product of a "this or that" duo
    nth: int = 0  # how many earlier ideas had this type: picks the wording variant
    occasion: str = ""  # a greeting post's occasion, e.g. "Eid al-Fitr"


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
Plan a content campaign for the brand below. Base it on the BRAND FACTS: what it actually sells, its product lines,
prices and sales, who it sells to and where. Be specific to this brand; nothing in the plan should fit any other business.
Plan the weekly themes around the SEASONAL MOMENTS listed (with their dates) where they fit the brand.
Use a live trend only if it is clearly about this brand's products, customers, industry or country; ignore the rest.
Never invent facts, awards, numbers or offers.
Return JSON:
{
  "positioning": "one sentence: who it's for, what it does, why it's different",
  "audience": "one sentence describing the ideal customer specifically",
  "voice_rules": ["5 concrete do/don't rules for how this brand writes"],
  "pillars": [{"name": "2-3 words", "description": "one sentence"}],   // exactly 4 pillars
  "weekly_themes": ["one theme per week, each tied to a trend or season where possible"]
}"""


def facts_brief(kit: BrandKit, start: date, days: int) -> str:
    f = brand_facts(kit)
    book = playbook_for(kit.industry)
    lines = [
        f"Sells: {book.category}" + (f" (lines: {', '.join(f.lines)})" if f.lines else ""),
        f"For: {f.who or 'not stated'}" + (f", in {f.country}" if f.country else ""),
        f"Prices: {f.price_range}" if f.price_range else "",
        f"On sale now: up to {f.best_discount}% off" if f.best_discount else "",
        f"What this audience wants: {book.need}",
    ]
    moments = calendar.upcoming(kit.country, start, days)
    return "\n".join(x for x in lines if x) + "\n\nSEASONAL MOMENTS:\n" + (
        "\n".join(f"- {m.label()}" for m in moments) or "- none in this window")


async def build_strategy(kit: BrandKit, trends: list[TrendItem], weeks: int, research: str = "",
                         start: date | None = None) -> CampaignStrategy:
    start = start or date.today()
    trends = relevant_trends(kit, trends)
    if router.enabled:
        try:
            user = (f"BRAND:\n{brand_brief(kit)}\n\nBRAND FACTS:\n{facts_brief(kit, start, weeks * 7)}\n\n"
                    f"LIVE TRENDS:\n{trend_brief(trends)}\n\n")
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
    return fallback_strategy(kit, trends, weeks, start)


NOT_NEWS = re.compile(r"official (?:online )?(?:store|site|website)|shop now|buy online|\| ?home\b|sign in|log in", re.I)
# Corporate and financial stories are news about a company, not something its customers want to see.
CORPORATE = re.compile(r"\bstock\b|\bshares?\b|earnings|investor|\bipo\b|valuation|revenue|quarterly|lawsuit|layoffs?|"
                       r"\bhires?\b|appoints?|chief \w+ officer|\bceo\b|\bcfo\b|acquisition|merger", re.I)
GENERIC_NAME_WORDS = {"the", "and", "shop", "store", "online", "official", "company", "brand", "group", "studio", "bakery", "cafe",
                      "order", "orders", "special", "cards", "items", "more", "best", "sellers", "ready", "sale", "home", "with"}


def relevant_trends(kit: BrandKit, trends: list[TrendItem], limit: int = 8) -> list[TrendItem]:
    """Keep only news about this brand, its product lines or what it sells, best first.

    Broad industry words ("food", "fashion") alone aren't enough, since every market report uses
    them; a story needs the brand, one of its lines, or a specific word for what it sells
    ("bread", "sandal", "kurta"), or a broad word plus the brand's country."""
    broad, specific = TERMS.get(playbook_key(kit.industry), ((), ()))
    own = {w for w in re.findall(r"[a-z]{4,}", " ".join([*kit.offerings, *kit.keywords[:6]]).lower())} - GENERIC_NAME_WORDS
    country = COUNTRY_NAMES.get(kit.country.upper(), "").removeprefix("the ").lower()
    name_words = [w for w in re.findall(r"[a-z]{4,}", kit.name.lower()) if w not in GENERIC_NAME_WORDS]
    lines = [l.lower() for l in brand_facts(kit).lines if len(l) >= 4 and l.lower() not in {"ready to wear", "best sellers"}]
    scored = []
    for t in trends:
        text = f"{t.title} {t.snippet}".lower()
        if NOT_NEWS.search(t.title) or CORPORATE.search(t.title):
            continue
        brand = any(re.search(rf"\b{re.escape(w)}\b", text) for w in name_words)
        line = any(l in text for l in lines)
        exact = any(re.search(rf"\b{re.escape(w)}", text) for w in (*specific, *own))
        general = any(re.search(rf"\b{re.escape(w)}", text) for w in broad)
        local = bool(country) and country in text
        score = 4 * brand + 3 * line + 2 * exact + general + local
        if score >= 2:
            scored.append((score, t))
    scored.sort(key=lambda x: -x[0])  # stable: equal scores keep search order
    return [t for _, t in scored[:limit]]


def fallback_strategy(kit: BrandKit, trends: list[TrendItem], weeks: int, start: date | None = None) -> CampaignStrategy:
    """A brand-specific plan without a model: the industry playbook filled with the brand's facts."""
    start = start or date.today()
    book = playbook_for(kit.industry)
    f = brand_facts(kit)
    pillars = [ContentPillar(name=n, description=d.format(brand=kit.name)) for n, d in book.pillars]

    if f.lines:
        offer = f"{book.category} ({join_words(f.lines[:3])})"
    elif kit.offerings:
        offer = join_words([in_sentence(o).lower() for o in kit.offerings[:3]])
    else:
        offer = book.category
    where = f" across {f.country}" if f.country else (f" in {kit.location}" if kit.location else "")
    positioning = f"{kit.name} offers {offer}" + (f" for {f.who}" if f.who else "") + where
    if f.price_range:
        positioning += f", priced {f.price_range}"
    if kit.tagline:
        positioning += f". {kit.tagline.rstrip('.…')}"
    who = f.who or WHO.get(playbook_key(kit.industry), "customers")
    audience = (f"{who[0].upper()}{who[1:]}" + (f" in {f.country}" if f.country else "")
                + f" who want {book.need}" + (". Many are waiting for a sale" if f.best_discount else "") + ".")

    voice = list(book.voice)
    if f.best_discount:
        voice.append(f"When something is on sale, say how much: up to {f.best_discount}% off right now")

    themes = weekly_themes(kit, pillars, start, weeks, relevant_trends(kit, trends))
    return CampaignStrategy(positioning=positioning + ".", audience=audience, voice_rules=voice[:6], pillars=pillars, weekly_themes=themes)


def weekly_themes(kit: BrandKit, pillars: list[ContentPillar], start: date, weeks: int, trends: list[TrendItem]) -> list[str]:
    """One theme per week: the seasonal moment it builds up to, else a relevant trend, else a pillar."""
    moments = calendar.upcoming(kit.country, start, weeks * 7)
    seasons = iter(calendar.ongoing(kit.country, start))
    themes: list[str] = []
    used: set = set()
    trend_iter = iter(trends)
    for w in range(weeks):
        week_start, week_end = start + timedelta(days=7 * w), start + timedelta(days=7 * w + 13)
        moment = next((m for m in moments if week_start <= m.day <= week_end and m not in used), None)
        if moment:
            used.add(moment)
            lead = "Build-up to " if moment.day > week_start + timedelta(days=6) else ""
            themes.append(f"{lead}{moment.label()}")
            continue
        season = next(seasons, None) if w == 0 else None
        if season:
            themes.append(f"{season.name}: what's new this season")
            continue
        trend = next(trend_iter, None)
        themes.append(f"In the news: {trend.title[:70]}" if trend else pillars[w % len(pillars)].name)
    return themes


# --------------------------------------------------------------------------- slots


def varied(products: list[Product]) -> list[Product]:
    """Interleave products so the same item name (often a generic type like "3-Piece Set")
    doesn't run several posts in a row: every differently named product comes up before any
    name repeats. The same product listed twice (same name and photo) is kept once."""
    groups: dict[str, list[Product]] = {}
    seen: set[tuple[str, str]] = set()
    for p in products:
        key = re.sub(r"[^a-z0-9]+", " ", short_name(p.name).lower()).strip() or p.name.lower()
        if (key, p.image_url or p.url) in seen:
            continue
        seen.add((key, p.image_url or p.url))
        groups.setdefault(key, []).append(p)
    out: list[Product] = []
    while any(groups.values()):
        for key in list(groups):
            if groups[key]:
                out.append(groups[key].pop(0))
    return out


def greeting_days(country: str, start: date | None, days: int) -> dict[int, str]:
    """Holidays inside the campaign that deserve a greeting on the day: {day offset: name}."""
    if not start:
        return {}
    out: dict[int, str] = {}
    for mo in calendar.upcoming(country, start, days, lead=0):
        o = occasions.find(mo.name)
        if mo.kind == "holiday" and o and o.key != "sale" and 0 <= (mo.day - start).days < days:
            out.setdefault((mo.day - start).days, mo.name.replace("Ramadan begins", "Ramadan"))
    return out


def plan_slots(strategy: CampaignStrategy, trends: list[TrendItem], platforms: list[Platform], days: int, per_day: int,
               products: list[Product] | None = None, claims: int = 0, start: date | None = None, country: str = "") -> list[Slot]:
    """One post idea per day (or per_day of them), each in a version for every platform.

    Ideas cycle through post types (spotlight, carousel, this-or-that duo, tip, quote, sale,
    seasonal moment) so the feed doesn't repeat itself. The versions of an idea share its
    type, product, pillar and trend; copy, image size and format are made for each platform
    (a carousel idea is a carousel on Instagram and LinkedIn, a single image elsewhere)."""
    pillars = [p.name for p in strategy.pillars] or ["General"]
    catalogue = varied([p for p in (products or []) if p.image_url] or list(products or []))
    on_sale = [p for p in catalogue if sale_percent(p)]
    platforms = list(dict.fromkeys(platforms))
    themes = [strategy.weekly_themes[min(day // 7, len(strategy.weekly_themes) - 1)] if strategy.weekly_themes else ""
              for day in range(days) for _ in range(per_day)]
    kinds = variety.plan_kinds(len(themes), products=len(catalogue), on_sale=len(on_sale), claims=claims,
                               moments=[theme_moment(t) for t in themes])
    # On Eid, Mother's Day, Independence Day and other holidays, the day's first post is a greeting.
    greetings = {day * per_day: name for day, name in greeting_days(country, start, days).items()}
    for i in greetings:
        if i < len(kinds):
            kinds[i] = "greeting"
    seen: Counter = Counter()
    next_product = next_sale = 0
    last_by_kind: dict[str, str] = {}  # the product each post type featured last time
    slots: list[Slot] = []
    for i, (theme, kind) in enumerate(zip(themes, kinds)):
        day = i // per_day
        pillar = pillars[i % len(pillars)]
        # Roughly every third idea rides a live trend.
        trend = trends[(i // 3) % len(trends)] if trends and i % 3 == 0 else None
        product = compare = None
        extra: tuple[Product, ...] = ()
        if catalogue and kind not in ("quote", "greeting"):
            if kind == "sale":
                product, next_sale = on_sale[next_sale % len(on_sale)], next_sale + 1
            else:
                if len(catalogue) > 1 and catalogue[next_product % len(catalogue)].url == last_by_kind.get(kind):
                    next_product += 1  # the same type twice shouldn't feature the same product
                product, next_product = catalogue[next_product % len(catalogue)], next_product + 1
            last_by_kind[kind] = product.url
            if kind == "duo":
                compare, next_product = catalogue[next_product % len(catalogue)], next_product + 1
            if kind == "carousel" and len(catalogue) > 1:
                extra = tuple(catalogue[(next_product + j) % len(catalogue)] for j in range(min(3, len(catalogue) - 1)))
        # The n-th post of the same type (and, for spotlights, pillar) uses the n-th wording variant.
        key = (kind, pillar if kind == "spotlight" else "")
        nth, seen[key] = seen[key], seen[key] + 1
        for platform in platforms:
            fmt = "carousel" if kind == "carousel" and platform in CAROUSEL_PLATFORMS else "single"
            slots.append(Slot(day=day, platform=platform, pillar=pillar, theme=theme, trend=trend, format=fmt, product=product,
                              slide_products=extra if fmt == "carousel" else (), group=i, kind=kind, compare=compare, nth=nth,
                              occasion=greetings.get(i, "")))
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
Follow each slot's "post_type": a "This or that" post asks people to choose between "product" and "compare_with"; a
"Sale" post leads with the saving; a "Greeting" post warmly wishes people a happy "occasion"
from the brand, with no selling and no product; a "Brand quote" is one short line from the brand's own claims; a "Styling tip" gives
one concrete tip; a "Seasonal moment" ties the product to the weekly theme's date.
No two posts may feel the same: never reuse a headline, never open two captions the same way, and vary the length.
Write each caption in its slot's "caption_shape" (a plain statement, a hook line first, a short fact list, a tiny story,
a closing question, or one punchy line), so neighbouring posts and a post's platform versions read differently.
Return a JSON array, one object per slot, in the same order:
[{"slot": <slot index>, "headline": "<= 7 words for the image overlay", "caption": "...", "cta": "short call to action",
  "slides": [{"headline": "...", "body": "..."}]  // carousel slots only
}]"""


async def write_batch(kit: BrandKit, strategy: CampaignStrategy, slots: list[Slot], offset: int, research: str = "") -> list[dict]:
    slot_desc = []
    for j, s in enumerate(slots):
        entry = {"slot": offset + j, "group": s.group, "platform": s.platform.value, "format": s.format, "pillar": s.pillar,
                 "post_type": variety.KIND_LABELS.get(effective_kind(s), s.kind), "weekly_theme": s.theme,
                 "caption_shape": variety.SHAPE_HINTS[variety.caption_shape(s.group + brand_seed(kit), s.platform.value)]}
        if s.compare:
            entry["compare_with"] = product_brief(s.compare)
        if s.occasion:
            entry["occasion"] = s.occasion
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
    dedupe_headlines(kit, slots, out)
    return out


def dedupe_headlines(kit: BrandKit, slots: list[Slot], copies: list[dict]) -> int:
    """No two posts share an image headline. A repeat (from a model or a template) is replaced
    by the next unused wording variant for that post; returns how many were replaced."""
    used: set[str] = set()
    replaced = 0
    done: dict[tuple[int, str], str] = {}
    for slot, copy in zip(slots, copies):
        key = (slot.group, slot.format)
        if key in done:  # this idea's other platform versions share the decided headline
            copy["headline"] = done[key]
            continue
        head = copy.get("headline", "")
        if variety.normalize(head) in used:
            alt = next((h for h in headline_options(kit, slot) if variety.normalize(h) not in used), "")
            if alt:
                head, replaced = alt, replaced + 1
        copy["headline"] = done[key] = head
        used.add(variety.normalize(head))
    return replaced


def product_slides(products) -> list[dict]:
    slides = []
    for p in products:
        price = price_line(p).strip().rstrip(".")
        body = " · ".join(x for x in (p.category, price) if x)
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
    slides = [{"headline": fit_headline(p), "body": f"Ask about {p if len(p.split()) <= 4 else 'this'} next time you're in, or see more at {site}."}
              for p in props]
    slides.append({"headline": "Save this for later", "body": f"Questions about any of these? Ask the {kit.name} team, we read every message."})
    return slides


def shop_link(kit: BrandKit, p: Product) -> str:
    url = (p.url or kit.website_url or "").split("?")[0]
    return url.split("//")[-1].rstrip("/")


GENERIC_NAME = re.compile(r"^(?:\d+\s*-?\s*(?:pc|pcs|piece|pieces)|unstitched|stitched|ready to wear|rtw|new|sale|basics?)$", re.I)
AUDIENCE_SUFFIX = re.compile(r"^(.+?)\s+[-–—]\s+(men|women|ladies|kids|boys|girls|toddlers?|junior|infants?|unisex)\b", re.I)


def short_name(name: str, max_words: int = 6) -> str:
    """A product name short enough for an image headline, cut at a natural break rather
    than mid-word ("3 Piece Printed Cotton Linen Suit with Dupatta" -> "...Linen Suit").
    Line-and-audience names read naturally: "Power - Men" -> "Power for men"."""
    if name.isupper():  # "DUPATTA" -> "Dupatta": don't shout
        name = name.title()
    m = AUDIENCE_SUFFIX.match(name)
    if m:
        return f"{m.group(1).strip()} for {m.group(2).lower()}"
    parts = re.split(r"\s+[-|–—:]\s+", name, maxsplit=1)
    if len(parts) == 2 and GENERIC_NAME.match(parts[0].strip()) and parts[1].strip():
        # "3 Piece - Embroidered Light Khaddar Suit": the part before the dash is just a type,
        # the part after tells products apart.
        name = parts[1].strip()
    base = re.split(r"\s+(?:with|for|in|by)\s+|\s+[-|–—:]\s+|\s*\(", name, maxsplit=1, flags=re.I)[0].strip() or name
    words = base.split()
    return " ".join(words[:max_words]) if len(words) > max_words else base


def pillar_angle(pillar: str) -> str:
    """Which angle a spotlight takes, from its content pillar's name."""
    p = pillar.lower()
    if any(w in p for w in ("behind", "craft", "making", "inside", "kitchen", "made")):
        return "craft"
    if any(w in p for w in ("comfort", "fit")):
        return "comfort"
    if any(w in p for w in ("customer", "review", "regular", "result", "stor", "win", "member")):
        return "customer"
    if any(w in p for w in ("tip", "style", "how", "routine", "guide", "idea")):
        return "tip"
    return "new"


def is_wearable(kit: BrandKit) -> bool:
    return any(w in kit.industry.lower() for w in ("fashion", "footwear", "jewel", "apparel"))


def effective_kind(slot: Slot) -> str:
    # A carousel idea's single-image versions (X, Facebook) are spotlights of its first product.
    return "spotlight" if slot.kind == "carousel" and slot.format != "carousel" else slot.kind


def collection_name(p: Product) -> str:
    """"Khaas: Floral Radiance" -> "Floral Radiance": the part of a category that names the collection."""
    return (p.category or "").rsplit(":", 1)[-1].strip()


def display_name(kit: BrandKit, p: Product) -> str:
    """The name a post calls a product. When several products share a generic name ("3-Piece
    Co-ord Set"), the collection tells them apart: "Floral Radiance 3-Piece"."""
    name = short_name(p.name)
    twins = sum(short_name(x.name).lower() == name.lower() for x in kit.products)
    coll = collection_name(p)
    if twins > 1 and len(coll.split()) >= 2 and coll.lower() not in name.lower():
        first = name.split()[0]
        return f"{coll} {first}" if re.search(r"\d", first) else f"{coll} {name}"
    return name


def headline_fields(kit: BrandKit, slot: Slot, p: Product) -> dict:
    name = display_name(kit, p)
    named_coll = collection_name(p) and collection_name(p).lower() in name.lower()
    return {
        "name": name, "coll": f" from our {p.category} collection" if p.category and not named_coll else "", "brand": kit.name,
        "pct": sale_percent(p), "price": tidy_price(p.price), "moment": theme_moment(slot.theme) or "the season",
        "n": len(slot.slide_products) + 1, "a": name, "b": display_name(kit, slot.compare) if slot.compare else "",
    }


def headline_options(kit: BrandKit, slot: Slot) -> list[str]:
    """Every headline this post could use, best first: its own wording family from its variant
    onwards, then other families that name its product. Used to replace a repeated headline."""
    out: list[str] = []
    for bump in range(1, 8):
        out.append(fallback_copy(kit, replace(slot, nth=slot.nth + bump))["headline"])
    p = slot.product
    if p:
        fields = headline_fields(kit, slot, p)
        for family in ("new", "craft", "customer", "tip" if is_wearable(kit) else "tip_other", "comfort"):
            out += [h.format(**fields) for h in variety.PRODUCT_HEADLINES[family] if "{name}" in h]
    return [fit_headline(h) for h in dict.fromkeys(out)]


def product_angle(kit: BrandKit, slot: Slot, p: Product) -> tuple[str, str]:
    """(image headline, the idea in one sentence): what every platform version of a post shares.
    The n-th post of a type uses the n-th wording variant, so phrasing doesn't repeat."""
    kind = effective_kind(slot)
    angle = pillar_angle(slot.pillar)
    family = variety.headline_family(kind, angle, is_wearable(kit))
    fields = headline_fields(kit, slot, p)
    idea_family = family if family in variety.PRODUCT_IDEAS else "tip"
    n = slot.nth + brand_seed(kit)
    headline = variety.pick(variety.PRODUCT_HEADLINES[family], n).format(**fields)
    idea = variety.pick(variety.PRODUCT_IDEAS[idea_family], n).format(**fields)
    return headline, idea


def sale_percent(p: Product) -> int:
    now, was = amount(p.price), amount(p.was_price)
    return round(100 * (1 - now / was)) if was > now > 0 else 0


def price_line(p: Product) -> str:
    if not p.price:
        return ""
    if p.was_price and sale_percent(p):
        return f" Now {tidy_price(p.price)}, was {tidy_price(p.was_price)}."
    return f" {tidy_price(p.price)}."


def brand_seed(kit: BrandKit) -> int:
    """Where this brand starts in every wording rotation, so two brands' campaigns don't open
    with the same headlines and captions ("3 picks worth a closer look" for everyone)."""
    return sum(map(ord, kit.name or "")) % 97


def closer(slot: Slot, kind: str, category: str, seed: int = 0) -> str:
    platform = slot.platform.value
    options = (variety.CLOSERS.get(f"{platform}_{kind}") or (variety.CLOSERS.get(f"{platform}_carousel") if slot.format == "carousel" else None)
               or variety.CLOSERS.get(platform, [""]))
    # Rotate by idea, so consecutive posts on a platform end differently.
    return variety.pick(options, slot.group + seed).format(category=category)


def flavour(kit: BrandKit) -> str:
    industry = (kit.industry or "").lower()
    return "wear" if is_wearable(kit) else "food" if "food" in industry or "restaurant" in industry else "other"


def shaped_caption(kit: BrandKit, slot: Slot, p: Product, headline: str, idea: str, price: str, shape: str) -> str:
    """The post's idea told in one of several shapes (see variety.CAPTION_SHAPES)."""
    # A shape comes round every len(CAPTION_SHAPES) posts: count its uses, so its lines rotate too.
    f = flavour(kit)
    g = (slot.group + brand_seed(kit)) // len(variety.CAPTION_SHAPES) + variety.PLATFORM_ORDER.index(slot.platform.value) + brand_seed(kit)
    price = price.strip()
    tail = f" {price}" if price else ""
    if shape == "hook":
        return f"{variety.pick(variety.HOOKS[f], g)}\n\n{idea}.{tail}"
    if shape == "details":
        site = (kit.website_url or "").split("//")[-1].split("/")[0].removeprefix("www.")
        city = (kit.location or "").split(",")[0].strip()
        facts = [f"From the {collection_name(p)} collection" if collection_name(p) and collection_name(p).lower() not in display_name(kit, p).lower() else "",
                 price.rstrip("."), f"Online at {site}" if site else f"In store in {city}" if city else ""]
        return display_name(kit, p) + "\n" + "\n".join(f"– {x}" for x in facts if x)
    if shape == "story":
        return f"{variety.pick(variety.STORY_OPENERS[f], g)} {idea}.{tail}"
    if shape == "question":
        asks = variety.CLOSERS["instagram_duo"] if effective_kind(slot) == "duo" else variety.QUESTIONS[f]
        return f"{idea}.{tail} {variety.pick(asks, g)}"
    if shape == "short":
        end = "" if headline.endswith(("?", "!", ".")) else "."
        return f"{headline}{end}{tail}"
    return f"{idea}.{tail}"


def fallback_product_copy(kit: BrandKit, slot: Slot, p: Product) -> dict:
    """Template copy for a post that features one real product, written for its platform, in a
    shape that changes from post to post so captions never read like one template."""
    headline, idea = product_angle(kit, slot, p)
    kind = effective_kind(slot)
    if kind == "duo" and slot.compare:
        price = "".join(f" {display_name(kit, x)}: {tidy_price(x.price)}." for x in (p, slot.compare) if x.price)
    else:
        price = price_line(p)
    link = shop_link(kit, p)
    close = closer(slot, kind, playbook_for(kit.industry).category, brand_seed(kit))
    cta_family = "instagram" if slot.platform is Platform.INSTAGRAM else "linkedin" if slot.platform is Platform.LINKEDIN else "linked"
    cta = variety.pick(variety.CTAS[cta_family], slot.group + brand_seed(kit)).format(link=link) if (link or cta_family == "instagram") else f"Shop {kit.name} online"
    shape = variety.caption_shape(slot.group + brand_seed(kit), slot.platform.value)
    if kind == "duo" and shape == "details":
        shape = "question"  # a fact list doesn't fit a "pick one" post
    if slot.platform is Platform.X:
        shape = "short" if shape in ("details", "story", "hook", "statement") else shape
        return {"headline": fit_headline(headline), "caption": shaped_caption(kit, slot, p, headline, idea, price, shape), "cta": link or kit.name}
    body = shaped_caption(kit, slot, p, headline, idea, price, shape)
    if slot.platform is Platform.LINKEDIN and shape == "statement":
        body = f"What's new at {kit.name}: {idea[0].lower()}{idea[1:]}.{price}"
    if shape == "question":
        caption = body  # it already ends by asking the reader something
    elif slot.platform is Platform.FACEBOOK and shape != "details":
        caption = f"{body} {close}"
    else:
        caption = f"{body}\n\n{close}"
    return {"headline": fit_headline(headline), "caption": caption, "cta": cta}


def adapt_to_platform(kit: BrandKit, slot: Slot, caption: str, kind: str = "") -> tuple[str, str]:
    """Give generic (non-product) copy each platform's own shape, ending and call to action."""
    site = (kit.website_url or "").split("//")[-1].strip("/")
    close = closer(slot, kind, playbook_for(kit.industry).category, brand_seed(kit))
    if slot.platform is Platform.X:
        return caption.split(". ")[0].rstrip(".") + ".", site or kit.name
    if slot.platform is Platform.LINKEDIN:
        return f"From the {kit.name} team: {caption}\n\n{close}", (f"Learn more: {site}" if site else "")
    if slot.platform is Platform.FACEBOOK:
        return f"{caption} {close}", ("Visit us today" if kit.location else f"Visit {site}" if site else "")
    return f"{caption}\n\n{close}", ("Visit us today" if kit.location else "Learn more at the link in bio")


def in_sentence(phrase: str) -> str:
    """How a heading reads mid-sentence: "SPECIAL ORDER CAKES" / "Special order cakes" -> "special
    order cakes"; title-cased names ("Gift Cards") keep their capitals."""
    if phrase.isupper():
        return phrase.lower()
    words = phrase.split()
    return phrase[0].lower() + phrase[1:] if len(words) > 1 and words[1][:1].islower() else phrase


def theme_moment(theme: str) -> str:
    """"Build-up to 11.11 sale (11 Nov)" -> "11.11 sale"; "" when the week isn't about a date."""
    m = re.match(r"^(?:Build-up to )?(.+?) \((?:expected )?\d{1,2} \w{3}\)$", theme or "")
    return m.group(1) if m else ""


TRAILING_SMALL_WORDS = {"on", "at", "the", "for", "and", "with", "of", "to", "in", "a", "an", "our", "your", "by", "from", "featuring"}


def fit_headline(text: str, limit: int = 60) -> str:
    """Trim an image headline to whole words (never "…offering unsti")."""
    text = strip_codes(" ".join(text.split()))
    text = re.sub(r"\b(the|a|our)\s+(?:the|a)\b", r"\1", text, flags=re.I)  # "from the The Majesty"
    if len(text) <= limit:
        return text
    words = text[: limit + 1].split()[:-1] or [text[:limit]]
    while len(words) > 2 and words[-1].lower().strip(",.;:") in TRAILING_SMALL_WORDS:
        words.pop()
    out = " ".join(words)
    head, comma, tail = out.rpartition(",")
    if comma and len(tail.split()) <= 2 and len(head.split()) >= 3:
        out = head  # "...fashion, offering" -> "...fashion"
    return out.rstrip(",;:-–—")


def short_claim(text: str, max_words: int = 9) -> str:
    """A brand claim short enough for a quote graphic, cut at a comma or a full word, never
    ending on a dangling "on" / "the" / "and"."""
    words = text.rstrip(".…").split()
    if len(words) <= max_words:
        return " ".join(words)
    cut = " ".join(words[:max_words])
    if "," in cut:
        cut = cut.rsplit(",", 1)[0]
    parts = cut.split()
    while len(parts) > 3 and parts[-1].lower().strip(",") in TRAILING_SMALL_WORDS:
        parts.pop()
    return " ".join(parts)


def brand_claims(kit: BrandKit) -> list[str]:
    """Everything the brand says about itself, each said once: value props, then the tagline."""
    out = [c.rstrip(".…") for c in kit.value_props if c.strip()] + ([kit.tagline.rstrip(".…")] if kit.tagline else [])

    return list(dict.fromkeys(c for c in out if not looks_like_menu(c)))


def quote_copy(kit: BrandKit, slot: Slot) -> dict:
    claims = brand_claims(kit)
    claim = claims[slot.nth % len(claims)]
    caption, cta = adapt_to_platform(kit, slot, f"{claim[0].upper()}{claim[1:]}.", "quote")
    headline = fit_headline(short_claim(claim))
    return {"headline": headline[:1].upper() + headline[1:], "caption": caption, "cta": cta}


GREETING_ENDINGS = {
    "facebook": ["Tag someone you're celebrating with.", "Who are you celebrating with today?"],
    "linkedin": ["Thank you to our customers and our team.", "Grateful to everyone who's part of our story."],
}


def greeting_copy(kit: BrandKit, slot: Slot) -> dict:
    """A warm greeting on the day itself: no selling, nothing claimed about the brand."""
    o = occasions.find(slot.occasion) or occasions.OCCASIONS["new_year"]
    name = slot.occasion
    headline = occasions.greeting(o, kit.name, name)
    caption = occasions.greeting_caption(o, kit.name, name)
    if slot.platform is Platform.X:
        return {"headline": headline, "caption": f"{headline} from all of us at {kit.name}.", "cta": ""}
    ending = variety.pick(GREETING_ENDINGS.get(slot.platform.value, [""]), slot.group)
    return {"headline": headline, "caption": f"{caption}\n\n{ending}".strip(), "cta": ""}


def fallback_copy(kit: BrandKit, slot: Slot) -> dict:
    """Template copy for demo mode (no API key) or failed batches, built only from what the
    brand's site says: its products, offerings and claims. Nothing is invented."""
    kind = effective_kind(slot)
    if kind == "greeting":
        return greeting_copy(kit, slot)
    if kind == "quote" and (kit.value_props or kit.tagline):
        return quote_copy(kit, slot)
    if slot.product:
        return fallback_product_copy(kit, slot, slot.product)
    name = kit.name
    offerings = [in_sentence(o) for o in kit.offerings] or [playbook_for(kit.industry).category]
    item = offerings[slot.group % len(offerings)]
    Item = item[0].upper() + item[1:]
    claims = [c.rstrip(".…") for c in kit.value_props if c.strip()] or ([kit.tagline.rstrip(".…")] if kit.tagline else [])
    claim = f" {claims[slot.group % len(claims)]}." if claims else ""
    food = "food" in kit.industry.lower()
    moment = theme_moment(slot.theme)
    fields = {"item": item, "brand": name, "moment": moment or "the season", "n": min(4, len(claims) or 1) + 1}
    H = variety.GENERIC_HEADLINES
    if slot.format == "carousel":
        headline = variety.pick(H["carousel"], slot.nth + brand_seed(kit))
        caption = f"A few things worth knowing about {name}, from {item} to how we work. Swipe through.{claim}"
    elif kind == "moment" and moment:
        headline = variety.pick(H["moment"], slot.nth + brand_seed(kit))
        caption = f"{moment} is coming up. Plan ahead with {item} from {name}.{claim}"
    elif kind == "question":
        headline = variety.pick(H["question"], slot.nth + brand_seed(kit))
        caption = (f"Tell us: what do you always get at {name}? {Item}, or something else?" if food
                   else f"Tell us: what brings you to {name}? {Item}, or something else?") + claim
    elif kind == "tip":
        headline = variety.pick(H["tip"], slot.nth + brand_seed(kit))
        caption = f"Good to know before you visit {name}:{claim or ' ask us anything.'}"
    elif pillar_angle(slot.pillar) == "craft":
        headline = variety.pick(H["craft"], slot.nth + brand_seed(kit))
        caption = f"A look at how {name} makes {item}.{claim}"
    else:
        headline = variety.pick(H["spotlight" if food else "spotlight_other"], slot.nth + brand_seed(kit))
        caption = f"{Item} at {name}.{claim}"
    caption, cta = adapt_to_platform(kit, slot, caption, kind)
    return {"headline": fit_headline(headline.format(**fields)), "caption": caption, "cta": cta}
