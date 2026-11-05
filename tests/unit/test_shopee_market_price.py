"""P92 B-10 "Giá thị trường": pack parser, per-unit statistics, stale / absent states and the
Demo + Ops routes. Synthetic cards; SQLite."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from types import SimpleNamespace

import pytest

from juli_backend.models.market import MarketListingSnapshot
from juli_backend.models.shop_keywords import ShopKeywordSeed
from juli_backend.services.shopee_builder import market_price as mp
from juli_backend.services.shopee_builder import unit_price as up
from tests.support.api import authenticate, build_app, client_for
from tests.support.shopee_reco import AS_OF, seed_reco_shop
from tests.unit.test_ops_shopee_dashboards import _ops_client

TODAY = date(2026, 11, 5)
CAPTURED = datetime(2026, 11, 3, 3, 0)
KW = "nước rửa chén"


# ------------------------------------------------------------------ pack parser


@pytest.mark.parametrize(
    ("title", "unit", "qty"),
    [
        ("Nước rửa chén 500ml hương chanh", "ml", 500),
        ("Nước rửa chén 2 chai 500ml", "ml", 1000),
        ("Nước rửa chén can 1 lít", "ml", 1000),
        ("Combo 3 hộp găng tay 100 cái", "cai", 300),
        ("Găng tay cao su hộp 100 cái", "cai", 100),
        ("Hộp 100 găng tay", "cai", 100),
        ("Combo 5 hộp găng tay", "hop", 5),
        ("Băng keo trong 5 cuộn", "cuon", 5),
        ("Bột giặt 2kg", "g", 2000),
        ("Khăn giấy", "item", 1),
        ("Set 3 khăn giấy", "item", 3),
    ],
)
def test_the_pack_parser_reads_unit_and_quantity(title, unit, qty):
    q = up.parse(title)
    assert (q.unit, q.qty) == (unit, qty)


def test_per_unit_price_is_per_comparable_unit():
    assert up.per_unit_price(90_000, up.parse("Nước rửa chén 500ml")) == 90_000
    assert up.per_unit_price(90_000, up.parse("Nước rửa chén 1 lít")) == 45_000
    assert up.per_unit_price(300_000, up.parse("Combo 3 hộp găng tay")) == 100_000
    assert up.per_unit_price(150_000, up.parse("Găng tay 300 cái")) == 50_000
    assert up.per_unit_price(0, up.parse("x")) is None


def test_the_own_title_leaves_the_pack_to_the_variation():
    own = up.parse("Găng tay cao su hộp 100 cái", multiplier=False)
    assert (own.unit, own.qty) == ("cai", 100)
    assert up.parse("Combo 3 hộp", multiplier=False).qty == 1


def test_similarity_is_shared_content_words():
    assert up.similarity("Nước rửa chén Ory 500ml", "Nước rửa chén hương chanh 500ml") > 0.4
    assert up.similarity("Nước rửa chén", "Găng tay cao su") == 0


# ------------------------------------------------------------------ the computation


def _row(pos, title, price, *, ad=False, item=None, shop="Shop", sold=10):
    return SimpleNamespace(
        platform_item_id=item or str(7000 + pos),
        title=title,
        price=price,
        sold_monthly=sold,
        sold_lifetime=sold * 10,
        pos=pos,
        extra={"is_ad": ad, "shop_title": f"{shop} {pos}"},
    )


def _cards():
    return [
        _row(1, "Nước rửa chén hương chanh 500ml", 80_000),
        _row(2, "Nước rửa chén diệt khuẩn 500ml", 90_000),
        _row(3, "Nước rửa chén thiên nhiên 1 lít", 160_000),  # 80 000 per 500 ml
        _row(4, "Nước rửa chén 2 chai 500ml", 200_000),  # 100 000 per 500 ml
        _row(5, "Nước rửa chén cao cấp 500ml", 1_000, ad=True),
        _row(6, "Găng tay cao su hộp 100 cái", 50_000),  # another unit and words
        _row(7, "Nước rửa chén Ory 500ml", 90_000, item="1002"),  # the product's own listing
    ]


def _variations(price=90_000, pack=1):
    return [{"variation_id": "", "selling_price": price, "pack_count": pack}]


def _compute(cards=None, **over):
    args = {
        "item_id": "1002",
        "name": "Nước rửa chén Ory 500ml",
        "keywords": [KW],
        "captures": {KW: (CAPTURED, _cards() if cards is None else cards)},
        "variation_rows": _variations(),
        "variation_id": None,
        "draft_price": None,
        "today": TODAY,
    }
    args.update(over)
    return mp.compute(**args)


def test_per_unit_median_quartiles_closest_and_what_is_left_out():
    out = _compute()
    assert out["available"] is True and out["unit"]["key"] == "ml"
    market = out["market"]
    assert market["n_similar"] == 4  # the ad, the other unit and our own listing are out
    assert (market["median"], market["p25"], market["p75"]) == (85_000, 80_000, 92_500)
    assert market["position"] == "within" and market["own_vs_median_pct"] == 5.9
    assert out["own"]["price_per_unit"] == 90_000
    assert {c["item_id"] for c in out["closest"]}.isdisjoint({"1002", "7005", "7006"})
    assert len(out["closest"]) == 4 and out["keyword"] == KW
    assert out["collected_on"] == "2026-11-03" and out["age_days"] == 2 and out["stale"] is False
    assert all(c["similarity"] >= 0.25 for c in out["closest"])


def test_a_pack_variation_is_priced_per_unit_and_the_marker_sits_in_the_range():
    out = _compute(variation_rows=_variations(price=250_000, pack=3), draft_price=240_000)
    assert out["own"]["pack_count"] == 3 and out["own"]["price_per_unit"] == 83_333
    assert out["market"]["position"] == "within"
    assert out["marker"]["price_per_unit"] == 80_000
    low = _compute(draft_price=40_000)
    assert low["marker"]["position"] == "below_p25"
    high = _compute(draft_price=400_000)
    assert high["marker"]["position"] == "above_p75" and high["marker"]["vs_median_pct"] > 0


def test_stale_after_14_days_keeps_the_date():
    out = _compute(today=date(2026, 11, 20))
    assert out["stale"] is True and out["age_days"] == 17 and out["available"] is True
    assert _compute(today=date(2026, 11, 17))["stale"] is False  # 14 days exactly


def test_absent_states_never_carry_numbers():
    none = _compute(keywords=[])
    assert none["reason"] == "no_keyword" and none["available"] is False and none["market"] is None
    cap = _compute(captures={})
    assert cap["reason"] == "no_capture" and cap["closest"] is None
    few = _compute(cards=_cards()[:2])
    assert few["reason"] == "no_similar" and few["market"] is None and few["n_similar"] == 2
    assert few["collected_on"] == "2026-11-03"


def test_a_lightweight_call_leaves_the_listings_out():
    out = _compute(closest=False)
    assert out["available"] is True and out["closest"] is None and out["market"]["median"]


def test_two_keywords_merge_without_double_counting():
    cards = _cards()
    out = _compute(
        keywords=[KW, "rửa chén"],
        captures={KW: (CAPTURED, cards), "rửa chén": (datetime(2026, 10, 1), cards[:3])},
    )
    assert out["market"]["n_similar"] == 4
    assert {k["keyword"]: k["stale"] for k in out["keywords"]} == {KW: False, "rửa chén": True}
    assert out["collected_on"] == "2026-11-03"  # the newest capture dates the block


# ------------------------------------------------------------------ routes


@pytest.fixture
async def reco(session):
    seeded = await seed_reco_shop(session)
    session.add(
        ShopKeywordSeed(
            id=uuid.uuid4(),
            shop_id=seeded.shop_id,
            platform="shopee",
            keyword=KW,
            pattern="common_phrase",
            item_ids=["1002"],
            role="chinh",
            item_scope="1002",
        )
    )
    await session.commit()
    return seeded


async def _capture(session):
    for card in _cards():
        session.add(
            MarketListingSnapshot(
                id=uuid.uuid4(),
                platform="shopee",
                keyword=KW,
                sort="relevancy",
                page=1,
                pos=card.pos,
                collected_at=CAPTURED,
                platform_item_id=card.platform_item_id,
                title=card.title,
                price=card.price,
                sold_monthly=card.sold_monthly,
                collector="extension",
                extra=card.extra,
            )
        )
    await session.commit()


async def test_demo_route_is_absent_without_a_capture_then_present(session, reco):
    app = build_app(session)
    authenticate(app, user=reco.user, shop=reco.shop)
    async with client_for(app) as client:
        r = await client.get(f"/v1/demo/shopee/products/1002/market-price?as_of={AS_OF}")
        assert r.status_code == 200
        assert r.json()["available"] is False and r.json()["reason"] == "no_capture"
        await _capture(session)
        await session.refresh(reco.shop)
        await session.refresh(reco.user)
        r = await client.get(
            f"/v1/demo/shopee/products/1002/market-price?as_of={AS_OF}&price=70000"
        )
        out = r.json()
        assert out["available"] is True and out["market"]["n_similar"] == 4
        assert out["marker"]["price_per_unit"] == 70_000 and out["closest"]
        lite = await client.get(f"/v1/demo/shopee/builder/products/1002/market-range?as_of={AS_OF}")
        assert (
            lite.json()["closest"] is None
            and lite.json()["market"]["median"] == out["market"]["median"]
        )
        assert (await client.get("/v1/demo/shopee/products/nope/market-price")).status_code == 404
    app.dependency_overrides.clear()


async def test_ops_route_reads_as_viewer(session, reco, monkeypatch):
    await _capture(session)
    viewer = await _ops_client(session, monkeypatch, "viewer")
    async with client_for(viewer) as client:
        r = await client.get(
            f"/v1/ops/shops/{reco.shop_id}/shopee/products/1002/market-price?as_of={AS_OF}"
        )
        assert r.status_code == 200 and r.json()["market"]["n_similar"] == 4
        r = await client.get(
            f"/v1/ops/shops/{reco.shop_id}/shopee/builder/products/1002/market-range"
            f"?as_of={AS_OF}&price=88000"
        )
        assert r.json()["marker"]["position"] == "within" and r.json()["closest"] is None
    viewer.dependency_overrides.clear()
