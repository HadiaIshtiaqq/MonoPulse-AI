"""Brand-specific strategies: industry playbooks, brand facts, seasonal moments, relevant trends."""
from datetime import date

import pytest

from app import config
from app.agents import calendar, strategist
from app.agents.playbooks import brand_facts, playbook_for
from app.schemas import BrandKit, TrendItem
from app.scraper import ingestor


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(config, "NEBIUS_API_KEY", "")
    monkeypatch.setattr(config, "AWS_BEDROCK_ENABLED", False)


STORE = """<html><head><title>Bata Pakistan</title>
<meta name="description" content="Discover Bata – Pakistan's Favorite Footwear Brand for men, women, and children. Explore timeless designs, exceptional comfort, and nationwide delivery. Shop online or visit your nearest Bata store today.">
</head><body><h2>Your cart is empty</h2>
<div class="card"><a href="/products/851-6617"><img src="/a.jpg" alt="Black"></a><h3 class="card__heading"><a href="/products/851-6617">Power - Men</a></h3>
  <span>-30%</span> Sale price Rs.4,199.00 Regular price Rs.5,999.00</div>
<div class="card"><a href="/products/151-9064"><img src="/b.jpg" alt="Brown"></a><h3 class="card__heading"><a href="/products/151-9064">Bubble Gummers - Toddler (2 Years - 5 Years)</a></h3>
  Sale price Rs.2,449.00 Regular price Rs.3,499.00</div>
<div class="card"><a href="/products/351-5623"><img src="/c.jpg" alt="Pink"></a><h3 class="card__heading"><a href="/products/351-5623">Comfit - Women</a></h3>
  Rs.1,959.00</div>
</body></html>"""


def bata_kit() -> BrandKit:
    site = ingestor.parse_html(STORE, "https://www.bata.com.pk/")
    kit = BrandKit(source_input="bata.com.pk", website_url=site.url, name="Bata Pakistan")
    kit.products, kit.country = site.products, ingestor.detect_country(kit, site)
    return ingestor.heuristic_kit(site, kit)


def test_store_facts_are_read_correctly():
    kit = bata_kit()
    assert [p.name for p in kit.products] == ["Power - Men", "Bubble Gummers - Toddler (2 Years - 5 Years)", "Comfit - Women"]
    assert kit.products[0].price == "Rs.4,199.00" and kit.products[0].was_price == "Rs.5,999.00"
    assert kit.industry == "Footwear" and kit.country == "PK"
    assert kit.segments == ["men", "women", "kids"]
    assert "cart" not in kit.tagline.lower()
    assert any("Pakistan's Favorite Footwear Brand" in v for v in kit.value_props) and "Nationwide delivery" in kit.value_props
    f = brand_facts(kit)
    assert f.price_range == "Rs.1,959 to Rs.4,199" and f.best_discount == 30 and f.lines[:2] == ["Power", "Bubble Gummers"]


def test_fallback_strategy_is_specific_to_the_brand():
    kit = bata_kit()
    s = strategist.fallback_strategy(kit, [], 5, start=date(2026, 10, 25))
    assert [p.name for p in s.pillars] == [n for n, _ in playbook_for("Footwear").pillars]
    assert s.positioning.startswith("Bata Pakistan offers footwear (Power, Bubble Gummers and Comfit) for men, women and kids across Pakistan")
    assert "Rs.1,959 to Rs.4,199" in s.positioning
    assert "cart" not in s.positioning.lower()
    assert s.audience.startswith("Men, women and kids in Pakistan")
    assert any("30%" in r for r in s.voice_rules)
    themes = " | ".join(s.weekly_themes)
    assert s.weekly_themes[0].startswith("Winter collection season")  # began 1 Oct, still running
    for moment in ("11.11 sale", "Wedding season", "Black Friday / White Friday"):
        assert moment in themes, themes
    assert "12.12" not in themes  # 12 Dec is outside this 5-week window


