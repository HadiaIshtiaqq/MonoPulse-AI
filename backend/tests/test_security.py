"""Who may do what: posting to your accounts only from this computer (or with the key), and the
access key kept in an httpOnly cookie rather than the page's storage."""
from fastapi.testclient import TestClient

from app import config
from app.main import app


def test_posting_endpoints_refuse_other_computers(monkeypatch):
    monkeypatch.setattr(config, "ACCESS_KEY", "")
    with TestClient(app, client=("203.0.113.9", 5000)) as remote:
        for method, path in [("get", "/api/browser"), ("post", "/api/browser/login/linkedin"), ("post", "/api/posts/x1/publish"),
                             ("post", "/api/posts/x1/browser-post"), ("put", "/api/publishing/auto"), ("post", "/api/maintenance/cleanup")]:
            resp = getattr(remote, method)(path)
            assert resp.status_code == 403, path
            assert "computer" in resp.json()["detail"]
        # Without a key, nothing else is open to other computers either: campaigns, keys, research.
        resp = remote.get("/api/campaigns")
        assert resp.status_code == 403 and "access key" in resp.json()["detail"]
        assert remote.get("/api/health").status_code == 200
    with TestClient(app, client=("127.0.0.1", 5000)) as local:
        assert local.post("/api/maintenance/cleanup").status_code == 200


def test_the_key_opens_posting_from_elsewhere(monkeypatch):
    monkeypatch.setattr(config, "ACCESS_KEY", "s3cret")
    with TestClient(app, client=("203.0.113.9", 5000)) as remote:
        assert remote.post("/api/maintenance/cleanup").status_code == 401
        assert remote.post("/api/maintenance/cleanup", headers={"X-Access-Key": "s3cret"}).status_code == 200


def test_a_request_passed_on_from_elsewhere_is_never_treated_as_local(monkeypatch):
    """The web app forwards /api here, and a tunnel forwards to the web app, so the direct caller is this
    computer even for someone across the internet. Their forwarding headers make it "elsewhere"."""
    monkeypatch.setattr(config, "ACCESS_KEY", "")
    with TestClient(app, client=("127.0.0.1", 5000)) as proxied:
        for trusted in (False, True):
            monkeypatch.setattr(config, "TRUST_PROXY", trusted)
            for headers in ({"X-Forwarded-For": "203.0.113.9"}, {"X-Forwarded-For": "127.0.0.1, 203.0.113.9"},
                            {"CF-Connecting-IP": "198.51.100.4"}, {"Forwarded": "for=203.0.113.9;proto=https"},
                            {"X-Real-IP": "203.0.113.9"}):
                assert proxied.get("/api/campaigns", headers=headers).status_code == 403, headers
                assert proxied.post("/api/maintenance/cleanup", headers=headers).status_code == 403, headers
        # This computer's own browser, through the web app's forwarding, is still local.
        for headers in ({}, {"X-Forwarded-For": "127.0.0.1"}, {"X-Forwarded-For": "::ffff:127.0.0.1"}, {"X-Forwarded-For": "::1"}):
            assert proxied.get("/api/campaigns", headers=headers).status_code == 200, headers


def test_access_key_lives_in_an_httponly_cookie(monkeypatch):
    monkeypatch.setattr(config, "ACCESS_KEY", "s3cret")
    with TestClient(app) as client:
        assert client.get("/api/campaigns").status_code == 401
        assert client.post("/api/access/login", json={"key": "wrong"}).status_code == 401
        resp = client.post("/api/access/login", json={"key": "s3cret"})
        assert resp.status_code == 200
        cookie = resp.headers["set-cookie"].lower()
        assert "httponly" in cookie and "samesite=lax" in cookie
        assert client.get("/api/access").json() == {"required": True, "ok": True}
        assert client.get("/api/campaigns").status_code == 200  # the cookie alone is enough
        client.post("/api/access/logout")
        client.cookies.clear()
        assert client.get("/api/campaigns").status_code == 401


def test_old_profile_moves_out_of_the_project(tmp_path, monkeypatch):
    from app.social import browser

    old = config.DATA_DIR / "browser-profile"
    (old / "Default").mkdir(parents=True, exist_ok=True)
    (old / "Default" / "Cookies").write_bytes(b"x")
    new = tmp_path / "MonoPlus" / "browser-profile"
    monkeypatch.setattr(config, "BROWSER_PROFILE_DIR", new)
    browser.move_old_profile()
    assert not old.exists() and (new / "Default" / "Cookies").read_bytes() == b"x"
