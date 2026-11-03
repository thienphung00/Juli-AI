"""P90 Step 6 on SQLite: file vs Connector on the same key (D-5, G-22), ads order basis (D-2),
and the `item_traffic_sources` dataset. One test per conflict pair, each asserting which value
wins. Values are synthetic."""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import update

from juli_backend.models.ingest import SOURCE_RANK, PlatformDailyMetric, effective_rank
from juli_backend.services.ingest.gateway import IngestRejected
from juli_backend.services.ingest.mapping import DATASETS, normalize_rows
from juli_backend.services.ingest.precedence import count_source_conflicts
from juli_backend.services.ingest.rate_limit import InMemoryRateGate, set_ingest_rate_gate
from tests.unit.test_shopee_file_datasets import _body, _ingest, _rows, _shop
from tests.unit.test_shopee_reader_datasets import _ad, _post

CARD = "psd_label_product_card"


@pytest.fixture(autouse=True)
def generous_gate():
    set_ingest_rate_gate(InMemoryRateGate())
    yield
    set_ingest_rate_gate(None)


def _traffic(sales: int, **over: Any) -> dict[str, Any]:
    return {"date": "2026-10-01", "source": CARD, "sales": sales, "orders": 1, **over}


def _from(source: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    return _body(rows, source=source, source_version=f"{source}-1")


async def _gmv(session, shop) -> list[Decimal]:
    stored = await _rows(session, PlatformDailyMetric, shop)
    return [m.gmv for m in stored if m.segment == "all"]


def test_ranks_put_a_file_above_the_connector_and_the_api_above_both():
    assert SOURCE_RANK["vendor"] < SOURCE_RANK["extension"] < SOURCE_RANK["file"]
    assert SOURCE_RANK["file"] < SOURCE_RANK["api"]
    # a row stored before D-5 (file = extension = 2) is ranked by its source
    assert effective_rank("file", 2) == SOURCE_RANK["file"]
    assert effective_rank("extension", 2) == SOURCE_RANK["extension"]


async def test_file_then_connector_the_file_row_stays(session):
    shop = await _shop(session)
    await _ingest(session, shop, "traffic_overview", _from("file", [_traffic(1000)]))
    await _ingest(session, shop, "traffic_overview", _from("extension", [_traffic(900)]))
    assert await _gmv(session, shop) == [Decimal("1000")]
    (row,) = await _rows(session, PlatformDailyMetric, shop)
    assert row.source == "file"


async def test_connector_then_file_the_file_row_replaces_it(session):
    shop = await _shop(session)
    await _ingest(session, shop, "traffic_overview", _from("extension", [_traffic(900)]))
    await _ingest(session, shop, "traffic_overview", _from("file", [_traffic(1000)]))
    assert await _gmv(session, shop) == [Decimal("1000")]
    (row,) = await _rows(session, PlatformDailyMetric, shop)
    assert row.source == "file" and row.source_rank == SOURCE_RANK["file"]


async def test_connector_then_connector_the_later_post_wins(session):
    shop = await _shop(session)
    await _ingest(session, shop, "traffic_overview", _from("extension", [_traffic(900)]))
    later = _from("extension", [_traffic(950)])
    later["captured_at"] = "2026-10-30T09:30:00+07:00"
    await _ingest(session, shop, "traffic_overview", later)
    assert await _gmv(session, shop) == [Decimal("950")]


async def test_a_row_stored_before_d5_at_rank_two_is_not_overwritten_by_the_connector(session):
    shop = await _shop(session)
    await _ingest(session, shop, "traffic_overview", _from("file", [_traffic(1000)]))
    await session.execute(update(PlatformDailyMetric).values(source_rank=2))  # as stored by 108
    await _ingest(session, shop, "traffic_overview", _from("extension", [_traffic(900)]))
    assert await _gmv(session, shop) == [Decimal("1000")]


async def test_the_connector_fills_a_day_no_file_covers(session):
    shop = await _shop(session)
    await _ingest(session, shop, "traffic_overview", _from("file", [_traffic(1000)]))
    other = _traffic(500, date="2026-10-02")
    body = _from("extension", [other])
    body["period"] = {"start": "2026-10-02", "end": "2026-10-02", "granularity": "day"}
    await _ingest(session, shop, "traffic_overview", body)
    by_day = {m.day: (m.gmv, m.source) for m in await _rows(session, PlatformDailyMetric, shop)}
    assert by_day == {
        date(2026, 10, 1): (Decimal("1000"), "file"),
        date(2026, 10, 2): (Decimal("500"), "extension"),
    }


async def test_a_difference_between_the_two_sources_is_counted_not_hidden(session, caplog):
    shop = await _shop(session)
    await _ingest(session, shop, "traffic_overview", _from("file", [_traffic(1000)]))
    with caplog.at_level(logging.INFO, logger="juli_backend.services.ingest.precedence"):
        await _ingest(session, shop, "traffic_overview", _from("extension", [_traffic(900)]))
    (record,) = [r for r in caplog.records if r.message == "ingest_source_conflicts"]
    assert (record.kept_existing, record.replaced_existing, record.differing) == (1, 0, 1)

    # the same numbers from both sources are a conflict by key but not a difference
    other = await _shop(session)
    await _ingest(session, other, "traffic_overview", _from("file", [_traffic(1000)]))
    values = [
        {
            "shop_id": other.id,
            "platform": "shopee",
            "dataset": "traffic_overview",
            "source": "extension",
            "day": date(2026, 10, 1),
            "item_id": "",
            "stream": "product_card",
            "segment": "all",
            "order_type": "confirmed",
            "gmv": Decimal("1000"),
            "orders": Decimal("1"),
        }
    ]
    found = await count_source_conflicts(
        session,
        PlatformDailyMetric,
        ("shop_id", "platform", "dataset", "day", "item_id", "stream", "segment", "order_type"),
        values,
    )
    assert (found.kept_existing, found.differing) == (1, 0)


# -- D-2: ads are placed / paid, never confirmed -----------------------------------------


@pytest.mark.parametrize("dataset", ["ads_campaign_daily"])
async def test_ads_reports_refuse_the_confirmed_order_type(session, dataset):
    shop = await _shop(session)
    body = _post([_ad("7001", impression=1)], "2026-10-29", "day", order_type="confirmed")
    with pytest.raises(IngestRejected) as err:
        await _ingest(session, shop, dataset, body)
    assert err.value.code == "ads_order_type_confirmed"


async def test_ads_rows_keep_their_placed_basis(session):
    shop = await _shop(session)
    body = _post([_ad("7001", impression=1)], "2026-10-29", "day", order_type="placed")
    await _ingest(session, shop, "ads_campaign_daily", body)
    (row,) = await _rows(session, PlatformDailyMetric, shop)
    assert row.order_type == "placed"


# -- item_traffic_sources ----------------------------------------------------------------


def _source(l1: str, l2: str, **over: Any) -> dict[str, Any]:
    return {
        "date": "2026-10-29",
        "item_id": "1001",
        "l1": l1,
        "l2": l2,
        "sales": 10,
        "orders": 1,
        **over,
    }


def test_item_traffic_sources_maps_the_contract_frame():
    spec = DATASETS[("shopee", "item_traffic_sources")]
    assert (spec.writes, spec.granularity, spec.has_order_type) == ("daily", "day", True)
    expected = {
        ("product_card", "total"): ("product_card", "all"),
        ("product_card", "search"): ("product_card", "search"),
        ("product_card", "recommendation"): ("product_card", "recommend"),
        ("product_card", "my_purchase"): ("product_card", "my_orders"),
        ("product_card", "shopping_cart"): ("product_card", "cart"),
        ("product_card", "shop"): ("product_card", "shop_page"),
        ("product_card", "promotion"): ("product_card", "promo"),
        ("product_card", "others"): ("product_card", "other"),
        ("live", "total"): ("seller_live", "all"),
        ("video", "search"): ("seller_video", "search"),
        ("affiliate", "total"): ("affiliate", "all"),
    }
    for (l1, l2), (stream, segment) in expected.items():
        row = spec.row_model.model_validate(_source(l1, l2))
        (normalized,) = normalize_rows(spec, [row])
        assert (normalized.stream, normalized.segment) == (stream, segment), (l1, l2)
        assert normalized.item_id == "1001" and normalized.day == date(2026, 10, 29)
        assert normalized.kpis["gmv"] == 10 and normalized.kpis["orders"] == 1


def test_item_traffic_sources_accepts_the_platform_prefix_and_refuses_unknowns():
    model = DATASETS[("shopee", "item_traffic_sources")].row_model
    assert model.model_validate(_source("product_card", "psd_label_search")).l2 == "search"
    for bad in (_source("product_card", "chat"), _source("ads", "total"), _source("live", "x")):
        with pytest.raises(ValidationError):
            model.model_validate(bad)
    with pytest.raises(ValidationError):
        model.model_validate({**_source("live", "total"), "buyer_name": "x"})


async def test_item_traffic_sources_lands_per_item_day_stream_segment(session):
    shop = await _shop(session)
    rows = [
        _source("product_card", "total"),
        _source("product_card", "shop"),
        _source("live", "total"),
    ]
    body = _body(rows, source="extension", source_version="0.3.1")
    body["period"] = {"start": "2026-10-29", "end": "2026-10-29", "granularity": "day"}
    await _ingest(session, shop, "item_traffic_sources", body)
    stored = await _rows(session, PlatformDailyMetric, shop)
    assert {(m.stream, m.segment) for m in stored} == {
        ("product_card", "all"),
        ("product_card", "shop_page"),
        ("seller_live", "all"),
    }
    assert {m.dataset for m in stored} == {"item_traffic_sources"}
    with pytest.raises(IngestRejected):  # a duplicate (item, day, l1, l2) is refused
        await _ingest(
            session,
            shop,
            "item_traffic_sources",
            {**body, "rows": [_source("live", "total"), _source("live", "total")]},
        )


# -- D-4 / G-21 ----------------------------------------------------------------------------


def test_the_two_flow_keys_never_collide():
    from juli_backend.services.shopee_kpi.job import FLOW_SOURCES
    from juli_backend.services.shopee_profit.flows import Flow

    assert "the_san_pham" in FLOW_SOURCES  # incl. Trang shop (shopee_kpi, unchanged)
    assert FLOW_SOURCES["the_san_pham"].segment == "all"
    assert {f.value for f in Flow} == {
        "the_san_pham_khac",
        "trang_shop",
        "live",
        "video",
        "lien_ket",
    }


def test_the_contract_gmv_column_is_tong_doanh_so():
    from juli_backend.services.ingest.mapping import normalize_rows
    from scripts.shopee_exports.parse import SHOP_OVERVIEW

    assert SHOP_OVERVIEW["Tổng doanh số (VND)"] == ("sales", None)
    spec = DATASETS[("shopee", "shop_overview")]
    row = spec.row_model.model_validate(
        {"date": "2026-10-01", "sales": 1000, "extra": {"sales_excl_shopee_subsidy": 900}}
    )
    (normalized,) = normalize_rows(spec, [row])
    assert normalized.kpis["gmv"] == 1000  # not the "excluding Shopee subsidy" column
    assert normalized.extra["sales_excl_shopee_subsidy"] == 900
