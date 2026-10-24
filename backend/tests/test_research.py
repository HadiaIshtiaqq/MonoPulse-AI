import asyncio
from datetime import date

import pytest

from app import config
from app.agents import memory, pipeline, research, strategist, trends
from app.llm import router
from app.schemas import Campaign, Platform, ResearchInsights, ResearchTask, TrendItem
from app.store import store

from test_core import _kit


@pytest.fixture(autouse=True)
def clean_store(monkeypatch):
    monkeypatch.setattr(config, "NEBIUS_API_KEY", "")
    monkeypatch.setattr(config, "TAVILY_API_KEY", "")
    monkeypatch.setattr(store, "save", lambda: None)
    monkeypatch.setattr(store, "research", {})
    monkeypatch.setattr(store, "memory", [])
    monkeypatch.setattr(store, "campaigns", {})


def _events(topic, **kw):
    async def collect():
        return [ev async for ev in research.run(topic, **kw)]
    return asyncio.run(collect())


def test_offline_research_is_honest():
    types = [e["type"] for e in _events("bakery pricing trends")]
    assert types[0] == "plan" and "error" in types and types[-1] == "done"
    report = next(e for e in _events("bakery pricing trends") if e["type"] == "report")["content"]
    assert "TAVILY_API_KEY" in report  # says why there's no data instead of inventing any


def test_live_research_cites_sources_and_extracts_insights(monkeypatch):
    monkeypatch.setattr(config, "TAVILY_API_KEY", "t")
    monkeypatch.setattr(config, "NEBIUS_API_KEY", "n")
    searched = []

    async def fake_search(q, **kw):
        searched.append((q, kw.get("topic"), kw.get("include_domains")))
        return [TrendItem(title=f"Result for {q}", url=f"https://ex.com/{len(searched)}", snippet="Sourdough prices up 12% in 2026.")]

    async def fake_extract(urls):
        return {u: "Full article text about sourdough prices." for u in urls}

    calls = []

    async def fake_json(purpose, system, user, **kw):
        calls.append(purpose)
        if purpose == "research_plan":
            assert "Bluebird Bakery" in system  # brand context reaches the planner
            return {"rationale": "Check prices and sentiment", "queries": [{"kind": "news", "q": "sourdough prices"}, {"kind": "social", "q": "sourdough reddit"}]}
        return {"verified_trend": "Sourdough prices rising", "audience_insight": "Locals value freshness", "content_angles": ["Why our price stayed put"],
                "confidence": 140, "opportunity": 72}

    async def fake_complete(purpose, system, user, **kw):
        calls.append(purpose)
        assert "[1]" in user and "[2]" in user
        return "## Executive Summary\nPrices are up [1]."

    monkeypatch.setattr(trends, "search", fake_search)
    monkeypatch.setattr(trends, "extract", fake_extract)
    monkeypatch.setattr(router, "complete_json", fake_json)
    monkeypatch.setattr(router, "complete", fake_complete)

    evs = _events("sourdough pricing", kit=_kit())
    assert calls == ["research_plan", "research_report", "insight_extract"]
    assert searched[1][2] == research.SOCIAL_DOMAINS  # social searches are restricted to social sites
    report = next(e for e in evs if e["type"] == "report")
    assert "## Sources" in report["content"] and len(report["sources"]) == 2
    insights = next(e for e in evs if e["type"] == "insights")["insights"]
    assert insights["confidence"] == 100 and insights["content_angles"] == ["Why our price stayed put"]
    assert memory.recall("sourdough pricing")[0]["title"] == "sourdough pricing"  # remembered for next time


def test_queue_processes_and_retries(monkeypatch):
    task = ResearchTask(topic="coffee trends")
    store.research[task.id] = task
    asyncio.run(research.process_task(task.id))
    assert task.status == "completed" and task.report and task.attempts == 1

    async def boom(*a, **kw):
        raise RuntimeError("search down")
        yield  # pragma: no cover

    monkeypatch.setattr(research, "run", boom)
    bad = ResearchTask(topic="will fail")
    store.research[bad.id] = bad
    for _ in range(3):
        asyncio.run(research.process_task(bad.id))
    assert bad.status == "failed" and bad.attempts == 3 and "search down" in bad.error


def test_memory_ranks_relevant_entries():
    memory.remember("research", "Coffee pricing in Austin", "Cold brew prices rose this summer.")
    memory.remember("research", "Gym marketing", "Members respond to challenges.")
    hits = memory.recall("austin coffee prices")
    assert [h["title"] for h in hits] == ["Coffee pricing in Austin"]
    assert memory.recall("") == []


def test_campaign_uses_attached_research(monkeypatch):
    task = ResearchTask(topic="sourdough trends", status="completed", report="## Executive Summary\nFoo",
                        insights=ResearchInsights(verified_trend="Sourdough demand up", content_angles=["Behind the starter"]))
    store.research[task.id] = task
    ctx = research.campaign_context([task.id, "missing"])
    assert "Sourdough demand up" in ctx and "Behind the starter" in ctx

    seen = {}

    async def fake_strategy(kit, trends_, weeks, findings=""):
        seen["strategy"] = findings
        return strategist.fallback_strategy(kit, trends_, weeks)

    async def fake_write_all(kit, strategy, slots, findings=""):
        seen["copy"] = findings
        return [strategist.fallback_copy(kit, s) for s in slots]

    async def fake_ingest(raw, search_fn=None):
        return _kit()

    monkeypatch.setattr(pipeline, "ingest", fake_ingest)
    monkeypatch.setattr(pipeline.strategist, "build_strategy", fake_strategy)
    monkeypatch.setattr(pipeline.strategist, "write_all", fake_write_all)
    camp = Campaign(start_date=date(2026, 11, 1), days=3, platforms=[Platform.X], research_ids=[task.id])
    job = pipeline.new_job(camp.id)
    asyncio.run(pipeline.run_campaign(job, camp, "bluebird.example", posts_per_day=1))
    assert job.status == "done"
    assert "Sourdough demand up" in seen["strategy"] and seen["strategy"] == seen["copy"]
    assert "research report" in next(s for s in job.steps if s.key == "strategy").detail
    from app import config as cfg
    for p in camp.posts:
        (cfg.MEDIA_DIR / f"{camp.id}_{p.id}.png").unlink(missing_ok=True)
