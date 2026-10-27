"""Special occasions: Eid, Ramadan, Mother's, Father's and Women's Day, Independence Day, a
brand's anniversary, sales and more, each with its greeting, festive colours and a motif.

Greeting posts and occasion reels use these. Wording is warm but never states facts about the
brand (no invented offers, dates or discounts): a sale is only called a sale when it's one of
the market's sale days or the owner picked it, and percentages come from real prices.
"""
from __future__ import annotations

import math
import random
import re
from dataclasses import dataclass, field
from functools import lru_cache

from PIL import Image, ImageDraw


@dataclass(frozen=True)
class Occasion:
    key: str
    label: str
    match: str  # regex over the calendar's moment names
    greeting: str  # "{name}" is the moment's own name ("Independence Day", "11.11 sale")
    hooks: tuple[str, ...]
    lines: dict = field(default_factory=dict)  # flavour (wear | food | other) -> scene lines; {brand}, {name}
    ctas: tuple[str, ...] = ()
    colors: tuple = ((11, 110, 79), (233, 196, 106), (16, 32, 26))  # primary, accent, ink
    motif: str = "sparkle"  # moon | hearts | bunting | confetti | sparkle
    selling: bool = True  # whether products belong in it (a greeting card doesn't push products)


GIFT = {"wear": ["A gift she'll actually wear", "Wrapped and ready", "The easy gift"],
        "food": ["Treat them today", "Dinner, sorted", "A table for the whole family"],
        "other": ["A gift they'll remember", "Made for sharing", "The easy gift"]}

