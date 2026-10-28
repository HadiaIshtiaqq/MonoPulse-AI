"""Captions for brands whose site lists no products with prices: restaurants, studios, services,
bakeries that only show what they make.

The old writer had one sentence per post type and pasted the brand's one or two claims into
nearly every post, so thirty posts read like six. Here each post type has many frames, the
frames draw on everything the site says (what it offers, its claims, its description, its
city, how long it's been around), and the writer remembers what the campaign has already said
on each platform, so a line or a fact comes back only once every fresh one is used. Nothing is
invented: a frame that needs a fact the site doesn't give is skipped.
"""
from __future__ import annotations

import re

from ..schemas import BrandKit
from ..scraper.products import looks_like_menu
from . import variety

# Headings scraped as offerings that are really cut-off sentences or list titles:
# "Top Restaurants of Islamabad include", "Best deals of the week", "Order now and".
NOT_AN_OFFERING = re.compile(r"\b(include|includes|including|and|or|of|for|with|the|a|an|our|your|to|in|on|at|by|from|are|is|near)$"
                             r"|^(top|best|latest|popular)\b.*\b(of|in|near)\b|\b(click|order now|sign up|log ?in|download)\b", re.I)
ITEM_USES = 3  # one offering leads at most this many posts per platform, so a brand with one isn't about one thing

GENERIC_OFFERINGS = {"products and services", "products", "services", "shop", "store", "home", "menu", "about us", "contact"}


def offerings(kit: BrandKit) -> list[str]:
    """What the brand offers, as it reads mid-sentence, without nav words ("Products and services")."""
    from .strategist import in_sentence

    out = []
    for o in kit.offerings:
        o = o.strip().rstrip(".…")
        if o and o.lower() not in GENERIC_OFFERINGS and not looks_like_menu(o) and "…" not in o and not NOT_AN_OFFERING.search(o):
            out.append(in_sentence(o))
    return list(dict.fromkeys(out))


def facts(kit: BrandKit) -> list[str]:
    """Whole sentences the brand says about itself, each once: claims, tagline, then description.
    Cut-off text ("include…") and menus scraped as sentences are left out."""
    raw = [*kit.value_props, kit.tagline or "", *re.split(r"(?<=[.!?])\s+", kit.description or "")]
    out: list[str] = []
    seen: set[str] = set()
    for s in raw:
        s = " ".join(s.split()).strip()
        if not s or "…" in s or s.endswith("...") or looks_like_menu(s) or not 3 <= len(s.split()) <= 32:
            continue
        s = s.rstrip(".!") + "."
        key = variety.normalize(s)
        if key in seen or any(key in k or k in key for k in seen):  # "Since 1988" inside a longer claim
            continue
        seen.add(key)
        out.append(s[0].upper() + s[1:])
    return out


def since(kit: BrandKit) -> str:
    m = re.search(r"\b(?:since|est\.?|established in|founded in)\s+((?:19|20)\d\d)\b",
                  f"{kit.tagline} {' '.join(kit.value_props)} {kit.description}", re.I)
    return m.group(1) if m else ""


# Frames per post type. {item} needs something the brand offers, {fact} one of its own sentences,
# {city} its city, {year} its founding year: a frame whose fields the brand doesn't have is skipped.
FRAMES = {
    "spotlight": [
        "This week we're putting {item} front and centre.",
        "If you only try one thing from {brand} this month, make it {item}.",
        "{Item}, the way {brand} does it.",
        "A small love letter to {item}.",
        "{Item} is having a moment at {brand}.",
        "Ask anyone who's been to {brand} about {item}.",
        "{Item}: worth the trip across {city}.",
        "Some days call for {item}. Today's one of them.",
        "{Item}, done properly.",
        "Of everything we do at {brand}, {item} might be the one we're proudest of.",
        "A little hello from everyone at {brand}.",
        "If {brand} isn't on your list yet, consider this your nudge.",
        "Glad you found us. Welcome to {brand}.",
        "Thanks for being part of the {brand} story.",
        "Here's to another good week at {brand}.",
        "New faces and old friends, all welcome at {brand}.",
    ],
    "craft": [
        "A peek behind the counter at how {item} comes together.",
        "There's no shortcut to good {item}. Here's ours.",
        "What goes into {item} at {brand}? Time, mostly.",
        "From first step to finished: {item} at {brand}.",
        "The part of {item} you don't usually see.",
        "Doing this since {year}, and still learning.",
        "A peek behind the scenes at {brand}.",
    ],
    "question": [
        "Settle a debate for us: what's the one thing you'd never leave {brand} without?",
        "Have you tried {item} yet? Tell us below.",
        "First time at {brand}, or a regular? Tell us below.",
        "What should {brand} post more of? Your answers decide.",
        "If you could only pick one thing from {brand} forever, what would it be?",
        "Who introduced you to {brand}? Tag them.",
        "What's your {brand} order when the week's been long?",
        "{Item} fans, where are you? Say hi below.",
        "What made you follow {brand}?",
        "Describe {brand} in three words. Go.",
        "What would you love to see from {brand} next?",
    ],
    "tip": [
        "Good to know: {fact}",
        "In case you didn't know: {fact_lc}",
        "Not sure where to start with {brand}? Start with {item}.",
        "One thing first-timers don't know: {fact}",
        "Questions about {item}? Ask us in the comments; we answer every one.",
        "Follow {brand} so you don't miss what's next.",
        "Questions for {brand}? Drop them in the comments.",
        "Save this so you can find {brand} again.",
    ],
    "moment": [
        "{Moment} is around the corner, and {item} is on the list.",
        "Getting ready for {moment}? So are we.",
        "{Moment} plans, sorted: {item} from {brand}.",
        "Counting down to {moment} at {brand}.",
        "Make {moment} easy on yourself. Let {brand} handle {item}.",
        "{Moment} is coming up. What are your plans?",
    ],
    "carousel": [
        "A quick tour of {brand}. Swipe through.",
        "Everything you'd want to know about {brand}, in a few slides.",
        "New here? Swipe for the {brand} basics.",
        "The {brand} story, slide by slide.",
        "Swipe for what {brand} offers, from {item} on.",
    ],
    "quote": [
        "In our own words: {claim}",
        "Something we say a lot at {brand}: {claim_lc}",
        "Words we work by: {claim_lc}",
        "What {brand} is about, in one line: {claim_lc}",
        "If you remember one thing about {brand}: {claim_lc}",
        "The short version of {brand}? {claim}",
    ],
}
# A second line that adds something real, used on about one post in two.
FACT_LINES = ["{fact}", "In case you're new here: {fact_lc}", "Fun fact: {fact_lc}", "{fact}", "{brand} in a sentence: {fact_lc}"]


