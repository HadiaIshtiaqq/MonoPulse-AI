"""Deep research agent, streamed.

plan (Nemotron 3 Ultra) -> parallel Tavily searches -> read top sources (Tavily Extract)
-> cited markdown report (Ultra) -> structured insights (Nemotron Nano) -> memory.

Completed research can be attached to a campaign so its findings shape the strategy and posts.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import AsyncIterator

from .. import config
from ..llm import LLMError, router
from ..schemas import BrandKit, ResearchInsights, ResearchSource, ResearchTask, now_utc
from ..store import store
from . import memory, trends
from .strategist import brand_brief

log = logging.getLogger(__name__)

SOCIAL_DOMAINS = ["reddit.com", "x.com", "twitter.com", "instagram.com", "tiktok.com", "news.ycombinator.com"]
JOB_DOMAINS = ["linkedin.com", "indeed.com", "greenhouse.io", "lever.co"]

PLAN_SYSTEM = """You plan web research for a social media marketing team.
{context}
Write 4-6 focused searches that together answer the question. Mix kinds: "news" for recent events,
"web" for analysis, competitors' positioning and pricing, "social" for what real customers say and share,
"jobs" only if hiring patterns matter.
Return JSON: {{"rationale": "one sentence", "queries": [{{"kind": "news|web|social|jobs", "q": "search text"}}]}}"""

REPORT_SYSTEM = """You are a senior market researcher writing for a small business's marketing lead.
{context}
Use ONLY the numbered sources. Cite claims inline as [n]. Prefer specifics (dates, prices, names, numbers).
If sources conflict or are thin, say so. Markdown with exactly these sections:
## Executive Summary
## Key Findings
## What This Means for Our Marketing
## Content Ideas
(Do not write a Sources section; it is appended automatically.)"""

INSIGHT_SYSTEM = """Extract structured intelligence from the research report. Return JSON:
{"verified_trend": "one sentence or empty", "pricing_gap": "one sentence or empty",
 "feature_insights": "one sentence or empty", "audience_insight": "one sentence about what the audience cares about, or empty",
 "content_angles": ["up to 5 concrete social post angles grounded in the report"],
 "confidence": 0-100, "confidence_rationale": "one sentence about source quality/agreement", "opportunity": 0-100}"""


def _context(kit: BrandKit | None) -> str:
    return f"The business: {brand_brief(kit)}" if kit else "No specific business context; answer for the market in general."


def _fallback_plan(topic: str, region: str) -> list[dict]:
    where = f" {region}" if region else ""
    return [
        {"kind": "news", "q": f"{topic}{where}"},
        {"kind": "web", "q": f"{topic}{where} analysis"},
        {"kind": "web", "q": f"{topic} competitors pricing"},
        {"kind": "social", "q": f"{topic} customers opinions"},
    ]


async def _run_query(q: dict) -> list[dict]:
    kind, text = q.get("kind", "web"), str(q.get("q", ""))[:300]
    if kind == "news":
        items = await trends.search(text, topic="news", days=30, max_results=6)
    elif kind == "social":
        items = await trends.search(text, max_results=6, include_domains=SOCIAL_DOMAINS)
    elif kind == "jobs":
        items = await trends.search(text, max_results=6, include_domains=JOB_DOMAINS)
    else:
        items = await trends.search(text, max_results=6)
    return [{"kind": kind, "title": i.title, "url": i.url, "snippet": i.snippet, "published_at": i.published_date} for i in items]


def _sources_md(sources: list[ResearchSource]) -> str:
    return "\n\n## Sources\n" + "\n".join(f"{s.id}. [{s.title or s.url}]({s.url})" for s in sources)


_STOP = {"the", "and", "for", "with", "what", "are", "how", "our", "this", "that", "from", "about", "which", "who", "their",
         "your", "into", "have", "has", "was", "were", "will", "they", "them", "its", "but", "not", "you", "all", "can"}
_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'])")


def _terms(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]{3,}", text.lower()) if w not in _STOP}


def _key_findings(question: str, sources: list[dict], limit: int = 6) -> list[tuple[str, int]]:
    """Extractive summary: the sentences that best answer the question, one per source, cited."""
    q = _terms(question)
    scored: list[tuple[float, str, int]] = []
    for s in sources:
        title_terms = _terms(s["title"])
        for sent in _SENT.split(s["text"]):
            sent = re.sub(r"^[^:]{2,40}:\s+", "", sent.strip())  # drop "Publisher: " prefixes from news snippets
            # A snippet that only repeats the headline isn't a finding.
            if title_terms and _terms(sent) <= title_terms:
                continue
            words = len(sent.split())
            if not 8 <= words <= 45 or sent.lower().startswith(("cookie", "subscribe", "sign up", "click")):
                continue
            overlap = len(q & _terms(sent))
            if overlap:
                has_number = 0.5 if re.search(r"\d", sent) else 0.0  # specifics (prices, %, dates) are worth more
                scored.append((overlap + has_number + (0.3 if s["kind"] == "news" else 0), sent, s["id"]))
    scored.sort(key=lambda x: -x[0])
    out, used = [], set()
    for _, sent, sid in scored:
        if sid in used:
            continue
        used.add(sid)
        out.append((sent, sid))
        if len(out) >= limit:
            break
    return out


def _evidence_report(question: str, sources: list[dict]) -> str:
    """Report written without a language model: counts, extracted key findings and content ideas, all cited."""
    if not sources:
        return f"## Executive Summary\nNo sources were found for “{question}”. Try wording it more broadly."
    kinds: dict[str, int] = {}
    for s in sources:
        kinds[s["kind"]] = kinds.get(s["kind"], 0) + 1
    dated = sorted((s for s in sources if s.get("published_at")), key=lambda s: s["published_at"], reverse=True)
    mix = ", ".join(f"{n} {k}" for k, n in kinds.items())
    lines = ["## Executive Summary", f"We found {len(sources)} sources on “{question}” ({mix})."]
    if dated:
        lines.append(f"The most recent is “{dated[0]['title']}” [{dated[0]['id']}] from {dated[0]['published_at'][:10]}.")
    findings = _key_findings(question, sources)
    lines += ["", "## Key Findings"]
    lines += [f"- {sent} [{sid}]" for sent, sid in findings] or [f"- {s['title']} [{s['id']}]" for s in sources[:5]]
    social = [s for s in sources if s["kind"] == "social"]
    if social:
        lines += ["", "## What People Are Saying"] + [f"- {s['title']} [{s['id']}]" for s in social[:4]]
    lines += ["", "## Content Ideas"]
    lines += [f"- React to the news: “{s['title']}” and what it means for your customers [{s['id']}]" for s in (dated or sources)[:3]]
    if social:
        lines.append(f"- Answer the question people keep asking in “{social[0]['title']}” [{social[0]['id']}]")
    return "\n".join(lines)


def heuristic_insights(question: str, sources: list[dict]) -> ResearchInsights | None:
    """Structured insights without a model, so research can still shape campaigns."""
    if not sources:
        return None
    findings = _key_findings(question, sources, 3)
    news = [s for s in sources if s["kind"] == "news"]
    social = [s for s in sources if s["kind"] == "social"]
    kinds = len({s["kind"] for s in sources})
    pricing = next((sent for sent, _ in _key_findings("price prices pricing cost costs cheaper expensive " + question, sources, 6)
                    if re.search(r"pric|cost|\$|€|£", sent, re.I)), "")
    return ResearchInsights(
        verified_trend=findings[0][0][:300] if findings else (f"Recent coverage: {news[0]['title']}" if news else ""),
        pricing_gap=pricing[:300],
        audience_insight=(social[0]["title"][:300] if social else ""),
        content_angles=[f"React to: {s['title'][:120]}" for s in (news or sources)[:3]],
        confidence=min(85, 25 + 6 * len(sources) + 8 * kinds),
        confidence_rationale=f"Based on {len(sources)} sources across {kinds} source type(s), summarised without an AI model.",
        opportunity=min(80, 30 + 10 * len(news[:4]) + 5 * len(social[:2])),
    )


async def run(topic: str, region: str = "", kit: BrandKit | None = None) -> AsyncIterator[dict]:
    question = topic + (f" (region: {region})" if region else "")
    ctx = _context(kit)

    prior = memory.recall_text(topic)
    if prior:
        yield {"type": "memory", "content": prior}

    plan, rationale = _fallback_plan(topic, region), "Default research plan."
    if router.enabled:
        try:
            data = await router.complete_json(
                "research_plan", PLAN_SYSTEM.format(context=ctx),
                f"Question: {question}\nPrior notes:\n{prior or 'none'}", temperature=0.3, max_tokens=800,
            )
            qs = [q for q in data.get("queries", []) if isinstance(q, dict) and q.get("q")][:6]
            if qs:
                plan, rationale = qs, str(data.get("rationale", ""))
        except (LLMError, AttributeError) as exc:
            yield {"type": "thinking", "content": f"Planner unavailable ({exc}); using the default plan."}
    yield {"type": "plan", "rationale": rationale, "queries": plan}

    if not config.search_enabled():
        yield {"type": "error", "message": "Live search is turned off, so there's no fresh evidence to read."}

    for q in plan:
        yield {"type": "search", "kind": q.get("kind", "web"), "query": q["q"]}
    groups = await asyncio.gather(*(_run_query(q) for q in plan))
    for q, g in zip(plan, groups):
        yield {"type": "tool_result", "name": f"search:{q.get('kind', 'web')}", "summary": f"{len(g)} results for “{q['q']}”"}

    seen: set[str] = set()
    results: list[dict] = []
    for r in (r for g in groups for r in g):
        if r["url"] and r["url"] not in seen:
            seen.add(r["url"])
            results.append(r)

    # Google News links are JavaScript redirects, so prefer pages we can actually read.
    to_read = [r for r in results if r["kind"] in ("web", "news") and "news.google.com" not in r["url"]][:3]
    for r in to_read:
        yield {"type": "scrape", "url": r["url"]}
    pages = await trends.extract([r["url"] for r in to_read])
    if to_read:
        yield {"type": "tool_result", "name": "extract", "summary": f"Read {len(pages)} of {len(to_read)} pages in full"}

    sources = []
    for i, r in enumerate(results[:24]):
        body = pages.get(r["url"]) or r["snippet"]
        sources.append(r | {"id": i + 1, "text": body[: 2500 if r["url"] in pages else 500]})

    report = ""
    if router.enabled and sources:
        numbered = "\n\n".join(f"[{s['id']}] ({s['kind']}, {s['published_at'] or 'undated'}) {s['title']}\n{s['text']}" for s in sources)
        try:
            report = await router.complete(
                "research_report", REPORT_SYSTEM.format(context=ctx),
                f"QUESTION: {question}\n\nPRIOR NOTES:\n{prior or 'none'}\n\nSOURCES:\n{numbered}", temperature=0.3, max_tokens=3000,
            )
        except LLMError as exc:
            yield {"type": "error", "message": f"Report synthesis failed: {exc}"}
    if not report:
        report = _evidence_report(question, sources)

    public = [ResearchSource(id=s["id"], title=s["title"], url=s["url"], kind=s["kind"], published_at=s["published_at"]) for s in sources]
    yield {"type": "report", "content": report + (_sources_md(public) if public else ""), "sources": [s.model_dump() for s in public]}

    insights = None
    if router.enabled and sources:
        try:
            data = await router.complete_json("insight_extract", INSIGHT_SYSTEM, report[:6000], temperature=0.1, max_tokens=700)
            insights = ResearchInsights.model_validate(
                {**data, "confidence": _score(data.get("confidence")), "opportunity": _score(data.get("opportunity")),
                 "content_angles": [str(a)[:200] for a in (data.get("content_angles") or [])][:5]}
            )
            yield {"type": "insights", "insights": insights.model_dump()}
        except (LLMError, AttributeError, ValueError) as exc:
            log.info("insight extraction failed: %s", exc)
    if insights is None and sources:
        insights = heuristic_insights(question, sources)
        if insights:
            yield {"type": "insights", "insights": insights.model_dump()}

    if sources:
        memory.remember("research", topic, report[:8000])
    yield {"type": "done", "insights": insights.model_dump() if insights else None}


def _score(v) -> int:
    try:
        return max(0, min(100, int(round(float(v)))))
    except (TypeError, ValueError):
        return 0


def brand_for(task: ResearchTask) -> BrandKit | None:
    camp = store.campaigns.get(task.campaign_id) if task.campaign_id else None
    return camp.brand if camp else None


async def execute(task: ResearchTask) -> AsyncIterator[dict]:
    """Run research for a task, recording the result on it, and re-yield the events."""
    task.status, task.started_at, task.attempts = "running", now_utc(), task.attempts + 1
    errors = []
    try:
        async for ev in run(task.topic, task.region, brand_for(task)):
            if ev["type"] == "report":
                task.report = ev["content"]
                task.sources = [ResearchSource.model_validate(s) for s in ev["sources"]]
            elif ev["type"] == "insights":
                task.insights = ResearchInsights.model_validate(ev["insights"])
            elif ev["type"] == "error":
                errors.append(ev["message"])
            yield ev
        task.status, task.completed_at = "completed", now_utc()
        task.error = "; ".join(errors) or None
    except Exception as exc:
        task.status = "retry" if task.attempts < 3 else "failed"
        task.error = str(exc)[:300]
        raise
    finally:
        if task.status == "running":
            # The viewer closed the page or stopped the stream mid-run (GeneratorExit / cancel):
            # hand the task to the background worker instead of leaving it stuck on "running".
            task.status = "retry" if task.attempts < 3 else "failed"
            task.error = "Interrupted; finishing in the background." if task.status == "retry" else "Interrupted too many times."
        store.save()


async def process_task(task_id: str) -> None:
    task = store.research.get(task_id)
    if not task or task.status not in ("pending", "retry"):
        return
    try:
        async for _ in execute(task):
            pass
    except Exception:  # noqa: BLE001 - status already recorded; retried on the next worker pass
        log.exception("research task %s failed", task_id)


async def worker(poll_s: float = 5.0) -> None:
    while True:
        for t in [t for t in store.research.values() if t.status in ("pending", "retry")][:2]:
            await process_task(t.id)
        await asyncio.sleep(poll_s)


def campaign_context(research_ids: list[str]) -> str:
    """Condensed findings from attached research, for the strategist and copywriter prompts."""
    parts = []
    for rid in research_ids:
        t = store.research.get(rid)
        if not t or t.status != "completed" or not t.report:
            continue
        lines = [f"Research: {t.topic}"]
        if t.insights:
            i = t.insights
            lines += [f"- {label}: {val}" for label, val in (("Trend", i.verified_trend), ("Audience", i.audience_insight),
                                                              ("Pricing gap", i.pricing_gap), ("Product", i.feature_insights)) if val]
            if i.content_angles:
                lines.append("- Content angles: " + "; ".join(i.content_angles))
        else:
            lines.append(t.report.split("## Sources")[0][:1500])
        parts.append("\n".join(lines))
    return "\n\n".join(parts)
