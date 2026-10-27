"""Competitor research agent.

Given a brand (its website), the agent:
  1. finds its competitors: a few web searches ("<brand> competitors", "brands like <brand>",
     "best <category> brands in <country>"), then reads the round-up articles those searches
     return for brand names linked to their own websites (and, with a model, asks Nemotron to
     name the direct competitors among them);
  2. reads each competitor's site: prices, sales, product lines, who it sells to, the service
     promises it makes (delivery, returns, cash on delivery…) and the social platforms it uses;
  3. compares them with the brand in plain facts: price position, discounting, gaps, strengths;
  4. turns that into advice the brand can act on: recommendations, a 4-week plan tied to its
     seasonal calendar and content ideas (Nemotron writes these when a model is configured;
     otherwise rules derived from the comparison do).

Everything said about a competitor comes from its own website or the search results.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import statistics
from collections import Counter
from datetime import date
from typing import AsyncIterator
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from .. import config
from ..llm import LLMError, router
from ..netguard import UnsafeURL, safe_client
from ..schemas import BrandKit, CompetitorProfile, CompetitorReport, PlanWeek, Recommendation
from ..scraper import ingestor
from ..scraper import products as product_finder
from . import calendar, freesearch, trends
from .calendar import COUNTRY_NAMES
from .playbooks import amount, join_words, playbook_for, product_line, tidy_price

log = logging.getLogger(__name__)

MAX_COMPETITORS = 5
# Sites that talk about brands but aren't one: directories, marketplaces, social networks, media.
NOT_BRANDS = {
    "similarweb.com", "semrush.com", "cbinsights.com", "craft.co", "comparably.com", "tracxn.com", "crunchbase.com", "zoominfo.com",
    "owler.com", "apistemic.com", "growjo.com", "rocketreach.co", "wikipedia.org", "facebook.com", "instagram.com", "youtube.com",
    "tiktok.com", "linkedin.com", "pinterest.com", "twitter.com", "x.com", "reddit.com", "quora.com", "medium.com", "amazon.com",
    "daraz.pk", "ebay.com", "etsy.com", "alibaba.com", "aliexpress.com", "walmart.com", "google.com", "bing.com", "apple.com",
    "blogspot.com", "wordpress.com", "trustpilot.com", "yelp.com", "tripadvisor.com", "glassdoor.com", "indeed.com", "statista.com",
    "forbes.com", "bloomberg.com", "reuters.com", "dawn.com", "tribune.com.pk", "thenews.com.pk", "brecorder.com", "nytimes.com",
    "whatsapp.com", "wa.me", "shopify.com", "bit.ly", "goo.gl", "linktr.ee", "maps.google.com", "play.google.com", "apps.apple.com",
}
DOMAIN_RE = re.compile(r"\b((?:[a-z0-9-]+\.)+(?:com\.pk|co\.uk|com\.au|co\.in|com|pk|in|ae|co|net|store|shop|ca|uk|au))\b", re.I)
UA = {"User-Agent": ingestor.USER_AGENT, "Accept": "text/html,application/xhtml+xml", "Accept-Language": "en-US,en;q=0.9"}


def registrable(host: str) -> str:
    host = host.lower().split(":")[0].removeprefix("www.")
    parts = host.split(".")
    if len(parts) >= 3 and parts[-2] in ("com", "co", "org", "net") and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def brand_slugs(kit: BrandKit) -> set[str]:
    out = {slug(w) for w in re.findall(r"[A-Za-z0-9]{3,}", kit.name) if len(w) >= 4}
    if kit.website_url:
        out.add(registrable(urlparse(kit.website_url).netloc).split(".")[0])
    return {s for s in out if len(s) >= 4} - {"shop", "store", "official", "online", "pakistan", "bakery"}


def is_brand_domain(domain: str, own: set[str]) -> bool:
    d = registrable(domain)
    return bool(d) and "." in d and d not in NOT_BRANDS and not any(s in d.split(".")[0] for s in own)


# --------------------------------------------------------------------------- 1. find competitors


def search_queries(kit: BrandKit) -> list[str]:
    category = playbook_for(kit.industry).category
    country = COUNTRY_NAMES.get(kit.country.upper(), "").removeprefix("the ")
    queries = [f"{kit.name} competitors", f"brands like {kit.name}" + (f" {country}" if country else "")]
    if category != "products and services":
        queries.append(f"best {category} brands in {country} {date.today().year}" if country else f"best {category} brands like {kit.name}")
    return queries


def candidates_from_results(results: list[dict], own: set[str]) -> Counter:
    """Brand domains named in search results: in snippets ("competitors: gulahmedshop.com, …")
    or as results that are a brand's own homepage."""
    found: Counter = Counter()
    for r in results:
        for d in DOMAIN_RE.findall(f"{r.get('title', '')} {r.get('snippet', '')}"):
            if is_brand_domain(d, own):
                found[registrable(d)] += 1
        u = urlparse(r.get("url", ""))
        if u.path in ("", "/") and is_brand_domain(u.netloc, own):
            found[registrable(u.netloc)] += 1
    return found


