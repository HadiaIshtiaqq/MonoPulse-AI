"""Reels: 9:16 motion videos made from a post and the brand's own photos."""
import asyncio
from datetime import date, datetime, timezone

from PIL import Image

from app.agents import occasions, reels, strategist
from app.schemas import Background, Campaign, Platform, Product, SocialPost

from test_core import _kit
from test_features import _campaign_with_posts, _png_bytes, client, offline  # noqa: F401 - fixtures


def _photo(tmp_path, name: str, color) -> Background:
    path = tmp_path / f"{name}.jpg"
    Image.new("RGB", (800, 1000), color).save(path)
    return Background(source="website", path=str(path))


def _post(campaign_id: str, group: str, day: int, product: Product | None, bg: Background | None, **kw) -> SocialPost:
    return SocialPost(campaign_id=campaign_id, group_id=group, day=day, platform=Platform.INSTAGRAM, product=product,
                      background=bg, publish_at=datetime(2026, 11, 1 + day, tzinfo=timezone.utc), **kw)


def _shop(tmp_path) -> Campaign:
    c = Campaign(start_date=date(2026, 11, 1), days=6, platforms=[Platform.INSTAGRAM], brand=_kit())
    names = [("Chicken Roll", "Rs. 450"), ("Zinger Burger", "Rs. 310"), ("Mighty Wings", "Rs. 640"), ("Red Velvet Cake", "Rs. 420")]
    c.posts = [_post(c.id, f"g{i}", i, Product(name=n, price=p, url=f"https://x/{i}"), _photo(tmp_path, f"p{i}", (60 * i, 90, 140)),
                     headline=f"New in: {n}") for i, (n, p) in enumerate(names)]
    c.posts += [_post(c.id, "g9", 5, None, _photo(tmp_path, "shop", "gray"), kind="quote", headline="Bread worth waking up for")]
    return c


def test_reel_shows_the_post_first_then_other_products_once_each(tmp_path):
    c = Campaign(start_date=date(2026, 11, 1), days=5, platforms=[Platform.INSTAGRAM], brand=_kit())
    roll, burger = Product(name="Chicken Roll", price="Rs. 450"), Product(name="Zinger Burger", price="Rs. 310")
    post = _post(c.id, "g1", 0, roll, _photo(tmp_path, "roll", "red"), headline="New in: Chicken Roll")
    c.posts = [post,
               _post(c.id, "g2", 1, burger, _photo(tmp_path, "burger", "orange")),
               _post(c.id, "g3", 2, burger, _photo(tmp_path, "burger2", "yellow")),  # same product again: skipped
               _post(c.id, "g4", 3, None, None)]
    assert [p.name for p, _, _ in reels.reel_photos(c, post)] == ["Chicken Roll", "Zinger Burger"]


def test_every_topic_tells_one_connected_story(tmp_path):
    c = _shop(tmp_path)
    post = c.posts[0]
    style = reels.STYLES["cinematic"]
    plans = {t: reels.plan_story(c, post, t, style) for t in ("products", "countdown", "tips", "poll", "story")}
    # The opening promises what the scenes deliver, the scenes are labelled in order, the end closes the loop.
    products = plans["products"]
    n = len(products.lines)
    assert products.hook.startswith(f"{n} picks") and products.tags == [f"{i + 1}/{n}" for i in range(n)]
    countdown = plans["countdown"]
    assert countdown.tags == ["#3", "#2", "#1"] and countdown.lines[-1] == "Chicken Roll"  # builds up to the post's product
    assert "#1" in countdown.cta
    tips = plans["tips"]
    assert tips.tags == ["Tip 1", "Tip 2", "Tip 3"] and "Chicken Roll" in tips.hook
    assert len({path for _, path, _ in tips.shots}) == 1  # every tip is about the same product
    poll = plans["poll"]
    assert poll.tags == ["A", "B"] and poll.lines == ["Chicken Roll", "Zinger Burger"]
    story = plans["story"]
    assert story.lines[:2] == ["Sourdough baked daily", "Custom cakes"] and "Bluebird Bakery" in story.hook
    scenes = reels.plan_scenes(countdown)
    assert [s.kind for s in scenes] == ["hook", "product", "product", "product", "cta"] and scenes[1].tag == "#3"


def test_reels_follow_the_posts_type_and_move_on_when_rewritten(tmp_path):
    c = _shop(tmp_path)
    duo = c.posts[0].model_copy(update={"kind": "duo"})
    assert reels.default_topic(c, duo) == "poll"
    assert reels.default_topic(c, c.posts[-1]) == "story"  # a quote post tells the brand's story
    assert reels.default_topic(c, duo, avoid="poll") != "poll"


