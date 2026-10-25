"""Agent 2: trend engine - live industry news, local events and viral topics.

Tavily when TAVILY_API_KEY is set; free Google News / DuckDuckGo otherwise.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date

from tavily import AsyncTavilyClient

from .. import config
from ..schemas import BrandKit, TrendItem
from . import freesearch

log = logging.getLogger(__name__)

_client: AsyncTavilyClient | None = None


def _get_client() -> AsyncTavilyClient:
    global _client
    if _client is None:
        _client = AsyncTavilyClient(api_key=config.TAVILY_API_KEY)
    return _client


async def search(
    query: str,
    *,
    topic: str = "general",
    days: int | None = None,
    max_results: int = 5,
    include_domains: list[str] | None = None,
) -> list[TrendItem]:
    """Tavily when configured; otherwise (or if Tavily fails) free Google News / DuckDuckGo."""
    rows: list[dict] = []
    if config.tavily_enabled():
        kwargs: dict = {"query": query[:380], "max_results": max_results, "topic": topic, "search_depth": "basic"}
        if topic == "news" and days:
            kwargs["days"] = days
        if include_domains:
            kwargs["include_domains"] = include_domains
        try:
            resp = await _get_client().search(**kwargs)
            rows = [{"title": r.get("title") or "", "url": r.get("url") or "", "snippet": r.get("content") or "",
                     "published_date": r.get("published_date")} for r in resp.get("results", [])]
        except Exception as exc:  # noqa: BLE001 - fall through to the free providers
            log.warning("tavily search failed for %r: %s", query, exc)
    if not rows and config.FREE_SEARCH:
        if topic == "news" and not include_domains:
            rows = await freesearch.google_news(query, days, max_results)
        else:
            rows = await freesearch.duckduckgo(query, max_results, include_domains)
    return [
        TrendItem(title=r["title"].strip()[:200], url=r["url"], snippet=r["snippet"].strip()[:400],
                  published_date=r.get("published_date"), query=query)
        for r in rows if r.get("title") and r.get("url")
    ]


async def extract(urls: list[str]) -> dict[str, str]:
    """Full page text for each URL: Tavily Extract when configured, else our own reader."""
    if not urls:
        return {}
    if config.tavily_enabled():
        try:
            resp = await _get_client().extract(urls=urls[:20])
            out = {r.get("url"): (r.get("raw_content") or "")[:20000] for r in resp.get("results", []) if r.get("url")}
            if out:
                return out
        except Exception as exc:  # noqa: BLE001
            log.warning("tavily extract failed: %s", exc)
    return await freesearch.fetch_text(urls) if config.FREE_SEARCH else {}


def build_queries(kit: BrandKit, today: date | None = None) -> list[tuple[str, str]]:
    today = today or date.today()
    month = today.strftime("%B %Y")
    industry = kit.industry or "small business"
    queries = [
        (f"{industry} industry news trends {month}", "news"),
        (f"trending {industry} social media topics and hashtags {month}", "general"),
    ]
    if kit.location:
        queries.append((f"{kit.location} local events {month}", "news"))
    else:
        queries.append((f"{industry} consumer behavior trend {month}", "news"))
    if kit.keywords:
        queries.append((f"{' '.join(kit.keywords[:3])} latest", "news"))
    return queries


async def gather_trends(kit: BrandKit, limit: int = 10) -> list[TrendItem]:
    results = await asyncio.gather(*(search(q, topic=t, days=14) for q, t in build_queries(kit)))
    seen: set[str] = set()
    merged: list[TrendItem] = []
    # Interleave so every query contributes something before any one dominates.
    for i in range(max((len(r) for r in results), default=0)):
        for group in results:
            if i < len(group):
                item = group[i]
                key = item.url or item.title
                if key and key not in seen and item.title:
                    seen.add(key)
                    merged.append(item)
    return merged[:limit]