def candidates_from_article(html: str, page_url: str, own: set[str]) -> dict[str, tuple[str, str]]:
    """A "brands like X" round-up links each brand's name to its website: {domain: (name, host linked)}."""
    soup = BeautifulSoup(html, "html.parser")
    page_domain = registrable(urlparse(page_url).netloc)
    out: dict[str, str] = {}
    for a in soup.find_all("a", href=True):
        href = urljoin(page_url, a["href"])
        host = urlparse(href).netloc
        name = " ".join(a.get_text(" ", strip=True).split())
        d = registrable(host)
        if not host or d == page_domain or not is_brand_domain(host, own) or not (2 <= len(name) <= 40):
            continue
        words = re.findall(r"[A-Za-z0-9]+", name)
        if not (1 <= len(words) <= 4):
            continue
        # The link text must be the brand's name, i.e. match its domain ("Gul Ahmed" -> gulahmedshop.com).
        label = d.split(".")[0]
        if slug(name)[:5] in label or label[:5] in slug(name):
            out.setdefault(d, (name, host.lower()))
    return out


DISCOVER_SYSTEM = """You identify a brand's direct competitors: brands selling similar products to the same customers in
the same market. From the search results, list up to 6 direct competitors that have their own website.
Return JSON: {"competitors": [{"name": "...", "website": "https://..."}]}. Only use brands that appear in the results."""


KNOWN_SYSTEM = """Name the direct competitors of the brand below that you are confident exist: brands selling similar
products to the same customers in the same country, each with its official website. If unsure, return fewer.
Return JSON: {"competitors": [{"name": "...", "website": "https://..."}]} (at most 6)."""


def homepage(url: str) -> str:
    url = url.strip()
    host = urlparse(url if "//" in url else f"https://{url}").netloc
    return f"https://{host}/" if host else ""


async def discover(kit: BrandKit, given: list[str] | None = None) -> tuple[list[tuple[str, str, str]], list[str]]:
    """[(name, homepage url, how it was found)], plus notes on what was searched.

    Competitors the user named come first; then web search; then, if search found nothing and a
    model is configured, the model's own knowledge (every site is still read and checked)."""
    own = brand_slugs(kit)
    notes: list[str] = []
    named = [(registrable(urlparse(homepage(u)).netloc).split(".")[0].title(), homepage(u), "you added it")
             for u in (given or []) if homepage(u)]
    picked_named = [c for c in named if is_brand_domain(urlparse(c[1]).netloc, own)]
    found, search_notes = await search_for_competitors(kit, own)
    notes += search_notes
    if not found and router.enabled:
        try:
            data = await router.complete_json("classify", KNOWN_SYSTEM,
                                              f"{kit.name}: {kit.industry}, {COUNTRY_NAMES.get(kit.country.upper(), 'country unknown')}, "
                                              f"{kit.website_url}. {kit.description[:300]}", temperature=0.1, max_tokens=400)
            for c in (data.get("competitors") or [])[:6] if isinstance(data, dict) else []:
                url = homepage(str(c.get("website") or ""))
                if url and is_brand_domain(urlparse(url).netloc, own):
                    found.append((str(c.get("name") or "")[:60] or urlparse(url).netloc, url, "suggested by Nemotron (site checked)"))
            notes.append(f"Search found nothing, so Nemotron suggested {len(found)} competitors to check")
        except (LLMError, AttributeError, TypeError) as exc:
            notes.append(f"Model couldn't suggest competitors ({exc})")
    seen = {registrable(urlparse(u).netloc) for _, u, _ in picked_named}
    merged = picked_named + [c for c in found if registrable(urlparse(c[1]).netloc) not in seen]
    return merged[: MAX_COMPETITORS + 2], notes


