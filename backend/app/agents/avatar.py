"""A free AI presenter: an illustrated character who speaks the ad's script.

Realistic AI people need large neural models (paid cloud services, or PyTorch, which Windows Smart
App Control blocks on this PC). This presenter is drawn instead, in a flat illustration style, and
animated frame by frame on this computer: lips move with the voice (mouth opening from the sound's
loudness, its shape, wide, open or round, from the sound's pitch), eyes blink, the head bobs and
nods at each new line, and the body sways a little. Characters are fictional, so there are no
likeness or consent questions, and they wear the brand's colour with its logo as a badge.
"""
from __future__ import annotations

import math
import random
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps

from ..schemas import BrandKit
from . import ugc_video
from .ugc_video import FPS, H, W, Mix, bright, draw_caption, end_card, ink_for, rounded_mask, safe_rgb, shadow

SS = 2  # characters are drawn at twice the size and scaled down, for smooth edges


@dataclass(frozen=True)
class Character:
    key: str
    name: str
    gender: str
    skin: tuple[int, int, int]
    hair: tuple[int, int, int]
    style: str  # long | bob | short | curly | bun | hijab
    beard: bool = False
    glasses: bool = False
    scarf: tuple[int, int, int] = (190, 120, 140)  # hijab colour


CHARACTERS = [
    Character("amna", "Amna", "female", (214, 165, 128), (40, 28, 24), "long"),
    Character("sara", "Sara", "female", (198, 150, 112), (40, 28, 24), "hijab", scarf=(176, 106, 128)),
    Character("zara", "Zara", "female", (236, 198, 170), (110, 70, 40), "bob"),
    Character("maya", "Maya", "female", (130, 88, 62), (28, 20, 18), "bun"),
    Character("ali", "Ali", "male", (196, 146, 106), (24, 20, 18), "short", beard=True),
    Character("omar", "Omar", "male", (150, 100, 70), (22, 18, 16), "curly", glasses=True),
]
BY_KEY = {c.key: c for c in CHARACTERS}


def shade(c, k: float) -> tuple[int, int, int]:
    return tuple(max(0, min(255, int(v * k))) for v in c)


# --------------------------------------------------------------------------- drawing the character

HEAD = (560, 700)  # head sprite size (1x); the face is centred at FACE
FACE = (280, 360)
FACE_W, FACE_H = 300, 370
MOUTH_AT = (280, 470)


