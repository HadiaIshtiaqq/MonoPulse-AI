"""A free AI presenter: a cute illustrated character who speaks the ad's script.

Realistic AI people need large neural models (paid cloud services, or PyTorch, which Windows Smart
App Control blocks on this PC). This presenter is drawn instead, in a soft "chibi" style (big head,
large sparkling eyes, rosy cheeks, full hair with highlights), and animated frame by frame on this
computer:
  * lips move with the voice: the sound's loudness opens the mouth, its brightness picks a wide,
    open or round shape;
  * the arms move: a wave hello on the first line, pointing up at the product when its name or price
    comes up, talking gestures otherwise, and back to rest between lines;
  * the eyes blink and look up at the product when pointing; the head tilts and nods; the body
    bounces a little on the stressed sounds.
Characters are fictional, so there are no likeness or consent questions; they wear the brand's
colour with its logo as a badge.
"""
from __future__ import annotations

import math
import random
import re
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps

from ..schemas import BrandKit
from . import ugc_video
from .ugc_video import FPS, H, W, Mix, bright, draw_caption, end_card, ink_for, rounded_mask, safe_rgb, shadow

SS = 3  # drawn at three times the size, then scaled down: smooth, soft edges


@dataclass(frozen=True)
class Character:
    key: str
    name: str
    gender: str
    skin: tuple[int, int, int]
    hair: tuple[int, int, int]
    style: str  # wavy | hijab | straight | puffs | fluffy | curly
    glasses: bool = False
    accent: tuple[int, int, int] = (255, 120, 150)  # bows, clips, the hijab
    iris: tuple[int, int, int] = (110, 70, 40)


CHARACTERS = [
    Character("amna", "Amna", "female", (250, 214, 190), (92, 56, 38), "wavy", accent=(255, 128, 160)),
    Character("sara", "Sara", "female", (240, 200, 170), (60, 40, 30), "hijab", accent=(232, 150, 172)),
    Character("zara", "Zara", "female", (252, 222, 200), (58, 38, 30), "straight", glasses=True, accent=(140, 120, 255)),
    Character("maya", "Maya", "female", (176, 120, 88), (40, 28, 24), "puffs", accent=(255, 196, 60), iris=(80, 50, 30)),
    Character("ali", "Ali", "male", (236, 194, 160), (54, 36, 28), "fluffy", accent=(80, 170, 255)),
    Character("omar", "Omar", "male", (190, 134, 98), (32, 24, 20), "curly", glasses=True, accent=(90, 200, 160), iris=(70, 44, 26)),
]
BY_KEY = {c.key: c for c in CHARACTERS}


def shade(c, k: float) -> tuple[int, int, int]:
    return tuple(max(0, min(255, int(v * k))) for v in c)


def lighten(c, k: float) -> tuple[int, int, int]:
    return tuple(int(v + (255 - v) * k) for v in c)


def _canvas(w: int, h: int) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGBA", (w * SS, h * SS), (0, 0, 0, 0))
    return img, ImageDraw.Draw(img)


def _done(img: Image.Image, w: int, h: int) -> Image.Image:
    return img.resize((w, h), Image.LANCZOS)


def _soft(img: Image.Image, shape_fn, color, blur: float, clip: Image.Image | None = None) -> None:
    """A soft shaded or glowing area (cheeks, shadows, highlights), optionally kept inside clip's alpha."""
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    shape_fn(ImageDraw.Draw(layer), color)
    layer = layer.filter(ImageFilter.GaussianBlur(blur * SS))
    if clip is not None:
        alpha = Image.composite(layer.getchannel("A"), Image.new("L", img.size, 0), clip.getchannel("A"))
        layer.putalpha(alpha)
    img.alpha_composite(layer)


# --------------------------------------------------------------------------- the head

HEAD_W, HEAD_H = 560, 600
FC = (280, 300)  # face centre in the head sprite
EYE_DX, EYE_Y, MOUTH_Y = 80, 318, 404
NECK = (280, 520)  # where the head sits on the neck (rotation pivot)


