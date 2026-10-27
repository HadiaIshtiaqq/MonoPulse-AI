"""What a reel says: its photos, its topic's story, the script (rules or Nemotron), humanizing, and editing."""
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING
import random
import re
from dataclasses import dataclass
from pathlib import Path


from ... import config
from ...llm import LLMError, router
from ...schemas import BrandKit, Campaign, Product, ReelScene, SocialPost
from .. import humanizer, occasions
from .. import lang as lang_mod
from .. import photos as photo_store
from .. import strategist

from .core import KINDS, MAX_PHOTOS, MAX_SCENES, ReelEditError, Scene

if TYPE_CHECKING:  # styles import this module, so the type is only named for checkers
    from .styles import Style

log = logging.getLogger(__name__)

# --------------------------------------------------------------------------- what goes in it


# (product shown, local photo, what the photo's own post or slide said about it)
Shot = tuple[Product | None, str, str]


def reel_photos(campaign: Campaign, post: SocialPost, limit: int = MAX_PHOTOS, rnd: random.Random | None = None,
                products_only: bool = False, brand_first: bool = False) -> list[Shot]:
    """The post's own photos first, then other products the campaign already has photos of,
    one per product, so a reel shows a little of the range rather than one shot four times.
    With `rnd`, the others start from a different point each time, so two reels differ.
    `brand_first` prefers photos that aren't of one product (for a brand story)."""
    out: list[Shot] = []
    paths: set[str] = set()
    names: set[str] = set()

    def add(product: Product | None, bg, said: str = "") -> None:
        if not bg or not Path(bg.path).exists() or bg.path in paths or (products_only and not product):
            return
        if product and product.name.lower() in names:
            return
        paths.add(bg.path)
        if product:
            names.add(product.name.lower())
        out.append((product, bg.path, said))

    others = [p for p in sorted(campaign.posts, key=lambda p: p.publish_at) if p.group_id != post.group_id]
    if rnd and others:
        start = rnd.randrange(len(others))
        others = others[start:] + others[:start]
    if brand_first:
        for other in others:
            if not other.product and len(out) < limit:
                add(None, other.background, other.headline)
    add(post.product, post.background, post.headline)
    if post.gallery:
        add(post.compare, post.gallery[0])
    for slide in post.slides:
        add(None, slide.background, slide.headline)
    for other in others:
        if len(out) >= limit:
            break
        if other.product:
            add(other.product, other.background)
    # Few or no products (a brand whose site has photos but no shop): use the campaign's other photos.
    for other in others:
        if len(out) >= min(limit, 4):
            break
        if not other.product:
            add(None, other.background, other.headline)
    return out[:limit]


def _price(p: Product | None) -> str:
    if not p or not p.price:
        return ""
    price = p.price[:-3] if p.price.endswith(".00") else p.price
    pct = strategist.sale_percent(p)
    return f"{price} · {pct}% off" if pct else price


def _words(text: str, limit: int) -> str:
    return strategist.fit_headline(" ".join(str(text or "").split()).strip(" \"'"), limit)


def _site(kit: BrandKit) -> str:
    return (kit.website_url or "").split("//")[-1].split("/")[0].removeprefix("www.")


def default_cta(kit: BrandKit, post: SocialPost) -> str:
    industry = (kit.industry or "").lower()
    return "Order yours today" if "food" in industry or "restaurant" in industry else "Shop the collection" if kit.products else f"Follow {kit.name}"


# --------------------------------------------------------------------------- topics: one connected story each
#
# Every reel tells one story. The opening makes a promise ("3 ways to wear the X", "Our top 3
# right now", "Why people choose Y"), each scene delivers the next part of it, labelled in
# order (Tip 1, #3, A), and the end card closes the loop ("Which tip will you try?").

TOPICS = {
    "products": ("Product showcase", "A few products, one after another, each with its price"),
    "countdown": ("Top picks", "A countdown from #3 to #1"),
    "tips": ("Tips", "Numbered tips around one product"),
    "poll": ("This or that", "Two products, A or B, and a vote"),
    "story": ("Brand story", "What the brand stands for, from its own facts"),
    "occasion": ("Occasion", "A greeting for Eid, Mother's Day, a sale and more, with festive colours"),
    "trend": ("Trending format", "Formats people know from their feed: POV, \"this is your sign\", rate it, wait for the last one"),
}
KIND_TOPIC = {"spotlight": "products", "carousel": "countdown", "duo": "poll", "tip": "tips", "quote": "story",
              "sale": "occasion", "moment": "occasion", "question": "poll", "greeting": "occasion"}

