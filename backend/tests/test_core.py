import asyncio
import time
from datetime import date, datetime, timezone

import pytest
from PIL import Image

from app import config
from app.agents import humanizer, pipeline, renderer, strategist
from app.agents.formatter import enforce_limits
from app.llm import ModelTier, parse_json, router
from app.schemas import BrandKit, Campaign, Platform, SocialPost
from app.scraper import ingestor

SAMPLE_HTML = """
<html><head>
  <title>Bluebird Bakery | Fresh Sourdough in Austin</title>
  <meta name="description" content="Family-run bakery baking sourdough, pastries and custom cakes daily in Austin, TX.">
  <meta name="theme-color" content="#E4572E">
  <link rel="icon" href="/favicon.png">
  <style>.btn{background:#E4572E;color:#fff} .hero{background:#17BEBB} body{color:#333333}</style>
</head><body>
  <header><img class="site-logo" src="/img/logo.png" alt="Bluebird Bakery"></header>
  <h1>Bread worth waking up for</h1>
  <h2>Sourdough baked every morning at 5am</h2>
  <p>We are a family-run bakery on South Congress baking naturally leavened sourdough, croissants and custom cakes for Austin since 2012.</p>
  <address>1200 S Congress Ave, Austin, TX</address>
</body></html>
"""


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(config, "NEBIUS_API_KEY", "")
    monkeypatch.setattr(config, "TAVILY_API_KEY", "")


def test_parse_html_extracts_brand_assets():
    site = ingestor.parse_html(SAMPLE_HTML, "https://bluebird.example/")
    assert ingestor.clean_name(site) == "Bluebird Bakery"
    assert "sourdough" in site.description.lower()
    assert site.theme_color == "#E4572E"
    assert site.logo_candidates[0] == "https://bluebird.example/img/logo.png"
    palette = ingestor.rank_palette(site.colors)
    assert palette[0] == "#E4572E"
    assert "#333333" not in palette  # greys are not brand colours
    assert ingestor.guess_industry(site.text_blob()) == "Food & Beverage"


@pytest.mark.parametrize(
    "raw,kind",
    [("bluebird.example", "website"), ("https://bluebird.example/menu", "website"),
     ("@bluebirdbakes", "handle"), ("https://instagram.com/bluebirdbakes", "handle")],
)
def test_detect_input(raw, kind):
    assert ingestor.detect_input(raw)[0] == kind


def test_humanizer_rule_pass_removes_tells():
    draft = ("In today's fast-paced digital landscape, it is important to elevate your brand. "
             "We do not just bake bread — we unlock seamless mornings! Amazing! Wow!")
    res = asyncio.run(humanizer.humanize(draft, use_llm=False))
    lowered = res.text.lower()
    for tell in ("fast-paced", "elevate", "unlock", "seamless", "—"):
        assert tell not in lowered
    assert "it's" in lowered and "don't" in lowered
    assert res.text.count("!") <= 1
    assert res.after < res.before


def test_contractions_skip_clause_end():
    assert humanizer.rule_pass("This is who we are.") == "This is who we are."


def test_model_tiering_routes_by_purpose():
    assert router.tier_for("strategy") is ModelTier.ULTRA
    assert router.tier_for("copywriting") is ModelTier.ULTRA
    assert router.tier_for("humanize") is ModelTier.ULTRA
    assert router.tier_for("format_seo") is ModelTier.NANO
    assert router.tier_for("hashtags") is ModelTier.NANO


