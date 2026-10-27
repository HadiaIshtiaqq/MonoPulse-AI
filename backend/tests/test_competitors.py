"""Competitor research agent: discovery, reading sites, comparison and advice (network mocked)."""
import asyncio
from datetime import date

import httpx
import pytest

from app import config
from app.agents import competitors, research
from app.schemas import BrandKit, Campaign, CompetitorProfile, Platform, Product, ResearchTask, TrendItem
from app.scraper import ingestor
from app.store import store


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(config, "NEBIUS_API_KEY", "")
    monkeypatch.setattr(config, "AWS_BEDROCK_ENABLED", False)
    monkeypatch.setattr(store, "save", lambda *a: None)


def kit() -> BrandKit:
    return BrandKit(source_input="x", name="Khaadi", website_url="https://pk.khaadi.com/", industry="Fashion & Apparel", country="PK",
                    segments=["women"], products=[Product(name="Black Cambric Kurta", price="PKR 8,000", url="https://pk.khaadi.com/k1")])


ROUNDUP = """<html><body><article>
<h2>1. <a href="https://www.gulahmedshop.com/">Gul Ahmed</a></h2><p>Lawn and more.</p>
<h2>2. <a href="https://pk.sapphireonline.pk/">Sapphire</a></h2>
<h2>3. <a href="https://www.instagram.com/khaadi">Khaadi on Instagram</a></h2>
<p>Read our <a href="https://www.apartstyle.com/post/other">other guide</a> and <a href="https://pk.khaadi.com/">Khaadi</a>.</p>
</article></body></html>"""


def test_candidates_come_from_snippets_and_roundup_links():
    own = competitors.brand_slugs(kit())
    snippets = [{"title": "khaadi.com Competitors - Top Sites Like khaadi.com | Similarweb", "url": "https://www.similarweb.com/website/khaadi.com/",
                 "snippet": "Top competitors: gulahmedshop.com, mariab.pk and generation.com.pk"}]
    found = competitors.candidates_from_results(snippets, own)
    assert set(found) == {"gulahmedshop.com", "mariab.pk", "generation.com.pk"}  # not similarweb, not khaadi itself
    linked = competitors.candidates_from_article(ROUNDUP, "https://www.apartstyle.com/post/brands-like-khaadi", own)
    assert linked == {"gulahmedshop.com": ("Gul Ahmed", "www.gulahmedshop.com"), "sapphireonline.pk": ("Sapphire", "pk.sapphireonline.pk")}


def rival(name, median=0.0, currency="PKR", **kw) -> CompetitorProfile:
    return CompetitorProfile(name=name, url=f"https://{name.lower()}.pk/", median_price=median, currency=currency, **kw)


def test_comparison_states_only_facts_it_has():
    brand = rival("Khaadi", 8000, segments=["women"], socials=["instagram", "facebook"])
    rivals = [rival("Sapphire", 0, segments=["men", "women", "kids"], claims=["Pay in installments"], socials=["instagram", "tiktok"]),
              rival("Mariab", 19000, best_discount=30, on_sale=4),
              rival("Generation", 15000, claims=["Free delivery", "Pay in installments"], socials=["tiktok"])]
    position, strengths, gaps = competitors.compare(brand, rivals)
    text = " ".join(position + gaps)
    assert "Priced 53% below competitors" in position[0] and "PKR 8,000" in position[0] and "Mariab and Generation" in position[0]
    assert "Sapphire" not in position[0]  # its prices weren't read, so it isn't part of the price claim
    assert "1 of 3 competitors is running sales right now: Mariab (up to 30% off)" in text
    assert "Sapphire and Generation promise “pay in installments”" in text and "Generation promises “free delivery”" in text
    assert "Sapphire and Generation are on Tiktok" in text
    recs, plan, ideas = competitors.rule_advice(kit(), brand, rivals, gaps, date(2026, 10, 25))
    assert recs[0].title == "Own the value position" and "Mariab and Generation" in recs[0].why
    titles = [r.title for r in recs]
    assert "Start on TikTok" in titles and "Have an answer to their sales" in titles
    sales = next(r for r in recs if r.title == "Have an answer to their sales")
    assert sales.why.startswith("Mariab is discounting up to 30%")
    assert len(plan) == 4 and plan[1].focus.startswith("Build up to 11.11 sale") and ideas


