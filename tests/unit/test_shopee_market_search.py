"""``market_search`` (P92 B-10) through the ingest gateway, SQLite. Every value is synthetic.

The Connector posts page 1 of a public Shopee search for one of the shop's keywords; the gateway
refuses a keyword that is not one of the shop's seeds, keeps ads out of the statistics and writes
the shared public lane (``market_listing_snapshots`` / ``market_keyword_snapshots``).
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select

from juli_backend.models.market import MarketKeywordSnapshot, MarketListingSnapshot
from juli_backend.models.shop_keywords import ShopKeywordSeed
from juli_backend.services.ingest import market
from juli_backend.services.ingest.gateway import IngestRejected
from juli_backend.services.ingest.rate_limit import InMemoryRateGate, set_ingest_rate_gate
from juli_backend.services.market_stats import median, percentile
from juli_backend.services.privacy.payload_allowlist import allowlist_payload, ingest_endpoint
from tests.unit.test_shopee_file_datasets import _ingest, _shop

KW = "găng tay cao su"


@pytest.fixture(autouse=True)
def gate_and_switch(monkeypatch):
    set_ingest_rate_gate(InMemoryRateGate())
    monkeypatch.setenv(market.ENV_FLAG, "1")
    monkeypatch.delenv(market.ENV_SHOPS, raising=False)
    yield
    set_ingest_rate_gate(None)


def _card(pos: int, price: int, **over: Any) -> dict[str, Any]:
    row = {
        "keyword": KW,
        "sort": "relevancy",
        "page": 1,
        "pos": pos,
        "item_id": str(9000 + pos),
        "shop_id": str(500 + pos),
        "shop_title": f"Shop {pos}",
        "title": f"Găng tay cao su hộp 100 cái {pos}",
        "price": price,
        "sold_monthly": 100 * pos,
    }
    row.update(over)
    return row


def _body(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "source": "extension",
        "source_version": "0.3.5",
        "captured_at": "2026-10-30T09:30:00+07:00",
        "period": {"start": "2026-10-30", "end": "2026-10-30", "granularity": "period"},
        "rows": rows,
    }


async def _seed(session, shop, keyword: str = KW, item: str = "1001", role: str = "chinh"):
    session.add(
        ShopKeywordSeed(
            id=uuid.uuid4(),
            shop_id=shop.id,
            platform="shopee",
            keyword=keyword,
            pattern="common_phrase",
            item_ids=[item],
            role=role,
            item_scope=item,
        )
    )
    await session.flush()


async def test_cards_and_keyword_summary_land_in_the_public_lane(session):
    shop = await _shop(session)
    await _seed(session, shop)
    rows = [
        _card(1, 100_000),
        _card(2, 120_000, price_before_discount=150_000, discount_pct=20),
        _card(3, 80_000, price_min=80_000, price_max=95_000),
        _card(4, 5_000, is_ad=True),
    ]
    result = await _ingest(session, shop, "market_search", _body(rows))
    assert result.rows == 4
    cards = (await session.execute(select(MarketListingSnapshot))).scalars().all()
    assert len(cards) == 4
    by_pos = {c.pos: c for c in cards}
    assert by_pos[3].extra["price_max"] == 95000.0
    assert by_pos[4].extra["is_ad"] is True
    assert by_pos[1].collector == "extension"
    assert by_pos[1].platform_shop_id == "501"
    summary = (await session.execute(select(MarketKeywordSnapshot))).scalar_one()
    assert summary.collected_on == date(2026, 10, 30)
    assert summary.n_cards == 3  # the ad is left out of every statistic
    assert summary.median_price_page1 == Decimal("100000")
    assert summary.share_discounted == Decimal("0.3333")
    assert summary.sold_monthly_median == Decimal("200")


async def test_a_keyword_that_is_not_the_shops_seed_is_refused(session):
    shop = await _shop(session)
    await _seed(session, shop)
    with pytest.raises(IngestRejected) as err:
        await _ingest(session, shop, "market_search", _body([_card(1, 1000, keyword="khác")]))
    assert err.value.code == "market_keyword_unknown"
    assert (await session.execute(select(MarketListingSnapshot))).first() is None


async def test_an_excluded_seed_is_not_searchable(session):
    shop = await _shop(session)
    await _seed(session, shop, role="loai_tru")
    with pytest.raises(IngestRejected):
        await _ingest(session, shop, "market_search", _body([_card(1, 1000)]))


async def test_the_server_switch_and_shop_list_gate_the_dataset(session, monkeypatch):
    shop = await _shop(session)
    await _seed(session, shop)
    monkeypatch.setenv(market.ENV_SHOPS, str(uuid.uuid4()))
    with pytest.raises(IngestRejected) as err:
        await _ingest(session, shop, "market_search", _body([_card(1, 1000)]))
    assert err.value.code == "market_search_disabled"
    monkeypatch.setenv(market.ENV_SHOPS, str(shop.id))
    assert (await _ingest(session, shop, "market_search", _body([_card(1, 1000)]))).rows == 1
    monkeypatch.setenv(market.ENV_FLAG, "0")
    assert market.enabled(shop.id) is False


async def test_the_row_model_refuses_bad_cards(session):
    shop = await _shop(session)
    await _seed(session, shop)
    for bad in (
        _card(1, 1000, price_min=9000, price_max=1000),
        _card(1, -5),
        _card(0, 1000),
        {**_card(1, 1000), "buyer": "x"},
    ):
        with pytest.raises(IngestRejected):
            await _ingest(session, shop, "market_search", _body([bad]))
    with pytest.raises(IngestRejected):  # duplicate card key
        await _ingest(session, shop, "market_search", _body([_card(1, 1000), _card(1, 2000)]))


async def test_a_repost_is_a_duplicate_and_writes_nothing_twice(session):
    shop = await _shop(session)
    await _seed(session, shop)
    body = _body([_card(1, 1000), _card(2, 2000)])
    await _ingest(session, shop, "market_search", body)
    again = await _ingest(session, shop, "market_search", body)
    assert again.duplicate is True
    assert len((await session.execute(select(MarketListingSnapshot))).scalars().all()) == 2


async def test_main_keywords_per_product_core_first_and_due_weekly(session):
    shop = await _shop(session)
    for kw, role in (("a", "phu"), ("b", "chinh"), ("c", "phu"), ("d", "chinh"), ("e", "loai_tru")):
        await _seed(session, shop, keyword=kw, role=role)
    picked = (await market.shop_keywords(session, shop.id))["1001"]
    assert picked == ["b", "d", "a"]
    today = date(2026, 11, 5)
    last = {"b": date(2026, 11, 1), "d": date(2026, 10, 29)}
    assert market.due(picked, last, today) == ["d", "a"]


def test_raw_copy_keeps_listed_fields_only():
    body = _body([_card(1, 1000)])
    body["rows"][0]["extra"] = {"n": 1, "text": "x"}
    kept = allowlist_payload("shopee", ingest_endpoint("market_search"), body)
    assert kept["rows"][0]["title"].startswith("Găng tay")
    assert kept["rows"][0]["extra"] == {"n": 1}


def test_percentiles_interpolate():
    assert percentile([], 0.5) is None
    assert median([10, 20, 30, 40]) == 25
    assert percentile([10, 20, 30, 40, 50], 0.25) == 20
    assert percentile([7], 0.9) == 7
