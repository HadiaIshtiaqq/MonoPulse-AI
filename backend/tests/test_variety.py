"""A month of posts shouldn't feel like the same post 30 times."""
import asyncio
from collections import Counter
from datetime import date, datetime, timezone

import pytest
from PIL import Image

from app import config
from app.agents import pipeline, renderer, strategist, variety
from app.schemas import Background, BrandKit, Platform, Product, SocialPost


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(config, "NEBIUS_API_KEY", "")
    monkeypatch.setattr(config, "AWS_BEDROCK_ENABLED", False)


def store_kit() -> BrandKit:
    products = [Product(name=n, price=p, was_price=w, url=f"https://shop.example/{i}", image_url=f"https://cdn.example/{i}.jpg")
                for i, (n, p, w) in enumerate([("Power - Men", "Rs.4,199.00", "Rs.5,999.00"), ("Comfit - Women", "Rs.1,959.00", ""),
                                               ("Bubble Gummers - Kids", "Rs.2,449.00", "Rs.3,499.00"), ("Weinbrenner - Men", "Rs.3,149.00", ""),
                                               ("Floatz - Men", "Rs.1,959.00", ""), ("Red Label - Women", "Rs.2,799.00", "")])]
    return BrandKit(source_input="x", name="Bata Pakistan", industry="Footwear", country="PK", segments=["men", "women", "kids"],
                    value_props=["Pakistan's favourite footwear brand", "Timeless designs, exceptional comfort, and nationwide delivery"],
                    products=products, website_url="https://www.bata.com.pk/")


def month_of_copy(kit, platforms=(Platform.INSTAGRAM,)):
    strategy = strategist.fallback_strategy(kit, [], 5, start=date(2026, 10, 25))
    slots = strategist.plan_slots(strategy, [], list(platforms), 30, 1, products=kit.products, claims=len(kit.value_props))
    return slots, asyncio.run(strategist.write_all(kit, strategy, slots))


def test_post_types_mix_and_never_repeat_back_to_back():
    kinds = variety.plan_kinds(30, products=6, on_sale=2, claims=2, moments=["11.11 sale"] * 30)
    assert all(a != b for a, b in zip(kinds, kinds[1:]))
    assert set(kinds) == {"spotlight", "carousel", "duo", "tip", "quote", "sale", "moment"}
    # A brand without products gets questions instead of duos and sales.
    plain = variety.plan_kinds(12, products=0, on_sale=0, claims=1, moments=[""] * 12)
    assert "duo" not in plain and "sale" not in plain and "question" in plain


def test_a_month_of_copy_has_no_repeated_headlines_or_endings():
    slots, copies = month_of_copy(store_kit())
    heads = [variety.normalize(c["headline"]) for c in copies]
    assert len(heads) == len(set(heads)), [h for h, n in Counter(heads).items() if n > 1]
    endings = [c["caption"].strip().split("\n")[-1] for c in copies]
    assert all(a != b for a, b in zip(endings, endings[1:]))  # consecutive posts end differently
    ctas = [c["cta"] for c in copies]
    assert all(a != b for a, b in zip(ctas, ctas[1:]))
    by_kind = {s.kind: c for s, c in zip(slots, copies)}
    assert by_kind["duo"]["headline"] in ("This or that?", "Pick one: Power for men or Comfit for women?") or "or" in by_kind["duo"]["headline"]
    assert "-" not in by_kind["quote"]["headline"] and by_kind["quote"]["headline"]
    sale_heads = [c["headline"] for s, c in zip(slots, copies) if s.kind == "sale"]
    assert sale_heads and all(any(w in h for w in ("% off", "Price drop", "Sale pick", "Now ")) for h in sale_heads)
    # The same post type never features the same product twice in a row.
    for kind in {s.kind for s in slots}:
        featured = [s.product.url for s in slots if s.kind == kind and s.product]
        assert all(a != b for a, b in zip(featured, featured[1:])), kind


def test_model_headline_repeats_are_replaced(monkeypatch):
    kit = store_kit()
    monkeypatch.setattr(config, "NEBIUS_API_KEY", "key")

    async def same_every_time(kit_, strategy, batch, offset, research=""):
        return [{"slot": offset + j, "headline": "Step into comfort", "caption": f"Caption {offset + j}", "cta": "Shop"} for j in range(len(batch))]

    monkeypatch.setattr(strategist, "write_batch", same_every_time)
    strategy = strategist.fallback_strategy(kit, [], 2, start=date(2026, 10, 25))
    slots = strategist.plan_slots(strategy, [], [Platform.INSTAGRAM, Platform.X], 8, 1, products=kit.products, claims=2)
    copies = asyncio.run(strategist.write_all(kit, strategy, slots))
    per_idea = {}
    for s, c in zip(slots, copies):
        per_idea.setdefault((s.group, s.format), c["headline"])
    heads = [variety.normalize(h) for h in per_idea.values()]
    assert heads.count("step into comfort") == 1 and len(heads) == len(set(heads))
    assert all(c["caption"].startswith("Caption") for c in copies)  # the model's captions are kept


def test_layouts_rotate_and_new_layouts_render(tmp_path):
    def photo(name, color):
        p = tmp_path / name
        Image.new("RGB", (600, 900), color).save(p)
        return Background(source="website", path=str(p))

    kit = store_kit()
    now = datetime.now(timezone.utc)
    posts = []
    for i, kind in enumerate(["spotlight", "duo", "tip", "quote", "sale", "spotlight", "moment"]):
        p = SocialPost(campaign_id="c", group_id=f"g{i}", day=i, platform=Platform.INSTAGRAM, kind=kind, headline=f"Post {i}",
                       publish_at=now, product=None if kind == "quote" else kit.products[i % 6],
                       compare=kit.products[(i + 1) % 6] if kind == "duo" else None)
        if kind != "quote":
            p.background = photo(f"{i}.jpg", (40 * i, 80, 120))
        if kind == "duo":
            p.gallery = [photo(f"{i}b.jpg", (200, 40, 40))]
        posts.append(p)
    pipeline.assign_layouts(posts)
    looks = [(p.layout, p.text_position) for p in posts]
    assert all(a != b for a, b in zip(looks, looks[1:]))
    assert {p.layout for p in posts} >= {"photo", "frame", "duo", "quote"}
    for platform in Platform:
        for p in posts:
            img = renderer.render(kit, p.model_copy(update={"platform": platform}))
            assert img.size == renderer.SIZES[platform]
    report = variety.variety_report(posts)
    assert report["posts"] == 7 and len(report["types"]) == 6 and report["repeated_headlines"] == 0
