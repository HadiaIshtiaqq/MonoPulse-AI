"""Humanizer v2, carousels, photo backgrounds, brand editing, export and webhook publishing."""
import asyncio
import io
import zipfile
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import config, publishing
from app.agents import humanizer, photos, pipeline, renderer
from app.llm import router
from app.schemas import Campaign, Platform, PostStatus, SocialPost
from app.store import store

from test_core import _kit


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(config, "NEBIUS_API_KEY", "")
    monkeypatch.setattr(config, "TAVILY_API_KEY", "")
    monkeypatch.setattr(config, "PEXELS_API_KEY", "")
    monkeypatch.setattr(store, "save", lambda: None)
    monkeypatch.setattr(store, "campaigns", {})
    monkeypatch.setattr(store, "research", {})
    from app.schemas import AppSettings
    monkeypatch.setattr(store, "settings", AppSettings())


@pytest.fixture
def client():
    from app.main import app
    with TestClient(app) as c:
        yield c


def _png_bytes(color=(200, 80, 40), size=(600, 400)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def _campaign_with_posts(days=4) -> Campaign:
    async def fake_ingest(raw, search_fn=None):
        return _kit()
    camp = Campaign(start_date=date(2026, 11, 1), days=days, platforms=[Platform.INSTAGRAM, Platform.LINKEDIN])
    job = pipeline.new_job(camp.id)
    orig = pipeline.ingest
    pipeline.ingest = fake_ingest
    try:
        asyncio.run(pipeline.run_campaign(job, camp, "x", posts_per_day=1))
    finally:
        pipeline.ingest = orig
    assert job.status == "done", job.error
    store.campaigns[camp.id] = camp
    return camp


# --------------------------------------------------------------------------- humanizer v2


def test_detects_blader_patterns():
    text = ("Great question! Let's dive in. It's not just a bakery, it's a lifestyle. Nestled in the heart of Austin, "
            "our shop serves as a testament to craft — truly pivotal.")
    ids = {p["id"] for p in humanizer.detect(text)}
    assert {"chatbot", "runup", "not_x_but_y", "sales", "copula", "ai_words", "dashes"} <= ids


def test_rule_pass_fixes_blader_and_lynote_vocab():
    out = humanizer.rule_pass("We utilize a methodology that serves as proof. Furthermore, it encompasses “everything” — subsequently we ship.")
    low = out.lower()
    for bad in ("utilize", "methodology", "serves as", "furthermore", "encompasses", "subsequently", "—", "“"):
        assert bad not in low
    assert "then we ship" in low


def test_fact_guard_rejects_changed_offer(monkeypatch):
    monkeypatch.setattr(config, "NEBIUS_API_KEY", "x")

    async def bad_rewrite(purpose, system, user, **kw):
        return "Grab a loaf this weekend, it's on sale!"  # dropped the price, date and handle

    monkeypatch.setattr(router, "complete", bad_rewrite)
    # "Not just X, it's Y" survives the rule pass, so the model rewrite runs.
    text = "It's not just bread, it's a ritual. Just $6 until 12/24, DM @bluebird."
    res = asyncio.run(humanizer.humanize(text, mode="standard", threshold=0))
    rejected = [s for s in res.steps if not s.accepted]
    assert rejected and "dropped" in rejected[0].note
    assert "$6" in res.text and "@bluebird" in res.text and "12/24" in res.text


def test_deep_mode_runs_translation_chain(monkeypatch):
    monkeypatch.setattr(config, "NEBIUS_API_KEY", "x")
    prompts = []

    async def fake(purpose, system, user, **kw):
        prompts.append(user[:40])
        if "Chinese" in user:
            return "中文 $6"
        if "Japanese" in user:
            return "日本語 $6"
        if "casual English" in user:
            return "Fresh sourdough, $6 a loaf. Come say hi."
        return "Fresh sourdough, $6 a loaf. Come by and say hi."

    monkeypatch.setattr(router, "complete", fake)
    res = asyncio.run(humanizer.humanize("Our sourdough is a game-changer at just $6!", mode="deep"))
    names = [s.name for s in res.steps]
    assert names[:4] == ["Original", "Rule pass", "Rewrite → Chinese", "Rewrite → Japanese"]
    assert "Back to English" in names and res.used_llm and "$6" in res.text
    assert res.after <= res.before


# --------------------------------------------------------------------------- carousels & rendering


def test_campaign_includes_rendered_carousels():
    camp = _campaign_with_posts(days=8)
    carousels = [p for p in camp.posts if p.format == "carousel"]
    assert carousels, "instagram/linkedin campaigns should include carousels"
    c = carousels[0]
    assert len(c.slides) >= 2 and len(c.image_urls) == len(c.slides) + 2  # cover + slides + CTA
    for url in c.image_urls:
        path = config.MEDIA_DIR / url.split("?")[0].removeprefix("/media/")
        assert Image.open(path).size == renderer.CAROUSEL_SIZE


@pytest.mark.parametrize("position", ["top", "center", "bottom"])
def test_photo_layout_with_upload(position):
    up = photos.save_upload(_png_bytes())
    post = SocialPost(campaign_id="t", day=0, platform=Platform.INSTAGRAM, headline="Fresh bread at 5am", publish_at=datetime.now(timezone.utc),
                      layout="photo", background=photos.background_from_upload(up["id"]), text_position=position, text_scale=1.3)
    img = renderer.render(_kit(), post)
    assert img.size == renderer.SIZES[Platform.INSTAGRAM]


def test_long_words_are_wrapped_inside_the_image():
    from PIL import ImageDraw
    img = Image.new("RGB", (400, 400))
    draw = ImageDraw.Draw(img)
    f = renderer.font(60)
    lines = renderer.wrap(draw, "Visit supercalifragilisticexpialidocious.example.com today", f, 300)
    assert all(draw.textlength(line, font=f) <= 300 for line in lines)
    assert "".join(lines).replace("-", "").replace(" ", "") == "Visitsupercalifragilisticexpialidocious.example.comtoday"  # nothing lost


def test_access_key_protects_api(client, monkeypatch):
    monkeypatch.setattr(config, "ACCESS_KEY", "s3cret")
    assert client.get("/api/campaigns").status_code == 401
    assert client.get("/api/campaigns", headers={"X-Access-Key": "wrong"}).status_code == 401
    assert client.get("/api/campaigns", headers={"X-Access-Key": "s3cret"}).status_code == 200
    assert client.get("/api/campaigns?key=s3cret").status_code == 200  # for download links
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/access").json() == {"required": True, "ok": False}
    assert client.get("/api/access", headers={"X-Access-Key": "s3cret"}).json() == {"required": True, "ok": True}


@pytest.mark.parametrize("url", ["http://127.0.0.1:8000/api/health", "http://localhost/", "http://10.0.0.5/", "http://169.254.169.254/latest/meta-data", "file:///etc/passwd"])
def test_website_reader_refuses_internal_addresses(url):
    from app.netguard import UnsafeURL, assert_public
    with pytest.raises(UnsafeURL):
        assert_public(url)


def test_campaign_from_internal_url_fails_safely():
    from app.scraper import ingestor
    from app.netguard import UnsafeURL
    with pytest.raises(UnsafeURL):
        asyncio.run(ingestor.ingest("http://127.0.0.1:8000/api/campaigns"))


def test_double_publish_is_blocked(fake_apis):
    camp = _campaign_with_posts()
    post = _post_for(camp, Platform.INSTAGRAM, "single")

    async def both():
        return await asyncio.gather(publishing.publish_post(post, camp), publishing.publish_post(post, camp), return_exceptions=True)

    results = asyncio.run(both())
    assert sum(isinstance(r, publishing.PublishError) for r in results) == 1
    assert [u for _, u in fake_apis.calls].count("https://graph.facebook.com/v21.0/ig1/media_publish") == 1


def test_interrupted_research_goes_back_to_queue():
    from app.agents import research
    from app.schemas import ResearchTask
    task = ResearchTask(topic="bakery trends", status="running")
    store.research[task.id] = task

    async def start_then_stop():
        gen = research.execute(task)
        await gen.__anext__()  # first event, then the viewer closes the page
        await gen.aclose()

    asyncio.run(start_then_stop())
    assert task.status == "retry" and "background" in task.error


def test_upload_rejects_non_images_and_path_tricks():
    with pytest.raises(ValueError):
        photos.save_upload(b"not an image")
    for bad in ("../secrets.png", "logo_x.png", "up_..\\x.png"):
        with pytest.raises(KeyError):
            photos.upload_path(bad)


# --------------------------------------------------------------------------- API flows


def test_brand_edit_logo_and_rerender(client):
    camp = _campaign_with_posts()
    before = camp.posts[0].image_url
    up = client.post("/api/uploads", files={"file": ("logo.png", _png_bytes((10, 10, 200), (300, 300)), "image/png")}).json()
    r = client.patch(f"/api/campaigns/{camp.id}/brand", json={"primary_color": "#112233", "name": "Bluebird Co", "logo_upload_id": up["id"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["brand"]["primary_color"] == "#112233" and body["brand"]["logo_url"].startswith("/media/logo_")
    assert body["posts"][0]["image_url"] != before  # re-rendered with the new kit
    assert client.patch(f"/api/campaigns/{camp.id}/brand", json={"primary_color": "blue"}).status_code == 422


def test_post_editing_controls(client):
    camp = _campaign_with_posts()
    post = next(p for p in camp.posts if p.format == "single")
    assert client.patch(f"/api/posts/{post.id}", json={"layout": "photo"}).status_code == 422  # needs a photo first
    up = client.post("/api/uploads", files={"file": ("bg.png", _png_bytes(), "image/png")}).json()
    r = client.post(f"/api/posts/{post.id}/background", json={"source": "upload", "upload_id": up["id"]}).json()
    assert r["layout"] == "photo" and r["background"]["source"] == "upload"
    r = client.patch(f"/api/posts/{post.id}", json={"text_position": "top", "text_scale": 1.2}).json()
    assert r["text_position"] == "top" and r["text_scale"] == 1.2
    r = client.patch(f"/api/posts/{post.id}", json={"clear_background": True}).json()
    assert r["background"] is None and r["layout"] == "bold"
    car = next(p for p in camp.posts if p.format == "carousel")
    r = client.patch(f"/api/posts/{car.id}", json={"slides": [{"headline": "One", "body": "First"}, {"headline": "Two", "body": ""}]}).json()
    assert len(r["slides"]) == 2 and len(r["image_urls"]) == 4


def test_export_zip(client):
    camp = _campaign_with_posts()
    r = client.get(f"/api/campaigns/{camp.id}/export")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = z.namelist()
    assert "posts.csv" in names
    assert sum(n.startswith("images/") for n in names) == sum(len(p.image_urls) for p in camp.posts)
    import csv
    rows = list(csv.DictReader(io.StringIO(z.read("posts.csv").decode())))
    assert len(rows) == len(camp.posts) and rows[0]["caption"] == sorted(camp.posts, key=lambda p: p.publish_at)[0].caption


class FakeAPIs:
    """Records every outgoing request and answers like the real platform APIs."""

    def __init__(self, fail_on: str | None = None):
        self.calls: list[tuple[str, str]] = []
        self.fail_on = fail_on
        self.n = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.calls.append((request.method, url.split("?")[0]))
        self.n += 1
        if self.fail_on and self.fail_on in url:
            return httpx.Response(400, json={"error": {"message": "Invalid OAuth access token"}})
        if "graph.facebook.com" in url:
            if url.split("?")[0].endswith("/photos"):
                return httpx.Response(200, json={"id": f"photo{self.n}", "post_id": f"page_post{self.n}"})
            if request.method == "GET" and "fields=images" in url:
                return httpx.Response(200, json={"images": [{"width": 1080, "source": f"https://scontent.fbcdn.net/p{self.n}.jpg"}]})
            if request.method == "GET" and "status_code" in url:
                return httpx.Response(200, json={"status_code": "FINISHED"})
            if request.method == "GET" and "permalink" in url:
                return httpx.Response(200, json={"permalink": "https://www.instagram.com/p/ABC123/"})
            return httpx.Response(200, json={"id": f"c{self.n}"})
        if "api.linkedin.com" in url and "initializeUpload" in url:
            return httpx.Response(200, json={"value": {"uploadUrl": f"https://www.linkedin.com/dms-uploads/u{self.n}", "image": f"urn:li:image:{self.n}"}})
        if "dms-uploads" in url:
            return httpx.Response(201)
        if "api.linkedin.com" in url and url.endswith("/posts"):
            return httpx.Response(201, headers={"x-restli-id": "urn:li:share:999"})
        if "api.x.com/2/media/upload" in url:
            return httpx.Response(200, json={"data": {"id": f"m{self.n}"}})
        if "api.x.com/2/tweets" in url:
            return httpx.Response(201, json={"data": {"id": "1855"}})
        return httpx.Response(404)


@pytest.fixture
def fake_apis(monkeypatch):
    from app.social import base
    fake = FakeAPIs()
    monkeypatch.setattr(base, "transport", httpx.MockTransport(fake))
    for key, val in {"META_ACCESS_TOKEN": "t", "META_PAGE_ID": "page1", "INSTAGRAM_ACCOUNT_ID": "ig1",
                     "LINKEDIN_ACCESS_TOKEN": "t", "LINKEDIN_AUTHOR_URN": "urn:li:organization:5",
                     "X_USER_ACCESS_TOKEN": "t", "PUBLIC_API_URL": "http://localhost:8000"}.items():
        monkeypatch.setattr(config, key, val)
    return fake


def _post_for(camp: Campaign, platform: Platform, fmt: str) -> SocialPost:
    return next(p for p in camp.posts if p.platform is platform and p.format == fmt)


def test_not_connected_returns_400(client):
    camp = _campaign_with_posts()
    r = client.post(f"/api/posts/{camp.posts[0].id}/publish")
    assert r.status_code == 400 and "isn't connected" in r.json()["detail"]
    status = client.get("/api/publishing").json()
    assert status["connected"] == {"instagram": False, "facebook": False, "linkedin": False, "x": False}
    assert "token" not in str(status).lower()  # never exposes secrets


def test_instagram_carousel_direct_post_stages_images_on_page(client, fake_apis):
    camp = _campaign_with_posts(days=8)
    post = _post_for(camp, Platform.INSTAGRAM, "carousel")
    r = client.post(f"/api/posts/{post.id}/publish")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "PUBLISHED" and body["published_via"] == "direct"
    assert body["remote_url"] == "https://www.instagram.com/p/ABC123/"
    paths = [u for _, u in fake_apis.calls]
    n = len(post.image_urls)
    # localhost API -> each slide staged as an unpublished Page photo, then children, carousel container, publish
    assert paths.count("https://graph.facebook.com/v21.0/page1/photos") == n
    assert paths.count("https://graph.facebook.com/v21.0/ig1/media") == n + 1
    assert paths[-2] == "https://graph.facebook.com/v21.0/ig1/media_publish"
    assert client.post(f"/api/posts/{post.id}/publish").status_code == 409  # can't double-post


def test_instagram_uses_public_url_when_deployed(client, fake_apis, monkeypatch):
    monkeypatch.setattr(config, "PUBLIC_API_URL", "https://api.monoplus.app")
    camp = _campaign_with_posts()
    post = _post_for(camp, Platform.INSTAGRAM, "single")
    assert client.post(f"/api/posts/{post.id}/publish").status_code == 200
    paths = [u for _, u in fake_apis.calls]
    assert "https://graph.facebook.com/v21.0/page1/photos" not in paths  # no staging needed
    assert (config.MEDIA_DIR / post.image_urls[0].split("?")[0].removeprefix("/media/")).with_suffix(".jpg").exists()


def test_linkedin_and_x_direct_posts(client, fake_apis):
    camp = Campaign(start_date=date(2026, 11, 1), days=3, platforms=[Platform.LINKEDIN, Platform.X])
    asyncio.run(_run(camp))
    li = camp.posts[0]
    r = client.post(f"/api/posts/{li.id}/publish").json()
    assert r["remote_url"] == "https://www.linkedin.com/feed/update/urn:li:share:999"
    xp = next(p for p in camp.posts if p.platform is Platform.X)
    r = client.post(f"/api/posts/{xp.id}/publish").json()
    assert r["remote_url"] == "https://x.com/i/web/status/1855"
    hosts = {u.split("/")[2] for _, u in fake_apis.calls}
    assert {"api.linkedin.com", "www.linkedin.com", "api.x.com"} <= hosts


def test_linkedin_commentary_escaping():
    from app.social import linkedin
    p = SocialPost(campaign_id="c", day=0, platform=Platform.LINKEDIN, caption="Big news (finally) for #bakers", hashtags=["#Sourdough"],
                   publish_at=datetime.now(timezone.utc))
    text = linkedin.commentary(p)
    assert "\\(finally\\)" in text and "{hashtag|\\#|bakers}" in text and "{hashtag|\\#|Sourdough}" in text


def test_publish_error_is_recorded(client, fake_apis):
    fake_apis.fail_on = "media_publish"
    camp = _campaign_with_posts()
    post = _post_for(camp, Platform.INSTAGRAM, "single")
    r = client.post(f"/api/posts/{post.id}/publish")
    assert r.status_code == 502 and "Invalid OAuth access token" in r.json()["detail"]
    assert post.status is not PostStatus.PUBLISHED and "Invalid OAuth" in post.publish_error


def test_scheduler_auto_publishes_due_approved_posts(client, fake_apis):
    camp = _campaign_with_posts()
    due, later, draft = camp.posts[0], camp.posts[1], camp.posts[2]
    due.status, due.publish_at = PostStatus.APPROVED, datetime.now(timezone.utc) - timedelta(minutes=1)
    later.status, later.publish_at = PostStatus.APPROVED, datetime.now(timezone.utc) + timedelta(days=1)
    draft.publish_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    assert asyncio.run(publishing.publish_due()) == 0  # auto-publish off
    assert client.put("/api/publishing/auto", json={"enabled": True}).json()["auto_publish"] is True
    assert asyncio.run(publishing.publish_due()) == 1
    assert due.status is PostStatus.PUBLISHED and later.status is PostStatus.APPROVED and draft.status is PostStatus.DRAFT


async def _run(camp: Campaign):
    async def fake_ingest(raw, search_fn=None):
        return _kit()
    orig = pipeline.ingest
    pipeline.ingest = fake_ingest
    try:
        job = pipeline.new_job(camp.id)
        await pipeline.run_campaign(job, camp, "x", posts_per_day=1)
    finally:
        pipeline.ingest = orig
    store.campaigns[camp.id] = camp


def test_webhook_signature():
    body = b'{"a":1}'
    sig = publishing.sign("secret", body)
    import hashlib
    import hmac
    assert sig == "sha256=" + hmac.new(b"secret", body, hashlib.sha256).hexdigest()


def test_humanize_endpoint_returns_trace(client):
    r = client.post("/api/humanize", json={"text": "Let's dive in! Our cutting-edge cafe is a game-changer — truly.", "mode": "light"}).json()
    assert r["mode"] == "light" and r["after"] < r["before"]
    assert [s["name"] for s in r["steps"]] == ["Original", "Rule pass"]
    assert r["patterns_before"] and len(r["patterns_after"]) < len(r["patterns_before"])


def test_redraw_undo_approve_and_media_cleanup(client, monkeypatch):
    import os
    import time

    from app import config, media_gc

    c = _campaign_with_posts(days=2)
    c.design_version = 0
    old_images = [p.image_url for p in c.posts]
    r = client.post(f"/api/campaigns/{c.id}/redraw")
    assert r.status_code == 200 and r.json()["design_version"] == config.DESIGN_VERSION
    assert [p.image_url for p in c.posts] != old_images  # drawn again under fresh names

    approved = client.post(f"/api/campaigns/{c.id}/approve-all").json()["approved_ids"]
    assert len(approved) == len(c.posts)
    client.post(f"/api/campaigns/{c.id}/undo-approve", json={"post_ids": approved[:2]})
    assert sum(p.status is PostStatus.DRAFT for p in c.posts) == 2

    stale = config.MEDIA_DIR / "stale_unused.png"
    stale.write_bytes(_png_bytes())
    fresh = config.MEDIA_DIR / "fresh_unused.png"
    fresh.write_bytes(_png_bytes())
    two_days_ago = time.time() - 3 * 24 * 3600
    os.utime(stale, (two_days_ago, two_days_ago))
    used = config.MEDIA_DIR / c.posts[0].image_url.split("?")[0].removeprefix("/media/")
    os.utime(used, (two_days_ago, two_days_ago))
    media_gc.cleanup()
    assert not stale.exists() and fresh.exists() and used.exists()  # only old, unused files go