def _face_mask(s: int) -> list[tuple[float, float]]:
    """A soft, wide chibi face: round cheeks, a small rounded chin."""
    cx, cy = FC[0] * s, FC[1] * s
    pts = []
    for i in range(72):
        a = 2 * math.pi * i / 72
        x, y = math.cos(a), math.sin(a)
        rx = 186 if y < 0 else 186 - 30 * y ** 2
        ry = 172 if y < 0 else 182
        pts.append((cx + x * rx * s, cy + 20 * s + y * ry * s))
    return pts


def _hair_back(ch: Character, d: ImageDraw.ImageDraw, s: int) -> None:
    cx, cy = FC[0] * s, FC[1] * s
    h = ch.hair
    if ch.style == "wavy":
        d.rounded_rectangle([cx - 236 * s, cy - 150 * s, cx + 236 * s, cy + 290 * s], radius=150 * s, fill=h)
        for side in (-1, 1):  # waves at the ends
            for k in range(3):
                d.ellipse([cx + side * (190 - k * 28) * s - 55 * s, cy + (230 + k * 18) * s, cx + side * (190 - k * 28) * s + 55 * s,
                           cy + (330 + k * 18) * s], fill=h)
    elif ch.style == "straight":
        d.rounded_rectangle([cx - 224 * s, cy - 160 * s, cx + 224 * s, cy + 300 * s], radius=120 * s, fill=h)
    elif ch.style == "hijab":
        d.ellipse([cx - 250 * s, cy - 230 * s, cx + 250 * s, cy + 240 * s], fill=ch.accent)
        d.rounded_rectangle([cx - 250 * s, cy + 40 * s, cx + 250 * s, HEAD_H * s], radius=140 * s, fill=ch.accent)
    elif ch.style == "puffs":
        for side in (-1, 1):
            d.ellipse([cx + side * 175 * s - 95 * s, cy - 250 * s, cx + side * 175 * s + 95 * s, cy - 60 * s], fill=h)


