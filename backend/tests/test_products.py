"""Real products, site photos and logo colours from a brand's website."""
import asyncio
import io
from datetime import datetime, timezone

import httpx
import pytest
from bs4 import BeautifulSoup
from PIL import Image

from app import config
from app.agents import photos, pipeline, renderer, strategist
from app.schemas import Background, BrandKit, CampaignStrategy, ContentPillar, Platform, Product, Slide, SocialPost
from app.scraper import ingestor
from app.scraper.products import extract_products, extract_site_images, shopify_products

BASE = "https://shop.example/collection/"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(config, "NEBIUS_API_KEY", "")
    monkeypatch.setattr(config, "AWS_BEDROCK_ENABLED", False)

STORE_TILES = """
<html><body>
<header><img src="/img/logo.png" alt="Shop logo"></header>
<div class="product" data-gtmdata='{"id":"A1","name":"2-Piece Co-ord Set","category":"Artisanal Block","price":"20000.00"}'>
  <div class="image-container" data-large-0="https://cdn.example/a1_1.jpg?sw=800"></div>
  <a href="/2-piece/A1.html?source=plp"><img src="/lazy.gif" alt=""></a>
  <span class="name">2-Piece Co-ord Set</span><span class="price">PKR 20,000</span>
</div>
<div class="product" data-gtmdata='{"id":"B2","name":"Kurta","category":"Lawn","price":"6500.00"}'>
  <img srcset="https://cdn.example/b2_400.jpg 400w, https://cdn.example/b2_1200.jpg 1200w" src="https://cdn.example/b2_400.jpg">
  <a href="/kurta/B2.html">Kurta</a><span>PKR 6,500</span>
</div>
</body></html>"""

JSON_LD = """
<html><head><script type="application/ld+json">
{"@context":"https://schema.org","@type":"ItemList","itemListElement":[
  {"@type":"ListItem","position":1,"item":{"@type":"Product","name":"Country Sourdough","image":["/img/sourdough.jpg"],
   "url":"/p/sourdough","offers":{"@type":"Offer","price":"12.00","priceCurrency":"USD"}}}]}
</script></head><body>
<section style="background-image: url('/img/hero-bakery.jpg')"></section>
<img src="/img/icon-cart.png" alt="cart icon" width="24">
<img src="/img/counter.jpg" alt="Our counter" width="1200">
</body></html>"""

CARDS = """
<html><body>
<div class="card"><a href="/p/latte"><img src="/img/latte.jpg" alt="Oat Latte"></a><p>$5.50</p></div>
<div class="card"><a href="/p/croissant"><img src="/img/croissant.jpg" alt="Butter Croissant"></a><p>$4</p></div>
</body></html>"""


def test_store_tiles_give_real_names_prices_photos_and_links():
    products = extract_products(BeautifulSoup(STORE_TILES, "html.parser"), BASE)
    assert [p.name for p in products] == ["2-Piece Co-ord Set", "Kurta"]
    first, second = products
    assert first.price == "PKR 20,000" and first.category == "Artisanal Block"
    assert first.image_url == "https://cdn.example/a1_1.jpg?sw=800"
    assert first.url == "https://shop.example/2-piece/A1.html?source=plp"
    assert second.image_url == "https://cdn.example/b2_1200.jpg"  # largest srcset candidate


def test_jsonld_products_and_site_photos():
    soup = BeautifulSoup(JSON_LD, "html.parser")
    (p,) = extract_products(soup, "https://bakery.example/")
    assert p.name == "Country Sourdough" and p.price == "$12" and p.image_url == "https://bakery.example/img/sourdough.jpg"
    images = extract_site_images(soup, "https://bakery.example/")
    assert "https://bakery.example/img/counter.jpg" in images and "https://bakery.example/img/hero-bakery.jpg" in images
    assert not any("icon" in u for u in images)


def test_generic_cards_fallback():
    products = extract_products(BeautifulSoup(CARDS, "html.parser"), "https://cafe.example/")
    assert {(p.name, p.price) for p in products} == {("Oat Latte", "$5.50"), ("Butter Croissant", "$4")}


