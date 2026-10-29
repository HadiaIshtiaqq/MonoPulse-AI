"""Connecting services in the app: checked before saving, kept outside the project, never sent back."""
import json

import httpx
from fastapi.testclient import TestClient

from app import config, connections
from app.main import app

PAGE_TOKEN = "EAAPAGEtokenNEVERshown1234567890abcdef"


def mock_meta(monkeypatch, pages):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/oauth/access_token"):
            return httpx.Response(200, json={"access_token": "long-lived-user-token"})
        if request.url.path.endswith("/me/accounts"):
            if request.headers.get("authorization") == "Bearer bad":
                return httpx.Response(400, json={"error": {"message": "Invalid OAuth access token."}})
            return httpx.Response(200, json={"data": pages})
        if request.url.path.endswith("/models"):
            ok = request.headers.get("authorization") == "Bearer nb-good-key-123"
            return httpx.Response(200 if ok else 401, json={"data": []})
        return httpx.Response(404)

    real = httpx.AsyncClient
    monkeypatch.setattr(connections.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    return seen


def test_instagram_connects_through_the_official_api_and_the_token_never_comes_back(monkeypatch):
    for k in ("META_ACCESS_TOKEN", "META_PAGE_ID", "INSTAGRAM_ACCOUNT_ID", "META_PAGE_NAME", "INSTAGRAM_USERNAME"):
        monkeypatch.setattr(config, k, "")
    monkeypatch.setattr(config, "ACCESS_KEY", "")
    seen = mock_meta(monkeypatch, [{"id": "1", "name": "Other Page", "access_token": "x"},
                                   {"id": "42", "name": "Outfitters", "access_token": PAGE_TOKEN,
                                    "instagram_business_account": {"id": "1789", "username": "outfitterspk"}}])
    with TestClient(app) as client:
        r = client.put("/api/connections/meta", json={"token": "short-user-token", "app_id": "123", "app_secret": "app-secret-xyz"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["meta"]["connected"] and body["meta"]["instagram"] == "outfitterspk" and body["result"]["lasting"]
        assert PAGE_TOKEN not in r.text and "app-secret-xyz" not in r.text
        assert PAGE_TOKEN not in client.get("/api/connections").text
    assert config.META_ACCESS_TOKEN == PAGE_TOKEN and config.INSTAGRAM_ACCOUNT_ID == "1789" and config.META_PAGE_ID == "42"
    saved = json.loads(connections.path().read_text(encoding="utf-8"))
    assert saved["META_ACCESS_TOKEN"] == PAGE_TOKEN and "app_secret" not in json.dumps(saved)
    assert all("app-secret-xyz" not in str(req.url) for req in seen)  # the secret went in a body, never a URL
    assert not str(connections.path()).startswith(str(config.DATA_DIR.parent.parent / "MonoPlus" / "backend"))


def test_a_bad_token_or_key_is_refused_and_nothing_is_saved(monkeypatch):
    monkeypatch.setattr(config, "META_ACCESS_TOKEN", "")
    monkeypatch.setattr(config, "NEBIUS_API_KEY", "")
    monkeypatch.setattr(config, "ACCESS_KEY", "")
    mock_meta(monkeypatch, [])
    with TestClient(app) as client:
        r = client.put("/api/connections/meta", json={"token": "bad"})
        assert r.status_code == 400 and "Invalid OAuth" in r.json()["detail"]
        r = client.put("/api/connections/keys", json={"nebius_api_key": "nb-wrong"})
        assert r.status_code == 400 and not config.NEBIUS_API_KEY
        r = client.put("/api/connections/keys", json={"nebius_api_key": "nb-good-key-123"})
        assert r.status_code == 200 and r.json()["nebius"]["connected"] and "nb-good-key-123" not in r.text
        assert config.NEBIUS_API_KEY == "nb-good-key-123"
        assert client.delete("/api/connections/nebius").json()["nebius"]["connected"] is False
    assert not config.NEBIUS_API_KEY


def test_connections_are_only_managed_from_this_computer(monkeypatch):
    monkeypatch.setattr(config, "ACCESS_KEY", "")
    with TestClient(app, client=("203.0.113.9", 5000)) as remote:
        assert remote.get("/api/connections").status_code == 403
        assert remote.put("/api/connections/keys", json={"nebius_api_key": "x"}).status_code == 403
