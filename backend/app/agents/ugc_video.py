"""The UGC ad videos themselves.

Product ads ("phone-style"): every ad gets its own mix, chosen per ad, so two ads never look alike:
  * a layout: full-screen photo, a floating card on a blurred backdrop, photo-over-colour split, a
    tilted polaroid, or a framed screen;
  * a camera move per shot, never the same twice in a row: handheld, slow push-in, pull-out reveal,
    pan, beat pops on each word, Dutch tilt, orbit;
  * a cut between shots: punch-in, whip pan, flash or zoom blur;
  * a caption style: outlined words, highlighted word boxes, karaoke, one word at a time, or a
    clean subtitle bar;
  * and a branded end card.
With a voiceover, shots follow the voice.

Real-person ads: your own video (recorded in the app or uploaded), trimmed to the speech, with
captions that follow what was actually said, the product popping in when it's mentioned, your logo,
and the same end card.
"""
from __future__ import annotations

import difflib
import math
import random
import re
import subprocess
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageOps

from ..schemas import BrandKit
from .reels.core import WORKERS
from .renderer import font, rgb

W, H, FPS = 1080, 1920, 30
LOOKS = ["full", "card", "split", "polaroid", "frame"]
MOTIONS = ["handheld", "push_in", "pull_out", "pan", "beat", "dutch", "orbit"]
CAPTIONS = ["outline", "box", "karaoke", "pop", "bar"]
CUTS = ["punch", "whip", "flash", "zoom"]
LOOK_LABELS = {"full": "Full screen", "card": "Floating card", "split": "Photo + colour", "polaroid": "Polaroid", "frame": "Framed"}
CAPTION_LABELS = {"outline": "Outlined", "box": "Highlight box", "karaoke": "Karaoke", "pop": "One word at a time", "bar": "Subtitle bar"}


class VideoError(RuntimeError):
    pass


# --------------------------------------------------------------------------- style choice

@dataclass
class Mix:
    look: str
    caption: str
    cut: str
    motions: list[str]
    seed: int


def choose_mix(n_shots: int, seed: int, look: str = "", caption: str = "", avoid: dict | None = None) -> Mix:
    """A mix for this ad: chosen layout and caption style if given, else a random one that differs
    from the brand's last ad (avoid), and a camera move per shot that never repeats back to back."""
    rng = random.Random(seed)
    avoid = avoid or {}
    look = look if look in LOOKS else rng.choice([x for x in LOOKS if x != avoid.get("look")] or LOOKS)
    caption = caption if caption in CAPTIONS else rng.choice([x for x in CAPTIONS if x != avoid.get("caption")] or CAPTIONS)
    motions: list[str] = []
    for _ in range(n_shots):
        motions.append(rng.choice([m for m in MOTIONS if not motions or m != motions[-1]]))
    return Mix(look, caption, rng.choice(CUTS), motions, seed)


# --------------------------------------------------------------------------- drawing helpers

def ink_for(c: tuple[int, int, int]) -> tuple[int, int, int]:
    return (17, 17, 17) if 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2] > 150 else (255, 255, 255)


def bright(kit: BrandKit) -> tuple[int, int, int]:
    for c in (kit.accent_color, kit.primary_color):
        try:
            r, g, b = rgb(c)
        except (ValueError, TypeError):
            continue
        if 0.299 * r + 0.587 * g + 0.114 * b > 120:
            return r, g, b
    return 255, 221, 51


def safe_rgb(hex_color: str, fallback=(91, 71, 251)) -> tuple[int, int, int]:
    try:
        return rgb(hex_color)
    except (ValueError, TypeError):
        return fallback


def rounded_mask(size: tuple[int, int], r: int) -> Image.Image:
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, size[0] - 1, size[1] - 1], r, fill=255)
    return m


def shadow(size: tuple[int, int], r: int, blur: int = 40, alpha: int = 120) -> Image.Image:
    pad = blur * 2
    s = Image.new("RGBA", (size[0] + pad * 2, size[1] + pad * 2), (0, 0, 0, 0))
    ImageDraw.Draw(s).rounded_rectangle([pad, pad, pad + size[0], pad + size[1]], r, fill=(0, 0, 0, alpha))
    return s.filter(ImageFilter.GaussianBlur(blur))