def _hair_front(ch: Character, img: Image.Image, d: ImageDraw.ImageDraw, s: int, face: Image.Image) -> None:
    cx, cy = FC[0] * s, FC[1] * s
    h, hl = ch.hair, lighten(ch.hair, 0.35)
    if ch.style == "hijab":
        # the scarf frames the face; a soft fold at the top
        ring = Image.new("L", img.size, 0)
        rd = ImageDraw.Draw(ring)
        rd.ellipse([cx - 250 * s, cy - 230 * s, cx + 250 * s, cy + 240 * s], fill=255)
        rd.ellipse([cx - 192 * s, cy - 170 * s, cx + 192 * s, cy + 205 * s], fill=0)
        img.paste(Image.new("RGBA", img.size, (*ch.accent, 255)), (0, 0), ring)
        d.arc([cx - 200 * s, cy - 178 * s, cx + 200 * s, cy + 210 * s], 200, 340, fill=shade(ch.accent, 0.86), width=10 * s)
        return
    if ch.style in ("wavy", "straight", "puffs"):
        # a full fringe with soft side-swept curves
        fr = [(cx - 196 * s, cy - 10 * s)]
        for i in range(25):
            a = math.pi + math.pi * i / 24
            fr.append((cx + math.cos(a) * 200 * s, cy - 40 * s + math.sin(a) * 178 * s))
        fr += [(cx + 196 * s, cy - 10 * s), (cx + 120 * s, cy - 92 * s), (cx + 40 * s, cy - 62 * s), (cx - 30 * s, cy - 108 * s),
               (cx - 110 * s, cy - 74 * s), (cx - 160 * s, cy - 40 * s)]
        d.polygon(fr, fill=h)
        if ch.style == "straight":  # a centre part
            d.line([(cx, cy - 214 * s), (cx + 8 * s, cy - 130 * s)], fill=shade(h, 0.75), width=6 * s)
        for side in (-1, 1):  # locks framing the face
            d.ellipse([cx + side * 190 * s - 34 * s, cy - 60 * s, cx + side * 190 * s + 34 * s, cy + 170 * s], fill=h)
        # glossy highlights
        d.arc([cx - 150 * s, cy - 196 * s, cx + 80 * s, cy - 40 * s], 205, 255, fill=hl, width=12 * s)
        d.arc([cx - 20 * s, cy - 200 * s, cx + 170 * s, cy - 50 * s], 270, 320, fill=hl, width=10 * s)
        if ch.style == "wavy":  # a little clip
            d.rounded_rectangle([cx + 120 * s, cy - 120 * s, cx + 172 * s, cy - 98 * s], radius=10 * s, fill=ch.accent)
        if ch.style == "puffs":  # hair ties
            for side in (-1, 1):
                d.ellipse([cx + side * 120 * s - 20 * s, cy - 120 * s, cx + side * 120 * s + 20 * s, cy - 80 * s], fill=ch.accent)
    elif ch.style == "fluffy":
        rng = random.Random(3)
        top = [(cx - 196 * s, cy - 20 * s)]
        for i in range(19):
            a = math.pi + math.pi * i / 18
            r = (196 + rng.uniform(-6, 18)) * s
            top.append((cx + math.cos(a) * r, cy - 40 * s + math.sin(a) * r * 0.95))
        top += [(cx + 196 * s, cy - 20 * s)]
        for i in range(7):  # a soft spiky fringe
            x = cx + (150 - i * 50) * s
            top += [(x, cy - 70 * s), (x - 25 * s, cy - 105 * s + (i % 2) * 12 * s)]
        d.polygon(top, fill=h)
        d.arc([cx - 140 * s, cy - 210 * s, cx + 60 * s, cy - 60 * s], 210, 260, fill=hl, width=12 * s)
    elif ch.style == "curly":
        rng = random.Random(11)
        for _ in range(34):
            a = rng.uniform(math.pi * 0.98, math.pi * 2.02)
            r = rng.uniform(0.86, 1.06) * 196
            x, y = cx + math.cos(a) * r * s, cy - 30 * s + math.sin(a) * r * 0.92 * s
            rr = rng.uniform(40, 56) * s
            d.ellipse([x - rr, y - rr, x + rr, y + rr], fill=h)
        for _ in range(10):
            x, y = cx + rng.uniform(-150, 150) * s, cy - rng.uniform(140, 190) * s
            d.arc([x - 30 * s, y - 30 * s, x + 30 * s, y + 30 * s], 200, 300, fill=hl, width=7 * s)


def _head_base(ch: Character) -> Image.Image:
    """Everything on the head that doesn't move frame to frame: hair, face, cheeks, brows, nose."""
    s = SS
    img, d = _canvas(HEAD_W, HEAD_H)
    _hair_back(ch, d, s)
    cx, cy = FC[0] * s, FC[1] * s
    if ch.style != "hijab":  # the hijab covers the neck
        d.rounded_rectangle([cx - 58 * s, cy + 150 * s, cx + 58 * s, HEAD_H * s], radius=26 * s, fill=shade(ch.skin, 0.88))
    # ears (boys; long hair hides them)
    if ch.style in ("fluffy", "curly"):
        for side in (-1, 1):
            d.ellipse([cx + side * 186 * s - 28 * s, cy + 10 * s, cx + side * 186 * s + 28 * s, cy + 80 * s], fill=shade(ch.skin, 0.94))
    face = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(face).polygon(_face_mask(s), fill=(*ch.skin, 255))
    img.alpha_composite(face)
    d = ImageDraw.Draw(img)
    # soft shading: lighter in the middle, a shadow under the hair line
    _soft(img, lambda dd, c: dd.ellipse([cx - 120 * s, cy - 40 * s, cx + 120 * s, cy + 150 * s], fill=c), (*lighten(ch.skin, 0.35), 110), 30, face)
    _soft(img, lambda dd, c: dd.ellipse([cx - 190 * s, cy - 150 * s, cx + 190 * s, cy - 40 * s], fill=c), (*shade(ch.skin, 0.93), 70), 26, face)
    # rosy cheeks
    for side in (-1, 1):
        _soft(img, lambda dd, c, side=side: dd.ellipse([cx + side * 118 * s - 46 * s, cy + 70 * s, cx + side * 118 * s + 46 * s, cy + 106 * s],
                                                         fill=c), (255, 120, 140, 150), 9, face)
    d = ImageDraw.Draw(img)
    # nose: a tiny soft dot
    d.ellipse([cx - 9 * s, cy + 64 * s, cx + 9 * s, cy + 76 * s], fill=shade(ch.skin, 0.84))
    _hair_front(ch, img, ImageDraw.Draw(img), s, face)
    d = ImageDraw.Draw(img)
    # eyebrows: short, soft, slightly raised (friendly)
    brow = shade(ch.hair, 1.0) if ch.style != "hijab" else (70, 46, 36)
    for side in (-1, 1):
        x = cx + side * EYE_DX * s
        d.arc([x - 34 * s, cy - 50 * s, x + 34 * s, cy - 14 * s], 210, 330, fill=brow, width=8 * s)
    return _done(img, HEAD_W, HEAD_H)


