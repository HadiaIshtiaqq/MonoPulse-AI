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
import math
import random
import re
import subprocess
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageFilter, ImageOps

from .. import config
from ..llm import LLMError, router
from ..schemas import BrandKit, Product
from . import strategist
from .playbooks import playbook_for, tidy_price
from .reels.core import WORKERS
from .renderer import font, rgb

log = logging.getLogger(__name__)
W, H, FPS = 1080, 1920, 30


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


def template_script(kit: BrandKit, p: Product, fmt: str) -> list[str]:
    f = facts(kit, p)
    price_line = (f"Now {f['price']}, down from {f['was']}" if f["pct"] and f["was"] else f"Just {f['price']}" if f["price"] else "")
    detail = f"From the {f['collection']} collection" if f["collection"] else (f"Only at {f['brand']}" if f["brand"] else "")
    promise = f["promises"][0] if f["promises"] else ""
    cta = random.Random(f["name"] + fmt).choice(["Link in bio", "Tap the link in bio", f"Find it at {f['site']}" if f["site"] else "Link in bio"])
    # Each reason a different fact: the price (with the saving if there is one), a promise, where it's from.
    sale = f"{f['pct']}% off right now" if f["pct"] and not f["was"] else ""
    reasons = [x for x in [price_line, sale, promise, *f["promises"][1:2], detail] if x]
    lines = {
        "pov": [f"POV: you just found the {f['name']}", price_line, detail, promise, cta],
        "first_look": [f"First look: the {f['name']}", "Look at the details", detail, price_line, f"Would you get it? {cta}"],
        "reasons": [f"{min(3, len(reasons)) or 1} reasons to get the {f['name']}"] + [f"{i + 1}. {r}" for i, r in enumerate(reasons[:3])] + [cta],
        "before_you_buy": [f"Before you buy {f['category']}, see this", f"The {f['name']}", price_line, promise or detail, cta],
        "sign": ["This is your sign to treat yourself", f"The {f['name']}", price_line, cta],
        "taste": ["Craving something good?", f"The {f['name']}", price_line, promise or (f"From {f['brand']}" if f["brand"] else ""), cta],
        "outfit": [f"Outfit check: the {f['name']}", detail or "Dress it up or keep it easy", price_line, cta],
    }.get(fmt) or [f"The {f['name']}", price_line, cta]
    return [x for x in dict.fromkeys(line.strip() for line in lines) if x][:7]


SCRIPT_SYSTEM = """You write scripts for short vertical UGC-style video ads (Reels/TikTok), spoken by a presenter showing a
product. Format: {fmt_label} ({fmt_blurb}). 4 to 6 lines; each line under 12 words, punchy, conversational, the first a
scroll-stopping hook, the last a call to action. Use ONLY the facts given (name, price, sale, collection, brand promises).
Never invent results, reviews, ratings, ingredients, materials, stock levels or claims, and never speak as a customer who used
it ("I've been using this..."). Language: {language}. Return JSON: {{"lines": ["...", "..."]}}"""


async def write_script(kit: BrandKit, p: Product, fmt: str, language: str = "English") -> tuple[list[str], bool]:
    """(lines, used_model)."""
    base = template_script(kit, p, fmt)
    if not router.enabled:
        return base, False
    label, blurb = FORMATS.get(fmt, ("Product ad", ""))
    f = facts(kit, p)
    try:
        data = await router.complete_json("rewrite", SCRIPT_SYSTEM.format(fmt_label=label, fmt_blurb=blurb, language=language),
                                          f"Brand: {kit.name}\nFacts: {f}\nA plain draft to improve on:\n" + "\n".join(base),
                                          temperature=0.8, max_tokens=500)
        lines = [str(x).strip() for x in (data.get("lines") if isinstance(data, dict) else None) or [] if str(x).strip()]
        if 3 <= len(lines) <= 8:
            return [line[:120] for line in lines], True
    except (LLMError, AttributeError) as exc:
        log.info("ugc script fell back to the template: %s", exc)
    return base, False


# --------------------------------------------------------------------------- built-in renderer


@dataclass
class Shot:
    text: str
    seconds: float
    zoom: float
    cx: float
    cy: float
    words: list[str] = field(default_factory=list)


def plan(lines: list[str], seed: int) -> list[Shot]:
    rng = random.Random(seed)
    shots = []
    for i, line in enumerate(lines):
        words = line.split()
        secs = min(4.5, max(1.6, len(words) / 2.7 + 0.7))
        # Alternate wide shots and close-ups on different parts of the product, like a phone moving around it.
        zoom = 1.06 if i == 0 else rng.choice([1.15, 1.3, 1.45]) if i % 2 else rng.choice([1.05, 1.1])
        shots.append(Shot(line, secs, zoom, rng.uniform(0.38, 0.62), rng.uniform(0.35, 0.6), words))
    return shots


def _cover(photo: Image.Image, size=(W, H)) -> Image.Image:
    return ImageOps.fit(photo.convert("RGB"), size, Image.LANCZOS)


def _wrap(draw: ImageDraw.ImageDraw, words: list[str], fnt, max_w: int) -> list[list[str]]:
    lines, cur = [], []
    for w in words:
        trial = " ".join(cur + [w])
        if cur and draw.textlength(trial, font=fnt) > max_w:
            lines.append(cur)
            cur = [w]
        else:
            cur.append(w)
    if cur:
        lines.append(cur)
    return lines


