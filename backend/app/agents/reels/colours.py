"""Reel colour palettes worked out from a brand's colours, plus curated and custom ones."""
from __future__ import annotations

import colorsys
import re
from collections import Counter
from dataclasses import dataclass


from ...schemas import BrandKit, Campaign, SocialPost
from ..renderer import luminance, rgb, shade


# --------------------------------------------------------------------------- colours


def _hex(c) -> str:
    return "#%02X%02X%02X" % tuple(int(v) for v in c)


def hue_shift(c, degrees: float, lightness: float | None = None) -> tuple[int, int, int]:
    h, l, s = colorsys.rgb_to_hls(*(v / 255 for v in c))
    r, g, b = colorsys.hls_to_rgb((h + degrees / 360) % 1, l if lightness is None else lightness, max(s, 0.45))
    return int(r * 255), int(g * 255), int(b * 255)


def _brand(p, a, i):
    return p, a, i


def _midnight(p, a, i):
    return shade(p, 0.11), shade(p, 0.62) if luminance(shade(p, 0.62)) > 0.15 else (255, 255, 255), (20, 20, 26)


def _pastel(p, a, i):
    return shade(p, 0.86), shade(p, 0.42), shade(p, 0.16)


def _complement(p, a, i):
    return hue_shift(p, 180, 0.42), p if luminance(p) > 0.08 else shade(p, 0.6), (22, 22, 28)


def _custom(color):
    def make(p, a, i):
        # The picked colour is what people notice (caption blocks, stickers, bars, price chips),
        # so it's the accent; a deep shade of it is the background.
        c = rgb(color)
        accent = c if luminance(c) > 0.06 else shade(c, 0.6)
        base = shade(c, 0.3) if luminance(c) > 0.12 else c
        return base, accent, shade(c, 0.12)
    return make


@dataclass(frozen=True)
class Palette:
    key: str
    label: str
    make: object  # (primary, accent, ink) -> (primary, accent, ink)


PALETTES: dict[str, Palette] = {p.key: p for p in [
    Palette("brand", "Your brand", _brand),
    Palette("midnight", "Night", _midnight),
    Palette("pastel", "Soft", _pastel),
    Palette("complement", "Pop", _complement),
    Palette("mono", "Mono", lambda p, a, i: ((22, 22, 26), (255, 255, 255), (17, 17, 17))),
    Palette("sunset", "Sunset", lambda p, a, i: ((226, 88, 52), (255, 202, 88), (48, 20, 14))),
    Palette("ocean", "Ocean", lambda p, a, i: ((14, 74, 128), (92, 200, 245), (10, 26, 42))),
    Palette("forest", "Forest", lambda p, a, i: ((28, 70, 52), (156, 216, 180), (12, 30, 22))),
    Palette("berry", "Berry", lambda p, a, i: ((122, 28, 86), (255, 150, 182), (36, 10, 26))),
]}
AUTO_PALETTES = ["brand", "midnight", "pastel", "complement"]  # rotated for reels nobody customised; all on-brand
PACES = {"relaxed": 1.25, "normal": 1.0, "snappy": 0.8}
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def palette_colors(kit: BrandKit, key: str, color: str = "") -> tuple:
    base = (rgb(kit.primary_color), rgb(kit.accent_color), rgb(kit.secondary_color))
    make = _custom(color) if key == "custom" and HEX.match(color or "") else PALETTES.get(key, PALETTES["brand"]).make
    return tuple(tuple(int(v) for v in c) for c in make(*base))


def palette_kit(kit: BrandKit, key: str, color: str = "") -> BrandKit:
    p, a, i = palette_colors(kit, key, color)
    return kit.model_copy(update={"primary_color": _hex(p), "accent_color": _hex(a), "secondary_color": _hex(i)})


def palette_list(kit: BrandKit) -> list[dict]:
    return [{"key": p.key, "label": p.label, "colors": [_hex(c) for c in palette_colors(kit, p.key)]} for p in PALETTES.values()]


def choose_palette(campaign: Campaign, post: SocialPost, avoid: str = "") -> str:
    """The on-brand palette this campaign's other reels have used least (your brand colours first)."""
    others = {p.group_id or p.id: p.reel_options.palette for p in campaign.posts
              if p.video_url and (p.group_id or p.id) != (post.group_id or post.id)}
    used = Counter(others.values())
    keys = [k for k in AUTO_PALETTES if k != avoid] or AUTO_PALETTES
    return min(keys, key=lambda k: used[k])
