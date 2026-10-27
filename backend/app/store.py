"""Persistent store: in-memory objects backed by SQLite.

Each campaign, research task and memory entry is its own row, and a save writes only the rows
that changed, inside SQLite's own locking (WAL mode). So a save never rewrites everything,
a crash can't leave a half-written file, and two processes editing different campaigns don't
overwrite each other. An older db.json is imported once and kept as a backup.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time

from . import config
from .schemas import AppSettings, Campaign, Job, MemoryEntry, ResearchTask, SocialPost

MAX_MEMORY = 500


class Store:
    def __init__(self) -> None:
        self.campaigns: dict[str, Campaign] = {}
        self.jobs: dict[str, Job] = {}
        self.research: dict[str, ResearchTask] = {}
        self.memory: list[MemoryEntry] = []
        self.settings = AppSettings()
        self._lock = threading.Lock()
        self._written: dict[tuple[str, str], str] = {}  # what each row held after the last save
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(config.SQLITE_PATH, check_same_thread=False, timeout=15)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("CREATE TABLE IF NOT EXISTS records (kind TEXT, id TEXT, data TEXT NOT NULL, updated REAL, "
                         "PRIMARY KEY (kind, id))")
        self._db.commit()
        self._migrate_json()
        self._load()

    # ------------------------------------------------------------------ loading

    def _migrate_json(self) -> None:
        """Bring an older db.json into SQLite once, then keep it as db.json.migrated."""
        if not config.DB_PATH.exists() or self._db.execute("SELECT 1 FROM records LIMIT 1").fetchone():
            return
        try:
            raw = json.loads(config.DB_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        rows = [("campaign", c["id"], json.dumps(c)) for c in raw.get("campaigns", []) if c.get("id")]
        rows += [("research", t["id"], json.dumps(t)) for t in raw.get("research", []) if t.get("id")]
        rows += [("memory", str(i), json.dumps(m)) for i, m in enumerate(raw.get("memory", []))]
        if raw.get("settings"):
            rows.append(("settings", "app", json.dumps(raw["settings"])))
        now = time.time()
        self._db.executemany("INSERT OR REPLACE INTO records VALUES (?, ?, ?, ?)", [(*r, now) for r in rows])
        self._db.commit()
        config.DB_PATH.replace(config.DB_PATH.with_suffix(".json.migrated"))

    def _load(self) -> None:
        memory: list[tuple[int, MemoryEntry]] = []
        for kind, key, data in self._db.execute("SELECT kind, id, data FROM records"):
            try:
                obj = json.loads(data)
                if kind == "campaign":
                    camp = Campaign.model_validate(obj)
                    self.campaigns[camp.id] = camp
                elif kind == "research":
                    task = ResearchTask.model_validate(obj)
                    self.research[task.id] = task
                elif kind == "memory":
                    memory.append((int(key), MemoryEntry.model_validate(obj)))
                elif kind == "settings":
                    self.settings = AppSettings.model_validate(obj)
                self._written[(kind, key)] = data
            except (ValueError, TypeError):
                continue  # one bad row never stops the app from starting
        self.memory = [m for _, m in sorted(memory, key=lambda x: x[0])]

    # ------------------------------------------------------------------ saving

    def _rows(self) -> dict[tuple[str, str], str]:
        rows = {("campaign", c.id): c.model_dump_json() for c in self.campaigns.values()}
        rows.update({("research", t.id): t.model_dump_json() for t in self.research.values()})
        rows.update({("memory", str(i)): m.model_dump_json() for i, m in enumerate(self.memory[-MAX_MEMORY:])})
        rows[("settings", "app")] = self.settings.model_dump_json()
        return rows

    def save(self, *campaigns: Campaign) -> None:
        """Write what changed since the last save, and remove what was deleted. Given campaigns,
        only those are checked: editing one post shouldn't serialise every campaign there is."""
        with self._lock:
            if campaigns:
                rows = {("campaign", c.id): c.model_dump_json() for c in campaigns if c.id in self.campaigns}
                gone = []
            else:
                rows = self._rows()
                gone = [key for key in self._written if key not in rows]
            changed = [(k, i, d, time.time()) for (k, i), d in rows.items() if self._written.get((k, i)) != d]
            if not changed and not gone:
                return
            with self._db:
                if changed:
                    self._db.executemany("INSERT OR REPLACE INTO records VALUES (?, ?, ?, ?)", changed)
                if gone:
                    self._db.executemany("DELETE FROM records WHERE kind = ? AND id = ?", gone)
            for k, i, d, _ in changed:
                self._written[(k, i)] = d
            for key in gone:
                self._written.pop(key, None)

    def find_post(self, post_id: str) -> tuple[Campaign, SocialPost] | None:
        for camp in self.campaigns.values():
            for post in camp.posts:
                if post.id == post_id:
                    return camp, post
        return None


store = Store()
