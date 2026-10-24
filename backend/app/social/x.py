"""X publishing: v2 media upload, then a v2 post with up to 4 images."""
from __future__ import annotations

from .. import config
from ..schemas import SocialPost
from .base import Published, PublishError, as_jpeg, client, full_caption, image_paths, raise_for

API = "https://api.x.com/2"


def connected() -> bool:
    return bool(config.X_USER_ACCESS_TOKEN)


async def publish(post: SocialPost) -> Published:
    if not connected():
        raise PublishError("X isn't connected.")
    auth = {"Authorization": f"Bearer {config.X_USER_ACCESS_TOKEN}"}
    jpegs = [as_jpeg(p) for p in image_paths(post)][:4]
    async with client() as c:
        media_ids = []
        for path in jpegs:
            resp = await c.post(f"{API}/media/upload", headers=auth, data={"media_category": "tweet_image"},
                                files={"media": (path.name, path.read_bytes(), "image/jpeg")})
            raise_for(resp, "Uploading image to X")
            body = resp.json()
            media_ids.append(str((body.get("data") or {}).get("id") or body.get("media_id_string")))
        resp = await c.post(f"{API}/tweets", headers=auth, json={"text": full_caption(post)[:280], "media": {"media_ids": media_ids}})
        raise_for(resp, "Posting to X")
        tweet_id = resp.json()["data"]["id"]
    return Published("x", tweet_id, f"https://x.com/i/web/status/{tweet_id}")
