"""UGC-style video ads: short vertical videos in the casual, phone-shot look of creator content.

Two engines:
  * built in (free, on this computer): the product's photo filmed "handheld" (gentle drift, sway
    and punch-in cuts) with big word-by-word captions, the format that plays muted in feeds;
  * an AI presenter (HeyGen, with your key): a realistic AI person speaks the script in front of
    the product photo.

Scripts say only what's true: the product's name, price, sale, collection, and the brand's own
promises (delivery, returns...). They're written as a presenter showing the product, never as a
customer reporting results they didn't have ("I used it for a month and..."): a made-up
testimonial misleads buyers and gets ads taken down. Videos with an AI person should carry the
platform's "AI-generated" label; the app reminds you.
"""
from __future__ import annotations

import asyncio
import io
import logging
import random
import re
import time
from pathlib import Path

import httpx
from PIL import Image

from .. import config
from ..llm import LLMError, router
from ..schemas import BrandKit, Product
from . import strategist
from .playbooks import playbook_for, tidy_price

log = logging.getLogger(__name__)


class UgcError(RuntimeError):
    pass


FORMATS = {
    "pov": ("POV", "\"POV: you just found…\", the most-used hook on Reels and TikTok"),
    "first_look": ("First look", "A quick first look: the product, the details, the price"),
    "reasons": ("3 reasons", "Numbered reasons to get it, each one a real fact"),
    "before_you_buy": ("Before you buy", "\"Before you buy X, see this\": stops the scroll"),
    "sign": ("Your sign", "\"This is your sign to…\": light and shareable"),
    "taste": ("Taste test", "For food: crave-worthy close-ups and the price"),
    "outfit": ("Outfit check", "For fashion: the piece, how to wear it, the price"),
    "aesthetic": ("Aesthetic", "Soft and slow: a few quiet words on screen over music, no voice"),
}


def formats_for(kit: BrandKit) -> list[dict]:
    wear, food = strategist.is_wearable(kit), "food" in (kit.industry or "").lower()
    keys = [k for k in FORMATS if not (k == "taste" and not food) and not (k == "outfit" and not wear)]
    return [{"key": k, "label": FORMATS[k][0], "blurb": FORMATS[k][1]} for k in keys]


# --------------------------------------------------------------------------- the script

SHORT_PROMISE = re.compile(r"(free|fast|same[- ]day|nationwide|cash on delivery|cod|easy|returns?|exchange|warranty|delivery|shipping)", re.I)


def facts(kit: BrandKit, p: Product) -> dict:
    name = strategist.display_name(kit, p)
    price = tidy_price(p.price) if p.price else ""
    pct = strategist.sale_percent(p)
    collection = strategist.collection_name(p)
    promises = [c.rstrip(".") for c in kit.value_props if SHORT_PROMISE.search(c) and len(c.split()) <= 6]
    site = (kit.website_url or "").split("//")[-1].split("/")[0].removeprefix("www.")
    return {"name": name, "price": price, "pct": pct, "was": tidy_price(p.was_price) if p.was_price else "",
            "collection": collection if collection and collection.lower() not in name.lower() else "",
            "category": playbook_for(kit.industry).category, "promises": promises, "site": site, "brand": kit.name,
            "city": (kit.location or "").split(",")[0].strip()}


SCRIPT_LANGUAGES = {"en": "English", "ur": "Urdu (اردو)", "roman": "Roman Urdu"}
END_CTA = {"en": "Link in bio", "ur": "لنک بائیو میں ہے", "roman": "Link bio mein hai"}

