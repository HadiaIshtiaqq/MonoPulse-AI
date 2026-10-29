"""Campaigns stay tidy: tracking tags never make one site look like many, a failed campaign says why
and can be tried again, and making the same brand twice is offered the existing one first."""
from datetime import date

from app.agents import pipeline
from app.schemas import Campaign, CampaignStatus, Platform
from app.scraper.ingestor import clean_input, handle_name, source_key
from app.store import store
from test_features import _campaign_with_posts, client, offline  # noqa: F401 - fixtures


def test_tracking_tags_are_dropped_and_the_same_site_has_one_key():
    assert clean_input("https://outfitters.com.pk/?srsltid=AYCX9v") == "https://outfitters.com.pk/"
    assert clean_input("https://bata.com.pk/?gad_source=1&gclid=x&gbraid=y&color=red#top") == "https://bata.com.pk/?color=red"
    assert clean_input("khaadi.com/?utm_source=ig") == "khaadi.com/"
    assert clean_input("@the_bake_shop") == "@the_bake_shop"
    keys = {source_key(s) for s in ["https://www.outfitters.com.pk/?srsltid=a", "outfitters.com.pk", "https://outfitters.com.pk/?gclid=b"]}
    assert keys == {"outfitters.com.pk"}
    assert source_key("https://www.instagram.com/fitt.ote0/") == source_key("@fitt.ote0") == "@fitt.ote0"


def test_handles_with_numbers_keep_their_spelling():
    assert handle_name("fitt.ote0") == "@fitt.ote0"
    assert handle_name("the_bake_shop") == "The Bake Shop"


def test_a_failed_campaign_says_why_and_can_be_tried_again(client, monkeypatch):  # noqa: F811
    started = []

    def fake_start(req):
        started.append(req)
        c = Campaign(source_input=req.input, start_date=date.today(), days=req.days, platforms=req.platforms)
        store.campaigns[c.id] = c
        return c, type("J", (), {"id": "job1"})()

    monkeypatch.setattr(pipeline, "start", fake_start)
    failed = Campaign(source_input="https://bata.com.pk/", start_date=date.today(), days=7, platforms=[Platform.INSTAGRAM],
                      status=CampaignStatus.FAILED, error="bata.com.pk blocked automated access (403).", posts_per_day=2)
    store.campaigns[failed.id] = failed
    row = next(c for c in client.get("/api/campaigns").json() if c["id"] == failed.id)
    assert row["name"] == "bata.com.pk" and row["error"].startswith("bata.com.pk blocked") and row["source"] == "bata.com.pk"
    r = client.post(f"/api/campaigns/{failed.id}/retry")
    assert r.status_code == 202, r.text
    assert started[0].input == "https://bata.com.pk/" and started[0].days == 7 and started[0].posts_per_day == 2
    assert failed.id not in store.campaigns  # the empty failed one is replaced, not kept beside the new one
    done = _campaign_with_posts(days=1)
    assert client.post(f"/api/campaigns/{done.id}/retry").status_code == 409


def test_making_the_same_brand_again_finds_the_existing_campaign(client):  # noqa: F811
    c = _campaign_with_posts(days=1)
    c.source_input = "https://www.tartinebakery.com/"
    found = client.get("/api/campaigns/existing", params={"input": "tartinebakery.com/?utm_source=google"}).json()
    assert [x["id"] for x in found] == [c.id] and found[0]["posts"] == len(c.posts)
    assert client.get("/api/campaigns/existing", params={"input": "sweetgreen.com"}).json() == []