def _head(ch: Character, eyes_open: bool) -> Image.Image:
    """The head without a mouth (drawn per frame), eyes open or closed."""
    w, h = HEAD[0] * SS, HEAD[1] * SS
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = SS
    cx, cy = FACE[0] * s, FACE[1] * s
    fw, fh = FACE_W * s, FACE_H * s
    skin, dark = ch.skin, shade(ch.skin, 0.84)

    def ell(x0, y0, x1, y1, fill, **kw):
        d.ellipse([cx + x0 * s, cy + y0 * s, cx + x1 * s, cy + y1 * s], fill=fill, **kw)

    # behind the head
    if ch.style == "long":
        d.rounded_rectangle([cx - fw * 0.62, cy - fh * 0.5, cx + fw * 0.62, cy + fh * 0.78], radius=150 * s, fill=ch.hair)
    if ch.style == "bun":
        ell(-70, -260, 70, -150, ch.hair)
    if ch.style == "hijab":
        d.ellipse([cx - fw * 0.78, cy - fh * 0.72, cx + fw * 0.78, cy + fh * 0.95], fill=ch.scarf)
        d.rounded_rectangle([cx - fw * 0.8, cy + fh * 0.2, cx + fw * 0.8, h], radius=120 * s, fill=ch.scarf)
    # neck and ears
    d.rounded_rectangle([cx - 62 * s, cy + 120 * s, cx + 62 * s, h], radius=30 * s, fill=dark)
    if ch.style != "hijab":
        ell(-172, -20, -128, 60, dark)
        ell(128, -20, 172, 60, dark)
    # face: a soft egg shape (wider at the cheeks, narrower at the chin)
    d.ellipse([cx - fw / 2, cy - fh / 2, cx + fw / 2, cy + fh * 0.38], fill=skin)
    d.ellipse([cx - fw * 0.42, cy - fh * 0.1, cx + fw * 0.42, cy + fh / 2], fill=skin)
    if ch.beard:  # a short, trimmed beard along the jaw, and a moustache
        beard = shade(ch.hair, 1.25)
        d.chord([cx - fw * 0.44, cy + fh * 0.02, cx + fw * 0.44, cy + fh * 0.5], 10, 170, fill=beard)
        d.ellipse([cx - fw * 0.36, cy + fh * 0.0, cx + fw * 0.36, cy + fh * 0.36], fill=skin)
        d.chord([cx - 52 * s, cy + 78 * s, cx + 52 * s, cy + 112 * s], 180, 360, fill=beard)
    # cheeks
    blush = Image.new("RGBA", img.size, (0, 0, 0, 0))
    bd = ImageDraw.Draw(blush)
    for side in (-1, 1):
        bd.ellipse([cx + side * 95 * s - 34 * s, cy + 55 * s, cx + side * 95 * s + 34 * s, cy + 85 * s], fill=(235, 120, 120, 70))
    img.alpha_composite(blush.filter(ImageFilter.GaussianBlur(10 * s)))
    d = ImageDraw.Draw(img)
    # hair in front
    if ch.style in ("long", "bob", "bun"):
        d.chord([cx - fw * 0.55, cy - fh * 0.62, cx + fw * 0.55, cy + fh * 0.1], 180, 360, fill=ch.hair)
        d.polygon([(cx - fw * 0.53, cy - fh * 0.2), (cx - fw * 0.2, cy - fh * 0.42), (cx + fw * 0.1, cy - fh * 0.3),
                   (cx + fw * 0.53, cy - fh * 0.22), (cx + fw * 0.5, cy - fh * 0.45), (cx - fw * 0.5, cy - fh * 0.45)], fill=ch.hair)
        if ch.style == "bob":
            for side in (-1, 1):
                d.rounded_rectangle([cx + side * fw * 0.5 - 40 * s, cy - fh * 0.3, cx + side * fw * 0.5 + 40 * s, cy + fh * 0.28],
                                    radius=40 * s, fill=ch.hair)
        if ch.style == "long":
            for side in (-1, 1):
                d.rounded_rectangle([cx + side * fw * 0.48 - 45 * s, cy - fh * 0.25, cx + side * fw * 0.48 + 45 * s, cy + fh * 0.62],
                                    radius=45 * s, fill=ch.hair)
    elif ch.style == "short":  # a short crop with a side part
        d.chord([cx - fw * 0.52, cy - fh * 0.6, cx + fw * 0.52, cy - fh * 0.02], 180, 360, fill=ch.hair)
        d.polygon([(cx - fw * 0.5, cy - fh * 0.28), (cx - fw * 0.1, cy - fh * 0.38), (cx + fw * 0.5, cy - fh * 0.3),
                   (cx + fw * 0.5, cy - fh * 0.4), (cx - fw * 0.5, cy - fh * 0.4)], fill=ch.hair)
        for side in (-1, 1):  # short sideburns
            d.rounded_rectangle([cx + side * fw * 0.47 - 14 * s, cy - fh * 0.3, cx + side * fw * 0.47 + 14 * s, cy - fh * 0.05],
                                radius=12 * s, fill=ch.hair)
    elif ch.style == "curly":
        rng = random.Random(7)
        for _ in range(26):
            a = rng.uniform(math.pi * 1.0, math.pi * 2.0)
            r = rng.uniform(0.42, 0.56)
            x, y = cx + math.cos(a) * fw * r, cy - fh * 0.1 + math.sin(a) * fh * r * 0.95
            rr = rng.uniform(34, 48) * s
            d.ellipse([x - rr, y - rr, x + rr, y + rr], fill=ch.hair)
    elif ch.style == "hijab":
        # the scarf frames the face
        frame = Image.new("L", img.size, 0)
        ImageDraw.Draw(frame).ellipse([cx - fw * 0.78, cy - fh * 0.72, cx + fw * 0.78, cy + fh * 0.95], fill=255)
        ImageDraw.Draw(frame).ellipse([cx - fw * 0.47, cy - fh * 0.5, cx + fw * 0.47, cy + fh * 0.5], fill=0)
        scarf = Image.new("RGBA", img.size, (*ch.scarf, 255))
        img.paste(scarf, (0, 0), frame)
        d = ImageDraw.Draw(img)
        d.arc([cx - fw * 0.5, cy - fh * 0.53, cx + fw * 0.5, cy + fh * 0.53], 200, 340, fill=shade(ch.scarf, 0.8), width=8 * s)
    # eyebrows
    brow = shade(ch.hair, 1.1) if ch.style != "hijab" else (40, 28, 24)
    for side in (-1, 1):
        x = cx + side * 62 * s
        d.arc([x - 40 * s, cy - 70 * s, x + 40 * s, cy - 20 * s], 200 if side < 0 else 200, 340, fill=brow, width=10 * s)
    # eyes
    for side in (-1, 1):
        x, y = cx + side * 62 * s, cy - 8 * s
        if eyes_open:
            d.ellipse([x - 26 * s, y - 17 * s, x + 26 * s, y + 17 * s], fill=(255, 255, 255))
            d.ellipse([x - 13 * s, y - 14 * s, x + 13 * s, y + 14 * s], fill=(70, 45, 30))
            d.ellipse([x - 7 * s, y - 7 * s, x + 7 * s, y + 7 * s], fill=(15, 10, 10))
            d.ellipse([x + 2 * s, y - 8 * s, x + 8 * s, y - 2 * s], fill=(255, 255, 255))
            d.arc([x - 28 * s, y - 20 * s, x + 28 * s, y + 18 * s], 200, 340, fill=(30, 20, 20), width=5 * s)
        else:
            d.arc([x - 26 * s, y - 14 * s, x + 26 * s, y + 10 * s], 20, 160, fill=(30, 20, 20), width=6 * s)
    if ch.glasses:
        for side in (-1, 1):
            x, y = cx + side * 62 * s, cy - 8 * s
            d.rounded_rectangle([x - 44 * s, y - 32 * s, x + 44 * s, y + 30 * s], radius=18 * s, outline=(30, 30, 35), width=7 * s)
        d.line([cx - 18 * s, cy - 12 * s, cx + 18 * s, cy - 12 * s], fill=(30, 30, 35), width=7 * s)
    # nose
    d.arc([cx - 18 * s, cy + 20 * s, cx + 18 * s, cy + 62 * s], 20, 160, fill=shade(skin, 0.72), width=6 * s)
    return img.resize(HEAD, Image.LANCZOS)