OCCASIONS: dict[str, Occasion] = {o.key: o for o in [
    Occasion("eid_fitr", "Eid al-Fitr", r"eid al-fitr|eid ul fitr", "Eid Mubarak",
             ("Eid Mubarak", "Your Eid edit", "Eid is almost here", "Ready for Eid?"),
             {"wear": ["Your Eid look, sorted", "For the first day of Eid", "Made for Eid gatherings", "Chaand raat ready"],
              "food": ["For the Eid table", "Eid feasts start here", "Sweet Eid mornings", "Feeding the whole family"],
              "other": ["Made for Eid", "Something special for Eid", "Eid, sorted", "For everyone you love"]},
             ("Eid Mubarak from {brand}", "Celebrate with {brand}", "Find your Eid pick"),
             ((11, 92, 66), (233, 196, 106), (14, 30, 24)), "moon"),
    Occasion("eid_adha", "Eid al-Adha", r"eid al-adha|eid ul adha|bakra", "Eid al-Adha Mubarak",
             ("Eid al-Adha Mubarak", "Eid is almost here", "Ready for Eid?"),
             {"wear": ["Dressed for Eid day", "For family gatherings", "Your Eid look"],
              "food": ["For the Eid table", "Feeding the whole family", "Eid feasts start here"],
              "other": ["Something special for Eid", "For everyone you love", "Eid, sorted"]},
             ("Eid Mubarak from {brand}", "Celebrate with {brand}"), ((12, 84, 96), (233, 196, 106), (12, 26, 30)), "moon"),
    Occasion("ramadan", "Ramadan", r"ramadan", "Ramadan Kareem",
             ("Ramadan Kareem", "Ramadan is here", "For the blessed month"),
             {"wear": ["Easy for iftar evenings", "Calm, comfortable, ready", "For taraweeh nights"],
              "food": ["Iftar, sorted", "For sehri and iftar", "Break your fast with us"],
              "other": ["For the blessed month", "Ramadan, made easier", "With you all month"]},
             ("Ramadan Kareem from {brand}",), ((22, 36, 71), (233, 196, 106), (12, 18, 36)), "moon", True),
    Occasion("mothers", "Mother's Day", r"mother'?s day", "Happy Mother's Day",
             ("Happy Mother's Day", "For the one who does it all", "Made for mum"),
             GIFT, ("Celebrate her with {brand}", "Happy Mother's Day from {brand}"),
             ((194, 24, 91), (248, 187, 208), (60, 10, 30)), "hearts"),
    Occasion("fathers", "Father's Day", r"father'?s day", "Happy Father's Day",
             ("Happy Father's Day", "For the one who taught us everything", "Made for dad"),
             {"wear": ["A gift he'll actually wear", "Sharp, simple, his", "The easy gift"],
              "food": ["Treat dad today", "Dinner's on us, dad", "His favourite, sorted"],
              "other": ["A gift he'll remember", "For the best dad", "The easy gift"]},
             ("Celebrate him with {brand}", "Happy Father's Day from {brand}"), ((29, 53, 87), (168, 218, 220), (12, 22, 36)), "bunting"),
    Occasion("womens", "Women's Day", r"women'?s day", "Happy Women's Day",
             ("Happy Women's Day", "Here's to the women who inspire us", "For every woman"),
             {"wear": ["Made for every woman", "Wear what makes you feel strong", "For her, by design"],
              "food": ["Lunch with the girls", "Celebrate her today", "For every woman at the table"],
              "other": ["Here's to her", "For every woman", "Celebrate her today"]},
             ("Happy Women's Day from {brand}",), ((106, 27, 154), (225, 190, 231), (36, 10, 52)), "sparkle", False),
    Occasion("independence", "Independence Day", r"independence day|pakistan day|national day|republic day|quaid", "Happy {name}",
             ("Happy {name}", "Proudly local", "Celebrating {name}"),
             {"wear": ["Dressed for the celebrations", "Proudly local", "Wear your colours"],
              "food": ["Celebrate with a feast", "Proudly local flavours", "For the celebrations"],
              "other": ["Proudly local", "Here's to the nation", "Celebrating together"]},
             ("Happy {name} from {brand}",), ((1, 65, 28), (255, 255, 255), (8, 30, 14)), "bunting", False),
    Occasion("anniversary", "Anniversary", r"anniversary", "Happy anniversary to us",
             ("Celebrating {brand}", "Thank you for being with us", "It's our anniversary"),
             {"wear": ["Thank you for wearing us", "Here's to many more", "Made possible by you"],
              "food": ["Thank you for every visit", "Here's to many more", "Made possible by you"],
              "other": ["Thank you for being with us", "Here's to many more", "Made possible by you"]},
             ("Thank you from {brand}", "Celebrate with us"), ((184, 134, 11), (255, 236, 179), (40, 28, 6)), "confetti"),
    Occasion("sale", "Sale", r"sale|black friday|white friday|cyber monday|11\.11|12\.12", "{name}",
             ("The {name} is here", "Don't miss the {name}", "{name}: our picks"),
             {"wear": ["Grab it before it's gone", "Your sale pick", "Add to cart, now"],
              "food": ["Order before it's gone", "Your sale pick", "Treat yourself"],
              "other": ["Grab it before it's gone", "Your sale pick", "Don't wait on this one"]},
             ("Shop the {name} at {brand}", "Find your pick at {brand}"), ((214, 40, 40), (252, 191, 73), (40, 8, 8)), "confetti"),
    Occasion("new_year", "New Year", r"new year", "Happy New Year",
             ("Happy New Year", "Hello, new year", "New year, new favourites"),
             {"wear": ["Start the year in style", "Your first look of the year"], "food": ["Start the year deliciously", "Your first treat of the year"],
              "other": ["Start the year right", "New year, new favourites"]},
             ("Happy New Year from {brand}",), ((20, 20, 40), (240, 200, 90), (10, 10, 20)), "confetti"),
    Occasion("valentines", "Valentine's Day", r"valentine", "Happy Valentine's Day",
             ("Happy Valentine's Day", "For the one you love"), GIFT, ("With love, from {brand}",),
             ((190, 18, 60), (255, 179, 193), (60, 6, 20)), "hearts"),
    Occasion("christmas", "Christmas", r"christmas", "Merry Christmas",
             ("Merry Christmas", "The festive edit"), GIFT, ("Merry Christmas from {brand}",),
             ((165, 28, 48), (52, 140, 90), (30, 10, 12)), "sparkle"),
    Occasion("diwali", "Diwali", r"diwali", "Happy Diwali",
             ("Happy Diwali", "The festival of lights"), GIFT, ("Happy Diwali from {brand}",),
             ((128, 30, 90), (255, 183, 3), (36, 8, 28)), "sparkle"),
]}

INDEPENDENCE_COLORS = {"PK": ((1, 65, 28), (255, 255, 255)), "IN": ((255, 153, 51), (19, 136, 8)),
                       "US": ((30, 56, 120), (200, 30, 45)), "BD": ((0, 106, 78), (244, 42, 65)),
                       "AE": ((0, 115, 47), (206, 17, 38)), "SA": ((0, 108, 53), (255, 255, 255))}