# Words around the facts, per language. Product names, prices and the brand's own promises stay as
# the brand writes them (an Urdu voice hands English words to an English voice, as people speak).
WORDS = {
    "en": {
        "price": "Just {price}", "sale": "Now {price}, down from {was}", "pct": "{pct}% off right now",
        "detail": "From the {collection} collection", "only": "Only at {brand}", "cta": ["Link in bio", "Tap the link in bio", "Find it at {site}"],
        "pov": "POV: you just found the {name}", "first": "First look: the {name}", "look": "Look at the details", "ask": "Would you get it? {cta}",
        "reasons": "{n} reasons to get the {name}", "before": "Before you buy {category}, see this", "the": "The {name}",
        "sign": "This is your sign to treat yourself", "crave": "Craving something good?", "from": "From {brand}",
        "outfit": "Outfit check: the {name}", "wear": "Dress it up or keep it easy",
        "aes_open": "the {name}", "aes_detail": "every detail, up close",
    },
    "roman": {
        "price": "Sirf {price}", "sale": "Ab sirf {price}, pehle {was}", "pct": "Abhi {pct}% off",
        "detail": "{collection} collection se", "only": "Sirf {brand} par", "cta": ["Link bio mein hai", "Link bio mein", "{site} par dekhein"],
        "pov": "POV: aap ko mil gaya {name}", "first": "Pehli nazar: {name}", "look": "Zara details dekhein", "ask": "Lena chahenge? {cta}",
        "reasons": "{n} wajah {name} lene ki", "before": "{category} lene se pehle yeh dekhein", "the": "{name}",
        "sign": "Yeh sign hai khud ko treat karne ka", "crave": "Kuch mazedaar khane ka dil hai?", "from": "{brand} se",
        "outfit": "Aaj ka outfit: {name}", "wear": "Har mauqe ke liye",
        "aes_open": "{name}", "aes_detail": "har detail, qareeb se",
    },
    "ur": {
        "price": "صرف {price}", "sale": "اب صرف {price}، پہلے {was}", "pct": "ابھی {pct}% رعایت",
        "detail": "{collection} کلیکشن سے", "only": "صرف {brand} پر", "cta": ["لنک بائیو میں ہے", "لنک بائیو میں", "{site} پر دیکھیں"],
        "pov": "جب آپ کو مل جائے {name}", "first": "پہلی نظر: {name}", "look": "ذرا تفصیل دیکھیں", "ask": "لینا چاہیں گے؟ {cta}",
        "reasons": "{name} لینے کی {n} وجوہات", "before": "{category} لینے سے پہلے یہ دیکھیں", "the": "{name}",
        "sign": "یہ نشانی ہے کہ خود کو ٹریٹ کریں", "crave": "کچھ مزیدار کھانے کا دل ہے؟", "from": "{brand} سے",
        "outfit": "آج کا آؤٹ فٹ: {name}", "wear": "ہر موقع کے لیے",
        "aes_open": "{name}", "aes_detail": "ہر تفصیل، قریب سے",
    },
}


def template_script(kit: BrandKit, p: Product, fmt: str, language: str = "en") -> list[str]:
    f = facts(kit, p)
    w = WORDS.get(language, WORDS["en"])

    def say(key: str, **extra) -> str:
        return w[key].format(**{**f, **extra})

    price_line = (say("sale") if f["pct"] and f["was"] else say("price") if f["price"] else "")
    detail = say("detail") if f["collection"] else (say("only") if f["brand"] else "")
    promise = f["promises"][0] if f["promises"] else ""
    options = [c for c in w["cta"] if f["site"] or "{site}" not in c]
    cta = random.Random(f["name"] + fmt).choice(options).format(**f)
    # Each reason a different fact: the price (with the saving if there is one), a promise, where it's from.
    sale = say("pct") if f["pct"] and not f["was"] else ""
    reasons = [x for x in [price_line, sale, promise, *f["promises"][1:2], detail] if x]
    lines = {
        "pov": [say("pov"), price_line, detail, promise, cta],
        "first_look": [say("first"), say("look"), detail, price_line, say("ask", cta=cta)],
        "reasons": [say("reasons", n=min(3, len(reasons)) or 1)] + [f"{i + 1}. {r}" for i, r in enumerate(reasons[:3])] + [cta],
        "before_you_buy": [say("before"), say("the"), price_line, promise or detail, cta],
        "sign": [say("sign"), say("the"), price_line, cta],
        "taste": [say("crave"), say("the"), price_line, promise or (say("from") if f["brand"] else ""), cta],
        "outfit": [say("outfit"), detail or say("wear"), price_line, cta],
        "aesthetic": [say("aes_open"), say("aes_detail"), detail, price_line, cta],
    }.get(fmt) or [say("the"), price_line, cta]
    if fmt == "aesthetic" and language != "ur":  # quiet, lower-case captions; names and prices stay as written
        names = [n for n in (f["name"], f["collection"], f["brand"], f["price"]) if n]
        lines = [x[:1].lower() + x[1:] if x and not any(x.startswith(n) for n in names) else x for x in lines]
    return [x for x in dict.fromkeys(line.strip() for line in lines) if x][:7]


