"""LinkedIn publishing through the Posts and Images APIs (single image or multi-image)."""
from __future__ import annotations

import re

from .. import config
from ..schemas import SocialPost
from .base import Published, PublishError, as_jpeg, client, image_paths, raise_for

API = "https://api.linkedin.com/rest"
_RESERVED = re.compile(r"([\\|{}@\[\]()<>*_~])")
_HASHTAG = re.compile(r"#(\w+)")


def connected() -> bool:
    return bool(config.LINKEDIN_ACCESS_TOKEN and config.LINKEDIN_AUTHOR_URN)


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {config.LINKEDIN_ACCESS_TOKEN}",
        "LinkedIn-Version": config.LINKEDIN_VERSION,
        "X-Restli-Protocol-Version": "2.0.0",
    }


def commentary(post: SocialPost) -> str:
    """LinkedIn's "little text" format: escape reserved characters, keep hashtags clickable."""
    text = _RESERVED.sub(r"\\\1", post.caption)
    text = _HASHTAG.sub(lambda m: "{hashtag|\\#|" + m.group(1) + "}", text)
    tags = " ".join("{hashtag|\\#|" + t.lstrip("#") + "}" for t in post.hashtags)
    return f"{text}\n\n{tags}".strip() if tags else text


async def publish(post: SocialPost) -> Published:
    if not connected():
        raise PublishError("LinkedIn isn't connected.")
    jpegs = [as_jpeg(p) for p in image_paths(post)][:20]
    async with client() as c:
        image_urns = []
        for path in jpegs:
            resp = await c.post(f"{API}/images?action=initializeUpload", headers=_headers(),
                                json={"initializeUploadRequest": {"owner": config.LINKEDIN_AUTHOR_URN}})
            raise_for(resp, "Starting LinkedIn image upload")
            value = resp.json()["value"]
            up = await c.put(value["uploadUrl"], content=path.read_bytes(),
                             headers={"Authorization": f"Bearer {config.LINKEDIN_ACCESS_TOKEN}"})
            raise_for(up, "Uploading image to LinkedIn")
            image_urns.append(value["image"])
        content = {"media": {"id": image_urns[0], "altText": post.alt_text[:300]}} if len(image_urns) == 1 else {
            "multiImage": {"images": [{"id": u, "altText": post.alt_text[:300]} for u in image_urns]}}
        body = {
            "author": config.LINKEDIN_AUTHOR_URN,
            "commentary": commentary(post),
            "visibility": "PUBLIC",
            "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [], "thirdPartyDistributionChannels": []},
            "content": content,
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False,
        }
        resp = await c.post(f"{API}/posts", headers=_headers(), json=body)
        raise_for(resp, "Publishing to LinkedIn")
        urn = resp.headers.get("x-restli-id") or resp.headers.get("x-linkedin-id") or ""
    return Published("linkedin", urn, f"https://www.linkedin.com/feed/update/{urn}" if urn else None)