def test_occasion_reels_greet_with_festive_colours(tmp_path):
    c = _shop(tmp_path)
    plan = reels.plan_story(c, c.posts[0], "occasion", reels.STYLES["scrapbook"], occasion_key="eid_fitr")
    assert plan.occasion == "eid_fitr" and "Eid" in plan.cta + plan.hook
    assert occasions.find("Eid al-Fitr").key == "eid_fitr" and occasions.find("Black Friday / White Friday").key == "sale"
    assert occasions.colors(occasions.OCCASIONS["independence"], "PK")[0] == (1, 65, 28)
    for motif in ("moon", "hearts", "bunting", "confetti", "sparkle"):
        layer = occasions.motif_layer(motif, (540, 960), ((11, 92, 66), (233, 196, 106), (0, 0, 0)), 0.7)
        assert layer.getbbox() is not None  # it draws something


def test_reel_words_are_humanized():
    lines, info = asyncio.run(reels.humanize_lines(_kit(), ["Elevate your mornings with our bread.", "Unleash the flavour — order now!"],
                                                   ["hook", "cta"], deep=False))
    assert lines[0] == "Upgrade your mornings with our bread" and "—" not in lines[1] and "Unleash" not in lines[1]
    assert info["after"] <= info["before"]


def test_palettes_are_worked_out_from_the_brand():
    kit = _kit()
    pal = {p["key"]: p["colors"] for p in reels.palette_list(kit)}
    assert pal["brand"][0] == kit.primary_color.upper() and len(pal) == len(reels.PALETTES)
    assert pal["midnight"][0] != pal["brand"][0] and pal["pastel"][0] != pal["brand"][0]
    assert reels.palette_kit(kit, "custom", "#123456").primary_color == "#123456"


def test_reels_in_a_campaign_rotate_through_different_styles():
    c = Campaign(start_date=date(2026, 11, 1), days=6, platforms=[Platform.INSTAGRAM], brand=_kit())
    c.posts = [_post(c.id, f"g{i}", i, None, None) for i in range(6)]
    seen = []
    for p in c.posts[:5]:
        p.reel_style = reels.choose_style(c, p).key
        seen.append(p.reel_style)
    assert sorted(seen) == sorted(reels.STYLES)  # five reels, five different looks
    assert reels.choose_style(c, c.posts[0], avoid=c.posts[0].reel_style).key != c.posts[0].reel_style


def test_make_reel_through_the_api(client, monkeypatch):  # noqa: F811
    monkeypatch.setattr(reels.render, "FPS", 3)
    c = _campaign_with_posts(days=2)
    post = c.posts[0]
    r = client.post(f"/api/posts/{post.id}/reel")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["post"]["video_url"].startswith("/media/") and body["seconds"] > 4 and body["topic"]
    versions = [p for p in c.posts if p.group_id == post.group_id]
    assert len(versions) == 2 and all(v.video_url == body["post"]["video_url"] for v in versions)
    video = client.get(body["post"]["video_url"].split("?")[0])
    assert video.status_code == 200 and video.content[4:8] == b"ftyp"
    opts = client.get(f"/api/posts/{post.id}/reel/options").json()
    assert {t["key"] for t in opts["topics"]} == set(reels.TOPICS) and opts["palettes"] and opts["occasions"]


def test_reels_render_in_the_background(client, monkeypatch):  # noqa: F811
    import time

    monkeypatch.setattr(reels.render, "FPS", 3)
    post = _campaign_with_posts(days=1).posts[0]
    r = client.post(f"/api/posts/{post.id}/reel?background=true")
    assert r.status_code == 202 and r.json()["status"] == "running"
    job_id = r.json()["job_id"]
    for _ in range(1200):  # ends as soon as the job does; generous for a busy machine
        job = client.get(f"/api/reel-jobs/{job_id}").json()
        if job["status"] != "running":
            break
        time.sleep(0.5)
    assert job["status"] == "done", job
    assert job["result"]["post"]["video_url"].startswith("/media/")
    bad = client.post(f"/api/posts/{post.id}/reel?background=true", json={"style": "sparkles"}).json()["job_id"]
    for _ in range(20):
        job = client.get(f"/api/reel-jobs/{bad}").json()
        if job["status"] != "running":
            break
        time.sleep(0.2)
    assert job["status"] == "error" and job["code"] == 422
    assert client.get("/api/reel-jobs/nope").status_code == 404


