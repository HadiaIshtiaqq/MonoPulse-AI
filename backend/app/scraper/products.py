"""Real products and photos from a business website.

Reads, in order of reliability: schema.org JSON-LD and microdata, product data embedded in
data-* attributes (analytics payloads most store platforms render on each product tile), and
finally generic product cards (an image link next to a price). Also collects the site's own
photos for brands that don't sell products online.
"""
from __future__ import annotations

import json
import re
from collections import deque
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from ..schemas import Product

CURRENCY = r"(?:Rs\.?|PKR|INR|USD|US\$|CAD|AUD|NZD|AED|SAR|EUR|GBP|[$£€₹])"
PRICE_RE = re.compile(rf"{CURRENCY}\s?\d[\d,]*(?:\.\d{{1,2}})?|\d[\d,]*(?:\.\d{{1,2}})?\s?(?:PKR|USD|EUR|GBP|AED|€)", re.I)
# Attributes that hold a full-size image, best first. Store themes put the big image in data-*.
LARGE_ATTRS = ("data-large-0", "data-hi-res-0", "data-zoom-image", "data-zoom", "data-full", "data-large", "data-original")
IMG_ATTRS = ("data-lazy-src", "data-src", "src")
SKIP_IMG = re.compile(r"logo|icon|sprite|avatar|badge|payment|flag|placeholder|spinner|loader|pixel|blank|transparent|banner-ad|rating|star", re.I)
BG_URL_RE = re.compile(r"background(?:-image)?\s*:[^;]*url\(\s*['\"]?([^'\")]+)")
MAX_PRODUCTS = 24
MAX_IMAGES = 16


def _usable(url: str) -> bool:
    low = url.lower().split("?")[0]
    return bool(url) and not url.startswith("data:") and not low.endswith((".svg", ".gif", ".ico")) and not SKIP_IMG.search(low.rsplit("/", 1)[-1])


def _largest_from_srcset(srcset: str) -> str:
    best, best_w = "", -1
    for part in srcset.split(","):
        bits = part.strip().split()
        if not bits:
            continue
        w = 0
        if len(bits) > 1 and bits[1][:-1].replace(".", "").isdigit():
            w = int(float(bits[1][:-1]) * (1000 if bits[1].endswith("x") else 1))
        if w > best_w:
            best, best_w = bits[0], w
    return best


def image_of(tag: Tag, base: str) -> str:
    """Best full-size image URL in an element (itself or anything inside it)."""
    nodes = [tag, *tag.find_all(True)]
    for node in nodes:
        for attr in LARGE_ATTRS:
            val = node.get(attr)
            if isinstance(val, str) and _usable(val):
                return urljoin(base, val)
    for node in nodes:
        if node.name not in ("img", "source"):
            continue
        for attr in ("data-srcset", "srcset"):
            val = node.get(attr)
            if isinstance(val, str) and val.strip():
                src = _largest_from_srcset(val)
                if _usable(src):
                    return urljoin(base, src)
        for attr in IMG_ATTRS:
            val = node.get(attr)
            if isinstance(val, str) and _usable(val):
                return urljoin(base, val)
    return ""


def _link_of(tag: Tag, base: str) -> str:
    for a in ([tag] if tag.name == "a" else []) + tag.find_all("a", href=True):
        href = a.get("href") or ""
        if href and not href.startswith(("#", "javascript:", "mailto:", "tel:")):
            return urljoin(base, href)
    return ""


def format_price(amount, currency: str = "") -> str:
    try:
        value = float(str(amount).replace(",", ""))
    except ValueError:
        return ""
    if value <= 0:
        return ""
    text = f"{value:,.0f}" if value == int(value) else f"{value:,.2f}"
    symbol = {"USD": "$", "GBP": "£", "EUR": "€"}.get(currency.upper(), "")
    return f"{symbol}{text}" if symbol else (f"{currency.upper()} {text}" if currency else "")


def _clean(text: str, limit: int = 120) -> str:
    return " ".join(str(text or "").split())[:limit]


# --------------------------------------------------------------------------- JSON-LD / microdata


def _ld_image(value) -> str:
    if isinstance(value, list):
        value = value[0] if value else ""
    if isinstance(value, dict):
        value = value.get("url") or value.get("contentUrl") or ""
    return str(value or "")


