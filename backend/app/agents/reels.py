"""Agent 7: short motion videos (Reels, Shorts, TikTok) from a post and the brand's own photos.

Nemotron writes the on-screen script (a hook, a few words per photo, a call to action); one of
five visual styles animates it at 1080x1920. Styles differ in layout, motion, typography,
transitions and pacing (slow cinematic zooms, fast cuts with caption blocks, floating cards,
an editorial magazine page, a scrapbook of polaroids), and a campaign's reels rotate through
them so they never all look alike. Frames are drawn with Pillow on several threads and piped
straight into ffmpeg, so a 12-second reel renders in seconds with no video editor.
"""
from __future__ import annotations

import asyncio
import colorsys
import hashlib
import json
import logging
import math
import os
import random
import re
import shutil
import subprocess
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

from .. import config
from ..llm import LLMError, router
from ..schemas import BrandKit, Campaign, Product, ReelOptions, ReelScene, SocialPost
from . import humanizer, occasions
from . import lang as lang_mod
from . import photos as photo_store
from . import strategist
from .renderer import cover_photo, fit_text, font, gradient, luminance, rgb, shade, text_on, text_scrim

log = logging.getLogger(__name__)

W, H, FPS = 1080, 1920, 30
MAX_PHOTOS = 5
MAX_SCENES = 8
KINDS = {"hook", "product", "fact", "cta"}
WORKERS = max(2, min(6, (os.cpu_count() or 2) - 1))
M = 84  # side margin


class ReelError(RuntimeError):
    pass


class ReelEditError(ReelError):
    """The owner's edited scenes can't be used as they are (a missing or unknown photo…)."""


@dataclass
class Scene:
    kind: str  # hook | product | fact | cta
    text: str
    sub: str = ""  # price under a product, the website on the end card
    photo: str = ""  # local image file
    seconds: float = 2.4
    tag: str = ""  # where this scene sits in the story: "Tip 2", "#1", "A", "2/3"


def _seed(post: SocialPost) -> int:
    return int(hashlib.md5((post.group_id or post.id).encode()).hexdigest()[:8], 16)


# --------------------------------------------------------------------------- what goes in it


# (product shown, local photo, what the photo's own post or slide said about it)
Shot = tuple[Product | None, str, str]


def reel_photos(campaign: Campaign, post: SocialPost, limit: int = MAX_PHOTOS, rnd: random.Random | None = None,
                products_only: bool = False, brand_first: bool = False) -> list[Shot]:
    """The post's own photos first, then other products the campaign already has photos of,
    one per product, so a reel shows a little of the range rather than one shot four times.
    With `rnd`, the others start from a different point each time, so two reels differ.
    `brand_first` prefers photos that aren't of one product (for a brand story)."""
    out: list[Shot] = []
    paths: set[str] = set()
    names: set[str] = set()

    def add(product: Product | None, bg, said: str = "") -> None:
        if not bg or not Path(bg.path).exists() or bg.path in paths or (products_only and not product):
            return
        if product and product.name.lower() in names:
            return
        paths.add(bg.path)
        if product:
            names.add(product.name.lower())
        out.append((product, bg.path, said))

    others = [p for p in sorted(campaign.posts, key=lambda p: p.publish_at) if p.group_id != post.group_id]
    if rnd and others:
        start = rnd.randrange(len(others))
        others = others[start:] + others[:start]
    if brand_first:
        for other in others:
            if not other.product and len(out) < limit:
                add(None, other.background, other.headline)
    add(post.product, post.background, post.headline)
    if post.gallery:
        add(post.compare, post.gallery[0])
    for slide in post.slides:
        add(None, slide.background, slide.headline)
    for other in others:
        if len(out) >= limit:
            break
        if other.product:
            add(other.product, other.background)
    # Few or no products (a brand whose site has photos but no shop): use the campaign's other photos.
    for other in others:
        if len(out) >= min(limit, 4):
            break
        if not other.product:
            add(None, other.background, other.headline)
    return out[:limit]


def _price(p: Product | None) -> str:
    if not p or not p.price:
        return ""
    price = p.price[:-3] if p.price.endswith(".00") else p.price
    pct = strategist.sale_percent(p)
    return f"{price} · {pct}% off" if pct else price


def _words(text: str, limit: int) -> str:
    return strategist.fit_headline(" ".join(str(text or "").split()).strip(" \"'"), limit)


def _site(kit: BrandKit) -> str:
    return (kit.website_url or "").split("//")[-1].split("/")[0].removeprefix("www.")


def default_cta(kit: BrandKit, post: SocialPost) -> str:
    industry = (kit.industry or "").lower()
    return "Order yours today" if "food" in industry or "restaurant" in industry else "Shop the collection" if kit.products else f"Follow {kit.name}"


# --------------------------------------------------------------------------- topics: one connected story each
#
# Every reel tells one story. The opening makes a promise ("3 ways to wear the X", "Our top 3
# right now", "Why people choose Y"), each scene delivers the next part of it, labelled in
# order (Tip 1, #3, A), and the end card closes the loop ("Which tip will you try?").

TOPICS = {
    "products": ("Product showcase", "A few products, one after another, each with its price"),
    "countdown": ("Top picks", "A countdown from #3 to #1"),
    "tips": ("Tips", "Numbered tips around one product"),
    "poll": ("This or that", "Two products, A or B, and a vote"),
    "story": ("Brand story", "What the brand stands for, from its own facts"),
    "occasion": ("Occasion", "A greeting for Eid, Mother's Day, a sale and more, with festive colours"),
    "trend": ("Trending format", "Formats people know from their feed: POV, \"this is your sign\", rate it, wait for the last one"),
}
KIND_TOPIC = {"spotlight": "products", "carousel": "countdown", "duo": "poll", "tip": "tips", "quote": "story",
              "sale": "occasion", "moment": "occasion", "question": "poll", "greeting": "occasion"}

TIPS = {
    "wear": ["Keep the rest of the look simple", "Add one statement accessory", "Dress it up with heels for evenings",
             "Dress it down with flats for the day", "Let one colour lead", "Layer it when the weather turns"],
    "food": ["Eat it hot, straight away", "Share a box with friends", "Pair it with a cold drink", "Save room for dessert",
             "Order ahead on busy nights", "Add a side for the table"],
    "other": ["Save this for later", "Start with what you need most", "Ask the team for advice", "Pair it with a favourite",
              "Try it this week", "Share it with a friend"],
}
ENDINGS = {
    "products": ["Which one's yours?", "Pick your favourite", "Which would you choose?"],
    "countdown": ["Which is your #1?", "Agree with our #1?", "What would your #1 be?"],
    "tips": ["Which tip will you try?", "Save these for later", "Try one this week"],
    "poll": ["Comment A or B", "A or B? Tell us", "Vote in the comments"],
    "story": ["Come and see for yourself", "That's us. Say hi", "Now you know us"],
}


def flavour(kit: BrandKit) -> str:
    return strategist.flavour(kit)


def product_shots(shots: list[Shot]) -> list[Shot]:
    return [s for s in shots if s[0]]


def available_topics(campaign: Campaign, post: SocialPost) -> list[str]:
    kit = campaign.brand
    shots = product_shots(reel_photos(campaign, post))
    out = ["products"] if shots else []
    if len(shots) >= 3:
        out.append("countdown")
    if shots:
        out.append("tips")
    if len(shots) >= 2:
        out.append("poll")
    if kit and len(story_facts(kit)) >= 2:
        out.append("story")
    out += ["trend", "occasion"]  # both work on the brand colours when there are no photos
    return out


def trend_formats(kit: BrandKit) -> list[str]:
    city = (kit.location or "").split(",")[0].strip() if kit else ""
    return [k for k in lang_mod.TRENDS if k != "local" or city]


def default_topic(campaign: Campaign, post: SocialPost, avoid: str = "") -> str:
    """The topic that fits the post's type ("this or that" post -> a poll reel); a fresh script
    for a reel that already had it moves on to another topic."""
    topics = available_topics(campaign, post)
    preferred = KIND_TOPIC.get(post.kind, "products")
    if preferred == "occasion" and not post_occasion(campaign, post):
        preferred = "products"
    order = [preferred] + [t for t in ("products", "trend", "countdown", "tips", "story", "poll") if t != preferred]
    return next((t for t in order if t in topics and t != avoid), topics[0] if topics else "products")


def post_occasion(campaign: Campaign, post: SocialPost) -> str:
    """The occasion a post is about: a greeting post's own occasion, else one its headline or
    caption names ("11.11 sale pick: ...", "Ready for Eid?")."""
    for text in (post.occasion, post.headline, post.caption[:160]):
        o = occasions.find(text) if text else None
        if o:
            return o.key
    return ""


def story_facts(kit: BrandKit) -> list[str]:
    facts = [strategist.short_claim(c) for c in strategist.brand_claims(kit)]
    city = (kit.location or "").split(",")[0].strip()
    if city:
        facts.append(f"Proudly from {city}")
    return [f for f in dict.fromkeys(facts) if f][:4]


def _pick(options: list[str], rnd: random.Random | None) -> str:
    return rnd.choice(options) if rnd else options[0]