EYE_W, EYE_H = 96, 110


def _eye(ch: Character, gaze: tuple[float, float], closed: bool, side: int) -> Image.Image:
    """One big sparkling eye (side -1 = screen left), looking towards gaze (-1..1, -1..1)."""
    s = SS
    img, d = _canvas(EYE_W, EYE_H)
    cx, cy = EYE_W / 2 * s, EYE_H / 2 * s + 6 * s
    line = (44, 28, 26)
    if closed:  # a happy closed eye: a soft upward curve
        d.arc([cx - 30 * s, cy - 18 * s, cx + 30 * s, cy + 26 * s], 200, 340, fill=line, width=9 * s)
        return _done(img, EYE_W, EYE_H)
    rw, rh = 34 * s, 40 * s
    d.ellipse([cx - rw, cy - rh, cx + rw, cy + rh], fill=(255, 255, 255))
    gx, gy = gaze[0] * 8 * s, gaze[1] * 8 * s
    ir_w, ir_h = 27 * s, 33 * s
    d.ellipse([cx + gx - ir_w, cy + gy - ir_h, cx + gx + ir_w, cy + gy + ir_h], fill=shade(ch.iris, 0.7))
    d.ellipse([cx + gx - ir_w * 0.82, cy + gy - ir_h * 0.55, cx + gx + ir_w * 0.82, cy + gy + ir_h * 0.95], fill=lighten(ch.iris, 0.18))
    d.ellipse([cx + gx - 13 * s, cy + gy - 15 * s, cx + gx + 13 * s, cy + gy + 15 * s], fill=(28, 18, 16))
    # sparkles
    d.ellipse([cx + gx + 4 * s, cy + gy - 24 * s, cx + gx + 20 * s, cy + gy - 6 * s], fill=(255, 255, 255))
    d.ellipse([cx + gx - 16 * s, cy + gy + 12 * s, cx + gx - 8 * s, cy + gy + 20 * s], fill=(255, 255, 255, 230))
    # keep the eye inside its outline
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).ellipse([cx - rw, cy - rh, cx + rw, cy + rh], fill=255)
    clipped = Image.new("RGBA", img.size, (0, 0, 0, 0))
    clipped.paste(img, (0, 0), mask)
    img = clipped
    d = ImageDraw.Draw(img)
    # a thick top lid line, and lashes for the girls
    d.arc([cx - rw - 3 * s, cy - rh - 3 * s, cx + rw + 3 * s, cy + rh + 3 * s], 195, 345, fill=line, width=8 * s)
    if ch.gender == "female":
        ox = cx + side * -1 * 0 + (rw if side > 0 else -rw)
        for k in range(2):
            ang = (-0.5 - k * 0.35) if side > 0 else (math.pi + 0.5 + k * 0.35)
            x0, y0 = ox - side * 2 * s, cy - rh * 0.55 + k * 8 * s
            d.line([(x0, y0), (x0 + math.cos(ang) * 18 * s * side * side, y0 + math.sin(ang) * 18 * s * -1 if side > 0 else y0 - abs(math.sin(ang)) * 18 * s)],
                   fill=line, width=6 * s)
    return _done(img, EYE_W, EYE_H)