SCRIPT_SYSTEM = """You write scripts for short vertical UGC-style video ads (Reels/TikTok), spoken by a presenter showing a
product. Format: {fmt_label} ({fmt_blurb}). 4 to 6 lines; each line under 12 words, punchy, conversational, the first a
scroll-stopping hook, the last a call to action. Use ONLY the facts given (name, price, sale, collection, brand promises).
Never invent results, reviews, ratings, ingredients, materials, stock levels or claims, and never speak as a customer who used
it ("I've been using this..."). Language: {language}. Return JSON: {{"lines": ["...", "..."]}}"""


TRANSLITERATE = """Rewrite each line of Roman Urdu (Urdu written in Latin letters) in Urdu script, so an Urdu voice can read
it aloud. Keep the meaning and the words; don't translate or add anything. Keep brand names, product names, English
words and prices exactly as written, in Latin letters. Return JSON: {"lines": ["...", "..."]} with the same number of lines."""


async def to_urdu_script(lines: list[str]) -> list[str] | None:
    """Roman Urdu lines in Urdu letters, for the voice only (captions keep the Roman Urdu). None
    without a model, or if the answer doesn't fit (a different number of lines, or no Urdu in them)."""
    from . import lang

    if not router.enabled or not lines:
        return None
    try:
        data = await router.complete_json("transliterate", TRANSLITERATE, "\n".join(lines), temperature=0.1, max_tokens=600)
    except (LLMError, AttributeError, ValueError) as exc:
        log.info("Roman Urdu stays in Latin letters for the voice: %s", exc)
        return None
    out = [str(x).strip() for x in (data.get("lines") if isinstance(data, dict) else None) or []]
    # Every line in Urdu letters, or left exactly as it was (a line that's all English or a price).
    if len(out) != len(lines) or not all(lang.ARABIC.search(x) or x == y for x, y in zip(out, lines)) \
            or not any(lang.ARABIC.search(x) for x in out):
        return None
    return [x[:200] for x in out]


async def write_script(kit: BrandKit, p: Product, fmt: str, language: str = "en") -> tuple[list[str], bool]:
    """(lines, used_model). language: en, ur (Urdu script) or roman (Roman Urdu)."""
    base = template_script(kit, p, fmt, language)
    if not router.enabled:
        return base, False
    label, blurb = FORMATS.get(fmt, ("Product ad", ""))
    f = facts(kit, p)
    try:
        lang_name = {"ur": "Urdu in Urdu script (keep product names in English letters)", "roman": "Roman Urdu (Urdu in Latin letters)"}.get(
            language, "English")
        system = SCRIPT_SYSTEM.format(fmt_label=label, fmt_blurb=blurb, language=lang_name)
        if fmt == "aesthetic":
            system += ("\nThis one isn't spoken: it's quiet on-screen text over slow, soft video and music. Lower-case, calm, "
                       "2 to 6 words a line, no hooks or exclamation marks; keep the product name and price as written.")
        data = await router.complete_json("rewrite", system,
                                          f"Brand: {kit.name}\nFacts: {f}\nA plain draft to improve on:\n" + "\n".join(base),
                                          temperature=0.8, max_tokens=500)
        lines = [str(x).strip() for x in (data.get("lines") if isinstance(data, dict) else None) or [] if str(x).strip()]
        if 3 <= len(lines) <= 8:
            return [line[:120] for line in lines], True
    except (LLMError, AttributeError) as exc:
        log.info("ugc script fell back to the template: %s", exc)
    return base, False


