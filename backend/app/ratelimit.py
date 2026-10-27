"""Per-client limits on the expensive calls (campaign generation, reels, research, uploads,
model rewrites), so one client can't tie up the server for everyone else.

A sliding window per (client, bucket) in memory: right for a single server; behind several,
put the limit in the proxy instead.
"""
from __future__ import annotations

import re
import time
from collections import deque

# (method, path pattern) -> (bucket, calls allowed, per seconds)
RULES: list[tuple[str, re.Pattern, str, int, int]] = [
    ("POST", re.compile(r"^/api/campaigns$"), "generate", 6, 600),
    ("POST", re.compile(r"^/api/posts/[^/]+/reel$"), "reel", 12, 300),
    ("POST", re.compile(r"^/api/research/"), "research", 10, 600),
    ("POST", re.compile(r"^/api/uploads$"), "upload", 40, 300),
    ("POST", re.compile(r"^/api/(posts/[^/]+/(rewrite|humanize|caption-language|reel/humanize)|humanize)$"), "rewrite", 40, 300),
]


class RateLimiter:
    def __init__(self) -> None:
        self.hits: dict[tuple[str, str], deque[float]] = {}

    def check(self, client: str, method: str, path: str) -> tuple[str, int] | None:
        """None when the call may go ahead, else (what was limited, seconds to wait)."""
        for verb, rx, bucket, limit, window in RULES:
            if method != verb or not rx.match(path):
                continue
            now = time.monotonic()
            q = self.hits.setdefault((client, bucket), deque())
            while q and now - q[0] > window:
                q.popleft()
            if len(q) >= limit:
                return bucket, int(window - (now - q[0])) + 1
            q.append(now)
        return None


limiter = RateLimiter()

FRIENDLY = {
    "generate": "You've started a lot of campaigns in a short time.",
    "reel": "You've made a lot of reels in a short time.",
    "research": "You've started a lot of research in a short time.",
    "upload": "You've uploaded a lot of images in a short time.",
    "rewrite": "You've asked for a lot of rewrites in a short time.",
}
