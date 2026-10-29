"""Removes media files nothing refers to any more: images and reels re-rendered under a new
name, photos a post swapped out, uploads that were never used. Files younger than a couple of
days are always kept, so an upload someone is about to use (or another process's fresh render)
is never pulled from under them.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

from . import config
from .store import store

log = logging.getLogger(__name__)
KEEP_SECONDS = 2 * 24 * 3600
KEEP_UPLOAD_SECONDS = 14 * 24 * 3600  # your own photos: kept a fortnight in case you come back for them


def _media_refs(value) -> list[str]:
    """Every "/media/…" string inside a design document."""
    if isinstance(value, str):
        return [value] if value.startswith("/media/") else []
    if isinstance(value, dict):
        return [r for v in value.values() for r in _media_refs(v)]
    if isinstance(value, list):
        return [r for v in value for r in _media_refs(v)]
    return []


def referenced() -> set[str]:
    names: set[str] = set()

    def add(value: str | None) -> None:
        if value:
            names.add(Path(value.split("?")[0]).name)

    for c in store.campaigns.values():
        if c.brand:
            add(c.brand.logo_path)
            for url in c.brand.images:  # photos saved at import (Instagram's)
                if url.startswith("/media/"):
                    add(url)
        for p in c.posts:
            for url in [p.image_url, p.video_url, p.video_poster, *p.image_urls]:
                add(url)
            for bg in [p.background, *p.gallery, *(s.background for s in p.slides)]:
                if bg:
                    add(bg.path)
                    add(bg.thumb_url)
            for scene in p.reel_scenes:
                add(scene.photo)
            for ref in _media_refs(p.design):  # photos placed in the editor
                add(ref)
    return names


def cleanup(now: float | None = None) -> dict:
    """Delete unreferenced media older than KEEP_SECONDS. Returns what was removed."""
    now = now or time.time()
    keep = referenced()
    removed, freed = 0, 0
    for f in config.MEDIA_DIR.glob("*"):
        age = KEEP_UPLOAD_SECONDS if f.name.startswith("up_") else KEEP_SECONDS
        if not f.is_file() or f.name in keep or now - f.stat().st_mtime < age:
            continue
        try:
            size = f.stat().st_size
            f.unlink()
            removed, freed = removed + 1, freed + size
        except OSError:
            continue
    if removed:
        log.info("media cleanup removed %d unused files (%.1f MB)", removed, freed / 1e6)
    return {"removed": removed, "freed_mb": round(freed / 1e6, 1)}
