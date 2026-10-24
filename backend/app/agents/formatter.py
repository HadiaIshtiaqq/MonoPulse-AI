"""Agent 5: Formatting & SEO (Nemotron Nano/Super).

Fast, structured calls: hashtag clustering, alt text and SEO keywords per post, then
hard platform constraints (length limits, hashtag counts) enforced in code.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re

from ..llm import LLMError, router
from ..schemas import BrandKit, Platform, SocialPost

log = logging.getLogger(__name__)

HASHTAG_COUNT = {Platform.INSTAGRAM: 10, Platform.LINKEDIN: 4, Platform.X: 2, Platform.FACEBOOK: 3}
CHAR_LIMIT = {Platform.X: 280, Platform.LINKEDIN: 3000, Platform.INSTAGRAM: 2200, Platform.FACEBOOK: 5000}

FORMAT_SYSTEM = """You are an SEO and social formatting assistant.
For each post, return hashtags, image alt text and SEO keywords.
Hashtag counts: instagram 8-12, linkedin 3-5, x 1-2, facebook 2-3. Mix niche, local and broad tags. No spaces inside tags.
Return a JSON array: [{"id": "...", "hashtags": ["#tag"], "alt_text": "<= 120 chars", "seo_keywords": ["3 phrases"]}]"""

BATCH = 10


def _tag(s: str) -> str:
    s = re.sub(r"[^\w]", "", s.replace("&", "and").title().replace(" ", ""))
    return f"#{s}" if s else ""


def fallback_meta(kit: BrandKit, post: SocialPost) -> dict:
    base = [_tag(kit.name), _tag(kit.industry)] + [_tag(k) for k in kit.keywords]
    if kit.location:
        base.insert(1, _tag(kit.location.split(",")[0]))
    base += ["#SmallBusiness", "#ShopLocal", "#SupportSmallBusiness"]
    tags = list(dict.fromkeys(t for t in base if len(t) > 2))
    return {
        "hashtags": tags,
        "alt_text": f"{kit.name} branded graphic: {post.headline}"[:120],
        "seo_keywords": kit.keywords[:3],
    }


async def _format_batch(kit: BrandKit, posts: list[SocialPost]) -> dict[str, dict]:
    items = [{"id": p.id, "platform": p.platform.value, "headline": p.headline, "caption": p.caption[:600]} for p in posts]
    user = f"Brand: {kit.name} ({kit.industry}, {kit.location or 'online'}). Keywords: {', '.join(kit.keywords)}\n\nPOSTS:\n{json.dumps(items, ensure_ascii=False)}"
    data = await router.complete_json("format_seo", FORMAT_SYSTEM, user, temperature=0.3, max_tokens=2500)
    if isinstance(data, dict):
        data = data.get("posts") or data.get("items") or []
    return {str(d.get("id")): d for d in data if isinstance(d, dict)}


def normalize_hashtags(tags: list, limit: int) -> list[str]:
    out = []
    for t in tags:
        t = str(t).strip()
        if not t:
            continue
        t = "#" + re.sub(r"[^\w]", "", t.lstrip("#"))
        if len(t) > 2 and t.lower() not in {x.lower() for x in out}:
            out.append(t)
    return out[:limit]


def enforce_limits(post: SocialPost) -> None:
    limit = CHAR_LIMIT[post.platform]
    tags = " ".join(post.hashtags)
    body = post.caption.strip()
    if post.cta and post.cta.lower() not in body.lower():
        body = f"{body}\n\n{post.cta}" if post.platform is not Platform.X else f"{body} {post.cta}"
    budget = limit - (len(tags) + 2 if tags else 0)
    if len(body) > budget:
        cut = body[: budget - 1]
        cut = cut[: max(cut.rfind(". "), cut.rfind(" "))].rstrip(" ,;:")
        body = cut + "…"
    post.caption = body


async def format_posts(kit: BrandKit, posts: list[SocialPost]) -> None:
    meta: dict[str, dict] = {}
    if router.enabled:
        batches = [posts[i : i + BATCH] for i in range(0, len(posts), BATCH)]
        results = await asyncio.gather(*(_format_batch(kit, b) for b in batches), return_exceptions=True)
        for r in results:
            if isinstance(r, BaseException):
                log.warning("format batch failed: %s", r if isinstance(r, LLMError) else repr(r))
            else:
                meta.update(r)
    for post in posts:
        m = meta.get(post.id) or fallback_meta(kit, post)
        post.hashtags = normalize_hashtags(m.get("hashtags") or fallback_meta(kit, post)["hashtags"], HASHTAG_COUNT[post.platform])
        post.alt_text = str(m.get("alt_text") or "")[:200]
        post.seo_keywords = [str(k) for k in (m.get("seo_keywords") or [])][:5]
        enforce_limits(post)
