"""Reading a brand from its Instagram profile (official API or MonoPlus's signed-in browser), and
never mistaking someone else's website for the brand's."""
import asyncio
import io

import httpx
from PIL import Image

from app import config
from app.scraper import ingestor, instagram


def test_instagram_handles_are_recognised():
    assert instagram.instagram_handle("https://www.instagram.com/fitt.ote0/") == "fitt.ote0"
    assert instagram.instagram_handle("instagram.com/the_bake_shop?igsh=abc") == "the_bake_shop"
    assert instagram.instagram_handle("@khaadi") == "khaadi"
    assert instagram.instagram_handle("https://www.instagram.com/p/C123/") is None  # a post, not a profile
    assert ingestor.handle_name("fitt.ote0") == "@fitt.ote0" and ingestor.handle_name("the_bake_shop") == "The Bake Shop"


def test_someone_elses_site_is_not_taken_for_the_brand():
    unrelated = ingestor.ScrapedSite(url="https://www.fitt.com/people/", title="Fitt | Our people", text="Meet the team")
    assert not ingestor.site_belongs_to("fitt.ote0", "https://www.fitt.com/people/", unrelated)
    own = ingestor.ScrapedSite(url="https://khaadi.com/", title="Khaadi", text="")
    assert ingestor.site_belongs_to("khaadi", "https://khaadi.com/", own)
    mentions = ingestor.ScrapedSite(url="https://fitstudio.pk/", title="Fit Studio", text="Follow us @fitt.ote0 for classes")
    assert ingestor.site_belongs_to("fitt.ote0", "https://fitstudio.pk/", mentions)


def test_profile_page_read_by_the_browser():
    data = {
        "title": "FittOte Studio (@fitt.ote0) • Instagram photos and videos",
        "header": "fitt.ote0 Follow Message 48 posts 2,310 followers 180 following FittOte Studio Women-only gym in Lahore. "
                  "Personal training, yoga and HIIT. Book a free trial",
        "spans": ["fitt.ote0", "48 posts", "FittOte Studio"],
        "picture": "https://cdn.example/pic.jpg",
        "website": "https://fittote.pk/",
        "posts": [["https://cdn.example/1.jpg", "Morning HIIT class"], ["data:image/gif;base64,xx", ""]],
    }
    p = instagram.parse_page("fitt.ote0", data)
    assert p.full_name == "FittOte Studio" and p.website == "https://fittote.pk/"
    assert p.bio.startswith("Women-only gym in Lahore") and p.posts == [("https://cdn.example/1.jpg", "Morning HIIT class")]


def test_business_discovery_through_the_official_api(monkeypatch):
    monkeypatch.setattr(config, "META_ACCESS_TOKEN", "token")
    monkeypatch.setattr(config, "INSTAGRAM_ACCOUNT_ID", "1789")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["fields"] = request.url.params["fields"]
        assert "access_token" not in str(request.url) and request.headers["authorization"] == "Bearer token"  # never in a URL
        return httpx.Response(200, json={"business_discovery": {
            "username": "fitt.ote0", "name": "FittOte Studio", "biography": "Women-only gym in Lahore",
            "website": "https://fittote.pk/", "profile_picture_url": "https://cdn.example/pic.jpg",
            "media": {"data": [{"media_type": "IMAGE", "media_url": "https://cdn.example/1.jpg", "caption": "HIIT at 7"},
                               {"media_type": "VIDEO", "thumbnail_url": "https://cdn.example/2.jpg", "caption": "Yoga"}]}}})

    real = httpx.AsyncClient
    monkeypatch.setattr(instagram.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    p = asyncio.run(instagram.via_graph("fitt.ote0"))
    assert "business_discovery.username(fitt.ote0)" in seen["fields"]
    assert p.full_name == "FittOte Studio" and p.posts == [("https://cdn.example/1.jpg", "HIIT at 7"), ("https://cdn.example/2.jpg", "Yoga")]


def test_a_brand_kit_from_the_profile_alone(monkeypatch):
    monkeypatch.setattr(config, "NEBIUS_API_KEY", "")
    buf = io.BytesIO()
    Image.new("RGB", (480, 480), (214, 40, 120)).save(buf, "PNG")
    picture = buf.getvalue()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=picture, headers={"content-type": "image/png"})

    profile = instagram.Profile(username="fitt.ote0", full_name="FittOte Studio", bio="Women-only gym in Lahore. Yoga and HIIT.",
                                picture="https://cdn.example/pic.png", posts=[("https://cdn.example/1.jpg", "Morning HIIT class")])

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await ingestor.kit_from_instagram(profile, "https://www.instagram.com/fitt.ote0/", client)

    kit = asyncio.run(run())
    assert kit.name == "FittOte Studio" and kit.logo_path
    assert len(kit.images) == 1 and kit.images[0].startswith("/media/ig_")  # saved: Instagram links expire
    assert (config.MEDIA_DIR / kit.images[0].removeprefix("/media/")).is_file()
    assert kit.industry == "Fitness & Wellness" and kit.primary_color.upper() != "#5B47FB"  # the picture's own colour