def test_shopify_products_json():
    data = {"products": [{"title": "Linen Shirt", "handle": "linen-shirt", "product_type": "Shirts",
                          "variants": [{"price": "49.00"}], "images": [{"src": "https://cdn.shopify.com/s/linen.jpg"}]}]}
    (p,) = shopify_products(data, "https://store.example", "USD")
    assert (p.name, p.price, p.url, p.category) == ("Linen Shirt", "$49", "https://store.example/products/linen-shirt", "Shirts")


def test_product_names_drop_stock_codes():
    data = {"products": [{"title": "Sandstone - 3 Pc (WU3PPBS26-LI1F67)", "handle": "sandstone",
                          "variants": [{"price": "4990"}], "images": [{"src": "https://cdn.shopify.com/s/s.jpg"}]},
                         {"title": "12-PCS Gift Box", "handle": "gift",
                          "variants": [{"price": "20"}], "images": [{"src": "https://cdn.shopify.com/s/g.jpg"}]}]}
    names = [p.name for p in shopify_products(data, "https://store.example", "USD")]
    assert names == ["Sandstone - 3 Pc", "12-PCS Gift Box"]


def _logo_bytes() -> bytes:
    img = Image.new("RGB", (200, 120), "white")
    for x in range(30, 170):
        for y in range(20, 100):
            img.putpixel((x, y), (237, 83, 63))  # coral mark
    for x in range(40, 160):
        for y in range(50, 70):
            img.putpixel((x, y), (33, 31, 31))  # charcoal wordmark
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def test_logo_colours_beat_platform_css():
    logo = _logo_bytes()
    css = ["#00A1E0"] * 30 + ["#008827"] * 20  # a store platform's default stylesheet colours
    palette = ingestor.choose_palette(None, ingestor.dominant_colors_from_image(logo), css)
    assert palette and ingestor._distance(palette[0], "#ED533F") < 30
    assert all(ingestor._distance(c, "#00A1E0") > 60 for c in palette)
    kit = ingestor.apply_palette(BrandKit(source_input="x", name="X"), palette, ink=ingestor.ink_color_from_image(logo))
    assert ingestor._distance(kit.secondary_color, "#211F1F") < 30
    # Without a logo colour the page CSS is still used.
    assert ingestor.choose_palette(None, [], css)[0] == "#00A1E0"


def _catalogue() -> list[Product]:
    names = ["3-Piece Set", "3-Piece Set", "3-Piece Set", "Kurta", "Dupatta"]
    return [Product(name=n, price=f"PKR {i + 1},000", image_url=f"https://cdn.example/{i}.jpg", url=f"https://shop.example/{i}")
            for i, n in enumerate(names)]


def test_slots_feature_varied_products_and_carousels_with_all_platforms():
    strategy = CampaignStrategy(pillars=[ContentPillar(name=n) for n in ("Behind the Scenes", "Customer Wins", "Quick Tips", "Offers & News")],
                                weekly_themes=["Launch"])
    slots = strategist.plan_slots(strategy, [], list(Platform), 12, 1, products=_catalogue())
    assert all(s.product for s in slots)
    first_version = [s for s in slots if s.platform is Platform.INSTAGRAM]
    assert [s.product.name for s in first_version[:3]] == ["3-Piece Set", "Kurta", "Dupatta"]
    for g in {s.group for s in slots}:  # every platform version features the same product
        assert len({s.product.url for s in slots if s.group == g}) == 1
    carousels = [s for s in slots if s.format == "carousel"]
    assert carousels and all(s.platform in strategist.CAROUSEL_PLATFORMS and len(s.slide_products) == 3 for s in carousels)
    copies = asyncio.run(strategist.write_all(BrandKit(source_input="x", name="Shop", industry="Fashion & Apparel"), strategy, slots))
    for slot, copy in zip(slots, copies):
        assert slot.product.price in copy["caption"]
        if slot.format == "carousel":
            assert [s["headline"] for s in copy["slides"]] == [p.name for p in slot.slide_products]
    assert strategist.short_name("3 Piece Printed Cotton Linen Suit with Dupatta") == "3 Piece Printed Cotton Linen Suit"
    assert strategist.short_name("Kurta - Lawn Collection") == "Kurta"


