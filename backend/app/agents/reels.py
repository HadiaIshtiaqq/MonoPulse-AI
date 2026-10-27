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
import hashlib
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
from ..schemas import BrandKit, Campaign, Product, ReelScene, SocialPost
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


def _seed(post: SocialPost) -> int:
    return int(hashlib.md5((post.group_id or post.id).encode()).hexdigest()[:8], 16)


# --------------------------------------------------------------------------- what goes in it


# (product shown, local photo, what the photo's own post or slide said about it)
Shot = tuple[Product | None, str, str]


def reel_photos(campaign: Campaign, post: SocialPost, limit: int = MAX_PHOTOS, rnd: random.Random | None = None) -> list[Shot]:
    """The post's own photos first, then other products the campaign already has photos of,
    one per product, so a reel shows a little of the range rather than one shot four times.
    With `rnd`, the others start from a different point each time, so two reels differ."""
    out: list[Shot] = []
    paths: set[str] = set()
    names: set[str] = set()

    def add(product: Product | None, bg, said: str = "") -> None:
        if not bg or not Path(bg.path).exists() or bg.path in paths:
            return
        if product and product.name.lower() in names:
            return
        paths.add(bg.path)
        if product:
            names.add(product.name.lower())
        out.append((product, bg.path, said))

    add(post.product, post.background, post.headline)
    if post.gallery:
        add(post.compare, post.gallery[0])
    for slide in post.slides:
        add(None, slide.background, slide.headline)
    others = [p for p in sorted(campaign.posts, key=lambda p: p.publish_at) if p.group_id != post.group_id]
    if rnd and others:
        start = rnd.randrange(len(others))
        others = others[start:] + others[:start]
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
    return p.price[:-3] if p.price.endswith(".00") else p.price


def _words(text: str, limit: int) -> str:
    return strategist.fit_headline(" ".join(str(text or "").split()).strip(" \"'"), limit)


def _site(kit: BrandKit) -> str:
    return (kit.website_url or "").split("//")[-1].split("/")[0].removeprefix("www.")


def cta_options(kit: BrandKit, post: SocialPost) -> list[str]:
    options = [post.cta.rstrip(".")] if post.cta and len(post.cta.split()) <= 5 and "http" not in post.cta else []
    industry = (kit.industry or "").lower()
    if "food" in industry or "restaurant" in industry:
        options += ["Order yours today", "Tap to order", "Hungry yet?", "Your table is waiting", "Order before it's gone"]
    elif kit.products:
        options += ["Shop the collection", "Shop the drop", "Find yours", "Tap to shop", "Get yours before it's gone"]
    else:
        options += [f"Follow {kit.name}", "See you soon", "Come say hi", "Book your visit"]
    return options


def default_cta(kit: BrandKit, post: SocialPost) -> str:
    return cta_options(kit, post)[0]


def hook_options(kit: BrandKit, post: SocialPost, n_photos: int) -> list[str]:
    city = (kit.location or "").split(",")[0].strip()
    options = [post.headline, kit.tagline, f"New at {kit.name} this week", f"Inside {kit.name}", f"{kit.name}, up close",
               "Wait for the last one", "Save this for later"]
    if n_photos >= 3:
        options += [f"{n_photos} picks from {kit.name}", f"Top {n_photos} right now"]
    if city:
        options += [f"{city}, this one's for you", f"Made for {city}"]
    return [o for o in options if o]


# "Spotlight: The August Rotation" -> "The August Rotation"; "11.11 sale: X" keeps its point.
LEAD_IN = re.compile(r"^(spotlight|good to know|a tip from [^:]+|tip|new in|in the details|all about[^:]*|the edit)\s*:\s*", re.I)
ASKS = re.compile(r"\?\s*$|\b(question|go-to|this or that|your vote|settle this|which (?:one|would))\b|^a tip from", re.I)


