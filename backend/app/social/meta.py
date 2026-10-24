"""Instagram and Facebook Page publishing through the Meta Graph API.

Instagram fetches images by URL. When PUBLIC_API_URL is reachable we hand it our own JPEG
links; when running locally we first upload each image to the linked Facebook Page as an
unpublished photo and use the CDN URL Meta gives back, so direct posting works without a
public server.
"""
from __future__ import annotations

import asyncio
import json

from .. import config
from ..schemas import SocialPost
from .base import Published, PublishError, as_jpeg, client, full_caption, image_paths, public_base_url, raise_for

POLL_S, POLL_TRIES = 2.0, 30


def graph(path: str) -> str:
    return f"https://graph.facebook.com/{config.GRAPH_API_VERSION}/{path.lstrip('/')}"


def instagram_connected() -> bool:
    return bool(config.META_ACCESS_TOKEN and config.INSTAGRAM_ACCOUNT_ID)


def facebook_connected() -> bool:
    return bool(config.META_ACCESS_TOKEN and config.META_PAGE_ID)


def _token() -> dict:
    return {"access_token": config.META_ACCESS_TOKEN}


async def _upload_page_photo(c, path, *, published: bool, message: str | None = None) -> dict:
    data = _token() | {"published": "true" if published else "false"}
    if message:
        data["message"] = message
    with open(path, "rb") as f:
        resp = await c.post(graph(f"{config.META_PAGE_ID}/photos"), data=data, files={"source": (path.name, f.read(), "image/jpeg")})
    raise_for(resp, "Facebook photo upload")
    return resp.json()


async def _hosted_urls(c, post: SocialPost) -> list[str]:
    jpegs = [as_jpeg(p) for p in image_paths(post)]
    base = public_base_url()
    if base:
        return [f"{base}/media/{p.name}" for p in jpegs]
    if not facebook_connected():
        raise PublishError(
            "Instagram downloads images from a public link. Either deploy the API and set PUBLIC_API_URL, "
            "or set META_PAGE_ID so images can be staged on your Facebook Page first."
        )
    urls = []
    for p in jpegs:
        photo = await _upload_page_photo(c, p, published=False)
        resp = await c.get(graph(photo["id"]), params=_token() | {"fields": "images"})
        raise_for(resp, "Reading staged photo")
        images = resp.json().get("images") or []
        if not images:
            raise PublishError("Facebook didn't return a URL for the staged photo.")
        urls.append(max(images, key=lambda i: i.get("width", 0))["source"])
    return urls


async def _wait_ready(c, container_id: str) -> None:
    for _ in range(POLL_TRIES):
        resp = await c.get(graph(container_id), params=_token() | {"fields": "status_code"})
        raise_for(resp, "Checking Instagram media")
        status = resp.json().get("status_code")
        if status == "FINISHED":
            return
        if status in ("ERROR", "EXPIRED"):
            raise PublishError(f"Instagram couldn't process the image ({status}).")
        await asyncio.sleep(POLL_S)
    raise PublishError("Instagram took too long to process the image.")


async def publish_instagram(post: SocialPost) -> Published:
    if not instagram_connected():
        raise PublishError("Instagram isn't connected.")
    ig = config.INSTAGRAM_ACCOUNT_ID
    caption = full_caption(post)[:2200]
    async with client() as c:
        urls = (await _hosted_urls(c, post))[:10]
        if len(urls) == 1:
            resp = await c.post(graph(f"{ig}/media"), data=_token() | {"image_url": urls[0], "caption": caption})
            raise_for(resp, "Creating Instagram post")
            creation = resp.json()["id"]
        else:
            children = []
            for u in urls:
                resp = await c.post(graph(f"{ig}/media"), data=_token() | {"image_url": u, "is_carousel_item": "true"})
                raise_for(resp, "Creating carousel slide")
                children.append(resp.json()["id"])
            for child in children:
                await _wait_ready(c, child)
            resp = await c.post(graph(f"{ig}/media"), data=_token() | {"media_type": "CAROUSEL", "children": ",".join(children), "caption": caption})
            raise_for(resp, "Creating Instagram carousel")
            creation = resp.json()["id"]
        await _wait_ready(c, creation)
        resp = await c.post(graph(f"{ig}/media_publish"), data=_token() | {"creation_id": creation})
        raise_for(resp, "Publishing to Instagram")
        media_id = resp.json()["id"]
        link = await c.get(graph(media_id), params=_token() | {"fields": "permalink"})
        permalink = link.json().get("permalink") if link.is_success else None
    return Published("instagram", media_id, permalink)


async def publish_facebook(post: SocialPost) -> Published:
    if not facebook_connected():
        raise PublishError("Facebook isn't connected.")
    caption = full_caption(post)
    jpegs = [as_jpeg(p) for p in image_paths(post)]
    async with client() as c:
        if len(jpegs) == 1:
            res = await _upload_page_photo(c, jpegs[0], published=True, message=caption)
            post_id = res.get("post_id") or res["id"]
        else:
            ids = [(await _upload_page_photo(c, p, published=False))["id"] for p in jpegs[:10]]
            resp = await c.post(graph(f"{config.META_PAGE_ID}/feed"), data=_token() | {
                "message": caption, "attached_media": json.dumps([{"media_fbid": i} for i in ids])})
            raise_for(resp, "Publishing to Facebook")
            post_id = resp.json()["id"]
    return Published("facebook", post_id, f"https://www.facebook.com/{post_id}")
