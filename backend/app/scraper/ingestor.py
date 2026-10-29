"""Agent 1: Web scraper & brand asset ingestor.

Turns a website URL (or a social handle) into a BrandKit: name, logo, colour palette,
value propositions, industry, location and a brand-voice prompt.
"""
from __future__ import annotations

import asyncio
import colorsys
import io
import logging
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, quote, unquote, urlencode, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from PIL import Image, ImageStat

from .. import config
from ..llm import LLMError, router
from ..netguard import UnsafeURL, safe_client
from ..agents.calendar import COUNTRY_NAMES
from ..schemas import BrandKit, Product
from . import products as product_finder

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36 AutoMarketerBot/1.0"
)
SOCIAL_HOSTS = ("instagram.com", "x.com", "twitter.com", "linkedin.com", "facebook.com", "tiktok.com")
HEX_RE = re.compile(r"#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")
RGB_RE = re.compile(r"rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})")
HSL_RE = re.compile(r"hsla?\(\s*([\d.]+)(?:deg)?[\s,]+([\d.]+)%[\s,]+([\d.]+)%")
PRESET_RE = re.compile(r"--wp--preset--[\w-]+\s*:[^;}]*[;}]|\.has-[\w-]+-(?:background-)?color[^{]*\{[^}]*\}")

INDUSTRY_KEYWORDS = {
    "Footwear": ["footwear", "shoes", "shoe", "sandal", "sneaker", "heels", "slipper", "boots", "loafer", "chappal",
                 "peshawari", "khussa", "moccasin", "joggers", "flip flop"],
    "Fashion & Apparel": ["dress", "kurta", "dupatta", "shirt", "jeans", "apparel", "clothing", "fashion", "unstitched",
                          "ready to wear", "co-ord", "embroidered", "trousers", "abaya", "shalwar", "jacket"],
    "Jewellery": ["jewel", "necklace", "earring", "bracelet", "bangle", "pendant", "diamond", "gold plated"],
    "Furniture & Home": ["furniture", "sofa", "mattress", "home decor", "cushion", "dining table", "wardrobe", "bedding"],
    "Food & Beverage": ["restaurant", "cafe", "coffee", "bakery", "menu", "pizza", "kitchen", "dining", "brunch",
                        "fried chicken", "burger", "zinger", "wings", "fries", "biryani", "shawarma", "kebab", "kabab",
                        "sandwich", "meal deal", "takeaway", "dine-in", "dine in", "nuggets", "steak", "noodles"],
    "Fitness & Wellness": ["gym", "fitness", "yoga", "pilates", "wellness", "workout", "trainer", "spa"],
    "Beauty": ["salon", "beauty", "hair", "nails", "skincare", "makeup", "barber", "cosmetic"],
    "Real Estate": ["real estate", "property", "realtor", "homes for sale", "apartment", "listing"],
    "Software & SaaS": ["software", "saas", "platform", "api", "dashboard", "integration", "app", "developers"],
    "E-commerce & Retail": ["shop", "store", "cart", "shipping", "collection", "boutique", "sale"],
    "Professional Services": ["consulting", "agency", "law", "accounting", "advisory", "firm", "clients"],
    "Healthcare": ["clinic", "dental", "dentist", "doctor", "health", "patients", "medical", "therapy"],
    "Education": ["course", "learn", "school", "tutoring", "academy", "students", "training"],
    "Home Services": ["plumbing", "cleaning", "repair", "landscaping", "roofing", "hvac", "contractor"],
}


@dataclass
class ScrapedSite:
    url: str
    title: str = ""
    site_name: str = ""
    description: str = ""
    headings: list[str] = field(default_factory=list)
    paragraphs: list[str] = field(default_factory=list)
    colors: list[str] = field(default_factory=list)
    theme_color: str | None = None
    logo_candidates: list[str] = field(default_factory=list)
    stylesheets: list[str] = field(default_factory=list)
    address_hint: str = ""
    products: list[Product] = field(default_factory=list)
    images: list[str] = field(default_factory=list)
    shop: dict = field(default_factory=dict)  # Shopify's public store info (/meta.json), when it's a Shopify store
    socials: list[str] = field(default_factory=list)  # platforms the site links to: instagram, tiktok…
    branches: list[str] = field(default_factory=list)  # store / restaurant branch names, when the site lists them
    text: str = ""  # the page's visible text (trimmed), for promises made in banners and footers

    def text_blob(self, limit: int = 4000) -> str:
        catalogue = [f"Product: {p.name}" + (f" ({p.category})" if p.category else "") + (f" {p.price}" if p.price else "")
                     for p in self.products[:12]]
        parts = [self.title, self.site_name, self.description, *catalogue, *self.headings, *self.paragraphs]
        return "\n".join(p for p in parts if p)[:limit]


# --------------------------------------------------------------------------- parsing


def normalize_hex(value: str) -> str:
    value = value.lstrip("#")
    if len(value) == 3:
        value = "".join(c * 2 for c in value)
    return "#" + value.upper()


def _rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _hls(hex_color: str) -> tuple[float, float, float]:
    r, g, b = (c / 255 for c in _rgb(hex_color))
    return colorsys.rgb_to_hls(r, g, b)


def is_brand_like(hex_color: str) -> bool:
    """Saturated, mid-lightness colours are brand colours; greys/near-white/near-black aren't."""
    _, lightness, saturation = _hls(hex_color)
    return saturation > 0.28 and 0.18 < lightness < 0.85


def extract_colors(css_text: str) -> list[str]:
    # Theme-framework presets (WordPress block colours etc.) ship on every site; they aren't brand colours.
    css_text = PRESET_RE.sub("", css_text)
    found = [normalize_hex(m) for m in HEX_RE.findall(css_text)]
    for r, g, b in RGB_RE.findall(css_text):
        r, g, b = (min(255, int(x)) for x in (r, g, b))
        found.append(f"#{r:02X}{g:02X}{b:02X}")
    for h, s, l in HSL_RE.findall(css_text):
        r, g, b = colorsys.hls_to_rgb((float(h) % 360) / 360, min(100.0, float(l)) / 100, min(100.0, float(s)) / 100)
        found.append(f"#{int(r * 255):02X}{int(g * 255):02X}{int(b * 255):02X}")
    return found