def fallback_script(kit: BrandKit, post: SocialPost, photos: list[Shot], rnd: random.Random | None = None) -> dict:
    """Words for each photo without a model: the product's name, else what the photo's own post
    said, else the brand's claims, offerings and value props, never the same line twice. With
    `rnd` the opening and closing lines are drawn from varied options instead of the first."""
    spare = [strategist.short_claim(c) for c in strategist.brand_claims(kit)]
    spare += [o for o in kit.offerings if o] + [strategist.short_claim(v) for v in kit.value_props]
    spare += [f"New at {kit.name}", "Made for every day", "Which one is yours?", f"Only at {kit.name}"]
    used: list[str] = []

    def fresh(line: str) -> bool:  # not a repeat, nor a fragment of a line already shown ("FW 2026-2027")
        low = line.lower()
        return bool(line) and not any(low in u or u in low for u in used)

    lines = []
    for product, _, said in photos:
        options = [strategist.short_name(product.name)] if product else []
        if said and not ASKS.search(said):  # "Quick question for you" says nothing about the photo
            options.append(LEAD_IN.sub("", said).strip())
        line = next((o for o in options + spare if fresh(o)), kit.name)
        used.append(line.lower())
        lines.append(line[0].upper() + line[1:])

    def repeats(text: str) -> bool:
        return any(x.lower() in text.lower() or text.lower() in x.lower() for x in lines)

    hooks = [h for h in hook_options(kit, post, len(photos)) if not repeats(h)] or [f"This week at {kit.name}"]
    ctas = cta_options(kit, post)
    hook = rnd.choice(hooks) if rnd else hooks[0]
    cta = rnd.choice(ctas) if rnd else ctas[0]
    return {"hook": hook[0].upper() + hook[1:], "scenes": lines, "cta": cta}


REEL_SYSTEM = """You write the on-screen text for a 10 to 15 second vertical video (an Instagram Reel, YouTube Short or TikTok) for a brand.
Each scene shows one real photo from the brand with a few words over it. The words must fit that photo.
Be specific to this brand and these products. Plain, punchy words a person would say. No hashtags, no emojis, no AI clichés
("elevate", "unleash", "indulge", "game-changer"). Do not invent prices, offers or facts. Vary the rhythm: not every
line should have the same shape, and don't open with "This week at" or "Discover".
Return JSON: {"hook": "<= 6 words that stop the scroll", "scenes": ["<= 6 words for each photo, in the same order"], "cta": "<= 5 words"}"""


async def write_script(kit: BrandKit, post: SocialPost, photos: list[Shot], style: "Style | None" = None,
                       rnd: random.Random | None = None) -> tuple[dict, bool]:
    base = fallback_script(kit, post, photos, rnd)
    if not router.enabled:
        return base, False
    shots = [f"{i + 1}. " + (f"{p.name}" + (f" ({_price(p)})" if _price(p) else "") if p else "a photo from the brand")
             for i, (p, _, _) in enumerate(photos)] or ["no photos: text on the brand colour"]
    user = (f"Brand: {strategist.brand_brief(kit)}\nPost headline: {post.headline}\nPost caption: {post.caption[:400]}\n"
            + (f"Video style: {style.label}. Tone: {style.tone}\n" if style else "")
            + "Photos in order:\n" + "\n".join(shots))
    try:
        data = await router.complete_json("reel_script", REEL_SYSTEM, user, temperature=0.9, max_tokens=500)
    except (LLMError, ValueError) as exc:
        log.info("reel script fell back to rules: %s", exc)
        return base, False
    if not isinstance(data, dict):
        return base, False
    scenes = [str(s) for s in (data.get("scenes") or []) if str(s).strip()]
    return {
        "hook": str(data.get("hook") or "").strip() or base["hook"],
        "scenes": [scenes[i] if i < len(scenes) else base["scenes"][i] for i in range(len(base["scenes"]))],
        "cta": str(data.get("cta") or "").strip() or base["cta"],
    }, True


def plan_scenes(kit: BrandKit, script: dict, photos: list[Shot]) -> list[Scene]:
    scenes = [Scene("hook", _words(script["hook"], 48), photo=photos[0][1] if photos else "")]
    if photos:
        for (product, path, _), line in zip(photos, script["scenes"]):
            scenes.append(Scene("product", _words(line, 44), sub=_price(product), photo=path))
    else:
        claims = [strategist.short_claim(c) for c in strategist.brand_claims(kit)][:3]
        scenes += [Scene("fact", _words(c, 52)) for c in claims]
    scenes.append(Scene("cta", _words(script["cta"], 36), sub=_site(kit) or kit.name))
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
        out.append(Scene(kind, " ".join(s.text.split())[:80], sub=" ".join(s.sub.split())[:40], photo=path))
    return out


