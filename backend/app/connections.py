"""What MonoPlus is connected to. Every key and token lives in the backend's .env file and nowhere
else: the web app never sees, sends or stores one. It only hears which services are set up.

Two commands help fill the .env file, run from the backend folder:

    .venv\\Scripts\\python -m app.connections check   # checks each key that's set with its service
    .venv\\Scripts\\python -m app.connections meta    # turns META_USER_TOKEN into the lasting Page connection

Neither prints a key. Values are hidden from logs and errors by redact.py, which reads them from config.
"""
from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

import httpx

from . import config

ENV_FILE = config.BACKEND_DIR / ".env"
# What each connection needs in .env, for the Connections page to show.
NEEDS = {
    "meta": ("META_ACCESS_TOKEN", "META_PAGE_ID", "INSTAGRAM_ACCOUNT_ID"),
    "nebius": ("NEBIUS_API_KEY",),
    "tavily": ("TAVILY_API_KEY",),
    "heygen": ("HEYGEN_API_KEY",),
    "huggingface": ("HF_TOKEN",),
    "langsmith": ("LANGSMITH_API_KEY",),
}


def status() -> dict:
    """What's connected, and the .env settings each one needs. Never a value."""
    return {
        "meta": {"connected": bool(config.META_ACCESS_TOKEN and (config.INSTAGRAM_ACCOUNT_ID or config.META_PAGE_ID)),
                 "page": getattr(config, "META_PAGE_NAME", "") or "", "instagram": getattr(config, "INSTAGRAM_USERNAME", "") or "",
                 "instagram_ready": bool(config.META_ACCESS_TOKEN and config.INSTAGRAM_ACCOUNT_ID), "env": list(NEEDS["meta"])},
        "nebius": {"connected": bool(config.NEBIUS_API_KEY), "env": list(NEEDS["nebius"])},
        "tavily": {"connected": bool(config.TAVILY_API_KEY), "env": list(NEEDS["tavily"])},
        "heygen": {"connected": bool(config.HEYGEN_API_KEY), "env": list(NEEDS["heygen"])},
        "huggingface": {"connected": bool(config.HF_TOKEN), "env": list(NEEDS["huggingface"])},
        "langsmith": {"connected": bool(config.LANGSMITH_API_KEY), "env": list(NEEDS["langsmith"])},
    }


class ConnectionError_(RuntimeError):
    pass


# --------------------------------------------------------------------------- checking keys

async def check_nebius(key: str) -> None:
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(f"{config.NEBIUS_BASE_URL.rstrip('/')}/models", headers={"Authorization": f"Bearer {key.strip()}"})
    if r.status_code != 200:
        raise ConnectionError_("Nebius didn't accept that key." + (" Check it's a Token Factory API key." if r.status_code in (401, 403) else
                                                                   f" (HTTP {r.status_code})"))


async def check_tavily(key: str) -> str:
    """Asks Tavily how much of the plan is used (this spends no credit)."""
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get("https://api.tavily.com/usage", headers={"Authorization": f"Bearer {key.strip()}"})
    if r.status_code != 200:
        raise ConnectionError_("Tavily didn't accept that key." + ("" if r.status_code in (401, 403) else f" (HTTP {r.status_code})"))
    return tavily_left(r.json())


def tavily_left(data: dict) -> str:
    """"ok, 812 of 1,000 credits left this month" from Tavily's usage reply, or "ok" if it's shaped differently."""
    for part in (data.get("account") or {}, data.get("key") or {}):
        used = part.get("plan_usage", part.get("usage"))
        limit = part.get("plan_limit", part.get("limit"))
        if isinstance(used, (int, float)) and isinstance(limit, (int, float)) and limit:
            return f"ok, {max(0, int(limit - used)):,} of {int(limit):,} credits left"
    return "ok"


async def check_langsmith(key: str) -> str | None:
    """Lists one tracing project (this sends no trace). A tracing-only key (lsv2_tr_) is accepted but may
    not list projects: LangSmith says so by name, which shows the key itself is good."""
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(f"{config.LANGSMITH_ENDPOINT.rstrip('/')}/api/v1/sessions", params={"limit": 1},
                             headers={"x-api-key": key.strip()})
    if r.status_code == 403 and "tracing key" in r.text:
        return "ok (a tracing-only key: it can send traces, nothing else)"
    if r.status_code != 200:
        raise ConnectionError_("LangSmith didn't accept that key." + ("" if r.status_code in (401, 403) else f" (HTTP {r.status_code})"))