def rank_stylesheets(urls: list[str]) -> list[str]:
    def score(u: str) -> int:
        name = urlparse(u).path.lower()
        s = 0
        if any(k in name for k in ("main", "site", "style", "theme", "app", "root", "global", "application", "brand", "custom")):
            s -= 2
        if any(k in name for k in ("reset", "normalize", "font", "icon", "plugin", "vendor", "print", "animate", "slick", "swiper")):
            s += 3
        return s

    return sorted(dict.fromkeys(urls), key=score)


def parse_html(html: str, base_url: str) -> ScrapedSite:
    soup = BeautifulSoup(html, "html.parser")
    site = ScrapedSite(url=base_url)

    def meta(*names: str) -> str:
        for n in names:
            tag = soup.find("meta", attrs={"property": n}) or soup.find("meta", attrs={"name": n})
            if tag and tag.get("content"):
                return tag["content"].strip()
        return ""

    site.title = (soup.title.string or "").strip() if soup.title and soup.title.string else ""
    site.site_name = meta("og:site_name", "application-name")
    site.description = meta("description", "og:description", "twitter:description")
    theme = meta("theme-color", "msapplication-TileColor")
    if theme and HEX_RE.fullmatch(theme.strip()):
        site.theme_color = normalize_hex(theme.strip())

    for tag in soup.find_all(["h1", "h2", "h3"], limit=20):
        text = " ".join(tag.get_text(" ", strip=True).split())
        if 3 < len(text) < 140 and text not in site.headings:
            site.headings.append(text)
    for tag in soup.find_all(["p", "li"]):
        text = " ".join(tag.get_text(" ", strip=True).split())
        if 60 <= len(text) <= 600 and text not in site.paragraphs:
            site.paragraphs.append(text)
        if len(site.paragraphs) >= 15:
            break

    addr = soup.find("address")
    if addr:
        site.address_hint = " ".join(addr.get_text(" ", strip=True).split())[:200]

    css_chunks = [s.get_text() for s in soup.find_all("style")]
    css_chunks += [t["style"] for t in soup.find_all(style=True)]
    colors = extract_colors("\n".join(css_chunks))
    if site.theme_color:
        colors = [site.theme_color] * 5 + colors  # an explicit theme-color is a strong signal
    site.colors = colors

    for link in soup.find_all("link", rel=True, href=True):
        rel = " ".join(link["rel"]).lower() if isinstance(link["rel"], list) else link["rel"].lower()
        if "stylesheet" in rel:
            site.stylesheets.append(urljoin(base_url, link["href"]))

    # Logo candidates, best first: a logo in the header/nav, then the touch icon, then other
    # "logo" images (unless there are many: that's a customer logo wall, not the brand).
    header_logos: list[str] = []
    other_logos: list[str] = []
    # A logo drawn as SVG right in the page ("<a class=header__logo><svg>…"): many shops have no logo file at all.
    for a in soup.find_all("a"):
        hay = " ".join([" ".join(a.get("class", [])), a.get("aria-label", ""), a.get("id", "")]).lower()
        svg = a.find("svg") if "logo" in hay else None
        if svg is not None and len(str(svg)) < 200_000:
            header_logos.append("data:image/svg+xml;utf8," + quote(str(svg)))
            break
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or ""
        if not src:
            continue
        hay = " ".join([src, img.get("alt", ""), " ".join(img.get("class", [])), img.get("id", "")]).lower()
        if "logo" not in hay and (product_finder.ICON_ALT.search(img.get("alt", "")) or
                                  product_finder.SKIP_IMG.search(src.lower().split("?")[0].rsplit("/", 1)[-1])):
            continue  # a cart, a "+", a heart: interface icons, not the brand's logo
        in_header = img.find_parent(["header", "nav"]) is not None
        home_link = img.find_parent("a", href=re.compile(r"^(/|\./|#?$|" + re.escape(base_url) + ")$"))
        if (in_header or home_link) and ("logo" in hay or home_link):
            header_logos.append(urljoin(base_url, src))
        elif "logo" in hay and _mentions_brand(hay, site, base_url):
            # Outside the header, a "logo" may be a partner's (payment, delivery, a pop-up
            # sponsor); only trust one that names this brand.
            other_logos.append(urljoin(base_url, src))
    logos: list[str] = header_logos[:2]
    touch_icons = [
        urljoin(base_url, link["href"])
        for link in soup.find_all("link", href=True)
        if "apple-touch-icon" in " ".join(link.get("rel") or []).lower()
    ]
    logos += touch_icons
    if len(other_logos) <= 3:
        logos += other_logos
    for rel in ("icon", "shortcut icon"):
        for link in soup.find_all("link", href=True):
            rels = link.get("rel") or []
            rels = " ".join(rels).lower() if isinstance(rels, list) else str(rels).lower()
            if rels == rel:
                logos.append(urljoin(base_url, link["href"]))
    og_image = meta("og:image")
    if og_image:
        logos.append(urljoin(base_url, og_image))
    site.logo_candidates = list(dict.fromkeys(logos))
    site.products = product_finder.extract_products(soup, base_url)
    site.images = product_finder.extract_site_images(soup, base_url)
    site.socials = social_platforms([a["href"] for a in soup.find_all("a", href=True)])
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    site.text = " ".join(soup.get_text(" ").split())[:30000]
    return site


SOCIAL_PLATFORMS = [("instagram", "instagram.com"), ("facebook", "facebook.com"), ("tiktok", "tiktok.com"),
                    ("youtube", "youtube.com"), ("x", "twitter.com"), ("x", "x.com"), ("pinterest", "pinterest."),
                    ("linkedin", "linkedin.com"), ("whatsapp", "wa.me"), ("whatsapp", "whatsapp.com"), ("snapchat", "snapchat.com")]


def social_platforms(hrefs: list[str]) -> list[str]:
    """Which social platforms a site links to (its footer icons, usually)."""
    found = []
    for href in hrefs:
        host = urlparse(href).netloc.lower().removeprefix("www.")
        for name, domain in SOCIAL_PLATFORMS:
            if host == domain or host.endswith("." + domain) or (domain.endswith(".") and host.startswith(domain)):
                found.append(name)
    return list(dict.fromkeys(found))


def service_claims(site: ScrapedSite) -> list[str]:
    """The service promises a site makes (delivery, returns, cash on delivery, instalments…)."""
    text = f"{site.description} {site.text}"
    return list(dict.fromkeys(label for rx, label in CLAIMS if label and re.search(rx, text, re.I)))


GENERIC_WORDS = {"shop", "store", "online", "official", "home", "with", "from", "page", "site", "website", "logo", "welcome"}


