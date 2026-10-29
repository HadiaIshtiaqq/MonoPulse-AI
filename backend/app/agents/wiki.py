"""Wikipedia and Wikidata: open, keyless and meant for programs, so research has a source that
doesn't depend on a search engine tolerating us.

Two uses:
  * background for a research question (the intros of the most relevant articles), and
  * finding a brand's competitors: companies Wikipedia lists for the same industry and country,
    with the official website Wikidata records for each, so their sites can be read and compared.
Requests identify MonoPlus honestly, as Wikimedia's API rules ask.
"""
from __future__ import annotations

import logging
import re
import time

import httpx

log = logging.getLogger(__name__)

API = "https://en.wikipedia.org/w/api.php"
WIKIDATA = "https://www.wikidata.org/w/api.php"
UA = {"User-Agent": "MonoPlus/0.4 (https://github.com/HadiaIshtiaqq/MonoPulse-AI; social media research assistant)"}
_cache: dict[str, tuple[float, object]] = {}
TTL = 6 * 3600


async def _get(url: str, params: dict) -> dict:
    key = url + repr(sorted(params.items()))
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < TTL:
        return hit[1]  # type: ignore[return-value]
    async with httpx.AsyncClient(headers=UA, timeout=15) as client:
        resp = await client.get(url, params={**params, "format": "json", "formatversion": "2"})
        resp.raise_for_status()
        data = resp.json()
    _cache[key] = (time.time(), data)
    return data


async def search(query: str, limit: int = 10) -> list[dict]:
    """[{title, snippet, pageid}] for a full-text search of English Wikipedia."""
    try:
        data = await _get(API, {"action": "query", "list": "search", "srsearch": query[:300], "srlimit": limit})
    except (httpx.HTTPError, ValueError) as exc:
        log.info("wikipedia search failed for %r: %s", query, exc)
        return []
    return [{"title": h["title"], "pageid": h["pageid"], "snippet": re.sub(r"<[^>]+>", "", h.get("snippet", ""))}
            for h in data.get("query", {}).get("search", [])]


async def intros(titles: list[str]) -> list[dict]:
    """[{title, url, extract, qid}]: each article's opening paragraphs and its Wikidata id."""
    if not titles:
        return []
    try:
        data = await _get(API, {"action": "query", "prop": "extracts|pageprops|info", "exintro": 1, "explaintext": 1,
                                "inprop": "url", "ppprop": "wikibase_item", "titles": "|".join(titles[:20]), "redirects": 1})
    except (httpx.HTTPError, ValueError) as exc:
        log.info("wikipedia extracts failed: %s", exc)
        return []
    out = []
    for p in data.get("query", {}).get("pages", []):
        if p.get("missing"):
            continue
        out.append({"title": p["title"], "url": p.get("fullurl", ""), "extract": (p.get("extract") or "").strip(),
                    "qid": (p.get("pageprops") or {}).get("wikibase_item", "")})
    order = {t: i for i, t in enumerate(titles)}
    return sorted(out, key=lambda p: order.get(p["title"], 99))


def _claim_values(entity: dict, prop: str) -> list:
    vals = []
    for c in entity.get("claims", {}).get(prop, []):
        v = (c.get("mainsnak") or {}).get("datavalue", {}).get("value")
        if isinstance(v, dict) and "id" in v:
            vals.append(v["id"])
        elif isinstance(v, str):
            vals.append(v)
    return vals


async def entities(qids: list[str]) -> dict[str, dict]:
    """{qid: {"website": str, "countries": [country names], "label": str}} from Wikidata."""
    qids = [q for q in dict.fromkeys(qids) if q][:50]
    if not qids:
        return {}
    try:
        data = await _get(WIKIDATA, {"action": "wbgetentities", "ids": "|".join(qids), "props": "claims|labels", "languages": "en"})
    except (httpx.HTTPError, ValueError) as exc:
        log.info("wikidata failed: %s", exc)
        return {}
    ents = data.get("entities", {})
    country_ids = {c for e in ents.values() for p in ("P17", "P495") for c in _claim_values(e, p)}
    names: dict[str, str] = {}
    if country_ids:
        try:
            cdata = await _get(WIKIDATA, {"action": "wbgetentities", "ids": "|".join(list(country_ids)[:50]), "props": "labels",
                                          "languages": "en"})
            names = {k: v.get("labels", {}).get("en", {}).get("value", "") for k, v in cdata.get("entities", {}).items()}
        except (httpx.HTTPError, ValueError):
            pass
    out = {}
    for qid, e in ents.items():
        sites = _claim_values(e, "P856")
        out[qid] = {"website": sites[0] if sites else "", "label": e.get("labels", {}).get("en", {}).get("value", ""),
                    "countries": [names.get(c, "") for p in ("P17", "P495") for c in _claim_values(e, p) if names.get(c)]}
    return out


async def brands_in(category: str, country: str, exclude: set[str], limit: int = 8) -> list[tuple[str, str, str]]:
    """Companies Wikipedia lists for this kind of business in this country, with their official
    websites: [(name, website, how it was found)]. Only ones Wikidata places in that country."""
    if not country:
        return []
    found: list[dict] = []
    for q in (f"{category} brand {country}", f"{category} company {country}", f"{category} retailer {country}"):
        found += await search(q, 12)
    titles = list(dict.fromkeys(h["title"] for h in found if not h["title"].lower().startswith(("list of", "category:"))))[:30]
    pages = await intros(titles)
    info = await entities([p["qid"] for p in pages])
    out: list[tuple[str, str, str]] = []
    for p in pages:
        e = info.get(p["qid"], {})
        site = e.get("website", "")
        if not site or not any(country.lower() == c.lower() for c in e.get("countries", [])):
            continue
        host = re.sub(r"^www\.", "", re.sub(r"^https?://", "", site).split("/")[0].lower())
        if any(x and x in host for x in exclude):
            continue
        out.append((e.get("label") or p["title"], site, f"listed on Wikipedia as a {country} business (website from Wikidata)"))
        if len(out) >= limit:
            break
    return out
