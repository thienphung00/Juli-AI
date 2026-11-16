"""P101 W2: the canonical rows (layer 3), the writer contract and the one compute input."""

from __future__ import annotations

import ast
import uuid
from dataclasses import fields, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from juli_backend.models.shopee_profit import ShopeeOrderIncome, ShopeeOrderLine
from juli_backend.services.ingest import canonical
from juli_backend.services.ingest.canonical import (
    FEE_OTHER,
    LINE_RENAMES,
    SETTLEMENT_NEW_FIELDS,
    SETTLEMENT_RENAMES,
    OrderLine,
    OrderSettlement,
    compute_status,
    day_of,
    profit_order_lines,
    replaces,
)
from juli_backend.services.shopee_profit.order_profit import OrderStatus, SkuCost, line_profit
from tests.support.canonical_writer import InMemoryCanonicalWriter

SHOP = uuid.UUID("00000000-0000-4000-8000-000000000001")
OTHER_SHOP = uuid.UUID("00000000-0000-4000-8000-000000000002")
BOOKKEEPING = {"id", "created_at", "updated_at"}
D = Decimal


LINE = OrderLine(
    shop_id=SHOP,
    platform="tiktok",
    order_ref="ref-a",
    line_no=0,
    ordered_at=datetime(2026, 10, 1, 3, 0, tzinfo=UTC),
    status="delivered",
    item_id="item-1",
    variation_id="var-1",
    variation_sku="SKU-1",
    qty=1,
    original_price=D("100000"),
    deal_price=D("90000"),
    seller_subsidy=D("10000"),
    source="api",
    source_version="test",
)
SETTLEMENT = OrderSettlement(
    shop_id=SHOP,
    platform="tiktok",
    order_ref="ref-a",
    source="api",
    source_rank=4,
    source_version="test",
)


def _line(**over: Any) -> OrderLine:
    return replace(LINE, **over)


def _settlement(**over: Any) -> OrderSettlement:
    return replace(SETTLEMENT, **over)


# -- field set = the Shopee columns (drift fails CI) ----------------------------------------


def _columns(model: type[ShopeeOrderLine] | type[ShopeeOrderIncome]) -> set[str]:
    return {c.name for c in model.__table__.columns} - BOOKKEEPING


def test_order_line_fields_are_the_shopee_line_columns_modulo_the_rename() -> None:
    canonical_fields = {f.name for f in fields(OrderLine)}
    renamed = {LINE_RENAMES.get(name, name) for name in canonical_fields}

    assert renamed == _columns(ShopeeOrderLine)
    assert LINE_RENAMES == {"platform_subsidy": "shopee_subsidy"}


def test_settlement_fields_are_the_income_columns_modulo_rename_and_fee_other() -> None:
    canonical_fields = {f.name for f in fields(OrderSettlement)} - SETTLEMENT_NEW_FIELDS
    renamed = {SETTLEMENT_RENAMES.get(name, name) for name in canonical_fields}

    assert renamed == _columns(ShopeeOrderIncome)
    assert SETTLEMENT_RENAMES == {"ship_platform_subsidy": "ship_shopee_subsidy"}
    assert SETTLEMENT_NEW_FIELDS == {"fee_other"}