def _mentions_brand(hay: str, site: ScrapedSite, base_url: str) -> bool:
    host = urlparse(base_url).netloc.lower().removeprefix("www.").split(".")[0]
    words = re.findall(r"[a-z0-9]{4,}", f"{site.site_name} {site.title}".lower()) + [host, host.removesuffix("shop").removesuffix("store")]
    squashed = re.sub(r"[^a-z0-9]", "", hay)
    return any(w in squashed for w in set(words) - GENERIC_WORDS if len(w) >= 4)


def rank_palette(colors: list[str]) -> list[str]:
    counts = Counter(c for c in colors if is_brand_like(c))
    ranked: list[str] = []
    for color, _ in counts.most_common():
        # Skip near-duplicates of colours already chosen.
        if all(_distance(color, c) > 60 for c in ranked):
            ranked.append(color)
        if len(ranked) == 5:
            break
    return ranked


def _distance(a: str, b: str) -> float:
    return sum((x - y) ** 2 for x, y in zip(_rgb(a), _rgb(b))) ** 0.5


def dominant_colors_from_image(data: bytes, k: int = 5) -> list[str]:
    try:
        img = Image.open(io.BytesIO(data)).convert("RGBA")
    except Exception:  # noqa: BLE001
        return []
    img.thumbnail((96, 96))
    bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
    img = Image.alpha_composite(bg, img).convert("RGB")
    quant = img.quantize(colors=8)
    palette = quant.getpalette() or []
    counts = sorted(quant.getcolors() or [], reverse=True)
    total = img.width * img.height
    out = []
    for count, idx in counts:
        # Tiny clusters are anti-aliasing blends along edges, not colours the brand chose.
        if count / total < 0.02:
            continue
        r, g, b = palette[idx * 3 : idx * 3 + 3]
        out.append(f"#{r:02X}{g:02X}{b:02X}")
    return [c for c in out if is_brand_like(c)][:k]


def ink_color_from_image(data: bytes) -> str | None:
    """The logo's dark 'ink' colour (e.g. a charcoal wordmark), if it has a meaningful one."""
    try:
        img = Image.open(io.BytesIO(data)).convert("RGBA")
    except Exception:  # noqa: BLE001
        return None
    img.thumbnail((96, 96))
    bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
    img = Image.alpha_composite(bg, img).convert("RGB")
    quant = img.quantize(colors=8)
    palette = quant.getpalette() or []
    total = img.width * img.height
    for count, idx in sorted(quant.getcolors() or [], reverse=True):
        r, g, b = palette[idx * 3 : idx * 3 + 3]
        color = f"#{r:02X}{g:02X}{b:02X}"
        if count / total >= 0.04 and _hls(color)[1] < 0.3:
            return color
    return None


GENERIC_INDUSTRIES = {"E-commerce & Retail"}  # every online shop says "shop", "cart" and "sale"


_KEYWORD_RX: dict[str, re.Pattern] = {}


def _keyword(k: str) -> re.Pattern:
    """A keyword as a whole word, plurals and simple endings allowed: "law" matches "laws" but not
    "lawn" (a lawn suit isn't a law firm), "dress" matches "dresses"."""
    if k not in _KEYWORD_RX:
        _KEYWORD_RX[k] = re.compile(r"\b" + re.escape(k) + r"(?:s|es|ed|ing)?\b")
    return _KEYWORD_RX[k]


def guess_industry(text: str) -> str:
    text = text.lower()
    scores = {ind: sum(len(_keyword(k).findall(text)) for k in kws) for ind, kws in INDUSTRY_KEYWORDS.items()}
    specific = {ind: s for ind, s in scores.items() if ind not in GENERIC_INDUSTRIES and s > 0}
    if specific:
        return max(specific, key=specific.get)
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "Small Business"


def clean_name(site: ScrapedSite) -> str:
    """The brand's name: og:site_name, else the part of the page title that matches the domain
    ("Women Clothing | Khaadi Pakistan" on khaadi.com -> "Khaadi Pakistan"), else the shortest part."""
    if site.site_name:
        return site.site_name
    host = urlparse(site.url).netloc.lower().removeprefix("www.")
    labels = [lab for lab in host.split(".") if len(lab) >= 3 and lab not in ("com", "net", "org", "shop", "store")]
    if site.title:
        parts = [p.strip() for p in re.split(r"\s+[|–—-]\s+|:\s+", site.title) if p.strip()]
        if len(parts) > 1:
            matching = [p for p in parts if any(lab[:5] in re.sub(r"[^a-z0-9]", "", p.lower()) for lab in labels)]
            return min(matching or parts, key=len)[:60]
        return site.title[:60]
    return (labels[0] if labels else host).replace("-", " ").title()


# Ad and analytics tags that end up in links copied from ads and search results. They say nothing
# about the brand, and they made one site look like many.
TRACKING = re.compile(r"(?i)^(utm_[a-z]+|gclid|gbraid|wbraid|gad_source|gad_campaignid|srsltid|fbclid|msclkid|igshid|igsh|"
                      r"mc_cid|mc_eid|_ga|_gl|yclid|dclid|ttclid|twclid|li_fat_id|ref_src|si)$")


def clean_input(raw: str) -> str:
    """The website or handle as typed, minus tracking tags and the trailing "?" or "#" they leave."""
    raw = raw.strip()
    if raw.startswith("@") or "?" not in raw and "#" not in raw:
        return raw
    parts = urlparse(raw if re.match(r"^https?://", raw, re.I) else f"https://{raw}")
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not TRACKING.match(k)])
    cleaned = parts._replace(query=query, fragment="").geturl()
    return cleaned if re.match(r"^https?://", raw, re.I) else cleaned.removeprefix("https://")


def source_key(raw: str) -> str:
    """What makes two campaigns "the same brand": the site's address without www, tags or a trailing
    slash, or the handle."""
    if not raw.strip():
        return ""
    kind, value = detect_input(clean_input(raw))
    if kind == "handle":
        return "@" + value.lower()
    p = urlparse(value)
    return (p.netloc.lower().removeprefix("www.") + p.path.rstrip("/").lower() + (f"?{p.query}" if p.query else ""))


def detect_input(raw: str) -> tuple[str, str]:
    """Return (kind, normalized) where kind is 'website' or 'handle'."""
    raw = raw.strip()
    if raw.startswith("@"):
        return "handle", raw.lstrip("@")
    candidate = raw if re.match(r"^https?://", raw, re.I) else f"https://{raw}"
    host = urlparse(candidate).netloc.lower()
    if any(host.endswith(h) for h in SOCIAL_HOSTS):
        path = urlparse(candidate).path.strip("/").split("/")
        handle = path[-1] if path and path[-1] else host
        return "handle", handle.lstrip("@")
    if "." not in host or " " in raw:
        return "handle", raw.lstrip("@")
    return "website", candidate