def _body(ch: Character, shirt: tuple[int, int, int], logo: Image.Image | None) -> Image.Image:
    w, h = 1000, 760
    img = Image.new("RGBA", (w * SS, h * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = SS
    color = ch.scarf if ch.style == "hijab" else shirt
    d.rounded_rectangle([60 * s, 160 * s, (w - 60) * s, (h + 300) * s], radius=260 * s, fill=color)
    if ch.style != "hijab":  # an open collar
        d.polygon([((w / 2 - 95) * s, 150 * s), ((w / 2 + 95) * s, 150 * s), (w / 2 * s, 300 * s)], fill=shade(ch.skin, 0.84))
        d.line([((w / 2 - 95) * s, 150 * s), (w / 2 * s, 300 * s), ((w / 2 + 95) * s, 150 * s)], fill=shade(color, 0.8), width=10 * s)
    body = img.resize((w, h), Image.LANCZOS)
    if logo is not None:
        badge = logo.copy()
        badge.thumbnail((110, 80))
        plate = Image.new("RGBA", (badge.width + 28, badge.height + 22), (255, 255, 255, 235))
        plate.putalpha(rounded_mask(plate.size, 16).point(lambda v: int(v * 0.92)))
        body.paste(plate, (int(w * 0.68), 330), plate)
        body.paste(badge, (int(w * 0.68) + 14, 341), badge)
    return body


def _mouth(head: Image.Image, openness: float, shape_: str, skin) -> None:
    """Draw the mouth for this frame onto the head."""
    d = ImageDraw.Draw(head)
    x, y = MOUTH_AT
    lip = shade(skin, 0.62)
    if openness < 0.08:  # closed: a gentle smile
        d.arc([x - 34, y - 16, x + 34, y + 16], 15, 165, fill=lip, width=6)
        return
    wscale = {"wide": 1.15, "round": 0.62, "open": 0.9}.get(shape_, 0.9)
    mw = 36 * wscale
    mh = 6 + 38 * openness * (1.15 if shape_ == "round" else 1.0)
    box = [x - mw, y - mh * 0.35, x + mw, y + mh * 0.65]
    d.ellipse(box, fill=(110, 36, 46), outline=lip, width=5)
    if openness > 0.3:  # top teeth
        d.chord([x - mw * 0.75, y - mh * 0.32, x + mw * 0.75, y + mh * 0.05], 180, 360, fill=(250, 250, 248))
    if openness > 0.5:  # tongue
        d.chord([x - mw * 0.55, y + mh * 0.15, x + mw * 0.55, y + mh * 0.62], 180, 360, fill=(214, 96, 104))


def preview(ch: Character, shirt: tuple[int, int, int] = (91, 71, 251), size: int = 360) -> Image.Image:
    """A small portrait for choosing a presenter."""
    canvas = Image.new("RGB", (W, int(H * 0.62)), (238, 236, 250))
    body = _body(ch, shirt, None)
    canvas.paste(body, ((W - body.width) // 2, 640), body)
    head = _head(ch, True)
    _mouth(head, 0.0, "rest", ch.skin)
    canvas.paste(head, ((W - head.width) // 2, 140), head)
    canvas = canvas.crop((W // 2 - 420, 120, W // 2 + 420, 120 + 840))
    canvas.thumbnail((size, size))
    return canvas


# --------------------------------------------------------------------------- lip sync from the voice

def lipsync(wav_path: str, frames: int) -> list[tuple[float, str]]:
    """(openness 0..1, mouth shape) for each video frame, read from the voice recording: louder opens
    the mouth, brighter sounds (ee) widen it, darker ones (oo) round it."""
    with wave.open(wav_path, "rb") as wf:
        rate = wf.getframerate()
        data = np.frombuffer(wf.readframes(wf.getnframes()), np.int16).astype(np.float32) / 32768.0
    hop = rate / FPS
    rms, cent = [], []
    for f in range(frames):
        a = int(f * hop)
        seg = data[a:int(a + hop)]
        if len(seg) < 32:
            rms.append(0.0)
            cent.append(0.0)
            continue
        rms.append(float(np.sqrt(np.mean(seg ** 2))))
        spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg))))
        freqs = np.fft.rfftfreq(len(seg), 1 / rate)
        cent.append(float((spec * freqs).sum() / (spec.sum() + 1e-9)))
    ref = np.percentile([r for r in rms if r > 0] or [1.0], 95) or 1.0
    out, level = [], 0.0
    for r, c in zip(rms, cent):
        target = min(1.0, max(0.0, (r / ref - 0.07) / 0.65))
        level += (target - level) * (0.65 if target > level else 0.4)  # quick to open, a touch slower to close
        shape_ = "closed" if level < 0.08 else "wide" if c > 2300 else "round" if c < 1050 else "open"
        out.append((level, shape_))
    return out


# --------------------------------------------------------------------------- the ad

def make_presenter_ad(kit: BrandKit, product_photo: str, lines: list[str], voice: str, character: str, out: Path, poster: Path,
                      mix: Mix, end: tuple[str, str, str] = ("", "", ""), product_label: tuple[str, str] = ("", "")) -> float:
    """The presenter speaks the script next to the product. Runs in a worker process."""
    from . import speech

    ch = BY_KEY.get(character) or CHARACTERS[0]
    wav = out.with_suffix(".voice.wav")
    durations = speech.speak(lines, wav, voice)
    try:
        talk = sum(durations)
        end_secs = 1.8 if any(end) else 0.0
        total = talk + end_secs
        frames, talk_frames = int(total * FPS), int(talk * FPS)
        mouth = lipsync(str(wav), talk_frames)
        starts = [sum(durations[:i]) for i in range(len(durations))]
        primary, accent = safe_rgb(kit.primary_color), bright(kit)
        logo = Image.open(kit.logo_path).convert("RGBA") if kit.logo_path and Path(kit.logo_path).exists() else None

        # What doesn't change, made once.
        top = tuple(min(255, int(c * 0.35 + 255 * 0.65)) for c in primary)
        bg = Image.new("RGB", (W, H), top)
        grad = Image.linear_gradient("L").resize((W, H))
        bg = Image.composite(Image.new("RGB", (W, H), tuple(min(255, int(c * 0.6 + 255 * 0.4)) for c in primary)), bg, grad)
        photo = ImageOps.exif_transpose(Image.open(product_photo)).convert("RGB")
        card_size = (780, 680)
        card = ImageOps.fit(photo, card_size)
        card_mask = rounded_mask(card_size, 44)
        card_shadow = shadow(card_size, 44, blur=36, alpha=90)
        heads = {True: _head(ch, True), False: _head(ch, False)}
        body = _body(ch, primary, logo)
        band = Image.new("L", (W, H), 0)
        ImageDraw.Draw(band).rectangle([0, int(H * 0.79), W, H], fill=150)
        band = band.filter(ImageFilter.GaussianBlur(60))
        black = Image.new("RGB", (W, H), (0, 0, 0))
        rng = random.Random(mix.seed)
        blinks = []
        t = rng.uniform(1.0, 2.5)
        while t < total:
            blinks.append(t)
            t += rng.uniform(2.6, 5.0)
        name, price = product_label
        line_words = [line.split() for line in lines]

        def draw(f: int) -> bytes:
            now = f / FPS
            if f >= talk_frames:
                img = end_card(kit, *end, logo, now - talk, mix.seed)
            else:
                img = bg.copy()
                # the product, floating
                fy = int(110 + 10 * math.sin(now * 1.3))
                img.paste(card_shadow, ((W - card_size[0]) // 2 - 72, fy - 50), card_shadow)
                img.paste(card, ((W - card_size[0]) // 2, fy), card_mask)
                if name or price:
                    chip = ImageDraw.Draw(img)
                    text = f"{name}  ·  {price}" if name and price else name or price
                    fnt = ugc_video.font(40, True)
                    tw = chip.textlength(text, font=fnt)
                    x0 = (W - tw) / 2 - 26
                    chip.rounded_rectangle([x0, fy + card_size[1] - 30, x0 + tw + 52, fy + card_size[1] + 40], 34, fill=accent)
                    chip.text((x0 + 26, fy + card_size[1] - 22), text, font=fnt, fill=ink_for(accent))
                # the presenter
                i = max(k for k, s in enumerate(starts) if s <= now)
                local = now - starts[i]
                nod = 3.5 * math.sin(min(1.0, local / 0.45) * math.pi) if local < 0.45 else 0.0
                sway = 6 * math.sin(now * 0.8)
                bob = 5 * math.sin(now * 2.1)
                img.paste(body, (int((W - body.width) / 2 + sway), 1380 + int(bob * 0.4)), body)
                eyes_open = not any(b <= now < b + 0.13 for b in blinks)
                head = heads[eyes_open].copy()
                level, shape_ = mouth[min(f, len(mouth) - 1)]
                _mouth(head, level, shape_, ch.skin)
                tilt = 2.2 * math.sin(now * 0.9) + nod
                head = head.rotate(tilt, resample=Image.BICUBIC, center=(FACE[0], FACE[1] + 150))
                img.paste(head, (int((W - head.width) / 2 + sway * 1.2), 900 + int(bob)), head)
                # captions over a soft dark band
                img = Image.composite(black, img, band)
                words = line_words[i]
                shown = min(len(words), 1 + int(local * len(words) / max(0.4, durations[i] * 0.85)))
                draw_caption(img, mix.caption, words, shown, accent, (60, int(H * 0.81), W - 60, H - 70))
            if f == int(FPS * 1.0):
                img.save(poster, quality=85)
            return img.tobytes()

        ugc_video._encode(out, frames, draw, audio=str(wav))
        return round(total, 1)
    finally:
        wav.unlink(missing_ok=True)
