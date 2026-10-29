"""Under heavy use the app turns work away politely instead of falling over."""
import asyncio
import time
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app import config
from app.agents import competitors, pipeline, reels
from app.agents.reels import render
from app.main import REEL_JOBS, app
from test_features import _campaign_with_posts, client, offline  # noqa: F401 - fixtures


def test_a_reel_renders_in_a_worker_process(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "REEL_PROCESSES", True)
    kit = _campaign_with_posts(days=1).brand
    scenes = [reels.Scene(kind="hook", text="Worker process"), reels.Scene(kind="cta", text="Shop now", sub="example.com")]
    out = tmp_path / "reel.mp4"
    seconds = asyncio.run(render.render_elsewhere(kit, scenes, out, None, None, 0.5, None, ""))
    assert seconds > 0 and out.read_bytes()[4:8] == b"ftyp"
    assert not list(tmp_path.glob("*.part.mp4"))  # its temporary file is its own and is gone


def test_one_reel_per_post_at_a_time_and_a_full_queue_says_busy(client, monkeypatch):  # noqa: F811
    post = _campaign_with_posts(days=1).posts[0]
    REEL_JOBS.clear()
    REEL_JOBS["x"] = {"status": "running", "post_id": post.id, "at": datetime.now(timezone.utc)}
    r = client.post(f"/api/posts/{post.id}/reel?background=true")
    assert r.status_code == 409 and "already being made" in r.json()["detail"]
    for i in range(config.REEL_RENDERS + reels.MAX_WAITING):
        REEL_JOBS[f"q{i}"] = {"status": "running", "post_id": f"other{i}", "at": REEL_JOBS["x"]["at"]}
    other = _campaign_with_posts(days=1).posts[0]
    r = client.post(f"/api/posts/{other.id}/reel?background=true")
    assert r.status_code == 429 and r.headers["retry-after"] == "60"
    REEL_JOBS.clear()


def test_too_many_campaigns_at_once_get_a_polite_busy(monkeypatch):
    monkeypatch.setattr(config, "CAMPAIGNS_AT_ONCE", 1)
    monkeypatch.setattr(config, "CAMPAIGN_QUEUE", 0)

    async def slow(job, campaign, raw, per_day):
        await asyncio.sleep(5)

    monkeypatch.setattr(pipeline, "run_campaign", slow)
    monkeypatch.setattr(pipeline, "_generating", None)
    with TestClient(app) as c:
        first = c.post("/api/campaigns", json={"input": "https://one.example", "days": 1})
        second = c.post("/api/campaigns", json={"input": "https://two.example", "days": 1})
        assert first.status_code == 202
        assert second.status_code == 429 and "Lots of campaigns" in second.json()["detail"]
        for t in list(pipeline._running):
            t.cancel()
        time.sleep(0.1)


def test_a_web_address_is_never_a_competitors_name():
    html = '<a href="https://www.borjan.com.pk/">www.borjan.com.pk/</a> <a href="https://www.servis.pk/">Servis Shoes</a>'
    found = competitors.candidates_from_article(html, "https://blog.example/top-shoe-brands", {"bata"})
    assert found["borjan.com.pk"][0] == "" and found["servis.pk"][0] == "Servis Shoes"
    assert competitors.looks_like_address("shopecs.com/") and not competitors.looks_like_address("Hush Puppies")


@pytest.mark.parametrize("name", ["health", "list_campaigns", "get_campaign", "get_job"])
def test_cheap_reads_dont_queue_for_the_thread_pool(name):
    import inspect

    import app.main as main

    assert inspect.iscoroutinefunction(getattr(main, name))