def find(name: str) -> Occasion | None:
    """The occasion a calendar moment (or an owner's pick) belongs to: "Eid al-Fitr" -> eid_fitr."""
    if name in OCCASIONS:
        return OCCASIONS[name]
    low = (name or "").lower()
    return next((o for o in OCCASIONS.values() if re.search(o.match, low)), None)


def colors(occasion: Occasion, country: str = "") -> tuple:
    if occasion.key == "independence" and country.upper() in INDEPENDENCE_COLORS:
        p, a = INDEPENDENCE_COLORS[country.upper()]
        return p, a, occasion.colors[2]
    return occasion.colors


def fill(text: str, brand: str, name: str) -> str:
    return text.replace("{brand}", brand).replace("{name}", name)


def greeting(occasion: Occasion, brand: str, name: str = "") -> str:
    return fill(occasion.greeting, brand, name or occasion.label)


GREETING_CAPTIONS = {
    "eid_fitr": "Eid Mubarak from all of us at {brand}. Wishing you and your family a day full of joy, good food and time together.",
    "eid_adha": "Eid al-Adha Mubarak from everyone at {brand}. May your home be full of blessings, family and good food.",
    "ramadan": "Ramadan Kareem from {brand}. Wishing you a peaceful, blessed month with the people you love.",
    "mothers": "Happy Mother's Day from {brand}. To every mother who makes it all look easy: thank you.",
    "fathers": "Happy Father's Day from {brand}. Here's to the dads, the granddads and everyone who stepped up.",
    "womens": "Happy Women's Day from {brand}. Here's to the women who lead, build, create and inspire, today and every day.",
    "independence": "Happy {name} from {brand}. Proud to be part of this country's story.",
    "anniversary": "It's our anniversary, and it's all thanks to you. From everyone at {brand}: thank you.",
    "new_year": "Happy New Year from {brand}. Thank you for being with us. Here's to the year ahead.",
    "valentines": "Happy Valentine's Day from {brand}. However you're celebrating, we hope it's a sweet one.",
    "christmas": "Merry Christmas from all of us at {brand}. Wishing you a warm, happy holiday.",
    "diwali": "Happy Diwali from {brand}. Wishing you light, joy and time with the people you love.",
    "sale": "The {name} is here. Have a look at {brand} and find your pick.",
}


def greeting_caption(occasion: Occasion, brand: str, name: str = "") -> str:
    return fill(GREETING_CAPTIONS.get(occasion.key, "{name} from {brand}."), brand, name or occasion.label)


# --------------------------------------------------------------------------- motifs


def _star(d: ImageDraw.ImageDraw, cx: float, cy: float, r: float, fill) -> None:
    pts = []
    for i in range(10):
        a = -math.pi / 2 + i * math.pi / 5
        rr = r if i % 2 == 0 else r * 0.45
        pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    d.polygon(pts, fill=fill)


def _heart(d: ImageDraw.ImageDraw, cx: float, cy: float, r: float, fill) -> None:
    d.ellipse([cx - r, cy - r * 0.6, cx, cy + r * 0.4], fill=fill)
    d.ellipse([cx, cy - r * 0.6, cx + r, cy + r * 0.4], fill=fill)
    d.polygon([(cx - r * 0.97, cy), (cx + r * 0.97, cy), (cx, cy + r * 1.2)], fill=fill)


@lru_cache(maxsize=16)
def _crescent(size: int, color: tuple) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    mask = Image.new("L", (size, size), 0)
    md = ImageDraw.Draw(mask)
    md.ellipse([0, 0, size - 1, size - 1], fill=255)
    md.ellipse([int(size * 0.28), int(-size * 0.08), int(size * 1.18), int(size * 0.86)], fill=0)
    img.paste(Image.new("RGBA", (size, size), (*color, 255)), (0, 0), mask)
    return img


