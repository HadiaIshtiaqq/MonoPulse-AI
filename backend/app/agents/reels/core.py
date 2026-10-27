"""Shared pieces of the reel maker: sizes, errors and the Scene a reel is made of."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from dataclasses import dataclass


from ... import config
from ...schemas import SocialPost


log = logging.getLogger(__name__)

W, H, FPS = 1080, 1920, 30
MAX_PHOTOS = 5
MAX_SCENES = 8
KINDS = {"hook", "product", "fact", "cta"}
WORKERS = max(2, min(6, (os.cpu_count() or 2) - 1))
M = 84  # side margin


class ReelError(RuntimeError):
    pass


class ReelBusy(ReelError):
    """Too many reels are already rendering or waiting."""


MAX_WAITING = 8
_waiting = 0
_slots: asyncio.Semaphore | None = None


def _render_slots() -> asyncio.Semaphore:
    global _slots
    if _slots is None:  # created inside the running event loop
        _slots = asyncio.Semaphore(config.REEL_RENDERS)
    return _slots


class ReelEditError(ReelError):
    """The owner's edited scenes can't be used as they are (a missing or unknown photo…)."""


@dataclass
class Scene:
    kind: str  # hook | product | fact | cta
    text: str
    sub: str = ""  # price under a product, the website on the end card
    photo: str = ""  # local image file
    seconds: float = 2.4
    tag: str = ""  # where this scene sits in the story: "Tip 2", "#1", "A", "2/3"


def _seed(post: SocialPost) -> int:
    return int(hashlib.md5((post.group_id or post.id).encode()).hexdigest()[:8], 16)
