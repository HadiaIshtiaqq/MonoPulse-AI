"""UGC-style video ads: honest scripts, the built-in phone-style video, and the HeyGen presenter path."""
import time

import httpx

from app import config
from app.agents import reels, ugc, ugc_video
from app.schemas import Product
from test_core import _kit
from test_features import _campaign_with_posts, _png_bytes, client, offline  # noqa: F401 - fixtures


def test_scripts_use_only_real_facts_and_never_speak_as_a_customer():
    kit = _kit()
    kit.value_props = ["Free delivery in Austin", "Baked fresh every morning since 1998 with love and patience"]
    p = Product(name="Seeded Sourdough", price="$9", was_price="$12", url="https://b.example/p", image_url="https://b.example/p.jpg")
    for fmt in ugc.FORMATS:
        lines = ugc.template_script(kit, p, fmt)
        text = " ".join(lines)
        assert 3 <= len(lines) <= 7 and "Seeded Sourdough" in text, (fmt, lines)
        assert not any(w in text.lower() for w in ("i've been", "i used", "my skin", "changed my life", "5 stars"))
    reasons = ugc.template_script(kit, p, "reasons")
    assert reasons[0].startswith("3 reasons") and "Now $9, down from $12" in reasons[1] and "Free delivery in Austin" in " ".join(reasons)


def test_formats_fit_the_brand():
    kit = _kit()
    keys = {f["key"] for f in ugc.formats_for(kit)}
    assert "taste" in keys and "outfit" not in keys  # a bakery gets a taste test, not an outfit check


def test_a_builtin_ugc_ad_end_to_end(client, monkeypatch):  # noqa: F811
    monkeypatch.setattr(ugc_video, "FPS", 4)
    c = _campaign_with_posts(days=1)
    photo = config.MEDIA_DIR / "up_ugcphoto.png"
    photo.write_bytes(_png_bytes(size=(900, 1200)))
    c.brand.products = [Product(name="Seeded Sourdough", price="$9", url="https://b.example/p", image_url="/media/up_ugcphoto.png")]
    overview = client.get(f"/api/campaigns/{c.id}/ugc").json()
    assert overview["products"][0]["name"] and overview["formats"] and overview["heygen"] is False
    script = client.post(f"/api/campaigns/{c.id}/ugc/script", json={"product": 0, "format": "pov"}).json()
    assert script["lines"][0].startswith("POV")
    r = client.post(f"/api/campaigns/{c.id}/ugc", json={"product": 0, "format": "pov", "lines": script["lines"]})
    assert r.status_code == 202, r.text
    job = r.json()["job_id"]
    for _ in range(120):
        j = client.get(f"/api/ugc-jobs/{job}").json()
        if j["status"] != "running":
            break
        time.sleep(0.5)
    assert j["status"] == "done", j
    ad = j["result"]
    video = client.get(ad["video_url"])
    assert video.status_code == 200 and video.content[4:8] == b"ftyp" and ad["seconds"] > 3
    post = c.posts[0]
    assert client.post(f"/api/campaigns/{c.id}/ugc/{ad['id']}/attach", json={"post_id": post.id}).status_code == 200
    assert post.video_url == ad["video_url"]
    assert client.post(f"/api/campaigns/{c.id}/ugc", json={"product": 0, "lines": ["x"], "engine": "avatar", "avatar_id": "a"}).status_code == 409
    assert client.delete(f"/api/campaigns/{c.id}/ugc/{ad['id']}").status_code == 204 and not c.ugc_ads


def test_heygen_presenter_flow(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "HEYGEN_API_KEY", "hg-key-123")
    real_sleep = ugc.asyncio.sleep
    monkeypatch.setattr(ugc.asyncio, "sleep", lambda s: real_sleep(0))  # no 8-second waits in tests
    calls = []
    states = iter(["processing", "completed"])

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path, request.headers.get("x-api-key")))
        if request.url.path == "/v3/assets":
            return httpx.Response(200, json={"data": {"asset_id": "asset_1"}})
        if request.url.path == "/v3/videos" and request.method == "POST":
            body = __import__("json").loads(request.content)
            assert body["type"] == "avatar" and body["aspect_ratio"] == "9:16" and body["background"] == {"type": "image", "asset_id": "asset_1"}
            return httpx.Response(200, json={"data": {"video_id": "v_1", "status": "waiting"}})
        if request.url.path == "/v3/videos/v_1":
            s = next(states)
            return httpx.Response(200, json={"data": {"status": s, "video_url": "https://cdn.heygen.example/v.mp4" if s == "completed" else None}})
        if request.url.host == "cdn.heygen.example":
            return httpx.Response(200, content=b"\x00\x00\x00\x18ftypmp42video")
        return httpx.Response(404)

    real = httpx.AsyncClient
    monkeypatch.setattr(ugc.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    photo = tmp_path / "p.png"
    photo.write_bytes(_png_bytes())
    out = tmp_path / "ad.mp4"
    import asyncio

    asyncio.run(ugc.heygen_video(str(photo), "look_1", "POV: you just found it", out, tmp_path / "ad.jpg"))
    assert out.read_bytes()[4:8] == b"ftyp"
    assert all(key == "hg-key-123" for m, path, key in calls if "heygen.example" not in path and path.startswith("/v3"))
    assert ("POST", "/v3/assets", "hg-key-123") in calls


def test_videos_share_render_slots():
    assert reels.render_slots is reels._render_slots
