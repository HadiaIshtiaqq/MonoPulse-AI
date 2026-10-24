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
    monkeypatch.setattr(pipeline.store, "save", lambda: None)
    camp = Campaign(start_date=date(2026, 11, 1), days=30, platforms=[Platform.INSTAGRAM, Platform.LINKEDIN, Platform.X])
    job = pipeline.new_job(camp.id)
    t0 = time.perf_counter()
    asyncio.run(pipeline.run_campaign(job, camp, "bluebird.example", posts_per_day=1))
    elapsed = time.perf_counter() - t0
    assert job.status == "done", job.error
    assert len(camp.posts) == 30
    assert {p.platform for p in camp.posts} == {Platform.INSTAGRAM, Platform.LINKEDIN, Platform.X}
    assert all(p.image_url and p.is_humanized and p.hashtags for p in camp.posts)
    assert elapsed < 30
    for p in camp.posts:
        (config.MEDIA_DIR / f"{camp.id}_{p.id}.png").unlink(missing_ok=True)


def test_slots_rotate_platforms_and_pillars():
    strat = strategist.fallback_strategy(_kit(), [], 2)
    slots = strategist.plan_slots(strat, [], [Platform.X, Platform.LINKEDIN], 10, 1)
    assert [s.platform for s in slots[:4]] == [Platform.X, Platform.LINKEDIN, Platform.X, Platform.LINKEDIN]
    assert len({s.pillar for s in slots}) == 4
