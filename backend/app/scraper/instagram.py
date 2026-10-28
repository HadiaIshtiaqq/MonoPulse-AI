"""Reading a brand's Instagram profile: name, bio, category, website, profile picture and recent
post photos with their captions.

Two honest ways, best first:
  1. Instagram's official API ("Business Discovery"), when an Instagram Business account is
     connected (META_ACCESS_TOKEN + INSTAGRAM_ACCOUNT_ID). It reads any business or creator profile.
  2. MonoPlus's own browser, when you've signed in to Instagram there: it opens the profile the
     way you would and reads what's on the page.
Instagram doesn't let anonymous programs read profiles, and MonoPlus doesn't pretend to be
something it isn't to get round that; without either way, the caller says so plainly.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

import httpx

from .. import config

log = logging.getLogger(__name__)
HANDLE = re.compile(r"^[A-Za-z0-9._]{1,30}$")


@dataclass
class Profile:
    username: str
    full_name: str = ""
    bio: str = ""
    website: str = ""
    category: str = ""
    picture: str = ""
    posts: list[tuple[str, str]] = field(default_factory=list)  # (image URL, caption)
    source: str = ""  # graph | browser

    def text(self) -> str:
        lines = [self.full_name, self.category, self.bio] + [c for _, c in self.posts[:12] if c]
        return "\n".join(x for x in lines if x)


def instagram_handle(raw: str) -> str | None:
    """"@brand", "brand" with an Instagram URL, or "instagram.com/brand/" -> "brand"."""
    raw = raw.strip()
    m = re.search(r"instagram\.com/([A-Za-z0-9._]{1,30})", raw)
    if m and m.group(1).lower() not in ("p", "reel", "reels", "explore", "stories", "accounts"):
        return m.group(1)
    if raw.startswith("@") and HANDLE.match(raw[1:]):
        return raw[1:]
    return None


async def via_graph(username: str) -> Profile | None:
    if not (config.META_ACCESS_TOKEN and config.INSTAGRAM_ACCOUNT_ID):
        return None
    from ..social.meta import graph

    fields = (f"business_discovery.username({username}){{username,name,biography,website,profile_picture_url,"
              "media.limit(12){media_url,thumbnail_url,caption,media_type}}")
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            resp = await c.get(graph(config.INSTAGRAM_ACCOUNT_ID), params={"fields": fields},
                                    headers={"Authorization": f"Bearer {config.META_ACCESS_TOKEN}"})
        if resp.status_code != 200:
            log.info("instagram business discovery for %s: %s", username, resp.text[:200])
            return None
        d = resp.json().get("business_discovery") or {}
    except (httpx.HTTPError, ValueError) as exc:
        log.info("instagram business discovery failed: %s", exc)
        return None
    posts = []
    for m in (d.get("media") or {}).get("data", []):
        url = m.get("thumbnail_url") if m.get("media_type") == "VIDEO" else m.get("media_url")
        if url:
            posts.append((url, m.get("caption") or ""))
    return Profile(username=d.get("username") or username, full_name=d.get("name") or "", bio=d.get("biography") or "",
                   website=d.get("website") or "", picture=d.get("profile_picture_url") or "", posts=posts, source="graph")


READ_PROFILE_JS = """() => {
  const header = document.querySelector('header');
  const text = el => (el && el.innerText || '').trim();
  const pic = header && (header.querySelector('img[alt*="profile picture" i]') || header.querySelector('img'));
  const link = header && [...header.querySelectorAll('a[href]')].find(a => /l\\.instagram\\.com|^https?:\\/\\/(?!www\\.instagram)/.test(a.href));
  let website = '';
  if (link) { try { const u = new URL(link.href); website = u.searchParams.get('u') || link.href; } catch (e) { website = link.href; } }
  const spans = header ? [...header.querySelectorAll('span, h1, h2')].map(text).filter(Boolean) : [];
  const posts = [...document.querySelectorAll('a[href*="/p/"] img, a[href*="/reel/"] img')].slice(0, 12)
    .map(img => [img.currentSrc || img.src, img.alt || '']);
  const title = document.querySelector('meta[property="og:title"]');
  return {header: text(header), spans, picture: pic ? (pic.currentSrc || pic.src) : '', website, posts,
          title: title ? title.content : document.title};
}"""


def parse_page(username: str, data: dict) -> Profile | None:
    """What MonoPlus's browser read from a profile page -> a Profile."""
    if not data or not (data.get("header") or data.get("posts")):
        return None
    m = re.match(r"^(.*?)\s*\(@", data.get("title") or "")
    full_name = (m.group(1).strip() if m else "") or next(
        (s for s in data.get("spans", []) if s and s.lower() != username.lower() and not re.search(r"\d+\s*(posts|followers|following)", s, re.I)
         and len(s) < 60), "")
    header = data.get("header") or ""
    # The bio is what follows the counts in the header ("12 posts 3,400 followers 120 following Name Bio…").
    bio = re.split(r"\bfollowing\b", header, maxsplit=1, flags=re.I)[-1].strip()
    if full_name and bio.startswith(full_name):
        bio = bio[len(full_name):].strip()
    bio = re.sub(r"\b(Follow|Message|Following|Followed by.*)$", "", bio, flags=re.I | re.S).strip()
    posts = [(src, alt) for src, alt in data.get("posts", []) if src and src.startswith("http")]
    return Profile(username=username, full_name=full_name, bio=bio[:500], website=data.get("website") or "",
                   picture=data.get("picture") or "", posts=posts, source="browser")


async def via_browser(username: str) -> Profile | None:
    from ..social import browser

    if not browser.available():
        return None
    try:
        signed_in = browser.poster.signed_in or await browser.poster.status()
        if not signed_in.get("instagram"):
            return None
        data = await browser.poster.read_instagram(username)
    except Exception as exc:  # noqa: BLE001 - no display, page changed, signed out
        log.info("reading @%s with the browser failed: %s", username, exc)
        return None
    return parse_page(username, data)


async def read_profile(username: str) -> Profile | None:
    for reader in (via_graph, via_browser):
        profile = await reader(username)
        if profile and (profile.full_name or profile.bio or profile.posts):
            return profile
    return None
