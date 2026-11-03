"""The Juli Connector's page readers (ADR-120 d.14) through the ingest gateway, SQLite.

- ``item_catalog`` -> ``platform_items`` (the identity half of the product list);
- ``ads_campaign_daily`` -> ``platform_daily_metrics`` (stream ``ads``, one row per campaign
  and finished day, plus the day's shop-level ROAS-target row);
- ``voucher_settings`` -> ``platform_promotions`` (``promo_type`` voucher, twins by voucher id);
- ``item_snapshot`` -> ``platform_item_snapshots`` (a row only when a tracked field changed);
  ``shop_health_daily`` -> ``shop_health_daily`` (append-only; migration 113).

Every value is synthetic.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from juli_backend.models.ingest import PlatformDailyMetric
from juli_backend.models.platform_data import PlatformItem, PlatformPromotion
from juli_backend.models.shopee_profit import PlatformItemSnapshot, ShopHealthDaily
from juli_backend.services.ingest.gateway import IngestRejected, validate_rows
from juli_backend.services.ingest.mapping import DATASETS, dataset_spec, normalize_rows
from juli_backend.services.ingest.rate_limit import InMemoryRateGate, set_ingest_rate_gate
from juli_backend.services.ingest.schemas import IngestBody
from juli_backend.services.privacy.payload_allowlist import (
    FORBIDDEN_FRAGMENT_EXCEPTIONS,
    FORBIDDEN_KEY_FRAGMENTS,
    allowlist_payload,
    ingest_endpoint,
)
from tests.unit.test_shopee_file_datasets import NOW, _ingest, _rows, _shop


@pytest.fixture(autouse=True)
def generous_gate():
    set_ingest_rate_gate(InMemoryRateGate())
    yield
    set_ingest_rate_gate(None)


def _post(rows: list[dict[str, Any]], day: str, granularity: str, **over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "source": "extension",
        "source_version": "0.3.0",
        "captured_at": "2026-10-30T09:30:00+07:00",
        "period": {"start": day, "end": day, "granularity": granularity},
        "rows": rows,
    }
    body.update(over)
    return body


def _ad(campaign_id: str | None, **fields: Any) -> dict[str, Any]:
    return {"date": "2026-10-29", "campaign_id": campaign_id, **fields}


def _voucher(voucher_id: str, name: str, **fields: Any) -> dict[str, Any]:
    return {
        "voucher_id": voucher_id,
        "program_name": name,
        "starts_at": "2026-10-01T00:00:00",
        "ends_at": "2026-10-31T23:59:59",
        **fields,
    }


# -- item_catalog -> platform_items ------------------------------------------------------


async def test_item_catalog_describes_items_and_variations(session):
    shop = await _shop(session)
    rows = [
        {"item_id": "1001", "item_name": "Sản phẩm mẫu A", "seller_sku": "SKU-A", "status": "1"},
        {"item_id": "1001", "variation_id": "5001", "variation_name": "Hồng", "seller_sku": "A-P"},
    ]
    result = await _ingest(session, shop, "item_catalog", _post(rows, "2026-10-29", "period"))
    assert result.rows == 2
    items = {(i.item_id, i.variation_id): i for i in await _rows(session, PlatformItem, shop)}
    assert set(items) == {("1001", ""), ("1001", "5001")}
    assert items[("1001", "")].name == "Sản phẩm mẫu A"
    assert items[("1001", "5001")].variation_name == "Hồng"
    assert items[("1001", "5001")].source == "extension"
    # a later snapshot without the status keeps the one already known
    await _ingest(
        session,
        shop,
        "item_catalog",
        _post([{"item_id": "1001", "item_name": "Tên mới"}], "2026-10-30", "period"),
    )
    items = {(i.item_id, i.variation_id): i for i in await _rows(session, PlatformItem, shop)}
    assert items[("1001", "")].name == "Tên mới"
    assert items[("1001", "")].status == "1"
    assert items[("1001", "")].last_seen_on == date(2026, 10, 30)


async def test_item_catalog_refuses_a_duplicate_key_and_an_order_type(session):
    shop = await _shop(session)
    rows = [{"item_id": "1"}, {"item_id": "1"}]
    with pytest.raises(IngestRejected):
        await _ingest(session, shop, "item_catalog", _post(rows, "2026-10-29", "period"))
    with pytest.raises(IngestRejected) as err:
        await _ingest(
            session,
            shop,
            "item_catalog",
            _post([{"item_id": "1"}], "2026-10-29", "period", order_type="placed"),
        )
    assert err.value.code == "order_type_not_allowed"


# -- ads_campaign_daily -> platform_daily_metrics ----------------------------------------


async def test_ads_daily_rows_are_ads_overlay_rows_per_campaign_and_day(session):
    shop = await _shop(session)
    rows = [
        _ad(
            "7001",
            campaign_name="Chiến dịch mẫu",
            ad_type="product",
            state="ongoing",
            daily_budget=200000,
            roi_two_target=5.5,
            impression=1000,
            click=40,
            ctr=0.04,
            cost=50000,
            broad_gmv=400000,
            broad_order=4,
            broad_roi=8,
            direct_gmv=300000,
            direct_order=3,
            atc=9,
            voucher_amount=1000,
        ),
        _ad("7002", campaign_name="Chiến dịch hai", impression=10),
        _ad(None, roi_target=6, roi_target_cold_start=False),
    ]
    body = _post(rows, "2026-10-29", "day", order_type="placed")
    result = await _ingest(session, shop, "ads_campaign_daily", body)
    assert result.rows == 3
    stored = await _rows(session, PlatformDailyMetric, shop)
    assert {m.dataset for m in stored} == {"ads_campaign_daily"}
    assert {m.stream for m in stored} == {"ads"}
    by_source = {m.platform_source: m for m in stored}
    main = by_source["Chiến dịch mẫu"]
    assert (main.impressions, main.clicks, main.orders, main.gmv, main.add_to_cart) == (
        Decimal("1000"),
        Decimal("40"),
        Decimal("4"),
        Decimal("400000"),
        Decimal("9"),
    )
    assert main.extra["cost"] == 50000
    assert main.extra["direct_gmv"] == 300000
    assert main.extra["state"] == "ongoing"
    assert main.segment != "all" and len(main.segment) == 13
    assert by_source["ads_roas_target"].segment == "all"
    assert by_source["ads_roas_target"].extra["roi_target"] == 6
    assert len({m.segment for m in stored}) == 3
    # the same campaign on the next day is another row, not a replacement
    next_day = _ad("7001", impression=5)
    next_day["date"] = "2026-10-30"
    await _ingest(
        session,
        shop,
        "ads_campaign_daily",
        _post([next_day], "2026-10-30", "day", order_type="placed"),
    )
    assert len(await _rows(session, PlatformDailyMetric, shop)) == 4


async def test_ads_daily_needs_an_order_type_and_a_unique_campaign_per_day(session):
    shop = await _shop(session)
    with pytest.raises(IngestRejected) as err:
        await _ingest(session, shop, "ads_campaign_daily", _post([_ad("1")], "2026-10-29", "day"))
    assert err.value.code == "order_type_required"
    twin = _post([_ad("1"), _ad("1")], "2026-10-29", "day", order_type="placed")
    with pytest.raises(IngestRejected):
        await _ingest(session, shop, "ads_campaign_daily", twin)


def test_ads_daily_refuses_a_non_numeric_campaign_id_and_unknown_fields():
    model = DATASETS[("shopee", "ads_campaign_daily")].row_model
    with pytest.raises(ValidationError):
        model.model_validate(_ad("abc"))
    with pytest.raises(ValidationError):
        model.model_validate({**_ad("1"), "buyer_phone": "0"})
    with pytest.raises(ValidationError):
        model.model_validate({**_ad("1"), "cost": -1})


# -- voucher_settings -> platform_promotions ---------------------------------------------


async def test_voucher_settings_land_as_voucher_promotions_with_twins_told_apart(session):
    shop = await _shop(session)
    rows = [
        _voucher(
            "9002",
            "Giảm 15k",
            voucher_code="ABC15",
            status="ongoing",
            discount_amount=15000,
            min_spend=200000,
            usage_limit=100,
            current_usage=12,
            distributed_count=40,
            use_type=1,
            reward_type=1,
            is_seller_absorbed=True,
            item_count=0,
            item_scope="shop",
        ),
        _voucher("9001", "Giảm 15k", discount_percent=10, max_value=30000),
    ]
    await _ingest(session, shop, "voucher_settings", _post(rows, "2026-10-29", "period"))
    stored = await _rows(session, PlatformPromotion, shop)
    assert {p.promo_type for p in stored} == {"voucher"}
    by_id = {p.extra["voucher_id"]: p for p in stored}
    assert by_id[9001].ordinal == 0 and by_id[9002].ordinal == 1
    full = by_id[9002]
    assert full.status == "ongoing"
    assert full.order_type == "none"
    assert (full.period_start, full.period_end) == (date(2026, 10, 29), date(2026, 10, 29))
    assert full.extra["discount_amount"] == 15000
    assert full.extra["current_usage"] == 12
    assert full.extra["is_seller_absorbed"] is True
    assert "voucher_code" not in full.extra and "item_scope" not in full.extra
    assert by_id[9001].extra["discount_percent"] == 10
    # the code is not lost: the raw copy keeps it
    assert "voucher_code" in DATASETS[("shopee", "voucher_settings")].row_model.model_fields


async def test_a_repeated_voucher_snapshot_is_a_duplicate_and_a_new_day_is_a_new_row(session):
    shop = await _shop(session)
    rows = [_voucher("9001", "Giảm 10%", current_usage=1)]
    first = await _ingest(session, shop, "voucher_settings", _post(rows, "2026-10-29", "period"))
    again = await _ingest(session, shop, "voucher_settings", _post(rows, "2026-10-29", "period"))
    assert again.duplicate and again.content_hash == first.content_hash
    rows[0]["current_usage"] = 3
    await _ingest(session, shop, "voucher_settings", _post(rows, "2026-10-30", "period"))
    assert len(await _rows(session, PlatformPromotion, shop)) == 2


def test_voucher_settings_refuse_a_percent_over_100_and_a_duplicate_voucher():
    spec = dataset_spec("shopee", "voucher_settings")
    assert spec is not None
    over = IngestBody.model_validate(
        _post([_voucher("1", "x", discount_percent=150)], "2026-10-29", "period")
    )
    with pytest.raises(IngestRejected):
        validate_rows(spec, over, NOW)
    dup = IngestBody.model_validate(
        _post([_voucher("1", "x"), _voucher("1", "y")], "2026-10-29", "period")
    )
    with pytest.raises(IngestRejected):
        validate_rows(spec, dup, NOW)


# -- the dataset specs --------------------------------------------------------------------


def test_the_new_datasets_are_registered_with_their_targets():
    expected = {
        "ads_campaign_daily": ("daily", "day", True),
        "voucher_settings": ("promotions", "period", False),
        "item_catalog": ("items", "period", False),
    }
    for name, (writes, granularity, order_type) in expected.items():
        spec = dataset_spec("shopee", name)
        assert spec is not None, name
        assert (spec.writes, spec.granularity, spec.has_order_type) == (
            writes,
            granularity,
            order_type,
        )


def test_normalizing_an_ads_row_is_pure_and_keeps_the_campaign_out_of_extra():
    spec = dataset_spec("shopee", "ads_campaign_daily")
    row = spec.row_model.model_validate(_ad("7001", campaign_name="A", impression=3))
    (normalized,) = normalize_rows(spec, [row])
    assert normalized.stream == "ads" and normalized.day == date(2026, 10, 29)
    assert "campaign_id" not in normalized.extra and "campaign_name" not in normalized.extra


def test_the_new_models_have_no_buyer_field_and_pass_the_allowlist_rules():
    models = [
        DATASETS[("shopee", n)].row_model
        for n in ("ads_campaign_daily", "voucher_settings", "item_catalog")
    ]
    models += [DATASETS[("shopee", n)].row_model for n in ("item_snapshot", "shop_health_daily")]
    for model in models:
        for field in model.model_fields:
            if field in FORBIDDEN_FRAGMENT_EXCEPTIONS:
                continue
            assert not any(f in field for f in FORBIDDEN_KEY_FRAGMENTS), (model.__name__, field)


def test_the_raw_copy_of_a_voucher_post_keeps_listed_fields_only():
    body = _post([_voucher("9001", "Giảm 10%", voucher_code="ABC")], "2026-10-29", "period")
    body["rows"][0]["extra"] = {"n": 1, "free_text": "x"}
    kept = allowlist_payload("shopee", ingest_endpoint("voucher_settings"), body)
    assert kept["rows"][0]["voucher_code"] == "ABC"
    assert kept["rows"][0]["extra"] == {"n": 1}


# -- item_snapshot, shop_health_daily (migration 113) --------------------------------------


def _snapshot_rows() -> list[dict[str, Any]]:
    return [
        {
            "item_id": "1001",
            "image": "img-item",
            "create_time": "2026-05-01T03:00:00+00:00",
            "price_min": 100000,
            "price_max": 150000,
            "selling_price_min": 90000,
            "selling_price_max": 135000,
            "has_discount": True,
            "discount_percent": 10,
            "total_available_stock": 30,
            "sellable_stock": 25,
            "in_transit_stock": 5,
            "view_count": 400,
            "sold_count": 12,
            "liked_count": 7,
            "promo_has_discount": True,
        },
        {"item_id": "1001", "model_id": "5001", "origin_price": 100000, "promotion_price": 90000},
    ]


def _health_rows() -> list[dict[str, Any]]:
    return [
        {
            "date": "2026-10-29",
            "failed_metric_count": 1,
            "penalty_point": 0,
            "performance_rating": 2,
        },
        {
            "date": "2026-10-29",
            "metric_id": "11",
            "label": "Tỷ lệ phản hồi chat",
            "display_value": "92%",
            "value": 92,
            "target_display": "≥ 90%",
            "target": 90,
            "compare_result": 1,
            "passed": True,
            "metric_tag": "service",
        },
    ]


def test_item_snapshot_is_a_gateway_dataset_that_validates_its_rows():
    spec = dataset_spec("shopee", "item_snapshot")
    assert spec is not None
    body = IngestBody.model_validate(_post(_snapshot_rows(), "2026-10-29", "period"))
    assert len(validate_rows(spec, body, NOW)) == 2
    dup = IngestBody.model_validate(_post([_snapshot_rows()[0]] * 2, "2026-10-29", "period"))
    with pytest.raises(IngestRejected, match="invalid_rows"):
        validate_rows(spec, dup, NOW)
    bad = IngestBody.model_validate(
        _post([{"item_id": "1", "discount_percent": 140}], "2026-10-29", "period")
    )
    with pytest.raises(IngestRejected, match="invalid_rows"):
        validate_rows(spec, bad, NOW)


def test_shop_health_daily_is_a_gateway_dataset_that_refuses_a_buyer_field():
    spec = dataset_spec("shopee", "shop_health_daily")
    assert spec is not None
    body = IngestBody.model_validate(_post(_health_rows(), "2026-10-29", "day"))
    assert len(validate_rows(spec, body, NOW)) == 2
    with pytest.raises(ValidationError):
        spec.row_model.model_validate({**_health_rows()[1], "buyer_phone": "0"})


async def test_an_item_snapshot_is_written_only_when_a_tracked_field_changed(session):
    shop = await _shop(session)
    await _ingest(session, shop, "item_snapshot", _post(_snapshot_rows(), "2026-10-29", "period"))
    first = await _rows(session, PlatformItemSnapshot, shop)
    assert {(s.item_id, s.variation_id) for s in first} == {("1001", ""), ("1001", "5001")}
    item = next(s for s in first if s.variation_id == "")
    assert (item.list_price, item.current_price, item.stock, item.sold_total, item.likes) == (
        Decimal("150000"),
        Decimal("90000"),
        30,
        12,
        7,
    )
    assert item.promo_label == "-10%" and item.image_urls == ["img-item"]
    model_row = next(s for s in first if s.variation_id == "5001")
    assert (model_row.list_price, model_row.current_price) == (Decimal("100000"), Decimal("90000"))

    # A later read with nothing changed (only a view count moved, which is not tracked).
    unchanged = _snapshot_rows()
    unchanged[0]["view_count"] = 999
    await _ingest(
        session,
        shop,
        "item_snapshot",
        _post(unchanged, "2026-10-30", "period", captured_at="2026-10-30T09:45:00+07:00"),
    )
    assert len(await _rows(session, PlatformItemSnapshot, shop)) == 2

    # Stock changed on the item row only: one new snapshot, for that item.
    changed = _snapshot_rows()
    changed[0]["total_available_stock"] = 29
    await _ingest(
        session,
        shop,
        "item_snapshot",
        _post(changed, "2026-10-30", "period", captured_at="2026-10-30T09:55:00+07:00"),
    )
    after = await _rows(session, PlatformItemSnapshot, shop)
    assert len(after) == 3
    assert sorted(s.stock for s in after if s.variation_id == "" and s.stock is not None) == [
        29,
        30,
    ]


async def test_shop_health_is_appended_per_capture_and_a_repeat_adds_nothing(session):
    shop = await _shop(session)
    body = _post(_health_rows(), "2026-10-29", "day")
    await _ingest(session, shop, "shop_health_daily", body)
    stored = await _rows(session, ShopHealthDaily, shop)
    assert {s.metric_id for s in stored} == {"", "11"}
    metric = next(s for s in stored if s.metric_id == "11")
    assert (metric.value, metric.target, metric.passed, metric.compare_result) == (
        Decimal("92"),
        Decimal("90"),
        True,
        "1",
    )
    overview = next(s for s in stored if s.metric_id == "")
    assert (overview.failed_metric_count, overview.penalty_point) == (1, 0)
    # The same body again is a duplicate (content hash): nothing is written twice.
    await _ingest(session, shop, "shop_health_daily", body)
    assert len(await _rows(session, ShopHealthDaily, shop)) == 2
    # An identical re-read at a later time is a duplicate too (the content hash ignores the
    # capture time); a CHANGED reading of the same day is a new row, never an edit.
    later = _health_rows()
    later[0]["penalty_point"] = 1
    await _ingest(
        session,
        shop,
        "shop_health_daily",
        _post(later, "2026-10-29", "day", captured_at="2026-10-30T09:58:00+07:00"),
    )
    stored = await _rows(session, ShopHealthDaily, shop)
    assert len(stored) == 4
    assert sorted(s.penalty_point for s in stored if s.metric_id == "") == [0, 1]
