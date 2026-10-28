"""Keeps a campaign from feeling monotonous.

Three levers, all deterministic so a campaign is reproducible:
  * post types: a campaign mixes product spotlights, "this or that" duos, sale posts, styling
    tips, brand-quote graphics, seasonal-moment posts and carousels, never the same type twice
    in a row;
  * wording: every angle has several headline and caption variants, and the n-th post of an
    angle uses the n-th variant, so phrasing doesn't come back until every variant is used;
  * look: layouts rotate (photo with the headline at the bottom or the top, framed photo, duo,
    graphic), so two neighbouring posts never look alike.
A final check catches repeated headlines, including ones a model wrote, and reports the mix.
"""
from __future__ import annotations

import re
from collections import Counter

PRODUCT_CYCLE = ["spotlight", "carousel", "duo", "tip", "quote", "sale", "spotlight", "moment", "carousel", "duo", "tip", "spotlight"]
GENERIC_CYCLE = ["spotlight", "carousel", "question", "tip", "quote", "moment", "spotlight", "carousel", "question", "quote", "tip", "spotlight"]

KIND_LABELS = {
    "spotlight": "Product spotlight", "carousel": "Carousel", "duo": "This or that", "tip": "Styling tip", "quote": "Brand quote",
    "sale": "Sale", "moment": "Seasonal moment", "question": "Question", "greeting": "Greeting",
}


def plan_kinds(n: int, *, products: int, on_sale: int, claims: int, moments: list[str]) -> list[str]:
    """One post type per idea. moments[i] is the seasonal moment idea i falls before ("" if none)."""
    cycle = PRODUCT_CYCLE if products else GENERIC_CYCLE
    fillers = ["spotlight", "duo", "carousel", "tip"] if products >= 2 else ["spotlight", "carousel", "tip"] if products else \
        ["spotlight", "question", "carousel", "tip"]
    kinds: list[str] = []
    for i in range(n):
        kind = cycle[i % len(cycle)]
        moment_here = i < len(moments) and bool(moments[i])
        unavailable = ((kind == "duo" and products < 2) or (kind == "sale" and not on_sale)
                       or (kind == "quote" and kinds.count("quote") >= claims)  # each quote post needs its own claim
                       or (kind == "moment" and not moment_here))
        if unavailable or (kinds and kind == kinds[-1]):
            # Fill the gap with whichever usable type has been used least, never repeating the last one.
            options = [k for k in fillers if not kinds or k != kinds[-1]]
            if moment_here and kind != "moment" and kinds[-2:].count("moment") == 0:
                options.insert(0, "moment")
            kind = min(options, key=lambda k: (kinds.count(k), options.index(k)))
        kinds.append(kind)
    return kinds


def pick(options: list[str], nth: int) -> str:
    return options[nth % len(options)]


# --------------------------------------------------------------------------- wording

