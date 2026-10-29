"""LangSmith traces of every Nemotron call (optional: set LANGSMITH_API_KEY, or LANG_CHAIN, in backend/.env).

Each call shows up in the LangSmith project as an LLM run named after its purpose (strategy, ugc_director,
...), with the tier and model, the prompt and the reply, tokens and latency, so every agent step can be
inspected. Traces are sent in the background by LangSmith's client and never slow a call down; a failure
to send one is only logged. Past LANGSMITH_DAILY_TRACES a day, calls simply aren't traced.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone

from . import config, usage
from .redact import redact

log = logging.getLogger(__name__)
_client = None
_lock = threading.Lock()
LIMIT = 4000  # characters of each message kept in a trace


def enabled() -> bool:
    return bool(config.LANGSMITH_API_KEY)


def _get_client():
    global _client
    with _lock:
        if _client is None:
            from langsmith import Client  # imported only when tracing is on

            _client = Client(api_key=config.LANGSMITH_API_KEY, api_url=config.LANGSMITH_ENDPOINT)
        return _client


def record_llm_call(rec, system: str, user: str, reply: str, provider: str) -> None:
    """Send one finished model call (an LLMCallRecord) to LangSmith."""
    if not enabled() or not usage.langsmith_traces.allows():
        return
    try:
        from langsmith.run_trees import RunTree

        run = RunTree(
            name=f"nemotron.{rec.purpose}", run_type="llm", project_name=config.LANGSMITH_PROJECT, client=_get_client(),
            start_time=rec.at, tags=[rec.tier, provider],
            inputs={"messages": [{"role": "system", "content": redact(system)[:LIMIT]},
                                 {"role": "user", "content": redact(user)[:LIMIT]}]},
            extra={"metadata": {"ls_provider": provider, "ls_model_name": rec.model, "tier": rec.tier, "purpose": rec.purpose}},
        )
        prompt, completion = rec.prompt_tokens or 0, rec.completion_tokens or 0
        run.end(outputs={"choices": [{"message": {"role": "assistant", "content": redact(reply)[:LIMIT]}}],
                         "usage_metadata": {"input_tokens": prompt, "output_tokens": completion, "total_tokens": prompt + completion}},
                error=rec.error, end_time=datetime.now(timezone.utc))
        run.post()
        usage.langsmith_traces.add()
    except Exception as exc:  # noqa: BLE001 - tracing must never break a model call
        log.warning("couldn't send a LangSmith trace: %s", redact(str(exc))[:200])


def flush() -> None:
    """Send any traces still queued (on shutdown)."""
    if _client is not None:
        try:
            _client.flush()
        except Exception:  # noqa: BLE001
            pass
