"""Chat's voucher figures are the tabs' own (batch-1125 r1-chat): đơn / GMV = the Phân tích
voucher ranking's shop cell, cost = the ladder's `offer_voucher` (the C9-decided seller voucher
on the known orders), voucher settings listed without result columns. Synthetic rows only."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from juli_backend.services.analytics_agent.data_service import (
    voucher_figures_of,
    voucher_settings_in_window,
)
from juli_backend.services.shopee_analytics.rankings import _cell_other
from juli_backend.services.shopee_profit.ladder import components_of
from juli_backend.services.shopee_profit.order_profit import OrderStatus

Z = Decimal(0)


def _pair(
    order: str,
    value: int,
    share: int,
    seller_voucher: int,
    *,
    known: bool = True,
    status: OrderStatus = OrderStatus.DELIVERED,
) -> tuple[Any, Any]:
    ln = SimpleNamespace(
        order_id=order,
        order_value=Decimal(value),
        shop_voucher_share=Decimal(share),
        status=status,
    )
    pb = SimpleNamespace(
        excluded_reason=None,
        contribution=Decimal(1) if known else None,
        revenue=Decimal(value),
        cogs=Z,
        vat_input_credit=Z,
        packaging=Z,
        fees_total=Z,
        income_costs_total=Z,
        commission=Z,
        promo_discount=Z,
        voucher=Decimal(seller_voucher),
        bundle=Z,
    )
    return ln, pb


def _view(pairs: list[tuple[Any, Any]], rows: list[Any] | None = None) -> Any:
    return SimpleNamespace(
        pairs=pairs, data=SimpleNamespace(vouchers=SimpleNamespace(rows=rows or []))
    )


PAIRS = [
    _pair("o1", 100_000, 5_000, 5_000),  # a seller-paid voucher
    _pair("o1", 50_000, 2_000, 2_000),  # the same order's second line: one order
    _pair("o2", 80_000, 4_000, 0),  # buyer-side voucher C9 found the seller did NOT pay
    _pair("o3", 60_000, 3_000, 3_000, known=False),  # cost unknown: out of the cost
    _pair("o4", 70_000, 0, 0),  # no voucher
    _pair("o5", 40_000, 2_000, 2_000, status=OrderStatus.RETURNED),  # a refund: no sale
]


def test_orders_and_gmv_are_the_voucher_ranking_cell() -> None:
    got = voucher_figures_of(_view(PAIRS))
    cell = _cell_other("vouchers", _view(PAIRS))
    assert got["orders"] == int(cell.orders) == 3  # o1, o2, o3 (o5 is a refund, o4 no voucher)
    assert got["gmv"] == cell.gmv == Decimal(290_000)


def test_cost_is_the_ladders_offer_voucher_with_its_coverage() -> None:
    got = voucher_figures_of(_view(PAIRS))
    assert got["cost"] == components_of(PAIRS)["offer_voucher"]
    assert got["cost"] == Decimal(7_000) + Decimal(2_000)  # o1 + the known refund line
    assert got["known_orders"] == 2  # o1, o2
    assert round(got["known_gmv_share_pct"], 1) == round(230_000 * 100 / 290_000, 1)


def test_no_known_voucher_order_means_no_cost_never_zero() -> None:
    pairs = [_pair("o9", 10_000, 1_000, 1_000, known=False)]
    assert voucher_figures_of(_view(pairs))["cost"] is None
    # no voucher order at all: a real 0
    assert voucher_figures_of(_view([_pair("o8", 10_000, 0, 0)]))["cost"] == Z


def _snap(vid: int, read: date, starts: date, ends: date | None, **extra: Any) -> Any:
    return SimpleNamespace(
        program_name=f"V{vid}",
        starts_at=datetime(starts.year, starts.month, starts.day),
        ends_at=None if ends is None else datetime(ends.year, ends.month, ends.day, 23, 59),
        period_start=read,
        period_end=read,
        captured_at=datetime(read.year, read.month, read.day, 8),
        extra={"voucher_id": vid, **extra},
    )


def test_settings_list_the_vouchers_that_ran_newest_read_by_the_window_end() -> None:
    a, b = date(2026, 11, 1), date(2026, 11, 24)
    rows = [
        _snap(1, date(2026, 11, 20), date(2026, 11, 5), date(2026, 11, 30), current_usage=4),
        _snap(1, date(2026, 11, 24), date(2026, 11, 5), date(2026, 11, 30), current_usage=9),
        _snap(1, date(2026, 11, 26), date(2026, 11, 5), date(2026, 11, 30), current_usage=15),
        _snap(2, date(2026, 11, 26), date(2026, 11, 3), None, discount_percent=10),
        _snap(3, date(2026, 11, 26), date(2026, 12, 1), None),  # starts after the window
        _snap(4, date(2026, 11, 26), date(2026, 9, 1), date(2026, 10, 15)),  # ended before
    ]
    got = voucher_settings_in_window(rows, a, b)
    assert [v["name"] for v in got] == ["V2", "V1"]
    v1 = got[1]
    assert v1["usage"] == 9 and v1["usage_on"] == date(2026, 11, 24)  # read by 24/11, not 26/11
    assert got[0]["usage"] is None and got[0]["usage_on"] is None  # read after the window only
    assert got[0]["discount_percent"] == 10 and got[0]["ends"] is None
