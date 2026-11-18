"""P101 W2 M3 / M4 / item 6: ``DbCanonicalWriter`` on ``order_lines`` / ``order_settlements``
(SQLite here; the same writer on Postgres is in ``tests/integration``). Synthetic rows only."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from juli_backend.models.shopee_profit import ShopeeOrderIncome, ShopeeOrderLine
from juli_backend.services.ingest.canonical import OrderLine, OrderSettlement
from juli_backend.services.ingest.canonical_writer import DbCanonicalWriter
from juli_backend.services.ingest.tiktok_mapper import map_order
from tests.support.builders import make_tenant

D = Decimal
# 03:00 on 5 Oct in Vietnam = 20:00 UTC on 4 Oct
AT_0300_VN = datetime(2026, 10, 4, 20, 0, tzinfo=UTC)


def _line(shop_id: uuid.UUID, **over) -> OrderLine:
    values = {
        "shop_id": shop_id,
        "platform": "tiktok",
        "order_ref": "ref-a",
        "line_no": 0,
        "ordered_at": AT_0300_VN,
        "status": "delivered",
        "item_id": "item-1",
        "variation_id": "var-1",
        "qty": 1,
        "original_price": D("100000"),
        "deal_price": D("90000"),
        "source": "api",
        "source_version": "tiktok:test",
        **over,
    }
    return OrderLine(**values)


def _settlement(shop_id: uuid.UUID, **over) -> OrderSettlement:
    values = {
        "shop_id": shop_id,
        "platform": "tiktok",
        "order_ref": "ref-a",
        "source": "api",
        "source_rank": 4,
        "source_version": "tiktok:test",
        "payout": D("70000"),
        **over,
    }
    return OrderSettlement(**values)


async def _lines(session) -> list[ShopeeOrderLine]:
    stmt = select(ShopeeOrderLine).execution_options(populate_existing=True)
    return list((await session.execute(stmt)).scalars())


async def _settlements(session) -> list[ShopeeOrderIncome]:
    stmt = select(ShopeeOrderIncome).execution_options(populate_existing=True)
    return list((await session.execute(stmt)).scalars())


async def test_writing_twice_is_the_same_rows(session) -> None:
    _, shop = await make_tenant(session, platform="tiktok")
    writer = DbCanonicalWriter(session)
    lines = [_line(shop.id), _line(shop.id, line_no=1, variation_id="var-2")]
    settlement = _settlement(shop.id, fee_other=D("4000"))

    first = (
        await writer.upsert_order_lines(shop.id, "tiktok", lines),
        await writer.upsert_settlements(shop.id, "tiktok", [settlement]),
    )
    snapshot = {r.line_no: (r.status, r.deal_price, r.day) for r in await _lines(session)}
    second = (
        await writer.upsert_order_lines(shop.id, "tiktok", lines),
        await writer.upsert_settlements(shop.id, "tiktok", [settlement]),
    )

    assert first == second == (2, 1)
    stored = await _lines(session)
    assert {r.line_no: (r.status, r.deal_price, r.day) for r in stored} == snapshot
    assert len(stored) == 2 and len(await _settlements(session)) == 1
    assert all((r.platform, r.source, r.source_rank) == ("tiktok", "api", 4) for r in stored)


async def test_a_connector_row_does_not_overwrite_an_api_row_but_fills_its_gaps(session) -> None:
    _, shop = await make_tenant(session, platform="tiktok")
    writer = DbCanonicalWriter(session)
    await writer.upsert_order_lines(shop.id, "tiktok", [_line(shop.id, status="delivered")])
    await writer.upsert_settlements(shop.id, "tiktok", [_settlement(shop.id, payout=D("70000"))])

    connector_line = _line(shop.id, source="extension", status="cancelled", fee_fixed=D("9000"))
    connector_settlement = _settlement(
        shop.id, source="extension", source_rank=3, payout=D("1"), fee_payment=D("500")
    )
    line_count = await writer.upsert_order_lines(shop.id, "tiktok", [connector_line])
    settlement_count = await writer.upsert_settlements(shop.id, "tiktok", [connector_settlement])

    (line,) = await _lines(session)
    (row,) = await _settlements(session)
    # the API values and provenance stay; only the NULL columns were filled
    assert (line.status, line.source, line.source_rank) == ("delivered", "api", 4)
    assert line.fee_fixed == D("9000")
    assert (row.payout, row.source, row.source_rank) == (D("70000"), "api", 4)
    assert row.fee_payment == D("500")
    assert (line_count, settlement_count) == (1, 1)

    # a Connector row that adds nothing is not counted, and changes nothing
    assert await writer.upsert_order_lines(shop.id, "tiktok", [connector_line]) == 0
    assert await writer.upsert_settlements(shop.id, "tiktok", [connector_settlement]) == 0


async def test_an_api_row_replaces_a_connector_row_and_a_null_never_clears(session) -> None:
    _, shop = await make_tenant(session, platform="tiktok")
    writer = DbCanonicalWriter(session)
    await writer.upsert_order_lines(
        shop.id, "tiktok", [_line(shop.id, source="file", status="in_transit", fee_fixed=D("5"))]
    )
    await writer.upsert_order_lines(
        shop.id, "tiktok", [_line(shop.id, source="extension", status="confirmed")]
    )
    await writer.upsert_order_lines(shop.id, "tiktok", [_line(shop.id, status="delivered")])

    (line,) = await _lines(session)
    assert (line.status, line.source, line.source_rank) == ("delivered", "api", 4)
    assert line.fee_fixed == D("5")  # no later row stated it as NULL-clearing


async def test_times_are_aware_utc_and_day_is_the_vn_date_at_0300_vn(session) -> None:
    _, shop = await make_tenant(session, platform="tiktok")
    writer = DbCanonicalWriter(session)
    await writer.upsert_order_lines(
        shop.id,
        "tiktok",
        [_line(shop.id, paid_at=AT_0300_VN.replace(minute=5))],
    )

    (line,) = await _lines(session)
    assert line.ordered_at == AT_0300_VN  # the same instant
    assert line.ordered_at.utcoffset() is not None
    assert line.ordered_at.astimezone(UTC).date() == date(2026, 10, 4)
    assert line.day == date(2026, 10, 5)  # the VN day, not the UTC date


async def test_the_mapper_output_lands_with_fee_other_and_the_nine_statuses(session) -> None:
    _, shop = await make_tenant(session, platform="tiktok")
    order = {
        "id": "900000000000000001",
        "status": "AWAITING_SHIPMENT",
        "create_time": int(AT_0300_VN.timestamp()),
        "paid_time": int(AT_0300_VN.timestamp()) + 60,
        "payment": {"currency": "VND", "shipping_fee": "0"},
        "line_items": [
            {
                "id": "1",
                "product_id": "7",
                "sku_id": "6",
                "original_price": "100000",
                "sale_price": "100000",
            }
        ],
    }
    statement = {
        "currency": "VND",
        "settlement_amount": "60000",
        "sku_transactions": [
            {
                "sku_id": "6",
                "settlement_amount": "60000",
                "revenue_breakdown": {"subtotal_before_discount_amount": "100000"},
                "fee_tax_breakdown": {
                    "fee": {
                        "platform_commission_amount": "-9000",
                        "sfp_service_fee_amount": "-4000",
                    },
                    "tax": {"vat_amount": "-1800"},
                },
            }
        ],
    }
    mapped = map_order(order, shop_id=shop.id, statement=statement)
    assert mapped.settlement is not None
    writer = DbCanonicalWriter(session)

    await writer.upsert_order_lines(shop.id, "tiktok", mapped.lines)
    await writer.upsert_settlements(shop.id, "tiktok", [mapped.settlement])

    (line,) = await _lines(session)
    (row,) = await _settlements(session)
    assert (line.status, line.day) == ("confirmed", date(2026, 10, 5))
    assert row.fee_other == D("4000") and row.fee_fixed == D("9000")
    assert row.vat_withheld == D("1800")  # stored as reported


async def test_a_row_of_another_shop_is_refused(session) -> None:
    _, shop = await make_tenant(session, platform="tiktok")
    writer = DbCanonicalWriter(session)

    with pytest.raises(ValueError, match="outside") as excinfo:
        await writer.upsert_order_lines(shop.id, "tiktok", [_line(uuid.uuid4())])

    assert "shop / platform" in str(excinfo.value)
    assert await _lines(session) == []


async def test_a_settlement_equal_rank_latest_wins(session) -> None:
    _, shop = await make_tenant(session, platform="tiktok")
    writer = DbCanonicalWriter(session)
    first = _settlement(shop.id, payout=D("100"))
    await writer.upsert_settlements(shop.id, "tiktok", [first])
    await writer.upsert_settlements(shop.id, "tiktok", [replace(first, payout=D("120"))])

    (row,) = await _settlements(session)
    assert row.payout == D("120")