def test_site_photos_go_on_posts_and_carousel_pages(monkeypatch, tmp_path):
    calls = []

    async def fake_bg(url, credit, credit_url=""):
        calls.append(url)
        if "broken" in url:
            raise ValueError("not an image")
        path = tmp_path / f"{len(calls)}.jpg"
        Image.new("RGB", (800, 1200), (200, 180, 160)).save(path)
        return Background(source="website", path=str(path), thumb_url="/media/x.jpg", credit=credit, credit_url=credit_url or url)

    monkeypatch.setattr(photos, "website_background", fake_bg)
    cat = _catalogue()
    kit = BrandKit(source_input="x", name="Shop", products=cat, images=["https://shop.example/hero.jpg", "https://shop.example/broken.jpg"])
    now = datetime.now(timezone.utc)
    single = SocialPost(campaign_id="c", day=0, platform=Platform.INSTAGRAM, product=cat[0], publish_at=now)
    carousel = SocialPost(campaign_id="c", day=1, platform=Platform.INSTAGRAM, format="carousel", product=cat[3],
                          slides=[Slide(headline="a"), Slide(headline="b")], publish_at=now)
    plain = SocialPost(campaign_id="c", day=2, platform=Platform.X, publish_at=now)
    attached = asyncio.run(pipeline.attach_site_photos(kit, [single, carousel, plain], {carousel.id: [cat[4], cat[1]]}))
    assert attached == 3 and all(p.layout == "photo" for p in (single, carousel, plain))
    assert single.background.credit_url == cat[0].url
    assert all(s.background for s in carousel.slides)
    assert len(calls) == len(set(calls))  # each photo downloaded once
    for post in (single, carousel, plain):
        pages = renderer.render_pages(kit, post)
        assert pages[0].size == (renderer.CAROUSEL_SIZE if post.format == "carousel" else renderer.SIZES[post.platform])


def test_rate_limited_site_is_retried_then_explained(monkeypatch):
    monkeypatch.setattr(ingestor, "RETRY_DELAYS", (0.01, 0.01))
    hits = []

    def handler(request):
        hits.append(request.url)
        if len(hits) < 3:
            return httpx.Response(429, headers={"retry-after": "0"})
        return httpx.Response(200, text="<html><title>Gul Ahmed</title></html>")

    async def run(transport):
        async with httpx.AsyncClient(transport=transport) as client:
            return await ingestor.get_page(client, "https://store.example/p/1")

    assert asyncio.run(run(httpx.MockTransport(handler))).status_code == 200 and len(hits) == 3
    with pytest.raises(ingestor.SiteUnavailable, match="limiting requests"):
        asyncio.run(run(httpx.MockTransport(lambda r: httpx.Response(429))))


SVG_LOGO = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 50"><rect width="200" height="50" fill="#8CC63F"/></svg>'


def test_svg_logo_is_rendered_and_partner_logos_are_ignored():
    png = ingestor.rasterize_svg(SVG_LOGO, width=400)
    assert Image.open(io.BytesIO(png)).size == (400, 100)
    assert ingestor._distance(ingestor.dominant_colors_from_image(png)[0], "#8CC63F") < 20
    assert ingestor.is_svg("https://x/logo.svg?v=1", "", b"") and ingestor.is_svg("https://x/l", "", SVG_LOGO)
    html = """<html><head><title>Shirt | GulAhmed</title><meta property="og:site_name" content="GulAhmed Ideas"></head><body>
      <div class="popup"><img src="/files/YANGO-Logo.png" alt="Yango"></div>
      <footer><img src="/files/Ideas_by_Gul_Ahmed_logo.png" alt="logo"></footer></body></html>"""
    site = ingestor.parse_html(html, "https://www.gulahmedshop.com/products/shirt")
    assert not any("YANGO" in u for u in site.logo_candidates)
    assert any("Gul_Ahmed" in u for u in site.logo_candidates)