PRODUCT_HEADLINES = {
    "new": ["New in: {name}", "Just landed: {name}", "Meet the {name}", "Say hello to the {name}", "Your next favourite: {name}",
            "{name}, up close"],
    "craft": ["The making of the {name}", "In the details: {name}", "Made with care: {name}", "Look closer: {name}"],
    "comfort": ["Made to be worn all day: {name}", "Comfort, first: {name}", "All-day easy: {name}", "Feels as good as it looks"],
    "customer": ["Everyone's asking about this one", "A customer favourite: {name}", "The one you keep asking about",
                 "Most-loved this week: {name}"],
    "tip": ["How to wear the {name}", "3 ways to style the {name}", "Style note: the {name}", "Wear it your way: {name}"],
    "tip_other": ["Getting the most from the {name}", "A quick tip for the {name}", "Good to know: {name}"],
    "duo": ["This or that?", "Pick one: {a} or {b}?", "Which would you choose?", "Two favourites, one choice",
            "{a} or {b}?", "Your vote: A or B?"],
    "sale": ["{pct}% off: {name}", "Price drop: {name}", "Sale pick: {name}", "Now {price}: {name}"],
    "moment": ["{moment} pick: {name}", "Ready for {moment}?", "Your {moment} edit: {name}", "{moment} is coming: {name}"],
    "carousel": ["{n} picks worth a closer look", "{n} favourites from {brand}", "Swipe through: {n} new picks", "{n} to know this week",
                 "The edit: {n} pieces we love", "{n} ways to shop {brand} now"],
}
PRODUCT_IDEAS = {
    "new": ["The {name}{coll} is new at {brand}", "Fresh in at {brand}: the {name}{coll}", "Here's the {name}{coll}, just added at {brand}",
            "Just in: the {name}{coll}", "Meet the newest arrival at {brand}, the {name}{coll}"],
    "craft": ["Every detail of the {name}{coll} was chosen on purpose", "Look closely at the {name}{coll}: the finish is the point",
              "It's all in the details with the {name}{coll}", "Zoom in on the {name}{coll} and you'll see why it took time",
              "Made slowly and carefully: the {name}{coll}"],
    "comfort": ["The {name}{coll} is built for comfort from the first wear", "Comfortable from morning to night: the {name}{coll}",
                "Made to be worn, not just looked at: the {name}{coll}", "Easy all day, every day: the {name}{coll}"],
    "customer": ["The {name}{coll} is the one people keep asking us about", "Customers keep coming back for the {name}{coll}",
                 "A favourite in store and online: the {name}{coll}", "If you've asked us about the {name}{coll}, here it is"],
    "tip": ["Keep everything else simple and let the {name}{coll} lead", "Pair the {name}{coll} with one statement piece and stop there",
            "Dress the {name}{coll} up for an event or down for the weekend", "Start with the {name}{coll} and build the look around it"],
    "sale": ["The {name}{coll} is {pct}% off right now", "Good news if you've had your eye on the {name}{coll}: it's on sale",
             "Price drop on the {name}{coll}", "Now's the time for the {name}{coll}: {pct}% off"],
    "moment": ["{moment} is coming up, and the {name}{coll} is ready for it", "Planning for {moment}? Start with the {name}{coll}",
               "One for {moment}: the {name}{coll}", "Counting down to {moment} with the {name}{coll}"],
    "carousel": ["A few favourites from {brand}, starting with the {name}{coll}", "Swipe through a few picks from {brand}, beginning with the {name}{coll}",
                 "From the {name}{coll} onwards, here's what we're loving at {brand}", "Our shortlist this week opens with the {name}{coll}"],
    "duo": ["The {a} or the {b}? Both are at {brand}", "Two picks from {brand}: the {a} and the {b}",
            "Can't decide between the {a} and the {b}? Neither can we"],
}

# --------------------------------------------------------------------------- caption shapes
# Captions take different shapes from post to post (and from platform to platform within a
# post), so a feed reads like a person wrote it, not like one template filled in thirty times.

CAPTION_SHAPES = ["statement", "hook", "details", "story", "question", "short"]
SHAPE_HINTS = {
    "statement": "one or two plain sentences",
    "hook": "a short hook line on its own, then the details",
    "details": "the product name, then 2 or 3 facts, one per line, each starting with an en dash",
    "story": "a tiny moment or story in 2 or 3 sentences",
    "question": "a short description that ends by asking the reader a question",
    "short": "one punchy line of under 15 words",
}
PLATFORM_ORDER = ["instagram", "facebook", "linkedin", "x"]


def caption_shape(group: int, platform: str) -> str:
    """Neighbouring posts get different shapes, and so do the platform versions of one post."""
    offset = PLATFORM_ORDER.index(platform) * 2 if platform in PLATFORM_ORDER else 0
    return CAPTION_SHAPES[(group + offset) % len(CAPTION_SHAPES)]


HOOKS = {
    "wear": ["Okay, this one's special.", "Your next outfit, sorted.", "We've been waiting to show you this.", "Saving the best for this week.",
             "This is the one.", "Hear us out."],
    "food": ["Hungry? Keep scrolling.", "Okay, this one's special.", "Your next craving, sorted.", "We've been waiting to show you this.",
             "This is the one.", "Hear us out."],
    "other": ["Okay, this one's special.", "We've been waiting to show you this.", "Quick one for your list.", "This is the one.",
              "Something new for you.", "Hear us out."],
}
# Scene-setting only: openers imagine a moment, they never claim facts about the brand.
STORY_OPENERS = {
    "wear": ["Picture it: an evening out, and everyone asks where it's from.", "Some pieces feel right the moment you put them on.",
             "Imagine the invite arrives tomorrow. You'd be ready.", "Picture a slow Sunday, coffee in hand, dressed in this."],
    "food": ["Picture it: a long day, then the first bite.", "Some things are worth the wait.",
             "Imagine Friday night, friends over, and this on the table.", "Picture the first bite. Now stop picturing and order."],
    "other": ["Picture it: the moment you finally find exactly what you needed.", "Some things just feel right the moment you see them.",
              "Imagine ticking this off your list today.", "Picture next week, sorted."],
}
QUESTIONS = {
    "wear": ["Would you wear it?", "Day look or evening look?", "Yes or no?", "Who would you wear it with?", "How would you style it?"],
    "food": ["Would you try it?", "Sharing or all for you?", "Yes or no?", "Who are you bringing?", "Lunch or dinner?"],
    "other": ["Would you try it?", "Yes or no?", "Who would you share this with?", "What do you think?"],
}

