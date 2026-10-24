"""Shared plumbing for the direct-publishing clients."""
from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx
from PIL import Image

from .. import config
from ..schemas import SocialPost

# Tests swap this for an httpx.MockTransport so no request leaves the machine.
transport: httpx.AsyncBaseTransport | None = None


class PublishError(RuntimeError):
    pass


@dataclass
class Published:
    platform: str
    remote_id: str
    url: str | None


def client(**kw) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=kw.pop("timeout", 60), transport=transport, **kw)


def image_paths(post: SocialPost) -> list[Path]:
    paths = []
    for url in post.image_urls or ([post.image_url] if post.image_url else []):
        path = config.MEDIA_DIR / url.split("?")[0].removeprefix("/media/")
        if path.exists():
            paths.append(path)
    if not paths:
        raise PublishError("This post has no rendered image yet.")
    return paths


def as_jpeg(path: Path) -> Path:
    """Instagram only accepts JPEG, and JPEGs are smaller for every platform."""
    out = path.with_suffix(".jpg")
    if not out.exists() or out.stat().st_mtime < path.stat().st_mtime:
        Image.open(path).convert("RGB").save(out, "JPEG", quality=92, optimize=True)
    return out


def public_base_url() -> str | None:
    """PUBLIC_API_URL if the internet can reach it, else None (localhost or a private IP)."""
    host = urlparse(config.PUBLIC_API_URL).hostname or ""
    if host in ("localhost", "") or host.endswith(".local"):
        return None
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback:
            return None
    except ValueError:
        pass
    return config.PUBLIC_API_URL


def full_caption(post: SocialPost) -> str:
    tags = " ".join(post.hashtags)
    return f"{post.caption}\n\n{tags}".strip() if tags else post.caption


def raise_for(resp: httpx.Response, what: str) -> None:
    if resp.is_success:
        return
    try:
        body = resp.json()
        err = body.get("error") or {}
        msg = err.get("error_user_msg") or err.get("message") or body.get("message") or body.get("detail") or body.get("title") or resp.text
    except ValueError:
        msg = resp.text
    raise PublishError(f"{what} failed ({resp.status_code}): {str(msg)[:240]}")