# --------------------------------------------------------------------------- AI presenter (HeyGen)

HEYGEN = "https://api.heygen.com"


def heygen_ready() -> bool:
    return bool(config.HEYGEN_API_KEY)


def _hg_headers() -> dict:
    return {"x-api-key": config.HEYGEN_API_KEY}


def _hg_error(resp: httpx.Response) -> str:
    try:
        body = resp.json()
        err = body.get("error") or body.get("message") or body
        return str(err.get("message") if isinstance(err, dict) else err)[:200]
    except ValueError:
        return resp.text[:200]


async def heygen_avatars(limit: int = 40) -> list[dict]:
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(f"{HEYGEN}/v3/avatars/looks", params={"limit": min(50, limit), "ownership": "public"}, headers=_hg_headers())
    if r.status_code != 200:
        raise UgcError(f"HeyGen didn't list presenters: {_hg_error(r)}")
    return [{"id": a["id"], "name": a.get("name") or "", "preview": a.get("preview_image_url") or "", "gender": a.get("gender") or ""}
            for a in r.json().get("data") or [] if a.get("id")]


async def heygen_check(key: str) -> None:
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get(f"{HEYGEN}/v3/avatars/looks", params={"limit": 1}, headers={"x-api-key": key.strip()})
    if r.status_code != 200:
        raise UgcError("HeyGen didn't accept that key." + ("" if r.status_code in (401, 403) else f" (HTTP {r.status_code})"))


async def heygen_video(photo_path: str, avatar_id: str, script: str, out: Path, poster: Path, on_progress=None) -> float:
    """Upload the product photo as the background, have the presenter speak the script, wait for
    HeyGen to finish (it takes a few minutes), and save the video here."""
    async with httpx.AsyncClient(timeout=60) as c:
        with open(photo_path, "rb") as fh:
            up = await c.post(f"{HEYGEN}/v3/assets", headers=_hg_headers(), files={"file": (Path(photo_path).name, fh.read(), "image/jpeg")})
        if up.status_code != 200:
            raise UgcError(f"HeyGen didn't take the product photo: {_hg_error(up)}")
        asset = (up.json().get("data") or {}).get("asset_id")
        body = {"type": "avatar", "avatar_id": avatar_id, "script": script, "aspect_ratio": "9:16", "resolution": "1080p",
                "title": "MonoPlus UGC ad", "background": {"type": "image", "asset_id": asset}}
        made = await c.post(f"{HEYGEN}/v3/videos", headers=_hg_headers(), json=body)
        if made.status_code != 200:
            raise UgcError(f"HeyGen couldn't start the video: {_hg_error(made)}")
        video_id = (made.json().get("data") or {}).get("video_id")
        if not video_id:
            raise UgcError("HeyGen didn't return a video id.")
        started = time.time()
        while True:
            await asyncio.sleep(8)
            st = await c.get(f"{HEYGEN}/v3/videos/{video_id}", headers=_hg_headers())
            if st.status_code != 200:
                raise UgcError(f"HeyGen status check failed: {_hg_error(st)}")
            d = st.json().get("data") or {}
            if on_progress:
                on_progress(f"HeyGen: {d.get('status', 'working')}")
            if d.get("status") == "completed" and d.get("video_url"):
                break
            if d.get("status") == "failed":
                raise UgcError(f"HeyGen couldn't make the video: {d.get('failure_message') or d.get('failure_code') or 'unknown reason'}")
            if time.time() - started > 20 * 60:
                raise UgcError("HeyGen is taking longer than 20 minutes. Check your HeyGen dashboard; the video may still arrive there.")
        video = await c.get(d["video_url"], timeout=300)
        video.raise_for_status()
        out.write_bytes(video.content)
        if d.get("thumbnail_url"):
            thumb = await c.get(d["thumbnail_url"])
            if thumb.status_code == 200:
                Image.open(io.BytesIO(thumb.content)).convert("RGB").save(poster, quality=85)
    return 0.0