@dataclass
class Plan:
    """A reel's story before it's worded: the opening, each scene's subject, the ending."""
    topic: str
    hook: str
    lines: list[str]  # one per scene, the rule-based wording
    shots: list[Shot]  # one per scene ("" photo = brand colour)
    tags: list[str]
    subs: list[str]
    cta: str
    cta_sub: str
    occasion: str = ""
    brief: str = ""  # what the story is, for the script writer


def plan_story(campaign: Campaign, post: SocialPost, topic: str, style: "Style", rnd: random.Random | None = None,
               occasion_key: str = "", language: str = "en", trend: str = "") -> Plan:
    plan = _plan_story(campaign, post, topic, style, rnd, occasion_key, language, trend)
    return localize(plan, campaign.brand, language, rnd)


def localize(plan: Plan, kit: BrandKit, language: str, rnd: random.Random | None) -> Plan:
    """The story's own words (opening, ending, tips, labels, greetings) in Roman Urdu or Urdu.
    Product names and the brand's facts stay as written; "mix" keeps English tips."""
    p = lang_mod.pools(language)
    if p == "en" or plan.topic == "trend":  # trend formats are written in the language from the start
        return plan
    f = flavour(kit)
    subject = strategist.display_name(kit, plan.shots[0][0]) if plan.shots and plan.shots[0][0] else kit.name
    fields = {"n": len(plan.lines), "brand": kit.name, "name": subject, "verb": lang_mod.VERBS[p][f]}
    if plan.topic in lang_mod.HOOKS[p]:
        plan.hook = _pick(lang_mod.HOOKS[p][plan.topic], rnd).format(**fields)
        plan.cta = _pick(lang_mod.ENDINGS[p][plan.topic], rnd)
    if plan.topic == "tips" and language != "mix":
        tips = list(lang_mod.TIPS[p][f])
        if rnd:
            rnd.shuffle(tips)
        plan.lines = tips[: len(plan.lines)]
        plan.tags = [lang_mod.TIP_LABEL[p].format(i=i + 1) for i in range(len(plan.lines))]
    if plan.topic == "occasion":
        o = occasions.OCCASIONS.get(plan.occasion)
        greet = lang_mod.greeting(plan.occasion, language, occasions.greeting(o, kit.name) if o else "")
        plan.hook = greet
        if language != "mix":
            lines = lang_mod.OCCASION_LINES[p]
            plan.lines = [lines[i % len(lines)] for i in range(len(plan.lines))]
        plan.cta = lang_mod.FROM_BRAND[p].format(brand=kit.name, greeting=greet)
    return plan


def _plan_story(campaign: Campaign, post: SocialPost, topic: str, style: "Style", rnd: random.Random | None,
                occasion_key: str, language: str, trend: str) -> Plan:
    kit = campaign.brand
    f = flavour(kit)
    site = _site(kit) or kit.name
    name = lambda p: strategist.display_name(kit, p)  # noqa: E731
    if topic == "occasion":
        o = occasions.find(occasion_key or post_occasion(campaign, post)) or occasions.OCCASIONS["sale" if post.kind == "sale" else "eid_fitr"]
        moment = occasion_key if occasion_key and occasion_key not in occasions.OCCASIONS else o.label
        shots = reel_photos(campaign, post, min(style.photos, 3), rnd, products_only=o.selling) if o.selling else \
            reel_photos(campaign, post, 2, rnd, brand_first=True)
        if o.key == "sale":  # real sale prices first
            on_sale = [s for s in shots if s[0] and strategist.sale_percent(s[0])]
            shots = on_sale + [s for s in shots if s not in on_sale]
        lines_pool = list(o.lines.get(f, o.lines.get("other", [])))
        lines = [occasions.fill(lines_pool[i % len(lines_pool)], kit.name, moment) for i in range(len(shots))] or \
            [occasions.fill(x, kit.name, moment) for x in lines_pool[:2]]
        subs = [_price(p) if p else "" for p, _, _ in shots] or [""] * len(lines)
        hook = occasions.fill(_pick(list(o.hooks), rnd), kit.name, moment)
        return Plan("occasion", hook, lines, shots or [(None, "", "")] * len(lines), [""] * len(lines), subs,
                    occasions.fill(_pick(list(o.ctas) or [occasions.greeting(o, kit.name, moment)], rnd), kit.name, moment), site, o.key,
                    f"A {o.label} reel: the opening greets people for {moment}; each scene shows a pick for the occasion; the end wishes them well.")
    if topic == "story":
        facts = story_facts(kit)[:3]
        shots = reel_photos(campaign, post, len(facts), rnd, brand_first=True)
        hook = _pick([f"Why people choose {kit.name}", f"Meet {kit.name}", f"{len(facts)} things to know about {kit.name}"], rnd)
        return Plan("story", hook, facts, (shots + [(None, "", "")] * len(facts))[:len(facts)], [str(i + 1) for i in range(len(facts))],
                    [""] * len(facts), _pick(ENDINGS["story"], rnd), site,
                    brief=f"A brand story: the opening asks why people choose {kit.name}; each scene gives one real reason from the brief, "
                          "in order; the end invites them in. Never add facts that aren't in the brief.")
    shots = product_shots(reel_photos(campaign, post, MAX_PHOTOS, rnd, products_only=True))
    if topic == "trend":
        p = lang_mod.pools(language)
        keys = trend_formats(kit)
        key = trend if trend in keys else _pick(keys, rnd)
        t = lang_mod.TRENDS[key]
        picks = (shots or reel_photos(campaign, post, style.photos, rnd))[: max(3, min(style.photos, 4))]
        city = (kit.location or "").split(",")[0].strip()
        hook = t["hook"][p]
        hook = (hook.get(flavour(kit)) if isinstance(hook, dict) else hook).format(brand=kit.name, city=city)
        n = len(picks)
        tags = [t["tag"][p]] * n if "tag" in t else [""] * n
        if "last" in t and n:
            tags[-1] = t["last"][p]
        lines = [name(pr) if pr else (LEAD_IN.sub("", said).strip() or kit.name) for pr, _, said in picks]
        if not picks:  # no photos: the brand's own facts, on its colours
            lines = story_facts(kit)[:3] or [kit.tagline or kit.name]
            picks = [(None, "", "")] * len(lines)
            n = len(lines)
            tags = [t["tag"][p]] * n if "tag" in t else [""] * n
            if "last" in t:
                tags[-1] = t["last"][p]
        return Plan("trend", hook, lines, picks, tags, [_price(pr) for pr, _, _ in picks],
                    t["end"][p].format(city=city), site, occasion=key,
                    brief=f"A trending '{t['label'].format(city=city)}' reel: the opening uses that well-known format; each scene "
                          "shows one photo, in order; the end invites people to join in. Keep the format's opening recognisable.")
    if topic == "tips" and shots:
        subject = shots[0]
        tips = list(TIPS[f])
        if rnd:
            rnd.shuffle(tips)
        tips = tips[:3]
        p = subject[0]
        verb = "wear" if f == "wear" else "enjoy" if f == "food" else "use"
        hook = _pick([f"{len(tips)} ways to {verb} the {name(p)}", f"How to {verb} the {name(p)}", f"{len(tips)} tips for the {name(p)}"], rnd)
        return Plan("tips", hook, tips, [subject] * len(tips), [f"Tip {i + 1}" for i in range(len(tips))], [""] * len(tips),
                    _pick(ENDINGS["tips"], rnd), f"{name(p)} · {_price(p)}" if _price(p) else site,
                    brief=f"Tips: the opening promises {len(tips)} ways to {verb} the {name(p)}; each scene is one short practical tip "
                          "about that same product, in order; the end asks which tip they'll try.")
    if topic == "poll" and len(shots) >= 2:
        pair = shots[:2]
        hook = _pick(["This or that?", "Which would you pick?", "Help us settle this"], rnd)
        return Plan("poll", hook, [name(p) for p, _, _ in pair], pair, ["A", "B"], [_price(p) for p, _, _ in pair],
                    _pick(ENDINGS["poll"], rnd), site,
                    brief=f"This or that: the opening asks people to choose; scene A shows {name(pair[0][0])}, scene B shows "
                          f"{name(pair[1][0])}; the end asks them to vote A or B in the comments.")
    if topic == "countdown" and len(shots) >= 3:
        picks = shots[: min(len(shots), max(3, style.photos - 1))][:4]
        n = len(picks)
        ordered = list(reversed(picks))  # build up to #1, the post's own product
        return Plan("countdown", _pick([f"Our top {n} right now", f"Top {n} at {kit.name}", f"The {n} we can't stop talking about"], rnd),
                    [name(p) for p, _, _ in ordered], ordered, [f"#{n - i}" for i in range(n)], [_price(p) for p, _, _ in ordered],
                    _pick(ENDINGS["countdown"], rnd), site,
                    brief=f"A countdown: the opening promises the top {n}; scenes go from #{n} down to #1, one product each; "
                          "the end asks which is their #1.")
    # products (also the fallback when a topic has nothing to show)
    picks = shots[: style.photos] or reel_photos(campaign, post, style.photos, rnd)
    n = len(picks)
    if not n:
        facts = story_facts(kit)[:3] or [kit.tagline or kit.name]
        return Plan("story", f"Meet {kit.name}", facts, [(None, "", "")] * len(facts), [str(i + 1) for i in range(len(facts))],
                    [""] * len(facts), _pick(ENDINGS["story"], rnd), site, brief="A brand story told on the brand colours.")
    hook = _pick([f"{n} picks from {kit.name}", f"Meet {n} {kit.name} favourites", f"{n} you'll want this week"], rnd)
    lines = [name(p) if p else (LEAD_IN.sub("", said).strip() or kit.name) for p, _, said in picks]
    return Plan("products", hook, lines, picks, [f"{i + 1}/{n}" for i in range(n)], [_price(p) for p, _, _ in picks],
                _pick(ENDINGS["products"], rnd), site,
                brief=f"A showcase: the opening promises {n} picks; each scene names the product in its photo, in order; "
                      "the end asks which one is theirs.")


