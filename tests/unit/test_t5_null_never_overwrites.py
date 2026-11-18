"""Owner 2026-11-18 (T5 round 2): the Connector outranks a file, and a NULL or missing value
never overwrites a stored one, whatever the source.

The gateway's ranked upsert (``platform_daily_metrics``, flags, promotions), the order-line and
the affiliate-line writers, on SQLite. ``order_settlements`` already kept stated values
(``tests/unit/test_shopee_income_ingest.py``).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select

from juli_backend.models.ingest import PlatformDailyMetric
from juli_backend.models.shopee_profit import ShopeeAffiliateLine, ShopeeOrderLine
from juli_backend.services.ingest.rate_limit import InMemoryRateGate, set_ingest_rate_gate
from juli_backend.services.ingest.schemas import ShopeeAffiliateOrderLineRow, ShopeeOrderLineRow
from juli_backend.services.ingest.writers import write_affiliate_lines, write_order_lines
from tests.support.builders import make_tenant
from tests.unit.test_shopee_file_datasets import _body, _ingest, _rows, _shop

CARD = "psd_label_product_card"
ORDER = f"{9:032x}"
AT = datetime(2026, 10, 1, 10, 0)


@pytest.fixture(autouse=True)
def generous_gate():
    set_ingest_rate_gate(InMemoryRateGate())
    yield
    set_ingest_rate_gate(None)


def _traffic(**kpis: Any) -> dict[str, Any]:
    return {"date": "2026-10-01", "source": CARD, **kpis}


def _post(source: str, captured_at: str, **kpis: Any) -> dict[str, Any]:
    return _body(
        [_traffic(**kpis)],
        source=source,
        source_version=f"{source}-1",
        captured_at=captured_at,
    )


async def _shop_row(session, shop) -> PlatformDailyMetric:
    (row,) = [m for m in await _rows(session, PlatformDailyMetric, shop) if m.segment == "all"]
    return row


# ------------------------------------------------------------------ the gateway's ranked upsert


async def test_a_higher_rank_post_with_a_null_keeps_the_stored_value(session):
    shop = await _shop(session)
    await _ingest(
        session,
        shop,
        "traffic_overview",
        _post("file", "2026-10-29T09:30:00+07:00", sales=1000, orders=4),
    )
    await _ingest(
        session,
        shop,
        "traffic_overview",
        _post("extension", "2026-10-29T10:30:00+07:00", sales=900),
    )
    row = await _shop_row(session, shop)
    assert (row.gmv, row.orders, row.source) == (Decimal("900"), 4, "extension")


async def test_a_later_post_with_a_value_replaces_the_stored_value(session):
    shop = await _shop(session)
    await _ingest(
        session,
        shop,
        "traffic_overview",
        _post("extension", "2026-10-29T09:30:00+07:00", sales=900, orders=4),
    )
    await _ingest(
        session,
        shop,
        "traffic_overview",
        _post("extension", "2026-10-29T10:30:00+07:00", sales=950, orders=5),
    )
    row = await _shop_row(session, shop)
    assert (row.gmv, row.orders) == (Decimal("950"), 5)


async def test_a_lower_rank_post_is_ignored_even_where_the_stored_value_is_null(session):
    shop = await _shop(session)
    await _ingest(
        session,
        shop,
        "traffic_overview",
        _post("extension", "2026-10-29T09:30:00+07:00", sales=900),
    )
    await _ingest(
        session,
        shop,
        "traffic_overview",
        _post("file", "2026-10-29T10:30:00+07:00", sales=1000, orders=4),
    )
    row = await _shop_row(session, shop)
    assert (row.gmv, row.orders, row.source) == (Decimal("900"), None, "extension")


# ------------------------------------------------------------------ the order-line writer


def _provenance(shop_id, source: str = "file", rank: int = 2) -> dict[str, Any]:
    return {
        "shop_id": shop_id,
        "platform": "shopee",
        "source": source,
        "source_rank": rank,
        "source_version": "t5",
        "raw_payload_id": None,
        "updated_at": datetime(2026, 10, 3, 1, 0),
    }


def _line(**over: Any) -> ShopeeOrderLineRow:
    values = {
        "order_ref": ORDER,
        "ordered_at": AT,
        "status": "delivered",
        "sku": "G1",
        "qty": 1,
        "original_price": Decimal(100_000),
        "deal_price": Decimal(90_000),
        **over,
    }
    return ShopeeOrderLineRow.model_validate(values)


async def _stored_line(session) -> ShopeeOrderLine:
    stmt = select(ShopeeOrderLine).execution_options(populate_existing=True)
    return (await session.execute(stmt)).scalar_one()


async def test_an_order_line_null_never_erases_a_stored_fee_or_sku(session):
    _, shop = await make_tenant(session)
    full = _line(
        buyer_shipping_fee=Decimal(15_000), bank_promo=Decimal(2_000), variation_sku="G1-R"
    )
    await write_order_lines(session, [full], None, _provenance(shop.id))
    bare = _line(status="in_transit")  # a Connector read without them
    await write_order_lines(session, [bare], None, _provenance(shop.id, "extension", 3))
    stored = await _stored_line(session)
    assert (stored.buyer_shipping_fee, stored.bank_promo) == (Decimal(15_000), Decimal(2_000))
    assert (stored.variation_sku, stored.status, stored.source) == (
        "G1-R",
        "in_transit",
        "extension",
    )
    again = _line(buyer_shipping_fee=Decimal(16_000))
    await write_order_lines(session, [again], None, _provenance(shop.id, "extension", 3))
    assert (await _stored_line(session)).buyer_shipping_fee == Decimal(16_000)


# ------------------------------------------------------------------ the affiliate-line writer


def _affiliate(**over: Any) -> ShopeeAffiliateOrderLineRow:
    values = {
        "order_ref": ORDER,
        "item_id": "1001",
        "model_id": "55",
        "qty": 1,
        "ordered_at": AT,
        "order_status": "Đang chờ xử lý",
        "valid": True,
        **over,
    }
    return ShopeeAffiliateOrderLineRow.model_validate(values)


async def test_an_affiliate_line_null_never_erases_a_stored_value(session):
    _, shop = await make_tenant(session)
    first = _affiliate(price=Decimal(90_000), refund_amount=Decimal(0), affiliate_account="kol.a")
    await write_affiliate_lines(session, [first], None, _provenance(shop.id))
    await write_affiliate_lines(
        session, [_affiliate(order_status="Đã hoàn thành")], None, _provenance(shop.id)
    )
    stmt = select(ShopeeAffiliateLine).execution_options(populate_existing=True)
    stored = (await session.execute(stmt)).scalar_one()
    assert (stored.price, stored.refund_amount) == (Decimal(90_000), Decimal(0))
    assert (stored.kol_handle, stored.status) == ("kol.a", "Đã hoàn thành")
