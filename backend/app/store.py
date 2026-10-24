"""Tiny persistent store: in-memory dicts snapshotted to a JSON file.

Good enough for a single-instance demo deployment; swap for Postgres when scaling out.
"""
from __future__ import annotations

import json
import threading

from . import config
from .schemas import AppSettings, Campaign, Job, MemoryEntry, ResearchTask, SocialPost


class Store:
    def __init__(self) -> None:
        self.campaigns: dict[str, Campaign] = {}
        self.jobs: dict[str, Job] = {}
        self.research: dict[str, ResearchTask] = {}
        self.memory: list[MemoryEntry] = []
        self.settings = AppSettings()
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        if not config.DB_PATH.exists():
            return
        try:
            raw = json.loads(config.DB_PATH.read_text(encoding="utf-8"))
            for c in raw.get("campaigns", []):
                camp = Campaign.model_validate(c)
                self.campaigns[camp.id] = camp
            for t in raw.get("research", []):
                task = ResearchTask.model_validate(t)
                self.research[task.id] = task
            self.memory = [MemoryEntry.model_validate(m) for m in raw.get("memory", [])]
            if raw.get("settings"):
                self.settings = AppSettings.model_validate(raw["settings"])
        except (OSError, ValueError):
            pass

    def save(self) -> None:
        with self._lock:
            data = {
                "campaigns": [c.model_dump(mode="json") for c in self.campaigns.values()],
                "research": [t.model_dump(mode="json") for t in self.research.values()],
                "memory": [m.model_dump(mode="json") for m in self.memory[-500:]],
                "settings": self.settings.model_dump(mode="json"),
            }
            tmp = config.DB_PATH.with_suffix(".tmp")
            tmp.write_text(json.dumps(data), encoding="utf-8")
            tmp.replace(config.DB_PATH)

    def find_post(self, post_id: str) -> tuple[Campaign, SocialPost] | None:
        for camp in self.campaigns.values():
            for post in camp.posts:
                if post.id == post_id:
                    return camp, post
        return None


store = Store()
