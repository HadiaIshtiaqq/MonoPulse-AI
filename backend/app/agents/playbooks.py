"""Industry playbooks: the content pillars, audience need and voice rules that work for each
kind of business, filled in with the brand's own facts (product lines, prices, sales,
who it sells to, where). Used when no model is configured, and as guidance for one."""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..schemas import BrandKit
from .calendar import COUNTRY_NAMES


@dataclass(frozen=True)
class Playbook:
    category: str  # what the brand sells, in plain words
    need: str  # what the audience wants from it
    pillars: tuple[tuple[str, str], ...]
    voice: tuple[str, ...]


PLAYBOOKS: dict[str, Playbook] = {
    "footwear": Playbook(
        "footwear", "shoes that look right, feel comfortable all day and are worth the price",
        (("New Arrivals & Bestsellers", "The newest styles and the ones customers buy most, shown on foot."),
         ("Comfort & Fit", "Soles, materials and sizing tips: why {brand} shoes feel good all day."),
         ("Style It", "Pairings for work, weddings, Eid, school and weekends."),
         ("Offers & Occasions", "Sales and seasonal edits with real prices and dates.")),
        ("Show the shoe on foot or close up, never a generic lifestyle shot", "Name the line and who it's for (men, women, kids)",
         "Always give the real price, and the old price when it's on sale", "Talk about comfort and fit in concrete terms"),
    ),
    "fashion": Playbook(
        "clothing", "outfits that suit the occasion, fit well and feel special without overspending",
        (("New Collection Drops", "Each new collection and piece, with the fabric and the price."),
         ("How to Style It", "Ways to wear a piece: accessories, occasions, day to night."),
         ("Craft & Fabric", "Prints, embroidery and fabrics up close: what makes {brand} pieces different."),
         ("Occasion Edits", "Wedding, festive, office and everyday edits, with sales when they're on.")),
        ("Lead with the piece, not the brand", "Mention fabric, cut and occasion", "Give the real price",
         "Describe colours and details the photo shows; never invent them"),
    ),
    "jewellery": Playbook(
        "jewellery", "pieces that feel personal, suit the occasion and are worth gifting",
        (("Signature Pieces", "Bestsellers and new designs, with materials and price."),
         ("Gift Guides", "What to give for birthdays, weddings, anniversaries and Eid."),
         ("Craftsmanship", "How {brand} pieces are made and finished."), ("Styling & Care", "Layering, pairing and keeping pieces bright.")),
        ("Show the piece in close-up", "Name the metal, stone and finish", "Give the real price", "Speak to the occasion"),
    ),
    "home": Playbook(
        "furniture and home decor", "pieces that fit their space, last for years and make the room feel finished",
        (("Room Ideas", "Rooms styled with {brand} pieces, with what's in the shot."), ("Product Spotlight", "One piece at a time: size, material, price."),
         ("Made to Last", "Materials, build and care."), ("Offers & New Arrivals", "Sales and new pieces, with dates.")),
        ("Give dimensions and materials", "Show the piece in a real room", "Give the real price", "Be specific about care and delivery"),
    ),
    "food": Playbook(
        "food and drink", "something delicious they can count on, at a fair price, close by",
        (("Menu Spotlight", "One dish or drink at a time: what's in it and what it costs."), ("Behind the Kitchen", "How {brand} makes it, and who makes it."),
         ("Regulars & Reviews", "What customers order and say."), ("Seasonal Specials", "Limited dishes, deals and holiday menus with dates.")),
        ("Describe taste and texture, not adjectives like 'amazing'", "Give the price and where to get it", "Post food at its best moment",
         "Mention opening hours and ordering when relevant"),
    ),
    "beauty": Playbook(
        "beauty and personal care", "products and treatments that actually work for them",
        (("Product Spotlight", "One product or service at a time: what it does, who it's for, price."), ("Routines & Tips", "Step-by-step routines and how-tos."),
         ("Real Results", "Before-and-after and customer stories, with consent."), ("Launches & Offers", "New products and deals with dates.")),
        ("Say who a product suits (skin or hair type)", "No medical claims", "Give the real price", "Show texture and results honestly"),
    ),
    "fitness": Playbook(
        "fitness and wellness", "results they can see, a schedule they can keep and people who keep them going",
        (("Workouts & Tips", "Short, useful exercises and habits."), ("Member Wins", "Real progress from members, with consent."),
         ("Inside the Club", "Coaches, classes and the space."), ("Classes & Offers", "Schedules, trials and membership deals.")),
        ("Encourage, never shame", "Be specific about class times and prices", "No medical or weight-loss promises", "Show real members and coaches"),
    ),
    "software": Playbook(
        "software", "to save time, reduce mistakes and see results quickly",
        (("How-tos", "One feature or workflow at a time, step by step."), ("Customer Results", "Numbers and stories from real customers."),
         ("Industry Insights", "What's changing in the field and what it means."), ("Product Updates", "New features and why they matter.")),
        ("Lead with the problem solved", "Use real numbers", "Show the product, not stock photos", "Avoid jargon"),
    ),
    "real estate": Playbook(
        "property", "the right home or investment, with honest advice and no surprises",
        (("Featured Listings", "Homes with price, size and location."), ("Neighbourhood Guides", "What it's like to live there."),
         ("Buyer & Seller Tips", "Practical advice for each step."), ("Market Updates", "Prices and trends in the area.")),
        ("Always give price, size and area", "Be accurate about locations", "Explain the process plainly", "Show the property honestly"),
    ),
}
DEFAULT = Playbook(
    "products and services", "something good, from people they trust, at a fair price",
    (("Product Spotlight", "One product or service at a time, with the price."), ("Behind the Scenes", "How {brand} works and who does it."),
     ("Customer Stories", "Real customers and what they chose."), ("Tips & Offers", "Useful advice, plus deals with dates.")),
    ("Be specific: products, prices, places", "Talk like a person, not a press release", "One idea per post", "End with a clear next step"),
)

