"""Keys live only in the backend's .env: the web app can see what's connected but can't send, save
or read a key, and the Meta helper writes its token into .env without ever printing it."""
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


def test_the_page_sees_what_is_connected_but_never_a_key(monkeypatch):
    monkeypatch.setattr(config, "ACCESS_KEY", "")
    monkeypatch.setattr(config, "NEBIUS_API_KEY", "nb-secret-key-987654321")
    monkeypatch.setattr(config, "HF_TOKEN", "")
    with TestClient(app) as client:
        r = client.get("/api/connections")
        assert r.status_code == 200 and "nb-secret-key-987654321" not in r.text
        body = r.json()
        assert body["nebius"] == {"connected": True, "env": ["NEBIUS_API_KEY"]}
        assert body["huggingface"]["connected"] is False and body["huggingface"]["env"] == ["HF_TOKEN"]
        # Nothing on the API takes a key any more.
        assert client.put("/api/connections/keys", json={"nebius_api_key": "x"}).status_code in (404, 405)
        assert client.put("/api/connections/meta", json={"token": "x"}).status_code in (404, 405)
        assert client.delete("/api/connections/nebius").status_code in (404, 405)
    assert config.NEBIUS_API_KEY == "nb-secret-key-987654321"


def test_the_meta_helper_writes_the_page_token_into_env_and_never_prints_it(monkeypatch, tmp_path, capsys):
    env = tmp_path / ".env"
    env.write_text("# my settings\nNEBIUS_API_KEY=keep-me\nMETA_USER_TOKEN=short-user-token\nMETA_ACCESS_TOKEN=\n", encoding="utf-8")
    monkeypatch.setattr(connections, "ENV_FILE", env)
    monkeypatch.setenv("META_USER_TOKEN", "short-user-token")
    monkeypatch.setenv("META_APP_ID", "123")
    monkeypatch.setenv("META_APP_SECRET", "app-secret-xyz")
    seen = mock_meta(monkeypatch, [{"id": "1", "name": "Other Page", "access_token": "x"},
                                   {"id": "42", "name": "Outfitters", "access_token": PAGE_TOKEN,
                                    "instagram_business_account": {"id": "1789", "username": "outfitterspk"}}])
    assert connections.main(["meta"]) == 0
    out = capsys.readouterr().out
    assert "Outfitters" in out and "@outfitterspk" in out and "lasting" in out
    assert PAGE_TOKEN not in out and "app-secret-xyz" not in out and "short-user-token" not in out
    text = env.read_text(encoding="utf-8")
    assert f"META_ACCESS_TOKEN={PAGE_TOKEN}" in text and "META_PAGE_ID=42" in text and "INSTAGRAM_ACCOUNT_ID=1789" in text
    assert "# my settings" in text and "NEBIUS_API_KEY=keep-me" in text  # the rest of the file is untouched
    assert "META_USER_TOKEN=\n" in text  # the short-lived token is cleared once used
    assert text.count("META_ACCESS_TOKEN=") == 1
    assert all("app-secret-xyz" not in str(req.url) for req in seen)  # the secret went in a body, never a URL


def test_a_bad_meta_token_changes_nothing(monkeypatch, tmp_path, capsys):
    env = tmp_path / ".env"
    env.write_text("META_USER_TOKEN=bad\n", encoding="utf-8")
    monkeypatch.setattr(connections, "ENV_FILE", env)
    monkeypatch.setenv("META_USER_TOKEN", "bad")
    monkeypatch.delenv("META_APP_ID", raising=False)
    mock_meta(monkeypatch, [])
    assert connections.main(["meta"]) == 1
    assert "Invalid OAuth" in capsys.readouterr().out
    assert env.read_text(encoding="utf-8") == "META_USER_TOKEN=bad\n"


def test_checking_keys_says_ok_or_why_not_and_never_shows_them(monkeypatch):
    import asyncio

    monkeypatch.setattr(config, "NEBIUS_API_KEY", "nb-wrong")
    monkeypatch.setattr(config, "TAVILY_API_KEY", "")
    monkeypatch.setattr(config, "HEYGEN_API_KEY", "")
    monkeypatch.setattr(config, "HF_TOKEN", "")
    mock_meta(monkeypatch, [])
    results = dict(asyncio.run(connections.check_all()))
    assert "didn't accept" in results["Nemotron on Nebius (NEBIUS_API_KEY)"] and results["Tavily (TAVILY_API_KEY)"] == "not set"
    assert not any("nb-wrong" in r for r in results.values())


def test_connections_are_only_shown_to_this_computer(monkeypatch):
    monkeypatch.setattr(config, "ACCESS_KEY", "")
    with TestClient(app, client=("203.0.113.9", 5000)) as remote:
        assert remote.get("/api/connections").status_code == 403