# --------------------------------------------------------------------------- fetching


RETRY_STATUSES = {429, 502, 503, 504}
RETRY_DELAYS = (2.0, 5.0, 10.0)  # seconds to wait before each retry
MAX_RETRY_AFTER = 15.0


class SiteUnavailable(RuntimeError):
    """The website couldn't be read; the message is written for the user."""


async def get_page(client: httpx.AsyncClient, url: str) -> httpx.Response:
    """GET a page, waiting and retrying when the site rate-limits or is briefly down."""
    resp = None
    for attempt in range(len(RETRY_DELAYS) + 1):
        resp = await client.get(url)
        if resp.status_code not in RETRY_STATUSES or attempt == len(RETRY_DELAYS):
            break
        retry_after = resp.headers.get("retry-after", "")
        delay = float(retry_after) if retry_after.replace(".", "", 1).isdigit() else RETRY_DELAYS[attempt]
        await asyncio.sleep(min(delay, MAX_RETRY_AFTER))
    host = urlparse(url).netloc
    if resp.status_code == 429:
        raise SiteUnavailable(f"{host} is limiting requests right now (429 Too Many Requests). Wait a minute and try again.")
    if resp.status_code in (401, 403):
        raise SiteUnavailable(f"{host} blocked automated access ({resp.status_code}). Try the site's homepage, or create the campaign from its Instagram handle.")
    if resp.status_code == 404:
        raise SiteUnavailable(f"That page wasn't found on {host} (404). Check the link, or use the site's homepage.")
    if resp.status_code >= 400:
        raise SiteUnavailable(f"{host} returned an error ({resp.status_code}). Try again shortly, or use the site's homepage.")
    return resp


PAGE_CACHE_SECONDS = 600
# url -> (fetched at, html, final url). Re-running a campaign for the same site shouldn't hit
# it again: stores rate-limit bursts, and a second campaign right after the first is common.
_page_cache: dict[str, tuple[float, str, str]] = {}


async def fetch_html(client: httpx.AsyncClient, url: str) -> tuple[str, str]:
    hit = _page_cache.get(url)
    if hit and time.monotonic() - hit[0] < PAGE_CACHE_SECONDS:
        return hit[1], hit[2]
    try:
        resp = await get_page(client, url)
    except httpx.TimeoutException as exc:
        raise SiteUnavailable(f"{urlparse(url).netloc} took too long to respond. Try again shortly.") from exc
    except httpx.ConnectError as exc:
        raise SiteUnavailable(f"Couldn't connect to {urlparse(url).netloc}. Check the address.") from exc
    _page_cache[url] = (time.monotonic(), resp.text, str(resp.url))
    return resp.text, str(resp.url)


async def fetch_site(url: str, client: httpx.AsyncClient) -> ScrapedSite:
    html, final_url = await fetch_html(client, url)
    site = parse_html(html, final_url)
    if "cdn.shopify.com" in html or "Shopify.shop" in html:
        origin = f"{urlparse(site.url).scheme}://{urlparse(site.url).netloc}"
        # Shopify's public store info: name, city, country, currency and description.
        try:
            r = await client.get(f"{origin}/meta.json", timeout=8)
            if r.status_code == 200 and isinstance(r.json(), dict):
                site.shop = r.json()
                site.description = site.description or str(site.shop.get("description") or "")
        except (httpx.HTTPError, UnsafeURL, ValueError):
            pass
        if len(site.products) < 3:
            try:
                r = await client.get(f"{origin}/products.json?limit=24", timeout=8)
                if r.status_code == 200:
                    currency = product_finder.shopify_currency(html) or str(site.shop.get("currency") or "")
                    site.products = product_finder.shopify_products(r.json(), origin, currency) or site.products
            except (httpx.HTTPError, UnsafeURL, ValueError):
                pass
    elif product_finder.is_indolj(html):
        await read_indolj(site, html, client)
    return site


async def read_indolj(site: ScrapedSite, html: str, client: httpx.AsyncClient) -> None:
    """Restaurant sites on Indolj draw their menu in the browser, so the page itself has no
    dishes or photos. Ask the menu endpoint the page uses, with the page's own visitor token."""
    host = urlparse(site.url).netloc
    origin = f"{urlparse(site.url).scheme}://{host}"
    site.branches = product_finder.indolj_branches(html)
    try:
        r = await client.get(product_finder.INDOLJ_MENU_URL, params={"domain": host.removeprefix("www."), "json": 1},
                             headers={"Authorization": f"Bearer {product_finder.indolj_token(html)}", "Origin": origin,
                                      "Referer": origin + "/"}, timeout=12)
        if r.status_code == 200 and isinstance(r.json(), dict):
            menu = product_finder.indolj_products(r.json(), origin)
            if menu:
                site.products = menu
                site.images = list(dict.fromkeys([*site.images, *(p.image_url for p in menu)]))[:24]
    except (httpx.HTTPError, UnsafeURL, ValueError):
        pass
    cities = branch_cities(site.branches)
    if len(site.branches) >= 2:
        where = f" across {join_cities(cities)}" if cities else ""
        site.paragraphs.insert(0, f"{len(site.branches)} branches{where}.")
    if cities:
        site.address_hint = site.address_hint or cities[0]


CITIES = {"karachi": "Karachi", "lahore": "Lahore", "islamabad": "Islamabad", "rawalpindi": "Rawalpindi",
          "hyderabad": "Hyderabad", "faisalabad": "Faisalabad", "multan": "Multan", "peshawar": "Peshawar",
          "quetta": "Quetta", "sialkot": "Sialkot", "gujranwala": "Gujranwala", "sukkur": "Sukkur",
          "dubai": "Dubai", "abu dhabi": "Abu Dhabi", "sharjah": "Sharjah", "riyadh": "Riyadh", "jeddah": "Jeddah",
          "doha": "Doha", "london": "London", "manchester": "Manchester", "birmingham": "Birmingham",
          "toronto": "Toronto", "new york": "New York", "chicago": "Chicago", "mumbai": "Mumbai", "delhi": "Delhi",
          "bangalore": "Bangalore", "dhaka": "Dhaka", "sydney": "Sydney", "melbourne": "Melbourne"}