def _ld_price(offers) -> str:
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    if not isinstance(offers, dict):
        return ""
    amount = offers.get("price") or offers.get("lowPrice")
    if amount is None and isinstance(offers.get("priceSpecification"), dict):
        amount = offers["priceSpecification"].get("price")
    return format_price(amount, str(offers.get("priceCurrency") or "")) if amount is not None else ""


def jsonld_products(soup: BeautifulSoup, base: str) -> list[Product]:
    out = []
    for script in soup.find_all("script", type=re.compile("ld\\+json", re.I)):
        try:
            data = json.loads(script.string or script.get_text() or "")
        except ValueError:
            continue
        queue = deque([data])
        while queue:
            node = queue.popleft()
            if isinstance(node, list):
                queue.extend(node)
                continue
            if not isinstance(node, dict):
                continue
            types = node.get("@type")
            types = types if isinstance(types, list) else [types]
            if "Product" in types and node.get("name"):
                image = _ld_image(node.get("image"))
                out.append(Product(name=_clean(node["name"]), price=_ld_price(node.get("offers")),
                                   url=urljoin(base, str(node.get("url") or "")) if node.get("url") else "",
                                   image_url=urljoin(base, image) if image else "", category=_clean(node.get("category") or "", 60)))
            for key in ("@graph", "itemListElement", "item", "mainEntity"):
                if key in node:
                    queue.append(node[key])
    return out


def microdata_products(soup: BeautifulSoup, base: str) -> list[Product]:
    out = []
    for el in soup.find_all(attrs={"itemtype": re.compile(r"schema\.org/Product$", re.I)}):
        def prop(name: str) -> Tag | None:
            return el.find(attrs={"itemprop": name})

        name = prop("name")
        if not name:
            continue
        price, currency = prop("price"), prop("priceCurrency")
        amount = (price.get("content") or price.get_text(strip=True)) if price else ""
        cur = (currency.get("content") or currency.get_text(strip=True)) if currency else ""
        img = prop("image")
        image = (img.get("content") or img.get("src") or img.get("href") or "") if img else image_of(el, base)
        out.append(Product(name=_clean(name.get("content") or name.get_text(" ", strip=True)),
                           price=format_price(amount, cur) or _displayed_price(el),
                           url=_link_of(el, base), image_url=urljoin(base, image) if image else ""))
    return out


# --------------------------------------------------------------------------- data-* payloads and cards


def _displayed_price(el: Tag) -> str:
    m = PRICE_RE.search(el.get_text(" ", strip=True))
    return " ".join(m.group(0).split()) if m else ""


def data_attr_products(soup: BeautifulSoup, base: str) -> list[Product]:
    out = []
    for el in soup.find_all(True):
        for attr, val in el.attrs.items():
            if not (attr.startswith("data-") and isinstance(val, str) and val.lstrip().startswith("{")):
                continue
            if '"name"' not in val or "price" not in val:
                continue
            try:
                data = json.loads(val)
            except ValueError:
                continue
            if not isinstance(data, dict) or not data.get("name"):
                continue
            out.append(Product(name=_clean(data["name"]), price=_displayed_price(el) or format_price(data.get("price"), str(data.get("currency") or "")),
                               url=_link_of(el, base), image_url=image_of(el, base), category=_clean(data.get("category") or "", 60)))
            break
    return out


COLOR_WORDS = {"black", "white", "brown", "tan", "beige", "navy", "blue", "red", "green", "grey", "gray", "pink", "maroon",
               "olive", "mustard", "camel", "khaki", "cream", "off white", "silver", "gold", "purple", "orange", "yellow", "multi"}
TITLE_CLASS = re.compile(r"title|name|heading", re.I)
SALE_RE = re.compile(rf"(?:sale\s*price|now)?\s*({PRICE_RE.pattern})\s*(?:regular\s*price|was|original\s*price)\s*({PRICE_RE.pattern})", re.I)


def is_label_not_name(text: str) -> bool:
    """Image alt texts are often a colour or a size ("Brown", "Black / 42"), not the product's name."""
    low = re.sub(r"[^a-z ]", " ", text.lower()).split()
    return not low or all(w in COLOR_WORDS or w in {"and", "with", "size"} for w in low) or len(text) < 3


def _card_name(card: Tag, link: Tag, img: Tag) -> str:
    candidates = [link.get("title") or ""]
    for el in card.find_all(class_=TITLE_CLASS):
        candidates.append(el.get_text(" ", strip=True))
    candidates += [a.get_text(" ", strip=True) for a in card.find_all("a", href=link["href"])]
    candidates.append(img.get("alt") or "")
    for c in candidates:
        c = _clean(c)
        if c and not PRICE_RE.fullmatch(c) and not is_label_not_name(c) and len(c) <= 120:
            return c
    return ""