def _fields(kit: BrandKit, item: str, fact: str, moment: str) -> dict:
    city = (kit.location or "").split(",")[0].strip()
    return {"brand": kit.name, "item": item, "Item": item[:1].upper() + item[1:] if item else "", "fact": fact,
            "fact_lc": fact[:1].lower() + fact[1:] if fact and not fact[:2].isupper() else fact, "city": city,
            "year": since(kit), "moment": moment, "Moment": moment[:1].upper() + moment[1:] if moment else ""}


def quote_caption(kit: BrandKit, claim: str, nth: int, seed: int) -> str:
    """A brand claim introduced, not just repeated from the graphic: "Something we say a lot at X: free delivery."."""
    claim = claim.rstrip(".") + "."
    lc = claim[:1].lower() + claim[1:] if not claim[:2].isupper() else claim
    fields = {"brand": kit.name, "claim": claim[:1].upper() + claim[1:], "claim_lc": lc}
    return variety.pick(FRAMES["quote"], nth + seed).format(**fields)


def _usable(frame: str, fields: dict) -> bool:
    return all(fields.get(k) for k in re.findall(r"{(\w+)}", frame))


SPECIFIC = re.compile(r"{(item|Item|fact|fact_lc|city|year|moment|Moment)}")


def _first_unused(options: list[str], start: int, used: set[str]) -> str | None:
    for i in range(len(options)):
        text = options[(start + i) % len(options)]
        if variety.normalize(text) not in used:
            return text
    return None


def write(kit: BrandKit, kind: str, nth: int, group: int, seed: int, moment: str = "", used: set[str] | None = None,
          item: str | None = None) -> str:
    """One caption body for a post with no product: an opening line in this post type's voice,
    sometimes followed by one of the brand's own sentences. `used` holds what this campaign has
    already said on this platform, so lines and facts aren't said twice while fresh ones remain."""
    used = used if used is not None else set()
    items, said = offerings(kit), facts(kit)
    item = item if item is not None else items[(group + seed) % len(items)] if items else ""  # the headline's item, when given
    uses = [f"item:{variety.normalize(item)}:{k}" for k in range(ITEM_USES)]
    if item and all(u in used for u in uses):
        item = ""  # this offering has had its turn: talk about something else
    fresh = [f for f in said if variety.normalize(f) not in used]
    fact = fresh[(group + seed) % len(fresh)] if fresh else ""
    fields = _fields(kit, item, fact, moment)
    start = nth + seed

    def options(kinds: list[str], specific: bool) -> list[str]:
        # Specific lines say something about this brand (what it offers, its own words, its city,
        # its age); the rest only name it. Specific ones always go first: relevance beats variety.
        return [f.format(**fields) for k in kinds for f in FRAMES[k]
                if _usable(f, fields) and bool(SPECIFIC.search(f)) == specific]

    own = kind if kind in FRAMES else "spotlight"
    others = ["spotlight", "craft", "tip", "question"]  # never "swipe" lines on a post without slides
    # A post stays what it is (a question asks, a carousel says swipe): its own lines first,
    # specific before plain, and only then lines borrowed from other post types.
    opener = (_first_unused(options([own], True), start, used)
              or _first_unused(options([own], False), start, used)
              or _first_unused(options(others, True), start, used)
              or _first_unused(options(others, False), start, used)
              or next(iter(options([own], True) + options([own], False)), f"Hello from {kit.name}."))
    used.add(variety.normalize(opener))
    if item and item.lower() in opener.lower():
        used.add(next(u for u in uses if u not in used))
    if fact and fact in opener:
        used.add(variety.normalize(fact))
    elif fact and kind != "question" and (group + seed) % 2 == 0:
        used.add(variety.normalize(fact))
        return f"{opener} {variety.pick(FACT_LINES, group + seed).format(**fields)}"
    return opener