async def check_huggingface(token: str) -> None:
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get("https://huggingface.co/api/whoami-v2", headers={"Authorization": f"Bearer {token.strip()}"})
    if r.status_code != 200:
        raise ConnectionError_("Hugging Face didn't accept that token." + ("" if r.status_code in (401, 403) else f" (HTTP {r.status_code})"))


async def check_all() -> list[tuple[str, str]]:
    """(service, "ok" | why not) for each key that's set."""
    from .agents import ugc

    checks = [("Nemotron on Nebius (NEBIUS_API_KEY)", config.NEBIUS_API_KEY, check_nebius),
              ("Tavily (TAVILY_API_KEY)", config.TAVILY_API_KEY, check_tavily),
              ("HeyGen (HEYGEN_API_KEY)", config.HEYGEN_API_KEY, ugc.heygen_check),
              ("Hugging Face (HF_TOKEN)", config.HF_TOKEN, check_huggingface),
              ("LangSmith (LANGSMITH_API_KEY or LANG_CHAIN)", config.LANGSMITH_API_KEY, check_langsmith)]
    out = []
    for name, key, check in checks:
        if not key:
            out.append((name, "not set"))
            continue
        try:
            out.append((name, await check(key) or "ok"))
        except (ConnectionError_, ugc.UgcError) as exc:
            out.append((name, str(exc)))
        except httpx.HTTPError as exc:
            out.append((name, f"couldn't reach the service ({type(exc).__name__})"))
    return out


# --------------------------------------------------------------------------- the Meta connection

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
    and the Instagram Business/Creator account linked to it, and return the settings for .env.

    With the app's id and secret, the token is first exchanged for a long-lived one, so the Page
    token never expires; without them it lasts as long as the token given (about an hour from the
    Graph API Explorer)."""
    token = user_token.strip()
    if not token:
        raise ConnectionError_("Set META_USER_TOKEN in backend/.env first.")
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
    return {"settings": {"META_ACCESS_TOKEN": page.get("access_token") or token, "META_PAGE_ID": str(page.get("id", "")),
                         "INSTAGRAM_ACCOUNT_ID": str(ig.get("id", "")), "META_PAGE_NAME": str(page.get("name", "")),
                         "INSTAGRAM_USERNAME": str(ig.get("username", ""))},
            "page": page.get("name", ""), "instagram": ig.get("username", ""), "lasting": lasting,
            "note": "" if ig else "Connected to the Facebook Page, but no Instagram Business or Creator account is linked to it. "
                                  "Link one in the Page's settings, then run this again."}


def write_env(values: dict[str, str], path: Path = ENV_FILE) -> None:
    """Set these lines in the .env file, keeping everything else in it as it was."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    left = dict(values)
    for i, line in enumerate(lines):
        m = re.match(r"^\s*([A-Z0-9_]+)\s*=", line)
        if m and m.group(1) in left:
            lines[i] = f"{m.group(1)}={left.pop(m.group(1))}"
    lines += [f"{k}={v}" for k, v in left.items()]
    tmp = path.with_suffix(".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp.replace(path)


def main(argv: list[str]) -> int:
    import os

    if argv[:1] == ["check"]:
        for name, result in asyncio.run(check_all()):
            print(f"{name}: {result}")
        return 0
    if argv[:1] == ["meta"]:
        try:
            result = asyncio.run(connect_meta(os.environ.get("META_USER_TOKEN", ""), os.environ.get("META_APP_ID", ""),
                                              os.environ.get("META_APP_SECRET", "")))
        except (ConnectionError_, httpx.HTTPError) as exc:
            print(f"Not connected: {exc}")
            return 1
        write_env({**result["settings"], "META_USER_TOKEN": ""}, ENV_FILE)  # the short-lived token is no longer needed
        print(f"Connected the Facebook Page {result['page']!r}" + (f" and Instagram @{result['instagram']}" if result["instagram"] else "")
              + (", lasting" if result["lasting"] else ", for about an hour (add META_APP_ID and META_APP_SECRET for a lasting one)")
              + f". Saved to {ENV_FILE}. Restart MonoPlus to use it.")
        if result["note"]:
            print(result["note"])
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
