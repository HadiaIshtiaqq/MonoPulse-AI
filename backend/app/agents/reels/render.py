"""Turning scenes into an MP4 (frames on several threads piped into ffmpeg), and making a post's reel."""
from __future__ import annotations

import asyncio
import random
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image, ImageDraw

from ... import config
from ...schemas import BrandKit, Campaign, ReelOptions, ReelScene, SocialPost
from .. import occasions
from .. import lang as lang_mod
from ..renderer import luminance, rgb, text_on

from .core import FPS, H, M, MAX_WAITING, ReelBusy, ReelEditError, ReelError, Scene, W, WORKERS, _render_slots, _waiting
from .story import TOPICS, available_topics, default_topic, humanize_lines, plan_scenes, plan_story, scenes_from_edit, to_edit, write_script
from .draw import ease_out, paste_center, pill, scaled, spring
from .colours import HEX, PACES, PALETTES, _hex, choose_palette, palette_kit
from .styles import Base, STYLES, Style, choose_style

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
    # A few reels render at once; more wait their turn, and a long queue is turned away
    # rather than slowing every reel down.
    global _waiting
    if _waiting >= MAX_WAITING:
        raise ReelBusy("Lots of reels are being made right now. Please try again in a minute.")
    _waiting += 1
    try:
        async with _render_slots():
            seconds = await asyncio.to_thread(render_reel, look, scenes, out, poster, style, PACES[opts.pace], upper,
                                              festive.motif if festive else "")
    finally:
        _waiting -= 1
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