CLOSERS = {
    "instagram": ["Save this post for later.", "Tag someone who needs to see this.", "Which one is your style? Tell us below.",
                  "Share this with your shopping buddy.", "Double tap if it's a yes.", "Send this to the friend who'd say yes.",
                  "Thoughts? The comments are open.", "Keep this one for the weekend.", "Tell us in one emoji.",
                  "Bookmark it before you forget.", "Would you? Yes or no below.", "Your turn: what would you add?",
                  "Show this to someone who'd love it.", "Drop a 🔥 if you're in."],
    "instagram_carousel": ["Swipe to see them all, then tell us your favourite.", "Swipe through and save the one you want.",
                           "Which slide is your pick? Tell us below."],
    "instagram_duo": ["Vote in the comments: A or B?", "A or B? Tell us below.", "Comment your pick: A or B."],
    "facebook": ["Have you seen it in person yet? Tell us in the comments.", "Tag a friend who'd love this.",
                 "Yes or no? Let us know in the comments.", "Share it with someone who'd like it.",
                 "What would you add? Tell us below.", "We read every comment, so go ahead.", "Who's coming with you?"],
    "facebook_duo": ["Which would you pick? Tell us in the comments.", "A or B? We want to know."],
    "linkedin": ["We'd love to hear what you think of it.", "Thoughts? We read every comment.",
                 "What do you look for when you choose {category}?", "Proud of how this one turned out.",
                 "Curious how others see it. Share your view below.", "If this is useful to someone in your network, pass it on.",
                 "More soon. Follow along if this is your kind of thing.", "Questions welcome in the comments.",
                 "Small things, done well, add up.", "What would you like to see from us next?"],
}
CTAS = {
    "instagram": ["Shop via the link in bio", "Tap the link in bio to shop", "Link in bio", "Find it through our bio", "Yours via the link in bio",
                  "It's one tap away in our bio", "Bio link, if you're curious", "Details in our bio", "Head to the link in bio",
                  "All the details: link in bio", "The link in our bio has it", "Go on, check the bio"],
    "instagram_info": ["More in our bio", "Link in bio", "Details in our bio", "Everything else: link in bio", "Find us through the bio",
                       "Bio link for more", "The rest is in our bio"],
    "linked": ["Shop it here: {link}", "See it here: {link}", "Find it at {link}", "Get yours: {link}", "Take a closer look: {link}"],
    "linkedin": ["See the collection: {link}", "More at {link}", "See it here: {link}", "Explore it: {link}"],
}

NOT_FOR_EVERYONE = {
    "wear": re.compile(r"\b(style|wear|outfit)\b", re.I),  # fashion talk, wrong for a bakery or a software firm
    "shop": re.compile(r"\bshopping\b", re.I),  # shopping talk, wrong for a brand that doesn't sell products online
}


def closers_for(wearable: bool, sells: bool) -> dict[str, list[str]]:
    """Endings that make sense for this kind of brand."""
    def fits(line: str) -> bool:
        return not ((not wearable and NOT_FOR_EVERYONE["wear"].search(line)) or (not sells and NOT_FOR_EVERYONE["shop"].search(line)))

    return {k: [c for c in v if fits(c)] or v for k, v in CLOSERS.items()}


GENERIC_HEADLINES = {
    "spotlight": ["On the menu: {item}", "Spotlight: {item}", "Meet our {item}", "Fresh this week: {item}", "Craving {item}?",
                  "{item}, done right", "Today's pick: {item}", "You, us and {item}", "This week at {brand}", "A {brand} favourite",
                  "Have you tried it?", "Say hello to {item}"],
    "spotlight_other": ["Spotlight: {item}", "All about our {item}", "Meet our {item}", "This week: {item}", "Why people love our {item}",
                        "{item}, explained", "Inside {brand}", "This week at {brand}", "What we do best", "Hello from {brand}"],
    "craft": ["How we make {item}", "Behind our {item}", "Inside {brand}: {item}", "Behind the scenes", "The part you don't see",
              "Made with care", "How it comes together"],
    "question": ["What's your go-to?", "Quick question for you", "Settle this for us", "Tell us your favourite", "Your turn",
                 "We need your vote", "Be honest", "Help us decide", "Over to you"],
    "tip": ["Good to know: {item}", "A tip from the {brand} team", "Before you visit: {item}", "Save this tip", "Know before you go",
            "Little tip, big difference", "First time here?"],
    "moment": ["{moment}: {item}", "Ready for {moment}?", "{moment} is coming", "Counting down to {moment}", "{moment} plans, sorted"],
    "carousel": ["{n} things to know about {brand}", "{brand} in {n} slides", "Swipe: {n} things we love", "Meet {brand}",
                 "The {brand} basics", "Swipe through"],
    "any": ["Hello from {brand}", "This week at {brand}", "Meet {brand}", "Inside {brand}", "From all of us at {brand}"],
}


