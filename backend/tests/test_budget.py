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
    assert len(sent) == 2 and r.telemetry()["today"]["tokens"] == 1600 and r.telemetry()["today"]["limit"] == 1000
    restarted = router()  # the count is on disk, not just in memory
    with pytest.raises(LLMError):
        asyncio.run(restarted.complete("rewrite", "s", "u"))
    assert len(sent) == 2
    tomorrow = router()
    (tmp_path / "llm_usage.json").write_text('{"day": "2000-01-01", "tokens": 999999}', encoding="utf-8")
    assert asyncio.run(tomorrow.complete("rewrite", "s", "u")) == "hi"  # a new day starts from zero


def test_a_dollar_cap_stops_calls_when_prices_are_set(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "NEBIUS_API_KEY", "nb-test")
    monkeypatch.setattr(config, "LLM_DAILY_TOKENS", 0)
    monkeypatch.setattr(config, "LLM_DAILY_DOLLARS", 0.001)
    monkeypatch.setattr(config, "PRICE_PER_M_ULTRA", 1.0)  # $1 per million: 800 tokens is $0.0008

    class Completions:
        async def create(self, **kw):
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(content="hi"))],
                                         usage=types.SimpleNamespace(prompt_tokens=500, completion_tokens=300))

    r = ModelRouter()
    r._resolved = True
    r._client = types.SimpleNamespace(chat=types.SimpleNamespace(completions=Completions()))
    asyncio.run(r.complete("rewrite", "s", "u"))
    asyncio.run(r.complete("rewrite", "s", "u"))  # $0.0016 now, over $0.001
    with pytest.raises(LLMError, match="spending limit"):
        asyncio.run(r.complete("rewrite", "s", "u"))
    assert r.telemetry()["today"]["dollars"] == 0.0016


def test_the_right_nemotron_models_are_picked_from_what_the_key_offers(monkeypatch):
    """Model names change on Token Factory: the router picks the newest text Nemotron for each tier."""
    from app import llm

    monkeypatch.setattr(config, "NEBIUS_API_KEY", "nb-test")
    monkeypatch.setitem(llm.TIER_MODELS, llm.ModelTier.ULTRA, "nvidia/NVIDIA-Nemotron-3-Ultra")
    monkeypatch.setitem(llm.TIER_MODELS, llm.ModelTier.NANO, "nvidia/NVIDIA-Nemotron-Nano-9B-v2")
    offered = ["meta-llama/Llama-3.3-70B-Instruct", "nvidia/Llama-3_1-Nemotron-Ultra-253B-v1", "nvidia/Nemotron-3-Ultra-550B-A55B",
               "nvidia/nemotron-3-super-120b-a12b", "nvidia/NVIDIA-Nemotron-3-Nano-Omni", "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B",
               "nvidia/llama-nemotron-embed-1b-v2"]

    class Models:
        async def list(self):
            return types.SimpleNamespace(data=[types.SimpleNamespace(id=m) for m in offered])

    r = ModelRouter()
    r._client = types.SimpleNamespace(models=Models())
    asyncio.run(r.resolve_models())
    assert llm.TIER_MODELS[llm.ModelTier.ULTRA] == "nvidia/Nemotron-3-Ultra-550B-A55B"  # Nemotron 3 before the older Ultra
    assert llm.TIER_MODELS[llm.ModelTier.NANO] == "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"  # not the Omni (vision) model
