"""Drawing helpers shared by the reel styles: text blocks, chips, stickers, logo chips, motion curves."""
from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from ...schemas import BrandKit
from .. import lang as lang_mod
from ..renderer import fit_text, font, text_on

from .core import H, W

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