async def search_for_competitors(kit: BrandKit, own: set[str]) -> tuple[list[tuple[str, str, str]], list[str]]:
    notes: list[str] = []
    results: list[dict] = []
    for q in search_queries(kit):
        rows = await trends.search(q, topic="general", max_results=8)
        notes.append(f"Searched “{q}”: {len(rows)} results")
        results += [{"title": r.title, "url": r.url, "snippet": r.snippet} for r in rows]
    counts = candidates_from_results(results, own)
    names: dict[str, str] = {}
    hosts: dict[str, str] = {}  # the exact host an article linked (www. or a country subdomain)

    articles = [r["url"] for r in results if is_article(r)][:3]
    pages = await fetch_html_many(articles)
    for url, html in pages.items():
        found = candidates_from_article(html, url, own)
        notes.append(f"Read {urlparse(url).netloc}: {len(found)} brands linked")
        for d, (name, host) in found.items():
            counts[d] += 2  # a brand named and linked in a round-up is a strong signal
            names.setdefault(d, name)
            hosts.setdefault(d, host)

    picked: list[tuple[str, str, str]] = []
    if router.enabled and results:
        listing = "\n".join(f"- {r['title']} ({r['url']}): {r['snippet'][:200]}" for r in results[:24])
        known = ", ".join(f"{names.get(d, d)} ({d})" for d, _ in counts.most_common(15))
        try:
            data = await router.complete_json("classify", DISCOVER_SYSTEM,
                                              f"BRAND: {kit.name} ({kit.industry}, {kit.country or 'unknown country'}), {kit.website_url}\n\n"
                                              f"SEARCH RESULTS:\n{listing}\n\nBRANDS LINKED IN ARTICLES: {known or 'none'}",
                                              temperature=0.1, max_tokens=500)
            for c in (data.get("competitors") or [])[:6] if isinstance(data, dict) else []:
                site = str(c.get("website") or "")
                host = urlparse(site if "//" in site else f"https://{site}").netloc
                if host and is_brand_domain(host, own):
                    picked.append((str(c.get("name") or host)[:60], f"https://{host}/", "named by Nemotron from search results"))
        except (LLMError, AttributeError, TypeError) as exc:
            notes.append(f"Model couldn't pick competitors ({exc}); using what the searches linked")
    for d, n in counts.most_common():
        if len(picked) >= MAX_COMPETITORS + 2:  # a couple spare, in case some sites can't be read
            break
        if all(registrable(urlparse(u).netloc) != d for _, u, _ in picked):
            how = "linked in a round-up article" if d in names else "named in search results"
            picked.append((names.get(d) or d.split(".")[0].title(), f"https://{hosts.get(d, d)}/", how))
    return picked, notes


def is_article(r: dict) -> bool:
    u = urlparse(r.get("url", ""))
    d = registrable(u.netloc)
    return bool(u.path.strip("/")) and d not in NOT_BRANDS and "google.com" not in d