# "Spotlight: The August Rotation" -> "The August Rotation"
LEAD_IN = re.compile(r"^(spotlight|good to know|a tip from [^:]+|tip|new in|in the details|all about[^:]*|the edit)\s*:\s*", re.I)


REEL_SYSTEM = """You write the on-screen words for a 10 to 15 second vertical video (an Instagram Reel, YouTube Short or TikTok).
The video tells ONE connected story, described in "story". The hook makes a promise; each scene delivers the next part of
that promise, in order, about what its photo shows (keep each scene's label and subject); the closing line pays it off.
Specific to this brand, plain and punchy, words a person would say. No hashtags, no emojis, no AI clichés ("elevate",
"unleash", "indulge", "game-changer"). Never invent prices, offers, discounts or facts.
Return JSON: {"hook": "<= 7 words", "scenes": ["<= 7 words per scene, same order and count"], "cta": "<= 6 words"}"""


LANGUAGE_NOTES = {
    "roman": "Write every line in Roman Urdu: Urdu in Latin letters, casual, the way people in Pakistan text and post.",
    "ur": "Write every line in Urdu, in Urdu script.",
    "mix": "Write in English with natural Roman Urdu phrases mixed in, the way Pakistani brands post.",
}


async def write_script(kit: BrandKit, post: SocialPost, plan: Plan, style: "Style | None" = None,
                       language: str = "en") -> tuple[Plan, bool]:
    """The model words the planned story; the rule-based words stay when there's no model."""
    if not router.enabled:
        return plan, False
    scenes = [{"label": tag, "photo": (strategist.display_name(kit, p) + (f" ({_price(p)})" if _price(p) else "")) if p else "a photo from the brand",
               "draft": line} for tag, (p, _, _), line in zip(plan.tags, plan.shots, plan.lines)]
    user = (f"Brand: {strategist.brand_brief(kit)}\nStory: {plan.brief}\nDraft hook: {plan.hook}\nDraft closing: {plan.cta}\n"
            + (f"Video style: {style.label}. Tone: {style.tone}\n" if style else "")
            + (f"Language: {LANGUAGE_NOTES[language]} Product names stay as given.\n" if language in LANGUAGE_NOTES else "")
            + f"Scenes: {json.dumps(scenes, ensure_ascii=False)}")
    try:
        data = await router.complete_json("reel_script", REEL_SYSTEM, user, temperature=0.8, max_tokens=500)
    except (LLMError, ValueError) as exc:
        log.info("reel script fell back to rules: %s", exc)
        return plan, False
    if not isinstance(data, dict):
        return plan, False
    lines = [str(s) for s in (data.get("scenes") or []) if str(s).strip()]
    if len(lines) != len(plan.lines):
        lines = plan.lines
    plan.hook = str(data.get("hook") or "").strip() or plan.hook
    plan.lines = lines
    plan.cta = str(data.get("cta") or "").strip() or plan.cta
    return plan, True


def tidy_line(text: str, kind: str) -> str:
    """On-screen words read like a person wrote them: the humanizer's rule pass (no stock AI
    phrases, no em dashes, contractions), no full stop on a short line, a capital to start."""
    line = humanizer.rule_pass(" ".join(str(text or "").split())).strip()
    if line.endswith(".") and line.count(".") == 1 and not line.endswith(".."):
        line = line[:-1]
    return line[:1].upper() + line[1:]


async def humanize_lines(kit: BrandKit, lines: list[str], kinds: list[str], deep: bool) -> tuple[list[str], dict]:
    """Humanize a reel's words together, so they keep one voice. With a model, the full
    humanizer rewrites them (facts and the brand name are guarded); then every line gets the rule pass."""
    joined = "\n".join(lines)
    before = humanizer.ai_tell_score(joined)
    used_llm = False
    if deep and router.enabled and any(lines):
        res = await humanizer.humanize(joined, voice=kit.brand_voice_prompt, threshold=0, protect=[kit.name])
        rewritten = [x for x in res.text.split("\n") if x.strip()]
        if len(rewritten) == len(lines):  # one line in, one line out, or the rewrite is ignored
            lines, used_llm = rewritten, res.used_llm
    out = [tidy_line(line, kind) or line for line, kind in zip(lines, kinds)]
    return out, {"before": round(before, 1), "after": round(humanizer.ai_tell_score("\n".join(out)), 1), "used_llm": used_llm}


async def humanize_scenes(kit: BrandKit, scenes: list[ReelScene]) -> tuple[list[ReelScene], dict]:
    texts, info = await humanize_lines(kit, [s.text for s in scenes], [s.kind for s in scenes], deep=True)
    return [s.model_copy(update={"text": t}) for s, t in zip(scenes, texts)], info


def plan_scenes(plan: Plan) -> list[Scene]:
    first = next((path for _, path, _ in plan.shots if path), "")
    scenes = [Scene("hook", _words(plan.hook, 52), photo=first)]
    for (p, path, _), line, tag, sub in zip(plan.shots, plan.lines, plan.tags, plan.subs):
        scenes.append(Scene("product" if path else "fact", _words(line, 52), sub=sub, photo=path, tag=tag))
    scenes.append(Scene("cta", _words(plan.cta, 40), sub=plan.cta_sub))
    return scenes


# --------------------------------------------------------------------------- editing


def media_url(path: str) -> str:
    p = Path(path) if path else None
    return f"/media/{p.name}" if p and p.parent.resolve() == config.MEDIA_DIR.resolve() and p.exists() else ""


def photo_choices(campaign: Campaign) -> list[dict]:
    """Every photo a scene can use: ones the campaign already has, then the rest of the
    brand's product and website photos (downloaded when picked)."""
    out: list[dict] = []
    seen: set[str] = set()  # local files, web URLs already downloaded, and products already shown

    def add(url: str, label: str, price: str = "", remote: bool = False) -> None:
        if url and url not in seen:
            seen.add(url)
            out.append({"url": url, "label": label, "price": price, "remote": remote})

    kit = campaign.brand
    for p in sorted(campaign.posts, key=lambda p: p.publish_at):
        for bg, product in ((p.background, p.product), *((g, p.compare) for g in p.gallery[:1]),
                            *((s.background, None) for s in p.slides)):
            if bg and media_url(bg.path):
                seen.update({bg.credit_url or "", f"product:{product.name.lower()}" if product else ""})
                add(media_url(bg.path), product.name if product else (kit.name if kit else "Photo"), _price(product))
    if kit:
        for product in kit.products:
            if product.image_url and f"product:{product.name.lower()}" not in seen:
                add(product.image_url, product.name, _price(product), remote=True)
        for url in kit.images:
            add(url, f"From {kit.name}'s website", remote=True)
    return out[:60]


async def resolve_photo(campaign: Campaign, ref: str) -> str:
    """A scene's photo reference -> a local file. Local files must be in MonoPlus's media folder;
    web photos must be ones found on the brand's own site."""
    ref = (ref or "").strip()
    if not ref:
        return ""
    if ref.startswith("/media/"):
        path = config.MEDIA_DIR / Path(ref.split("?")[0]).name
        if not path.exists() or path.suffix.lower() not in (".jpg", ".jpeg", ".png", ".webp"):
            raise ReelEditError("One of the photos is no longer available. Pick another.")
        return str(path)
    kit = campaign.brand
    allowed = {p.image_url for p in (kit.products if kit else []) if p.image_url} | set(kit.images if kit else [])
    if ref not in allowed:
        raise ReelEditError("Pick photos from the list: your campaign's photos, your website's or an upload.")
    try:
        bg = await photo_store.website_background(ref, credit=f"Photo from {kit.name}")
    except Exception as exc:  # noqa: BLE001 - download or decode failure
        raise ReelEditError(f"Couldn't download that photo: {exc}") from exc
    return bg.path


async def scenes_from_edit(campaign: Campaign, edited: list[ReelScene]) -> list[Scene]:
    edited = [s for s in edited if s.text.strip() or s.photo][:MAX_SCENES]
    if not edited:
        raise ReelEditError("A reel needs at least one scene.")
    out = []
    for s in edited:
        kind = s.kind if s.kind in KINDS else "product"
        path = await resolve_photo(campaign, s.photo) if kind != "cta" else ""
        if kind == "product" and not path:
            kind = "fact"  # a product scene without a photo is shown on the brand colour
        out.append(Scene(kind, " ".join(s.text.split())[:80], sub=" ".join(s.sub.split())[:40], photo=path, tag=s.tag.strip()[:12]))
    return out