MOUTH_W, MOUTH_H = 120, 90


def _mouth(level: float, shape_: str, skin) -> Image.Image:
    s = SS
    img, d = _canvas(MOUTH_W, MOUTH_H)
    cx, cy = MOUTH_W / 2 * s, MOUTH_H / 2 * s
    lip = shade(skin, 0.6)
    if level < 0.08:  # closed: a little smile
        d.arc([cx - 26 * s, cy - 22 * s, cx + 26 * s, cy + 12 * s], 25, 155, fill=lip, width=6 * s)
        return _done(img, MOUTH_W, MOUTH_H)
    wscale = {"wide": 1.2, "round": 0.62, "open": 0.95}.get(shape_, 0.95)
    mw = 24 * wscale * s
    mh = (6 + 34 * level * (1.15 if shape_ == "round" else 1.0)) * s
    box = [cx - mw, cy - mh * 0.4, cx + mw, cy + mh * 0.6]
    if shape_ == "round":
        d.ellipse(box, fill=(120, 34, 50))
    else:  # a soft "D" shape: flat-ish top, round bottom, like cartoon talking mouths
        d.chord([box[0], box[1] - mh * 0.6, box[2], box[3]], 0, 180, fill=(120, 34, 50))
    if level > 0.35:
        d.chord([cx - mw * 0.7, box[1] - mh * 0.15, cx + mw * 0.7, box[1] + mh * 0.3], 0, 180, fill=(255, 255, 255))
    if level > 0.45:
        d.ellipse([cx - mw * 0.5, cy + mh * 0.12, cx + mw * 0.5, box[3] + mh * 0.05], fill=(240, 110, 120))
    return _done(img, MOUTH_W, MOUTH_H)


def _glasses() -> Image.Image:
    s = SS
    img, d = _canvas(HEAD_W, HEAD_H)
    cx, cy = FC[0] * s, (EYE_Y + 6) * s
    for side in (-1, 1):
        x = cx + side * EYE_DX * s
        d.ellipse([x - 52 * s, cy - 50 * s, x + 52 * s, cy + 50 * s], outline=(50, 40, 44), width=8 * s)
        d.ellipse([x - 40 * s, cy - 40 * s, x - 10 * s, cy - 18 * s], fill=(255, 255, 255, 70))
    d.arc([cx - 30 * s, cy - 24 * s, cx + 30 * s, cy + 6 * s], 200, 340, fill=(50, 40, 44), width=8 * s)
    return _done(img, HEAD_W, HEAD_H)


# --------------------------------------------------------------------------- body and arms

BODY_W, BODY_H = 520, 560
UPPER_L, FORE_L = 118, 112  # arm segment lengths (1x)
SHOULDER_DX, SHOULDER_DY = 168, 70  # from the neck base


def _body(ch: Character, shirt, logo: Image.Image | None) -> Image.Image:
    s = SS
    img, d = _canvas(BODY_W, BODY_H)
    cx = BODY_W / 2 * s
    color = ch.accent if ch.style == "hijab" else shirt
    d.rounded_rectangle([cx - 200 * s, 40 * s, cx + 200 * s, (BODY_H + 200) * s], radius=170 * s, fill=color)
    _soft(img, lambda dd, c: dd.ellipse([cx - 170 * s, 50 * s, cx - 40 * s, 220 * s], fill=c), (255, 255, 255, 26), 34, img)
    d = ImageDraw.Draw(img)
    if ch.style != "hijab":  # a round neckline
        d.chord([cx - 70 * s, -10 * s, cx + 70 * s, 110 * s], 0, 180, fill=shade(ch.skin, 0.88))
        d.arc([cx - 72 * s, -12 * s, cx + 72 * s, 112 * s], 0, 180, fill=shade(color, 0.82), width=8 * s)
    body = _done(img, BODY_W, BODY_H)
    if logo is not None:
        badge = logo.copy()
        badge.thumbnail((96, 70))
        plate = Image.new("RGBA", (badge.width + 24, badge.height + 20), (255, 255, 255, 240))
        plate.putalpha(rounded_mask(plate.size, 18).point(lambda v: int(v * 0.94)))
        body.paste(plate, (int(BODY_W * 0.6), 190), plate)
        body.paste(badge, (int(BODY_W * 0.6) + 12, 200), badge)
    return body