def test_share_links_never_send_facebook_a_website_preview():
    from app.publishing import share_links

    now = datetime.now(timezone.utc)

    def post(platform):
        return SocialPost(campaign_id="c", day=0, platform=platform, caption="New in: Kurta. PKR 6,500.", hashtags=["#Kurta"],
                          image_url="/media/c_1.png", publish_at=now)

    fb = share_links(post(Platform.FACEBOOK))
    assert fb["url"] == "https://www.facebook.com/" and fb["image_url"].endswith("/media/c_1.png")
    assert "PKR%206%2C500" in share_links(post(Platform.X))["url"]  # caption prefilled where allowed
    assert "shareActive=true&text=" in share_links(post(Platform.LINKEDIN))["url"]


def test_wide_post_with_tall_product_photo_uses_split(tmp_path):
    path = tmp_path / "tall.jpg"
    Image.new("RGB", (600, 900), (10, 10, 10)).save(path)
    post = SocialPost(campaign_id="c", day=0, platform=Platform.X, layout="photo", headline="New in", publish_at=datetime.now(timezone.utc),
                      product=Product(name="Kurta", price="PKR 6,500"),
                      background=Background(source="website", path=str(path)))
    img = renderer.render(BrandKit(source_input="x", name="Shop", primary_color="#ED533F"), post)
    assert img.size == renderer.SIZES[Platform.X]
    assert img.getpixel((img.width - 50, img.height // 2)) == (10, 10, 10)  # the photo, uncropped, on the right
    assert config.MEDIA_DIR.exists()


def test_indolj_menu_becomes_products_and_branches():
    from app.scraper import products as pf

    item = lambda iid, name, price, photo="https://assets.indolj.io/upload/a b.jpg?q=10": {  # noqa: E731
        "item_id": iid, "item_name": name, "photo": photo, "prices": [{"price": price, "pretty_price": f"Rs. {price:,}"}]}
    menu = {"details": {
        "1": {"title": "Burgers", "items": {"10": item("10", "ZINGER BURGER", 450), "11": item("11", "Extra Cheese", 100)}},
        "2": {"title": "Popular Items", "items": {"20": item("20", "Chicken Mandi", 1150), "21": item("21", "Raita", 50)}},
        "3": {"title": "Beverages", "items": {"30": item("30", "Cold Drink Can", 150),
                                               "31": item("31", "Milkshake", 530, "https://assets.indolj.io/upload/placholde-general2.png")}},
    }}
    got = pf.indolj_products(menu, "https://kj.example")
    assert [(p.name, p.price, p.category) for p in got] == [("Chicken Mandi", "Rs. 1,150", "Popular Items"), ("Zinger Burger", "Rs. 450", "Burgers")]
    assert got[0].image_url == "https://assets.indolj.io/upload/a%20b.jpg"

    html = ('<img src="https://assets.indolj.io/upload/logo.png"><script>self.__next_f.push([1,"{\\"token\\":\\"eyJa.eyJb.sig\\",'
            '\\"active_branches\\":[{\\"name\\":\\"PECHS Block 2 Karachi\\"},{\\"name\\":\\"Gulberg  Lahore\\"},{\\"name\\":\\"Clifton Karachi\\"}]}"])</script>')
    assert pf.is_indolj(html) and pf.indolj_token(html) == "eyJa.eyJb.sig"
    branches = pf.indolj_branches(html)
    assert branches == ["PECHS Block 2 Karachi", "Gulberg Lahore", "Clifton Karachi"]
    assert ingestor.branch_cities(branches) == ["Karachi", "Lahore"]


def test_fast_food_reads_as_food_and_beverage():
    assert ingestor.guess_industry("Product: Zinger Burger (Burgers)\nProduct: Crispy Wings\nFried chicken and fries") == "Food & Beverage"