def to_edit(scenes: list[Scene]) -> list[ReelScene]:
    return [ReelScene(kind=s.kind, text=s.text, sub=s.sub, photo=media_url(s.photo)) for s in scenes]


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
        img = Image.new("RGBA", (int(probe.textlength(line, font=fnt)) + 8, lh), (0, 0, 0, 0))
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
        block = Image.new("RGBA", (tw + 2 * pad_x, int(fnt.size * 1.18) + 2 * pad_y), (0, 0, 0, 0))
        d = ImageDraw.Draw(block)
        d.rounded_rectangle([0, 0, block.width - 1, block.height - 1], radius=int(fnt.size * 0.18), fill=(*fill, 255))
        d.text((pad_x, pad_y), line, font=fnt, fill=(*text_on(fill), 255))
        out.append(block.rotate((-2.2 if i % 2 else 1.8) if tilt else 0, expand=True, resample=Image.BICUBIC))
    return out


def pill(text: str, size: int, fill, fg) -> Image.Image:
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


# --------------------------------------------------------------------------- styles


class Base:
    """Draws one scene of a reel at local time t (seconds from the scene's start)."""
    upper = False

    def __init__(self, kit: BrandKit, scene: Scene, index: int, count: int, prev: list["Base"]):
        self.kit, self.scene, self.index, self.count, self.prev = kit, scene, index, count, prev
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


def render_reel(kit: BrandKit, scenes: list[Scene], out: Path, poster: Path | None = None, style: Style | None = None) -> float:
    """Render the scenes to an MP4 (H.264 + a silent AAC track, which every platform accepts).
    Returns the video's length in seconds."""
    style = style or STYLES["cinematic"]
    exe = ffmpeg_exe()
    for s in scenes:
        s.seconds = style.pace.get(s.kind, 2.4)
    renderers: list[Base] = []
    for i, s in enumerate(scenes):
        renderers.append(style.renderer(kit, s, i, len(scenes), list(renderers)))
    starts, total = timeline(scenes, style.overlap)
    accent = rgb(kit.accent_color)
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
        img = renderers[a].frame(now - starts[a])
        if len(live) > 1:
            b = live[1]
            k = ease_out((now - starts[b]) / max(0.01, style.overlap))
            nxt = renderers[b].frame(now - starts[b])
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


async def make_reel(campaign: Campaign, post: SocialPost, edited: list[ReelScene] | None = None, style_key: str | None = None) -> dict:
    """Write (or take the owner's edited scenes), render and attach a reel to every platform
    version of the post. A fresh script also gets a fresh look: the campaign's least-used style,
    never the one this reel had, unless the owner picked a style."""
    kit = campaign.brand
    if not kit:
        raise ReelError("This campaign has no brand kit yet.")
    if style_key and style_key not in STYLES:
        raise ReelEditError(f"Unknown style. Pick one of: {', '.join(s.label for s in STYLES.values())}.")
    rnd = random.Random()
    used_llm = False
    if edited is not None:
        style = STYLES[style_key] if style_key else STYLES.get(post.reel_style) or choose_style(campaign, post)
        scenes = await scenes_from_edit(campaign, edited)
    else:
        style = STYLES[style_key] if style_key else choose_style(campaign, post, avoid=post.reel_style, rnd=rnd)
        photos = reel_photos(campaign, post, style.photos, rnd)
        script, used_llm = await write_script(kit, post, photos, style, rnd)
        scenes = plan_scenes(kit, script, photos)
    key = f"{campaign.id}_{post.group_id or post.id}_reel"
    out, poster = config.MEDIA_DIR / f"{key}.mp4", config.MEDIA_DIR / f"{key}.jpg"
    started = time.perf_counter()
    seconds = await asyncio.to_thread(render_reel, kit, scenes, out, poster, style)
    stamp = int(time.time() * 1000)
    for p in campaign.posts:
        if p.id == post.id or (post.group_id and p.group_id == post.group_id):
            p.video_url, p.video_poster = f"/media/{out.name}?v={stamp}", f"/media/{poster.name}?v={stamp}"
            p.reel_scenes, p.reel_style = to_edit(scenes), style.key
    return {"seconds": seconds, "scenes": [s.text for s in scenes], "used_llm": used_llm, "style": style.key,
            "render_ms": int((time.perf_counter() - started) * 1000)}


def style_list() -> list[dict]:
    return [{"key": s.key, "label": s.label, "blurb": s.blurb} for s in STYLES.values()]
