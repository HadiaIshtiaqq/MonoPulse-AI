"""Publishing.

Direct: posts go straight to Instagram, Facebook Pages, LinkedIn and X through their
official APIs when the account is connected in the server's .env (see app/social).
Webhook (optional): PUBLISH_WEBHOOK_URL sends the post to Zapier / Make / n8n instead.
1-click fallback: when a platform isn't connected, open its composer with the caption ready.

With auto-publish on, approved posts go out at their scheduled time.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import json
import logging
import socket
from datetime import datetime, timezone
from urllib.parse import quote, urlparse

import httpx

from . import config
from .schemas import Campaign, Platform, PostStatus, SocialPost
from .social import browser, linkedin, meta, x
from .social.base import Published, PublishError, full_caption
from .store import store

log = logging.getLogger(__name__)

DIRECT = {
    Platform.INSTAGRAM: (meta.instagram_connected, meta.publish_instagram),
    Platform.FACEBOOK: (meta.facebook_connected, meta.publish_facebook),
    Platform.LINKEDIN: (linkedin.connected, linkedin.publish),
    Platform.X: (x.connected, x.publish),
}


def connections() -> dict[str, bool]:
    return {p.value: check() for p, (check, _) in DIRECT.items()}


def browser_ready(platform: Platform) -> bool:
    """Scheduled posts may use the browser when it's switched on and you're signed in there."""
    return store.settings.browser_publish and browser.poster.signed_in.get(platform.value, False)


def can_publish(platform: Platform) -> bool:
    return DIRECT[platform][0]() or bool(config.PUBLISH_WEBHOOK_URL) or browser_ready(platform)


def post_files(post: SocialPost, media: str = "images") -> list:
    """The post's own files on disk: its images (every carousel page), or its reel."""
    urls = [post.video_url] if media == "reel" and post.video_url else (post.image_urls or [post.image_url])
    files = [config.MEDIA_DIR / u.split("?")[0].removeprefix("/media/") for u in urls if u]
    return [f for f in files if f.exists()]


async def browser_post(post: SocialPost, submit: bool, media: str = "images") -> str:
    """Fill in (and, with submit, post) the post in MonoPlus's signed-in browser."""
    if not browser.available():
        raise PublishError("Posting from the browser needs Playwright: pip install playwright && python -m playwright install chromium")
    try:
        message = await browser.poster.post(post.platform, full_caption(post), post_files(post, media), submit)
    except browser.BrowserPostError as exc:
        raise PublishError(str(exc)) from exc
    if submit:
        post.status, post.published_via, post.publish_error = PostStatus.PUBLISHED, "browser", None
        store.save()
    return message


def absolute(url: str | None) -> str | None:
    return f"{config.PUBLIC_API_URL}{url.split('?')[0]}" if url else None


def share_links(post: SocialPost) -> dict:
    text = full_caption(post)
    images = [absolute(u) for u in (post.image_urls or [post.image_url]) if u]
    if post.platform is Platform.X:
        url = f"https://x.com/intent/post?text={quote(text)}"
        note = "X is open with your caption. Attach the downloaded image to finish."
    elif post.platform is Platform.LINKEDIN:
        url = f"https://www.linkedin.com/feed/?shareActive=true&text={quote(text)}"
        note = "LinkedIn is open with your caption. Attach the downloaded image" + ("s." if len(images) > 1 else ".")
    elif post.platform is Platform.FACEBOOK:
        # Facebook's share dialog only takes a link, which would post a preview of the website
        # instead of the designed image; its news feed composer accepts a pasted image.
        url = "https://www.facebook.com/"
        note = "Facebook is open. Paste the image into a new post, then paste the caption."
    else:
        url = "https://www.instagram.com/"
        note = "Your caption is copied. Download the image" + ("s" if len(images) > 1 else "") + " and post from Instagram."
    return {"platform": post.platform.value, "url": url, "caption": text, "image_url": images[0] if images else None,
            "image_urls": images, "note": note}


# --------------------------------------------------------------------------- webhook (optional)


