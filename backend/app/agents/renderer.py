"""Agent 6: Canva-style visual renderer.

Composites brand-coloured post graphics with headline overlays, optional background photos
and the brand logo, sized per platform. Carousels render a cover, content slides and a CTA
slide. Pure Pillow, so it runs anywhere (local, container, Nebius job).
"""
from __future__ import annotations

import asyncio
import colorsys
import re
import time
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps, ImageStat

from .. import config
from ..schemas import BrandKit, Platform, SocialPost
from . import lang as lang_mod
from . import occasions

SIZES = {
    Platform.INSTAGRAM: (1080, 1350),
    Platform.FACEBOOK: (1200, 1200),
    Platform.LINKEDIN: (1200, 1200),
    Platform.X: (1600, 900),
}
CAROUSEL_SIZE = (1080, 1350)
LAYOUTS = ["bold", "split", "quote", "photo", "frame", "poster", "minimal", "duo", "greeting"]
PHOTO_LAYOUTS = {"photo", "frame", "poster", "minimal", "duo"}  # need a background photo (duo also needs a second one)
POSITIONS = ["auto", "top", "center", "bottom"]

FONT_CANDIDATES = {
    True: [
        "C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/arialbd.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", "/Library/Fonts/Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    ],
    False: [
        "C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf", "/Library/Fonts/Arial.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ],
}


@lru_cache(maxsize=96)
def font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in FONT_CANDIDATES[bold]:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def luminance(c: tuple[int, int, int]) -> float:
    def ch(v: int) -> float:
        v = v / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = c
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def text_on(bg: tuple[int, int, int]) -> tuple[int, int, int]:
    return (255, 255, 255) if luminance(bg) < 0.45 else (17, 24, 39)


def shade(c: tuple[int, int, int], lightness: float) -> tuple[int, int, int]:
    h, _, s = colorsys.rgb_to_hls(*(v / 255 for v in c))
    r, g, b = colorsys.hls_to_rgb(h, lightness, s)
    return int(r * 255), int(g * 255), int(b * 255)


def gradient(size: tuple[int, int], top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    w, h = size
    base = Image.new("RGB", (1, h))
    for y in range(h):
        t = y / max(1, h - 1)
        base.putpixel((0, y), tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    return base.resize(size)


def wrap(draw: ImageDraw.ImageDraw, text: str, fnt, max_width: int) -> list[str]:
    """Lines that fit max_width. Urdu lines come back shaped (joined letters, right to left),
    ready to draw; they're measured shaped too."""
    if lang_mod.ARABIC.search(text or ""):
        return [lang_mod.shape(line) for line in _wrap(draw, text, fnt, max_width, measure=lang_mod.shape)]
    return _wrap(draw, text, fnt, max_width)


def _wrap(draw: ImageDraw.ImageDraw, text: str, fnt, max_width: int, measure=lambda s: s) -> list[str]:
    lines: list[str] = []
    for para in text.split("\n"):
        line = ""
        for w in para.split():
            trial = f"{line} {w}".strip()
            if draw.textlength(measure(trial), font=fnt) <= max_width:
                line = trial
                continue
            if line:
                lines.append(line)
            # A single word wider than the box (long URL or brand name) is split, never drawn off-canvas.
            while draw.textlength(measure(w), font=fnt) > max_width and len(w) > 1:
                cut = len(w) - 1
                while cut > 1 and draw.textlength(w[:cut] + "-", font=fnt) > max_width:
                    cut -= 1
                lines.append(w[:cut] + "-")
                w = w[cut:]
            line = w
        if line:
            lines.append(line)
    return lines


def fit_text(draw, text: str, max_width: int, max_height: int, start: int, minimum: int = 26, max_lines: int = 5, bold: bool = True,
             spacing: float = 1.15):
    size = start
    while size >= minimum:
        fnt = font(size, bold)
        lines = wrap(draw, text, fnt, max_width)
        line_h = int(size * spacing)
        if len(lines) <= max_lines and line_h * len(lines) <= max_height:
            return fnt, lines, line_h
        size -= 3
    fnt = font(minimum, bold)
    return fnt, wrap(draw, text, fnt, max_width)[:max_lines], int(minimum * spacing)


def paste_logo(img: Image.Image, kit: BrandKit, box: tuple[int, int, int, int], on_dark: bool, align: str = "left") -> bool:
    """on_dark puts the logo on a white chip. Every brand-coloured or photo background needs
    one: logos are usually drawn in the brand colour, so they vanish on their own colour.
    align="right" keeps the logo against the box's right edge."""
    if not kit.logo_path or not Path(kit.logo_path).exists():
        return False
    try:
        logo = Image.open(kit.logo_path).convert("RGBA")
    except OSError:
        return False
    x0, y0, x1, y1 = box
    logo = logo.crop(logo.getbbox() or (0, 0, *logo.size))
    # Fit the box both ways: many sites only offer a small logo file (a 32 px favicon), which
    # would otherwise sit tiny in the corner.
    s = min((x1 - x0) / logo.width, (y1 - y0) / logo.height)
    logo = logo.resize((max(1, int(logo.width * s)), max(1, int(logo.height * s))), Image.LANCZOS)
    if align == "right":
        x0 = x1 - logo.width
    if on_dark:
        pad = 14
        chip = Image.new("RGBA", (logo.width + pad * 2, logo.height + pad * 2), (0, 0, 0, 0))
        ImageDraw.Draw(chip).rounded_rectangle([0, 0, chip.width - 1, chip.height - 1], radius=18, fill=(255, 255, 255, 235))
        img.paste(chip, (x0 - pad, y0 - pad), chip)
    img.paste(logo, (x0, y0), logo)
    return True


def brand_label(kit: BrandKit) -> str:
    if kit.website_url:
        host = kit.website_url.split("//")[-1].split("/")[0].removeprefix("www.")
        return f"{kit.name}  ·  {host}"
    return kit.name


def draw_lines(draw, lines, fnt, line_h, x, y, fill) -> int:
    for line in lines:
        draw.text((x, y), line, font=fnt, fill=fill)
        y += line_h
    return y


def block_y(position: str, h: int, m: int, block_h: int, default: str) -> int:
    pos = default if position == "auto" else position
    if pos == "top":
        return m + int(h * 0.14)
    if pos == "center":
        return (h - block_h) // 2
    return h - m - int(h * 0.1) - block_h


def swipe_chip(draw, w: int, h: int, m: int, color, text_color) -> None:
    f = font(int(min(w, h) * 0.03))
    label = "Swipe  →"
    tw = draw.textlength(label, font=f)
    pad = 18
    x1, y1 = w - m, h - m + 8
    draw.rounded_rectangle([x1 - tw - pad * 2, y1 - f.size - pad, x1, y1 + pad // 2], radius=40, fill=color)
    draw.text((x1 - tw - pad, y1 - f.size - pad // 2), label, font=f, fill=text_color)


def cover_photo(path: str, size: tuple[int, int]) -> Image.Image:
    img = Image.open(path).convert("RGB")
    # Product shots are usually portrait with the subject's face near the top; keep it in frame.
    centering = (0.5, 0.2) if img.height > img.width * 1.15 and size[1] < img.height * size[0] / img.width else (0.5, 0.45)
    return ImageOps.fit(img, size, Image.LANCZOS, centering=centering)


def text_scrim(size: tuple[int, int], anchor: str, tint: tuple[int, int, int]) -> Image.Image:
    w, h = size
    overlay = Image.new("RGBA", size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    for y in range(h):
        t = y / h
        if anchor == "top":
            a = max(0.0, 1 - t / 0.45)
        elif anchor == "center":
            a = max(0.0, 1 - abs(t - 0.5) / 0.3) * 0.8
        else:
            a = max(0.0, (t - 0.55) / 0.45)
        # A light wash at the top keeps the logo chip and price tag legible on bright photos.
        a = max(a, max(0.0, 1 - t / 0.18) * 0.35)
        od.line([(0, y), (w, y)], fill=(*tint, int(225 * a)))
    return overlay


def price_chip(draw: ImageDraw.ImageDraw, price: str, right: int, top: int, size: int, color) -> None:
    f = font(size)
    tw = draw.textlength(price, font=f)
    pad_x, pad_y = int(size * 0.7), int(size * 0.45)
    draw.rounded_rectangle([right - tw - pad_x * 2, top, right, top + size + pad_y * 2], radius=size, fill=(255, 255, 255))
    draw.text((right - tw - pad_x, top + pad_y - size * 0.08), price, font=f, fill=shade(color, 0.25) if luminance(color) > 0.5 else color)


def busyness(img: Image.Image, box: tuple[int, int, int, int]) -> float:
    """How much is going on in part of a photo (edges and contrast): text, faces and products score high."""
    crop = img.crop(box).convert("L").resize((64, 64))
    return ImageStat.Stat(crop.filter(ImageFilter.FIND_EDGES)).mean[0] + ImageStat.Stat(crop).stddev[0] * 0.3


def photo_corners(img: Image.Image, kit: BrandKit, post: SocialPost, m: int, logo_size: tuple[int, int], price: str,
                  primary, accent, chip_size: int, badge: int, logo: bool = True) -> None:
    """Logo, price and sale badge on a photo: the logo goes in whichever top corner is calmer, so it
    doesn't cover the photo's own words or the product, and the price or badge takes the other corner."""
    w, h = img.size
    lw, lh = logo_size
    left, right = (m, m, m + lw, m + lh), (w - m - lw, m, w - m, m + lh)
    side = "left" if busyness(img, left) <= busyness(img, right) else "right"
    if logo:
        paste_logo(img, kit, left if side == "left" else right, on_dark=True, align=side)
    else:  # no logo here: the price takes the calmer corner itself
        side = "right" if side == "left" else "left"
    draw = ImageDraw.Draw(img)
    if post.kind == "sale" and sale_pct(post.product):
        sale_badge(img, sale_pct(post.product), (w - m - badge, m) if side == "left" else (m, m), badge, accent)
    elif price:
        price = price[:-3] if price.endswith(".00") else price
        chip_w = int(draw.textlength(price, font=font(chip_size))) + int(chip_size * 0.7) * 2
        price_chip(draw, price, w - m if side == "left" else m + chip_w, m, chip_size, primary)


def sale_pct(product) -> int:
    if not product or not product.was_price:
        return 0
    def num(s: str) -> float:
        m = re.search(r"\d[\d,]*(?:\.\d+)?", s or "")
        return float(m.group(0).replace(",", "")) if m else 0.0
    now, was = num(product.price), num(product.was_price)
    return round(100 * (1 - now / was)) if was > now > 0 else 0


def sale_badge(img: Image.Image, pct: int, at: tuple[int, int], d: int, fill) -> None:
    """A round "-30% OFF" sticker."""
    badge = Image.new("RGBA", (d, d), (0, 0, 0, 0))
    bd = ImageDraw.Draw(badge)
    bd.ellipse([0, 0, d - 1, d - 1], fill=(*fill, 255), outline=(255, 255, 255, 255), width=max(3, d // 40))
    big, small = font(int(d * 0.3)), font(int(d * 0.14))
    fg = text_on(fill)
    t1, t2 = f"-{pct}%", "OFF"
    bd.text(((d - bd.textlength(t1, font=big)) / 2, d * 0.24), t1, font=big, fill=fg)
    bd.text(((d - bd.textlength(t2, font=small)) / 2, d * 0.58), t2, font=small, fill=fg)
    img.paste(badge, at, badge)


def rounded_photo(path: str, size: tuple[int, int], radius: int) -> Image.Image:
    photo = cover_photo(path, size).convert("RGBA")
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size[0] - 1, size[1] - 1], radius=radius, fill=255)
    photo.putalpha(mask)
    return photo


def render_frame(kit: BrandKit, post: SocialPost, size: tuple[int, int], headline: str, scale: float) -> Image.Image:
    """The photo inset in a brand-colour frame, headline on the band below: a calmer, editorial look."""
    w, h = size
    primary, accent = rgb(kit.primary_color), rgb(kit.accent_color)
    m = int(min(w, h) * 0.06)
    wide = w > h * 1.2
    img = Image.new("RGB", size, primary)
    draw = ImageDraw.Draw(img)
    fg = text_on(primary)
    if wide:  # photo on the right, text panel on the left
        pw = int(w * 0.5)
        photo = rounded_photo(post.background.path, (pw - m, h - 2 * m), m)
        img.paste(photo, (w - pw, m), photo)
        tx, tw, top, bottom = m * 2, w - pw - m * 3, m * 2, h - m * 2
    else:
        band = int(h * 0.26)
        photo = rounded_photo(post.background.path, (w - 2 * m, h - band - 2 * m), m)
        img.paste(photo, (m, m), photo)
        tx, tw, top, bottom = m * 2, w - m * 4, h - band + int(m * 0.3), h - m
    inset = img.crop((w - pw, m, w - m, h - m)) if wide else img.crop((m, m, w - m, h - band - m))
    corner = Image.new("RGB", inset.size)
    corner.paste(inset)
    sub_post = post.model_copy(update={"product": None}) if post.kind != "sale" else post  # the price is in the band below
    photo_corners(corner, kit, sub_post, m, (int(w * (0.16 if wide else 0.22)), int(h * (0.1 if wide else 0.065))), "",
                  primary, accent, int(min(w, h) * 0.035), int(min(w, h) * 0.2))
    mask = Image.new("L", corner.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, corner.width - 1, corner.height - 1], radius=m, fill=255)
    img.paste(corner, (w - pw, m) if wide else (m, m), mask)
    draw = ImageDraw.Draw(img)
    fnt, lines, lh = fit_text(draw, headline, tw, int((bottom - top) * 0.62), int(min(w, h) * 0.085 * scale), max_lines=3)
    y = top + (int((bottom - top) * 0.3) - lh * len(lines) // 2 if wide else 0)
    y = draw_lines(draw, lines, fnt, lh, tx, max(top, y), fg)
    price = post.product.price if post.product else ""
    meta = "  ·  ".join(x for x in (price[:-3] if price.endswith(".00") else price, brand_label(kit)) if x)
    draw.rectangle([tx, y + 14, tx + 110, y + 24], fill=accent)
    draw.text((tx, min(bottom - int(min(w, h) * 0.035), y + 44)), meta, font=font(int(min(w, h) * 0.03), False), fill=fg)
    return img


def render_poster(kit: BrandKit, post: SocialPost, size: tuple[int, int], headline: str, scale: float, carousel: bool) -> Image.Image:
    """The full photo with the headline on a tilted brand-colour ribbon, like a shop-window poster."""
    w, h = size
    primary, accent = rgb(kit.primary_color), rgb(kit.accent_color)
    s = min(w, h)
    m = int(s * 0.07)
    img = cover_photo(post.background.path, size).convert("RGBA")
    probe = ImageDraw.Draw(img)
    has_logo = bool(kit.logo_path and Path(kit.logo_path).exists())
    logo_w = int(w * 0.2) if has_logo else 0
    fnt, lines, lh = fit_text(probe, headline, int(w * 0.8) - (logo_w + m if has_logo else 0), int(h * 0.22),
                              int(s * 0.085 * scale), max_lines=3)
    band_h = max(lh * len(lines) + int(s * 0.09), int(s * 0.15) if has_logo else 0)
    band = Image.new("RGBA", (int(w * 1.4), band_h), (*primary, 245))
    bd = ImageDraw.Draw(band)
    bd.rectangle([0, 0, band.width, int(s * 0.012)], fill=(*accent, 255))
    tx = (band.width - w) // 2 + m
    y = (band_h - lh * len(lines)) // 2
    for line in lines:
        bd.text((tx, y), line, font=fnt, fill=(*text_on(primary), 255))
        y += lh
    if has_logo:  # the logo rides on the ribbon, so it never covers the photo's own words or the product
        right = (band.width + w) // 2 - m
        chip_h = min(int(s * 0.08), band_h - int(s * 0.05))
        paste_logo(band, kit, (right - logo_w, (band_h - chip_h) // 2, right, (band_h + chip_h) // 2), on_dark=True, align="right")
    band = band.rotate(4, expand=True, resample=Image.BICUBIC)
    pos = post.text_position if post.text_position in ("top", "center") else "bottom"
    # "top" sits below where a model's face usually is, so the ribbon never covers it.
    cy = {"top": int(h * 0.42), "center": int(h * 0.56)}.get(pos, int(h * 0.74))
    img.alpha_composite(band, ((w - band.width) // 2, cy - band.height // 2))
    photo_corners(img, kit, post, m, (int(w * 0.22), int(h * 0.065)), post.product.price if post.product else "",
                  primary, accent, int(s * 0.04), int(s * 0.2), logo=False)
    draw = ImageDraw.Draw(img)
    label = brand_label(kit)
    lf = font(int(s * 0.03), False)
    lw = draw.textlength(label, font=lf)
    shade_layer = Image.new("RGBA", size, (0, 0, 0, 0))  # a see-through backing so the label reads on any photo
    ImageDraw.Draw(shade_layer).rounded_rectangle([m - 14, h - m - int(s * 0.03) - 12, m + lw + 14, h - m + 12], radius=20, fill=(0, 0, 0, 110))
    img.alpha_composite(shade_layer)
    draw = ImageDraw.Draw(img)
    draw.text((m, h - m - int(s * 0.03)), label, font=lf, fill=(255, 255, 255))
    if carousel:
        swipe_chip(draw, w, h, m, accent, text_on(accent))
    return img.convert("RGB")


def render_minimal(kit: BrandKit, post: SocialPost, size: tuple[int, int], headline: str, scale: float) -> Image.Image:
    """A quiet, gallery-like look: the photo on a paper background with small, dark type."""
    w, h = size
    primary = rgb(kit.primary_color)
    paper = tuple(int(250 + (c - 250) * 0.06) for c in primary)
    ink = rgb(kit.secondary_color) if luminance(rgb(kit.secondary_color)) < 0.2 else (28, 28, 34)
    img = Image.new("RGB", size, paper)
    draw = ImageDraw.Draw(img)
    s = min(w, h)
    m = int(s * 0.07)
    price = post.product.price if post.product else ""
    price = price[:-3] if price.endswith(".00") else price
    if w > h * 1.2:  # wide: photo on the right, words on the left
        pw = int(w * 0.48)
        photo = rounded_photo(post.background.path, (pw - m, h - 2 * m), int(m * 0.4))
        img.paste(photo, (w - pw, m), photo)
        tx, tw, top = m, w - pw - 2 * m, int(h * 0.3)
    else:
        ph = int(h * (0.66 if h > w else 0.6))
        photo = rounded_photo(post.background.path, (w - 2 * m, ph), int(m * 0.4))
        img.paste(photo, (m, m), photo)
        tx, tw, top = m, w - 2 * m, m + ph + int(m * 0.6)
    kicker = (kit.name.upper() + ("  ·  " + price if price else ""))
    draw.text((tx, top), kicker, font=font(int(s * 0.026)), fill=primary if luminance(primary) < 0.5 else ink)
    fnt, lines, lh = fit_text(draw, headline, tw, int(h - top - m * 1.6), int(s * 0.06 * scale), minimum=24, max_lines=3)
    y = draw_lines(draw, lines, fnt, lh, tx, top + int(s * 0.05), ink)
    draw.rectangle([tx, y + 12, tx + 60, y + 16], fill=primary)
    if post.kind == "sale" and sale_pct(post.product):
        d = int(s * 0.16)
        sale_badge(img, sale_pct(post.product), (w - m - d - 10, m + 10), d, primary)
    return img


def render_greeting(kit: BrandKit, post: SocialPost, size: tuple[int, int], headline: str, scale: float) -> Image.Image:
    """A festive card for Eid, Mother's Day, Independence Day and other occasions: the occasion's
    colours and motif, a big greeting, and the brand's logo and name to sign it."""
    w, h = size
    o = occasions.find(post.occasion or headline) or occasions.OCCASIONS["new_year"]
    primary, accent, _ = occasions.colors(o, kit.country)
    s = min(w, h)
    img = gradient(size, shade(primary, 0.36) if luminance(primary) > 0.05 else primary, shade(primary, 0.14)).convert("RGBA")
    img.alpha_composite(occasions.motif_layer(o.motif, size, (primary, accent, (0, 0, 0))))
    draw = ImageDraw.Draw(img)
    fg = accent if luminance(accent) > 0.35 else (255, 255, 255)
    start = int(s * 0.13 * scale)
    longest = max(headline.split(), key=len) if headline.split() else headline
    while start > 30 and draw.textlength(longest, font=font(start)) > w * 0.8:  # never split "Independence"
        start -= 4
    fnt, lines, lh = fit_text(draw, headline, int(w * 0.8), int(h * 0.36), start, max_lines=3)
    y = (h - lh * len(lines)) // 2 - int(h * 0.04)
    for line in lines:
        draw.text(((w - draw.textlength(line, font=fnt)) / 2, y), line, font=fnt, fill=fg)
        y += lh
    y += int(lh * 0.3)  # clear of the last line's descenders
    draw.rectangle([w // 2 - 60, y, w // 2 + 60, y + 8], fill=fg)
    sign = f"From all of us at {kit.name}"
    sf = font(int(s * 0.035), False)
    draw.text(((w - draw.textlength(sign, font=sf)) / 2, y + 34), sign, font=sf, fill=(255, 255, 255))
    lw, lh2 = int(w * 0.24), int(h * 0.08)
    paste_logo(img, kit, ((w - lw) // 2, h - int(s * 0.07) - lh2, (w + lw) // 2, h - int(s * 0.07)), on_dark=True)
    return img.convert("RGB")


def render_duo(kit: BrandKit, post: SocialPost, size: tuple[int, int]) -> Image.Image:
    """"This or that": two products side by side, lettered A and B, for a vote in the comments."""
    w, h = size
    primary, secondary, accent = rgb(kit.primary_color), rgb(kit.secondary_color), rgb(kit.accent_color)
    m = int(min(w, h) * 0.05)
    img = Image.new("RGB", size, shade(primary, 0.95))
    draw = ImageDraw.Draw(img)
    head_h = int(h * (0.2 if w <= h * 1.2 else 0.24))
    draw.rectangle([0, 0, w, head_h], fill=primary)
    paste_logo(img, kit, (m, m, m + int(w * 0.2), head_h - m), on_dark=True)
    fg = text_on(primary)
    fnt, lines, lh = fit_text(draw, post.headline or "This or that?", int(w * 0.62), head_h - m, int(head_h * 0.42), max_lines=2)
    y = (head_h - lh * len(lines)) // 2
    for line in lines:
        draw.text((w - m - draw.textlength(line, font=fnt), y), line, font=fnt, fill=fg)
        y += lh
    label_h = int(h * 0.13)
    col_w = (w - 3 * m) // 2
    ph = h - head_h - label_h - 2 * m
    items = [(post.background.path, post.product), (post.gallery[0].path, post.compare)]
    for i, (path, product) in enumerate(items):
        x = m + i * (col_w + m)
        photo = rounded_photo(path, (col_w, ph), int(m * 0.8))
        img.paste(photo, (x, head_h + m), photo)
        letter = "AB"[i]
        r = int(min(w, h) * 0.05)
        draw.ellipse([x + m // 2, head_h + m + m // 2, x + m // 2 + 2 * r, head_h + m + m // 2 + 2 * r], fill=accent)
        lf = font(int(r * 1.1))
        draw.text((x + m // 2 + r - draw.textlength(letter, font=lf) / 2, head_h + m + m // 2 + r * 0.35), letter, font=lf, fill=text_on(accent))
        if product:
            name = product.name if len(product.name) <= 26 else product.name[:25].rsplit(" ", 1)[0] + "…"
            ty = head_h + m + ph + int(m * 0.6)
            nf = font(int(label_h * 0.3))
            draw.text((x, ty), name, font=nf, fill=secondary)
            if product.price:
                price = product.price[:-3] if product.price.endswith(".00") else product.price
                draw.text((x, ty + int(label_h * 0.4)), price, font=font(int(label_h * 0.26), False), fill=shade(secondary, 0.35))
    return img


def photo_split(kit: BrandKit, post: SocialPost, size: tuple[int, int], headline: str, scale: float, price: str) -> Image.Image:
    """Wide canvas, tall product photo: show the whole photo beside a brand-colour panel."""
    w, h = size
    primary, accent = rgb(kit.primary_color), rgb(kit.accent_color)
    photo_w = int(h * 0.8)
    img = gradient((w, h), primary, shade(primary, 0.25))
    img.paste(cover_photo(post.background.path, (photo_w, h)), (w - photo_w, 0))
    draw = ImageDraw.Draw(img)
    fg = text_on(primary)
    m = int(h * 0.09)
    panel = w - photo_w
    paste_logo(img, kit, (m, m, m + int(panel * 0.42), m + int(h * 0.15)), on_dark=True)
    fnt, lines, lh = fit_text(draw, headline, panel - 2 * m, int(h * 0.45), int(h * 0.1 * scale), max_lines=4)
    y = block_y(post.text_position, h, m, lh * len(lines), "center")
    y = draw_lines(draw, lines, fnt, lh, m, y, fg)
    draw.rectangle([m, y + 22, m + 120, y + 34], fill=accent)
    if price:
        f = font(int(h * 0.055))
        draw.text((m, y + 60), price, font=f, fill=fg)
    draw.text((m, h - m), brand_label(kit), font=font(int(h * 0.032), False), fill=fg)
    return img


# --------------------------------------------------------------------------- single post / cover


def render_cover(kit: BrandKit, post: SocialPost, size: tuple[int, int], carousel: bool = False) -> Image.Image:
    w, h = size
    primary, secondary, accent = rgb(kit.primary_color), rgb(kit.secondary_color), rgb(kit.accent_color)
    m = int(min(w, h) * 0.08)
    headline = post.headline or kit.tagline or kit.name
    scale = max(0.6, min(1.5, post.text_scale or 1.0))
    layout = post.layout if post.layout in LAYOUTS else "bold"
    has_photo = bool(post.background and Path(post.background.path).exists())
    if layout == "duo" and not (has_photo and post.gallery and Path(post.gallery[0].path).exists()):
        layout = "photo"
    if layout in PHOTO_LAYOUTS and not has_photo:
        layout = "bold"
    if layout == "duo":
        return render_duo(kit, post, size)
    if layout == "frame":
        return render_frame(kit, post, size, headline, scale)
    if layout == "greeting" or post.kind == "greeting":
        return render_greeting(kit, post, size, headline, scale)
    if layout == "poster":
        return render_poster(kit, post, size, headline, scale, carousel)
    if layout == "minimal":
        return render_minimal(kit, post, size, headline, scale)

    if layout == "photo":
        price = post.product.price if post.product else ""
        with Image.open(post.background.path) as probe:
            portrait_photo = probe.height > probe.width
        if w > h * 1.2 and portrait_photo:
            return photo_split(kit, post, size, headline, scale, price)
        img = cover_photo(post.background.path, size).convert("RGBA")
        pos = post.text_position if post.text_position in POSITIONS else "auto"
        anchor = "bottom" if pos == "auto" else pos
        # Darken only where the text sits, so the product itself stays clearly visible.
        img = Image.alpha_composite(img, text_scrim(size, anchor, shade(primary, 0.08))).convert("RGB")
        draw = ImageDraw.Draw(img)
        fnt, lines, lh = fit_text(draw, headline, w - 2 * m, int(h * 0.3), int(min(w, h) * 0.095 * scale), max_lines=3)
        y = block_y(pos, h, m, lh * len(lines), "bottom")
        y = draw_lines(draw, lines, fnt, lh, m, y, (255, 255, 255))
        draw.rectangle([m, y + 22, m + 130, y + 34], fill=accent)
        photo_corners(img, kit, post, m, (int(w * 0.22), int(h * 0.065)), price, primary, accent,
                      int(min(w, h) * 0.04), int(min(w, h) * 0.2))
        draw = ImageDraw.Draw(img)
        draw.text((m, h - m), brand_label(kit), font=font(int(min(w, h) * 0.03), False), fill=(235, 235, 235))
        if carousel:
            swipe_chip(draw, w, h, m, accent, text_on(accent))
        return img

    if layout == "split" and w >= h:
        img = Image.new("RGB", (w, h), secondary)
        draw = ImageDraw.Draw(img)
        panel_x = int(w * 0.62)
        img.paste(gradient((w - panel_x, h), primary, shade(primary, 0.3)), (panel_x, 0))
        for i in range(6):
            r = int(h * (0.15 + i * 0.12))
            draw.ellipse([w - r, h - r, w + r, h + r], outline=accent, width=4)
        fg = text_on(secondary)
        fnt, lines, lh = fit_text(draw, headline, panel_x - 2 * m, h - 3 * m, int(h * 0.12 * scale))
        y = block_y(post.text_position, h, m, lh * len(lines), "center")
        draw.rectangle([m, y - 40, m + 90, y - 30], fill=accent)
        draw_lines(draw, lines, fnt, lh, m, y, fg)
        paste_logo(img, kit, (panel_x + m, m, w - m, m + int(h * 0.16)), on_dark=True)
        draw.text((m, h - m), brand_label(kit), font=font(int(h * 0.035), False), fill=fg)
        return img

    if layout == "quote":
        bg = shade(primary, 0.95)
        img = Image.new("RGB", (w, h), bg)
        draw = ImageDraw.Draw(img)
        draw.rectangle([0, 0, w, int(m * 0.35)], fill=primary)
        fnt, lines, lh = fit_text(draw, headline, w - 2 * m, int(h * 0.5), int(min(w, h) * 0.1 * scale))
        y = block_y(post.text_position, h, m, lh * len(lines), "center")
        draw.text((m - 10, max(int(m * 0.6), y - int(h * 0.2))), "\u201c", font=font(int(h * 0.26)), fill=accent)
        y = draw_lines(draw, lines, fnt, lh, m, y, secondary)
        draw.rectangle([m, y + 30, m + 120, y + 40], fill=primary)
        has_logo = paste_logo(img, kit, (m, h - m - int(h * 0.09), m + int(w * 0.3), h - m), on_dark=False)
        fx = m + int(w * 0.3) + 30 if has_logo else m
        draw.text((fx, h - m - int(h * 0.035)), brand_label(kit), font=font(int(min(w, h) * 0.032), False), fill=secondary)
        if carousel:
            swipe_chip(draw, w, h, m, primary, text_on(primary))
        return img

    # "bold" (default): full-bleed gradient, oversized headline.
    img = gradient((w, h), primary, shade(primary, 0.22))
    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    r = int(max(w, h) * 0.45)
    gd.ellipse([w - r, -r // 2, w + r, r * 1.5], fill=(*shade(primary, 0.7), 110))
    glow = glow.filter(ImageFilter.GaussianBlur(80))
    img = Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB")
    draw = ImageDraw.Draw(img)
    fg = text_on(primary)
    paste_logo(img, kit, (m, m, m + int(w * 0.28), m + int(h * 0.1)), on_dark=True)
    fnt, lines, lh = fit_text(draw, headline, w - 2 * m, int(h * 0.55), int(min(w, h) * 0.12 * scale))
    y = block_y(post.text_position, h, m, lh * len(lines), "bottom")
    y = draw_lines(draw, lines, fnt, lh, m, y, fg)
    draw.rectangle([m, y + 24, m + 140, y + 36], fill=accent)
    draw.text((m, h - m), brand_label(kit), font=font(int(min(w, h) * 0.032), False), fill=fg)
    if carousel:
        swipe_chip(draw, w, h, m, accent, text_on(accent))
    return img


# --------------------------------------------------------------------------- carousel pages


def render_slide(kit: BrandKit, post: SocialPost, index: int, total: int) -> Image.Image:
    """Content slide `index` (1-based among content slides) of a carousel with `total` pages."""
    w, h = CAROUSEL_SIZE
    primary, secondary, accent = rgb(kit.primary_color), rgb(kit.secondary_color), rgb(kit.accent_color)
    m = int(w * 0.09)
    slide = post.slides[index - 1]
    if slide.background and Path(slide.background.path).exists():
        return render_photo_slide(kit, post, slide, index, total)
    img = Image.new("RGB", (w, h), shade(primary, 0.965))
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, w, 14], fill=primary)
    pill = f"{index + 1} / {total}"
    pf = font(30)
    pw = draw.textlength(pill, font=pf)
    draw.rounded_rectangle([m, m, m + pw + 44, m + 56], radius=28, fill=primary)
    draw.text((m + 22, m + 11), pill, font=pf, fill=text_on(primary))
    draw.text((w - m - 120, m - 6), f"{index:02d}", font=font(110), fill=shade(primary, 0.88))

    top = m + int(h * 0.14)
    hf, hl, hlh = fit_text(draw, slide.headline or post.headline, w - 2 * m, int(h * 0.3), 76, minimum=40, max_lines=4)
    y = draw_lines(draw, hl, hf, hlh, m, top, secondary)
    draw.rectangle([m, y + 26, m + 110, y + 36], fill=accent)
    if slide.body:
        bf, bl, blh = fit_text(draw, slide.body, w - 2 * m, h - (y + 90) - int(h * 0.16), 46, minimum=28, max_lines=9, bold=False, spacing=1.4)
        draw_lines(draw, bl, bf, blh, m, y + 80, shade(secondary, 0.3) if luminance(secondary) < 0.3 else (51, 65, 85))
    draw.text((m, h - m), brand_label(kit), font=font(28, False), fill=(100, 116, 139))
    swipe_chip(draw, w, h, m, primary, text_on(primary))
    return img


def render_photo_slide(kit: BrandKit, post: SocialPost, slide, index: int, total: int) -> Image.Image:
    """A carousel page built around a real photo (one product per page)."""
    w, h = CAROUSEL_SIZE
    primary, accent = rgb(kit.primary_color), rgb(kit.accent_color)
    m = int(w * 0.08)
    img = cover_photo(slide.background.path, (w, h)).convert("RGBA")
    img = Image.alpha_composite(img, text_scrim((w, h), "bottom", shade(primary, 0.08))).convert("RGB")
    draw = ImageDraw.Draw(img)
    pill = f"{index + 1} / {total}"
    pf = font(30)
    pw = draw.textlength(pill, font=pf)
    draw.rounded_rectangle([w - m - pw - 44, m, w - m, m + 56], radius=28, fill=(255, 255, 255))
    draw.text((w - m - pw - 22, m + 11), pill, font=pf, fill=primary if luminance(primary) < 0.6 else (30, 30, 30))
    paste_logo(img, kit, (m, m, m + int(w * 0.26), m + int(h * 0.08)), on_dark=True)
    bf, bl, blh = (None, [], 0)
    if slide.body:
        bf, bl, blh = fit_text(draw, slide.body, w - 2 * m, int(h * 0.12), 38, minimum=26, max_lines=3, bold=False)
    hf, hl, hlh = fit_text(draw, slide.headline or post.headline, w - 2 * m, int(h * 0.2), 72, minimum=40, max_lines=3)
    block = hlh * len(hl) + (blh * len(bl) + 30 if bl else 0)
    y = h - m - int(h * 0.07) - block
    y = draw_lines(draw, hl, hf, hlh, m, y, (255, 255, 255))
    if bl:
        draw_lines(draw, bl, bf, blh, m, y + 20, (235, 235, 235))
    draw.text((m, h - m), brand_label(kit), font=font(28, False), fill=(225, 225, 225))
    swipe_chip(draw, w, h, m, accent, text_on(accent))
    return img


def render_cta(kit: BrandKit, post: SocialPost, total: int) -> Image.Image:
    w, h = CAROUSEL_SIZE
    primary, accent = rgb(kit.primary_color), rgb(kit.accent_color)
    m = int(w * 0.09)
    img = gradient((w, h), primary, shade(primary, 0.2))
    draw = ImageDraw.Draw(img)
    fg = text_on(primary)
    has_logo = paste_logo(img, kit, (w // 2 - 160, int(h * 0.18), w // 2 + 160, int(h * 0.18) + 150), on_dark=True)
    cta = post.cta or "Follow for more"
    fnt, lines, lh = fit_text(draw, cta, w - 2 * m, int(h * 0.3), 92, minimum=44, max_lines=4)
    y = int(h * 0.42) if has_logo else (h - lh * len(lines)) // 2
    for line in lines:
        lw = draw.textlength(line, font=fnt)
        draw.text(((w - lw) / 2, y), line, font=fnt, fill=fg)
        y += lh
    label = brand_label(kit)
    lf = font(34, False)
    draw.rectangle([w // 2 - 70, y + 30, w // 2 + 70, y + 40], fill=accent)
    draw.text(((w - draw.textlength(label, font=lf)) / 2, y + 80), label, font=lf, fill=fg)
    pf = font(28)
    pill = f"{total} / {total}"
    draw.text(((w - draw.textlength(pill, font=pf)) / 2, h - m), pill, font=pf, fill=shade(primary, 0.75))
    return img


def render_pages(kit: BrandKit, post: SocialPost) -> list[Image.Image]:
    if post.format == "carousel" and post.slides:
        total = len(post.slides) + 2
        pages = [render_cover(kit, post, CAROUSEL_SIZE, carousel=True)]
        pages += [render_slide(kit, post, i, total) for i in range(1, len(post.slides) + 1)]
        pages.append(render_cta(kit, post, total))
        return pages
    return [render_cover(kit, post, SIZES[post.platform])]


def render(kit: BrandKit, post: SocialPost) -> Image.Image:
    return render_pages(kit, post)[0]


def render_post(kit: BrandKit, post: SocialPost) -> None:
    """Render every page of the post to disk and set image_url / image_urls."""
    stamp = int(time.time() * 1000)
    urls = []
    for old in config.MEDIA_DIR.glob(f"{post.campaign_id}_{post.id}*.png"):
        old.unlink(missing_ok=True)
    for i, page in enumerate(render_pages(kit, post)):
        name = f"{post.campaign_id}_{post.id}{'' if i == 0 else f'_{i}'}.png"
        page.save(config.MEDIA_DIR / name, optimize=True)
        urls.append(f"/media/{name}?v={stamp}")
    post.image_url, post.image_urls = urls[0], urls


def render_to_file(kit: BrandKit, post: SocialPost) -> str:
    render_post(kit, post)
    return post.image_url or ""


async def render_posts(kit: BrandKit, posts: list[SocialPost]) -> None:
    await asyncio.gather(*(asyncio.to_thread(render_post, kit, p) for p in posts))
