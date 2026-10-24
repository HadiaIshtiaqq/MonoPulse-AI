"""Smart model tiering over Nebius Token Factory (OpenAI-compatible API).

ULTRA  -> Nemotron 3 Ultra: strategy, copywriting, humanizer rephrasing.
NANO   -> Nemotron Nano/Super: JSON formatting, hashtags, SEO tags, classification.

Every call is recorded so the dashboard can show which tier handled what and how fast.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from collections import deque
from enum import Enum
from typing import Any

from openai import AsyncOpenAI

from . import config
from .schemas import LLMCallRecord


class ModelTier(str, Enum):
    ULTRA = "ultra"
    NANO = "nano"


TIER_MODELS = {ModelTier.ULTRA: config.MODEL_ULTRA, ModelTier.NANO: config.MODEL_NANO}

# Which tier owns which kind of task. Agents ask for a purpose, the router picks the model.
PURPOSE_TIER: dict[str, ModelTier] = {
    "strategy": ModelTier.ULTRA,
    "copywriting": ModelTier.ULTRA,
    "humanize": ModelTier.ULTRA,
    "rewrite": ModelTier.ULTRA,
    "brand_voice": ModelTier.ULTRA,
    "research_plan": ModelTier.ULTRA,
    "research_report": ModelTier.ULTRA,
    "insight_extract": ModelTier.NANO,
    "format_seo": ModelTier.NANO,
    "hashtags": ModelTier.NANO,
    "classify": ModelTier.NANO,
    "brand_extract": ModelTier.NANO,
}

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


class LLMError(RuntimeError):
    pass


class ModelRouter:
    def __init__(self) -> None:
        self._client: AsyncOpenAI | None = None
        self.records: deque[LLMCallRecord] = deque(maxlen=500)
        # Nebius rate limits are per-key; keep a lid on fan-out.
        self._sem = asyncio.Semaphore(8)

    @property
    def enabled(self) -> bool:
        return config.llm_enabled()

    def _get_client(self) -> AsyncOpenAI:
        if self._client is None:
            self._client = AsyncOpenAI(
                base_url=config.NEBIUS_BASE_URL,
                api_key=config.NEBIUS_API_KEY,
                timeout=config.LLM_TIMEOUT_S,
                max_retries=2,
            )
        return self._client

    def tier_for(self, purpose: str) -> ModelTier:
        return PURPOSE_TIER.get(purpose, ModelTier.NANO)

    async def complete(
        self,
        purpose: str,
        system: str,
        user: str,
        *,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> str:
        if not self.enabled:
            raise LLMError("NEBIUS_API_KEY not set")
        tier = self.tier_for(purpose)
        model = TIER_MODELS[tier]
        if tier is ModelTier.NANO:
            # Nemotron Nano/Super honour /no_think to skip the reasoning trace for fast calls.
            system = "/no_think\n" + system
        started = time.perf_counter()
        record = LLMCallRecord(tier=tier.value, model=model, purpose=purpose, ok=False, latency_ms=0)
        try:
            async with self._sem:
                resp = await self._get_client().chat.completions.create(
                    model=model,
                    messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            text = resp.choices[0].message.content or ""
            record.ok = True
            if resp.usage:
                record.prompt_tokens = resp.usage.prompt_tokens
                record.completion_tokens = resp.usage.completion_tokens
            return _THINK_RE.sub("", text).strip()
        except Exception as exc:  # noqa: BLE001 - surfaced to the caller as LLMError
            record.error = f"{type(exc).__name__}: {exc}"[:300]
            raise LLMError(record.error) from exc
        finally:
            record.latency_ms = int((time.perf_counter() - started) * 1000)
            self.records.append(record)

    async def complete_json(self, purpose: str, system: str, user: str, **kw: Any) -> Any:
        system = system + "\n\nRespond with valid JSON only. No markdown fences, no commentary."
        text = await self.complete(purpose, system, user, **kw)
        return parse_json(text)

    def telemetry(self) -> dict[str, Any]:
        out: dict[str, Any] = {"models": {t.value: m for t, m in TIER_MODELS.items()}, "tiers": {}}
        for tier in ModelTier:
            recs = [r for r in self.records if r.tier == tier.value]
            ok = [r for r in recs if r.ok]
            out["tiers"][tier.value] = {
                "calls": len(recs),
                "failures": len(recs) - len(ok),
                "avg_latency_ms": int(sum(r.latency_ms for r in ok) / len(ok)) if ok else None,
                "tokens": sum((r.prompt_tokens or 0) + (r.completion_tokens or 0) for r in ok),
                "purposes": sorted({r.purpose for r in recs}),
            }
        out["recent"] = [r.model_dump(mode="json") for r in list(self.records)[-25:]][::-1]
        return out


def parse_json(text: str) -> Any:
    """Parse JSON from a model reply that may include fences or stray prose."""
    text = _THINK_RE.sub("", text).strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    pairs = sorted((("{", "}"), ("[", "]")), key=lambda p: (text.find(p[0]) == -1, text.find(p[0])))
    for open_ch, close_ch in pairs:
        start, end = text.find(open_ch), text.rfind(close_ch)
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                continue
    raise LLMError(f"Model did not return JSON: {text[:200]}")


router = ModelRouter()
