"""Outbound-request safety: never let user-supplied URLs reach this machine or the internal network."""
from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

import httpx

from . import config


class UnsafeURL(ValueError):
    pass


def assert_public(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise UnsafeURL("Only http(s) website addresses are allowed.")
    if config.ALLOW_PRIVATE_URLS:
        return
    try:
        infos = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror as exc:
        raise UnsafeURL(f"Couldn't find the website {parsed.hostname}.") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            raise UnsafeURL("That address points at a private network, which isn't allowed.")


async def _check(request: httpx.Request) -> None:
    await asyncio.to_thread(assert_public, str(request.url))


def safe_client(**kw) -> httpx.AsyncClient:
    """An httpx client that checks every request, including each redirect hop."""
    return httpx.AsyncClient(event_hooks={"request": [_check]}, **kw)