def test_canonical_imports_no_orm_or_database_module() -> None:
    tree = ast.parse(Path(canonical.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    banned = [
        m
        for m in imported
        if m.split(".")[0] == "sqlalchemy"
        or m.startswith(
            ("juli_backend.models", "juli_backend.database", "juli_backend.repositories")
        )
    ]
    assert banned == []
    assert "juli_backend.services.shopee_profit.order_profit" in imported


def test_defaults_match_the_columns_defaults() -> None:
    line = _line()

    assert (line.returned_qty, line.shop_voucher_share, line.platform_subsidy) == (0, 0, 0)
    assert line.promo_kind == "none"
    assert line.affiliate is False
    assert line.ad_attributed is None
    assert line.fee_fixed is None and line.payout is None


# -- precedence and the writer contract -----------------------------------------------------


@pytest.mark.parametrize(
    ("stored", "incoming", "expected"),
    [(3, 4, True), (4, 4, True), (4, 3, False)],
)
def test_replaces_same_or_higher_rank(stored: int, incoming: int, expected: bool) -> None:
    assert replaces(stored, incoming) is expected


async def test_writer_is_idempotent_on_the_line_key() -> None:
    writer = InMemoryCanonicalWriter()
    lines = [_line(line_no=0), _line(line_no=1, item_id="item-2")]

    first = await writer.upsert_order_lines(SHOP, "tiktok", lines)
    second = await writer.upsert_order_lines(SHOP, "tiktok", lines)

    assert (first, second) == (2, 2)
    assert len(writer.lines) == 2
    assert writer.lines[(SHOP, "tiktok", "ref-a", 1)].item_id == "item-2"


async def test_line_rank_comes_from_source_and_lower_never_overwrites() -> None:
    writer = InMemoryCanonicalWriter()
    await writer.upsert_order_lines(SHOP, "tiktok", [_line(source="file", status="in_transit")])

    kept = await writer.upsert_order_lines(
        SHOP, "tiktok", [_line(source="extension", status="cancelled")]
    )
    replaced = await writer.upsert_order_lines(
        SHOP, "tiktok", [_line(source="api", status="delivered")]
    )

    assert (kept, replaced) == (0, 1)
    stored = writer.lines[(SHOP, "tiktok", "ref-a", 0)]
    assert (stored.source, stored.status) == ("api", "delivered")


async def test_line_null_fee_or_time_never_erases_a_stored_one() -> None:
    writer = InMemoryCanonicalWriter()
    paid = datetime(2026, 10, 1, 4, 0, tzinfo=UTC)
    await writer.upsert_order_lines(SHOP, "tiktok", [_line(fee_fixed=D("5000"), paid_at=paid)])

    await writer.upsert_order_lines(SHOP, "tiktok", [_line(status="cancelled")])

    stored = writer.lines[(SHOP, "tiktok", "ref-a", 0)]
    assert stored.status == "cancelled"
    assert (stored.fee_fixed, stored.paid_at) == (D("5000"), paid)


async def test_settlement_precedence_equal_rank_latest_wins_lower_kept() -> None:
    writer = InMemoryCanonicalWriter()
    await writer.upsert_settlements(
        SHOP, "tiktok", [_settlement(source="file", source_rank=3, payout=D("100"))]
    )

    lower = await writer.upsert_settlements(
        SHOP, "tiktok", [_settlement(source="extension", source_rank=2, payout=D("1"))]
    )
    equal = await writer.upsert_settlements(
        SHOP, "tiktok", [_settlement(source="file", source_rank=3, payout=D("120"))]
    )
    higher = await writer.upsert_settlements(
        SHOP, "tiktok", [_settlement(source="api", source_rank=4, fee_fixed=D("7"))]
    )

    assert (lower, equal, higher) == (0, 1, 1)
    stored = writer.settlements[(SHOP, "tiktok", "ref-a")]
    assert stored.source == "api"
    # The api row did not state a payout: the stored one survives (NULL is not zero).
    assert (stored.payout, stored.fee_fixed) == (D("120"), D("7"))


async def test_writer_rejects_a_row_of_another_shop() -> None:
    writer = InMemoryCanonicalWriter()

    with pytest.raises(ValueError, match="outside") as excinfo:
        await writer.upsert_settlements(SHOP, "tiktok", [_settlement(shop_id=OTHER_SHOP)])

    assert "shop / platform" in str(excinfo.value)
    assert writer.settlements == {}


# -- canonical -> compute input -------------------------------------------------------------


def test_actual_fees_is_the_sum_of_stated_line_fees() -> None:
    lines = [
        _line(line_no=0, fee_fixed=D("3000"), fee_other=D("500")),
        _line(line_no=1, item_id="item-2"),
    ]

    out = profit_order_lines(lines)

    assert [ln.actual_fees for ln in out] == [D("3500"), None]
    assert out[0].buyer_paid == D("90000")
    assert out[0].order_date == date(2026, 10, 1)


def test_settlement_split_by_buyer_paid_with_fee_other_and_reported_tax() -> None:
    lines = [
        _line(line_no=0, deal_price=D("60000")),
        _line(line_no=1, item_id="item-2", variation_sku="SKU-2", deal_price=D("30000")),
    ]
    settlement = _settlement(
        fee_fixed=D("9000"),
        fee_payment=D("3000"),
        fee_other=D("1500"),
        affiliate_commission=D("0"),
        net_shipping_cost=D("6000"),
        vat_withheld=D("900"),
        pit_withheld=D("450"),
        payout=D("70000"),
    )

    out = profit_order_lines(lines, settlement)

    first = out[0].income
    assert first is not None
    fees = dict(first.fees)
    assert (fees["phi_co_dinh"], fees["phi_xu_ly_giao_dich"], fees[FEE_OTHER]) == (
        D("6000.00"),
        D("2000.00"),
        D("1000.00"),
    )
    assert sum(dict(ln.income.fees)[FEE_OTHER] for ln in out if ln.income) == D("1500")
    # reported VAT 900 + PIT 450, 2/3 on this line (buyer paid 60000 of 90000)
    assert first.tax_withheld == D("900.00")
    assert sum(ln.income.tax_withheld for ln in out if ln.income) == D("1350")
    breakdown = line_profit(out[0], SkuCost(sku="SKU-1", cogs=D("20000"), packaging=D("1000")))
    # 60000 buyer paid - 9000 fees (6000+2000+1000) - 20000 COGS - 1000 packaging - 4000 shipping
    # - 900 reported withheld tax
    assert breakdown.contribution == D("25100.00")
    assert breakdown.fee_source == "income"


def test_unknown_status_counts_as_in_transit_never_delivered() -> None:
    out = profit_order_lines([_line(status="awaiting_magic")])

    assert compute_status("awaiting_magic") is OrderStatus.IN_TRANSIT
    assert out[0].status is OrderStatus.IN_TRANSIT
    assert line_profit(out[0], None).excluded_reason == "no_fee_no_profit"


def test_zero_quantity_lines_are_left_out_and_orders_cannot_mix() -> None:
    assert profit_order_lines([_line(qty=0)]) == []

    with pytest.raises(ValueError, match="one order") as excinfo:
        profit_order_lines([_line(), _line(order_ref="ref-b")])
    assert "one order" in str(excinfo.value)


def test_order_date_is_the_vietnam_calendar_day() -> None:
    late_utc = datetime(2026, 10, 1, 18, 30, tzinfo=UTC)  # 01:30 on 2 Oct in Hanoi

    assert day_of(late_utc) == date(2026, 10, 2)
    assert day_of(late_utc.replace(tzinfo=None)) == date(2026, 10, 2)
    assert profit_order_lines([_line(ordered_at=late_utc)])[0].order_date == date(2026, 10, 2)


def test_settlement_of_another_order_is_refused() -> None:
    with pytest.raises(ValueError, match="another order") as excinfo:
        profit_order_lines([_line()], replace(_settlement(), order_ref="ref-z"))
    assert "another order" in str(excinfo.value)