def assert_public_url(url: str) -> None:
    """Refuse webhooks that point at this machine or the internal network (SSRF)."""
    parsed = urlparse(url)
    if parsed.scheme != "https" and not (config.ALLOW_PRIVATE_WEBHOOKS and parsed.scheme == "http"):
        raise PublishError("Webhook URLs must use https.")
    if not parsed.hostname:
        raise PublishError("Webhook URL has no host.")
    if config.ALLOW_PRIVATE_WEBHOOKS:
        return
    try:
        infos = socket.getaddrinfo(parsed.hostname, parsed.port or 443)
    except socket.gaierror as exc:
        raise PublishError(f"Can't resolve {parsed.hostname}.") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise PublishError("Webhook URLs can't point at private or internal addresses.")


def sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


async def send_webhook(post: SocialPost, campaign: Campaign) -> Published:
    url = config.PUBLISH_WEBHOOK_URL
    await asyncio.to_thread(assert_public_url, url)
    payload = {
        "event": "post.publish",
        "post": {"id": post.id, "platform": post.platform.value, "format": post.format, "full_caption": full_caption(post),
                 "image_urls": [absolute(u) for u in (post.image_urls or [post.image_url]) if u], "alt_text": post.alt_text,
                 "publish_at": post.publish_at.isoformat()},
        "brand": {"name": campaign.brand.name if campaign.brand else ""},
    }
    body = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json", "X-MonoPlus-Signature": sign(store.settings.webhook_secret, body)}
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
            resp = await client.post(url, content=body, headers=headers)
    except httpx.HTTPError as exc:
        raise PublishError(f"Webhook request failed: {exc}") from exc
    if not resp.is_success:
        raise PublishError(f"Webhook answered {resp.status_code}")
    return Published(post.platform.value, "", None)


# --------------------------------------------------------------------------- dispatch


_in_flight: set[str] = set()


async def publish_post(post: SocialPost, campaign: Campaign) -> SocialPost:
    # A double click, or the scheduler firing during a manual post, must never post twice.
    if post.id in _in_flight:
        raise PublishError("This post is already being published.")
    if post.status is PostStatus.PUBLISHED:
        raise PublishError("This post is already published.")
    _in_flight.add(post.id)
    try:
        return await _publish(post, campaign)
    finally:
        _in_flight.discard(post.id)


async def _publish(post: SocialPost, campaign: Campaign) -> SocialPost:
    connected, direct = DIRECT[post.platform]
    try:
        if connected():
            result, via = await direct(post), "direct"
        elif config.PUBLISH_WEBHOOK_URL:
            result, via = await send_webhook(post, campaign), "webhook"
        elif browser_ready(post.platform):
            await browser_post(post, submit=True)
            return post
        else:
            raise PublishError(f"{post.platform.value.title()} isn't connected yet.")
    except PublishError as exc:
        post.publish_error = str(exc)
        store.save(campaign)
        raise
    except httpx.HTTPError as exc:
        post.publish_error = f"Network error: {exc}"
        store.save(campaign)
        raise PublishError(post.publish_error) from exc
    post.status, post.published_via, post.publish_error = PostStatus.PUBLISHED, via, None
    post.remote_id, post.remote_url = result.remote_id or None, result.url
    store.save(campaign)
    return post


def due_posts(now: datetime | None = None) -> list[tuple[Campaign, SocialPost]]:
    now = now or datetime.now(timezone.utc)
    return [
        (c, p) for c in store.campaigns.values() for p in c.posts
        if p.status is PostStatus.APPROVED and p.publish_at <= now and not p.publish_error and can_publish(p.platform)
    ]


async def publish_due() -> int:
    if not store.settings.auto_publish:
        return 0
    sent = 0
    for campaign, post in due_posts():
        try:
            await publish_post(post, campaign)
            sent += 1
        except PublishError as exc:
            log.warning("auto-publish failed for %s: %s", post.id, exc)
    return sent


async def scheduler(poll_s: float = 60.0) -> None:
    while True:
        try:
            await publish_due()
        except Exception:  # noqa: BLE001 - keep the scheduler alive
            log.exception("auto-publish pass failed")
        await asyncio.sleep(poll_s)