def headline_family(kind: str, angle: str, wearable: bool) -> str:
    if kind in ("duo", "sale", "moment", "carousel"):
        return kind
    if kind == "tip":
        return "tip" if wearable else "tip_other"
    # Spotlights follow their pillar's angle, except styling wording, which belongs to tip posts.
    return "new" if angle == "tip" else angle


# --------------------------------------------------------------------------- the check


def normalize(text: str) -> str:
    return " ".join(text.lower().replace("’", "'").split()).strip(" .!?")


def variety_report(posts) -> dict:
    """Counts for the campaign's content mix and how many headlines repeat across posts."""
    ideas: dict[str, object] = {}
    for p in posts:
        ideas.setdefault(p.group_id or p.id, p)
    heads = Counter(normalize(p.headline) for p in ideas.values() if p.headline)
    kinds = Counter(getattr(p, "kind", "") or "spotlight" for p in ideas.values())
    looks = Counter(f"{p.layout}:{p.text_position}" for p in ideas.values())
    return {
        "posts": len(ideas),
        "types": dict(kinds),
        "layouts": len(looks),
        "repeated_headlines": sum(c - 1 for c in heads.values() if c > 1),
    }


# --------------------------------------------------------------------------- one campaign, no repeats

SENTENCE = re.compile(r"[^.!?\n]+[.!?]*")
PRICE = re.compile(r"(rs\.?|pkr|usd|\$|£|€|aed|sar)\s?\d|\d[\d,]*(\.\d+)?\s?(rs|pkr)\b", re.I)


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in SENTENCE.findall(text) if s.strip()]


def make_unique(platforms: list[str], copies: list[dict], closers: dict[str, list[str]] | None = None) -> int:
    """No sentence said twice on one platform in a campaign, whoever wrote it (templates or the
    model). A repeated sentence is dropped from the later post; a repeated ending is swapped for
    an ending this platform hasn't used yet, or dropped; a repeated Instagram call to action is
    swapped the same way. A product's name-and-price line, list lines and hashtags are left
    alone: they're facts, not phrasing. Returns how many lines changed."""
    closers = closers or CLOSERS
    used: dict[str, set[str]] = {}
    ended: dict[str, set[str]] = {}
    cta_order: dict[str, list[str]] = {}  # calls to action, least recently used first
    changed = 0
    for platform, copy in zip(platforms, copies):
        seen, ends = used.setdefault(platform, set()), ended.setdefault(platform, set())
        paragraphs = str(copy.get("caption") or "").split("\n\n")
        out = []
        for i, para in enumerate(paragraphs):
            ending = i == len(paragraphs) - 1 and len(paragraphs) > 1
            lines = []
            for line in para.split("\n"):
                if ending or line.lstrip().startswith(("–", "-", "#", "•")) or PRICE.search(line):
                    lines.append(line)  # endings are judged whole, below; facts stay
                    continue
                keys = [normalize(s) for s in _sentences(line)]
                # A line is one thought ("Not sure where to start? Start with the bowls."): cutting a
                # sentence out of it leaves a fragment, so a line with a repeat goes as a whole.
                if any(len(k) >= 12 and k in seen for k in keys):
                    changed += 1
                    continue
                seen.update(keys)
                lines.append(line)
            text = "\n".join(lines).strip()
            if ending and text and normalize(text) in ends:
                fresh = [c for c in closers.get(platform, []) if "{" not in c and normalize(c) not in ends and normalize(c) not in seen]
                text = fresh[0] if fresh else ""
                changed += 1
            if ending and text:
                ends.add(normalize(text))
                seen.update(normalize(s) for s in _sentences(text))
            if text:
                out.append(text)
            elif not ending and i == len(paragraphs) - 2 and not out and para.strip():
                out.append(para.strip())  # never cut a caption down to only its ending: a repeat beats an empty post
        if out:
            copy["caption"] = "\n\n".join(out)
        cta = str(copy.get("cta") or "")
        if cta and platform == "instagram":
            order = cta_order.setdefault(platform, [])
            if cta in order:
                pool = CTAS["instagram"] if re.search(r"shop|yours", cta, re.I) else CTAS["instagram_info"]
                fresh = [c for c in pool if c not in order]
                # Every wording used once already: reuse the one used longest ago, never the last one.
                copy["cta"] = cta = fresh[0] if fresh else next((c for c in order if c in pool and c != order[-1]), cta)
                changed += 1
            if cta in order:
                order.remove(cta)
            order.append(cta)
    return changed