def motif_layer(motif: str, size: tuple[int, int], palette: tuple, t: float = 0.0, seed: int = 7) -> Image.Image:
    """Festive decoration kept to the edges of the frame, so it never covers the words.
    `t` (seconds) animates it in reels: stars twinkle, hearts float up, confetti falls, bunting sways."""
    w, h = size
    s = min(w, h)
    primary, accent = palette[0], palette[1]
    light = (255, 255, 255) if sum(accent) < 200 else accent
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    rnd = random.Random(seed)
    if motif == "moon":
        moon = _crescent(int(s * 0.2), light)
        img.alpha_composite(moon, (int(w - s * 0.27), int(s * 0.07)))
        for i in range(9):
            x, y = rnd.uniform(0.04, 0.96) * w, rnd.uniform(0.02, 0.2) * h
            tw = 0.55 + 0.45 * math.sin(t * 3 + i)
            _star(d, x, y, s * rnd.uniform(0.008, 0.018), (*light, int(230 * tw)))
        for i, x in enumerate((0.1, 0.22)):  # two hanging lanterns
            sway = math.sin(t * 2 + i) * s * 0.01
            top, length = 0, s * (0.12 + 0.05 * i)
            cx = w * x + sway
            d.line([(w * x, top), (cx, top + length)], fill=(*light, 200), width=max(2, s // 300))
            d.rounded_rectangle([cx - s * 0.025, top + length, cx + s * 0.025, top + length + s * 0.06], radius=int(s * 0.012),
                                fill=(*accent, 230), outline=(*light, 255), width=max(2, s // 400))
    elif motif == "hearts":
        for i in range(12):
            x = rnd.uniform(0.03, 0.97) * w
            base = rnd.uniform(0, 1)
            y = (1 - ((base + t * 0.08) % 1)) * h
            if 0.3 * h < y < 0.75 * h and 0.2 * w < x < 0.8 * w:
                continue  # keep the middle clear for the words
            _heart(d, x, y, s * rnd.uniform(0.015, 0.03), (*(accent if i % 2 else light), 170))
    elif motif == "confetti":
        cols = [accent, light, primary if sum(primary) > 150 else accent]
        for i in range(40):
            x = rnd.uniform(0, 1) * w
            y = ((rnd.uniform(0, 1) + t * rnd.uniform(0.08, 0.16)) % 1) * h
            if 0.28 * h < y < 0.78 * h and 0.12 * w < x < 0.88 * w:
                continue
            a = rnd.uniform(0, math.pi) + t * 3
            r = s * rnd.uniform(0.006, 0.012)
            pts = [(x + r * 2 * math.cos(a + k * math.pi / 2) * (1 if k % 2 else 0.45),
                    y + r * 2 * math.sin(a + k * math.pi / 2) * (1 if k % 2 else 0.45)) for k in range(4)]
            d.polygon(pts, fill=(*cols[i % len(cols)], 235))
    elif motif == "bunting":
        n = 9
        for row, (y0, dip) in enumerate(((s * 0.03, s * 0.05),)):
            for i in range(n):
                x0, x1 = w * i / n, w * (i + 1) / n
                sway = math.sin(t * 2.5 + i) * s * 0.004
                yl = y0 + dip * math.sin(math.pi * i / n)
                yr = y0 + dip * math.sin(math.pi * (i + 1) / n)
                tip = ((x0 + x1) / 2 + sway, (yl + yr) / 2 + s * 0.07)
                d.polygon([(x0, yl), (x1, yr), tip], fill=(*(accent if i % 2 else light if sum(primary) < 300 else primary), 240))
            d.line([(0, y0), (w, y0 + dip * 0.2)], fill=(*light, 200), width=max(2, s // 350))
    else:  # sparkle
        for i in range(14):
            x, y = rnd.uniform(0.03, 0.97) * w, rnd.choice((rnd.uniform(0.02, 0.22), rnd.uniform(0.8, 0.97))) * h
            tw = 0.4 + 0.6 * abs(math.sin(t * 2.2 + i * 1.3))
            _star(d, x, y, s * rnd.uniform(0.008, 0.02) * (0.7 + 0.3 * tw), (*(light if i % 3 else accent), int(240 * tw)))
    return img


def occasion_list(country: str = "") -> list[dict]:
    out = []
    for o in OCCASIONS.values():
        p, a, _ = colors(o, country)
        out.append({"key": o.key, "label": o.label, "greeting": greeting(o, "", o.label if o.key != "independence" else "Independence Day"),
                    "colors": ["#%02X%02X%02X" % p, "#%02X%02X%02X" % a]})
    return out