# --------------------------------------------------------------------------- camera

def motion(kind: str, local: float, dur: float, now: float, seed: int) -> tuple[float, float, float, float]:
    """(zoom, x offset, y offset, tilt degrees) for a camera move, offsets as fractions of the frame."""
    p = min(1.0, local / max(0.3, dur))
    if kind == "push_in":
        return 1.05 + 0.22 * p, 0.0, 0.0, 0.0
    if kind == "pull_out":
        return 1.35 - 0.25 * (1 - (1 - p) ** 2), 0.0, 0.0, 0.0
    if kind == "pan":
        d = 1 if seed % 2 else -1
        return 1.3, d * (0.12 - 0.24 * p), 0.0, 0.0
    if kind == "beat":  # small zoom pops, about two a second, like cuts on the beat
        return 1.12 + 0.07 * (math.floor(local * 2.2) % 2) + 0.02 * p, 0.0, 0.0, 0.0
    if kind == "dutch":
        return 1.2 + 0.08 * p, 0.0, 0.02 * math.sin(now), 4.5
    if kind == "orbit":
        return 1.18 + 0.05 * math.sin(now * 1.1), 0.05 * math.sin(now * 0.9), 0.04 * math.cos(now * 0.9), 2.5 * math.sin(now * 0.7)
    # handheld: sway, drift, a slight wobble
    return (1.12 + 0.05 * p, 0.012 * math.sin(now * 1.7 + seed) + 0.005 * math.sin(now * 4.1),
            0.01 * math.sin(now * 1.3 + 1 + seed) + 0.004 * math.sin(now * 3.7), 0.9 * math.sin(now * 0.8 + seed))


def shot_image(big: Image.Image, size: tuple[int, int], z: float, fx: float, fy: float, tilt: float, focus=(0.5, 0.5)) -> Image.Image:
    """A view into the oversized photo: zoom, position and tilt in one transform (one resample)."""
    w, h = size
    k = min(big.width / w, big.height / h) / z  # source pixels per output pixel
    cw, ch = w * k, h * k
    cx = big.width * focus[0] + fx * big.width
    cy = big.height * focus[1] + fy * big.height
    cx = min(max(cx, cw * 0.55), big.width - cw * 0.55)
    cy = min(max(cy, ch * 0.55), big.height - ch * 0.55)
    th = math.radians(tilt)
    a, b = k * math.cos(th), k * math.sin(th)
    return big.transform((w, h), Image.AFFINE, (a, b, cx - a * w / 2 - b * h / 2, -b, a, cy + b * w / 2 - a * h / 2),
                         resample=Image.BILINEAR)


# --------------------------------------------------------------------------- captions

def _wrap(draw, words, fnt, max_w):
    lines, cur = [], []
    for w in words:
        if cur and draw.textlength(" ".join(cur + [w]), font=fnt) > max_w:
            lines.append(cur)
            cur = [w]
        else:
            cur.append(w)
    if cur:
        lines.append(cur)
    return lines