TIPS = {
    "wear": ["Keep the rest of the look simple", "Add one statement accessory", "Dress it up with heels for evenings",
             "Dress it down with flats for the day", "Let one colour lead", "Layer it when the weather turns"],
    "food": ["Eat it hot, straight away", "Share a box with friends", "Pair it with a cold drink", "Save room for dessert",
             "Order ahead on busy nights", "Add a side for the table"],
    "other": ["Save this for later", "Start with what you need most", "Ask the team for advice", "Pair it with a favourite",
              "Try it this week", "Share it with a friend"],
}
ENDINGS = {
    "products": ["Which one's yours?", "Pick your favourite", "Which would you choose?"],
    "countdown": ["Which is your #1?", "Agree with our #1?", "What would your #1 be?"],
    "tips": ["Which tip will you try?", "Save these for later", "Try one this week"],
    "poll": ["Comment A or B", "A or B? Tell us", "Vote in the comments"],
    "story": ["Come and see for yourself", "That's us. Say hi", "Now you know us"],
}


def flavour(kit: BrandKit) -> str:
    return strategist.flavour(kit)


def product_shots(shots: list[Shot]) -> list[Shot]:
    return [s for s in shots if s[0]]


def available_topics(campaign: Campaign, post: SocialPost) -> list[str]:
    kit = campaign.brand
    shots = product_shots(reel_photos(campaign, post))
    out = ["products"] if shots else []
    if len(shots) >= 3:
        out.append("countdown")
    if shots:
        out.append("tips")
    if len(shots) >= 2:
        out.append("poll")
    if kit and len(story_facts(kit)) >= 2:
        out.append("story")
    out += ["trend", "occasion"]  # both work on the brand colours when there are no photos
    return out


def trend_formats(kit: BrandKit) -> list[str]:
    city = (kit.location or "").split(",")[0].strip() if kit else ""
    return [k for k in lang_mod.TRENDS if k != "local" or city]


def default_topic(campaign: Campaign, post: SocialPost, avoid: str = "") -> str:
    """The topic that fits the post's type ("this or that" post -> a poll reel); a fresh script
    for a reel that already had it moves on to another topic."""
    topics = available_topics(campaign, post)
    preferred = KIND_TOPIC.get(post.kind, "products")
    if preferred == "occasion" and not post_occasion(campaign, post):
        preferred = "products"
    order = [preferred] + [t for t in ("products", "trend", "countdown", "tips", "story", "poll") if t != preferred]
    return next((t for t in order if t in topics and t != avoid), topics[0] if topics else "products")


def post_occasion(campaign: Campaign, post: SocialPost) -> str:
    """The occasion a post is about: a greeting post's own occasion, else one its headline or
    caption names ("11.11 sale pick: ...", "Ready for Eid?")."""
    for text in (post.occasion, post.headline, post.caption[:160]):
        o = occasions.find(text) if text else None
        if o:
            return o.key
    return ""


def story_facts(kit: BrandKit) -> list[str]:
    facts = [strategist.short_claim(c) for c in strategist.brand_claims(kit)]
    city = (kit.location or "").split(",")[0].strip()
    if city:
        facts.append(f"Proudly from {city}")
    return [f for f in dict.fromkeys(facts) if f][:4]


def _pick(options: list[str], rnd: random.Random | None) -> str:
    return rnd.choice(options) if rnd else options[0]


@dataclass
class Plan:
    """A reel's story before it's worded: the opening, each scene's subject, the ending."""
    topic: str
    hook: str
    lines: list[str]  # one per scene, the rule-based wording
    shots: list[Shot]  # one per scene ("" photo = brand colour)
    tags: list[str]
    subs: list[str]
    cta: str
    cta_sub: str
    occasion: str = ""
    brief: str = ""  # what the story is, for the script writer


def plan_story(campaign: Campaign, post: SocialPost, topic: str, style: "Style", rnd: random.Random | None = None,
               occasion_key: str = "", language: str = "en", trend: str = "") -> Plan:
    plan = _plan_story(campaign, post, topic, style, rnd, occasion_key, language, trend)
    return localize(plan, campaign.brand, language, rnd)


