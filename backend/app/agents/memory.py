"""Research memory: past reports the agent recalls before new research.

Keyword-overlap ranking over the store; small enough that a full scan is instant.
"""
from __future__ import annotations

import re

from ..schemas import MemoryEntry
from ..store import store

_WORD = re.compile(r"[a-z0-9]{3,}")
_STOP = {"the", "and", "for", "with", "what", "are", "how", "our", "this", "that", "from", "about", "which", "who", "their", "your"}


def _terms(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in _STOP}


def remember(kind: str, title: str, content: str, ref_id: str = "") -> None:
    store.memory.append(MemoryEntry(kind=kind, title=title[:300], content=content[:12000], ref_id=ref_id))


def recall(query: str, limit: int = 5) -> list[dict]:
    q = _terms(query)
    if not q:
        return []
    scored = []
    for m in store.memory:
        title, body = _terms(m.title), _terms(m.content)
        score = 3 * len(q & title) + len(q & body)
        if score:
            scored.append((score, m))
    scored.sort(key=lambda x: (-x[0], -x[1].created_at.timestamp()))
    out = []
    for _, m in scored[:limit]:
        excerpt = next((s for s in re.split(r"(?<=[.!?])\s+", m.content) if _terms(s) & q), m.content[:240])
        out.append({"kind": m.kind, "ref_id": m.ref_id, "title": m.title, "created_at": m.created_at.isoformat(), "excerpt": excerpt[:300]})
    return out


def recall_text(query: str, limit: int = 4) -> str:
    return "\n".join(f"- [{h['kind']} {h['created_at'][:10]}] {h['title']}: {h['excerpt']}" for h in recall(query, limit))
