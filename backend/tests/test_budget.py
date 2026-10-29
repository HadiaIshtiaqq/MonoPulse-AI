"""The daily model cap: once today's tokens are used, no more calls go out (so free credits can't be
overspent), the count survives a restart, and a new day starts from zero."""
import asyncio
import types

import pytest

from app import config
from app.llm import LLMError, ModelRouter


def test_calls_stop_at_the_daily_cap_and_the_count_survives_a_restart(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "NEBIUS_API_KEY", "nb-test")
    monkeypatch.setattr(config, "LLM_DAILY_TOKENS", 1000)
    sent = []

    class Completions:
        async def create(self, **kw):
            sent.append(kw)
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(content="hi"))],
                                         usage=types.SimpleNamespace(prompt_tokens=500, completion_tokens=300))

    def router():
        r = ModelRouter()
        r._resolved = True
        r._client = types.SimpleNamespace(chat=types.SimpleNamespace(completions=Completions()))
        return r

    r = router()
    assert asyncio.run(r.complete("rewrite", "s", "u")) == "hi"  # 800 tokens used
    assert asyncio.run(r.complete("rewrite", "s", "u")) == "hi"  # 1,600: over the cap after this one
    with pytest.raises(LLMError, match="limit"):
        asyncio.run(r.complete("rewrite", "s", "u"))
    assert len(sent) == 2 and r.telemetry()["today"] == {"tokens": 1600, "limit": 1000}
    restarted = router()  # the count is on disk, not just in memory
    with pytest.raises(LLMError):
        asyncio.run(restarted.complete("rewrite", "s", "u"))
    assert len(sent) == 2
    tomorrow = router()
    (tmp_path / "llm_usage.json").write_text('{"day": "2000-01-01", "tokens": 999999}', encoding="utf-8")
    assert asyncio.run(tomorrow.complete("rewrite", "s", "u")) == "hi"  # a new day starts from zero
