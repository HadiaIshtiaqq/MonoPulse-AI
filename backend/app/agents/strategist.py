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

from datetime import date, timedelta

from .. import config
from ..llm import LLMError, router
from ..schemas import BrandKit, CampaignStrategy, ContentPillar, Platform, Product, TrendItem
from . import calendar
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
    slides = [{"headline": p[:60], "body": f"Ask about {p if len(p.split()) <= 4 else 'this'} next time you're in, or see more at {site}."}
              for p in props]
    slides.append({"headline": "Save this for later", "body": f"Questions about any of these? Ask the {kit.name} team, we read every message."})
    return slides


def shop_link(kit: BrandKit, p: Product) -> str:
    url = (p.url or kit.website_url or "").split("?")[0]
    return url.split("//")[-1].rstrip("/")


AUDIENCE_SUFFIX = re.compile(r"^(.+?)\s+[-–—]\s+(men|women|ladies|kids|boys|girls|toddlers?|junior|infants?|unisex)\b", re.I)


def short_name(name: str, max_words: int = 6) -> str:
    """A product name short enough for an image headline, cut at a natural break rather
    than mid-word ("3 Piece Printed Cotton Linen Suit with Dupatta" -> "...Linen Suit").
    Line-and-audience names read naturally: "Power - Men" -> "Power for men"."""
    m = AUDIENCE_SUFFIX.match(name)
    if m:
        return f"{m.group(1).strip()} for {m.group(2).lower()}"
    base = re.split(r"\s+(?:with|for|in|by)\s+|\s+[-|–—:]\s+|\s*\(", name, maxsplit=1, flags=re.I)[0].strip() or name
    words = base.split()
    return " ".join(words[:max_words]) if len(words) > max_words else base


def product_angle(kit: BrandKit, slot: Slot, p: Product) -> tuple[str, str]:
    """(image headline, the idea in one sentence): what every platform version of a post shares."""
    name, brand = short_name(p.name), kit.name
    coll = f" from our {p.category} collection" if p.category else ""
    industry = kit.industry.lower()
    wearable = any(w in industry for w in ("fashion", "footwear", "jewel", "apparel"))
    pillar = slot.pillar.lower()
    sale = sale_percent(p)
    if slot.format == "carousel":
        n = len(slot.slide_products) + 1
        return (f"{n} picks worth a closer look" if wearable else f"{n} favourites from {brand}",
                f"A few favourites from {brand}, starting with the {name}{coll}")
    if sale and any(w in pillar for w in ("offer", "sale", "occasion", "special", "launch")):
        return f"{sale}% off: {name}", f"The {name}{coll} is {sale}% off right now"
    if any(w in pillar for w in ("behind", "craft", "making", "inside", "kitchen", "made")):
        return f"The making of the {name}", f"Every detail of the {name}{coll} was chosen on purpose"
    if any(w in pillar for w in ("comfort", "fit")):
        return f"Made to be worn all day: {name}", f"The {name}{coll} is built for comfort from the first wear"
    if any(w in pillar for w in ("customer", "review", "regular", "result", "stor", "win")):
        return "Everyone's asking about this one", f"The {name}{coll} is the one people keep asking us about"
    if any(w in pillar for w in ("tip", "style", "how", "routine", "guide", "idea")):
        return (f"How to wear the {name}" if wearable else f"Getting the most from the {name}",
                f"Keep everything else simple and let the {name}{coll} lead")
    if sale:
        return f"{sale}% off: {name}", f"The {name}{coll} is {sale}% off right now"
    return f"New in: {name}", f"The {name}{coll} is new at {brand}"


def sale_percent(p: Product) -> int:
    now, was = amount(p.price), amount(p.was_price)
    return round(100 * (1 - now / was)) if was > now > 0 else 0


def price_line(p: Product) -> str:
    if not p.price:
        return ""
    if p.was_price and sale_percent(p):
        return f" Now {tidy_price(p.price)}, was {tidy_price(p.was_price)}."
    return f" {tidy_price(p.price)}."


def fallback_product_copy(kit: BrandKit, slot: Slot, p: Product) -> dict:
    """Template copy for a post that features one real product, written for its platform."""
    headline, idea = product_angle(kit, slot, p)
    price = price_line(p)
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
        return f"From the {kit.name} team: {caption}\n\nWe'd love to hear what you think.", (f"Learn more: {site}" if site else "")
    if platform is Platform.FACEBOOK:
        return f"{caption} What do you think? Tell us in the comments.", ("Visit us today" if kit.location else f"Visit {site}" if site else "")
    return f"{caption}\n\nSave this for later.", ("Visit us today" if kit.location else "Learn more at the link in bio")


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


def fallback_copy(kit: BrandKit, slot: Slot) -> dict:
    """Template copy for demo mode (no API key) or failed batches, built only from what the
    brand's site says: its products, offerings and claims. Nothing is invented."""
    if slot.product:
        return fallback_product_copy(kit, slot, slot.product)
    name = kit.name
    book_category = playbook_for(kit.industry).category
    offerings = [in_sentence(o) for o in kit.offerings] or [book_category]
    item = offerings[slot.group % len(offerings)]
    Item = item[0].upper() + item[1:]
    claims = [c.rstrip(".…") for c in kit.value_props if c.strip()] or ([kit.tagline.rstrip(".…")] if kit.tagline else [])
    claim = f" {claims[slot.group % len(claims)]}." if claims else ""
    food = "food" in kit.industry.lower()
    pillar = slot.pillar.lower()
    moment = theme_moment(slot.theme)
    if slot.format == "carousel":
        headline = f"{min(4, len(claims) or 1) + 1} things to know about {name}"
        caption = f"A few things worth knowing about {name}, from {item} to how we work. Swipe through.{claim}"
    elif moment and any(w in pillar for w in ("offer", "special", "season", "occasion", "launch", "update")):
        headline, caption = f"{moment}: {item}", f"{moment} is coming up. Plan ahead with {item} from {name}.{claim}"
    elif any(w in pillar for w in ("behind", "kitchen", "craft", "inside", "made", "how")):
        headline, caption = f"How we make {item}", f"A look at how {name} makes {item}.{claim}"
    elif any(w in pillar for w in ("customer", "review", "regular", "result", "stor", "win", "member")):
        headline, caption = "What's your go-to?", f"Tell us: what do you always get at {name}? {Item}, or something else?{claim}"
    elif any(w in pillar for w in ("tip", "guide", "routine", "idea", "insight")):
        headline, caption = f"Good to know: {item}", f"Good to know before you visit {name}:{claim or ' ask us anything.'}"
    else:
        headline = f"On the menu: {item}" if food else f"Spotlight: {item}"
        caption = f"{Item} at {name}.{claim}"
    caption, cta = adapt_to_platform(kit, slot.platform, caption)
    return {"headline": headline[:60], "caption": caption, "cta": cta}
