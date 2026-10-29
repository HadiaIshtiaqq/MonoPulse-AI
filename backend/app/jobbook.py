"""Background video jobs (reels, UGC ads) that outlive a restart.

The page polls a job until it's done. Kept only in memory, a restart lost every job: the page waited
for one that no longer existed. Each job's state is now also written to the data folder when it
starts and when it finishes. After a restart, finished jobs still answer, and a job that was cut off
says so, so the page can tell the person to make it again.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from . import config

log = logging.getLogger(__name__)
KEEP = timedelta(hours=6)  # finished jobs are kept this long for the page to collect


class JobBook(dict):
    def __init__(self, name: str) -> None:
        super().__init__()
        self.name = name
        self._load()

    def _path(self):
        return config.DATA_DIR / f"jobs_{self.name}.json"

    def _load(self) -> None:
        try:
            saved = json.loads(self._path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for job_id, job in saved.items():
            try:
                job["at"] = datetime.fromisoformat(job["at"])
            except (KeyError, TypeError, ValueError):
                continue
            if job.get("status") == "running":
                job.update(status="error", error="MonoPlus restarted while this was being made. Please make it again.")
            self[job_id] = job

    def save(self) -> None:
        """Write the jobs from the last few hours (called when one starts or finishes)."""
        now = datetime.now(timezone.utc)
        for k in [k for k, j in self.items() if j["status"] != "running" and now - j["at"] > KEEP]:
            self.pop(k, None)
        data = {k: {**j, "at": j["at"].isoformat()} for k, j in self.items()}
        try:
            tmp = self._path().with_suffix(".tmp")
            tmp.write_text(json.dumps(data, default=str), encoding="utf-8")
            tmp.replace(self._path())
        except OSError as exc:
            log.warning("couldn't save the %s jobs: %s", self.name, exc)