def test_irrelevant_news_is_dropped():
    kit = bata_kit()
    trends = [TrendItem(title="Monthly Retail Trade - Sales Report", snippet="Census.gov"),
              TrendItem(title="2026 Deloitte Holiday Retail Survey", snippet=""),
              TrendItem(title="Comfortable footwear sales jump ahead of wedding season", snippet="Shoe brands report..."),
              TrendItem(title="Bata Pakistan opens new flagship store in Karachi", snippet="")]
    trends.append(TrendItem(title="Bata Pakistan | Official Online Store", snippet="Shop footwear"))
    kept = [t.title for t in strategist.relevant_trends(kit, trends)]
    # News about the brand itself first, then its category; reports and its own shop page dropped.
    assert kept == ["Bata Pakistan opens new flagship store in Karachi", "Comfortable footwear sales jump ahead of wedding season"]


BAKERY = """<html><head><title>Tartine Bakery – Tartine is a thoughtful expression of modern craft through good food and warm
experiences. We are a product of our communities and our friends.</title></head><body>
<h2>Home</h2><h2>Welcome to Tartine</h2><h2>SPECIAL ORDER CAKES</h2><h2>PRE ORDER CAKES &amp; TARTS</h2><h2>Gift Cards</h2>
<h2>WHO WE ARE</h2><h2>A thoughtful expression of modern craft.</h2>
<p>Craving Tartine but you don't live in SF or LA? We're thrilled to offer nationwide shipping through our partners.</p>
<p>Locations: The Bakery, Tartine Manufactory, Inner Sunset, Mill Valley, Santa Monica and the Bay Area.</p>
</body></html>"""


def test_a_bakery_without_product_listings_gets_a_real_plan():
    site = ingestor.parse_html(BAKERY, "https://tartinebakery.com/")
    kit = BrandKit(source_input="tartinebakery.com", website_url=site.url, name="Tartine Bakery")
    kit.country = ingestor.detect_country(kit, site)
    kit = ingestor.heuristic_kit(site, kit)
    assert kit.industry == "Food & Beverage" and kit.country == "US"
    assert kit.tagline == "Tartine is a thoughtful expression of modern craft through good food and warm experiences"
    assert kit.offerings == ["Special order cakes", "Pre order cakes & tarts", "Gift Cards"]
    assert "Nationwide delivery" in kit.value_props
    s = strategist.fallback_strategy(kit, [], 4, start=date(2026, 10, 25))
    assert s.positioning.startswith("Tartine Bakery offers special order cakes, pre order cakes & tarts and gift cards")
    assert s.audience.startswith("Locals and visitors in the US")
    assert [p.name for p in s.pillars][0] == "Menu Spotlight"
    assert any("Black Friday" in t for t in s.weekly_themes)
    slots = strategist.plan_slots(s, [], [strategist.Platform.INSTAGRAM], 4, 1)
    heads = [strategist.fallback_copy(kit, sl)["headline"] for sl in slots]
    assert heads[0] == "On the menu: special order cakes" and "take" not in " ".join(heads).lower()


def test_calendar_dates():
    pk = {m.name: m.day for m in calendar.moments_for_year(2026, "PK")}
    assert pk["Black Friday / White Friday"] == date(2026, 11, 27) and pk["11.11 sale"] == date(2026, 11, 11)
    us = {m.name: m.day for m in calendar.moments_for_year(2026, "US")}
    assert us["Cyber Monday"] == date(2026, 11, 30) and us["Mother's Day"] == date(2026, 5, 10) and "11.11 sale" not in us
    eid = next(m for m in calendar.moments_for_year(2027, "PK") if m.name == "Eid al-Fitr")
    assert eid.expected and "expected" in eid.label()


def test_sale_products_get_sale_copy():
    kit = bata_kit()
    slot = strategist.Slot(day=0, platform=strategist.Platform.INSTAGRAM, pillar="Offers & Occasions", theme="", trend=None,
                           product=kit.products[0], kind="sale")
    copy = strategist.fallback_copy(kit, slot)
    assert copy["headline"] == "30% off: Power for men"
    assert "Now Rs.4,199, was Rs.5,999." in copy["caption"]
    assert strategist.short_name("Bubble Gummers - Toddler (2 Years - 5 Years)") == "Bubble Gummers for toddler"