def localize(plan: Plan, kit: BrandKit, language: str, rnd: random.Random | None) -> Plan:
    """The story's own words (opening, ending, tips, labels, greetings) in Roman Urdu or Urdu.
    Product names and the brand's facts stay as written; "mix" keeps English tips."""
    p = lang_mod.pools(language)
    if p == "en" or plan.topic == "trend":  # trend formats are written in the language from the start
        return plan
    f = flavour(kit)
    subject = strategist.display_name(kit, plan.shots[0][0]) if plan.shots and plan.shots[0][0] else kit.name
    fields = {"n": len(plan.lines), "brand": kit.name, "name": subject, "verb": lang_mod.VERBS[p][f]}
    if plan.topic in lang_mod.HOOKS[p]:
        plan.hook = _pick(lang_mod.HOOKS[p][plan.topic], rnd).format(**fields)
        plan.cta = _pick(lang_mod.ENDINGS[p][plan.topic], rnd)
    if plan.topic == "tips" and language != "mix":
        tips = list(lang_mod.TIPS[p][f])
        if rnd:
            rnd.shuffle(tips)
        plan.lines = tips[: len(plan.lines)]
        plan.tags = [lang_mod.TIP_LABEL[p].format(i=i + 1) for i in range(len(plan.lines))]
    if plan.topic == "occasion":
        o = occasions.OCCASIONS.get(plan.occasion)
        greet = lang_mod.greeting(plan.occasion, language, occasions.greeting(o, kit.name) if o else "")
        plan.hook = greet
        if language != "mix":
            lines = lang_mod.OCCASION_LINES[p]
            plan.lines = [lines[i % len(lines)] for i in range(len(plan.lines))]
        plan.cta = lang_mod.FROM_BRAND[p].format(brand=kit.name, greeting=greet)
    return plan