def to_edit(scenes: list[Scene]) -> list[ReelScene]:
    return [ReelScene(kind=s.kind, text=s.text, sub=s.sub, photo=media_url(s.photo), tag=s.tag) for s in scenes]


# --------------------------------------------------------------------------- drawing helpers


def ease_out(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def spring(t: float) -> float:
    """0 -> 1 with a little overshoot, for things that pop in."""
    t = max(0.0, min(1.0, t))
    return 1 - math.exp(-6 * t) * math.cos(9 * t)


def faded(layer: Image.Image, k: float) -> Image.Image:
    if k >= 0.999:
        return layer
    out = layer.copy()
    out.putalpha(layer.getchannel("A").point(lambda a: int(a * max(0.0, k))))
    return out


def scaled(layer: Image.Image, s: float) -> Image.Image | None:
    if s <= 0.02:
        return None
    return layer.resize((max(1, int(layer.width * s)), max(1, int(layer.height * s))), Image.BILINEAR)


def paste_center(img: Image.Image, layer: Image.Image | None, cx: float, cy: float) -> None:
    if layer is not None:
        img.alpha_composite(layer, (int(cx - layer.width / 2), int(cy - layer.height / 2)))


def mix(a, b, k: float) -> tuple[int, int, int]:
    return tuple(int(a[i] + (b[i] - a[i]) * k) for i in range(3))


def logo_chip(kit: BrandKit, max_w: int, max_h: int) -> Image.Image | None:
    """The logo on a white chip, scaled up to fill the box: many sites only offer a small logo file."""
    if not kit.logo_path or not Path(kit.logo_path).exists():
        return None
    try:
        logo = Image.open(kit.logo_path).convert("RGBA")
    except OSError:
        return None
    logo = logo.crop(logo.getbbox() or (0, 0, *logo.size))
    s = min(max_w / logo.width, max_h / logo.height)
    logo = logo.resize((max(1, int(logo.width * s)), max(1, int(logo.height * s))), Image.LANCZOS)
    pad = max(14, int(min(logo.size) * 0.12))
    chip = Image.new("RGBA", (logo.width + 2 * pad, logo.height + 2 * pad), (0, 0, 0, 0))
    ImageDraw.Draw(chip).rounded_rectangle([0, 0, chip.width - 1, chip.height - 1], radius=pad * 2, fill=(255, 255, 255, 240))
    chip.alpha_composite(logo, (pad, pad))
    return chip


def _lines(text: str, width: int, max_h: int, start: int, minimum: int = 48, max_lines: int = 4):
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    return fit_text(probe, text, width, max_h, start, minimum=minimum, max_lines=max_lines)


def text_block(text: str, width: int, max_h: int, start: int, color, align: str = "left", max_lines: int = 4,
               minimum: int = 54, shadow: bool = True) -> Image.Image:
    fnt, lines, lh = _lines(text, width, max_h, start, minimum, max_lines)
    block = Image.new("RGBA", (width, lh * len(lines) + int(lh * 0.3)), (0, 0, 0, 0))
    d = ImageDraw.Draw(block)
    for i, line in enumerate(lines):
        x = (width - d.textlength(line, font=fnt)) / 2 if align == "center" else 0
        if shadow:  # a soft shadow keeps white type readable on any part of a photo
            d.text((x + 3, i * lh + 4), line, font=fnt, fill=(0, 0, 0, 90))
        d.text((x, i * lh), line, font=fnt, fill=(*color, 255))
    return block


def line_images(text: str, width: int, max_h: int, start: int, color, minimum: int = 44, max_lines: int = 4) -> list[Image.Image]:
    """One tight image per line, for effects that reveal a line at a time."""
    fnt, lines, lh = _lines(text, width, max_h, start, minimum, max_lines)
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    out = []
    for line in lines:
        # Size the strip from the glyphs themselves: a strip one line-height tall cuts off the
        # tails of g, j, p, q and y ("Proudly local").
        _, _, right, bottom = probe.textbbox((0, 0), line, font=fnt)
        img = Image.new("RGBA", (right + 8, max(lh, bottom + 6)), (0, 0, 0, 0))
        ImageDraw.Draw(img).text((0, 0), line, font=fnt, fill=(*color, 255))
        out.append(img)
    return out


def caption_blocks(text: str, width: int, start: int, fills: list, tilt: bool = True) -> list[Image.Image]:
    """TikTok-style captions: each line on its own colour block, alternately tilted."""
    fnt, lines, lh = _lines(text, width - 60, 600, start, minimum=56, max_lines=4)
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    out = []
    for i, line in enumerate(lines):
        fill = fills[i % len(fills)]
        tw = int(probe.textlength(line, font=fnt))
        pad_x, pad_y = int(fnt.size * 0.32), int(fnt.size * 0.16)
        ink = max(int(fnt.size * 1.18), probe.textbbox((0, 0), line, font=fnt)[3] + 4)  # room for lowercase tails
        block = Image.new("RGBA", (tw + 2 * pad_x, ink + 2 * pad_y), (0, 0, 0, 0))
        d = ImageDraw.Draw(block)
        d.rounded_rectangle([0, 0, block.width - 1, block.height - 1], radius=int(fnt.size * 0.18), fill=(*fill, 255))
        d.text((pad_x, pad_y), line, font=fnt, fill=(*text_on(fill), 255))
        out.append(block.rotate((-2.2 if i % 2 else 1.8) if tilt else 0, expand=True, resample=Image.BICUBIC))
    return out


def pill(text: str, size: int, fill, fg) -> Image.Image:
    text = lang_mod.shape(text)
    f = font(size)
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    tw = int(probe.textlength(text, font=f))
    px, py = int(size * 0.7), int(size * 0.42)
    img = Image.new("RGBA", (tw + 2 * px, size + 2 * py + 6), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, img.width - 1, img.height - 1], radius=img.height // 2, fill=(*fill, 255))
    d.text((px, py - size * 0.06), text, font=f, fill=(*fg, 255))
    return img


def sticker(text: str, d: int, fill, angle: float) -> Image.Image:
    """A round price sticker."""
    text = lang_mod.shape(text)
    img = Image.new("RGBA", (d, d), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([0, 0, d - 1, d - 1], fill=(*fill, 255), outline=(255, 255, 255, 255), width=max(6, d // 30))
    size = int(d * 0.24)
    while size > 20 and draw.textlength(text, font=font(size)) > d * 0.78:
        size -= 2
    f = font(size)
    draw.text(((d - draw.textlength(text, font=f)) / 2, (d - size * 1.15) / 2), text, font=f, fill=(*text_on(fill), 255))
    return img.rotate(angle, expand=True, resample=Image.BICUBIC)


def rounded(img: Image.Image, radius: int) -> Image.Image:
    out = img.convert("RGBA")
    mask = Image.new("L", out.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, out.width - 1, out.height - 1], radius=radius, fill=255)
    out.putalpha(mask)
    return out


def drop_shadow(size: tuple[int, int], radius: int, blur: int = 30, alpha: int = 110) -> Image.Image:
    pad = blur * 2
    img = Image.new("RGBA", (size[0] + 2 * pad, size[1] + 2 * pad), (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle([pad, pad, pad + size[0], pad + size[1]], radius=radius, fill=(0, 0, 0, alpha))
    return img.filter(ImageFilter.GaussianBlur(blur))


@lru_cache(maxsize=8)
def soft_glow(color: tuple[int, int, int], r: int = 620, alpha: int = 70) -> Image.Image:
    pad = 360
    glow = Image.new("RGBA", (2 * (r + pad), 2 * (r + pad)), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse([pad, pad, pad + 2 * r, pad + 2 * r], fill=(*color, alpha))
    return glow.filter(ImageFilter.GaussianBlur(120))


@lru_cache(maxsize=8)
def dotted(paper: tuple[int, int, int], dot: tuple[int, int, int]) -> Image.Image:
    img = Image.new("RGBA", (W, H), (*paper, 255))
    d = ImageDraw.Draw(img)
    for row, y in enumerate(range(-20, H + 60, 96)):
        for x in range(-20 + (48 if row % 2 else 0), W + 60, 96):
            d.ellipse([x, y, x + 14, y + 14], fill=(*dot, 60))
    return img


def ken_burns(photo: Image.Image, z: float, cx_frac: float = 0.5, cy_frac: float = 0.5, size=(W, H)) -> Image.Image:
    """A window into an oversized photo; z >= 1 zooms in. The photo must already have the frame's aspect."""
    cw, ch = photo.width / z, photo.height / z
    cx = min(max(photo.width * cx_frac, cw / 2), photo.width - cw / 2)
    cy = min(max(photo.height * cy_frac, ch / 2), photo.height - ch / 2)
    box = (int(cx - cw / 2), int(cy - ch / 2), int(cx + cw / 2), int(cy + ch / 2))
    return photo.resize(size, Image.BILINEAR, box=box)


# --------------------------------------------------------------------------- colours


def _hex(c) -> str:
    return "#%02X%02X%02X" % tuple(int(v) for v in c)


def hue_shift(c, degrees: float, lightness: float | None = None) -> tuple[int, int, int]:
    h, l, s = colorsys.rgb_to_hls(*(v / 255 for v in c))
    r, g, b = colorsys.hls_to_rgb((h + degrees / 360) % 1, l if lightness is None else lightness, max(s, 0.45))
    return int(r * 255), int(g * 255), int(b * 255)


def _brand(p, a, i):
    return p, a, i


def _midnight(p, a, i):
    return shade(p, 0.11), shade(p, 0.62) if luminance(shade(p, 0.62)) > 0.15 else (255, 255, 255), (20, 20, 26)


def _pastel(p, a, i):
    return shade(p, 0.86), shade(p, 0.42), shade(p, 0.16)


def _complement(p, a, i):
    return hue_shift(p, 180, 0.42), p if luminance(p) > 0.08 else shade(p, 0.6), (22, 22, 28)


def _custom(color):
    def make(p, a, i):
        # The picked colour is what people notice (caption blocks, stickers, bars, price chips),
        # so it's the accent; a deep shade of it is the background.
        c = rgb(color)
        accent = c if luminance(c) > 0.06 else shade(c, 0.6)
        base = shade(c, 0.3) if luminance(c) > 0.12 else c
        return base, accent, shade(c, 0.12)
    return make


@dataclass(frozen=True)
class Palette:
    key: str
    label: str
    make: object  # (primary, accent, ink) -> (primary, accent, ink)


PALETTES: dict[str, Palette] = {p.key: p for p in [
    Palette("brand", "Your brand", _brand),
    Palette("midnight", "Night", _midnight),
    Palette("pastel", "Soft", _pastel),
    Palette("complement", "Pop", _complement),
    Palette("mono", "Mono", lambda p, a, i: ((22, 22, 26), (255, 255, 255), (17, 17, 17))),
    Palette("sunset", "Sunset", lambda p, a, i: ((226, 88, 52), (255, 202, 88), (48, 20, 14))),
    Palette("ocean", "Ocean", lambda p, a, i: ((14, 74, 128), (92, 200, 245), (10, 26, 42))),
    Palette("forest", "Forest", lambda p, a, i: ((28, 70, 52), (156, 216, 180), (12, 30, 22))),
    Palette("berry", "Berry", lambda p, a, i: ((122, 28, 86), (255, 150, 182), (36, 10, 26))),
]}
AUTO_PALETTES = ["brand", "midnight", "pastel", "complement"]  # rotated for reels nobody customised; all on-brand
PACES = {"relaxed": 1.25, "normal": 1.0, "snappy": 0.8}
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def palette_colors(kit: BrandKit, key: str, color: str = "") -> tuple:
    base = (rgb(kit.primary_color), rgb(kit.accent_color), rgb(kit.secondary_color))
    make = _custom(color) if key == "custom" and HEX.match(color or "") else PALETTES.get(key, PALETTES["brand"]).make
    return tuple(tuple(int(v) for v in c) for c in make(*base))


def palette_kit(kit: BrandKit, key: str, color: str = "") -> BrandKit:
    p, a, i = palette_colors(kit, key, color)
    return kit.model_copy(update={"primary_color": _hex(p), "accent_color": _hex(a), "secondary_color": _hex(i)})


def palette_list(kit: BrandKit) -> list[dict]:
    return [{"key": p.key, "label": p.label, "colors": [_hex(c) for c in palette_colors(kit, p.key)]} for p in PALETTES.values()]


def choose_palette(campaign: Campaign, post: SocialPost, avoid: str = "") -> str:
    """The on-brand palette this campaign's other reels have used least (your brand colours first)."""
    others = {p.group_id or p.id: p.reel_options.palette for p in campaign.posts
              if p.video_url and (p.group_id or p.id) != (post.group_id or post.id)}
    used = Counter(others.values())
    keys = [k for k in AUTO_PALETTES if k != avoid] or AUTO_PALETTES
    return min(keys, key=lambda k: used[k])


# --------------------------------------------------------------------------- styles


class Base:
    """Draws one scene of a reel at local time t (seconds from the scene's start)."""
    upper = False

    def __init__(self, kit: BrandKit, scene: Scene, index: int, count: int, prev: list["Base"], upper: bool | None = None):
        self.kit, self.scene, self.index, self.count, self.prev = kit, scene, index, count, prev
        if upper is not None:
            self.upper = upper
        self.primary, self.accent, self.ink = rgb(kit.primary_color), rgb(kit.accent_color), rgb(kit.secondary_color)
        self.on_primary = text_on(self.primary)
        self.text = scene.text.upper() if self.upper else scene.text
        self.dur = scene.seconds
        self.setup()

    def setup(self) -> None:
        pass

    def frame(self, t: float) -> Image.Image:
        raise NotImplementedError


class Cinematic(Base):
    """Full-screen photos with slow zooms that alternate in and out, words that rise into place."""

    def setup(self) -> None:
        s = self.scene
        self.logo = logo_chip(self.kit, 220, 120)
        self.photo = None
        if s.photo and s.kind != "cta":
            big = (int(W * 1.12), int(H * 1.12))
            photo = cover_photo(s.photo, big)
            if s.kind in ("hook", "fact"):  # a blurred, brand-tinted version of the photo behind the words
                photo = Image.blend(photo.filter(ImageFilter.GaussianBlur(28)), Image.new("RGB", big, shade(self.primary, 0.18)), 0.55)
            self.photo = photo
        if s.kind == "product":
            scrim = text_scrim((W, H), "bottom", shade(self.primary, 0.08))
            top_h, bottom_y = int(H * 0.18), int(H * 0.55)
            self.scrim = [(scrim.crop((0, 0, W, top_h)), 0), (scrim.crop((0, bottom_y, W, H)), bottom_y)]
            self.block = text_block(self.text, W - 2 * M, int(H * 0.22), 112, (255, 255, 255))
            self.price = pill(s.sub, 52, self.accent, text_on(self.accent)) if s.sub else None
        else:
            fg = self.on_primary if not self.photo else (255, 255, 255)
            self.block = text_block(self.text, W - 2 * M, int(H * 0.32), 120 if s.kind != "cta" else 104, fg, align="center")
            self.bg = None if self.photo else gradient((W, H), self.primary, shade(self.primary, 0.2)).convert("RGBA")
            self.glow = soft_glow(shade(self.primary, 0.62))
            if s.kind == "cta":
                self.big_logo = logo_chip(self.kit, 420, 300)
                self.site = pill(s.sub, 40, (255, 255, 255), shade(self.primary, 0.25)) if s.sub else None

    def background(self, t: float) -> Image.Image:
        if self.photo is not None:
            p = t / max(0.1, self.dur)
            z = 1.0 + 0.1 * (p if self.index % 2 == 0 else 1 - p)
            drift = 0.5 + (p - 0.5) * (0.08 if self.index % 2 else -0.08)
            return ken_burns(self.photo, z, drift).convert("RGBA")
        img = self.bg.copy()
        cx = int(W * (0.2 + 0.6 * (t / max(0.1, self.dur))))
        img.alpha_composite(self.glow, (cx - self.glow.width // 2, 260 - self.glow.height // 2))
        return img

    def frame(self, t: float) -> Image.Image:
        img = self.background(t)
        k = ease_out((t - 0.12) / 0.5)
        s = self.scene
        if s.kind == "product":
            for part, y0 in self.scrim:
                img.alpha_composite(part, (0, y0))
            y = H - M - 150 - self.block.height - (self.price.height + 30 if self.price else 0)
            img.alpha_composite(faded(self.block, k), (M, int(y + 70 * (1 - k))))
            bar = int(150 * ease_out((t - 0.35) / 0.4))
            if bar > 2:
                ImageDraw.Draw(img).rectangle([M, y + self.block.height + 4, M + bar, y + self.block.height + 18], fill=(*self.accent, 255))
            if self.price:
                chip = scaled(self.price, spring((t - 0.45) / 0.6))
                if chip:
                    img.alpha_composite(chip, (M, y + self.block.height + 44 + (self.price.height - chip.height) // 2))
        elif s.kind == "cta":
            top = 560
            if self.big_logo is not None:
                paste_center(img, scaled(self.big_logo, spring((t - 0.05) / 0.7)), W / 2, top + self.big_logo.height / 2)
                top += self.big_logo.height + 90
            k2 = ease_out((t - 0.4) / 0.5)
            img.alpha_composite(faded(self.block, k2), (M, int(top + 60 * (1 - k2))))
            top += self.block.height + 40
            bar = int(180 * ease_out((t - 0.7) / 0.4))
            if bar > 2:
                ImageDraw.Draw(img).rectangle([(W - bar) // 2, top, (W + bar) // 2, top + 12], fill=(*self.accent, 255))
            if self.site:
                img.alpha_composite(faded(self.site, ease_out((t - 0.9) / 0.5)), ((W - self.site.width) // 2, top + 70))
        else:
            y = (H - self.block.height) // 2 - 40
            img.alpha_composite(faded(self.block, k), (M, int(y + 90 * (1 - k))))
            bar = int(160 * ease_out((t - 0.45) / 0.4))
            if bar > 2:
                yb = y + self.block.height + 30
                ImageDraw.Draw(img).rectangle([(W - bar) // 2, yb, (W + bar) // 2, yb + 12], fill=(*self.accent, 255))
        if self.logo is not None and s.kind != "cta":
            img.alpha_composite(self.logo, (M - 20, 150))
        return img.convert("RGB")


class Punch(Base):
    """Fast cuts: every scene lands with a zoom punch, captions pop in on tilted colour blocks."""
    upper = True

    def setup(self) -> None:
        s = self.scene
        self.logo = logo_chip(self.kit, 200, 110)
        self.photo = None
        if s.photo and s.kind != "cta":
            photo = cover_photo(s.photo, (int(W * 1.1), int(H * 1.1)))
            self.photo = ImageEnhance.Brightness(photo).enhance(0.55 if s.kind in ("hook", "fact") else 0.85)
        else:
            base = self.accent if s.kind == "cta" else self.primary
            img = Image.new("RGBA", (W, H), (*base, 255))
            d = ImageDraw.Draw(img)
            stripe = (*shade(base, 0.5 if sum(base) > 380 else 0.4), 60)
            for x in range(-H, W, 120):  # diagonal stripes
                d.polygon([(x, H), (x + 60, H), (x + 60 + H, 0), (x + H, 0)], fill=stripe)
            self.flat = img
        fills = [(255, 255, 255), self.accent] if s.kind != "cta" else [self.primary, (255, 255, 255)]
        if fills[1] == fills[0] or sum(abs(a - b) for a, b in zip(fills[0], fills[1])) < 60:
            fills[1] = self.primary
        self.blocks = caption_blocks(self.text, W - 2 * M, 118 if s.kind != "product" else 104, fills)
        self.sticker = sticker(s.sub, 300, self.accent if sum(self.accent) < 650 else self.primary, -12) if s.sub and s.kind == "product" else None
        if s.kind == "cta":
            self.big_logo = logo_chip(self.kit, 440, 320)

    def frame(self, t: float) -> Image.Image:
        s = self.scene
        if self.photo is not None:
            z = 1.0 + 0.16 * (1 - ease_out(t / 0.32)) + 0.05 * (t / max(0.1, self.dur))
            img = ken_burns(self.photo, z).convert("RGBA")
        else:
            img = self.flat.copy()
        total_h = sum(b.height for b in self.blocks) - 10 * (len(self.blocks) - 1)
        y = {"product": int(H * 0.64), "cta": int(H * 0.6)}.get(s.kind, H // 2) - total_h // 2
        for i, block in enumerate(self.blocks):
            paste_center(img, scaled(block, spring((t - 0.06 - i * 0.11) / 0.4)), W / 2, y + block.height / 2)
            y += block.height - 10
        if self.sticker is not None:
            paste_center(img, scaled(self.sticker, spring((t - 0.32) / 0.45)), W - M - 130, int(H * 0.36))
        if s.kind == "cta" and self.big_logo is not None:
            bounce = abs(math.sin(min(t, 1.2) * 5)) * 40 * max(0.0, 1 - t / 1.2)
            paste_center(img, scaled(self.big_logo, spring(t / 0.5)), W / 2, int(H * 0.33) - bounce)
        if self.logo is not None and s.kind != "cta":
            img.alpha_composite(self.logo, (M - 20, 140))
        return img.convert("RGB")


class Showcase(Base):
    """Each photo arrives on a floating card over the brand colours; pages push sideways."""

    def setup(self) -> None:
        s = self.scene
        base = gradient((W, H), shade(self.primary, 0.42), shade(self.primary, 0.16)).convert("RGBA")
        base.alpha_composite(soft_glow(self.accent, 420, 90), (W - 700, H - 900))
        self.base = base
        self.glow = soft_glow(shade(self.primary, 0.6), 500, 80)
        self.fg = text_on(shade(self.primary, 0.3))
        self.logo = logo_chip(self.kit, 200, 100)
        self.card = None
        if s.kind == "cta":
            logo = logo_chip(self.kit, 520, 380)
            card = Image.new("RGBA", (W - 2 * 150, 620), (0, 0, 0, 0))
            ImageDraw.Draw(card).rounded_rectangle([0, 0, card.width - 1, card.height - 1], radius=56, fill=(255, 255, 255, 255))
            if logo is not None:
                card.alpha_composite(logo, ((card.width - logo.width) // 2, (card.height - logo.height) // 2))
            self.card, self.card_y = card, int(H * 0.2)
        elif s.photo:
            cw, ch = W - 2 * 110, int(H * (0.56 if s.kind == "product" else 0.5))
            photo = rounded(cover_photo(s.photo, (cw, ch)), 44)
            card = Image.new("RGBA", (cw + 24, ch + 24), (0, 0, 0, 0))
            ImageDraw.Draw(card).rounded_rectangle([0, 0, card.width - 1, card.height - 1], radius=54, fill=(255, 255, 255, 255))
            card.alpha_composite(photo, (12, 12))
            self.card, self.card_y = card, int(H * 0.31) if s.kind == "product" else int(H * 0.42)
        if self.card is not None:
            self.shadow = drop_shadow(self.card.size, 54)
        size = 104 if s.kind == "product" else 118
        top_room = (self.card_y - 260) if self.card is not None and s.kind != "cta" else int(H * 0.3)
        self.block = text_block(self.text, W - 2 * M, max(200, top_room), size, self.fg,
                                align="left" if s.kind == "product" else "center", shadow=False)
        self.price = pill(s.sub, 56, (255, 255, 255), shade(self.primary, 0.3)) if s.sub else None
        self.side = 1 if self.index % 2 else -1

    def frame(self, t: float) -> Image.Image:
        s = self.scene
        img = self.base.copy()
        gx = int(W * (0.8 - 0.6 * t / max(0.1, self.dur)))
        img.alpha_composite(self.glow, (gx - self.glow.width // 2, 300 - self.glow.height // 2))
        k = ease_out(t / 0.6)
        if self.card is not None:
            dx = int((1 - k) * W * 0.75 * self.side)
            dy = int(math.sin(t * 2.4) * 8)
            x = (W - self.card.width) // 2 + dx
            img.alpha_composite(self.shadow, (x - 60, self.card_y + dy + 30 - 60))
            img.alpha_composite(self.card, (x, self.card_y + dy))
        k2 = ease_out((t - 0.2) / 0.5)
        if s.kind == "product" or (s.kind == "hook" and self.card is not None):
            y = max(220, self.card_y - 60 - self.block.height) if s.kind == "product" else int(H * 0.17)
        elif s.kind == "cta":
            y = self.card_y + self.card.height + 80 if self.card is not None else int(H * 0.4)
        else:
            y = (H - self.block.height) // 2
        img.alpha_composite(faded(self.block, k2), (M, int(y + 50 * (1 - k2))))
        if self.price is not None:
            below = (self.card_y + self.card.height + 50) if (self.card is not None and s.kind != "cta") else y + self.block.height + 60
            paste_center(img, scaled(self.price, spring((t - 0.5) / 0.5)), W / 2, below + self.price.height / 2)
        if self.logo is not None and s.kind != "cta":
            img.alpha_composite(self.logo, (W - M - self.logo.width + 20, 120))
        return img.convert("RGB")


class Magazine(Base):
    """An editorial page: a photo panel that unrolls, a numbered label, words that write themselves on."""

    def setup(self) -> None:
        s = self.scene
        self.paper = mix((250, 248, 243), self.primary, 0.06)
        self.ink_c = self.ink if sum(self.ink) < 330 else (28, 28, 34)
        # Labels and rules must read on paper: a pale accent (a pink tint) gives way to the main colour.
        self.rule = self.accent if luminance(self.accent) < 0.3 else self.primary if luminance(self.primary) < 0.45 else self.ink_c
        self.canvas = Image.new("RGBA", (W, H), (*self.paper, 255))
        self.logo = logo_chip(self.kit, 200, 100)
        self.panel_h = int(H * (0.6 if s.kind == "product" else 0.5))
        self.photo = cover_photo(s.photo, (W, int(self.panel_h * 1.18))) if s.photo and s.kind != "cta" else None
        label = ("New story" if s.kind == "hook" else f"No. {self.index:02d}" if s.kind in ("product", "fact") else "Find us")
        self.label = line_images(f"{label}  ·  {self.kit.name}".upper(), W - 2 * M, 60, 34, self.rule, minimum=26, max_lines=1)[0]
        size = 92 if s.kind == "product" else 104
        room = H - (self.panel_h if self.photo else int(H * 0.36)) - 420
        self.lines = line_images(self.text, W - 2 * M, max(240, room), size, self.ink_c, minimum=48, max_lines=4)
        self.price = line_images(s.sub, W - 2 * M, 80, 58, self.ink_c, minimum=30, max_lines=1)[0] if s.sub else None
        self.counter = line_images(f"{self.index + 1:02d} / {self.count:02d}", 300, 50, 30, mix(self.ink_c, self.paper, 0.4),
                                   minimum=20, max_lines=1)[0]
        self.big_logo = logo_chip(self.kit, 420, 280) if s.kind == "cta" else None

    def frame(self, t: float) -> Image.Image:
        s = self.scene
        img = self.canvas.copy()
        d = ImageDraw.Draw(img)
        if self.photo is not None:
            p = t / max(0.1, self.dur)
            y0 = int((self.photo.height - self.panel_h) * p)
            shown = max(1, int(self.panel_h * ease_out(t / 0.55)))
            img.paste(self.photo.crop((0, y0, W, y0 + shown)), (0, 0))
            top = self.panel_h + 70
        elif self.big_logo is not None:
            paste_center(img, faded(self.big_logo, ease_out(t / 0.5)), W / 2, int(H * 0.27))
            top = int(H * 0.27) + self.big_logo.height // 2 + 110
        else:
            d.text((M - 10, int(H * 0.2)), "“", font=font(300), fill=(*self.rule, 255))
            top = int(H * 0.36)
        img.alpha_composite(faded(self.label, ease_out((t - 0.2) / 0.4)), (M, top))
        rule = int((W - 2 * M) * ease_out((t - 0.3) / 0.6))
        if rule > 2:
            d.rectangle([M, top + self.label.height + 18, M + rule, top + self.label.height + 22], fill=(*self.rule, 255))
        y = top + self.label.height + 60
        for i, line in enumerate(self.lines):  # each line writes itself on, left to right
            r = ease_out((t - 0.4 - i * 0.2) / 0.45)
            if r > 0.01:
                img.alpha_composite(line.crop((0, 0, max(1, int(line.width * r)), line.height)), (M, y))
            y += line.height
        if self.price is not None:
            k = ease_out((t - 0.5 - len(self.lines) * 0.2) / 0.4)
            img.alpha_composite(faded(self.price, k), (M, y + 30))
            under = int(self.price.width * k)
            if under > 2:
                d.rectangle([M, y + 30 + self.price.height + 4, M + under, y + 30 + self.price.height + 12], fill=(*self.rule, 255))
        img.alpha_composite(self.counter, (W - M - self.counter.width, H - M - 20))
        if self.logo is not None and s.kind != "cta":
            img.alpha_composite(self.logo, (M - 20, 90))
        return img.convert("RGB")


POLAROID_ANGLES = [-6, 5, -3, 7, -5, 4, -7, 3]


class Scrapbook(Base):
    """Polaroids that drop onto a growing pile, with round stickers for prices."""

    def setup(self) -> None:
        s = self.scene
        paper = mix((255, 252, 246), self.primary, 0.08)
        self.base = dotted(paper, self.primary)
        self.ink_c = self.ink if sum(self.ink) < 330 else (30, 30, 36)
        self.logo = logo_chip(self.kit, 200, 100)
        pw, ph, strip = 780, 820, 230
        card = Image.new("RGBA", (pw, ph + strip + 40), (255, 255, 255, 255))
        if s.kind == "cta":
            logo = logo_chip(self.kit, 520, 520)
            if logo is not None:
                card.alpha_composite(logo, ((pw - logo.width) // 2, 40 + (ph - logo.height) // 2))
        elif s.photo:
            card.paste(cover_photo(s.photo, (pw - 60, ph)), (30, 40))
        else:
            ImageDraw.Draw(card).rectangle([30, 40, pw - 30, 40 + ph], fill=(*self.primary, 255))
        block = text_block(s.text, pw - 80, strip - 30, 66, self.ink_c, align="center", max_lines=2, minimum=34, shadow=False)
        card.alpha_composite(block, (40, 40 + ph + (strip - block.height) // 2 + 10))
        angle = POLAROID_ANGLES[self.index % len(POLAROID_ANGLES)]
        self.sprite = card.rotate(angle, expand=True, resample=Image.BICUBIC)
        self.shadow = drop_shadow(card.size, 6, 26, 90).rotate(angle, expand=True, resample=Image.BICUBIC)
        self.pos = (W / 2 + (30 if self.index % 2 else -30), H * 0.47)
        self.pile = [(p.sprite, p.pos) for p in self.prev[-2:] if isinstance(p, Scrapbook)]
        self.sticker = sticker(s.sub, 270, self.accent if sum(self.accent) < 650 else self.primary, 12) if s.sub and s.kind == "product" else None
        self.site = pill(s.sub, 40, self.primary, text_on(self.primary)) if s.sub and s.kind == "cta" else None

    def frame(self, t: float) -> Image.Image:
        img = self.base.copy()
        for sprite, (x, y) in self.pile:  # the pile the new polaroid lands on
            paste_center(img, sprite, x, y)
        drop = 1 - spring(t / 0.8)
        x, y = self.pos[0], self.pos[1] - drop * H * 0.9
        paste_center(img, self.shadow, x + 18, y + 30)
        paste_center(img, self.sprite, x, y)
        if self.sticker is not None:
            paste_center(img, scaled(self.sticker, spring((t - 0.55) / 0.45)), W - M - 120, int(H * 0.2))
        if self.site is not None:
            paste_center(img, faded(self.site, ease_out((t - 0.7) / 0.4)), W / 2, int(H * 0.86))
        if self.logo is not None and self.scene.kind != "cta":
            img.alpha_composite(self.logo, (M - 20, 110))
        return img.convert("RGB")


@dataclass(frozen=True)
class Style:
    key: str
    label: str
    blurb: str
    renderer: type
    transition: str  # fade | flash | push | wipe | cut
    overlap: float  # seconds two scenes share while one turns into the next
    pace: dict
    photos: int  # how many photos it shows
    bar: bool  # a story-style progress bar along the top
    tone: str  # a hint for the script writer


STYLES: dict[str, Style] = {s.key: s for s in [
    Style("cinematic", "Cinematic", "Full-screen photos, slow zooms, words that rise in, soft crossfades",
          Cinematic, "fade", 0.3, {"hook": 2.2, "product": 2.4, "fact": 2.4, "cta": 2.6}, 4, True, "calm and confident"),
    Style("punch", "Fast cuts", "Quick cuts with a zoom punch and a flash, bold caption blocks that pop in",
          Punch, "flash", 0.0, {"hook": 1.6, "product": 1.5, "fact": 1.6, "cta": 2.2}, 5, True,
          "punchy and energetic, 2 to 4 words per line"),
    Style("showcase", "Showcase", "Each photo slides in on a floating card over your brand colours",
          Showcase, "push", 0.35, {"hook": 2.3, "product": 2.5, "fact": 2.4, "cta": 2.6}, 4, False, "clear and friendly"),
    Style("magazine", "Magazine", "An editorial page: a photo panel, numbered pages, words that write themselves on",
          Magazine, "wipe", 0.4, {"hook": 2.6, "product": 2.8, "fact": 2.6, "cta": 2.8}, 3, False,
          "calm and descriptive, like a magazine caption"),
    Style("scrapbook", "Scrapbook", "Polaroids that drop onto a pile, with sticker prices",
          Scrapbook, "cut", 0.0, {"hook": 2.0, "product": 2.1, "fact": 2.1, "cta": 2.5}, 4, False, "playful and warm"),
]}


def choose_style(campaign: Campaign, post: SocialPost, avoid: str = "", rnd: random.Random | None = None) -> Style:
    """The style this campaign's other reels have used least, so a feed of reels never repeats one look."""
    others = {p.group_id or p.id: p.reel_style for p in campaign.posts
              if p.reel_style in STYLES and (p.group_id or p.id) != (post.group_id or post.id)}
    used = Counter(others.values())
    keys = list(STYLES)
    (rnd or random.Random(_seed(post))).shuffle(keys)
    keys = [k for k in keys if k != avoid] or keys
    return STYLES[min(keys, key=lambda k: used[k])]


# --------------------------------------------------------------------------- encoding


def ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001 - not installed, or no binary for this platform
        exe = shutil.which("ffmpeg")
        if not exe:
            raise ReelError("Making videos needs ffmpeg: pip install imageio-ffmpeg") from None
        return exe


def timeline(scenes: list[Scene], overlap: float) -> tuple[list[float], float]:
    starts, t = [], 0.0
    for s in scenes:
        starts.append(t)
        t += s.seconds - overlap
    return starts, t + overlap


WHITE = Image.new("RGB", (W, H), (255, 255, 255))


def tag_chip(text: str, kit: BrandKit) -> Image.Image:
    accent = rgb(kit.accent_color)
    fill = accent if luminance(accent) > 0.12 else rgb(kit.primary_color)
    return pill(text, 58 if len(text) <= 3 else 46, fill, text_on(fill))


def render_reel(kit: BrandKit, scenes: list[Scene], out: Path, poster: Path | None = None, style: Style | None = None,
                pace: float = 1.0, upper: bool | None = None, motif: str = "") -> float:
    """Render the scenes to an MP4 (H.264 + a silent AAC track, which every platform accepts).
    `pace` stretches (> 1) or tightens (< 1) every scene; `upper` forces capitals on or off.
    Returns the video's length in seconds."""
    style = style or STYLES["cinematic"]
    exe = ffmpeg_exe()
    for s in scenes:
        s.seconds = round(style.pace.get(s.kind, 2.4) * pace, 2)
    renderers: list[Base] = []
    for i, s in enumerate(scenes):
        renderers.append(style.renderer(kit, s, i, len(scenes), list(renderers), upper))
    starts, total = timeline(scenes, style.overlap)
    accent = rgb(kit.accent_color)
    tags = [tag_chip(s.tag, kit) if s.tag else None for s in scenes]
    palette = (rgb(kit.primary_color), accent, rgb(kit.secondary_color))

    def scene_frame(i: int, t: float) -> Image.Image:
        img = renderers[i].frame(t)
        if not tags[i] and not motif:
            return img
        img = img.convert("RGBA")
        if motif:
            img.alpha_composite(occasions.motif_layer(motif, (W, H), palette, t + starts[i]))
        if tags[i] is not None:  # the scene's place in the story, top right
            paste_center(img, scaled(tags[i], spring((t - 0.05) / 0.45)), W - M - tags[i].width / 2, 330)
        return img.convert("RGB")
    tmp = out.with_suffix(".part.mp4")
    cmd = [exe, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
           "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100", "-shortest",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "64k", "-movflags", "+faststart", str(tmp)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    frames = int(total * FPS)

    def draw(f: int) -> bytes:
        now = f / FPS
        live = [i for i, s in enumerate(scenes) if starts[i] <= now < starts[i] + s.seconds] or [len(scenes) - 1]
        a = live[0]
        img = scene_frame(a, now - starts[a])
        if len(live) > 1:
            b = live[1]
            k = ease_out((now - starts[b]) / max(0.01, style.overlap))
            nxt = scene_frame(b, now - starts[b])
            if style.transition == "push":  # the old page slides out as the new one slides in
                canvas = Image.new("RGB", (W, H))
                off = int(W * k)
                canvas.paste(img, (-off, 0))
                canvas.paste(nxt, (W - off, 0))
                img = canvas
            elif style.transition == "wipe":  # the new page is revealed behind a brand-colour edge
                x = int(W * k)
                img.paste(nxt.crop((0, 0, max(1, x), H)), (0, 0))
                ImageDraw.Draw(img).rectangle([x - 16, 0, x, H], fill=accent)
            else:
                img = Image.blend(img, nxt, k)
        elif style.transition == "flash" and a > 0 and now - starts[a] < 0.14:
            img = Image.blend(img, WHITE, 0.7 * (1 - (now - starts[a]) / 0.14))
        if style.bar:  # a thin progress bar along the top, like a story
            ImageDraw.Draw(img).rectangle([0, 0, int(W * (f + 1) / frames), 9], fill=accent)
        if poster and f == int(FPS * 1.2):
            img.save(poster, quality=85)
        return img.tobytes()

    # Pillow does its pixel work outside the GIL, so frames render in parallel; small ordered
    # batches keep memory flat while ffmpeg encodes.
    try:
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            for start in range(0, frames, WORKERS * 2):
                for data in pool.map(draw, range(start, min(frames, start + WORKERS * 2))):
                    proc.stdin.write(data)
        proc.stdin.close()
    except BrokenPipeError:
        pass
    err = proc.stderr.read().decode(errors="replace")
    if proc.wait() != 0:
        tmp.unlink(missing_ok=True)
        raise ReelError(f"ffmpeg couldn't encode the video: {err.strip()[:300]}")
    tmp.replace(out)
    return round(total, 1)


def resolve_options(campaign: Campaign, post: SocialPost, options: ReelOptions | None, fresh: bool) -> ReelOptions:
    """The options a render uses. Unset ones keep the reel's own; a fresh script without a chosen
    palette rotates to the campaign's least-used on-brand one."""
    current = post.reel_options
    opts = (options or current).model_copy()
    if opts.palette and opts.palette not in PALETTES and opts.palette not in ("custom", "occasion"):
        raise ReelEditError(f"Unknown colours. Pick one of: {', '.join(p.label for p in PALETTES.values())}, or a custom colour.")
    if opts.palette == "custom" and not HEX.match(opts.color or ""):
        raise ReelEditError("Pick a custom colour as #RRGGBB.")
    if opts.pace not in PACES:
        raise ReelEditError("Pace must be relaxed, normal or snappy.")
    if opts.case not in ("auto", "normal", "upper"):
        raise ReelEditError("Text must be auto, normal or upper.")
    if opts.language not in lang_mod.LANGUAGES:
        raise ReelEditError(f"Language must be one of: {', '.join(lang_mod.LANGUAGES.values())}.")
    if not opts.palette:
        opts.palette = choose_palette(campaign, post, avoid=current.palette if fresh and post.video_url else "") \
            if fresh or not current.palette else current.palette
    return opts


async def make_reel(campaign: Campaign, post: SocialPost, edited: list[ReelScene] | None = None, style_key: str | None = None,
                    options: ReelOptions | None = None, topic: str | None = None, occasion: str | None = None,
                    trend: str | None = None) -> dict:
    """Write (or take the owner's edited scenes), render and attach a reel to every platform
    version of the post. A fresh script also gets a fresh look: the campaign's least-used style
    and palette, never the ones this reel had, unless the owner picked them. Written scripts are
    humanized before they're shown; the owner's own words are kept as typed."""
    kit = campaign.brand
    if not kit:
        raise ReelError("This campaign has no brand kit yet.")
    if style_key and style_key not in STYLES:
        raise ReelEditError(f"Unknown style. Pick one of: {', '.join(s.label for s in STYLES.values())}.")
    if topic and topic not in TOPICS:
        raise ReelEditError(f"Unknown topic. Pick one of: {', '.join(label for label, _ in TOPICS.values())}.")
    if occasion and not occasions.find(occasion):
        raise ReelEditError("Unknown occasion.")
    if occasion and not topic:
        topic = "occasion"
    if trend and not topic:
        topic = "trend"
    if trend and trend not in lang_mod.TRENDS:
        raise ReelEditError("Unknown trend format.")
    opts = resolve_options(campaign, post, options, fresh=edited is None)
    rnd = random.Random()
    used_llm = False
    human: dict = {}
    if edited is not None:
        style = STYLES[style_key] if style_key else STYLES.get(post.reel_style) or choose_style(campaign, post)
        scenes = await scenes_from_edit(campaign, edited)
        topic = topic or post.reel_topic or "products"
        occasion_key = (occasions.find(occasion).key if occasion else post.reel_occasion) if topic == "occasion" else ""
    else:
        style = STYLES[style_key] if style_key else choose_style(campaign, post, avoid=post.reel_style, rnd=rnd)
        topic = topic or default_topic(campaign, post, avoid=post.reel_topic if post.video_url else "")
        if topic not in available_topics(campaign, post):
            raise ReelEditError(f"There isn't enough to make a {TOPICS[topic][0].lower()} reel for this post. Try another topic.")
        plan = plan_story(campaign, post, topic, style, rnd, occasion or "", opts.language, trend or "")
        plan, used_llm = await write_script(kit, post, plan, style, opts.language)
        topic, occasion_key = plan.topic, plan.occasion
        scenes = plan_scenes(plan)
        # The model humanizer is tuned for English; other languages get the rule pass only.
        texts, human = await humanize_lines(kit, [s.text for s in scenes], [s.kind for s in scenes],
                                            deep=used_llm and opts.language == "en")
        for s, t in zip(scenes, texts):
            s.text = t
    festive = occasions.OCCASIONS.get(occasion_key) if topic == "occasion" else None
    if festive and not (options and options.palette) and (edited is None or not post.reel_options.palette or post.reel_topic != "occasion"):
        opts.palette = "occasion"  # festive colours unless the owner picked a palette
    key = f"{campaign.id}_{post.group_id or post.id}_reel"
    out, poster = config.MEDIA_DIR / f"{key}.mp4", config.MEDIA_DIR / f"{key}.jpg"
    started = time.perf_counter()
    if opts.palette == "occasion" and festive:
        p, a, i = occasions.colors(festive, kit.country)
        look = kit.model_copy(update={"primary_color": _hex(p), "accent_color": _hex(a), "secondary_color": _hex(i)})
    else:
        look = palette_kit(kit, opts.palette if opts.palette != "occasion" else "brand", opts.color)
    upper = None if opts.case == "auto" else opts.case == "upper"
    seconds = await asyncio.to_thread(render_reel, look, scenes, out, poster, style, PACES[opts.pace], upper,
                                      festive.motif if festive else "")
    stamp = int(time.time() * 1000)
    for p in campaign.posts:
        if p.id == post.id or (post.group_id and p.group_id == post.group_id):
            p.video_url, p.video_poster = f"/media/{out.name}?v={stamp}", f"/media/{poster.name}?v={stamp}"
            p.reel_scenes, p.reel_style, p.reel_options = to_edit(scenes), style.key, opts
            p.reel_topic, p.reel_occasion = topic, occasion_key  # a trend reel keeps its format here
    return {"seconds": seconds, "scenes": [s.text for s in scenes], "used_llm": used_llm, "style": style.key,
            "topic": topic, "occasion": occasion_key,
            "options": opts.model_dump(), "humanized": human, "render_ms": int((time.perf_counter() - started) * 1000)}


def style_list() -> list[dict]:
    return [{"key": s.key, "label": s.label, "blurb": s.blurb} for s in STYLES.values()]
