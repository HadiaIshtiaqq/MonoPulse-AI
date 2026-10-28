"""Credentials never leak: not into logs, error messages, saved errors or URLs."""
import logging

import httpx
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import config
from app.main import app
from app.redact import HIDDEN, redact

TOKEN = "EAAGm0PX4ZCpsBAKZCZBnotarealtokenatall1234567890"


def test_known_keys_and_credential_shapes_are_hidden(monkeypatch):
    monkeypatch.setattr(config, "META_ACCESS_TOKEN", TOKEN)
    monkeypatch.setattr(config, "NEBIUS_API_KEY", "nb-very-secret-key-123")
    text = (f"Client error '400' for url 'https://graph.facebook.com/v21.0/123?fields=id&access_token={TOKEN}' "
            "headers={'Authorization': 'Bearer abcdefghijklmnop'} key nb-very-secret-key-123 sk-abcdefghijklmnopqrstuv "
            "https://hooks.example/x?api_key=zzz111zzz")
    clean = redact(text)
    for secret in (TOKEN, "abcdefghijklmnop", "nb-very-secret-key-123", "sk-abcdefghijklmnopqrstuv", "zzz111zzz"):
        assert secret not in clean, secret
    assert HIDDEN in clean and "graph.facebook.com" in clean  # the useful part of the message stays
    assert redact("max_tokens=2048 and a normal sentence.") == "max_tokens=2048 and a normal sentence."


def test_log_lines_never_carry_a_key(monkeypatch, caplog):
    monkeypatch.setattr(config, "LINKEDIN_ACCESS_TOKEN", "li-secret-token-999")
    with caplog.at_level(logging.INFO):
        logging.getLogger("app.social.linkedin").info("posting failed: %s", "401 for Bearer li-secret-token-999")
        logging.getLogger("uvicorn.access").info('127.0.0.1 - "GET /api/campaigns?key=%s HTTP/1.1" 401', "hunter2hunter2")
        try:
            raise RuntimeError("token li-secret-token-999 rejected")
        except RuntimeError:
            logging.getLogger("monoplus").exception("crash")
    assert "li-secret-token-999" not in caplog.text and "hunter2hunter2" not in caplog.text


def test_error_messages_sent_to_the_page_are_redacted(monkeypatch):
    monkeypatch.setattr(config, "ACCESS_KEY", "")
    monkeypatch.setattr(config, "X_USER_ACCESS_TOKEN", "x-secret-token-777")

    async def leaky():
        raise HTTPException(502, "X said no: Bearer x-secret-token-777 is invalid")

    async def crashes():
        raise RuntimeError("boom with x-secret-token-777")

    app.add_api_route("/api/_test_leaky", leaky)
    app.add_api_route("/api/_test_crash", crashes)
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            r = client.get("/api/_test_leaky")
            assert r.status_code == 502 and "x-secret-token-777" not in r.text and "X said no" in r.text
            r = client.get("/api/_test_crash")
            assert r.status_code == 500 and "x-secret-token-777" not in r.text and "boom" not in r.text
    finally:
        app.router.routes[:] = [rt for rt in app.router.routes if getattr(rt, "path", "") not in ("/api/_test_leaky", "/api/_test_crash")]


def test_a_failed_post_saves_no_token(monkeypatch):
    import asyncio
    from datetime import date

    from app import publishing
    from app.schemas import Campaign, Platform, SocialPost

    monkeypatch.setattr(config, "META_ACCESS_TOKEN", TOKEN)

    async def direct(post):
        raise httpx.ConnectError(f"failed for https://graph.facebook.com/x?access_token={TOKEN}")

    monkeypatch.setitem(publishing.DIRECT, Platform.FACEBOOK, (lambda: True, direct))
    camp = Campaign(start_date=date(2026, 11, 1), days=1, platforms=[Platform.FACEBOOK])
    post = SocialPost(campaign_id=camp.id, day=0, platform=Platform.FACEBOOK, pillar="x", headline="h", caption="c",
                      publish_at="2026-11-01T10:00:00Z")
    camp.posts = [post]
    try:
        asyncio.run(publishing._publish(post, camp))
    except Exception:  # noqa: BLE001
        pass
    assert post.publish_error and TOKEN not in post.publish_error


def test_the_access_cookie_is_not_the_key(monkeypatch):
    monkeypatch.setattr(config, "ACCESS_KEY", "s3cret-key")
    with TestClient(app) as client:
        resp = client.post("/api/access/login", json={"key": "s3cret-key"})
        assert "s3cret-key" not in resp.headers["set-cookie"]
        assert client.get("/api/campaigns").status_code == 200  # the derived cookie still works
        client.cookies.clear()
        client.cookies.set("monoplus_access", "s3cret-key")  # the raw key isn't accepted as a cookie
        assert client.get("/api/campaigns").status_code == 401
