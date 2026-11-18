"""A8: the loader's read -> StockRead mapping (GMT+7 day) and the FunnelRows default."""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

from juli_backend.services.shopee_analytics import funnel
from juli_backend.services.shopee_analytics.windows import Window


def _h(item, model, at, sellable, status="active", available=None):
    return SimpleNamespace(
        item_id=item,
        variation_id=model,  # stock_history.variation_id (model_id until 134)
        read_at=at,
        sellable=sellable,
        available=available,
        listing_status=status,
    )


def test_the_default_field_keeps_every_existing_constructor_call_working():
    rows = funnel.FunnelRows(Window(date(2026, 11, 1), date(2026, 11, 2)))
    assert dict(rows.unavailable) == {}


def test_reads_become_local_days_and_unavailable_sets():
    # 20:00 UTC on 11-14 is 03:00 GMT+7 on 11-15
    hist = [
        _h("A", "m1", datetime(2026, 11, 14, 20), 0),
        _h("A", "m2", datetime(2026, 11, 14, 20), 0),
        _h("B", "", datetime(2026, 11, 14, 2), 5, "unlisted"),
        _h("C", "", datetime(2026, 11, 14, 2), 5),
    ]
    got = funnel.unavailable_from_history(hist, Window(date(2026, 11, 14), date(2026, 11, 16)))
    assert got == {"A": frozenset({date(2026, 11, 15)}), "B": frozenset({date(2026, 11, 14)})}


def test_reads_outside_the_window_are_ignored():
    hist = [_h("A", "", datetime(2026, 11, 1, 2), 0)]
    assert (
        funnel.unavailable_from_history(hist, Window(date(2026, 11, 14), date(2026, 11, 16))) == {}
    )


def test_kho_hang_available_stock_wins_over_prepared_sellable():
    # a shop without "Gói Sẵn Giao Nhanh": sellable is 0 on every read, Kho hàng holds the stock
    at = datetime(2026, 11, 15, 2)
    hist = [
        _h("A", "m1", at, 0, available=7),  # in stock in Kho hàng -> available
        _h("B", "", at, 0, available=0),  # 0 in Kho hàng -> out of stock
        _h("C", "", at, 5, available=0),  # Kho hàng wins over a prepared figure
        _h("D", "", at, 0),  # no Kho hàng figure -> sellable is the basis
    ]
    got = funnel.unavailable_from_history(hist, Window(date(2026, 11, 14), date(2026, 11, 16)))
    day = frozenset({date(2026, 11, 15)})
    assert got == {"B": day, "C": day, "D": day}