def _segment(length: int, width: int, color, hand=None) -> Image.Image:
    """An arm segment hanging down from its pivot (top centre); with a cute mitten hand at the end."""
    s = SS
    pad = 46 if hand else 0
    w, h = width + 2 * pad, length + width // 2 + pad + 10
    img, d = _canvas(w, h)
    cx = w / 2 * s
    d.rounded_rectangle([cx - width / 2 * s, 0, cx + width / 2 * s, (length + width / 2) * s], radius=width / 2 * s, fill=color)
    if hand:
        hy = (length + 4) * s
        d.ellipse([cx - 38 * s, hy - 30 * s, cx + 38 * s, hy + 42 * s], fill=hand)
        d.ellipse([cx + 18 * s, hy - 26 * s, cx + 44 * s, hy + 8 * s], fill=hand)  # thumb
        d.arc([cx - 22 * s, hy + 4 * s, cx + 10 * s, hy + 34 * s], 200, 330, fill=shade(hand, 0.85), width=4 * s)
    return _done(img, w, h)


def _paste_rot(dst: Image.Image, sprite: Image.Image, pivot: tuple[float, float], at: tuple[float, float], angle: float) -> None:
    """Rotate sprite about pivot by angle (degrees, counter-clockwise) and paste so pivot lands on at."""
    rot = sprite.rotate(angle, resample=Image.BICUBIC, expand=True)
    cx, cy = sprite.width / 2, sprite.height / 2
    vx, vy = pivot[0] - cx, pivot[1] - cy
    a = math.radians(angle)
    rx, ry = vx * math.cos(a) + vy * math.sin(a), -vx * math.sin(a) + vy * math.cos(a)
    nx, ny = rot.width / 2 + rx, rot.height / 2 + ry
    dst.paste(rot, (int(at[0] - nx), int(at[1] - ny)), rot)


@dataclass
class Pose:
    """Arm angles (degrees from straight down, counter-clockwise on screen) for the screen-left (l)
    and screen-right (r) arm: shoulder then elbow (absolute); where the eyes look; body lean."""
    l1: float
    l2: float
    r1: float
    r2: float
    gaze: tuple[float, float] = (0.0, 0.0)
    lean: float = 0.0


REST = Pose(-10, -2, 10, 2)


def _pose(kind: str, t: float, energy: float) -> Pose:
    if kind == "wave":
        return Pose(-12, -4, 118, 152 + 24 * math.sin(t * 9.5), (0.2, -0.1), -1.5)
    if kind == "point":  # up at the product above
        return Pose(-14, -6, 128, 160 + 3 * math.sin(t * 3), (0.35, -1.0), -2.0)
    if kind == "both":  # open hands, presenting
        k = 6 * math.sin(t * 4.2) + 10 * energy
        return Pose(-48 - k, -110 - k, 48 + k, 110 + k, (0.0, 0.1), 0.0)
    if kind == "talk":  # one hand moving with the words
        k = 14 * math.sin(t * 5.0) + 18 * energy
        return Pose(-10, -4, 22, -78 + k, (-0.15, 0.0), 1.0)
    return REST


def _mix(a: Pose, b: Pose, k: float) -> Pose:
    k = 0.5 - 0.5 * math.cos(math.pi * max(0.0, min(1.0, k)))
    m = lambda x, y: x + (y - x) * k  # noqa: E731
    return Pose(m(a.l1, b.l1), m(a.l2, b.l2), m(a.r1, b.r1), m(a.r2, b.r2), (m(a.gaze[0], b.gaze[0]), m(a.gaze[1], b.gaze[1])), m(a.lean, b.lean))


