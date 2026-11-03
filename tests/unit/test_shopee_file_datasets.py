"""ADR-117 step 2: the Seller Centre file datasets through the ingest gateway, SQLite.

- level-2 sources land as ``segment`` beside the L1 total (``all``); an unknown label is
  refused, never filed under ``other``;
- ``impressions`` follows the stream (views on live / video, ad impressions on ads); ads
  rows keep the post's order type like every stream;
- every row records ``mapper_version``;
- the new daily datasets (shop / product overview, promotion types) map onto the KPI
  columns;
- ``granularity: "period"`` datasets land in ``platform_period_metrics`` (two periods
  starting the same day do not collide), describe their items in ``platform_items`` (the
  seen range widens), and an API post replaces a file post on the same key;
- product flags and promotions get their own tables; two programs sharing a name and run
  times are told apart by ``ordinal``.

Values are synthetic; only Seller Centre labels and field names come from the exports.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select

from juli_backend.models.ingest import PlatformDailyMetric
from juli_backend.models.platform_data import (
    PlatformItem,
    PlatformPeriodMetric,
    PlatformProductFlag,
    PlatformPromotion,
)
from juli_backend.services import ingest as svc
from juli_backend.services.ingest import mapping
from juli_backend.services.ingest.rate_limit import InMemoryRateGate, set_ingest_rate_gate
from juli_backend.services.ingest.schemas import SHOPEE_L2_SOURCES
from tests.support.builders import make_tenant
from tests.support.consent import grant_service_consent

NOW = datetime(2026, 10, 30, 3, 0)  # naive UTC
DAY = date(2026, 10, 1)
OCTOBER = {"start": "2026-10-01", "end": "2026-10-28", "granularity": "period"}


@pytest.fixture(autouse=True)
def generous_gate():
    set_ingest_rate_gate(InMemoryRateGate())
    yield
    set_ingest_rate_gate(None)


def _body(rows: list[dict[str, Any]], **over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "source": "file",
        "source_version": "seller-centre-xlsx-1",
        "captured_at": "2026-10-29T09:30:00+07:00",
        "period": {"start": DAY.isoformat(), "end": DAY.isoformat(), "granularity": "day"},
        "order_type": "confirmed",
        "rows": rows,
    }
    body.update(over)
    return body


async def _shop(session):
    _, shop = await make_tenant(session, platform="shopee", tiktok_shop_id=None)
    await grant_service_consent(session, shop.id)
    return shop


async def _ingest(session, shop, dataset: str, body: dict[str, Any]):
    return await svc.ingest(
        session,
        shop_id=shop.id,
        platform="shopee",
        dataset=dataset,
        body=svc.IngestBody.model_validate(body),
        token_id=None,
        now=NOW,
    )


async def _rows(session, model, shop):
    stmt = select(model).where(model.shop_id == shop.id).execution_options(populate_existing=True)
    return list((await session.execute(stmt)).scalars())


# -- traffic_overview: L2 segments, impressions per stream ------------------------------


async def test_a_level_two_source_is_a_segment_beside_the_level_one_total(session):
    shop = await _shop(session)
    card = "psd_label_product_card"
    rows = [
        {"date": "2026-10-01", "source": card, "product_impressions": 1000, "product_clicks": 30},
        {"date": "2026-10-01", "source": card, "sub_source": "Cửa hàng", "product_clicks": 4},
        {"date": "2026-10-01", "source": card, "sub_source": "Tìm kiếm", "product_clicks": 20},
    ]
    await _ingest(session, shop, "traffic_overview", _body(rows))
    stored = {m.segment: m for m in await _rows(session, PlatformDailyMetric, shop)}
    assert set(stored) == {"all", "shop_page", "search"}
    assert {m.stream for m in stored.values()} == {"product_card"}
    assert stored["shop_page"].clicks == Decimal("4")
    assert {m.mapper_version for m in stored.values()} == {mapping.MAPPER_VERSION}


async def test_an_unknown_level_two_label_is_refused(session):
    shop = await _shop(session)
    row = {"date": "2026-10-01", "source": "psd_label_affiliate", "sub_source": "Cửa hàng"}
    with pytest.raises(svc.IngestRejected) as refused:
        await _ingest(session, shop, "traffic_overview", _body([row]))
    assert refused.value.code == "invalid_rows"
    assert await _rows(session, PlatformDailyMetric, shop) == []


def test_every_level_two_code_fits_the_segment_column():
    codes = {code for labels in SHOPEE_L2_SOURCES.values() for code in labels.values()}
    assert all(len(code) <= 16 for code in codes)
    assert SHOPEE_L2_SOURCES["psd_label_product_card"]["Cửa hàng"] == "shop_page"


async def test_live_impressions_are_views_and_ads_rows_keep_the_post_order_type(session):
    shop = await _shop(session)
    rows = [
        {"date": "2026-10-01", "source": "psd_label_seller_live", "live_views": 400},
        {
            "date": "2026-10-01",
            "source": "psd_label_shopee_ads",
            "sub_source": "Quảng cáo cửa hàng",
            "ads_impressions": 2500,
            "sales": 600000,
            "ads_expense": 120000,
        },
    ]
    await _ingest(session, shop, "traffic_overview", _body(rows))
    stored = {m.stream: m for m in await _rows(session, PlatformDailyMetric, shop)}
    assert stored["seller_live"].impressions == Decimal("400")
    ads = stored["ads"]
    assert (ads.segment, ads.impressions) == ("ads_shop", Decimal("2500"))
    assert ads.order_type == "confirmed" and "ads_attribution" not in ads.extra
    assert ads.extra["ads_expense"] == 120000


# -- new daily datasets ------------------------------------------------------------------


async def test_shop_and_product_overview_map_onto_the_total_stream(session):
    shop = await _shop(session)
    shop_row = {
        "date": "2026-10-01",
        "sales": 500000,
        "orders": 3,
        "product_clicks": 40,
        "visitors": 45,
        "buyers": 3,
        "cancelled_orders": 1,
    }
    product_row = {
        "date": "2026-10-01",
        "product_visitors": 19,
        "product_page_views": 57,
        "atc_visitors": 7,
        "bounce_rate": 0.1053,
    }
    await _ingest(session, shop, "shop_overview", _body([shop_row]))
    await _ingest(session, shop, "product_overview", _body([product_row]))
    stored = {m.dataset: m for m in await _rows(session, PlatformDailyMetric, shop)}
    overview = stored["shop_overview"]
    assert (overview.stream, overview.gmv, overview.clicks) == (
        "total",
        Decimal("500000"),
        Decimal("40"),
    )
    assert overview.extra["cancelled_orders"] == 1
    funnel = stored["product_overview"]
    assert (funnel.visitors, funnel.page_views, funnel.add_to_cart) == (
        Decimal("19"),
        Decimal("57"),
        Decimal("7"),
    )


async def test_promotion_types_are_segments_of_the_promo_stream(session):
    shop = await _shop(session)
    rows = [
        {"date": "2026-10-01", "promo_type": "Tất cả", "sales": 800000, "orders": 6},
        {"date": "2026-10-01", "promo_type": "Combo Khuyến Mãi", "sales": 0, "orders": 0},
    ]
    await _ingest(session, shop, "promotion_daily", _body(rows))
    stored = {m.segment: m for m in await _rows(session, PlatformDailyMetric, shop)}
    assert set(stored) == {"all", "bundle"}
    assert stored["all"].stream == "promo"


# -- period datasets ---------------------------------------------------------------------


def _product(item_id: str, variation_id: str = "", **over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "item_id": item_id,
        "variation_id": variation_id,
        "item_name": "Synthetic gloves",
        "item_status": "Đang hoạt động",
        "sales": 1000000,
        "orders": 7,
        "units": 8,
        "product_impressions": 2000,
        "product_clicks": 80,
    }
    row.update(over)
    return row


async def test_a_day_dataset_refuses_a_period_body_and_back(session):
    shop = await _shop(session)
    with pytest.raises(svc.IngestRejected) as refused:
        await _ingest(session, shop, "product_period", _body([_product("1001")]))
    assert refused.value.code == "granularity_mismatch"
    row = {"date": "2026-10-01", "sales": 1}
    with pytest.raises(svc.IngestRejected) as refused:
        await _ingest(session, shop, "shop_overview", _body([row], period=OCTOBER))
    assert refused.value.code == "granularity_mismatch"


async def test_product_period_rows_land_in_the_period_table_and_describe_items(session):
    shop = await _shop(session)
    rows = [
        _product("1001"),
        _product("1001", "2001", variation_name="Combo 3", seller_sku="G1", orders=4),
    ]
    await _ingest(session, shop, "product_period", _body(rows, period=OCTOBER))
    stored = await _rows(session, PlatformPeriodMetric, shop)
    assert {(m.item_id, m.variation_id) for m in stored} == {("1001", ""), ("1001", "2001")}
    assert {(m.period_start, m.period_end) for m in stored} == {
        (date(2026, 10, 1), date(2026, 10, 28))
    }
    assert {m.mapper_version for m in stored} == {mapping.MAPPER_VERSION}
    assert not any("item_name" in m.extra for m in stored)
    items = {i.variation_id: i for i in await _rows(session, PlatformItem, shop)}
    assert items[""].name == "Synthetic gloves"
    assert (items["2001"].variation_name, items["2001"].seller_sku) == ("Combo 3", "G1")


async def test_two_periods_starting_the_same_day_do_not_collide_and_items_widen(session):
    shop = await _shop(session)
    week = {"start": "2026-10-01", "end": "2026-10-07", "granularity": "period"}
    await _ingest(session, shop, "product_period", _body([_product("1001")], period=OCTOBER))
    await _ingest(session, shop, "product_period", _body([_product("1001")], period=week))
    september = {"start": "2026-09-01", "end": "2026-09-30", "granularity": "period"}
    await _ingest(session, shop, "product_period", _body([_product("1001")], period=september))
    assert len(await _rows(session, PlatformPeriodMetric, shop)) == 3
    (item,) = await _rows(session, PlatformItem, shop)
    assert (item.first_seen_on, item.last_seen_on) == (date(2026, 9, 1), date(2026, 10, 28))


async def test_an_api_post_replaces_a_file_post_on_the_same_period_key(session):
    shop = await _shop(session)
    await _ingest(session, shop, "product_period", _body([_product("1001")], period=OCTOBER))
    await _ingest(
        session,
        shop,
        "product_period",
        _body([_product("1001", orders=9)], period=OCTOBER, source="api"),
    )
    (row,) = await _rows(session, PlatformPeriodMetric, shop)
    assert (row.source, row.orders) == ("api", Decimal("9"))
    # A later file post does not overwrite the API row.
    await _ingest(
        session,
        shop,
        "product_period",
        _body([_product("1001", orders=1)], period=OCTOBER, source_version="file-2"),
    )
    (row,) = await _rows(session, PlatformPeriodMetric, shop)
    assert (row.source, row.orders) == ("api", Decimal("9"))


async def test_source_period_totals_keep_the_segment_and_item_rows_skip_extra_names(session):
    shop = await _shop(session)
    totals = [
        {"source": "psd_label_product_card", "product_impressions": 50000},
        {"source": "psd_label_product_card", "sub_source": "Cửa hàng", "product_clicks": 150},
    ]
    await _ingest(session, shop, "traffic_overview_period", _body(totals, period=OCTOBER))
    by_item = [
        {
            "item_id": "1001",
            "item_name": "Synthetic gloves",
            "source": "psd_label_seller_video",
            "video_views": 19,
        }
    ]
    await _ingest(session, shop, "item_by_source_period", _body(by_item, period=OCTOBER))
    stored = {(m.dataset, m.segment): m for m in await _rows(session, PlatformPeriodMetric, shop)}
    assert set(stored) == {
        ("traffic_overview_period", "all"),
        ("traffic_overview_period", "shop_page"),
        ("item_by_source_period", "all"),
    }
    video = stored[("item_by_source_period", "all")]
    assert (video.stream, video.impressions) == ("seller_video", Decimal("19"))
    assert "item_name" not in video.extra
    (item,) = await _rows(session, PlatformItem, shop)
    assert item.name == "Synthetic gloves"


# -- flags and promotions ----------------------------------------------------------------


async def test_product_flags_get_their_own_table(session):
    shop = await _shop(session)
    rows = [
        {"item_id": "1001", "flag": "ads_optimize"},
        {"item_id": "1002", "flag": "ads_optimize"},
    ]
    body = _body(rows, period=OCTOBER, order_type=None)
    await _ingest(session, shop, "product_flags", body)
    flags = await _rows(session, PlatformProductFlag, shop)
    assert {(f.item_id, f.flag) for f in flags} == {
        ("1001", "ads_optimize"),
        ("1002", "ads_optimize"),
    }
    assert {f.mapper_version for f in flags} == {mapping.MAPPER_VERSION}


def _program(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "program_name": "Giảm giá trực tiếp sản phẩm",
        "promo_type": "Chương Trình Khuyến Mãi",
        "starts_at": "2026-06-15T10:30:00",
        "ends_at": "2026-12-12T09:30:00",
        "status": "Đang diễn ra",
        "sales": 900000,
        "orders": 6,
    }
    row.update(over)
    return row


async def test_twin_programs_are_told_apart_by_ordinal(session):
    shop = await _shop(session)
    rows = [_program(), _program(ordinal=1, sales=99000, orders=1)]
    await _ingest(session, shop, "promotions", _body(rows, period=OCTOBER))
    stored = sorted(await _rows(session, PlatformPromotion, shop), key=lambda p: p.ordinal)
    assert [(p.ordinal, p.gmv) for p in stored] == [(0, Decimal("900000")), (1, Decimal("99000"))]
    assert {p.promo_type for p in stored} == {"discount"}
    assert {(p.period_start, p.period_end) for p in stored} == {
        (date(2026, 10, 1), date(2026, 10, 28))
    }


async def test_a_duplicate_program_key_in_one_post_is_refused(session):
    shop = await _shop(session)
    with pytest.raises(svc.IngestRejected) as refused:
        await _ingest(session, shop, "promotions", _body([_program(), _program()], period=OCTOBER))
    assert refused.value.code == "invalid_rows"
    assert await _rows(session, PlatformPromotion, shop) == []


async def test_a_repeated_file_post_changes_nothing(session):
    shop = await _shop(session)
    body = _body([_product("1001")], period=OCTOBER)
    first = await _ingest(session, shop, "product_period", body)
    again = await _ingest(session, shop, "product_period", body)
    assert (first.duplicate, again.duplicate) == (False, True)
    assert again.raw_payload_id == first.raw_payload_id


# -- ads campaigns (a three-month period dataset) --------------------------------------------

QUARTER = {"start": "2026-08-01", "end": "2026-10-28", "granularity": "period"}


def _ad(name: str = "Quảng cáo A", **over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "campaign_name": name,
        "running": True,
        "ads_impressions": 10000,
        "ad_clicks": 250,
        "ctr": 0.025,
        "conversions": 12,
        "units_sold": 15,
        "sales": 1200000,
        "ads_expense": 300000,
        "ads_roas": 4,
    }
    row.update(over)
    return row


async def test_ad_campaign_totals_land_in_the_period_table_as_ads_overlay_rows(session):
    shop = await _shop(session)
    rows = [_ad(), _ad("Quảng cáo B", item_id="1001"), _ad("Quảng cáo A", item_id="1001")]
    body = _body(rows, period=QUARTER, order_type="placed")
    await _ingest(session, shop, "ads_campaign_period", body)
    stored = await _rows(session, PlatformPeriodMetric, shop)
    assert len(stored) == 3
    assert {(m.stream, m.order_type, m.period_start, m.period_end) for m in stored} == {
        ("ads", "placed", date(2026, 8, 1), date(2026, 10, 28))
    }
    assert len({(m.item_id, m.segment) for m in stored}) == 3
    shop_level = next(m for m in stored if m.item_id == "" and m.platform_source == "Quảng cáo A")
    assert (shop_level.impressions, shop_level.clicks, shop_level.orders) == (10000, 250, 12)
    assert (shop_level.gmv, shop_level.units) == (Decimal("1200000"), Decimal("15"))
    assert shop_level.extra == {"ads_expense": 300000, "ads_roas": 4, "running": True}
    assert await _rows(session, PlatformDailyMetric, shop) == []


async def test_two_windows_of_the_same_campaign_do_not_collide(session):
    shop = await _shop(session)
    overlap = {"start": "2026-09-01", "end": "2026-10-29", "granularity": "period"}
    for window in (QUARTER, overlap):
        body = _body([_ad()], period=window, order_type="placed")
        await _ingest(session, shop, "ads_campaign_period", body)
    assert len(await _rows(session, PlatformPeriodMetric, shop)) == 2


async def test_a_repeated_ads_file_post_is_a_duplicate(session):
    shop = await _shop(session)
    body = _body([_ad()], period=QUARTER, order_type="placed")
    first = await _ingest(session, shop, "ads_campaign_period", body)
    again = await _ingest(session, shop, "ads_campaign_period", body)
    assert (first.duplicate, again.duplicate) == (False, True)


async def test_only_the_ads_dataset_may_exceed_a_month(session):
    shop = await _shop(session)
    with pytest.raises(svc.IngestRejected) as refused:
        await _ingest(session, shop, "promotions", _body([_program()], period=QUARTER))
    assert refused.value.code == "period_too_long"
    too_long = {"start": "2026-06-01", "end": "2026-10-28", "granularity": "period"}
    with pytest.raises(ValueError, match="longer than"):
        svc.IngestBody.model_validate(_body([_ad()], period=too_long, order_type="placed"))


async def test_flash_sale_and_voucher_programs_are_promotion_rows(session):
    shop = await _shop(session)
    rows = [
        _program(promo_type="Flash Sale", program_name="Flash Sale 12:00-14:00"),
        _program(promo_type="Voucher", program_name="Giảm 5 phần trăm", ends_at=None),
    ]
    await _ingest(session, shop, "promotions", _body(rows, period=OCTOBER))
    stored = await _rows(session, PlatformPromotion, shop)
    assert {p.promo_type for p in stored} == {"flash_sale", "voucher"}