def draw_caption(img: Image.Image, style: str, words: list[str], shown: int, accent, box: tuple[int, int, int, int],
                 ink=(255, 255, 255), panel=None) -> None:
    """Captions in one of several creator styles, inside box (x0, y0, x1, y1)."""
    if not words or shown <= 0:
        return
    draw = ImageDraw.Draw(img)
    x0, y0, x1, y1 = box
    if style == "pop":  # one or two words at a time, huge
        i = shown - 1
        chunk = " ".join(words[max(0, i - (1 if len(words[i]) < 4 else 0)): i + 1])
        size = 150
        fnt = font(size, True)
        while draw.textlength(chunk, font=fnt) > (x1 - x0) and size > 70:
            size -= 10
            fnt = font(size, True)
        tw = draw.textlength(chunk, font=fnt)
        draw.text(((x0 + x1 - tw) / 2, (y0 + y1) / 2 - size * 0.6), chunk, font=fnt, fill=accent, stroke_width=size // 11,
                  stroke_fill=(15, 15, 15))
        return
    size = 84 if style != "bar" else 58
    fnt = font(size, True)
    visible = words if style == "karaoke" else words[:shown]
    lines = _wrap(draw, words, fnt, x1 - x0 - 40)
    while len(lines) > 3 and size > 48:
        size -= 6
        fnt = font(size, True)
        lines = _wrap(draw, words, fnt, x1 - x0 - 40)
    lh = int(size * 1.3)
    y = (y0 + y1) // 2 - len(lines) * lh // 2
    if style == "bar":
        top = y - 24
        bar = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(bar).rounded_rectangle([x0 + 10, top, x1 - 10, y + len(lines) * lh + 18], 28,
                                              fill=(*(panel or (0, 0, 0)), 170))
        img.paste(bar, (0, 0), bar)
    n = 0
    for line in lines:
        widths = [draw.textlength(w + " ", font=fnt) for w in line]
        x = (x0 + x1 - sum(widths) + draw.textlength(" ", font=fnt)) / 2
        for w, wd in zip(line, widths):
            said, newest = n < shown, n == shown - 1
            if style == "karaoke":  # the whole line on screen, lighting up as it's said
                fill = accent if newest else ink if said else tuple(int(c * 0.45 + 40) for c in ink)
                draw.text((x, y), w, font=fnt, fill=fill, stroke_width=size // 14, stroke_fill=(15, 15, 15))
            elif n < len(visible):
                if style == "box" and newest:
                    pad = size * 0.16
                    draw.rounded_rectangle([x - pad, y - pad * 0.5, x + wd - draw.textlength(" ", font=fnt) + pad, y + size + pad], 14, fill=accent)
                    draw.text((x, y), w, font=fnt, fill=ink_for(accent))
                elif style == "bar":
                    draw.text((x, y), w, font=fnt, fill=accent if newest else (255, 255, 255))
                else:
                    draw.text((x, y), w, font=fnt, fill=accent if newest else ink, stroke_width=max(5, size // 12), stroke_fill=(15, 15, 15))
            x += wd
            n += 1
        y += lh


# --------------------------------------------------------------------------- the end card

def end_card(kit: BrandKit, title: str, price: str, cta: str, logo: Image.Image | None, p: float, variant: int) -> Image.Image:
    primary, accent = safe_rgb(kit.primary_color), bright(kit)
    bg = primary if variant % 2 == 0 else (17, 17, 17)
    img = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img)
    ink = ink_for(bg)
    if sum(abs(x - y) for x, y in zip(accent, bg)) < 160:  # the accent would vanish on this background
        accent = (255, 221, 51) if ink == (255, 255, 255) else (17, 17, 17)
    k = 1 - (1 - min(1.0, p / 0.35)) ** 3  # ease in
    y = int(H * 0.3 + (1 - k) * 120)
    if logo is not None:
        lg = logo.copy()
        lg.thumbnail((360, 260))
        plate = Image.new("RGBA", (lg.width + 60, lg.height + 60), (255, 255, 255, 235))
        plate.putalpha(rounded_mask(plate.size, 36).point(lambda v: int(v * 0.92)))
        img.paste(plate, ((W - plate.width) // 2, y - plate.height - 40), plate)
        img.paste(lg, ((W - lg.width) // 2, y - plate.height - 10), lg)
    for text, size, color in ((title, 76, ink), (price, 96, accent), (cta, 58, ink)):
        if not text:
            continue
        fnt = font(size, True)
        for line in _wrap(d, text.split(), fnt, W - 160)[:2]:
            s = " ".join(line)
            d.text(((W - d.textlength(s, font=fnt)) / 2, y), s, font=fnt, fill=color)
            y += int(size * 1.25)
        y += 30
    return img


# --------------------------------------------------------------------------- product ads

@dataclass
class Shot:
    text: str
    seconds: float
    words: list[str] = field(default_factory=list)
    focus: tuple[float, float] = (0.5, 0.5)


def render_product_ad(kit: BrandKit, photo_path: str, lines: list[str], out: Path, poster: Path, mix: Mix,
                      durations: list[float] | None = None, voice_wav: str = "", end: tuple[str, str, str] = ("", "", "")) -> float:
    """The phone-style product ad. Returns its length in seconds."""
    rng = random.Random(mix.seed)
    photo = ImageOps.exif_transpose(Image.open(photo_path)).convert("RGB")
    big = ImageOps.fit(photo, (int(W * 1.5), int(H * 1.5)), Image.LANCZOS)
    shots = []
    for i, line in enumerate(lines):
        words = line.split()
        secs = durations[i] if durations and i < len(durations) else min(4.5, max(1.6, len(words) / 2.7 + 0.7))
        shots.append(Shot(line, secs, words, (rng.uniform(0.38, 0.62), rng.uniform(0.35, 0.62))))
    starts, t = [], 0.0
    for s in shots:
        starts.append(t)
        t += s.seconds
    talk = t
    end_secs = 1.8 if any(end) else 0.0
    total = talk + end_secs
    primary, accent = safe_rgb(kit.primary_color), bright(kit)
    logo = Image.open(kit.logo_path).convert("RGBA") if kit.logo_path and Path(kit.logo_path).exists() else None
    small_logo = None
    if logo is not None:
        small_logo = logo.copy()
        small_logo.thumbnail((170, 120))

    # What doesn't change frame to frame, made once.
    look = mix.look
    backdrop = None
    if look == "card":
        backdrop = ImageOps.fit(photo, (W, H)).filter(ImageFilter.GaussianBlur(45))
        backdrop = Image.blend(backdrop, Image.new("RGB", (W, H), primary), 0.35)
    card_size = (int(W * 0.82), int(H * 0.56)) if look == "card" else (int(W * 0.78), int(W * 0.95)) if look == "polaroid" else (W, H)
    card_mask = rounded_mask(card_size, 48) if look == "card" else None
    card_shadow = shadow(card_size, 48) if look in ("card", "polaroid") else None
    split_h = int(H * 0.6)
    band = Image.new("L", (W, H), 0)
    ImageDraw.Draw(band).rectangle([0, int(H * 0.52), W, H], fill=105)
    band = band.filter(ImageFilter.GaussianBlur(110))
    black = Image.new("RGB", (W, H), (0, 0, 0))
    pol_bg = Image.new("RGB", (W, H), primary)
    frame_mask = rounded_mask((W - 80, H - 80), 56) if look == "frame" else None

    def view(i: int, local: float, now: float, size) -> Image.Image:
        s = shots[i]
        z, fx, fy, tilt = motion(mix.motions[i % len(mix.motions)], local, s.seconds, now, mix.seed + i)
        if local < 0.2 and i > 0:  # the cut into this shot
            k = 1 - local / 0.2
            if mix.cut == "punch":
                z += 0.12 * k
            elif mix.cut == "zoom":
                z += 0.35 * k
            elif mix.cut == "whip":
                fx += 0.25 * k * (1 if i % 2 else -1)
        img = shot_image(big, size, z, fx, fy, tilt, s.focus)
        if local < 0.2 and i > 0 and mix.cut in ("whip", "zoom"):
            img = img.filter(ImageFilter.BoxBlur(int(18 * (1 - local / 0.2))))
        return img

    def compose(i: int, local: float, now: float) -> Image.Image:
        s = shots[i]
        shown = min(len(s.words), 1 + int(local * len(s.words) / max(0.4, s.seconds * 0.78)))
        if look == "card":
            frame = backdrop.copy()
            float_y = int(14 * math.sin(now * 1.4))
            card = view(i, local, now, card_size)
            pos = ((W - card_size[0]) // 2, int(H * 0.12) + float_y)
            frame.paste(card_shadow, (pos[0] - 80, pos[1] - 60), card_shadow)
            frame.paste(card, pos, card_mask)
            draw_caption(frame, mix.caption, s.words, shown, accent, (60, int(H * 0.7), W - 60, int(H * 0.92)))
        elif look == "split":
            frame = Image.new("RGB", (W, H), primary)
            frame.paste(view(i, local, now, (W, split_h)), (0, 0))
            draw_caption(frame, mix.caption, s.words, shown, accent if accent != primary else (255, 255, 255),
                         (60, split_h + 30, W - 60, H - 80), ink=ink_for(primary), panel=primary)
        elif look == "polaroid":
            frame = pol_bg.copy()
            card = view(i, local, now, card_size)
            border = Image.new("RGB", (card_size[0] + 60, card_size[1] + 200), (250, 250, 247))
            border.paste(card, (30, 30))
            angle = -3 + 2 * math.sin(now * 0.6)
            rot = border.convert("RGBA").rotate(angle, resample=Image.BICUBIC, expand=True)
            frame.paste(rot, ((W - rot.width) // 2, int(H * 0.08)), rot)
            draw_caption(frame, mix.caption, s.words, shown, accent if accent != primary else (255, 255, 255),
                         (60, int(H * 0.72), W - 60, int(H * 0.94)), ink=ink_for(primary))
        else:
            frame = view(i, local, now, (W, H))
            frame = Image.composite(black, frame, band)
            if look == "frame":
                outer = Image.new("RGB", (W, H), primary)
                outer.paste(frame.resize((W - 80, H - 80)), (40, 40), frame_mask)
                frame = outer
            draw_caption(frame, mix.caption, s.words, shown, accent, (60, int(H * 0.56), W - 60, int(H * 0.8)))
        if small_logo is not None and look != "polaroid":
            frame.paste(small_logo, (70, 100), small_logo)
        if mix.cut == "flash" and i > 0 and local < 0.12:
            frame = Image.blend(frame, Image.new("RGB", (W, H), (255, 255, 255)), 0.75 * (1 - local / 0.12))
        return frame

    def draw(f: int) -> bytes:
        now = f / FPS
        if now >= talk:
            img = end_card(kit, *end, logo, now - talk, mix.seed)
        else:
            i = max(k for k, s in enumerate(starts) if s <= now)
            img = compose(i, now - starts[i], now)
        if f == int(FPS * 1.0):
            img.save(poster, quality=85)
        return img.tobytes()

    _encode(out, int(total * FPS), draw, audio=voice_wav)
    return round(total, 1)


def _encode(out: Path, frames: int, draw, audio: str = "", audio_start: float = 0.0, audio_end: float | None = None) -> None:
    """Draw frames in parallel (Pillow works outside the GIL) and encode H.264 + AAC with ffmpeg.
    Audio: a file (voice or the person's own sound, padded with silence), or a silent track."""
    from .reels.render import ffmpeg_exe

    tmp = out.with_name(f"{out.stem}.{uuid.uuid4().hex[:8]}.part.mp4")
    cmd = [ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-"]
    seconds = frames / FPS
    # The exact length instead of -shortest: ffmpeg 7 fails ("No space left on device") when a
    # padded audio track meets -shortest.
    if audio:
        if audio_start:
            cmd += ["-ss", f"{audio_start:.3f}"]
        if audio_end is not None:
            cmd += ["-to", f"{audio_end:.3f}"]
        cmd += ["-i", audio, "-map", "0:v", "-map", "1:a", "-af", f"apad=whole_dur={seconds:.3f}"]
    else:
        cmd += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
    cmd += ["-t", f"{seconds:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart", str(tmp)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
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
        raise VideoError(f"The video couldn't be encoded: {err.strip()[:200]}")
    tmp.replace(out)


# --------------------------------------------------------------------------- real-person ads

def _norm(w: str) -> str:
    return re.sub(r"[^a-z0-9]", "", w.lower())


def align_to_script(heard: list, script: list[str]) -> list[tuple[str, float, float]]:
    """Caption words for a real person's video: what Whisper heard, with the script's spelling
    wherever the person was reading it ("Rs. 450", the product's exact name). Words said off-script
    stay as heard; words in the script that weren't said are never added."""
    said = _tidy([(w.text, w.start, w.end) for w in heard])
    if not script:
        return said
    sw = [w for line in script for w in line.split()]
    sm = difflib.SequenceMatcher(a=[_norm(t) for t, _, _ in said], b=[_norm(w) for w in sw], autojunk=False)
    out = list(said)
    ops = sm.get_opcodes()
    for n, (tag, i1, i2, j1, j2) in enumerate(ops):
        # Between two stretches read word for word, a mismatch is still the script, misheard.
        anchored = (n == 0 or ops[n - 1][0] == "equal") and (n == len(ops) - 1 or ops[n + 1][0] == "equal")
        if tag == "equal":
            for k in range(i2 - i1):
                out[i1 + k] = (sw[j1 + k], said[i1 + k][1], said[i1 + k][2])
        elif tag == "replace" and (i2 - i1) == (j2 - j1) and i2 - i1 <= 3:  # a near-miss, like "Puff" for "POV"
            for k in range(i2 - i1):
                h, s = _norm(said[i1 + k][0]), _norm(sw[j1 + k])
                if difflib.SequenceMatcher(a=h, b=s).ratio() >= 0.5 or (h[:1] == s[:1] and len(h) <= 5 and len(s) <= 5):
                    out[i1 + k] = (sw[j1 + k], said[i1 + k][1], said[i1 + k][2])
        elif tag == "replace" and i2 - i1 <= 4 and j2 - j1 <= 4:
            # A phrase heard in a different number of pieces ("P -O -V" for "POV:", "seat at Sourdo" for
            # "Seeded Sourdough"): if it sounds the same as a whole, the script's words take its time span.
            h = "".join(_norm(t) for t, _, _ in said[i1:i2])
            s = "".join(_norm(w) for w in sw[j1:j2])
            if difflib.SequenceMatcher(a=h, b=s).ratio() >= (0.5 if anchored else 0.65):
                t0, t1 = said[i1][1], said[i2 - 1][2]
                step = (t1 - t0) / (j2 - j1)
                spread = [(sw[j1 + k], t0 + k * step, t0 + (k + 1) * step) for k in range(j2 - j1)]
                out[i1:i2] = [None] * (i2 - i1)  # replaced below, keeping indexes stable while the opcodes run
                out[i1] = spread  # type: ignore[call-overload]
    flat: list[tuple[str, float, float]] = []
    for item in out:
        if isinstance(item, list):
            flat.extend(item)
        elif item is not None:
            flat.append(item)
    return flat


def _tidy(words: list[tuple[str, float, float]]) -> list[tuple[str, float, float]]:
    """Common mishearings of money words fixed, and number pieces joined ("12" ",990" -> "12,990")."""
    fixed: list[tuple[str, float, float]] = []
    for text, s, e in ((MISHEARD.get(_norm(t), t), s, e) for t, s, e in words):
        if fixed and re.match(r"^[,.]\d", text) and re.search(r"\d$", fixed[-1][0]):
            fixed[-1] = (fixed[-1][0] + text, fixed[-1][1], e)
        else:
            fixed.append((text, s, e))
    return fixed


MISHEARD = {"robies": "rupees", "rupies": "rupees", "rupes": "rupees", "roopees": "rupees", "rupis": "rupees"}


def mentions(words: list[tuple[str, float, float]], terms: list[str], hold: float = 2.0) -> list[tuple[float, float]]:
    """When the product (its name or price) is mentioned: windows to show the product photo in."""
    keys = {_norm(t) for term in terms for t in term.split() if len(_norm(t)) >= 3}
    spans: list[tuple[float, float]] = []
    for text, start, _ in words:
        if _norm(text) in keys and (not spans or start > spans[-1][1]):
            spans.append((start, start + hold))
    return spans


def probe_duration(path: str) -> float:
    from .reels.render import ffmpeg_exe

    proc = subprocess.run([ffmpeg_exe(), "-i", path], capture_output=True, text=True, errors="replace")
    if "Video:" not in proc.stderr:
        raise VideoError("That file doesn't look like a video.")
    m = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", proc.stderr)
    if m:
        return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    # Browser recordings (WebM from MediaRecorder) carry no duration: read through the file to measure it.
    proc = subprocess.run([ffmpeg_exe(), "-i", path, "-f", "null", "-"], capture_output=True, text=True, errors="replace", timeout=300)
    times = re.findall(r"time=(\d+):(\d+):(\d+\.\d+)", proc.stderr)
    if not times:
        raise VideoError("That video couldn't be read.")
    h, mnt, s = times[-1]
    return int(h) * 3600 + int(mnt) * 60 + float(s)


def render_person_ad(kit: BrandKit, video_path: str, words: list[tuple[str, float, float]], product_photo: str, terms: list[str],
                     out: Path, poster: Path, caption: str, seed: int, end: tuple[str, str, str] = ("", "", "")) -> float:
    """Your video, trimmed to the speech, upright 9:16, with captions that follow what was said, the
    product popping in when it's mentioned, your logo and an end card."""
    from .reels.render import ffmpeg_exe

    length = probe_duration(video_path)
    start = max(0.0, (words[0][1] - 0.35) if words else 0.0)
    stop = min(length, (words[-1][2] + 0.6) if words else length)
    talk = max(1.0, stop - start)
    end_secs = 1.8 if any(end) else 0.0
    total = talk + end_secs
    frames, talk_frames = int(total * FPS), int(talk * FPS)
    accent = bright(kit)
    logo = Image.open(kit.logo_path).convert("RGBA") if kit.logo_path and Path(kit.logo_path).exists() else None
    small_logo = None
    if logo is not None:
        small_logo = logo.copy()
        small_logo.thumbnail((170, 120))
    product = ImageOps.exif_transpose(Image.open(product_photo)).convert("RGB") if product_photo else None
    pip_size = (int(W * 0.5), int(W * 0.5))
    pip = ImageOps.fit(product, pip_size) if product else None
    pip_mask = rounded_mask(pip_size, 40)
    pip_shadow = shadow(pip_size, 40, blur=30)
    shown_spans = mentions(words, terms)
    local_words = [(t, s - start, e - start) for t, s, e in words]
    # Caption groups: a few words at a time, like creator captions.
    groups, cur = [], []
    for w in local_words:
        cur.append(w)
        if len(cur) >= 4 or w[0].endswith((".", "!", "?", ",")):
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    band = Image.new("L", (W, H), 0)
    ImageDraw.Draw(band).rectangle([0, int(H * 0.55), W, H], fill=90)
    band = band.filter(ImageFilter.GaussianBlur(110))
    black = Image.new("RGB", (W, H), (0, 0, 0))

    # Decode the clip upright, cropped to 9:16, at 30 fps.
    dec = subprocess.Popen([ffmpeg_exe(), "-loglevel", "error", "-ss", f"{start:.3f}", "-to", f"{stop:.3f}", "-i", video_path,
                            "-vf", f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS}",
                            "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    size = W * H * 3
    last = [Image.new("RGB", (W, H), (0, 0, 0))]

    def next_frame() -> Image.Image:
        data = dec.stdout.read(size)
        if len(data) == size:
            last[0] = Image.frombytes("RGB", (W, H), data)
        return last[0].copy()

    def draw(f: int, img: Image.Image | None) -> bytes:
        now = f / FPS
        if f >= talk_frames:
            frame = end_card(kit, *end, logo, now - talk, seed)
        else:
            frame = Image.composite(black, img, band)
            for s0, s1 in shown_spans:
                if s0 <= now < s1 and pip is not None:
                    k = min(1.0, (now - s0) / 0.25, (s1 - now) / 0.25)
                    x = int(W - pip_size[0] - 60 + (1 - k) * (pip_size[0] + 80))
                    frame.paste(pip_shadow, (x - 60, 220 - 60), pip_shadow)
                    frame.paste(pip, (x, 220), pip_mask)
            group = next((g for g in groups if g[0][1] - 0.05 <= now <= g[-1][2] + 0.25), None)
            if group:
                gw = [t for t, _, _ in group]
                shown = sum(1 for _, s, _ in group if s <= now + 0.02)
                draw_caption(frame, caption, gw, max(1, shown), accent, (60, int(H * 0.6), W - 60, int(H * 0.82)))
            if small_logo is not None:
                frame.paste(small_logo, (70, 100), small_logo)
        if f == int(FPS * 1.0):
            frame.save(poster, quality=85)
        return frame.tobytes()

    # Frames come off the decoder in order, so they're read here and drawn in parallel batches.
    def frames_in_order():
        for f in range(frames):
            yield f, (next_frame() if f < talk_frames else None)

    def draw_pair(pair) -> bytes:
        return draw(*pair)

    tmp = out.with_name(f"{out.stem}.{uuid.uuid4().hex[:8]}.part.mp4")
    cmd = [ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
           "-ss", f"{start:.3f}", "-to", f"{stop:.3f}", "-i", video_path, "-map", "0:v", "-map", "1:a?",
           "-af", f"apad=whole_dur={total:.3f}", "-t", f"{total:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
           "-movflags", "+faststart", str(tmp)]
    enc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            batch = []
            for pair in frames_in_order():
                batch.append(pair)
                if len(batch) >= WORKERS * 2:
                    for data in pool.map(draw_pair, batch):
                        enc.stdin.write(data)
                    batch = []
            for data in pool.map(draw_pair, batch):
                enc.stdin.write(data)
        enc.stdin.close()
    except BrokenPipeError:
        pass
    finally:
        dec.kill()
    err = enc.stderr.read().decode(errors="replace")
    if enc.wait() != 0:
        tmp.unlink(missing_ok=True)
        raise VideoError(f"The video couldn't be encoded: {err.strip()[:200]}")
    tmp.replace(out)
    return round(total, 1)


# --------------------------------------------------------------------------- speaking text

def for_speech(line: str) -> str:
    """How a line should be read aloud: "POV" -> "P.O.V.", "Rs. 6,990" -> "6,990 rupees"."""
    s = re.sub(r"\bPOV\b", "P O V", line)
    s = re.sub(r"\b(?:Rs\.?|PKR)\s?([\d,]+(?:\.\d+)?)", r"\1 rupees", s)
    s = re.sub(r"\$\s?([\d,]+(?:\.\d+)?)", r"\1 dollars", s)
    s = s.replace("%", " percent").replace("&", " and ")
    return re.sub(r"[\U0001F300-\U0001FAFF☀-➿]", "", s).strip()


# --------------------------------------------------------------------------- whole jobs (run in a worker process)

def make_product_ad(kit: BrandKit, photo: str, lines: list[str], out: Path, poster: Path, mix: Mix, voice: str = "",
                    end: tuple[str, str, str] = ("", "", "")) -> float:
    """Voice (if asked for) then video, in one worker process: the voice sets each shot's length."""
    durations, wav = None, ""
    if voice:
        from . import speech

        wav_path = out.with_suffix(".voice.wav")
        durations = speech.speak([for_speech(line) for line in lines], wav_path, voice)
        wav = str(wav_path)
    try:
        return render_product_ad(kit, photo, lines, out, poster, mix, durations=durations, voice_wav=wav, end=end)
    finally:
        if wav:
            Path(wav).unlink(missing_ok=True)


def make_person_ad(kit: BrandKit, video: str, script: list[str], product_photo: str, terms: list[str], out: Path, poster: Path,
                   caption: str, seed: int, end: tuple[str, str, str] = ("", "", "")) -> tuple[float, list[str]]:
    """Listen to the clip, line the words up with the script, and edit the ad. Returns its length
    and the captions as they appear (what the person actually said)."""
    from . import speech

    heard, _ = speech.transcribe(video)
    if not heard:
        raise VideoError("No speech was heard in that video. Check the microphone was on, then try again.")
    words = align_to_script(heard, script)
    seconds = render_person_ad(kit, video, words, product_photo, terms, out, poster, caption, seed, end)
    return seconds, [" ".join(t for t, _, _ in words)]
