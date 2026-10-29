"""Free credits last: Tavily stops at its daily allowance and repeats are served from a cache, LangSmith
traces stop at theirs, and tests can never spend a real credit."""
import asyncio

from app import config, connections, tracing, usage
from app.agents import trends
from app.schemas import LLMCallRecord


class FakeTavily:
    def __init__(self):
        self.searches, self.extracts = 0, 0

    async def search(self, **kw):
        self.searches += 1
        return {"results": [{"title": f"Result for {kw['query']}", "url": "https://example.com/a", "content": "text"}]}

    async def extract(self, urls):
        self.extracts += 1
        return {"results": [{"url": u, "raw_content": "page"} for u in urls]}


def _setup(monkeypatch, tmp_path, limit):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "TAVILY_API_KEY", "test-key")
    fake = FakeTavily()
    monkeypatch.setattr(trends, "_get_client", lambda: fake)
    monkeypatch.setattr(trends, "_cache", {})
    monkeypatch.setattr(usage, "tavily_credits", usage.DailyAllowance("tavily", limit))
    return fake


def test_tests_never_hold_a_real_key():
    assert not config.TAVILY_API_KEY and not config.LANGSMITH_API_KEY and not config.HF_TOKEN and not config.NEBIUS_API_KEY
    assert not tracing.enabled()


def test_tavily_stops_at_the_daily_allowance_and_repeats_are_free(monkeypatch, tmp_path):
    fake = _setup(monkeypatch, tmp_path, limit=2)
    for _ in range(3):
        assert asyncio.run(trends.search("lawn suits"))  # the same search three times: one credit
    assert fake.searches == 1
    asyncio.run(trends.search("eid sale"))
    assert fake.searches == 2 and usage.tavily_credits.snapshot() == {"used": 2, "limit": 2}
    assert asyncio.run(trends.search("bridal wear")) == []  # allowance spent; free search is off in tests
    assert fake.searches == 2
    again = usage.DailyAllowance("tavily", 2)  # after a restart, today's count is still there
    assert not again.allows(1)


def test_reading_pages_costs_one_credit_for_every_five(monkeypatch, tmp_path):
    fake = _setup(monkeypatch, tmp_path, limit=3)
    pages = asyncio.run(trends.extract([f"https://example.com/{i}" for i in range(7)]))
    assert len(pages) == 7 and fake.extracts == 1 and usage.tavily_credits.snapshot()["used"] == 2
    assert asyncio.run(trends.extract([f"https://example.com/{i}" for i in range(10)])) == {}  # needs 2, 1 is left
    assert fake.extracts == 1


def test_the_tavily_check_reports_credits_left():
    assert connections.tavily_left({"account": {"plan_usage": 188, "plan_limit": 1000}}) == "ok, 812 of 1,000 credits left"
    assert connections.tavily_left({"key": {"usage": 5, "limit": 100}}) == "ok, 95 of 100 credits left"
    assert connections.tavily_left({}) == "ok"


def test_nemotron_calls_are_traced_to_langsmith_within_the_allowance(monkeypatch, tmp_path):
    import langsmith.run_trees

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "LANGSMITH_API_KEY", "test-key")
    monkeypatch.setattr(config, "NEBIUS_API_KEY", "sk-secret-value-1234567890")
    monkeypatch.setattr(usage, "langsmith_traces", usage.DailyAllowance("langsmith", 2))
    monkeypatch.setattr(tracing, "_get_client", lambda: None)
    sent = []

    class FakeRun:
        def __init__(self, **kw):
            self.kw = kw

        def end(self, **kw):
            self.kw.update(kw)

        def post(self):
            sent.append(self.kw)

    monkeypatch.setattr(langsmith.run_trees, "RunTree", FakeRun)
    rec = LLMCallRecord(tier="ultra", model="nvidia/NVIDIA-Nemotron-3-Ultra", purpose="ugc_director", ok=True, latency_ms=900,
                        prompt_tokens=120, completion_tokens=40)
    for _ in range(3):
        tracing.record_llm_call(rec, "You direct ads.", "key sk-secret-value-1234567890 here", '{"shots": []}', "nebius")
    assert len(sent) == 2  # the third is past today's allowance
    run = sent[0]
    assert run["name"] == "nemotron.ugc_director" and run["run_type"] == "llm" and run["tags"] == ["ultra", "nebius"]
    assert run["outputs"]["usage_metadata"]["total_tokens"] == 160
    assert "sk-secret-value" not in str(run["inputs"])  # keys never reach a trace


def test_a_trace_that_cant_be_sent_never_breaks_the_call(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "LANGSMITH_API_KEY", "test-key")
    monkeypatch.setattr(usage, "langsmith_traces", usage.DailyAllowance("langsmith", 5))

    def broken():
        raise RuntimeError("network down")

    monkeypatch.setattr(tracing, "_get_client", broken)
    rec = LLMCallRecord(tier="nano", model="m", purpose="hashtags", ok=True, latency_ms=10)
    tracing.record_llm_call(rec, "s", "u", "r", "nebius")  # no exception
    assert usage.langsmith_traces.snapshot()["used"] == 0
