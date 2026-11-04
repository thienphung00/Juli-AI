"""Which GMV a product row reports: Shopee's product-period total or the order lines (pure)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from juli_backend.services.shopee_analytics import matrix
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


def _view(pf: ProductFlows, lines: OrderLinesLoad) -> SimpleNamespace:
    line_total = SimpleNamespace(gmv=Decimal(8_680_000), orders=90)
    return SimpleNamespace(
        profit=SimpleNamespace(products={}),
        matrix=SimpleNamespace(lever={}, totals={PID: line_total}),
        flows=None,
        data=SimpleNamespace(product_flows=pf, lines=lines),
        names={PID: "Sản phẩm mẫu"},
    )


@pytest.fixture(autouse=True)
def _no_overlays(monkeypatch):
    monkeypatch.setattr(matrix, "ads_overlay", lambda *a, **k: {"spend": 0})
    monkeypatch.setattr(matrix, "card_children", lambda *a, **k: None)


def test_order_lines_covered_days_clip_the_export_span_to_the_window():
    assert _lines(date(2026, 10, 9), date(2026, 11, 20), 20).covered_days == 25
    assert _lines(date(2026, 9, 1), date(2026, 12, 1), 20).covered_days == 30
    assert OrderLinesLoad([], WINDOW, 7, None).covered_days == 7


def test_three_days_of_product_data_lose_to_24_days_of_order_lines():
    view = _view(_flows(3, "contained"), _lines(date(2026, 10, 9), date(2026, 11, 2), 24))
    row = matrix.product_row(view, PID)
    assert row["gmv_basis"] == "order_lines"
    assert row["gmv"] == 8_680_000
    assert row["orders"] == 90
    assert product_totals_for(view.data.product_flows, view.data.lines) == {}


def test_a_product_period_covering_the_window_keeps_the_shopee_basis():
    view = _view(_flows(30, "exact"), _lines(date(2026, 10, 9), date(2026, 11, 2), 24))
    row = matrix.product_row(view, PID)
    assert row["gmv_basis"] == "shopee_product_period"
    assert row["gmv"] == 2_450_000
    assert row["orders"] == 31
    assert row["line_gmv"] == 8_680_000


def test_equal_coverage_and_no_order_lines_prefer_the_shopee_totals():
    same = _view(_flows(3, "contained"), _lines(date(2026, 10, 31), date(2026, 11, 2), 3))
    assert matrix.product_row(same, PID)["gmv_basis"] == "shopee_product_period"
    none = _view(_flows(3, "contained"), OrderLinesLoad([], WINDOW))
    assert matrix.product_row(none, PID)["gmv_basis"] == "shopee_product_period"