async def fetch_html_many(urls: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    if not urls:
        return out
    async with safe_client(headers=UA, follow_redirects=True, timeout=12) as client:
        async def one(u: str):
            try:
                r = await client.get(u)
                if r.status_code == 200 and "html" in r.headers.get("content-type", "html"):
                    out[u] = r.text[:800_000]
            except (httpx.HTTPError, UnsafeURL):
                pass
        await asyncio.gather(*(one(u) for u in urls))
    return out


# --------------------------------------------------------------------------- 2. read each site


def currency_of(price: str) -> str:
    m = re.match(r"\s*([^\d\s]+)", price or "")
    return m.group(1).strip(".") if m else ""


def profile_from_site(site: ingestor.ScrapedSite, name: str, found_via: str) -> CompetitorProfile:
    priced = [(p, amount(p.price)) for p in site.products if amount(p.price) > 0]
    discounts = [round(100 * (1 - amount(p.price) / amount(p.was_price))) for p in site.products
                 if p.was_price and amount(p.was_price) > amount(p.price) > 0]
    price_range = ""
    if priced:
        lo, hi = min(priced, key=lambda x: x[1])[0], max(priced, key=lambda x: x[1])[0]
        price_range = tidy_price(lo.price) if lo.price == hi.price else f"{tidy_price(lo.price)} to {tidy_price(hi.price)}"
    return CompetitorProfile(
        name=name, url=site.url, tagline=ingestor.tagline_from(site, name), price_range=price_range,
        median_price=statistics.median([v for _, v in priced]) if priced else 0, currency=currency_of(priced[0][0].price) if priced else "",
        products_seen=len(site.products), on_sale=len(discounts), best_discount=max(discounts, default=0),
        lines=list(dict.fromkeys(product_line(p.category or p.name) for p in site.products if p.name))[:5],
        segments=ingestor.detect_segments(site), claims=ingestor.service_claims(site), socials=site.socials,
        # Only real product cards (a photo and a price), not icons or banners that happened to be linked.
        sample_products=[p for p in site.products if p.image_url and amount(p.price) > 0][:3], found_via=found_via,
    )


async def shopify_store_data(url: str, client: httpx.AsyncClient) -> ingestor.ScrapedSite | None:
    """Shopify stores publish a store summary (/meta.json) and product feed (/products.json) for
    exactly this kind of reading; use them when the store's pages refuse automated visits."""
    origin = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
    try:
        meta = await client.get(f"{origin}/meta.json", headers={"Accept": "application/json"})
        if meta.status_code != 200 or not isinstance(meta.json(), dict) or "myshopify_domain" not in meta.json():
            return None
        shop = meta.json()
        site = ingestor.ScrapedSite(url=f"{origin}/", title=str(shop.get("name") or ""), site_name=str(shop.get("name") or ""),
                                    description=str(shop.get("description") or ""), shop=shop)
        feed = await client.get(f"{origin}/products.json?limit=30", headers={"Accept": "application/json"})
        if feed.status_code == 200:
            site.products = product_finder.shopify_products(feed.json(), origin, str(shop.get("currency") or ""))
        return site
    except (httpx.HTTPError, UnsafeURL, ValueError):
        return None


async def analyse(name: str, url: str, found_via: str, client: httpx.AsyncClient) -> CompetitorProfile:
    try:
        site = await ingestor.fetch_site(url, client)
    except (ingestor.SiteUnavailable, UnsafeURL, httpx.HTTPError) as exc:
        site = await shopify_store_data(url, client) if isinstance(exc, ingestor.SiteUnavailable) else None
        if site is None:
            return CompetitorProfile(name=name, url=url, found_via=found_via, reachable=False, note=str(exc)[:200])
        found_via += " · read from its public store data"
    # A name from an article or the model ("Gul Ahmed") reads better than a page title; a name
    # guessed from a domain ("Gulahmedshop") doesn't, so use the site's own name then.
    real = ingestor.clean_name(site)
    from_domain = "search results" in found_via or found_via == "you added it"
    if from_domain and real and len(real) <= 40 and real.lower() not in ("home", "index", "shop"):
        name = real
    return profile_from_site(site, name, found_via)


# --------------------------------------------------------------------------- 3. compare


def verb(who: list, one: str, many: str) -> str:
    return one if len(who) == 1 else many


def money(currency: str, value: float) -> str:
    """PKR 8,000 / $12 / £9.50."""
    text = f"{value:,.0f}" if value == int(value) else f"{value:,.2f}"
    return f"{currency} {text}" if currency[:1].isalpha() else f"{currency}{text}"


def priced_rivals(brand: CompetitorProfile, rivals: list[CompetitorProfile]) -> list[CompetitorProfile]:
    """Competitors whose prices were read, in the brand's currency (others can't be compared)."""
    return [r for r in rivals if r.median_price and r.currency and r.currency == brand.currency]


def compare(brand: CompetitorProfile, rivals: list[CompetitorProfile]) -> tuple[list[str], list[str], list[str]]:
    """(position, strengths, gaps): plain facts, each traceable to the sites read."""
    position, strengths, gaps = [], [], []
    priced = priced_rivals(brand, rivals)
    if brand.median_price and priced:
        market = statistics.median([r.median_price for r in priced])
        diff = round(100 * (brand.median_price / market - 1))
        against = (f"across {join_words([r.name for r in priced])}" if len(priced) > 1
                   else f"at {priced[0].name} (the only competitor whose prices could be read)")
        if abs(diff) < 10:
            position.append(f"Priced in line with competitors: a typical {brand.name} item is {money(brand.currency, brand.median_price)}, "
                            f"close to the typical {money(brand.currency, market)} {against}.")
        else:
            position.append(f"Priced {abs(diff)}% {'below' if diff < 0 else 'above'} competitors: a typical {brand.name} item is "
                            f"{money(brand.currency, brand.median_price)} against a typical {money(brand.currency, market)} {against}.")
    discounting = [r for r in rivals if r.best_discount]
    if discounting:
        names = join_words([f"{r.name} (up to {r.best_discount}% off)" for r in discounting[:3]])
        position.append(f"{len(discounting)} of {len(rivals)} competitors {verb(discounting, 'is', 'are')} running sales right now: {names}.")
        if not brand.best_discount:
            gaps.append("Competitors are discounting and you show no sale prices, so price-led shoppers may go elsewhere this season.")
    if brand.best_discount:
        strengths.append(f"You're running a sale yourself (up to {brand.best_discount}% off), which you can lead with.")
    for claim in sorted({c for r in rivals for c in r.claims} - set(brand.claims)):
        who = [r.name for r in rivals if claim in r.claims]
        gaps.append(f"{join_words(who[:3])} {verb(who, 'promises', 'promise')} “{claim.lower()}”; your site doesn't say it. "
                    "If you offer it, say it in posts.")
    for claim in sorted(set(brand.claims) - {c for r in rivals for c in r.claims}):
        strengths.append(f"Only you promise “{claim.lower()}” among the sites read.")
    for platform in sorted({s for r in rivals for s in r.socials} - set(brand.socials) - {"whatsapp", "linkedin"}):
        who = [r.name for r in rivals if platform in r.socials]
        if len(who) >= max(1, len(rivals) // 2):
            gaps.append(f"{join_words(who[:3])} {'is' if len(who) == 1 else 'are'} on {platform.title()}; your site doesn't link a {platform.title()} account.")
    for seg in sorted({s for r in rivals for s in r.segments} - set(brand.segments)):
        who = [r.name for r in rivals if seg in r.segments]
        position.append(f"{join_words(who[:3])} also {verb(who, 'sells', 'sell')} for {seg}; your main page doesn't show any.")
    if brand.segments and len(brand.segments) < len({s for r in rivals for s in r.segments}):
        strengths.append(f"A sharper focus ({join_words(brand.segments)}) than broader competitors: own it in your positioning.")
    return position, strengths, gaps


# --------------------------------------------------------------------------- 4. advise


def rule_advice(kit: BrandKit, brand: CompetitorProfile, rivals: list[CompetitorProfile], gaps: list[str],
                start: date) -> tuple[list[Recommendation], list[PlanWeek], list[str]]:
    """Advice derived from the comparison and the brand's calendar, without a model."""
    recs: list[Recommendation] = []
    rival_names = join_words([r.name for r in rivals[:3]]) or "your competitors"
    priced = priced_rivals(brand, rivals)
    priced_names = join_words([r.name for r in priced[:3]])
    market = statistics.median([r.median_price for r in priced]) if priced and brand.median_price else 0
    if market and brand.median_price < market * 0.9:
        recs.append(Recommendation(title="Own the value position",
                                   why=f"You're priced below {priced_names} for comparable {playbook_for(kit.industry).category}.",
                                   how="Show prices on every post, put two similar pieces side by side (\"this or that\"), and use lines like "
                                       "\"same quality, fairer price\" without naming competitors."))
    elif market and brand.median_price > market * 1.1:
        recs.append(Recommendation(title="Justify the premium",
                                   why=f"You're priced above {priced_names}, so shoppers need a reason.",
                                   how="Lead with craft, materials and detail close-ups; avoid matching their discounts and offer "
                                       "early access or exclusives instead."))
    else:
        why = (f"Your prices sit with {priced_names}, so price alone won't win." if market else
               f"{rival_names} sell similar {playbook_for(kit.industry).category} to the same shoppers, so you need a reason to be remembered.")
        recs.append(Recommendation(title="Differentiate on more than price", why=why,
                                   how="Pick one thing to be known for (fit, comfort, design, service) and repeat it in every post's first line."))
    discounting = [r for r in rivals if r.best_discount]
    moments = calendar.upcoming(kit.country, start, 28)
    sale_moments = [m for m in moments if m.kind == "sale"]
    if discounting:
        recs.append(Recommendation(title="Have an answer to their sales",
                                   why=f"{join_words([r.name for r in discounting[:3]])} {verb(discounting, 'is', 'are')} discounting up to "
                                       f"{max(r.best_discount for r in discounting)}%"
                                       + (f", with {join_words([m.label() for m in sale_moments[:2]])} coming up" if sale_moments else "") + ".",
                                   how=("Lead with your own sale prices (now vs was) and a clear end date." if brand.best_discount else
                                        "Counter with bundles, free delivery or early access for followers rather than a deep cut, "
                                        "or plan a short, clearly dated sale.")))
    elif sale_moments:
        recs.append(Recommendation(title=f"Get ahead of {sale_moments[0].name}",
                                   why="Shoppers plan purchases around it and competitors haven't started yet.",
                                   how=f"Start teasing a week before {sale_moments[0].label()} and post your offer on the day."))
    claim_gaps = [g for g in gaps if g.startswith(tuple(r.name for r in rivals)) and "promise" in g]
    if claim_gaps:
        claims = sorted({c for r in rivals for c in r.claims} - set(brand.claims))
        recs.append(Recommendation(title="Say your service promises out loud",
                                   why=f"Competitors advertise {join_words([c.lower() for c in claims[:3]])}; those remove purchase doubt.",
                                   how="If you offer them, add one promise to every caption's last line and to your bio."))
    platform_gaps = sorted({s for r in rivals for s in r.socials} - set(brand.socials) - {"whatsapp", "linkedin"})
    if "tiktok" in platform_gaps or "youtube" in platform_gaps:
        p = "TikTok" if "tiktok" in platform_gaps else "YouTube"
        recs.append(Recommendation(title=f"Start on {p}",
                                   why="Competitors are building audiences there and you aren't visible.",
                                   how="Turn your carousels into 10–15 second videos: one product, three angles, price on screen."))
    hero = sorted(kit.products, key=lambda p: -(amount(p.was_price) - amount(p.price)) if p.was_price else 0)[:1]
    if hero:
        recs.append(Recommendation(title=f"Make the {product_line(hero[0].name)} line your hero",
                                   why="One recognisable product makes a feed memorable; competitors spread attention thin.",
                                   how="Feature it in every third post: styling tips, close-ups, customer photos and the price."))
    recs.append(Recommendation(title="Post what competitors don't",
                               why="Most brand feeds are product photos only.",
                               how="Mix in this-or-that polls, styling tips, behind-the-scenes and seasonal posts (MonoPlus campaigns already do)."))

    m_names = [m.label() for m in moments]
    plan = [
        PlanWeek(week=1, focus="Position and hero products", actions=[
            recs[0].how.split(";")[0].rstrip("."), f"Introduce your hero line{f': {product_line(hero[0].name)}' if hero else ''}",
            "Update your bio with your one-line promise and best service claim"]),
        PlanWeek(week=2, focus=f"Build up to {m_names[0]}" if m_names else "Social proof", actions=(
            [f"Tease {m_names[0]} three days ahead", "Post a this-or-that poll between two bestsellers", "Share a styling or how-to carousel"]
            if m_names else ["Repost customer photos and reviews", "Post a this-or-that poll", "Share a how-to carousel"])),
        PlanWeek(week=3, focus=f"{m_names[1]}" if len(m_names) > 1 else "Engagement", actions=(
            [f"Plan {m_names[1]} posts with clear dates and prices", "Answer every comment within a day", "Go behind the scenes once"]
            if len(m_names) > 1 else ["Run a question post", "Go behind the scenes once", "Feature a customer favourite"])),
        PlanWeek(week=4, focus="Convert", actions=["Lead with prices and service promises", "Last-chance post for any offer",
                                                   "Review which post types got the most saves and plan next month around them"]),
    ]
    ideas = [
        "This or that: two of your bestsellers, vote A or B",
        "\"Why our prices are what they are\": materials and making" if market and brand.median_price > market else
        "\"Same quality, fairer price\": a close-up of the details",
        "3 ways to wear or use one hero product (carousel)",
        "Customer photo of the week, with their permission",
    ] + [f"{m.name} countdown post" for m in moments[:2]]
    return recs[:6], plan, ideas


ADVICE_SYSTEM = """You are a senior marketing strategist for small and mid-size brands. From the COMPARISON of a brand with its
competitors (facts read from their websites) and the brand's SEASONAL CALENDAR, write advice the brand can act on now.
Never name a fact that isn't in the input. Never advise attacking competitors by name in public posts.
Return JSON:
{"summary": "3 sentences: where the brand stands and the single biggest opportunity",
 "recommendations": [{"title": "<= 8 words", "why": "the evidence, citing the comparison", "how": "concrete steps"}],  // 4-6
 "plan": [{"week": 1, "focus": "...", "actions": ["...", "..."]}],  // 4 weeks
 "content_ideas": ["6 specific post ideas for this brand"]}"""


async def model_advice(kit: BrandKit, report: CompetitorReport, start: date) -> bool:
    payload = {
        "brand": report.brand.model_dump(exclude={"sample_products"}) if report.brand else {"name": kit.name},
        "competitors": [c.model_dump(exclude={"sample_products"}) for c in report.competitors if c.reachable],
        "position": report.position, "strengths": report.strengths, "gaps": report.gaps,
    }
    moments = "\n".join(f"- {m.label()}" for m in calendar.upcoming(kit.country, start, 28)) or "- none"
    try:
        data = await router.complete_json("research_report", ADVICE_SYSTEM,
                                          f"COMPARISON:\n{json.dumps(payload, ensure_ascii=False)[:9000]}\n\nSEASONAL CALENDAR:\n{moments}",
                                          temperature=0.4, max_tokens=2500)
        recs = [Recommendation.model_validate(r) for r in data.get("recommendations", []) if isinstance(r, dict) and r.get("title")]
        plan = [PlanWeek.model_validate(w) for w in data.get("plan", []) if isinstance(w, dict) and w.get("focus")]
        if not recs:
            return False
        report.summary = str(data.get("summary") or "")[:800]
        report.recommendations, report.plan = recs[:6], plan[:4]
        report.content_ideas = [str(x)[:200] for x in data.get("content_ideas", [])][:8]
        report.method = "model"
        return True
    except (LLMError, AttributeError, TypeError, ValueError) as exc:
        log.info("model advice failed, using rules: %s", exc)
        return False


def rule_summary(kit: BrandKit, report: CompetitorReport) -> str:
    rivals = [c for c in report.competitors if c.reachable]
    if not rivals:
        why = ("web search is refusing requests from this server right now (no TAVILY_API_KEY is set, and the free search is rate-limited)"
               if freesearch.recently_blocked() and not config.tavily_enabled() else "no competitor websites could be found or read")
        return (f"No competitors were compared: {why}. Add competitors you know (their websites) and run it again. Meanwhile this plan "
                f"uses {kit.name}'s own site, its industry playbook and its seasonal calendar.")
    first = report.position[0] if report.position else ""
    top = report.recommendations[0].title if report.recommendations else ""
    return f"{kit.name} was compared with {join_words([c.name for c in rivals])}. {first} Biggest opportunity: {top.lower()}."


# --------------------------------------------------------------------------- orchestration


async def run(kit: BrandKit, start: date | None = None, competitor_urls: list[str] | None = None) -> AsyncIterator[dict]:
    """Yields {"type": "progress", "message": ...} events, then {"type": "report", "report": CompetitorReport}."""
    start = start or date.today()
    yield {"type": "progress", "message": f"Looking for brands that compete with {kit.name}"}
    found, notes = await discover(kit, competitor_urls)
    for n in notes:
        yield {"type": "progress", "message": n}
    yield {"type": "progress", "message": f"Found {len(found)} candidate competitors" + (
        f": {join_words([n for n, _, _ in found[:6]])}" if found else "")}

    async with safe_client(headers=UA, follow_redirects=True, timeout=12) as client:
        brand_task = analyse(kit.name, kit.website_url, "your website", client) if kit.website_url else None
        sem = asyncio.Semaphore(3)

        async def limited(name: str, url: str, how: str) -> CompetitorProfile:
            async with sem:
                return await analyse(name, url, how, client)

        jobs = [limited(n, u, h) for n, u, h in found]
        profiles = await asyncio.gather(*([brand_task] if brand_task else []), *jobs)
    brand = profiles[0] if brand_task else CompetitorProfile(name=kit.name)
    rivals = list(profiles[1:] if brand_task else profiles)
    brand.name = kit.name
    readable = [r for r in rivals if r.reachable and (r.products_seen or r.tagline)]
    yield {"type": "progress", "message": f"Read {len(readable)} competitor sites"
           + (f" ({len(rivals) - len(readable)} couldn't be read)" if len(rivals) > len(readable) else "")}
    rivals = (readable + [r for r in rivals if r not in readable])[:MAX_COMPETITORS]

    report = CompetitorReport(brand=brand, competitors=rivals)
    report.position, report.strengths, report.gaps = compare(brand, readable)
    yield {"type": "progress", "message": "Compared prices, sales, promises and platforms"}
    if not (router.enabled and readable and await model_advice(kit, report, start)):
        report.recommendations, report.plan, report.content_ideas = rule_advice(kit, brand, readable, report.gaps, start)
    if not report.summary:
        report.summary = rule_summary(kit, report)
    yield {"type": "progress", "message": "Wrote the strategy and a 4-week plan" + (" with Nemotron" if report.method == "model" else "")}
    yield {"type": "report", "report": report}


def to_markdown(kit_name: str, r: CompetitorReport) -> str:
    """The report as Markdown (for the research library, exports and campaign context)."""
    out = [f"## Competitor analysis: {kit_name}", "", r.summary, ""]
    if r.competitors:
        out += ["### Competitors", "", "| Brand | Prices | On sale | Sells for | Promises | Platforms |", "|---|---|---|---|---|---|"]
        for c in r.competitors:
            sale = f"up to {c.best_discount}%" if c.best_discount else ("no" if c.reachable else "?")
            out.append(f"| [{c.name}]({c.url}) | {c.price_range or '–'} | {sale} | {', '.join(c.segments) or '–'} | "
                       f"{', '.join(c.claims) or '–'} | {', '.join(c.socials) or '–'} |")
        out.append("")
    for title, items in (("Where you stand", r.position), ("Your strengths", r.strengths), ("Gaps", r.gaps)):
        if items:
            out += [f"### {title}", ""] + [f"- {x}" for x in items] + [""]
    if r.recommendations:
        out += ["### Recommended strategy", ""]
        for i, rec in enumerate(r.recommendations, 1):
            out.append(f"{i}. **{rec.title}**. {rec.why} *How:* {rec.how}")
        out.append("")
    if r.plan:
        out += ["### 4-week plan", ""]
        for w in r.plan:
            out.append(f"- **Week {w.week}: {w.focus}**: " + "; ".join(w.actions))
        out.append("")
    if r.content_ideas:
        out += ["### Content ideas", ""] + [f"- {x}" for x in r.content_ideas]
    return "\n".join(out)
