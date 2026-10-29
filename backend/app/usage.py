"""Daily allowances for the free credits MonoPlus spends (Tavily searches, LangSmith traces), kept in
the data folder so a restart doesn't reset them. When one runs out, MonoPlus carries on without that
service until the next day: free search instead of Tavily, no trace instead of a LangSmith trace."""
from __future__ import annotations

import json
import threading
from datetime import date

from . import config


class DailyAllowance:
    def __init__(self, name: str, limit: int) -> None:
        self.name, self.limit = name, limit
        self._day, self._used, self._loaded = "", 0, False
        self._lock = threading.Lock()

    def _path(self):
        return config.DATA_DIR / f"usage_{self.name}.json"

    def _today(self) -> None:
        today = date.today().isoformat()
        if not self._loaded:
            self._loaded = True
            try:
                saved = json.loads(self._path().read_text(encoding="utf-8"))
                self._day, self._used = str(saved.get("day", "")), int(saved.get("used", 0))
            except (OSError, ValueError):
                pass
        if self._day != today:
            self._day, self._used = today, 0

    def allows(self, amount: int = 1) -> bool:
        """Whether `amount` more fits in today's allowance (0 = no limit)."""
        with self._lock:
            self._today()
            return not self.limit or self._used + amount <= self.limit

    def add(self, amount: int = 1) -> None:
        with self._lock:
            self._today()
            self._used += max(0, amount)
            try:
                self._path().write_text(json.dumps({"day": self._day, "used": self._used}), encoding="utf-8")
            except OSError:
                pass

    def snapshot(self) -> dict:
        with self._lock:
            self._today()
            return {"used": self._used, "limit": self.limit}


tavily_credits = DailyAllowance("tavily", config.TAVILY_DAILY_CREDITS)
langsmith_traces = DailyAllowance("langsmith", config.LANGSMITH_DAILY_TRACES)
