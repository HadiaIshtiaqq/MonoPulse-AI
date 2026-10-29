"""Connections you set up in the app instead of in a .env file: the official Instagram/Facebook
connection, the Nemotron (Nebius) key and the Tavily search key.

They're kept in a file on this computer, outside the project folder (next to MonoPlus's browser
profile), so they're never committed or copied with the project. A setting in the environment
(.env) wins over the file. Values are checked with the service before they're saved, never sent
back to the page (only "connected" and names), and hidden from logs and errors by redact.py,
which reads them from config.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import httpx

from . import config

log = logging.getLogger(__name__)

KEYS = ("NEBIUS_API_KEY", "TAVILY_API_KEY", "HEYGEN_API_KEY", "META_ACCESS_TOKEN", "META_PAGE_ID", "INSTAGRAM_ACCOUNT_ID",
        "META_PAGE_NAME", "INSTAGRAM_USERNAME")
_from_env = {k: bool(os.environ.get(k)) for k in KEYS}


def path() -> Path:
    return Path(os.environ.get("MONOPLUS_CONNECTIONS_FILE") or config.BROWSER_PROFILE_DIR.parent / "connections.json")


def _read() -> dict:
    try:
        data = json.loads(path().read_text(encoding="utf-8"))
        return {k: str(v) for k, v in data.items() if k in KEYS and v}
    except (OSError, ValueError):
        return {}


def load() -> None:
    """Apply saved connections to the running settings (an environment value always wins)."""
    for k, v in _read().items():
        if not _from_env.get(k):
            setattr(config, k, v)


def _write(data: dict) -> None:
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps({k: v for k, v in data.items() if v}, indent=2), encoding="utf-8")
    tmp.replace(p)


def save(**values: str) -> None:
    data = _read()
    for k, v in values.items():
        assert k in KEYS, k
        data[k] = v or ""
        if not _from_env.get(k):
            setattr(config, k, v or "")
    _write(data)
    _reset_clients()


def _reset_clients() -> None:
    """Clients built with the old key are dropped, so the next call uses the new one."""
    from .agents import trends
    from .llm import router

    router._client, router._resolved = None, False
    trends._client = None


def status() -> dict:
    """What's connected, without a single secret in it."""
    return {
        "meta": {"connected": bool(config.META_ACCESS_TOKEN and (config.INSTAGRAM_ACCOUNT_ID or config.META_PAGE_ID)),
                 "page": getattr(config, "META_PAGE_NAME", "") or "", "instagram": getattr(config, "INSTAGRAM_USERNAME", "") or "",
                 "instagram_ready": bool(config.META_ACCESS_TOKEN and config.INSTAGRAM_ACCOUNT_ID),
                 "from_env": _from_env["META_ACCESS_TOKEN"]},
        "nebius": {"connected": bool(config.NEBIUS_API_KEY), "from_env": _from_env["NEBIUS_API_KEY"]},
        "tavily": {"connected": bool(config.TAVILY_API_KEY), "from_env": _from_env["TAVILY_API_KEY"]},
        "heygen": {"connected": bool(config.HEYGEN_API_KEY), "from_env": _from_env["HEYGEN_API_KEY"]},
        "file": str(path()),
    }


class ConnectionError_(RuntimeError):
    pass


def _graph(p: str) -> str:
    return f"https://graph.facebook.com/{config.GRAPH_API_VERSION}/{p.lstrip('/')}"


def _meta_error(resp: httpx.Response) -> str:
    try:
        err = resp.json().get("error") or {}
        return err.get("error_user_msg") or err.get("message") or resp.text[:200]
    except ValueError:
        return resp.text[:200]


async def connect_meta(user_token: str, app_id: str = "", app_secret: str = "") -> dict:
    """Turn a Meta user access token into a lasting connection: find the Facebook Page you manage
    and the Instagram Business/Creator account linked to it, and keep the Page's token.

    With the app's id and secret, the token is first exchanged for a long-lived one, so the Page
    token never expires; without them it lasts as long as the token you pasted (about an hour
    from the Graph API Explorer)."""
    token = user_token.strip()
    if not token:
        raise ConnectionError_("Paste an access token first.")
    async with httpx.AsyncClient(timeout=20) as client:
        lasting = False
        if app_id.strip() and app_secret.strip():
            # In the request body, not the URL, so the secret can't turn up in an address or an error message.
            r = await client.post(_graph("oauth/access_token"), data={
                "grant_type": "fb_exchange_token", "client_id": app_id.strip(), "client_secret": app_secret.strip(),
                "fb_exchange_token": token})
            if r.status_code != 200:
                raise ConnectionError_(f"Meta didn't accept the app id and secret: {_meta_error(r)}")
            token, lasting = r.json().get("access_token", token), True
        r = await client.get(_graph("me/accounts"), params={"fields": "name,access_token,instagram_business_account{id,username}"},
                             headers={"Authorization": f"Bearer {token}"})
        if r.status_code != 200:
            raise ConnectionError_(f"Meta didn't accept that token: {_meta_error(r)}")
        pages = r.json().get("data") or []
    if not pages:
        raise ConnectionError_("That token doesn't manage any Facebook Page. It needs the pages_show_list and pages_manage_posts "
                               "permissions, and an Instagram account linked to the Page.")
    page = next((p for p in pages if p.get("instagram_business_account")), pages[0])
    ig = page.get("instagram_business_account") or {}
    save(META_ACCESS_TOKEN=page.get("access_token") or token, META_PAGE_ID=str(page.get("id", "")),
         INSTAGRAM_ACCOUNT_ID=str(ig.get("id", "")), META_PAGE_NAME=str(page.get("name", "")),
         INSTAGRAM_USERNAME=str(ig.get("username", "")))
    return {"page": page.get("name", ""), "instagram": ig.get("username", ""), "lasting": lasting,
            "note": "" if ig else "Connected to the Facebook Page, but no Instagram Business or Creator account is linked to it. "
                                  "Link one in the Page's settings, then connect again."}


async def check_nebius(key: str) -> None:
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(f"{config.NEBIUS_BASE_URL.rstrip('/')}/models", headers={"Authorization": f"Bearer {key.strip()}"})
    if r.status_code != 200:
        raise ConnectionError_("Nebius didn't accept that key." + (" Check it's a Token Factory API key." if r.status_code in (401, 403) else
                                                                   f" (HTTP {r.status_code})"))


async def check_tavily(key: str) -> None:
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post("https://api.tavily.com/search", json={"query": "test", "max_results": 1},
                              headers={"Authorization": f"Bearer {key.strip()}"})
    if r.status_code != 200:
        raise ConnectionError_("Tavily didn't accept that key." + ("" if r.status_code in (401, 403) else f" (HTTP {r.status_code})"))


def disconnect(name: str) -> None:
    keys = {"meta": ("META_ACCESS_TOKEN", "META_PAGE_ID", "INSTAGRAM_ACCOUNT_ID", "META_PAGE_NAME", "INSTAGRAM_USERNAME"),
            "nebius": ("NEBIUS_API_KEY",), "tavily": ("TAVILY_API_KEY",), "heygen": ("HEYGEN_API_KEY",)}[name]
    save(**{k: "" for k in keys})