PLAYBOOK_KEYS = [("footwear", "footwear"), ("shoe", "footwear"), ("fashion", "fashion"), ("apparel", "fashion"), ("cloth", "fashion"),
                 ("jewel", "jewellery"), ("furniture", "home"), ("home decor", "home"), ("food", "food"), ("restaurant", "food"),
                 ("cafe", "food"), ("bakery", "food"), ("beauty", "beauty"), ("salon", "beauty"), ("skincare", "beauty"),
                 ("fitness", "fitness"), ("gym", "fitness"), ("wellness", "fitness"), ("software", "software"), ("saas", "software"),
                 ("real estate", "real estate"), ("property", "real estate")]


# Words that show a news story is about this kind of business (used to filter trends):
# (broad words that also appear in generic industry reports, specific words that don't).
TERMS = {
    "footwear": ((), ("footwear", "shoe", "sneaker", "sandal", "boot", "heels", "slipper", "loafer", "trainers")),
    "fashion": (("fashion", "clothing", "apparel"), ("dress", "outfit", "bridal", "couture", "lawn", "kurta", "embroider", "designer")),
    "jewellery": ((), ("jewel", "necklace", "earring", "bracelet", "diamond", "bridal")),
    "home": (("home decor",), ("furniture", "interior", "sofa", "mattress")),
    "food": (("food", "restaurant", "beverage", "drink"), ("bakery", "bread", "cafe", "coffee", "chef", "dining", "pastry", "dessert")),
    "beauty": (("beauty",), ("skincare", "makeup", "salon", "haircare", "cosmetic")),
    "fitness": (("fitness", "wellness"), ("gym", "workout", "yoga", "pilates")),
    "software": (("software", "tech"), ("saas", "productivity", "automation")),
    "real estate": (("real estate", "property"), ("housing", "mortgage", "homebuyer")),
}
# How to address each industry's audience when the site doesn't say (men, women, kids).
WHO = {"footwear": "shoppers", "fashion": "shoppers", "jewellery": "shoppers", "home": "homeowners and renters",
       "food": "locals and visitors", "beauty": "people", "fitness": "people", "software": "teams", "real estate": "buyers, sellers and renters"}


def playbook_key(industry: str) -> str:
    low = industry.lower()
    return next((key for word, key in PLAYBOOK_KEYS if word in low), "")


def playbook_for(industry: str) -> Playbook:
    return PLAYBOOKS.get(playbook_key(industry), DEFAULT)


def join_words(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1] if items else ""


def tidy_price(price: str) -> str:
    """"Rs.4,199.00" -> "Rs.4,199" (only an exact .00 is dropped)."""
    return price[:-3] if price.endswith(".00") else price


def amount(price: str) -> float:
    m = re.search(r"\d[\d,]*(?:\.\d+)?", price or "")
    return float(m.group(0).replace(",", "")) if m else 0.0


@dataclass
class BrandFacts:
    lines: list[str]  # product lines / ranges, e.g. ["Power", "Bubble Gummers"]
    price_range: str  # "Rs.1,469 to Rs.4,199"
    best_discount: int  # largest % off among products on sale
    who: str  # "men, women and kids"
    country: str  # "Pakistan"


def product_line(name: str) -> str:
    return re.split(r"\s+[-|–—:]\s+|\s*\(", name, maxsplit=1)[0].strip()


def brand_facts(kit: BrandKit) -> BrandFacts:
    lines = list(dict.fromkeys(product_line(p.category or p.name) for p in kit.products if p.name))[:5]
    priced = [(p, amount(p.price)) for p in kit.products if amount(p.price) > 0]
    price_range = ""
    if len(priced) >= 2:
        lo, hi = min(priced, key=lambda x: x[1])[0], max(priced, key=lambda x: x[1])[0]
        if lo.price != hi.price:
            price_range = f"{tidy_price(lo.price)} to {tidy_price(hi.price)}"
    discounts = [round(100 * (1 - amount(p.price) / amount(p.was_price))) for p in kit.products
                 if p.was_price and amount(p.was_price) > amount(p.price) > 0]
    return BrandFacts(lines=lines, price_range=price_range, best_discount=max(discounts, default=0),
                      who=join_words(kit.segments), country=COUNTRY_NAMES.get(kit.country.upper(), ""))
