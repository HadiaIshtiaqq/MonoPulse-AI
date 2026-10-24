"""Agent 2: Tavily trend engine - live industry news, local events and viral topics."""
from __future__ import annotations

import asyncio
import logging
from datetime import date

from tavily import AsyncTavilyClient

from .. import config
from ..schemas import BrandKit, TrendItem

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
    if not config.tavily_enabled():
        return []
    kwargs: dict = {"query": query[:380], "max_results": max_results, "topic": topic, "search_depth": "basic"}
    if topic == "news" and days:
        kwargs["days"] = days
    if include_domains:
        kwargs["include_domains"] = include_domains
    try:
        resp = await _get_client().search(**kwargs)
    except Exception as exc:  # noqa: BLE001 - trends are an enrichment; never fail the campaign over them
        log.warning("tavily search failed for %r: %s", query, exc)
        return []
    out = []
    for r in resp.get("results", []):
        out.append(
            TrendItem(
                title=(r.get("title") or "").strip()[:200],
                url=r.get("url") or "",
                snippet=(r.get("content") or "").strip()[:400],
                published_date=r.get("published_date"),
                query=query,
            )
        )
    return out


async def extract(urls: list[str]) -> dict[str, str]:
    """Full page text for each URL via Tavily Extract (handles JS-heavy pages)."""
    if not config.tavily_enabled() or not urls:
        return {}
    try:
        resp = await _get_client().extract(urls=urls[:20])
    except Exception as exc:  # noqa: BLE001
        log.warning("tavily extract failed: %s", exc)
        return {}
    return {r.get("url"): (r.get("raw_content") or "")[:20000] for r in resp.get("results", []) if r.get("url")}


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
