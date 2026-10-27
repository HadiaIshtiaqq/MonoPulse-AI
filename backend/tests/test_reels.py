"""Reels: 9:16 motion videos made from a post and the brand's own photos."""
from datetime import date, datetime, timezone

from PIL import Image

from app.agents import reels
from app.schemas import Background, Campaign, Platform, Product, SocialPost

from test_core import _kit
from test_features import _campaign_with_posts, client, offline  # noqa: F401 - fixtures


def _photo(tmp_path, name: str, color) -> Background:
    path = tmp_path / f"{name}.jpg"
    Image.new("RGB", (800, 1000), color).save(path)
    return Background(source="website", path=str(path))


def _post(campaign_id: str, group: str, day: int, product: Product | None, bg: Background | None, **kw) -> SocialPost:
    return SocialPost(campaign_id=campaign_id, group_id=group, day=day, platform=Platform.INSTAGRAM, product=product,
                      background=bg, publish_at=datetime(2026, 11, 1 + day, tzinfo=timezone.utc), **kw)


def test_reel_shows_the_post_first_then_other_products_once_each(tmp_path):
    c = Campaign(start_date=date(2026, 11, 1), days=5, platforms=[Platform.INSTAGRAM], brand=_kit())
    roll, burger = Product(name="Chicken Roll", price="Rs. 450"), Product(name="Zinger Burger", price="Rs. 310")
    post = _post(c.id, "g1", 0, roll, _photo(tmp_path, "roll", "red"), headline="New in: Chicken Roll")
    c.posts = [post,
               _post(c.id, "g2", 1, burger, _photo(tmp_path, "burger", "orange")),
               _post(c.id, "g3", 2, burger, _photo(tmp_path, "burger2", "yellow")),  # same product again: skipped
               _post(c.id, "g4", 3, None, None)]
    photos = reels.reel_photos(c, post)
    assert [p.name for p, _ in photos] == ["Chicken Roll", "Zinger Burger"]

    script = reels.fallback_script(c.brand, post, photos)
    assert script["scenes"] == ["Chicken Roll", "Zinger Burger"]
    assert script["hook"] == "Bread worth waking up for"  # not "New in: Chicken Roll" right before "Chicken Roll"
    scenes = reels.plan_scenes(c.brand, script, photos)
    assert [s.kind for s in scenes] == ["hook", "product", "product", "cta"]
    assert scenes[1].sub == "Rs. 450" and scenes[-1].text == "Order yours today"


def test_make_reel_through_the_api(client, monkeypatch):  # noqa: F811
    monkeypatch.setattr(reels, "FPS", 4)  # a few frames are enough to prove it encodes
    c = _campaign_with_posts(days=2)
    post = c.posts[0]
    r = client.post(f"/api/posts/{post.id}/reel")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["post"]["video_url"].startswith("/media/") and body["seconds"] > 5
    # Every platform version of the post shares the reel.
    versions = [p for p in c.posts if p.group_id == post.group_id]
    assert len(versions) == 2 and all(v.video_url == body["post"]["video_url"] for v in versions)
    video = client.get(body["post"]["video_url"].split("?")[0])
    assert video.status_code == 200 and video.content[4:8] == b"ftyp"
    assert client.get(body["post"]["video_poster"].split("?")[0]).status_code == 200
