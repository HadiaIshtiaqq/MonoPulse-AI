"""The paths that run when Nemotron is configured, exercised with a stand-in model.

The rest of the suite runs offline on the rule-based fallbacks. These tests switch the model on
and answer like Nemotron would (JSON in the agreed shape), so the code that sends prompts and
reads replies is exercised too: copywriting, reel scripts, caption languages and rewrites. A
model that misbehaves (wrong counts, invented facts, errors) must never break a campaign.
"""
import asyncio
import json

import pytest

from app import config
from app.agents import reels, strategist
from app.llm import LLMError, router
from app.schemas import Platform

from test_core import _kit
from test_features import _campaign_with_posts, client, offline  # noqa: F401 - fixtures


@pytest.fixture
def model(monkeypatch):
    """Turn the model on and answer each purpose the way Nemotron is asked to."""
    monkeypatch.setattr(config, "NEBIUS_API_KEY", "test-key")
    calls: list[tuple[str, str]] = []
    replies: dict[str, object] = {}

    async def complete_json(purpose, system, user, **kw):
        calls.append((purpose, user))
        reply = replies.get(purpose)
        if isinstance(reply, Exception):
            raise reply
        if callable(reply):
            return reply(user)
        if reply is not None:
            return reply
        raise LLMError(f"no stand-in reply for {purpose}")

    async def complete(purpose, system, user, **kw):
        return json.dumps(await complete_json(purpose, system, user, **kw))

    monkeypatch.setattr(router, "complete_json", complete_json)
    monkeypatch.setattr(router, "complete", complete)
    return calls, replies


def test_reel_script_follows_the_plan_and_the_language(model):
    calls, replies = model
    replies["reel_script"] = {"hook": "Three you'll want today", "scenes": ["One", "Two", "Three"], "cta": "Which is yours?"}
    kit = _kit()
    plan = reels.Plan("products", "3 picks", ["a", "b", "c"], [(None, "", "")] * 3, ["1/3", "2/3", "3/3"], ["", "", ""],
                      "Which one's yours?", "bluebird.example", brief="A showcase")
    post = _campaign_with_posts(days=1).posts[0]
    out, used = asyncio.run(reels.write_script(kit, post, plan, reels.STYLES["punch"], "roman"))
    assert used and out.hook == "Three you'll want today" and out.lines == ["One", "Two", "Three"]
    assert "Roman Urdu" in calls[-1][1] and "A showcase" in calls[-1][1]  # the story and language reach the model
    # A reply with the wrong number of scenes keeps the planned lines rather than misplacing words.
    replies["reel_script"] = {"hook": "Hi", "scenes": ["Only one"], "cta": "Bye"}
    out, _ = asyncio.run(reels.write_script(kit, post, plan, None))
    assert out.lines == ["One", "Two", "Three"] or out.lines == ["a", "b", "c"]
    # A model error falls back to the rule-based story.
    replies["reel_script"] = LLMError("timeout")
    plan2 = reels.Plan("products", "3 picks", ["a"], [(None, "", "")], ["1/1"], [""], "End", "x", brief="b")
    out, used = asyncio.run(reels.write_script(kit, post, plan2, None))
    assert not used and out.hook == "3 picks"


def test_campaign_copy_written_by_the_model(model):
    calls, replies = model
    kit = _kit()

    def write(user: str):
        slots = json.loads(user.split("SLOTS:\n", 1)[1])
        return [{"slot": s["slot"], "headline": f"Fresh idea {s['slot']}", "caption": f"Caption for {s['platform']} ({s['caption_shape']})",
                 "cta": "Order now"} for s in slots]

    replies["copywriting"] = write
    strategy = strategist.fallback_strategy(kit, [], 1)
    slots = strategist.plan_slots(strategy, [], [Platform.INSTAGRAM, Platform.X], 3, 1)
    copies = asyncio.run(strategist.write_all(kit, strategy, slots))
    assert all(c["caption"].startswith("Caption for") for c in copies)
    assert any("caption_shape" in u for p, u in calls if p == "copywriting")  # each slot carries its shape


def test_caption_language_rewrite_keeps_facts(client, model):  # noqa: F811
    calls, replies = model
    c = _campaign_with_posts(days=1)
    post = c.posts[0]
    original = post.original_caption or post.caption  # languages always start from the post's own draft
    replies["rewrite"] = lambda user: {"caption": "Yeh dekho! " + original}
    r = client.post(f"/api/posts/{post.id}/caption-language", json={"language": "roman"}).json()
    assert r["rewritten"] and r["post"]["caption"].startswith("Yeh dekho!")
    # A rewrite that drops the brand name is refused; the caption gets the offline treatment instead.
    replies["rewrite"] = {"caption": "Kuch bhi"}
    r = client.post(f"/api/posts/{post.id}/caption-language", json={"language": "roman"}).json()
    assert not r["rewritten"] and original in r["post"]["caption"]


def test_a_full_reel_with_the_model_on(client, model, monkeypatch):  # noqa: F811
    monkeypatch.setattr(reels.render, "FPS", 2)
    calls, replies = model
    replies["reel_script"] = lambda user: {"hook": "Meet Bluebird", "scenes": ["Fact one", "Fact two"], "cta": "Come say hi"}
    replies["humanize"] = LLMError("no humanizer stand-in")  # the humanizer's model pass failing must not matter
    c = _campaign_with_posts(days=1)
    r = client.post(f"/api/posts/{c.posts[0].id}/reel", json={"topic": "story"})
    assert r.status_code == 200, r.text
    assert r.json()["post"]["reel_scenes"][0]["text"] == "Meet Bluebird"