def branch_cities(branches: list[str]) -> list[str]:
    """Cities a chain is in, most branches first ("Karachi", "Lahore", "Hyderabad")."""
    counts = Counter(name for b in branches for key, name in CITIES.items() if re.search(rf"\b{key}\b", b.lower()))
    return [city for city, _ in counts.most_common()]


def join_cities(cities: list[str]) -> str:
    return cities[0] if len(cities) == 1 else f"{', '.join(cities[:3][:-1])} and {cities[:3][-1]}"


async def stylesheet_colors(site: ScrapedSite, client: httpx.AsyncClient) -> list[str]:
    """Colours from a few external stylesheets. Only needed when the logo doesn't give any,
    so a site isn't sent five extra requests it doesn't need to answer."""
    async def css(u: str) -> str:
        try:
            r = await client.get(u, timeout=6)
            return r.text[:400_000] if r.status_code == 200 else ""
        except (httpx.HTTPError, UnsafeURL):
            return ""

    sheets = await asyncio.gather(*(css(u) for u in rank_stylesheets(site.stylesheets)[:5]))
    return extract_colors("\n".join(sheets))


def darken_light_logo(img: Image.Image) -> Image.Image:
    """A white logo (made for a dark header) disappears on the white chip posts put logos on:
    draw it in near-black instead, keeping its shape."""
    rgba = img.convert("RGBA")
    alpha = rgba.getchannel("A")
    if not alpha.getbbox():
        return rgba
    solid = alpha.point(lambda a: 255 if a > 128 else 0)
    count = solid.histogram()[255]
    brightness = ImageStat.Stat(rgba.convert("L"), mask=solid).mean[0] if count else 0
    if count and brightness > 225 and count < rgba.width * rgba.height * 0.9:
        dark = Image.new("RGBA", rgba.size, (24, 24, 28, 255))
        dark.putalpha(alpha)
        return dark
    return rgba


GOOD_LOGO_SIDE = 120  # a logo this wide is sharp on a post
# Site icons, not logos: only used when the page offers nothing better.
SITE_ICON = re.compile(r"favicon|apple-touch-icon|\.ico(\?|$)|/icons?/|android-chrome|mstile", re.I)
SIZE_PARAM = re.compile(r"(?i)^(width|height|w|h|crop|size)$")


def larger_variant(url: str) -> str | None:
    """Image CDNs (Shopify and others) serve a logo at the size the page asked for: "…logo.png?width=32".
    The same address with a bigger width gives the same logo, sharp."""
    parts = urlparse(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)]
    sizes = [int(v) for k, v in query if k.lower() in ("width", "w") and v.isdigit()]
    if not sizes or max(sizes) >= 400:
        return None
    kept = [(k, v) for k, v in query if not SIZE_PARAM.match(k)] + [("width", "600")]
    return parts._replace(query=urlencode(kept)).geturl()


async def download_logo(candidates: list[str], client: httpx.AsyncClient, brand_id: str) -> tuple[str | None, str | None, bytes | None]:
    """The first candidate that is the brand's logo (candidates come best guess first), fetched at a
    sharp size where the image server allows it. Site icons (favicons) are passed over while a
    better candidate might follow, and used, the largest of them, only when nothing else works.
    A later candidate never replaces an earlier real logo just for being bigger: an inline SVG is
    always "big", and the page's decorative icons are SVGs too."""
    icons: list[tuple[int, str | None, Image.Image]] = []

    def keep(url: str | None, img: Image.Image) -> tuple[str | None, str | None, bytes | None]:
        path = config.MEDIA_DIR / f"logo_{brand_id}.png"
        img = darken_light_logo(img)
        img.save(path)
        buf = io.BytesIO()
        img.save(buf, "PNG")
        return url, str(path), buf.getvalue()

    async def fetch(url: str) -> bytes | None:
        r = await client.get(url, timeout=8)
        if r.status_code != 200 or len(r.content) < 200:
            return None
        return rasterize_svg(r.content) if is_svg(url, r.headers.get("content-type", ""), r.content) else r.content

    for url in candidates[:5]:
        try:
            if url.startswith("data:image/svg+xml;utf8,"):  # an inline SVG logo, read from the page itself
                data, url = rasterize_svg(unquote(url.split(",", 1)[1]).encode()), None
            else:
                big = larger_variant(url)
                data = (await fetch(big) if big else None) or await fetch(url)
                url = big if big and data else url
                if data is None:
                    continue
            img = Image.open(io.BytesIO(data))
            img.load()
            if min(img.size) < 32 and max(img.size) < 120:
                continue
            if url and SITE_ICON.search(url) and max(img.size) < GOOD_LOGO_SIDE:
                icons.append((img.width * img.height, url, img))
                continue
            return keep(url, img)
        except Exception:  # noqa: BLE001 - any broken image just means "try the next one"
            continue
    if icons:
        _, url, img = max(icons, key=lambda s: s[0])
        return keep(url, img)
    return (candidates[0] if candidates else None), None, None


MAX_SVG_BYTES = 1_000_000


def is_svg(url: str, content_type: str, data: bytes) -> bool:
    head = data[:300].lstrip().lower()
    return ("svg" in content_type.lower() or url.lower().split("?")[0].endswith(".svg")
            or head.startswith(b"<svg") or (head.startswith(b"<?xml") and b"<svg" in data[:2000].lower()))


def rasterize_svg(data: bytes, width: int = 800) -> bytes:
    """Render an SVG logo to PNG (many modern sites ship their logo only as SVG)."""
    import resvg_py

    if len(data) > MAX_SVG_BYTES:
        raise ValueError("SVG too large")
    png = resvg_py.svg_to_bytes(svg_string=data.decode("utf-8", errors="replace"), width=width)
    return bytes(png)


# --------------------------------------------------------------------------- LLM enrichment

EXTRACT_SYSTEM = """You are a brand analyst. From raw website text, extract a compact brand profile.
Return JSON with keys:
  "name": string, "tagline": string (<= 12 words), "industry": string (2-4 words),
  "location": string ("" if unknown; city/region only),
  "value_props": array of 3-5 short strings,
  "keywords": array of 5-8 SEO keywords a customer would search,
  "voice": string - 2 sentences describing how this brand talks (formality, energy, vocabulary)."""


