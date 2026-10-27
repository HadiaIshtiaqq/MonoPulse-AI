"""Agent 7: short motion videos (Reels, Shorts, TikTok) from a post and the brand's own photos.

Nemotron writes the on-screen script (a hook, a few words per photo, a call to action); the
renderer animates it at 1080x1920: slow zooms across real product photos, text that slides
in, the price on a chip, the logo on every scene and an end card. Frames are drawn with Pillow
and piped straight into ffmpeg, so a 12-second reel renders in seconds with no video editor.
"""
from __future__ import annotations

import asyncio
import logging
import math
import shutil
import subprocess
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from .. import config
from ..llm import LLMError, router
from ..schemas import BrandKit, Campaign, Product, SocialPost
from . import strategist
from .renderer import cover_photo, fit_text, font, gradient, rgb, shade, text_on, text_scrim

log = logging.getLogger(__name__)

W, H, FPS = 1080, 1920, 30
XFADE = 0.3  # seconds two scenes overlap while one fades into the next
MAX_PHOTOS = 5
WORKERS = max(2, min(6, (os.cpu_count() or 2) - 1))
M = 84  # side margin


class ReelError(RuntimeError):
    pass


@dataclass
class Scene:
    kind: str  # hook | product | fact | cta
    text: str
    sub: str = ""  # price under a product, the website on the end card
    photo: str = ""  # local image file
    seconds: float = 2.4


# --------------------------------------------------------------------------- what goes in it


def reel_photos(campaign: Campaign, post: SocialPost) -> list[tuple[Product | None, str]]:
    """The post's own photos first, then other products the campaign already has photos of,
    one per product, so a reel shows a little of the range rather than one shot four times."""
    out: list[tuple[Product | None, str]] = []
    paths: set[str] = set()
    names: set[str] = set()

    def add(product: Product | None, bg) -> None:
        if not bg or not Path(bg.path).exists() or bg.path in paths:
            return
        if product and product.name.lower() in names:
            return
        paths.add(bg.path)
        if product:
            names.add(product.name.lower())
        out.append((product, bg.path))

    add(post.product, post.background)
    if post.gallery:
        add(post.compare, post.gallery[0])
    for slide in post.slides:
        add(None, slide.background)
    for other in sorted(campaign.posts, key=lambda p: p.publish_at):
        if len(out) >= MAX_PHOTOS:
            break
        if other.group_id != post.group_id and other.product:
            add(other.product, other.background)
    return out[:MAX_PHOTOS]


def _price(p: Product | None) -> str:
    if not p or not p.price:
        return ""
    return p.price[:-3] if p.price.endswith(".00") else p.price


def _words(text: str, limit: int) -> str:
    return strategist.fit_headline(" ".join(str(text or "").split()).strip(" \"'"), limit)


def default_cta(kit: BrandKit, post: SocialPost) -> str:
    if post.cta and len(post.cta.split()) <= 5 and "http" not in post.cta:
        return post.cta.rstrip(".")
    industry = (kit.industry or "").lower()
    if "food" in industry or "restaurant" in industry:
        return "Order yours today"
    if kit.products:
        return "Shop the collection"
    return f"Follow {kit.name}"


def fallback_script(kit: BrandKit, post: SocialPost, photos: list[tuple[Product | None, str]]) -> dict:
    claims = [strategist.short_claim(c) for c in strategist.brand_claims(kit)] or [kit.tagline or kit.name]
    lines = []
    for i, (product, _) in enumerate(photos):
        lines.append(strategist.short_name(product.name) if product else claims[i % len(claims)])
    hook = post.headline or kit.tagline or kit.name
    # Don't open on the same words the first scene shows ("New in: Chicken Crispy Roll", then "Chicken Crispy Roll").
    if lines and lines[0].lower() in hook.lower():
        hook = kit.tagline if kit.tagline and kit.tagline.lower() not in lines[0].lower() else f"This week at {kit.name}"
    return {"hook": hook, "scenes": lines, "cta": default_cta(kit, post)}


