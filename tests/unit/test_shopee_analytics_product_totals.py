"""Which GMV a product row reports (P97 D85.2): the order lines scaled to the shop totals, or --
with no lines -- Shopee's product-period totals scaled the same way. Pure."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from juli_backend.services.shopee_analytics import matrix, metrics
from juli_backend.services.shopee_analytics.loaders import (
    OrderLinesLoad,
    ProductFlows,
    product_totals_for,
)
from juli_backend.services.shopee_analytics.windows import PeriodChoice, Window

WINDOW = Window(date(2026, 10, 4), date(2026, 11, 2))  # 30 days
PID = "item-1"


def _flows(covered_days: int, basis: str) -> ProductFlows:
    period = (date(2026, 10, 31), date(2026, 11, 2))
    choice = PeriodChoice((period,), basis, covered_days)
    return ProductFlows(
        rows=[],
        children={},
        totals={PID: (Decimal(2_450_000), 31)},
        flow_totals={},
        trang_shop_split=False,
        flows_basis=choice,
        totals_basis=choice,
        source="item_traffic_sources",
    )


def _lines(first: date, last: date, days_with_orders: int) -> OrderLinesLoad:
    return OrderLinesLoad([], WINDOW, days_with_orders, (first, last))


def _ln(order: str, product: str, value: int, qty: int = 1) -> SimpleNamespace:
    return SimpleNamespace(order_id=order, product_id=product, order_value=Decimal(value), qty=qty)


def _view(pf: ProductFlows, lines: OrderLinesLoad, pairs: list | None = None) -> SimpleNamespace:
    pairs = pairs or []
    return SimpleNamespace(
        pairs=[(ln, None) for ln in pairs],
        line_orders=len({ln.order_id for ln in pairs}),
        data=SimpleNamespace(product_flows=pf, lines=lines),
    )


@pytest.fixture(autouse=True)
def _no_overlays(monkeypatch):
    monkeypatch.setattr(matrix, "ads_overlay", lambda *a, **k: {"spend": 0})
    monkeypatch.setattr(matrix, "card_children", lambda *a, **k: None)


def test_order_lines_covered_days_clip_the_export_span_to_the_window():
    assert _lines(date(2026, 10, 9), date(2026, 11, 20), 20).covered_days == 25
    assert _lines(date(2026, 9, 1), date(2026, 12, 1), 20).covered_days == 30
    assert OrderLinesLoad([], WINDOW, 7, None).covered_days == 7


def test_order_lines_are_scaled_to_the_shop_totals_and_add_up_exactly():
    pairs = [_ln("o1", PID, 100_000), _ln("o2", PID, 100_000), _ln("o3", "item-2", 100_000, 3)]
    view = _view(_flows(30, "exact"), _lines(date(2026, 10, 9), date(2026, 11, 2), 24), pairs)
    splits, scale, order_scale = metrics._splits(view, Decimal(1_000_000), 6)
    assert scale == Decimal(1_000_000) / Decimal(300_000) and order_scale == 2
    assert sum(s.gmv for s in splits.values()) == Decimal(1_000_000)
    assert splits[PID].gmv == Decimal(666_667) and splits["item-2"].gmv == Decimal(333_333)
    assert splits[PID].orders == 4 and splits[PID].basis == metrics.SPLIT_SCALED_LINES
    assert splits["item-2"].units == 10  # 3 units scaled by 10/3


def test_three_days_of_product_data_lose_to_24_days_of_order_lines():
    pairs = [_ln("o1", PID, 8_680_000)]
    view = _view(_flows(3, "contained"), _lines(date(2026, 10, 9), date(2026, 11, 2), 24), pairs)
    splits, _, _ = metrics._splits(view, Decimal(8_680_000), 90)
    assert splits[PID].basis == metrics.SPLIT_SCALED_LINES and splits[PID].gmv == 8_680_000
    assert product_totals_for(view.data.product_flows, view.data.lines) == {}


def test_without_order_lines_the_product_period_stands_in_scaled_to_the_shop():
    view = _view(_flows(30, "exact"), OrderLinesLoad([], WINDOW))
    splits, scale, _ = metrics._splits(view, Decimal(5_000_000), 62)
    assert splits[PID].basis == metrics.SPLIT_PRODUCT_PERIOD
    assert splits[PID].gmv == Decimal(5_000_000) and scale == Decimal(5_000_000) / 2_450_000
    # no lines and no product data: no split, the shop total stays unattributed
    empty = ProductFlows(
        [], {}, {}, {}, False, _flows(0, "none").flows_basis, _flows(0, "none").totals_basis, "none"
    )
    assert metrics._splits(_view(empty, OrderLinesLoad([], WINDOW)), Decimal(1), 1) == (
        {},
        None,
        None,
    )


def test_a_matrix_row_reports_the_split_and_keeps_the_raw_line_figures():
    split = metrics.ProductSplit(
        PID, Decimal(1_240_000), 31, 40, Decimal(8_680_000), 90, "scaled_order_lines"
    )
    view = SimpleNamespace(
        profit=SimpleNamespace(products={}),
        matrix=SimpleNamespace(
            lever={}, totals={PID: SimpleNamespace(gmv=Decimal(8_680_000), orders=90)}
        ),
        flows=None,
        metrics=SimpleNamespace(split=lambda i: split if i == PID else None),
        data=SimpleNamespace(
            product_flows=_flows(30, "exact"),
            lines=_lines(date(2026, 10, 9), date(2026, 11, 2), 24),
        ),
        names={PID: "Sản phẩm mẫu"},
    )
    row = matrix.product_row(view, PID)
    assert row["gmv"] == 1_240_000 and row["orders"] == 31
    assert row["gmv_basis"] == "scaled_order_lines"
    assert row["line_gmv"] == 8_680_000 and row["line_orders"] == 90