async def enrich(kit: BrandKit, text: str) -> BrandKit:
    if not router.enabled or not text.strip():
        return kit
    try:
        data = await router.complete_json("brand_extract", EXTRACT_SYSTEM, text[:5000], temperature=0.2, max_tokens=700)
    except LLMError as exc:
        log.warning("brand extraction failed: %s", exc)
        return kit
    if not isinstance(data, dict):
        return kit
    kit.name = str(data.get("name") or kit.name)[:80]
    kit.tagline = str(data.get("tagline") or kit.tagline)[:140]
    kit.industry = str(data.get("industry") or kit.industry)[:60]
    kit.location = str(data.get("location") or kit.location)[:80]
    kit.value_props = [str(v)[:160] for v in (data.get("value_props") or kit.value_props)][:5]
    kit.keywords = [str(v)[:40] for v in (data.get("keywords") or kit.keywords)][:8]
    kit.brand_voice_prompt = str(data.get("voice") or kit.brand_voice_prompt)[:500]
    return kit


JUNK_TEXT = re.compile(
    r"\b(cart|checkout|log ?in|sign ?(in|up)|my account|wishlist|cookie|newsletter|subscribe|search|menu|not found|404|"
    r"shopping bag|added to|quick view|sold out|filter|sort by|javascript|your bag|is empty|loading|skip to)\b", re.I)
COUNTRY_TLDS = {"pk": "PK", "in": "IN", "ae": "AE", "sa": "SA", "bd": "BD", "uk": "GB", "ca": "CA", "au": "AU", "nz": "NZ",
                "ie": "IE", "de": "DE", "fr": "FR", "es": "ES", "it": "IT", "nl": "NL", "tr": "TR", "eg": "EG", "my": "MY",
                "sg": "SG", "id": "ID", "ph": "PH", "za": "ZA", "ng": "NG", "ke": "KE", "qa": "QA", "kw": "KW", "om": "OM", "bh": "BH"}
COUNTRY_WORDS = {"pakistan": "PK", "karachi": "PK", "lahore": "PK", "islamabad": "PK", "india": "IN", "mumbai": "IN",
                 "delhi": "IN", "dubai": "AE", "uae": "AE", "saudi": "SA", "riyadh": "SA", "bangladesh": "BD", "dhaka": "BD",
                 "united kingdom": "GB", "london": "GB", "manchester": "GB", "canada": "CA", "toronto": "CA", "australia": "AU",
                 "sydney": "AU", "melbourne": "AU", "new zealand": "NZ", "san francisco": "US", "los angeles": "US",
                 "new york": "US", "chicago": "US", "bay area": "US", "santa monica": "US", "brooklyn": "US", "seattle": "US", "austin": "US", "united states": "US"}
CURRENCY_COUNTRY = {"PKR": "PK", "₹": "IN", "INR": "IN", "AED": "AE", "SAR": "SA", "£": "GB", "GBP": "GB", "BDT": "BD"}
SEGMENT_WORDS = [("men", r"\bmen\b|\bmen's\b|\bmens\b|\bgents\b"), ("women", r"\bwomen\b|\bwomen's\b|\bladies\b|\bwomens\b"),
                 ("kids", r"\bkids?\b|\bchildren\b|\bboys\b|\bgirls\b|\btoddler|\bjunior\b|\bbaby\b|\binfant")]
CLAIMS = [(r"nationwide (?:delivery|shipping)|(?:delivery|shipping) (?:all )?across", "Nationwide delivery"),
          (r"free (?:delivery|shipping)", "Free delivery"), (r"same[- ]day delivery", "Same-day delivery"),
          (r"made (?:in[- ]house|from scratch|fresh daily)|baked (?:fresh|daily)", "Made fresh, in-house"),
          (r"cash on delivery|\bCOD\b", "Cash on delivery"), (r"easy (?:returns|exchange)|free returns|\d+[- ]day returns?", "Easy returns"),
          (r"warranty|guarantee", "Warranty"), (r"handmade|hand[- ]crafted", "Handmade"), (r"since (?:19|20)\d\d", None),
          (r"\b\d{2,4}\+? (?:stores|outlets|branches)(?: (?:across|in) [^.!?]{3,60})?", None), (r"installments?", "Pay in installments")]


def detect_country(kit: BrandKit, site: ScrapedSite, shop: dict | None = None) -> str:
    if shop and shop.get("country"):
        return str(shop["country"]).upper()[:2]
    host = urlparse(site.url or kit.website_url or "").netloc.lower()
    tld = host.rsplit(".", 1)[-1] if "." in host else ""
    if tld in COUNTRY_TLDS:
        return COUNTRY_TLDS[tld]
    text = f"{site.title} {site.description} {site.address_hint} {' '.join(site.paragraphs[:10])}".lower()
    for word, code in COUNTRY_WORDS.items():
        if re.search(rf"\b{re.escape(word)}\b", text):
            return code
    if re.search(r"\b[A-Z]{2}\s\d{5}(?:-\d{4})?\b", site.address_hint + " " + " ".join(site.paragraphs[:10])):
        return "US"  # a US state + ZIP code
    prices = " ".join(p.price for p in site.products)
    return next((code for cur, code in CURRENCY_COUNTRY.items() if cur in prices), "")


def detect_segments(site: ScrapedSite) -> list[str]:
    text = " ".join([site.description, *(p.name + " " + p.category for p in site.products), *site.headings[:20]]).lower()
    return [seg for seg, rx in SEGMENT_WORDS if re.search(rx, text)]


def first_sentence(text: str, max_words: int = 16) -> str:
    """The first sentence, never cut mid-word; longer ones are cut at a comma or word boundary."""
    s = re.split(r"(?<=[.!?])\s+", " ".join(text.split()))[0].strip()
    s = re.sub(r"^(discover|explore|shop|welcome to|browse)\s+", "", s, flags=re.I)
    words = s.split()
    if len(words) <= max_words:
        return s.rstrip(" ,;:.")
    cut = " ".join(words[:max_words])
    return (cut.rsplit(",", 1)[0] if "," in cut else cut).rstrip(" ,;:.") + "…"


def title_description(site: ScrapedSite, name: str) -> str:
    """The descriptive part of a page title ("Brand – Fresh bread baked daily"), if any."""
    parts = [p.strip() for p in re.split(r"\s+[|–—-]\s+", site.title or "") if p.strip()]
    return next((p for p in parts if name.lower() not in p.lower() and len(p.split()) >= 3 and not JUNK_TEXT.search(p)), "")


def tagline_from(site: ScrapedSite, name: str) -> str:
    """A short, real line about the brand: the title's descriptive part, else the description's
    first clause, else a heading that isn't page furniture ("Your cart is empty")."""
    for text in (title_description(site, name), site.description):
        if text and not JUNK_TEXT.search(first_sentence(text)):
            return first_sentence(text)
    return next((h for h in site.headings if not JUNK_TEXT.search(h) and len(h.split()) >= 2), "")


