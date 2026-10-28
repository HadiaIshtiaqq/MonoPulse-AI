"""Smart model tiering over Nebius Token Factory (OpenAI-compatible API).

ULTRA  -> Nemotron 3 Ultra: strategy, copywriting, humanizer rephrasing.
NANO   -> Nemotron Nano/Super: JSON formatting, hashtags, SEO tags, classification.

Every call is recorded so the dashboard can show which tier handled what and how fast.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections import deque
from enum import Enum
from typing import Any

from openai import AsyncOpenAI

from . import config
from .redact import redact
from .schemas import LLMCallRecord

log = logging.getLogger(__name__)


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
    "reel_script": ModelTier.ULTRA,
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
        self._resolved = False
        self._resolve_lock = asyncio.Lock()
        self._bedrock_client = None

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

    async def resolve_models(self) -> None:
        """If a configured model id isn't offered to this key, switch to the closest Nemotron that is.

        Model ids on Token Factory change over time; a wrong id would otherwise fail every call.
        """
        if self._resolved or not self.enabled:
            return
        self._resolved = True
        try:
            listing = await self._get_client().models.list()
            available = [m.id for m in listing.data]
        except Exception as exc:  # noqa: BLE001 - keep the configured ids if listing isn't possible
            log.warning("couldn't list Token Factory models: %s", exc)
            return
        lower = {m.lower(): m for m in available}
        nemotron = [m for m in available if "nemotron" in m.lower()]
        prefs = {ModelTier.ULTRA: ("ultra", "253b", "super", "70b", "49b"), ModelTier.NANO: ("nano", "9b", "8b", "super")}
        for tier, wanted in prefs.items():
            if TIER_MODELS[tier].lower() in lower:
                continue
            pick = next((m for w in wanted for m in nemotron if w in m.lower()), None) or (nemotron[0] if nemotron else None)
            if pick:
                log.info("model %s isn't available; using %s for the %s tier", TIER_MODELS[tier], pick, tier.value)
                TIER_MODELS[tier] = pick

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
            raise LLMError("No model provider configured (set NEBIUS_API_KEY or AWS_BEDROCK_ENABLED=1)")
        tier = self.tier_for(purpose)
        if self.provider == "bedrock":
            return await self._complete_bedrock(purpose, tier, system, user, temperature, max_tokens)
        if not self._resolved:
            async with self._resolve_lock:
                await self.resolve_models()
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
            record.error = redact(f"{type(exc).__name__}: {exc}")[:300]
            raise LLMError(record.error) from exc
        finally:
            record.latency_ms = int((time.perf_counter() - started) * 1000)
            self.records.append(record)

    # ------------------------------------------------------------------ Amazon Bedrock

    @property
    def provider(self) -> str:
        """Bedrock when AWS_BEDROCK_ENABLED=1 (AWS Builder path), otherwise Nebius Token Factory."""
        return "bedrock" if config.AWS_BEDROCK_ENABLED else "nebius"

    def _bedrock(self):
        if self._bedrock_client is None:
            import boto3  # imported lazily so the Nebius-only setup doesn't need AWS packages
            from botocore.config import Config

            self._bedrock_client = boto3.client(
                "bedrock-runtime", region_name=config.AWS_REGION,
                config=Config(read_timeout=config.LLM_TIMEOUT_S, retries={"max_attempts": 3, "mode": "adaptive"}),
            )
        return self._bedrock_client

    async def _complete_bedrock(self, purpose: str, tier: "ModelTier", system: str, user: str, temperature: float, max_tokens: int) -> str:
        model = config.AWS_BEDROCK_MODEL_ULTRA if tier is ModelTier.ULTRA else config.AWS_BEDROCK_MODEL_NANO
        started = time.perf_counter()
        record = LLMCallRecord(tier=tier.value, model=model, purpose=purpose, ok=False, latency_ms=0)
        try:
            async with self._sem:
                resp = await asyncio.to_thread(
                    self._bedrock().converse,
                    modelId=model,
                    system=[{"text": system}],
                    messages=[{"role": "user", "content": [{"text": user}]}],
                    inferenceConfig={"maxTokens": max_tokens, "temperature": min(1.0, temperature)},
                )
            blocks = resp["output"]["message"]["content"]
            text = "".join(b.get("text", "") for b in blocks)
            usage = resp.get("usage") or {}
            record.ok = True
            record.prompt_tokens, record.completion_tokens = usage.get("inputTokens"), usage.get("outputTokens")
            return _THINK_RE.sub("", text).strip()
        except Exception as exc:  # noqa: BLE001 - surfaced to the caller as LLMError
            record.error = redact(f"{type(exc).__name__}: {exc}")[:300]
            raise LLMError(record.error) from exc
        finally:
            record.latency_ms = int((time.perf_counter() - started) * 1000)
            self.records.append(record)

    async def complete_json(self, purpose: str, system: str, user: str, **kw: Any) -> Any:
        system = system + "\n\nRespond with valid JSON only. No markdown fences, no commentary."
        text = await self.complete(purpose, system, user, **kw)
        return parse_json(text)

    def telemetry(self) -> dict[str, Any]:
        models = ({ModelTier.ULTRA.value: config.AWS_BEDROCK_MODEL_ULTRA, ModelTier.NANO.value: config.AWS_BEDROCK_MODEL_NANO}
                  if self.provider == "bedrock" else {t.value: m for t, m in TIER_MODELS.items()})
        out: dict[str, Any] = {"provider": self.provider, "models": models, "tiers": {}}
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
