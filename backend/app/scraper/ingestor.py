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
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from PIL import Image

from .. import config
from ..llm import LLMError, router
from ..netguard import UnsafeURL, safe_client
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
    "Fashion & Apparel": ["dress", "kurta", "dupatta", "shirt", "jeans", "apparel", "clothing", "fashion", "unstitched",
                          "ready to wear", "co-ord", "embroidered", "trousers", "abaya", "shalwar", "sneakers", "jacket"],
    "Food & Beverage": ["restaurant", "cafe", "coffee", "bakery", "menu", "pizza", "kitchen", "dining", "brunch"],
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
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or ""
        if not src:
            continue
        hay = " ".join([src, img.get("alt", ""), " ".join(img.get("class", [])), img.get("id", "")]).lower()
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
    return site


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


def guess_industry(text: str) -> str:
    text = text.lower()
    scores = {ind: sum(text.count(k) for k in kws) for ind, kws in INDUSTRY_KEYWORDS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "Small Business"


def clean_name(site: ScrapedSite) -> str:
    if site.site_name:
        return site.site_name
    if site.title:
        for sep in (" | ", " - ", " – ", " — ", ": "):
            if sep in site.title:
                parts = [p.strip() for p in site.title.split(sep) if p.strip()]
                return min(parts, key=len)
        return site.title[:60]
    host = urlparse(site.url).netloc.removeprefix("www.")
    return host.split(".")[0].replace("-", " ").title()


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
    if len(site.products) < 3 and ("cdn.shopify.com" in html or "Shopify.shop" in html):
        origin = f"{urlparse(site.url).scheme}://{urlparse(site.url).netloc}"
        try:
            r = await client.get(f"{origin}/products.json?limit=24", timeout=8)
            if r.status_code == 200:
                site.products = product_finder.shopify_products(r.json(), origin, product_finder.shopify_currency(html)) or site.products
        except (httpx.HTTPError, UnsafeURL, ValueError):
            pass
    return site


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


async def download_logo(candidates: list[str], client: httpx.AsyncClient, brand_id: str) -> tuple[str | None, str | None, bytes | None]:
    for url in candidates[:5]:
        try:
            r = await client.get(url, timeout=8)
            if r.status_code != 200 or len(r.content) < 200:
                continue
            data = r.content
            if is_svg(url, r.headers.get("content-type", ""), data):
                data = rasterize_svg(data)
            img = Image.open(io.BytesIO(data))
            img.load()
            if min(img.size) < 32:
                continue
            path = config.MEDIA_DIR / f"logo_{brand_id}.png"
            img.convert("RGBA").save(path)
            return url, str(path), data
        except Exception:  # noqa: BLE001 - any broken image just means "try the next one"
            continue
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


def heuristic_kit(site: ScrapedSite, kit: BrandKit) -> BrandKit:
    blob = site.text_blob()
    kit.industry = kit.industry or guess_industry(blob)
    kit.tagline = kit.tagline or (site.headings[0] if site.headings else site.description[:100])
    kit.description = site.description or (site.paragraphs[0] if site.paragraphs else "")
    if not kit.value_props:
        lines = list(dict.fromkeys(p.category or p.name for p in site.products))[:5]
        kit.value_props = lines or [h for h in site.headings[1:6]] or [p[:120] for p in site.paragraphs[:3]]
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


async def ingest(raw_input: str, search_fn=None) -> BrandKit:
    """search_fn(query) -> list[TrendItem]; used to research social handles."""
    kind, value = detect_input(raw_input)
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"}
    async with safe_client(headers=headers, follow_redirects=True, timeout=12) as client:
        if kind == "handle":
            kit = BrandKit(source_input=raw_input, source_type="handle", name=value.replace("_", " ").title())
            research = ""
            if search_fn:
                results = await search_fn(f"{value} business official website about")
                research = "\n".join(f"{r.title}: {r.snippet}" for r in results)
                site_url = next(
                    (r.url for r in results if r.url and not any(h in r.url for h in SOCIAL_HOSTS)), None
                )
                if site_url:
                    try:
                        site = await fetch_site(site_url, client)
                        kit.website_url = site.url
                        return await _finish_site_kit(kit, site, client, extra_text=research)
                    except (httpx.HTTPError, UnsafeURL, SiteUnavailable):
                        pass
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

    logo_colors = dominant_colors_from_image(logo_bytes) if logo_bytes else []
    if not logo_colors and not (site.theme_color and is_brand_like(site.theme_color)):
        site.colors += await stylesheet_colors(site, client)
    palette = choose_palette(site.theme_color, logo_colors, site.colors)
    kit = apply_palette(kit, palette, ink=ink_color_from_image(logo_bytes) if logo_bytes and logo_colors else None)
    return heuristic_kit(site, kit)