REEL_SYSTEM = """You write the on-screen text for a 10 to 15 second vertical video (an Instagram Reel, YouTube Short or TikTok) for a brand.
Each scene shows one real photo from the brand with a few words over it. The words must fit that photo.
Be specific to this brand and these products. Plain, punchy words a person would say. No hashtags, no emojis, no AI clichés
("elevate", "unleash", "indulge", "game-changer"). Do not invent prices, offers or facts.
Return JSON: {"hook": "<= 6 words that stop the scroll", "scenes": ["<= 6 words for each photo, in the same order"], "cta": "<= 5 words"}"""


async def write_script(kit: BrandKit, post: SocialPost, photos: list[tuple[Product | None, str]]) -> tuple[dict, bool]:
    base = fallback_script(kit, post, photos)
    if not router.enabled:
        return base, False
    shots = [f"{i + 1}. " + (f"{p.name}" + (f" ({_price(p)})" if _price(p) else "") if p else "a photo from the brand")
             for i, (p, _) in enumerate(photos)] or ["no photos: text on the brand colour"]
    user = (f"Brand: {strategist.brand_brief(kit)}\nPost headline: {post.headline}\nPost caption: {post.caption[:400]}\n"
            f"Photos in order:\n" + "\n".join(shots))
    try:
        data = await router.complete_json("reel_script", REEL_SYSTEM, user, temperature=0.8, max_tokens=500)
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


def plan_scenes(kit: BrandKit, script: dict, photos: list[tuple[Product | None, str]]) -> list[Scene]:
    site = (kit.website_url or "").split("//")[-1].split("/")[0].removeprefix("www.")
    scenes = [Scene("hook", _words(script["hook"], 48), photo=photos[0][1] if photos else "", seconds=2.2)]
    if photos:
        for (product, path), line in zip(photos, script["scenes"]):
            scenes.append(Scene("product", _words(line, 44), sub=_price(product), photo=path))
    else:
        claims = [strategist.short_claim(c) for c in strategist.brand_claims(kit)][:3]
        scenes += [Scene("fact", _words(c, 52)) for c in claims]
    scenes.append(Scene("cta", _words(script["cta"], 36), sub=site or kit.name, seconds=2.6))
    return scenes


# --------------------------------------------------------------------------- animation helpers


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


def text_block(text: str, width: int, max_h: int, start: int, color, align: str = "left", max_lines: int = 4,
               minimum: int = 54) -> Image.Image:
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    fnt, lines, lh = fit_text(probe, text, width, max_h, start, minimum=minimum, max_lines=max_lines)
    block = Image.new("RGBA", (width, lh * len(lines) + int(lh * 0.3)), (0, 0, 0, 0))
    d = ImageDraw.Draw(block)
    for i, line in enumerate(lines):
        x = (width - d.textlength(line, font=fnt)) / 2 if align == "center" else 0
        # A soft shadow keeps white type readable on any part of a photo.
        d.text((x + 3, i * lh + 4), line, font=fnt, fill=(0, 0, 0, 90))
        d.text((x, i * lh), line, font=fnt, fill=(*color, 255))
    return block


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