def test_parse_json_tolerates_fences_and_think_blocks():
    assert parse_json('<think>hmm</think>```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json('Sure! [{"x": 2}] hope that helps') == [{"x": 2}]


def _kit() -> BrandKit:
    return BrandKit(source_input="bluebird.example", name="Bluebird Bakery", industry="Food & Beverage",
                    location="Austin, TX", tagline="Bread worth waking up for",
                    value_props=["Sourdough baked daily", "Custom cakes"], keywords=["sourdough", "bakery austin"],
                    primary_color="#E4572E", accent_color="#17BEBB", secondary_color="#2A0F08")


@pytest.mark.parametrize("platform", list(Platform))
@pytest.mark.parametrize("layout", renderer.LAYOUTS)
def test_renderer_sizes(platform, layout):
    post = SocialPost(campaign_id="t", day=0, platform=platform, headline="Fresh sourdough every single morning",
                      layout=layout, publish_at=datetime.now(timezone.utc))
    img = renderer.render(_kit(), post)
    assert isinstance(img, Image.Image) and img.size == renderer.SIZES[platform]


def test_x_posts_respect_char_limit():
    post = SocialPost(campaign_id="t", day=0, platform=Platform.X, caption="word " * 100, cta="Order now",
                      hashtags=["#Bakery", "#Austin"], publish_at=datetime.now(timezone.utc))
    enforce_limits(post)
    assert len(post.caption) + len(" ".join(post.hashtags)) + 2 <= 280


def test_full_30_day_campaign_under_30s(monkeypatch):
    async def fake_ingest(raw, search_fn=None):
        return _kit()

    monkeypatch.setattr(pipeline, "ingest", fake_ingest)
    monkeypatch.setattr(pipeline.store, "save", lambda *a: None)
    camp = Campaign(start_date=date(2026, 11, 1), days=30, platforms=[Platform.INSTAGRAM, Platform.LINKEDIN, Platform.X])
    job = pipeline.new_job(camp.id)
    t0 = time.perf_counter()
    asyncio.run(pipeline.run_campaign(job, camp, "bluebird.example", posts_per_day=1))
    elapsed = time.perf_counter() - t0
    assert job.status == "done", job.error
    assert len(camp.posts) == 90  # 30 posts, each on 3 platforms
    assert len({p.group_id for p in camp.posts}) == 30
    assert {p.platform for p in camp.posts} == {Platform.INSTAGRAM, Platform.LINKEDIN, Platform.X}
    assert all(p.image_url and p.is_humanized and p.hashtags for p in camp.posts)
    assert elapsed < 30
    for p in camp.posts:
        (config.MEDIA_DIR / f"{camp.id}_{p.id}.png").unlink(missing_ok=True)


def test_every_post_has_a_version_per_platform_and_pillars_rotate():
    strat = strategist.fallback_strategy(_kit(), [], 2)
    slots = strategist.plan_slots(strat, [], [Platform.X, Platform.LINKEDIN], 10, 1)
    assert len(slots) == 20
    assert [(s.day, s.platform) for s in slots[:4]] == [(0, Platform.X), (0, Platform.LINKEDIN), (1, Platform.X), (1, Platform.LINKEDIN)]
    for g in {s.group for s in slots}:
        versions = [s for s in slots if s.group == g]
        assert len({s.pillar for s in versions}) == 1 and len({s.day for s in versions}) == 1
    assert len({s.pillar for s in slots}) == 4
    # A carousel idea is a carousel where the platform supports it, a single image elsewhere.
    carousel_group = [s for s in slots if s.group == 1]
    assert {s.platform: s.format for s in carousel_group} == {Platform.X: "single", Platform.LINKEDIN: "carousel"}


def test_platform_versions_are_written_for_each_platform():
    kit = _kit()
    strat = strategist.fallback_strategy(kit, [], 1)
    platforms = list(Platform)
    slots = strategist.plan_slots(strat, [], platforms, 1, 1)
    copies = asyncio.run(strategist.write_all(kit, strat, slots))
    by_platform = {s.platform: c for s, c in zip(slots, copies)}
    assert len({c["headline"] for c in copies}) == 1  # the same image headline everywhere
    assert len({c["caption"] for c in copies}) == 4  # but each caption is written for its platform
    from app.agents import variety
    assert by_platform[Platform.INSTAGRAM]["caption"].splitlines()[-1] in variety.CLOSERS["instagram"]
    assert any(c in by_platform[Platform.FACEBOOK]["caption"] for c in variety.CLOSERS["facebook"])
    assert by_platform[Platform.LINKEDIN]["caption"].startswith("From the Bluebird Bakery team")
    assert len(by_platform[Platform.X]["caption"]) < len(by_platform[Platform.INSTAGRAM]["caption"])


def test_batches_keep_a_posts_versions_together():
    strat = strategist.fallback_strategy(_kit(), [], 2)
    slots = strategist.plan_slots(strat, [], list(Platform), 5, 1)
    batches = strategist.group_batches(slots, 6)
    assert sum(len(b) for _, b in batches) == len(slots)
    for _, batch in batches:
        groups = {s.group for s in batch}
        assert all(sum(1 for s in slots if s.group == g) == sum(1 for s in batch if s.group == g) for g in groups)


def test_store_saves_only_what_changed_and_survives_a_restart(tmp_path, monkeypatch):
    from datetime import date

    from app import config
    from app.schemas import Campaign, Platform
    from app.store import Store

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "SQLITE_PATH", tmp_path / "monoplus.db")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "db.json")
    old = Campaign(start_date=date(2026, 11, 1), days=3, platforms=[Platform.INSTAGRAM])
    (tmp_path / "db.json").write_text('{"campaigns": [' + old.model_dump_json() + "]}", encoding="utf-8")
    first = Store()  # imports the older JSON store once
    assert old.id in first.campaigns and (tmp_path / "db.json.migrated").exists()
    a = Campaign(start_date=date(2026, 11, 1), days=3, platforms=[Platform.INSTAGRAM])
    first.campaigns[a.id] = a
    first.save()
    # Another process (a second Store on the same file) edits a different campaign; neither save is lost.
    second = Store()
    second.campaigns[old.id].days = 9
    second.save()
    first.campaigns[a.id].days = 5
    first.save()
    third = Store()
    assert third.campaigns[old.id].days == 9 and third.campaigns[a.id].days == 5
    del third.campaigns[a.id]
    third.save()
    assert a.id not in Store().campaigns
    # Saving one campaign writes only that one.
    third.campaigns[old.id].days = 4
    b = Campaign(start_date=date(2026, 11, 1), days=2, platforms=[Platform.X])
    third.campaigns[b.id] = b
    third.save(third.campaigns[old.id])
    fourth = Store()
    assert fourth.campaigns[old.id].days == 4 and b.id not in fourth.campaigns