def _plan_story(campaign: Campaign, post: SocialPost, topic: str, style: "Style", rnd: random.Random | None,
                occasion_key: str, language: str, trend: str) -> Plan:
    kit = campaign.brand
    f = flavour(kit)
    site = _site(kit) or kit.name
    name = lambda p: strategist.display_name(kit, p)  # noqa: E731
    if topic == "occasion":
        o = occasions.find(occasion_key or post_occasion(campaign, post)) or occasions.OCCASIONS["sale" if post.kind == "sale" else "eid_fitr"]
        moment = occasion_key if occasion_key and occasion_key not in occasions.OCCASIONS else o.label
        shots = reel_photos(campaign, post, min(style.photos, 3), rnd, products_only=o.selling) if o.selling else \
            reel_photos(campaign, post, 2, rnd, brand_first=True)
        if o.key == "sale":  # real sale prices first
            on_sale = [s for s in shots if s[0] and strategist.sale_percent(s[0])]
            shots = on_sale + [s for s in shots if s not in on_sale]
        lines_pool = list(o.lines.get(f, o.lines.get("other", [])))
        lines = [occasions.fill(lines_pool[i % len(lines_pool)], kit.name, moment) for i in range(len(shots))] or \
            [occasions.fill(x, kit.name, moment) for x in lines_pool[:2]]
        subs = [_price(p) if p else "" for p, _, _ in shots] or [""] * len(lines)
        hook = occasions.fill(_pick(list(o.hooks), rnd), kit.name, moment)
        return Plan("occasion", hook, lines, shots or [(None, "", "")] * len(lines), [""] * len(lines), subs,
                    occasions.fill(_pick(list(o.ctas) or [occasions.greeting(o, kit.name, moment)], rnd), kit.name, moment), site, o.key,
                    f"A {o.label} reel: the opening greets people for {moment}; each scene shows a pick for the occasion; the end wishes them well.")
    if topic == "story":
        facts = story_facts(kit)[:3]
        shots = reel_photos(campaign, post, len(facts), rnd, brand_first=True)
        hook = _pick([f"Why people choose {kit.name}", f"Meet {kit.name}", f"{len(facts)} things to know about {kit.name}"], rnd)
        return Plan("story", hook, facts, (shots + [(None, "", "")] * len(facts))[:len(facts)], [str(i + 1) for i in range(len(facts))],
                    [""] * len(facts), _pick(ENDINGS["story"], rnd), site,
                    brief=f"A brand story: the opening asks why people choose {kit.name}; each scene gives one real reason from the brief, "
                          "in order; the end invites them in. Never add facts that aren't in the brief.")
    shots = product_shots(reel_photos(campaign, post, MAX_PHOTOS, rnd, products_only=True))
    if topic == "trend":
        p = lang_mod.pools(language)
        keys = trend_formats(kit)
        key = trend if trend in keys else _pick(keys, rnd)
        t = lang_mod.TRENDS[key]
        picks = (shots or reel_photos(campaign, post, style.photos, rnd))[: max(3, min(style.photos, 4))]
        city = (kit.location or "").split(",")[0].strip()
        hook = t["hook"][p]
        hook = (hook.get(flavour(kit)) if isinstance(hook, dict) else hook).format(brand=kit.name, city=city)
        n = len(picks)
        tags = [t["tag"][p]] * n if "tag" in t else [""] * n
        if "last" in t and n:
            tags[-1] = t["last"][p]
        lines = [name(pr) if pr else (LEAD_IN.sub("", said).strip() or kit.name) for pr, _, said in picks]
        if not picks:  # no photos: the brand's own facts, on its colours
            lines = story_facts(kit)[:3] or [kit.tagline or kit.name]
            picks = [(None, "", "")] * len(lines)
            n = len(lines)
            tags = [t["tag"][p]] * n if "tag" in t else [""] * n
            if "last" in t:
                tags[-1] = t["last"][p]
        return Plan("trend", hook, lines, picks, tags, [_price(pr) for pr, _, _ in picks],
                    t["end"][p].format(city=city), site, occasion=key,
                    brief=f"A trending '{t['label'].format(city=city)}' reel: the opening uses that well-known format; each scene "
                          "shows one photo, in order; the end invites people to join in. Keep the format's opening recognisable.")
    if topic == "tips" and shots:
        subject = shots[0]
        tips = list(TIPS[f])
        if rnd:
            rnd.shuffle(tips)
        tips = tips[:3]
        p = subject[0]
        verb = "wear" if f == "wear" else "enjoy" if f == "food" else "use"
        hook = _pick([f"{len(tips)} ways to {verb} the {name(p)}", f"How to {verb} the {name(p)}", f"{len(tips)} tips for the {name(p)}"], rnd)
        return Plan("tips", hook, tips, [subject] * len(tips), [f"Tip {i + 1}" for i in range(len(tips))], [""] * len(tips),
                    _pick(ENDINGS["tips"], rnd), f"{name(p)} · {_price(p)}" if _price(p) else site,
                    brief=f"Tips: the opening promises {len(tips)} ways to {verb} the {name(p)}; each scene is one short practical tip "
                          "about that same product, in order; the end asks which tip they'll try.")
    if topic == "poll" and len(shots) >= 2:
        pair = shots[:2]
        hook = _pick(["This or that?", "Which would you pick?", "Help us settle this"], rnd)
        return Plan("poll", hook, [name(p) for p, _, _ in pair], pair, ["A", "B"], [_price(p) for p, _, _ in pair],
                    _pick(ENDINGS["poll"], rnd), site,
                    brief=f"This or that: the opening asks people to choose; scene A shows {name(pair[0][0])}, scene B shows "
                          f"{name(pair[1][0])}; the end asks them to vote A or B in the comments.")
    if topic == "countdown" and len(shots) >= 3:
        picks = shots[: min(len(shots), max(3, style.photos - 1))][:4]
        n = len(picks)
        ordered = list(reversed(picks))  # build up to #1, the post's own product
        return Plan("countdown", _pick([f"Our top {n} right now", f"Top {n} at {kit.name}", f"The {n} we can't stop talking about"], rnd),
                    [name(p) for p, _, _ in ordered], ordered, [f"#{n - i}" for i in range(n)], [_price(p) for p, _, _ in ordered],
                    _pick(ENDINGS["countdown"], rnd), site,
                    brief=f"A countdown: the opening promises the top {n}; scenes go from #{n} down to #1, one product each; "
                          "the end asks which is their #1.")
    # products (also the fallback when a topic has nothing to show)
    picks = shots[: style.photos] or reel_photos(campaign, post, style.photos, rnd)
    n = len(picks)
    if not n:
        facts = story_facts(kit)[:3] or [kit.tagline or kit.name]
        return Plan("story", f"Meet {kit.name}", facts, [(None, "", "")] * len(facts), [str(i + 1) for i in range(len(facts))],
                    [""] * len(facts), _pick(ENDINGS["story"], rnd), site, brief="A brand story told on the brand colours.")
    hook = _pick([f"{n} picks from {kit.name}", f"Meet {n} {kit.name} favourites", f"{n} you'll want this week"], rnd)
    lines = [name(p) if p else (LEAD_IN.sub("", said).strip() or kit.name) for p, _, said in picks]
    return Plan("products", hook, lines, picks, [f"{i + 1}/{n}" for i in range(n)], [_price(p) for p, _, _ in picks],
                _pick(ENDINGS["products"], rnd), site,
                brief=f"A showcase: the opening promises {n} picks; each scene names the product in its photo, in order; "
                      "the end asks which one is theirs.")


