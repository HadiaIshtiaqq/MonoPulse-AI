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


def test_research_with_search_off_is_honest():
    evs = _events("bakery pricing trends")
    types = [e["type"] for e in evs]
    assert types[0] == "plan" and "error" in types and types[-1] == "done"
    report = next(e for e in evs if e["type"] == "report")["content"]
    assert "No sources" in report  # says there's no data instead of inventing any


def test_keyless_research_builds_cited_summary_and_insights(monkeypatch):
    """No Tavily, no Nemotron: free search results still become a real report and insights."""
    monkeypatch.setattr(config, "FREE_SEARCH", True)

    async def fake_news(query, days=None, max_results=6):
        return [{"title": "Sourdough prices climb as flour costs rise", "url": "https://news.google.com/a1", "snippet": "Bakers raise loaf prices.",
                 "published_date": "2026-10-20"}]

    async def fake_ddg(query, max_results=6, include_domains=None):
        if include_domains:
            return [{"title": "Is $8 too much for sourdough? : r/Breadit", "url": "https://reddit.com/r/Breadit/1", "snippet": "Locals debate prices",
                     "published_date": None}]
        return [{"title": "Bakery pricing guide 2026", "url": "https://example.com/guide", "snippet": "How bakeries price bread", "published_date": None}]

    async def fake_fetch(urls):
        return {"https://example.com/guide": "Most independent bakeries raised sourdough prices by about 12 percent this year as flour costs rose. "
                                              "Customers still pay more for fresh bread baked on site."}

    from app.agents import freesearch
    monkeypatch.setattr(freesearch, "google_news", fake_news)
    monkeypatch.setattr(freesearch, "duckduckgo", fake_ddg)
    monkeypatch.setattr(freesearch, "fetch_text", fake_fetch)
    evs = _events("sourdough bakery pricing")
    report = next(e for e in evs if e["type"] == "report")["content"]
    assert "## Key Findings" in report and "12 percent" in report and "[" in report  # extracted and cited
    assert "## Content Ideas" in report and "## Sources" in report
    insights = next(e for e in evs if e["type"] == "insights")["insights"]
    assert insights["content_angles"] and insights["confidence"] > 0 and "12 percent" in insights["pricing_gap"]


def test_free_search_parsers():
    from app.agents import freesearch
    rss = b"""<rss><channel><item><title>Bakery sales jump - Baking Business</title><link>https://news.google.com/x</link>
      <pubDate>Wed, 14 Oct 2026 04:00:00 GMT</pubDate><description>&lt;a&gt;Bakery sales jump&lt;/a&gt;</description>
      <source url="https://bakingbusiness.com">Baking Business</source></item></channel></rss>"""
    items = freesearch.parse_google_news(rss)
    assert items[0]["title"] == "Bakery sales jump" and items[0]["published_date"] == "2026-10-14"
    html = """<div class="result result--ad"><a class="result__a" href="https://ads.example">Ad</a></div>
      <div class="result"><a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.sweetgreen.com%2F&rut=x">sweetgreen</a>
      <a class="result__snippet">Healthy food</a></div>"""
    results = freesearch.parse_duckduckgo(html)
    assert results == [{"title": "sweetgreen", "url": "https://www.sweetgreen.com/", "snippet": "Healthy food", "published_date": None}]


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