def test_full_run_as_a_background_research_task(monkeypatch):
    async def fake_search(q, **kw):
        return [TrendItem(title="21 Brands Like Khaadi", url="https://www.apartstyle.com/post/brands-like-khaadi", snippet="Pakistani fashion")]

    async def fake_fetch_many(urls):
        return {u: ROUNDUP for u in urls}

    sites = {
        "pk.khaadi.com": ingestor.ScrapedSite(url="https://pk.khaadi.com/", title="Khaadi", products=[
            Product(name="Black Cambric Kurta", price="PKR 8,000", image_url="https://x/1.jpg")], socials=["instagram"]),
        "www.gulahmedshop.com": ingestor.ScrapedSite(url="https://www.gulahmedshop.com/", title="GulAhmed", products=[
            Product(name="Lawn Suit", price="PKR 12,000", was_price="PKR 15,000", image_url="https://x/2.jpg"),
            Product(name="Kurta - Men", price="PKR 6,000")], socials=["instagram", "tiktok"], text="Free delivery on all orders"),
    }

    async def fake_fetch_site(url, client):
        host = httpx.URL(url).host
        if host not in sites:
            raise ingestor.SiteUnavailable(f"{host} is limiting requests right now (429 Too Many Requests).")
        return sites[host]

    async def no_shopify(url, client):
        return None

    monkeypatch.setattr(competitors.trends, "search", fake_search)
    monkeypatch.setattr(competitors, "fetch_html_many", fake_fetch_many)
    monkeypatch.setattr(competitors.ingestor, "fetch_site", fake_fetch_site)
    monkeypatch.setattr(competitors, "shopify_store_data", no_shopify)
    camp = Campaign(start_date=date(2026, 10, 25), days=7, platforms=[Platform.INSTAGRAM], brand=kit())
    monkeypatch.setattr(store, "campaigns", {camp.id: camp})
    monkeypatch.setattr(store, "research", {})
    task = ResearchTask(topic="x", kind="competitors", brand_url=kit().website_url, campaign_id=camp.id)
    store.research[task.id] = task

    async def run():
        async for _ in research.execute(task):
            pass

    asyncio.run(run())
    assert task.status == "completed" and task.topic == "Competitors of Khaadi"
    report = task.competitors
    names = [c.name for c in report.competitors]
    assert names[0] == "Gul Ahmed" and "Sapphire" in names
    gul = report.competitors[0]
    assert gul.reachable and gul.best_discount == 20 and gul.claims == ["Free delivery"] and "men" in gul.segments
    assert not next(c for c in report.competitors if c.name == "Sapphire").reachable
    assert any("Free delivery" in g or "free delivery" in g for g in report.gaps)
    assert report.recommendations and len(report.plan) == 4 and report.method == "rules"
    assert any("Found 2 candidate competitors" in p for p in task.progress)
    assert "### Recommended strategy" in task.report and "| [Gul Ahmed](" in task.report
    assert "Strategy:" in research.campaign_context([task.id])  # usable by campaigns


def test_shopify_store_data_fallback():
    def handler(request: httpx.Request):
        if request.url.path == "/meta.json":
            return httpx.Response(200, json={"name": "GENERATION", "currency": "PKR", "myshopify_domain": "gen.myshopify.com",
                                             "description": "Pakistani fashion since 1983"})
        if request.url.path == "/products.json":
            return httpx.Response(200, json={"products": [{"title": "Zareen Set", "handle": "zareen", "variants": [
                {"price": "9990.00", "compare_at_price": "12990.00"}], "images": [{"src": "https://cdn/z.jpg"}]}]})
        return httpx.Response(429)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await competitors.shopify_store_data("https://www.generation.com.pk/", client)

    site = asyncio.run(run())
    p = competitors.profile_from_site(site, "Generation", "you added it")
    assert p.products_seen == 1 and p.best_discount == 23 and p.price_range == "PKR 9,990" and p.currency == "PKR"