NOT_OFFERINGS = re.compile(r"^(home|welcome|who we are|about|contact|faq|locations?|shop|menu|news|blog|careers|stories|"
                           r"our story|happenings|follow|subscribe|gallery)\b", re.I)


def offerings_from(site: ScrapedSite, name: str) -> list[str]:
    """What a business offers, from short headings ("SPECIAL ORDER CAKES", "Gift Cards"), for sites
    that don't list products with prices."""
    out = []
    brand_words = [w for w in re.findall(r"[a-z]{4,}", name.lower()) if w not in GENERIC_WORDS | {"bakery", "cafe", "studio"}]
    for h in site.headings:
        words = h.split()
        # "Tartine Happenings", "Tartine at home": sections about the brand, not things it sells.
        if not (1 <= len(words) <= 5) or JUNK_TEXT.search(h) or NOT_OFFERINGS.search(h) \
                or any(w in h.lower() for w in brand_words) or h.endswith((".", "?", "!", ":")):
            continue
        h = product_finder.strip_codes(h)
        if h:
            out.append(h[0].upper() + h[1:].lower() if h.isupper() else h)
    return list(dict.fromkeys(out))[:6]


def value_props_from(site: ScrapedSite) -> list[str]:
    text = f"{site.description} {' '.join(site.paragraphs[:8])}"
    sentences: list[str] = []
    for sentence in re.split(r"(?<=[.!?])\s+", site.description.strip()):
        sentence = re.sub(r"^(discover|explore|shop online or|welcome to|browse)\s+", "", sentence.strip(), flags=re.I).rstrip(".")
        if 4 <= len(sentence.split()) <= 30 and not JUNK_TEXT.search(sentence) and not sentence.lower().startswith(("shop", "visit")) \
                and not product_finder.looks_like_menu(sentence):
            sentences.append(sentence[0].upper() + sentence[1:])
    claims: list[str] = []
    for rx, label in CLAIMS:
        m = re.search(rx, text, re.I)
        if m:
            claims.append(label or m.group(0)[0].upper() + m.group(0)[1:])
    return list(dict.fromkeys(sentences + claims))[:5]


def heuristic_kit(site: ScrapedSite, kit: BrandKit) -> BrandKit:
    blob = site.text_blob()
    kit.industry = kit.industry or guess_industry(blob)
    site.description = site.description or title_description(site, kit.name)
    kit.tagline = kit.tagline if kit.tagline and not JUNK_TEXT.search(kit.tagline) else tagline_from(site, kit.name)
    kit.description = site.description or (site.paragraphs[0] if site.paragraphs else "")
    kit.segments = kit.segments or detect_segments(site)
    if not site.products:
        kit.offerings = kit.offerings or offerings_from(site, kit.name)
    if not kit.value_props:
        kit.value_props = value_props_from(site) or [first_sentence(p) for p in site.paragraphs[:3] if not JUNK_TEXT.search(p) and not product_finder.looks_like_menu(p)]
    if not kit.keywords:
        words = re.findall(r"[a-zA-Z]{5,}", blob.lower())
        stop = {"about", "their", "there", "which", "would", "these", "other", "every", "where", "while", "cookies",
                "product", "products", "price", "prices", "piece", "pieces", "table", "ready", "items", "select", "sizes",
                "added", "account", "shipping", "login", "search", "close", "cart", "checkout", "wishlist", "filter", "sort"}
        kit.keywords = [w for w, _ in Counter(w for w in words if w not in stop).most_common(8)]
    kit.brand_voice_prompt = kit.brand_voice_prompt or (
        f"Friendly, confident and specific. Talks like a local {kit.industry.lower()} owner who knows their customers by name."
    )
    return kit


def _tint(hex_color: str, lightness: float) -> str:
    h, _, s = _hls(hex_color)
    r, g, b = colorsys.hls_to_rgb(h, lightness, s)
    return f"#{int(r * 255):02X}{int(g * 255):02X}{int(b * 255):02X}"


def choose_palette(theme_color: str | None, logo_colors: list[str], css_colors: list[str]) -> list[str]:
    """The logo is the most reliable statement of a brand's colours; page CSS often belongs to
    the store platform or theme (a Salesforce blue, a WordPress preset). CSS is used only when
    neither an explicit theme-color nor the logo gives a brand colour."""
    preferred = ([theme_color] if theme_color and is_brand_like(theme_color) else []) + logo_colors
    candidates = preferred if preferred else rank_palette(css_colors)
    palette: list[str] = []
    for c in candidates:
        if not all(_distance(c, p) > 60 for p in palette):
            continue
        # In a logo, a darker or paler version of a chosen colour is shading or edge blending
        # (e.g. where a dark wordmark overlaps a coloured shape), not a second brand colour.
        if preferred and any(_hue_gap(c, p) < 0.04 for p in palette):
            continue
        palette.append(c)
    return palette[:5]


def _hue_gap(a: str, b: str) -> float:
    d = abs(_hls(a)[0] - _hls(b)[0])
    return min(d, 1 - d)


def apply_palette(kit: BrandKit, palette: list[str], ink: str | None = None) -> BrandKit:
    if palette:
        kit.palette = palette
        kit.primary_color = palette[0]
        # A one-colour brand gets a light tint of its own colour as the accent, not a stranger.
        kit.accent_color = palette[1] if len(palette) > 1 else _tint(palette[0], 0.8)
    # Secondary is used for text panels: the logo's own dark ink if it has one, else a deep shade of the primary.
    if ink:
        kit.secondary_color = ink
    else:
        h, l, s = _hls(kit.primary_color)
        r, g, b = colorsys.hls_to_rgb(h, 0.14, min(0.6, s))
        kit.secondary_color = f"#{int(r * 255):02X}{int(g * 255):02X}{int(b * 255):02X}"
    return kit


# --------------------------------------------------------------------------- entry point


def handle_name(handle: str) -> str:
    """"the_bake_shop" -> "The Bake Shop": a readable name until a real one is found. A handle with
    numbers in it isn't made of words ("fitt.ote0" isn't "Fitt Ote0"), so it stays as written."""
    if re.search(r"\d", handle):
        return "@" + handle.lstrip("@")
    return " ".join(w[:1].upper() + w[1:] for w in re.split(r"[._]+", handle) if w) or handle