class Renderer:
    """Draws one scene at local time t (seconds from the scene's start)."""

    def __init__(self, kit: BrandKit, scene: Scene, index: int):
        self.kit, self.scene, self.index = kit, scene, index
        self.primary, self.accent = rgb(kit.primary_color), rgb(kit.accent_color)
        self.logo = logo_chip(kit, 220, 120)
        self.photo = None
        if scene.photo:
            big = (int(W * 1.16), int(H * 1.16))
            photo = cover_photo(scene.photo, big)
            if scene.kind == "hook":  # a blurred, brand-tinted version of the first photo behind the hook
                photo = photo.filter(ImageFilter.GaussianBlur(28))
                photo = Image.blend(photo, Image.new("RGB", big, shade(self.primary, 0.18)), 0.55)
            self.photo = photo
        if scene.kind == "product":
            scrim = text_scrim((W, H), "bottom", shade(self.primary, 0.08))
            # Only the dark parts need compositing each frame: keep them with their offsets.
            top_h, bottom_y = int(H * 0.18), int(H * 0.55)
            self.scrim = [(scrim.crop((0, 0, W, top_h)), 0), (scrim.crop((0, bottom_y, W, H)), bottom_y)]
            self.text = text_block(scene.text, W - 2 * M, int(H * 0.22), 112, (255, 255, 255))
            self.price = pill(scene.sub, 52, self.accent, text_on(self.accent)) if scene.sub else None
        else:
            fg = text_on(self.primary) if not self.photo else (255, 255, 255)
            self.fg = fg
            size = 120 if scene.kind != "cta" else 104
            self.text = text_block(scene.text, W - 2 * M, int(H * 0.32), size, fg, align="center", max_lines=4)
            self.bg = None if self.photo else gradient((W, H), self.primary, shade(self.primary, 0.2)).convert("RGBA")
            if not self.photo:  # blurred once; each frame only moves it
                r, pad = 620, 360
                glow = Image.new("RGBA", (2 * (r + pad), 2 * (r + pad)), (0, 0, 0, 0))
                ImageDraw.Draw(glow).ellipse([pad, pad, pad + 2 * r, pad + 2 * r], fill=(*shade(self.primary, 0.62), 70))
                self.glow = glow.filter(ImageFilter.GaussianBlur(120))
            if scene.kind == "cta":
                self.big_logo = logo_chip(self.kit, 420, 300)
                self.site = pill(scene.sub, 40, (255, 255, 255), shade(self.primary, 0.25)) if scene.sub else None

    def background(self, t: float) -> Image.Image:
        if self.photo is not None:
            # Ken Burns: alternate zooming in and out, drifting a little sideways.
            p = t / max(0.1, self.scene.seconds)
            zoom = 1.0 + 0.1 * (p if self.index % 2 == 0 else 1 - p)
            cw, ch = int(self.photo.width / 1.16 / zoom * 1.0), int(self.photo.height / 1.16 / zoom * 1.0)
            drift = (p - 0.5) * (self.photo.width - cw) * (0.6 if self.index % 2 else -0.6)
            cx = self.photo.width / 2 + drift
            cy = self.photo.height / 2
            box = (int(cx - cw / 2), int(cy - ch / 2), int(cx + cw / 2), int(cy + ch / 2))
            return self.photo.resize((W, H), Image.BILINEAR, box=box)
        # A soft glow that drifts across the brand colour, so text-only scenes still move.
        img = self.bg.copy()
        cx = int(W * (0.2 + 0.6 * (t / max(0.1, self.scene.seconds))))
        img.alpha_composite(self.glow, (cx - self.glow.width // 2, 260 - self.glow.height // 2))
        return img

    def frame(self, t: float) -> Image.Image:
        img = self.background(t).convert("RGBA")
        k = ease_out((t - 0.12) / 0.5)
        if self.scene.kind == "product":
            for part, y0 in self.scrim:
                img.alpha_composite(part, (0, y0))
            y = H - M - 150 - self.text.height - (self.price.height + 30 if self.price else 0)
            img.alpha_composite(faded(self.text, k), (M, int(y + 70 * (1 - k))))
            bar_w = int(150 * ease_out((t - 0.35) / 0.4))
            if bar_w > 2:
                ImageDraw.Draw(img).rectangle([M, y + self.text.height + 4, M + bar_w, y + self.text.height + 18], fill=(*self.accent, 255))
            if self.price:
                s = spring((t - 0.45) / 0.6)
                if s > 0.02:
                    pw, ph = max(1, int(self.price.width * s)), max(1, int(self.price.height * s))
                    chip = self.price.resize((pw, ph), Image.BILINEAR)
                    img.alpha_composite(chip, (M, y + self.text.height + 44 + (self.price.height - ph) // 2))
        elif self.scene.kind == "cta":
            top = 560
            if self.big_logo is not None:
                s = spring((t - 0.05) / 0.7)
                if s > 0.02:
                    lw, lh = max(1, int(self.big_logo.width * s)), max(1, int(self.big_logo.height * s))
                    img.alpha_composite(self.big_logo.resize((lw, lh), Image.BILINEAR), ((W - lw) // 2, top + (self.big_logo.height - lh) // 2))
                top += self.big_logo.height + 90
            k2 = ease_out((t - 0.4) / 0.5)
            img.alpha_composite(faded(self.text, k2), (M, int(top + 60 * (1 - k2))))
            top += self.text.height + 40
            bar = int(180 * ease_out((t - 0.7) / 0.4))
            if bar > 2:
                ImageDraw.Draw(img).rectangle([(W - bar) // 2, top, (W + bar) // 2, top + 12], fill=(*self.accent, 255))
            if self.site:
                k3 = ease_out((t - 0.9) / 0.5)
                img.alpha_composite(faded(self.site, k3), ((W - self.site.width) // 2, top + 70))
        else:  # hook / fact: the words rise into place in the middle of the frame
            y = (H - self.text.height) // 2 - 40
            img.alpha_composite(faded(self.text, k), (M, int(y + 90 * (1 - k))))
            bar = int(160 * ease_out((t - 0.45) / 0.4))
            if bar > 2:
                yb = y + self.text.height + 30
                ImageDraw.Draw(img).rectangle([(W - bar) // 2, yb, (W + bar) // 2, yb + 12], fill=(*self.accent, 255))
        if self.logo is not None and self.scene.kind != "cta":
            img.alpha_composite(self.logo, (M - 20, 150))
        return img.convert("RGB")


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


def timeline(scenes: list[Scene]) -> tuple[list[float], float]:
    starts, t = [], 0.0
    for s in scenes:
        starts.append(t)
        t += s.seconds - XFADE
    return starts, t + XFADE


def render_reel(kit: BrandKit, scenes: list[Scene], out: Path, poster: Path | None = None) -> float:
    """Render the scenes to an MP4 (H.264 + a silent AAC track, which every platform accepts).
    Returns the video's length in seconds."""
    exe = ffmpeg_exe()
    renderers = [Renderer(kit, s, i) for i, s in enumerate(scenes)]
    starts, total = timeline(scenes)
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
        live = [i for i, s in enumerate(scenes) if starts[i] <= now < starts[i] + s.seconds]
        img = renderers[live[0]].frame(now - starts[live[0]])
        if len(live) > 1:
            nxt = live[1]
            img = Image.blend(img, renderers[nxt].frame(now - starts[nxt]), ease_out((now - starts[nxt]) / XFADE))
        # A thin progress bar along the top, like a story.
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


async def make_reel(campaign: Campaign, post: SocialPost) -> dict:
    """Write, render and attach a reel to every platform version of the post."""
    kit = campaign.brand
    if not kit:
        raise ReelError("This campaign has no brand kit yet.")
    photos = reel_photos(campaign, post)
    script, used_llm = await write_script(kit, post, photos)
    scenes = plan_scenes(kit, script, photos)
    key = f"{campaign.id}_{post.group_id or post.id}_reel"
    out, poster = config.MEDIA_DIR / f"{key}.mp4", config.MEDIA_DIR / f"{key}.jpg"
    started = time.perf_counter()
    seconds = await asyncio.to_thread(render_reel, kit, scenes, out, poster)
    stamp = int(time.time() * 1000)
    for p in campaign.posts:
        if p.id == post.id or (post.group_id and p.group_id == post.group_id):
            p.video_url, p.video_poster = f"/media/{out.name}?v={stamp}", f"/media/{poster.name}?v={stamp}"
    return {"seconds": seconds, "scenes": [s.text for s in scenes], "used_llm": used_llm,
            "render_ms": int((time.perf_counter() - started) * 1000)}