def gestures(lines: list[str], terms: list[str], seed: int) -> list[str]:
    """A gesture per line: wave hello first, point at the product when it's named or priced, and
    vary the talking gestures so no two neighbouring lines move the same way."""
    keys = {w for term in terms for w in re.findall(r"[a-z0-9]{3,}", term.lower())}
    rng = random.Random(seed)
    out = []
    for i, line in enumerate(lines):
        words = set(re.findall(r"[a-z0-9]{3,}", line.lower()))
        if i == 0:
            out.append("wave")
        elif words & keys or re.search(r"\d", line):
            out.append("point" if out[-1] != "point" else "both")
        else:
            out.append(rng.choice([g for g in ("talk", "both", "rest") if g != out[-1]]))
    return out


# --------------------------------------------------------------------------- the rig

class Rig:
    """All of a character's pre-drawn parts, and how to put them together for one frame."""

    def __init__(self, ch: Character, shirt, logo: Image.Image | None):
        self.ch = ch
        self.head = _head_base(ch)
        self.body = _body(ch, shirt, logo)
        self.glasses = _glasses() if ch.glasses else None
        sleeve = ch.accent if ch.style == "hijab" else shirt
        self.upper = _segment(UPPER_L, 62, shade(sleeve, 0.96))
        self.fore = _segment(FORE_L, 54, shade(sleeve, 0.96) if ch.style == "hijab" else ch.skin, hand=ch.skin)
        self.eyes: dict = {}
        self.mouths: dict = {}

    def eye(self, gaze, closed, side):
        key = (round(gaze[0] * 4) / 4, round(gaze[1] * 4) / 4, closed, side)
        if key not in self.eyes:
            self.eyes[key] = _eye(self.ch, key[:2], closed, side)
        return self.eyes[key]

    def mouth(self, level, shape_):
        key = (round(level * 6) / 6, shape_ if level >= 0.08 else "closed")
        if key not in self.mouths:
            self.mouths[key] = _mouth(key[0], key[1], self.ch.skin)
        return self.mouths[key]

    def draw(self, dst: Image.Image, neck: tuple[float, float], pose: Pose, level: float, shape_: str, blink: bool, tilt: float,
             scale: float = 1.0) -> None:
        nx, ny = neck
        # arms behind the body when at rest, in front when gesturing (drawn after)
        bx, by = nx - self.body.width / 2, ny - 30
        dst.paste(self.body, (int(bx), int(by)), self.body)
        head = self.head.copy()
        for side in (-1, 1):
            e = self.eye(pose.gaze, blink, side)
            head.paste(e, (int(FC[0] + side * EYE_DX - EYE_W / 2), int(EYE_Y - EYE_H / 2)), e)
        m = self.mouth(level, shape_)
        head.paste(m, (int(FC[0] - MOUTH_W / 2), int(MOUTH_Y - MOUTH_H / 2)), m)
        if self.glasses is not None:
            head.alpha_composite(self.glasses)
        _paste_rot(dst, head, NECK, (nx, ny + 10), tilt)
        for side, a1, a2 in ((-1, pose.l1, pose.l2), (1, pose.r1, pose.r2)):
            sx, sy = nx + side * SHOULDER_DX, ny + SHOULDER_DY
            ex = sx + UPPER_L * math.sin(math.radians(a1))
            ey = sy + UPPER_L * math.cos(math.radians(a1))
            _paste_rot(dst, self.upper, (self.upper.width / 2, 0), (sx, sy), a1)
            _paste_rot(dst, self.fore, (self.fore.width / 2, 0), (ex, ey), a2)


