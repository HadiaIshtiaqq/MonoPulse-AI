"""The five reel styles: each draws one scene at a time, with its own layout, motion and type."""
from __future__ import annotations

import math
import random
from collections import Counter
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

from ...schemas import BrandKit, Campaign, SocialPost
from ..renderer import cover_photo, font, gradient, luminance, rgb, shade, text_on, text_scrim

from .core import H, M, Scene, W, _seed
from .draw import caption_blocks, dotted, drop_shadow, ease_out, faded, ken_burns, line_images, logo_chip, mix, paste_center, pill, rounded, scaled, soft_glow, spring, sticker, text_block

# --------------------------------------------------------------------------- styles


class Base:
    """Draws one scene of a reel at local time t (seconds from the scene's start)."""
    upper = False

    def __init__(self, kit: BrandKit, scene: Scene, index: int, count: int, prev: list["Base"], upper: bool | None = None):
        self.kit, self.scene, self.index, self.count, self.prev = kit, scene, index, count, prev
        if upper is not None:
            self.upper = upper
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
