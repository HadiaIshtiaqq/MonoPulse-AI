"""Background photos for posts: licensed stock search and the user's own uploads.

Stock comes from Pexels (free for commercial use, no attribution required) when
PEXELS_API_KEY is set, otherwise from Openverse (Creative Commons, no key; slower). We only
return images whose license allows commercial use and modification, and we keep the credit
line so it can be shown with the post.
"""
from __future__ import annotations

import hashlib
import io
import logging
import time
import uuid
from dataclasses import asdict, dataclass

import httpx
from PIL import Image, ImageOps

from .. import config
from ..netguard import safe_client
from ..schemas import Background

log = logging.getLogger(__name__)

UA = {"User-Agent": "MonoPlus/0.3 (social media marketing app)"}
# Store CDNs often refuse non-browser agents for images.
WEB_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
MIN_WEB_SIDE = 360
MAX_UPLOAD_BYTES = 15 * 1024 * 1024
MAX_SIDE = 2400
_cache: dict[str, tuple[float, list["Photo"]]] = {}
_index: dict[str, "Photo"] = {}  # photo id -> metadata, so the client only sends ids back


@dataclass
class Photo:
    id: str
    thumb: str
    full: str
    width: int
    height: int
    credit: str
    credit_url: str
    license: str
    source: str  # pexels | openverse

    def as_dict(self) -> dict:
        return asdict(self)


async def _pexels(client: httpx.AsyncClient, query: str, orientation: str) -> list[Photo]:
    resp = await client.get(
        "https://api.pexels.com/v1/search",
        params={"query": query, "per_page": 18, "orientation": orientation},
        headers={"Authorization": config.PEXELS_API_KEY},
    )
    resp.raise_for_status()
    return [
        Photo(id=f"pexels-{p['id']}", thumb=p["src"]["medium"], full=p["src"]["large2x"], width=p["width"], height=p["height"],
              credit=f"Photo by {p['photographer']} on Pexels", credit_url=p["url"], license="Pexels License", source="pexels")
        for p in resp.json().get("photos", [])
    ]


async def _openverse(client: httpx.AsyncClient, query: str, orientation: str) -> list[Photo]:
    aspect = {"square": "square", "portrait": "tall", "landscape": "wide"}.get(orientation, "square")
    resp = await client.get(
        "https://api.openverse.org/v1/images/",
        params={"q": query, "license_type": "commercial,modification", "page_size": 18, "aspect_ratio": aspect, "mature": "false"},
        timeout=40,
    )
    resp.raise_for_status()
    out = []
    for r in resp.json().get("results", []):
        if not r.get("url"):
            continue
        lic = f"CC {r.get('license', '').upper()} {r.get('license_version') or ''}".strip()
        creator = r.get("creator") or "unknown creator"
        out.append(Photo(id=f"ov-{r['id']}", thumb=r.get("thumbnail") or r["url"], full=r["url"], width=r.get("width") or 0,
                         height=r.get("height") or 0, credit=f"“{(r.get('title') or 'Photo')[:60]}” by {creator} ({lic})",
                         credit_url=r.get("foreign_landing_url") or r["url"], license=lic, source="openverse"))
    return out


async def search(query: str, orientation: str = "square") -> list[Photo]:
    key = f"{query.lower().strip()}|{orientation}"
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < 3600:
        return hit[1]
    photos: list[Photo] = []
    async with httpx.AsyncClient(timeout=15, headers=UA, follow_redirects=True) as client:
        providers = ([_pexels] if config.PEXELS_API_KEY else []) + [_openverse]
        for provider in providers:
            try:
                photos = await provider(client, query, orientation)
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                log.warning("photo search via %s failed: %s", provider.__name__, exc)
            if photos:
                break
    for p in photos:
        _index[p.id] = p
    _cache[key] = (time.time(), photos)
    return photos


def _save_image(data: bytes, prefix: str) -> str:
    img = Image.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img)
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    has_alpha = img.mode in ("RGBA", "LA", "P")
    name = f"{prefix}_{hashlib.sha1(data).hexdigest()[:16]}.{'png' if has_alpha else 'jpg'}"
    path = config.MEDIA_DIR / name
    if has_alpha:
        img.convert("RGBA").save(path)
    else:
        img.convert("RGB").save(path, quality=90)
    return name


async def to_background(photo_id: str) -> Background:
    photo = _index.get(photo_id)
    if not photo:
        raise KeyError("Unknown photo. Search again and pick a result.")
    async with httpx.AsyncClient(timeout=30, headers=UA, follow_redirects=True) as client:
        resp = await client.get(photo.full)
        resp.raise_for_status()
    name = _save_image(resp.content[:MAX_UPLOAD_BYTES], "bg")
    return Background(source="stock", path=str(config.MEDIA_DIR / name), thumb_url=f"/media/{name}", credit=photo.credit,
                      credit_url=photo.credit_url, license=photo.license)


async def website_background(url: str, credit: str, credit_url: str = "") -> Background:
    """Download one of the brand's own photos (a product shot, a hero image) for a post."""
    async with safe_client(headers={"User-Agent": WEB_UA}, follow_redirects=True, timeout=15) as client:
        resp = await client.get(url)
        resp.raise_for_status()
    data = resp.content[:MAX_UPLOAD_BYTES]
    img = Image.open(io.BytesIO(data))
    if min(img.size) < MIN_WEB_SIDE:
        raise ValueError("image too small for a post")
    if img.mode in ("RGBA", "LA", "P"):  # mostly see-through: an icon or a cut-out graphic, not a photo
        alpha = img.convert("RGBA").getchannel("A").resize((64, 64))
        if sum(alpha.histogram()[:16]) > 64 * 64 * 0.6:
            raise ValueError("that's an icon, not a photo")
    name = _save_image(data, "web")
    return Background(source="website", path=str(config.MEDIA_DIR / name), thumb_url=f"/media/{name}", credit=credit,
                      credit_url=credit_url or url, license="From the brand's own website")


def save_upload(data: bytes) -> dict:
    """Validate and store an uploaded image. Returns {id, url}."""
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError("Images are limited to 15 MB.")
    try:
        Image.open(io.BytesIO(data)).verify()
    except Exception as exc:  # noqa: BLE001 - any decode failure means "not an image"
        raise ValueError("That file isn't a supported image (PNG, JPG, WebP).") from exc
    name = _save_image(data, f"up_{uuid.uuid4().hex[:6]}")
    return {"id": name, "url": f"/media/{name}"}


def upload_path(upload_id: str):
    """Resolve an upload id to its file, refusing anything outside the media folder."""
    if "/" in upload_id or "\\" in upload_id or not upload_id.startswith("up_"):
        raise KeyError("Unknown upload.")
    path = config.MEDIA_DIR / upload_id
    if not path.exists():
        raise KeyError("Unknown upload.")
    return path


def background_from_upload(upload_id: str) -> Background:
    path = upload_path(upload_id)
    return Background(source="upload", path=str(path), thumb_url=f"/media/{upload_id}", credit="Your photo")