# "Spotlight: The August Rotation" -> "The August Rotation"
LEAD_IN = re.compile(r"^(spotlight|good to know|a tip from [^:]+|tip|new in|in the details|all about[^:]*|the edit)\s*:\s*", re.I)


REEL_SYSTEM = """You write the on-screen words for a 10 to 15 second vertical video (an Instagram Reel, YouTube Short or TikTok).
The video tells ONE connected story, described in "story". The hook makes a promise; each scene delivers the next part of
that promise, in order, about what its photo shows (keep each scene's label and subject); the closing line pays it off.
Specific to this brand, plain and punchy, words a person would say. No hashtags, no emojis, no AI clichés ("elevate",
"unleash", "indulge", "game-changer"). Never invent prices, offers, discounts or facts.
Return JSON: {"hook": "<= 7 words", "scenes": ["<= 7 words per scene, same order and count"], "cta": "<= 6 words"}"""


LANGUAGE_NOTES = {
    "roman": "Write every line in Roman Urdu: Urdu in Latin letters, casual, the way people in Pakistan text and post.",
    "ur": "Write every line in Urdu, in Urdu script.",
    "mix": "Write in English with natural Roman Urdu phrases mixed in, the way Pakistani brands post.",
}


async def write_script(kit: BrandKit, post: SocialPost, plan: Plan, style: "Style | None" = None,
                       language: str = "en") -> tuple[Plan, bool]:
    """The model words the planned story; the rule-based words stay when there's no model."""
    if not router.enabled:
        return plan, False
    scenes = [{"label": tag, "photo": (strategist.display_name(kit, p) + (f" ({_price(p)})" if _price(p) else "")) if p else "a photo from the brand",
               "draft": line} for tag, (p, _, _), line in zip(plan.tags, plan.shots, plan.lines)]
    user = (f"Brand: {strategist.brand_brief(kit)}\nStory: {plan.brief}\nDraft hook: {plan.hook}\nDraft closing: {plan.cta}\n"
            + (f"Video style: {style.label}. Tone: {style.tone}\n" if style else "")
            + (f"Language: {LANGUAGE_NOTES[language]} Product names stay as given.\n" if language in LANGUAGE_NOTES else "")
            + f"Scenes: {json.dumps(scenes, ensure_ascii=False)}")
    try:
        data = await router.complete_json("reel_script", REEL_SYSTEM, user, temperature=0.8, max_tokens=500)
    except (LLMError, ValueError) as exc:
        log.info("reel script fell back to rules: %s", exc)
        return plan, False
    if not isinstance(data, dict):
        return plan, False
    lines = [str(s) for s in (data.get("scenes") or []) if str(s).strip()]
    if len(lines) != len(plan.lines):
        lines = plan.lines
    plan.hook = str(data.get("hook") or "").strip() or plan.hook
    plan.lines = lines
    plan.cta = str(data.get("cta") or "").strip() or plan.cta
    return plan, True


def tidy_line(text: str, kind: str) -> str:
    """On-screen words read like a person wrote them: the humanizer's rule pass (no stock AI
    phrases, no em dashes, contractions), no full stop on a short line, a capital to start."""
    line = humanizer.rule_pass(" ".join(str(text or "").split())).strip()
    if line.endswith(".") and line.count(".") == 1 and not line.endswith(".."):
        line = line[:-1]
    return line[:1].upper() + line[1:]


async def humanize_lines(kit: BrandKit, lines: list[str], kinds: list[str], deep: bool) -> tuple[list[str], dict]:
    """Humanize a reel's words together, so they keep one voice. With a model, the full
    humanizer rewrites them (facts and the brand name are guarded); then every line gets the rule pass."""
    joined = "\n".join(lines)
    before = humanizer.ai_tell_score(joined)
    used_llm = False
    if deep and router.enabled and any(lines):
        res = await humanizer.humanize(joined, voice=kit.brand_voice_prompt, threshold=0, protect=[kit.name])
        rewritten = [x for x in res.text.split("\n") if x.strip()]
        if len(rewritten) == len(lines):  # one line in, one line out, or the rewrite is ignored
            lines, used_llm = rewritten, res.used_llm
    out = [tidy_line(line, kind) or line for line, kind in zip(lines, kinds)]
    return out, {"before": round(before, 1), "after": round(humanizer.ai_tell_score("\n".join(out)), 1), "used_llm": used_llm}


