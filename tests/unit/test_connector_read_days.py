"""F4.2: the Connector's hole list (``GET /v1/connector/shopee/read-days``). Synthetic values."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from juli_backend.models.ingest import IngestRawPayload, PlatformDailyMetric
from juli_backend.models.shopee_connector import ShopeeConnectorState
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
            ShopeeConnectorState(
                shop_id=shop.id,
                reader_blocks=[
                    {"reason": "login", "readers": ["item_traffic"], "section": "phan_tich"},
                    {"reason": "password_recheck", "readers": ["shop_totals"], "section": "pt"},
                ],
            ),
        ]
    )
    await session.commit()
    app = build_app(session)
    authenticate(app, user=user, shop=shop)
    async with client_for(app) as seller:
        res = await seller.get("/v1/ingest/shop-status")
    assert res.status_code == 200, res.text
    entries = {e["dataset"]: e for e in res.json()["datasets"]}
    assert entries["item_traffic_sources"]["blocked"] == "login"  # 1(a): the block, per dataset
    assert entries["shop_overview"]["blocked"] == "password_recheck"
    assert entries["order_lines"]["blocked"] is None
    assert entries["item_traffic_sources"]["reading_through"] == "2026-10-19"
    assert entries["shop_overview"]["held_through"] == "2026-11-18"
    assert entries["shop_overview"]["reading_through"] is None
    assert entries["order_income"]["held_through"] == "2026-10-31"
    assert entries["order_income"]["reading_through"] == "2026-10-19"


async def test_a_day_with_lines_that_name_no_item_is_read_again(session, monkeypatch):
    """C1: the triggered re-read of ``sku:unknown`` lines -- the day goes back on the hole list
    until a read names the items (the order reader then opens each order's detail)."""
    from tests.unit.test_ingest_composed_precedence import T1, T2, _catalogue, _write

    monkeypatch.setattr(read_days, "vietnam_today", lambda now=None: TODAY)
    _, shop = await _shopee_tenant(session)
    await _catalogue(session, shop.id)
    session.add(_post(shop.id, "order_lines", date(2026, 10, 20), date(2026, 11, 18)))
    await session.flush()
    at = datetime(2026, 11, 10, 3, 0)
    await _write(session, shop.id, "extension", 3, T1, sku=None, ordered_at=at)
    covered = await read_days.covered_days(session, shop.id, "shopee", TODAY)
    missing = read_days.missing_by_dataset(covered, TODAY)
    assert missing["order_lines"] == {"missing": ["2026-11-10"]}
    held = await read_days.covered_days(session, shop.id, "shopee", TODAY, extension_only=False)
    assert date(2026, 11, 10) in held["order_lines"]  # still held, only read again
    await _write(session, shop.id, "extension", 3, T2, ordered_at=at)  # the detail read
    covered = await read_days.covered_days(session, shop.id, "shopee", TODAY)
    assert "order_lines" not in read_days.missing_by_dataset(covered, TODAY)


def test_blocks_name_the_datasets_of_their_readers():
    blocks = [
        {"reason": "login", "readers": ["item_traffic", "traffic"], "section": "a"},
        {"reason": "captcha", "readers": ["traffic"], "section": "a"},
        {"reason": 3, "readers": ["orders"]},
    ]
    got = read_days.blocked_by_dataset(
        blocks, {"item_traffic": ("item_traffic_sources",), "traffic": ("traffic_overview",)}
    )
    assert got == {"item_traffic_sources": "login", "traffic_overview": "login"}
    assert read_days.blocked_by_dataset(None, {}) == {}


@pytest.mark.parametrize(
    "dataset",
    [
        "affiliate_content_period",
        "affiliate_partner_period",
        "affiliate_product_period",
        "affiliate_commission_period",
    ],
)
async def test_an_empty_affiliate_day_is_accepted_and_counts_as_read(session, dataset):
    """C3 (Connector 0.3.32): an empty affiliate page day (KOL content, partners, products,
    commissions) is posted with 0 rows; Juli keeps the post, so read-days no longer lists it."""
    from tests.unit.test_shopee_file_datasets import _body, _ingest, _shop

    shop = await _shop(session)
    body = _body(
        [],
        source="extension",
        source_version="0.3.32",
        period={"start": "2026-10-28", "end": "2026-10-28", "granularity": "period"},
        order_type=None,  # the Connector sends none for the affiliate pages
    )
    result = await _ingest(session, shop, dataset, body)
    assert result.rows == 0
    covered = await read_days.covered_days(session, shop.id, "shopee", date(2026, 10, 30))
    assert date(2026, 10, 28) in covered[dataset]


async def test_an_unresolved_item_day_is_not_handed_out_again_but_stays_a_hole_in_c2(
    session, monkeypatch, caplog
):
    """Connector 0.3.32: after 3 page reads that could not name a line, the Connector posts it as
    ``unresolved_item``: the day leaves the re-read hand-out (no budget spent on it daily) but the
    C2 status still shows the day as a hole; the write is logged."""
    from tests.unit.test_ingest_composed_precedence import T1, T2, _catalogue, _write

    monkeypatch.setattr(read_days, "vietnam_today", lambda now=None: TODAY)
    _, shop = await _shopee_tenant(session)
    await _catalogue(session, shop.id)
    session.add(_post(shop.id, "order_lines", date(2026, 10, 20), date(2026, 11, 18)))
    await session.flush()
    at = datetime(2026, 11, 10, 3, 0)
    await _write(session, shop.id, "extension", 3, T1, sku=None, ordered_at=at)
    with caplog.at_level("INFO"):
        await _write(session, shop.id, "extension", 3, T2, sku="unresolved_item", ordered_at=at)
    assert any(r.getMessage() == "order_line_unresolved_item" for r in caplog.records)
    covered = await read_days.covered_days(session, shop.id, "shopee", TODAY)
    assert "order_lines" not in read_days.missing_by_dataset(covered, TODAY)
    progress = await read_days.progress(session, shop.id, "shopee")
    assert progress["order_lines"]["reading_through"] == "2026-11-09"


async def test_s1_the_order_days_an_older_connector_read_are_handed_out_once_from_0_3_36(
    session, monkeypatch
):
    """batch-1124-a S1, owner decision #48, moved to 0.3.36 by batch-1124-b CONN (owner Q4: the
    combo discount from the order page's list prices, combo lines with their SKUs): once the
    shop's Connector reports 0.3.36, every order day of the window read only by an older
    Connector (0.3.35 included) forms its own hole set, once: the re-read's own post closes
    each day, a later heartbeat does not reopen it, and a day with no order is never handed out."""
    from tests.unit.test_ingest_composed_precedence import T1, T2, _write

    monkeypatch.setattr(read_days, "vietnam_today", lambda now=None: TODAY)
    _, shop = await _shopee_tenant(session)
    old = _post(shop.id, "order_lines", date(2026, 10, 20), date(2026, 11, 18))
    old.source_version = "0.3.35"
    session.add(old)
    await session.flush()
    for day, captured in ((5, T1), (10, T2)):
        await _write(
            session,
            shop.id,
            "extension",
            3,
            captured,
            ordered_at=datetime(2026, 11, day, 3, 0),
            order_ref=f"{day:032x}",
        )

    async def backfill() -> list[str] | None:
        datasets = (await read_days.read_days(session, shop.id, "shopee"))["datasets"]
        assert isinstance(datasets, dict)
        entry = datasets.get(read_days.ORDER_LINES_BACKFILL)
        return entry["missing"] if entry else None

    assert await backfill() is None  # no Connector state yet
    state = ShopeeConnectorState(shop_id=shop.id, connector_version="0.3.35")
    session.add(state)
    await session.flush()
    assert await backfill() is None  # an older Connector: nothing to re-read
    state.connector_version = "0.3.36"
    await session.flush()
    assert await backfill() == ["2026-11-05", "2026-11-10"]  # days with lines only, oldest first
    new = _post(shop.id, "order_lines", date(2026, 11, 8), date(2026, 11, 18))
    new.source_version = "0.3.36"
    session.add(new)
    await session.flush()
    assert await backfill() == ["2026-11-05"]  # the re-read closed its day
    newer = _post(shop.id, "order_lines", date(2026, 11, 1), date(2026, 11, 6))
    newer.source_version = "0.3.37"
    session.add(newer)
    state.connector_version = "0.3.37"  # a later heartbeat / upgrade
    await session.flush()
    assert await backfill() is None  # done: never handed out again
    covered = await read_days.covered_days(session, shop.id, "shopee", TODAY)
    assert "order_lines" not in read_days.missing_by_dataset(covered, TODAY)  # C2 unchanged