def test_owner_edits_and_options_then_rerenders(client, monkeypatch):  # noqa: F811
    monkeypatch.setattr(reels.render, "FPS", 3)
    c = _campaign_with_posts(days=2)
    post = c.posts[0]
    client.post(f"/api/posts/{post.id}/reel")
    upload = client.post("/api/uploads", files={"file": ("shot.png", _png_bytes(size=(900, 1200)), "image/png")}).json()
    edited = [{"kind": "hook", "text": "Our new loaf is here", "sub": "", "photo": "", "tag": ""},
              {"kind": "product", "text": "Seeded sourdough", "sub": "$9", "photo": upload["url"], "tag": "1/1"},
              {"kind": "cta", "text": "Pre-order now", "sub": "bluebird.example", "photo": "", "tag": ""}]
    r = client.post(f"/api/posts/{post.id}/reel", json={"scenes": edited, "options": {"palette": "ocean", "pace": "snappy", "case": "upper"}})
    assert r.status_code == 200, r.text
    saved = r.json()["post"]
    assert [s["text"] for s in saved["reel_scenes"]] == ["Our new loaf is here", "Seeded sourdough", "Pre-order now"]
    assert saved["reel_scenes"][1]["tag"] == "1/1" and saved["reel_options"]["palette"] == "ocean"
    hum = client.post(f"/api/posts/{post.id}/reel/humanize", json={"scenes": [dict(edited[0], text="Elevate your mornings.")]}).json()
    assert hum["scenes"][0]["text"] == "Upgrade your mornings"
    bad = [dict(edited[1], photo="https://evil.example/x.jpg")]
    assert client.post(f"/api/posts/{post.id}/reel", json={"scenes": bad}).status_code == 422
    assert client.post(f"/api/posts/{post.id}/reel", json={"options": {"palette": "neon"}}).status_code == 422
    assert client.post(f"/api/posts/{post.id}/reel", json={"style": "sparkles"}).status_code == 422


def test_every_style_and_an_occasion_reel_render(client, monkeypatch):  # noqa: F811
    monkeypatch.setattr(reels.render, "FPS", 2)
    c = _campaign_with_posts(days=2)
    post = c.posts[0]
    for key in reels.STYLES:
        r = client.post(f"/api/posts/{post.id}/reel", json={"style": key})
        assert r.status_code == 200 and r.json()["post"]["reel_style"] == key, (key, r.text)
    r = client.post(f"/api/posts/{post.id}/reel", json={"occasion": "mothers"})
    assert r.status_code == 200, r.text
    assert r.json()["topic"] == "occasion" and r.json()["post"]["reel_options"]["palette"] == "occasion"


def test_campaigns_greet_people_on_holidays():
    kit = _kit().model_copy(update={"country": "PK"})
    strategy = strategist.fallback_strategy(kit, [], 2, start=date(2027, 3, 4))
    slots = strategist.plan_slots(strategy, [], [Platform.INSTAGRAM, Platform.X], 10, 1, products=[], claims=2,
                                  start=date(2027, 3, 4), country="PK")
    greet = [s for s in slots if s.kind == "greeting"]
    assert greet and greet[0].occasion == "International Women's Day" and greet[0].day == 4  # 8 March
    copy = strategist.fallback_copy(kit, greet[0])
    assert copy["headline"] == "Happy Women's Day" and "Bluebird Bakery" in copy["caption"] and not copy["cta"]


def test_reels_in_roman_urdu_and_urdu_with_trending_formats(tmp_path):
    from app.agents import lang

    c = _shop(tmp_path)
    style = reels.STYLES["cinematic"]
    tips = reels.plan_story(c, c.posts[0], "tips", style, language="roman")
    assert "tareeqay" in tips.hook or "tips" in tips.hook and tips.lines[0] in lang.TIPS["roman"]["food"]
    urdu = reels.plan_story(c, c.posts[0], "countdown", style, language="ur")
    assert lang.ARABIC.search(urdu.hook) and lang.ARABIC.search(urdu.cta)
    eid = reels.plan_story(c, c.posts[0], "occasion", style, occasion_key="eid_fitr", language="roman")
    assert eid.hook == "Eid Mubarak" and "ki taraf se" in eid.cta
    for key in ("pov", "sign", "rate", "wait", "local"):
        plan = reels.plan_story(c, c.posts[0], "trend", style, language="en", trend=key)
        assert plan.topic == "trend" and plan.occasion == key and plan.hook
    assert reels.plan_story(c, c.posts[0], "trend", style, trend="rate").tags[0] == "1-10?"
    assert reels.plan_story(c, c.posts[0], "trend", style, trend="wait").tags[-1] == "The last one"
    assert "Austin" in reels.plan_story(c, c.posts[0], "trend", style, trend="local").hook
    # Urdu is shaped (joined, right to left) before it's drawn.
    assert lang.shape("عید مبارک") != "عید مبارک" and lang.shape("Eid Mubarak") == "Eid Mubarak"


def test_urdu_reel_renders_and_captions_change_language(client, monkeypatch):  # noqa: F811
    monkeypatch.setattr(reels.render, "FPS", 2)
    c = _campaign_with_posts(days=2)
    post = c.posts[0]
    r = client.post(f"/api/posts/{post.id}/reel", json={"topic": "trend", "trend": "sign", "options": {"language": "ur"}})
    assert r.status_code == 200, r.text
    assert r.json()["post"]["reel_options"]["language"] == "ur" and r.json()["topic"] == "trend"
    roman = client.post(f"/api/posts/{post.id}/caption-language", json={"language": "roman"}).json()["post"]["caption"]
    assert post.original_caption in roman and roman != post.original_caption  # a Roman Urdu opener and closer frame it
    back = client.post(f"/api/posts/{post.id}/caption-language", json={"language": "en"}).json()["post"]["caption"]
    assert back == post.original_caption
    assert client.post(f"/api/posts/{post.id}/caption-language", json={"language": "klingon"}).status_code == 422
