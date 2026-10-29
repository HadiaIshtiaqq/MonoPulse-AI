"""Designs made in the editor: saved with their layers, never overwritten by redraws, and resettable."""
import base64
import io

from PIL import Image

from app import config, media_gc
from test_features import _campaign_with_posts, client, offline  # noqa: F401 - fixtures


def page(size=(1080, 1350), color=(250, 120, 40)) -> str:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def test_a_saved_design_replaces_the_images_and_survives_a_redraw(client):  # noqa: F811
    c = _campaign_with_posts(days=1)
    post = c.posts[0]
    design = {"version": 1, "width": 1080, "height": 1350,
              "pages": [{"elements": [{"type": "text", "text": "My own words"}, {"type": "image", "src": "/media/up_abc.png"}]}]}
    r = client.put(f"/api/posts/{post.id}/design", json={"design": design, "pages": [page()]})
    assert r.status_code == 200, r.text
    saved = r.json()
    assert saved["image_url"].startswith("/media/design_") and saved["design"]["pages"][0]["elements"][0]["text"] == "My own words"
    img = Image.open(config.MEDIA_DIR / saved["image_url"].removeprefix("/media/"))
    assert img.size == (1080, 1350) and img.getpixel((10, 10)) == (250, 120, 40)
    assert client.post(f"/api/campaigns/{c.id}/redraw").status_code == 200
    assert post.image_url == saved["image_url"]  # the redraw left your design alone
    assert "up_abc.png" in media_gc.referenced()  # photos placed in a design aren't cleaned up
    reset = client.delete(f"/api/posts/{post.id}/design").json()
    assert reset["design"] is None and not reset["image_url"].startswith("/media/design_")


def test_bad_designs_are_refused(client):  # noqa: F811
    post = _campaign_with_posts(days=1).posts[0]
    assert client.put(f"/api/posts/{post.id}/design", json={"design": {}, "pages": []}).status_code == 422
    assert client.put(f"/api/posts/{post.id}/design", json={"design": {}, "pages": ["not an image"]}).status_code == 422
    assert client.put(f"/api/posts/{post.id}/design", json={"design": {}, "pages": [page((50, 50))]}).status_code == 422
    huge = {"pages": [{"elements": [{"text": "x" * 700_000}]}]}
    assert client.put(f"/api/posts/{post.id}/design", json={"design": huge, "pages": [page()]}).status_code == 422
