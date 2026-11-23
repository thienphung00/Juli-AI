"""F4.2: the Connector's hole list (``GET /v1/connector/shopee/read-days``). Synthetic values."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from juli_backend.models.ingest import IngestRawPayload, PlatformDailyMetric
from juli_backend.services.ingest import read_days
from juli_backend.services.ingest.rate_limit import InMemoryRateGate, set_ingest_rate_gate
from tests.support.api import client_for
from tests.unit.test_ingest_gateway import _paired_client, _shopee_tenant

TODAY = date(2026, 11, 19)


@pytest.fixture(autouse=True)
def generous_gate():
    set_ingest_rate_gate(InMemoryRateGate())
    yield
    set_ingest_rate_gate(None)


def test_the_window_is_the_30_days_before_today_oldest_first():
    days = read_days.window_days(TODAY)
    assert days[0] == date(2026, 10, 20) and days[-1] == date(2026, 11, 18) and len(days) == 30


def test_a_dataset_with_no_gap_is_left_out_and_holes_are_oldest_first():
    days = set(read_days.window_days(TODAY))
    covered = {
        "shop_overview": days,
        "item_performance": days - {date(2026, 11, 18), date(2026, 10, 25)},
    }
    out = read_days.missing_by_dataset(
        covered, TODAY, ("shop_overview", "item_performance", "order_lines")
    )
    assert "shop_overview" not in out
    assert out["item_performance"]["missing"] == ["2026-10-25", "2026-11-18"]
    assert len(out["order_lines"]["missing"]) == 30


def test_vietnam_today_rolls_over_at_17_utc():
    assert read_days.vietnam_today(datetime(2026, 11, 18, 16, 59, tzinfo=UTC)) == date(2026, 11, 18)
    assert read_days.vietnam_today(datetime(2026, 11, 18, 17, 0, tzinfo=UTC)) == date(2026, 11, 19)


def _post(shop_id, dataset, start, end, source="extension"):
    return IngestRawPayload(
        id=uuid.uuid4(),
        shop_id=shop_id,
        platform="shopee",
        dataset=dataset,
        source=source,
        source_version="0.3.29",
        captured_at=datetime(2026, 11, 19, 1, 0),
        received_at=datetime(2026, 11, 19, 1, 0),
        period_start=start,
        period_end=end,
        granularity="day",
        order_type="none",
        content_hash=uuid.uuid4().hex,
        row_count=0,
        payload={},
    )


def _metric(shop_id, day, segment, dataset="traffic_overview", stream="product_card"):
    return PlatformDailyMetric(
        id=uuid.uuid4(),
        shop_id=shop_id,
        platform="shopee",
        dataset=dataset,
        day=day,
        stream=stream,
        segment=segment,
        order_type="confirmed",
        clicks=Decimal(1),
        source="extension",
        source_rank=3,
        source_version="0.3.29",
        confidence="high",
        captured_at=datetime(2026, 11, 19, 1, 0),
        updated_at=datetime(2026, 11, 19, 1, 0),
    )


async def test_the_route_lists_days_with_no_extension_post_and_traffic_without_sub_sources(
    session, monkeypatch
):
    monkeypatch.setattr(read_days, "vietnam_today", lambda now=None: TODAY)
    user, shop = await _shopee_tenant(session)
    app, code = await _paired_client(session, shop, user)
    d = date
    session.add_all(
        [
            _post(shop.id, "shop_overview", d(2026, 10, 20), d(2026, 11, 18)),
            _post(shop.id, "item_performance", d(2026, 10, 25), d(2026, 11, 17)),
            _post(shop.id, "order_lines", d(2026, 11, 1), d(2026, 11, 18), source="file"),
            _metric(shop.id, d(2026, 11, 18), "all"),
            _metric(shop.id, d(2026, 11, 17), "all"),
            _metric(shop.id, d(2026, 11, 17), "shop_page"),
        ]
    )
    await session.commit()
    async with client_for(app) as ext:
        assert (await ext.get("/v1/connector/shopee/read-days")).status_code == 401
        paired = await ext.post("/v1/ingest/pair", json={"code": code, "platform": "shopee"})
        auth = {"Authorization": f"Bearer {paired.json()['token']}"}
        res = await ext.get("/v1/connector/shopee/read-days", headers=auth)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["window_days"] == 30 and body["as_of"] == "2026-11-19"
    sets = body["datasets"]
    assert "shop_overview" not in sets
    assert sets["item_performance"]["missing"][0] == "2026-10-20"
    assert sets["item_performance"]["missing"][-1] == "2026-11-18"
    assert len(sets["order_lines"]["missing"]) == 30  # a file import is not a Connector read
    assert "2026-11-18" in sets["traffic_overview"]["missing"]  # totals only
    assert "2026-11-17" not in sets["traffic_overview"]["missing"]


async def test_flash_sale_days_are_judged_by_their_own_stored_row_not_by_other_promotion_posts(
    session, monkeypatch
):
    """F6.4: promotion_daily posts of other types do not cover a flash sale day; a stored
    Flash Sale row (an empty day is a zero row) does."""
    monkeypatch.setattr(read_days, "vietnam_today", lambda now=None: TODAY)
    user, shop = await _shopee_tenant(session)
    app, code = await _paired_client(session, shop, user)
    d = date
    session.add_all(
        [
            _post(shop.id, "promotion_daily", d(2026, 10, 20), d(2026, 11, 18)),
            _metric(shop.id, d(2026, 11, 17), "flash_sale", "promotion_daily", "promo"),
            _metric(shop.id, d(2026, 11, 16), "discount", "promotion_daily", "promo"),
        ]
    )
    await session.commit()
    async with client_for(app) as ext:
        paired = await ext.post("/v1/ingest/pair", json={"code": code, "platform": "shopee"})
        auth = {"Authorization": f"Bearer {paired.json()['token']}"}
        res = await ext.get("/v1/connector/shopee/read-days", headers=auth)
    sets = res.json()["datasets"]
    assert "promotion_daily" not in sets  # every day has a promotion post
    assert "2026-11-17" not in sets["flash_sale"]["missing"]
    assert (
        "2026-11-16" in sets["flash_sale"]["missing"]
    )  # another promotion type is not a flash read
    assert len(sets["flash_sale"]["missing"]) == 29


def test_progress_is_the_newest_day_held_and_the_day_before_the_oldest_hole():
    """C2: Ops shows the newest day Juli holds and, while the Connector has a hole, "Đang đọc
    đến dd/mm" = the day before its oldest hole (holes are read oldest first)."""
    days = read_days.window_days(TODAY)
    full = set(days)
    out = read_days.progress_of(
        {"shop_overview": full, "order_income": set(days[:12]), "order_lines": full},
        {"shop_overview": full, "order_income": set(), "order_lines": full - {days[20]}},
        TODAY,
    )
    assert out["shop_overview"] == {"held_through": "2026-11-18", "reading_through": None}
    # a file import holds days the Connector has not read itself: it still reads them
    assert out["order_income"] == {"held_through": "2026-10-31", "reading_through": "2026-10-19"}
    assert out["order_lines"] == {"held_through": "2026-11-18", "reading_through": "2026-11-08"}
    assert out["ads_campaign_daily"] == {"held_through": None, "reading_through": "2026-10-19"}


async def test_the_seller_status_carries_held_and_reading_days_per_daily_dataset(
    session, monkeypatch
):
    from tests.support.api import authenticate, build_app

    monkeypatch.setattr(read_days, "vietnam_today", lambda now=None: TODAY)
    user, shop = await _shopee_tenant(session)
    d = date
    session.add_all(
        [
            _post(shop.id, "shop_overview", d(2026, 10, 20), d(2026, 11, 18)),
            _post(shop.id, "order_income", d(2026, 10, 20), d(2026, 10, 31), source="file"),
        ]
    )
    await session.commit()
    app = build_app(session)
    authenticate(app, user=user, shop=shop)
    async with client_for(app) as seller:
        res = await seller.get("/v1/ingest/shop-status")
    assert res.status_code == 200, res.text
    entries = {e["dataset"]: e for e in res.json()["datasets"]}
    assert entries["shop_overview"]["held_through"] == "2026-11-18"
    assert entries["shop_overview"]["reading_through"] is None
    assert entries["order_income"]["held_through"] == "2026-10-31"
    assert entries["order_income"]["reading_through"] == "2026-10-19"
