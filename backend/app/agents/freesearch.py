"""Keyless web search, used whenever Tavily isn't configured or fails.

News: Google News RSS. Web and social: DuckDuckGo's HTML endpoint. Full page text: our own
SSRF-guarded fetch. All free and key-less, so trends, research and handle lookup always work.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qs, unquote, urlparse

import httpx
from bs4 import BeautifulSoup

from ..netguard import UnsafeURL, safe_client

log = logging.getLogger(__name__)

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
      "Accept-Language": "en-US,en;q=0.9"}
_cache: dict[str, tuple[float, list[dict]]] = {}
_TTL = 15 * 60
_ddg_lock = asyncio.Lock()  # one DuckDuckGo request at a time keeps us under its rate limit


def _cached(key: str) -> list[dict] | None:
    hit = _cache.get(key)
    return hit[1] if hit and time.time() - hit[0] < _TTL else None


def _clean(html: str) -> str:
    return re.sub(r"\s+", " ", BeautifulSoup(html or "", "html.parser").get_text(" ", strip=True)).strip()


async def google_news(query: str, days: int | None = None, max_results: int = 6) -> list[dict]:
    q = f"{query} when:{days}d" if days else query
    key = f"gn|{q}|{max_results}"
    if (hit := _cached(key)) is not None:
        return hit
    out: list[dict] = []
    try:
        async with httpx.AsyncClient(timeout=15, headers=UA, follow_redirects=True) as client:
            resp = await client.get("https://news.google.com/rss/search", params={"q": q, "hl": "en-US", "gl": "US", "ceid": "US:en"})
        out = parse_google_news(resp.content, max_results)
    except (httpx.HTTPError, ET.ParseError) as exc:
        log.warning("google news search failed for %r: %s", query, exc)
    _cache[key] = (time.time(), out)
    return out


def parse_google_news(xml: bytes, max_results: int = 6) -> list[dict]:
    out = []
    for item in ET.fromstring(xml).iter("item"):
        title = (item.findtext("title") or "").strip()
        source = (item.findtext("source") or "").strip()
        if source and title.endswith(f" - {source}"):
            title = title[: -len(source) - 3]
        pub = item.findtext("pubDate")
        try:
            published = parsedate_to_datetime(pub).date().isoformat() if pub else None
        except (TypeError, ValueError):
            published = None
        snippet = _clean(item.findtext("description") or "")
        out.append({"title": title[:200], "url": item.findtext("link") or "", "snippet": (f"{source}: " if source else "") + snippet[:380],
                    "published_date": published})
        if len(out) >= max_results:
            break
    return out


def _ddg_url(href: str) -> str:
    if href.startswith("//duckduckgo.com/l/") or "duckduckgo.com/l/?" in href:
        qs = parse_qs(urlparse(href if href.startswith("http") else "https:" + href).query)
        return unquote(qs.get("uddg", [""])[0])
    return href


async def duckduckgo(query: str, max_results: int = 6, include_domains: list[str] | None = None) -> list[dict]:
    if include_domains:
        sites = " OR ".join(f"site:{d}" for d in include_domains[:3])
        query = f"{query} ({sites})" if len(include_domains) > 1 else f"{query} site:{include_domains[0]}"
    key = f"ddg|{query}|{max_results}"
    if (hit := _cached(key)) is not None:
        return hit
    out: list[dict] = []
    try:
        async with _ddg_lock:
            async with httpx.AsyncClient(timeout=15, headers=UA, follow_redirects=True) as client:
                resp = await client.post("https://html.duckduckgo.com/html/", data={"q": query[:300]})
            await asyncio.sleep(0.4)
        if resp.status_code == 202 or "anomaly" in resp.text[:20000].lower():
            global last_block
            last_block = time.time()
            log.warning("duckduckgo is rate-limiting this server; no results for %r", query)
        out = parse_duckduckgo(resp.text, max_results)
    except httpx.HTTPError as exc:
        log.warning("duckduckgo search failed for %r: %s", query, exc)
    if out:  # an empty answer is often a temporary block: don't remember it
        _cache[key] = (time.time(), out)
    return out


last_block = 0.0  # when DuckDuckGo last refused us (rate limit / bot check)


def recently_blocked(within: float = 600) -> bool:
    return time.time() - last_block < within


def parse_duckduckgo(html: str, max_results: int = 6) -> list[dict]:
    out = []
    for res in BeautifulSoup(html, "html.parser").select("div.result"):
        if "result--ad" in (res.get("class") or []):
            continue
        a = res.select_one("a.result__a")
        if not a or not a.get("href"):
            continue
        url = _ddg_url(a["href"])
        if not url.startswith("http") or "duckduckgo.com" in url:
            continue
        snip = res.select_one(".result__snippet")
        out.append({"title": a.get_text(" ", strip=True)[:200], "url": url,
                    "snippet": snip.get_text(" ", strip=True)[:400] if snip else "", "published_date": None})
        if len(out) >= max_results:
            break
    return out


async def fetch_text(urls: list[str]) -> dict[str, str]:
    """Readable main text of each page (Google News redirect links are skipped: they need JS)."""
    targets = [u for u in urls if u and "news.google.com" not in u][:5]

    async def one(client: httpx.AsyncClient, url: str) -> tuple[str, str]:
        try:
            resp = await client.get(url)
            if resp.status_code != 200 or "html" not in resp.headers.get("content-type", ""):
                return url, ""
            soup = BeautifulSoup(resp.text[:2_000_000], "html.parser")
            for tag in soup(["script", "style", "nav", "header", "footer", "aside", "form", "noscript"]):
                tag.decompose()
            body = soup.find("article") or soup.find("main") or soup.body or soup
            paras = [p.get_text(" ", strip=True) for p in body.find_all(["p", "li", "h2", "h3"])]
            text = "\n".join(p for p in paras if len(p) > 40)
            return url, re.sub(r"[ \t]+", " ", text)[:20000]
        except (httpx.HTTPError, UnsafeURL, ValueError):
            return url, ""

    async with safe_client(timeout=12, headers=UA, follow_redirects=True) as client:
        pairs = await asyncio.gather(*(one(client, u) for u in targets))
    return {u: t for u, t in pairs if t}