def preview(ch: Character, shirt: tuple[int, int, int] = (124, 104, 255), size: int = 360) -> Image.Image:
    """A small portrait for choosing a presenter (waving)."""
    canvas = Image.new("RGBA", (900, 900), (238, 236, 250, 255))
    rig = Rig(ch, shirt, None)
    rig.draw(canvas, (450, 560), _pose("wave", 0.15, 0), 0.0, "closed", False, -2.0)
    out = canvas.convert("RGB")
    out.thumbnail((size, size))
    return out


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
    """The presenter speaks the script and gestures at the product. Runs in a worker process."""
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
        moves = gestures(lines, [x for x in product_label if x], mix.seed)
        primary, accent = safe_rgb(kit.primary_color), bright(kit)
        logo = Image.open(kit.logo_path).convert("RGBA") if kit.logo_path and Path(kit.logo_path).exists() else None

        # What doesn't change, made once.
        top = lighten(primary, 0.72)
        bg = Image.new("RGB", (W, H), top)
        grad = Image.linear_gradient("L").resize((W, H))
        bg = Image.composite(Image.new("RGB", (W, H), lighten(primary, 0.45)), bg, grad)
        sparkle = ImageDraw.Draw(bg)
        rng = random.Random(mix.seed)
        for _ in range(26):  # soft confetti dots
            x, y, r = rng.uniform(0, W), rng.uniform(0, H * 0.75), rng.uniform(5, 14)
            sparkle.ellipse([x - r, y - r, x + r, y + r], fill=lighten(primary, rng.uniform(0.2, 0.9)))
        photo = ImageOps.exif_transpose(Image.open(product_photo)).convert("RGB")
        card_size = (700, 600)
        card = ImageOps.fit(photo, card_size)
        card_mask = rounded_mask(card_size, 48)
        card_shadow = shadow(card_size, 48, blur=36, alpha=90)
        rig = Rig(ch, primary, logo)
        band = Image.new("L", (W, H), 0)
        ImageDraw.Draw(band).rectangle([0, int(H * 0.8), W, H], fill=150)
        band = band.filter(ImageFilter.GaussianBlur(60))
        black = Image.new("RGB", (W, H), (0, 0, 0))
        blinks, t = [], rng.uniform(1.0, 2.5)
        while t < total:
            blinks.append(t)
            t += rng.uniform(2.4, 4.6)
        name, price = product_label
        line_words = [line.split() for line in lines]
        # a bounce on stressed sounds: the voice's loudness, smoothed
        energy = [lvl for lvl, _ in mouth]
        bounce = [0.0] * len(energy)
        acc = 0.0
        for i, e in enumerate(energy):
            acc += (e - acc) * 0.25
            bounce[i] = max(0.0, e - acc)

        def draw(f: int) -> bytes:
            now = f / FPS
            if f >= talk_frames:
                img = end_card(kit, *end, logo, now - talk, mix.seed)
            else:
                img = bg.copy()
                fy = int(100 + 12 * math.sin(now * 1.3))
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
                i = max(k for k, s in enumerate(starts) if s <= now)
                local = now - starts[i]
                level, shape_ = mouth[min(f, len(mouth) - 1)]
                prev = _pose(moves[i - 1], now, level) if i > 0 else REST
                cur = _pose(moves[i], now, level)
                # into this line's gesture, and back to rest just before the line ends
                pose = _mix(prev, cur, local / 0.35)
                left = durations[i] - local
                if left < 0.3 and i + 1 < len(moves) and moves[i + 1] != moves[i]:
                    pose = _mix(pose, REST, 1 - left / 0.3)
                hop = 16 * bounce[min(f, len(bounce) - 1)]
                sway = 7 * math.sin(now * 0.9)
                nod = 4 * math.sin(min(1.0, local / 0.4) * math.pi) if local < 0.4 else 0.0
                tilt = 3 * math.sin(now * 0.8) + nod + pose.lean
                blink = any(b <= now < b + 0.12 for b in blinks)
                rig.draw(img, (W / 2 + sway, 1330 - hop + 4 * math.sin(now * 2.0)), pose, level, shape_, blink, tilt)
                img = Image.composite(black, img, band)
                words = line_words[i]
                shown = min(len(words), 1 + int(local * len(words) / max(0.4, durations[i] * 0.85)))
                draw_caption(img, mix.caption, words, shown, accent, (60, int(H * 0.815), W - 60, H - 70))
            if f == int(FPS * 1.0):
                img.save(poster, quality=85)
            return img.tobytes()

        ugc_video._encode(out, frames, draw, audio=str(wav))
        return round(total, 1)
    finally:
        wav.unlink(missing_ok=True)