def site_belongs_to(handle: str, url: str, site: "ScrapedSite") -> bool:
    """A search result is only this brand's site if it says so: its address carries the handle's
    name, or the page mentions the handle. (Searching "fitt.ote0" found fitt.com, someone else.)"""
    compact = re.sub(r"[^a-z0-9]", "", handle.lower())
    host = urlparse(url).netloc.lower().removeprefix("www.").split(".")[0]
    core = re.sub(r"[^a-z0-9]", "", host)
    text = f"{site.title} {site.description} {site.text}".lower()
    if handle.lower() in text or f"@{handle.lower()}" in text:
        return True
    return bool(core) and (core == compact or (core in compact and len(core) >= 0.8 * len(compact)) or compact in core)


async def keep_instagram_photos(urls: list[str], client: httpx.AsyncClient) -> list[str]:
    """Instagram's photo links stop working after a few days, so the photos are saved at import."""
    from ..agents.photos import keep_photo

    async def one(url: str) -> str | None:
        try:
            resp = await client.get(url)
            resp.raise_for_status()
        except (httpx.HTTPError, UnsafeURL):
            return None
        return await asyncio.to_thread(keep_photo, resp.content, "ig")

    saved = await asyncio.gather(*(one(u) for u in urls[:12]))
    return [s for s in saved if s]


async def kit_from_instagram(profile, raw_input: str, client: httpx.AsyncClient) -> BrandKit:
    """A brand kit from the brand's own Instagram profile, plus its website when the bio links one."""
    kit = BrandKit(source_input=raw_input, source_type="handle", name=profile.full_name or handle_name(profile.username))
    photos = await keep_instagram_photos([u for u, _ in profile.posts], client)
    text = profile.text()
    if profile.website:
        try:
            site = await fetch_site(profile.website, client)
            kit.website_url = site.url
            kit = await _finish_site_kit(kit, site, client, extra_text=text)
            kit.images = list(dict.fromkeys(photos + kit.images))[:24]
            if not kit.logo_path and profile.picture:
                kit.logo_url, kit.logo_path, _ = await download_logo([profile.picture], client, kit.id)
            kit.description = kit.description or profile.bio
            return kit
        except (httpx.HTTPError, UnsafeURL, SiteUnavailable) as exc:
            log.info("@%s's website couldn't be read (%s); using the profile alone", profile.username, exc)
    site = ScrapedSite(url=f"https://www.instagram.com/{profile.username}/", title=kit.name, description=profile.bio,
                       paragraphs=[c for _, c in profile.posts if len(c) > 30][:10], images=photos, text=text[:4000])
    logo_task = download_logo([profile.picture] if profile.picture else [], client, kit.id)
    (logo_url, logo_path, logo_bytes), kit = await asyncio.gather(logo_task, enrich(kit, text))
    kit.logo_url, kit.logo_path = logo_url, logo_path
    kit.images = photos[:24]
    kit.description = profile.bio or kit.description
    logo_colors = dominant_colors_from_image(logo_bytes) if logo_bytes else []
    kit = apply_palette(kit, choose_palette(None, logo_colors, []), ink=ink_color_from_image(logo_bytes) if logo_colors else None)
    return heuristic_kit(site, kit)


async def ingest(raw_input: str, search_fn=None) -> BrandKit:
    """search_fn(query) -> list[TrendItem]; used to research social handles."""
    from . import instagram

    kind, value = detect_input(raw_input)
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"}
    async with safe_client(headers=headers, follow_redirects=True, timeout=12) as client:
        if kind == "handle":
            ig = instagram.instagram_handle(raw_input) or (value if instagram.HANDLE.match(value) else None)
            profile = await instagram.read_profile(ig) if ig else None
            if profile:
                return await kit_from_instagram(profile, raw_input, client)
            kit = BrandKit(source_input=raw_input, source_type="handle", name=handle_name(value))
            research = ""
            if search_fn:
                results = await search_fn(f"{value} business official website about")
                research = "\n".join(f"{r.title}: {r.snippet}" for r in results)
                for r in results[:4]:
                    if not r.url or any(h in r.url for h in SOCIAL_HOSTS):
                        continue
                    try:
                        site = await fetch_site(r.url, client)
                    except (httpx.HTTPError, UnsafeURL, SiteUnavailable):
                        continue
                    if site_belongs_to(value, r.url, site):
                        kit.website_url = site.url
                        return await _finish_site_kit(kit, site, client, extra_text=research)
                    log.info("search result %s isn't @%s's site; skipped", r.url, value)
            kit.description = research[:400]
            kit = heuristic_kit(ScrapedSite(url="", description=research), kit)
            kit = apply_palette(kit, [])
            return await enrich(kit, f"Handle: @{value}\n{research}")

        site = await fetch_site(value, client)
        kit = BrandKit(source_input=raw_input, source_type="website", website_url=site.url, name=clean_name(site))
        return await _finish_site_kit(kit, site, client)


async def _finish_site_kit(kit: BrandKit, site: ScrapedSite, client: httpx.AsyncClient, extra_text: str = "") -> BrandKit:
    if not kit.name or kit.source_type == "website":
        kit.name = clean_name(site)
    logo_task = download_logo(site.logo_candidates, client, kit.id)
    enrich_task = enrich(kit, site.text_blob() + "\n" + extra_text)
    (logo_url, logo_path, logo_bytes), kit = await asyncio.gather(logo_task, enrich_task)
    kit.logo_url, kit.logo_path = logo_url, logo_path
    kit.products, kit.images = site.products, site.images
    kit.country = detect_country(kit, site, site.shop)
    cities = branch_cities(site.branches)
    if not kit.location and cities:
        kit.location = f"{cities[0]}, {COUNTRY_NAMES.get(kit.country, kit.country).removeprefix('the ')}".strip(", ")
    if not kit.location and site.shop.get("city"):
        country = str(site.shop.get("country") or "")
        kit.location = f"{site.shop['city']}, {COUNTRY_NAMES.get(country, country).removeprefix('the ')}".strip(", ")

    logo_colors = dominant_colors_from_image(logo_bytes) if logo_bytes else []
    if not logo_colors and not (site.theme_color and is_brand_like(site.theme_color)):
        site.colors += await stylesheet_colors(site, client)
    palette = choose_palette(site.theme_color, logo_colors, site.colors)
    kit = apply_palette(kit, palette, ink=ink_color_from_image(logo_bytes) if logo_bytes and logo_colors else None)
    return heuristic_kit(site, kit)