def caption(img: Image.Image, words: list[str], shown: int, accent: tuple[int, int, int]) -> None:
    """Creator-style captions: big bold white words with a dark outline, appearing as they're said;
    the newest word pops in the accent colour."""
    draw = ImageDraw.Draw(img)
    size = 92
    fnt = font(size, bold=True)
    lines = _wrap(draw, words, fnt, int(W * 0.84))
    while len(lines) > 3 and size > 56:
        size -= 8
        fnt = font(size, bold=True)
        lines = _wrap(draw, words, fnt, int(W * 0.84))
    lh = int(size * 1.18)
    y = int(H * 0.66) - (len(lines) * lh) // 2
    n = 0
    for line in lines:
        widths = [draw.textlength(w + " ", font=fnt) for w in line]
        x = (W - sum(widths) + draw.textlength(" ", font=fnt)) / 2
        for w, wd in zip(line, widths):
            if n < shown:
                fill = accent if n == shown - 1 else (255, 255, 255)
                draw.text((x, y), w, font=fnt, fill=fill, stroke_width=max(5, size // 12), stroke_fill=(15, 15, 15))
            x += wd
            n += 1
        y += lh


def bright_accent(kit: BrandKit) -> tuple[int, int, int]:
    """The brand's accent if it reads on a photo, else the classic caption yellow."""
    for c in (kit.accent_color, kit.primary_color):
        try:
            r, g, b = rgb(c)
        except (ValueError, TypeError):
            continue
        if 0.299 * r + 0.587 * g + 0.114 * b > 120:
            return r, g, b
    return 255, 221, 51


def render_builtin(kit: BrandKit, photo_path: str, lines: list[str], out: Path, poster: Path, seed: int = 0) -> float:
    """Render the ad to MP4 (H.264 with a silent track). Returns its length in seconds."""
    from .reels.render import ffmpeg_exe

    base = Image.open(photo_path)
    base = ImageOps.exif_transpose(base)
    # Oversized so the handheld drift and close-ups never show an edge.
    big = _cover(base, (int(W * 1.6), int(H * 1.6)))
    shots = plan(lines, seed)
    starts, t = [], 0.0
    for s in shots:
        starts.append(t)
        t += s.seconds
    total = t
    accent = bright_accent(kit)
    logo = None
    if kit.logo_path and Path(kit.logo_path).exists():
        logo = Image.open(kit.logo_path).convert("RGBA")
        logo.thumbnail((170, 120))
    frames = int(total * FPS)
    # A soft dark band behind the captions keeps them readable on any photo (made once, not per frame).
    band = Image.new("L", (W, H), 0)
    ImageDraw.Draw(band).rectangle([0, int(H * 0.5), W, H], fill=110)
    band = band.filter(ImageFilter.GaussianBlur(120))
    black = Image.new("RGB", (W, H), (0, 0, 0))
    tmp = out.with_name(f"{out.stem}.{uuid.uuid4().hex[:8]}.part.mp4")
    cmd = [ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
           "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100", "-shortest",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "64k", "-movflags", "+faststart", str(tmp)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    def draw(f: int) -> bytes:
        now = f / FPS
        i = max(k for k, s in enumerate(starts) if s <= now)
        shot, local = shots[i], now - starts[i]
        # Handheld: slow sway and drift, plus a quick punch-in at each cut. Crop, zoom and tilt
        # happen in one affine transform from the oversized photo (one resample per frame).
        punch = 0.06 * max(0.0, 1 - local / 0.18)
        z = shot.zoom + 0.04 * local / max(0.5, shot.seconds) + punch
        cw = big.width / (z * 1.25)
        sc = cw / W  # source pixels per output pixel
        ch = H * sc
        cx = big.width * shot.cx + 1.6 * (18 * math.sin(now * 1.7 + seed) + 7 * math.sin(now * 4.1))
        cy = big.height * shot.cy + 1.6 * (14 * math.sin(now * 1.3 + 1 + seed) + 6 * math.sin(now * 3.7))
        cx = min(max(cx, cw * 0.53), big.width - cw * 0.53)  # room for the tilt's corners
        cy = min(max(cy, ch * 0.53), big.height - ch * 0.53)
        th = math.radians(0.9 * math.sin(now * 0.8 + seed))
        a, b = sc * math.cos(th), sc * math.sin(th)
        frame = big.transform((W, H), Image.AFFINE, (a, b, cx - a * W / 2 - b * H / 2, -b, a, cy + b * W / 2 - a * H / 2),
                              resample=Image.BILINEAR)
        frame = Image.composite(black, frame, band)
        shown = min(len(shot.words), 1 + int(local * len(shot.words) / max(0.4, shot.seconds * 0.75)))
        caption(frame, shot.words, shown, accent)
        if logo is not None:
            frame.paste(logo, (60, 90), logo)
        if f == int(FPS * 1.0):
            frame.save(poster, quality=85)
        return frame.tobytes()

    try:
        # Pillow does its pixel work outside the GIL, so frames draw in parallel; small ordered
        # batches keep memory flat while ffmpeg encodes.
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            for s in range(0, frames, WORKERS * 2):
                for data in pool.map(draw, range(s, min(frames, s + WORKERS * 2))):
                    proc.stdin.write(data)
        proc.stdin.close()
    except BrokenPipeError:
        pass
    err = proc.stderr.read().decode(errors="replace")
    if proc.wait() != 0:
        tmp.unlink(missing_ok=True)
        raise UgcError(f"The video couldn't be encoded: {err.strip()[:200]}")
    tmp.replace(out)
    return round(total, 1)


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