def sale_prices(text: str) -> tuple[str, str]:
    """(price now, regular price) from a card's text; regular price is "" when it isn't on sale."""
    m = SALE_RE.search(text)
    if m:
        now, was = (" ".join(g.split()) for g in (m.group(1), m.group(2)))
        if now != was:
            return now, was
    m = PRICE_RE.search(text)
    return (" ".join(m.group(0).split()) if m else ""), ""


def card_products(soup: BeautifulSoup, base: str) -> list[Product]:
    """Generic fallback: an image inside a link whose surrounding card shows a price."""
    out = []
    for img in soup.find_all("img"):
        link = img.find_parent("a", href=True)
        if not link:
            continue
        card, text = link, ""
        for _ in range(5):
            text = card.get_text(" ", strip=True)
            if PRICE_RE.search(text) or card.parent is None or len(text) > 600:
                break
            card = card.parent
        if not PRICE_RE.search(text) or len(text) > 2000:
            continue
        name = _card_name(card, link, img)
        image = image_of(img, base)
        if name and image:
            price, was = sale_prices(text)
            out.append(Product(name=name, price=price, was_price=was, url=urljoin(base, link["href"]), image_url=image))
    return out


def shopify_products(data: dict, origin: str, currency: str = "") -> list[Product]:
    out = []
    for p in (data.get("products") or [])[:MAX_PRODUCTS]:
        if not isinstance(p, dict) or not p.get("title"):
            continue
        variants = p.get("variants") or [{}]
        images = p.get("images") or [{}]
        was = variants[0].get("compare_at_price")
        on_sale = was and currency and _amount(was) > _amount(variants[0].get("price"))
        out.append(Product(name=_clean(p["title"]), price=format_price(variants[0].get("price"), currency) if currency else "",
                           was_price=format_price(was, currency) if on_sale else "",
                           url=f"{origin}/products/{p.get('handle', '')}", image_url=str(images[0].get("src") or ""),
                           category=_clean(p.get("product_type") or "", 60)))
    return out


def _amount(value) -> float:
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def shopify_currency(html: str) -> str:
    m = re.search(r'Shopify\.currency\s*=\s*\{\s*"active"\s*:\s*"(\w{3})"', html)
    return m.group(1) if m else ""


def extract_products(soup: BeautifulSoup, base: str) -> list[Product]:
    found: list[Product] = []
    for finder in (jsonld_products, microdata_products, data_attr_products):
        found += finder(soup, base)
    if len(found) < 3:
        found += card_products(soup, base)
    seen, out = set(), []
    for p in found:
        # A product page linked twice (two images in one card) is still one product.
        key = p.url.split("?")[0] if p.url else (p.name.lower(), p.image_url)
        if len(p.name) < 2 or key in seen:
            continue
        seen.add(key)
        out.append(p)
    out.sort(key=lambda p: (not p.image_url, not p.price))
    return out[:MAX_PRODUCTS]


# --------------------------------------------------------------------------- site photos


def extract_site_images(soup: BeautifulSoup, base: str) -> list[str]:
    """The site's own photos (hero images, galleries), skipping logos, icons and chrome."""
    urls: list[str] = []
    for prop in ("og:image", "twitter:image"):
        tag = soup.find("meta", attrs={"property": prop}) or soup.find("meta", attrs={"name": prop})
        if tag and tag.get("content") and _usable(tag["content"]):
            urls.append(urljoin(base, tag["content"]))
    for tag in soup.find_all(["img", "source"]):
        if tag.find_parent(["header", "nav", "footer"]):
            continue
        hay = " ".join([tag.get("alt", ""), " ".join(tag.get("class", [])), tag.get("id", "")])
        if SKIP_IMG.search(hay):
            continue
        width = str(tag.get("width") or "")
        if width.isdigit() and int(width) < 300:
            continue
        src = image_of(tag, base)
        if src:
            urls.append(src)
    for el in soup.find_all(style=BG_URL_RE):
        m = BG_URL_RE.search(el["style"])
        if m and _usable(m.group(1)):
            urls.append(urljoin(base, m.group(1)))
    return list(dict.fromkeys(urls))[:MAX_IMAGES]
