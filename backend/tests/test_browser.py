"""Posting from MonoPlus's own browser, checked against a local imitation of LinkedIn's composer.

The real sites can't be used in tests (they need your accounts), so this page offers the same
kinds of controls: a "Start a post" button, an "Add media" button that opens a file chooser, a
rich text box and a Post button. It proves the mechanics: attaching files, keeping line breaks,
leaving the post for review, and pressing Post.
"""
import asyncio
import functools
import http.server
import json
import threading

import pytest
from PIL import Image

from app.schemas import Platform
from app.social import browser

pytestmark = pytest.mark.skipif(not browser.available(), reason="Playwright isn't installed")

PAGE = """<!doctype html><html><body>
<button onclick="document.getElementById('modal').hidden=false">Start a post</button>
<div id="modal" hidden>
  <button aria-label="Add media" onclick="document.getElementById('f').click()">Add media</button>
  <input id="f" type="file" multiple hidden onchange="window.files = Array.from(this.files).map(f => f.name)">
  <div role="textbox" contenteditable="true" id="box" style="min-height:40px;border:1px solid"></div>
  <button onclick="localStorage.setItem('posted', JSON.stringify({text: document.getElementById('box').innerText, files: window.files || []}))">Post</button>
</div></body></html>"""


@pytest.fixture
def site(tmp_path):
    (tmp_path / "feed.html").write_text(PAGE, encoding="utf-8")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(tmp_path))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/feed.html"
    server.shutdown()


def test_fill_in_for_review_then_post(site, tmp_path, monkeypatch):
    monkeypatch.setitem(browser.HOME, Platform.LINKEDIN, site)
    image = tmp_path / "post.png"
    Image.new("RGB", (400, 400), "teal").save(image)
    poster = browser.BrowserPoster(profile=tmp_path / "profile", headless=True)
    caption = "New in: Linen Kurta\n\n#Linen #NewIn"

    async def go():
        note = await poster.post(Platform.LINKEDIN, caption, [image], submit=False)
        assert "Check it and press Post" in note

        def inspect():
            page = poster._ctx.pages[-1]
            return page.evaluate("[document.getElementById('box').innerText, window.files, localStorage.getItem('posted')]")
        text, files, posted = await poster.run(inspect)
        assert files == ["post.png"] and "Linen Kurta" in text and "#Linen" in text and posted is None  # filled, not posted
        assert text.count("\n") >= 1  # line breaks kept

        note = await poster.post(Platform.LINKEDIN, caption, [image], submit=True)
        assert note.startswith("Posted on Linkedin")

        def read():
            page = poster._ctx.new_page()
            page.goto(site)
            return json.loads(page.evaluate("localStorage.getItem('posted')"))
        posted = await poster.run(read)
        assert posted["files"] == ["post.png"] and "Linen Kurta" in posted["text"]
        await poster.run(lambda: poster._ctx.close())

    asyncio.run(go())


def test_not_signed_in_is_said_plainly(tmp_path, monkeypatch):
    monkeypatch.setitem(browser.HOME, Platform.X, "about:blank")

    class FakePage:
        url = "https://x.com/i/flow/login"

        def goto(self, url):
            pass

    with pytest.raises(browser.BrowserPostError, match="not signed in to X"):
        browser._x(FakePage(), "hi", [], submit=False)


def test_browser_endpoints_answer(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app

    async def fake_status():
        return {"linkedin": True, "x": False, "facebook": False, "instagram": False}

    async def fake_login(platform):
        return None

    monkeypatch.setattr(browser.poster, "status", fake_status)
    monkeypatch.setattr(browser.poster, "login", fake_login)
    with TestClient(app) as client:
        assert client.get("/api/browser").json()["signed_in"]["linkedin"] is True
        assert client.post("/api/browser/login/linkedin").json()["opened"] is True
        assert client.post("/api/browser/login/myspace").status_code == 422
        assert client.put("/api/browser/scheduled", json={"enabled": True}).json()["scheduled"] is True
        client.put("/api/browser/scheduled", json={"enabled": False})