async def humanize_scenes(kit: BrandKit, scenes: list[ReelScene]) -> tuple[list[ReelScene], dict]:
    texts, info = await humanize_lines(kit, [s.text for s in scenes], [s.kind for s in scenes], deep=True)
    return [s.model_copy(update={"text": t}) for s, t in zip(scenes, texts)], info


def plan_scenes(plan: Plan) -> list[Scene]:
    first = next((path for _, path, _ in plan.shots if path), "")
    scenes = [Scene("hook", _words(plan.hook, 52), photo=first)]
    for (p, path, _), line, tag, sub in zip(plan.shots, plan.lines, plan.tags, plan.subs):
        scenes.append(Scene("product" if path else "fact", _words(line, 52), sub=sub, photo=path, tag=tag))
    scenes.append(Scene("cta", _words(plan.cta, 40), sub=plan.cta_sub))
    return scenes


# --------------------------------------------------------------------------- editing


def media_url(path: str) -> str:
    p = Path(path) if path else None
    return f"/media/{p.name}" if p and p.parent.resolve() == config.MEDIA_DIR.resolve() and p.exists() else ""


def photo_choices(campaign: Campaign) -> list[dict]:
    """Every photo a scene can use: ones the campaign already has, then the rest of the
    brand's product and website photos (downloaded when picked)."""
    out: list[dict] = []
    seen: set[str] = set()  # local files, web URLs already downloaded, and products already shown

    def add(url: str, label: str, price: str = "", remote: bool = False) -> None:
        if url and url not in seen:
            seen.add(url)
            out.append({"url": url, "label": label, "price": price, "remote": remote})

    kit = campaign.brand
    for p in sorted(campaign.posts, key=lambda p: p.publish_at):
        for bg, product in ((p.background, p.product), *((g, p.compare) for g in p.gallery[:1]),
                            *((s.background, None) for s in p.slides)):
            if bg and media_url(bg.path):
                seen.update({bg.credit_url or "", f"product:{product.name.lower()}" if product else ""})
                add(media_url(bg.path), product.name if product else (kit.name if kit else "Photo"), _price(product))
    if kit:
        for product in kit.products:
            if product.image_url and f"product:{product.name.lower()}" not in seen:
                add(product.image_url, product.name, _price(product), remote=True)
        for url in kit.images:
            add(url, f"From {kit.name}'s pages", remote=not url.startswith("/media/"))
    return out[:60]


async def resolve_photo(campaign: Campaign, ref: str) -> str:
    """A scene's photo reference -> a local file. Local files must be in MonoPlus's media folder;
    web photos must be ones found on the brand's own site."""
    ref = (ref or "").strip()
    if not ref:
        return ""
    if ref.startswith("/media/"):
        path = config.MEDIA_DIR / Path(ref.split("?")[0]).name
        if not path.exists() or path.suffix.lower() not in (".jpg", ".jpeg", ".png", ".webp"):
            raise ReelEditError("One of the photos is no longer available. Pick another.")
        return str(path)
    kit = campaign.brand
    allowed = {p.image_url for p in (kit.products if kit else []) if p.image_url} | set(kit.images if kit else [])
    if ref not in allowed:
        raise ReelEditError("Pick photos from the list: your campaign's photos, your website's or an upload.")
    try:
        bg = await photo_store.website_background(ref, credit=f"Photo from {kit.name}")
    except Exception as exc:  # noqa: BLE001 - download or decode failure
        raise ReelEditError(f"Couldn't download that photo: {exc}") from exc
    return bg.path


async def scenes_from_edit(campaign: Campaign, edited: list[ReelScene]) -> list[Scene]:
    edited = [s for s in edited if s.text.strip() or s.photo][:MAX_SCENES]
    if not edited:
        raise ReelEditError("A reel needs at least one scene.")
    out = []
    for s in edited:
        kind = s.kind if s.kind in KINDS else "product"
        path = await resolve_photo(campaign, s.photo) if kind != "cta" else ""
        if kind == "product" and not path:
            kind = "fact"  # a product scene without a photo is shown on the brand colour
        out.append(Scene(kind, " ".join(s.text.split())[:80], sub=" ".join(s.sub.split())[:40], photo=path, tag=s.tag.strip()[:12]))
    return out


def to_edit(scenes: list[Scene]) -> list[ReelScene]:
    return [ReelScene(kind=s.kind, text=s.text, sub=s.sub, photo=media_url(s.photo), tag=s.tag) for s in scenes]