def test_posts_go_out_at_the_brands_local_hour():
    from app.agents import calendar

    zone = calendar.local_zone("PK")
    when = datetime(2026, 11, 2, 11, tzinfo=zone).astimezone(timezone.utc)
    assert when.hour == 6  # 11 am in Karachi is 6 am UTC
    assert calendar.local_zone("") is timezone.utc
    assert str(calendar.local_zone("US", "Austin, Texas")) == "America/Chicago"  # not New York's clock
    assert str(calendar.local_zone("AU", "Perth, Western Australia")) == "Australia/Perth"
    assert str(calendar.local_zone("US", "Brooklyn, NY")) == "America/New_York"


def test_expensive_calls_are_rate_limited_per_client(monkeypatch):
    from fastapi.testclient import TestClient

    from app import config, ratelimit
    from app.main import app

    monkeypatch.setattr(config, "RATE_LIMITS", True)
    monkeypatch.setattr(ratelimit, "limiter", ratelimit.RateLimiter())
    with TestClient(app) as client:
        codes = [client.post("/api/posts/nope/reel").status_code for _ in range(14)]
    assert codes[:12] == [404] * 12 and codes[12] == 429  # the 13th reel within five minutes waits
    assert ratelimit.limiter.check("someone-else", "POST", "/api/posts/x/reel") is None  # per client
