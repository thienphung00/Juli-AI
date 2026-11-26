"""F2: the adaptive window, missing days and the stale marker of the Shopee forecast base."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from juli_backend.services.shopee_analytics.forecast_base import (
    adaptive_base,
    last_days,
    stale_marker,
)
from juli_backend.services.shopee_analytics.funnel import FunnelRows, ScopeDay, SourceDay
from juli_backend.services.shopee_analytics.windows import Window

END = date(2026, 11, 10)


def _rows(days: int, orders_per_day: int, last_day: date = END, window_days: int = 60):
    window = Window(END - timedelta(days=window_days - 1), END)
    src, shop = [], []
    for i in range(window_days):
        day = END - timedelta(days=i)
        if day > last_day or i >= days:
            continue
        shop.append(ScopeDay(day, None, orders_per_day, Decimal(orders_per_day * 100), Decimal(10)))
        src.append(
            SourceDay(
                day, None, "the_san_pham_khac", 1000, 100, orders_per_day,
                Decimal(orders_per_day * 100), Decimal(10),
            )
        )  # fmt: skip
    return FunnelRows(window, tuple(src), tuple(shop), ())


def test_the_shortest_window_with_enough_events_is_used():
    # 5 orders a day: 14 days = 70 >= 30 events
    base = adaptive_base(_rows(60, 5), "s")
    assert dict(base.windows) == {"views": 14, "ctr": 14, "ctor": 14, "aov": 14}
    assert base.low_data == ()
    # the base is 30 days of the daily rate: 5 x 30 orders, 100 clicks x 30 / day
    assert base.total("orders") == Decimal(150)
    assert base.window_days == 30


def test_a_thin_shop_widens_the_window_then_falls_back_to_60_days():
    # 1 order a day: 14 -> 14, 30 -> 30 events: 30 days qualifies
    assert dict(adaptive_base(_rows(60, 1), "s").windows)["ctor"] == 30
    # owner 2026-11-16: 20 orders never reach 30 events -> the 60-day window anyway, not low data
    thin = adaptive_base(_rows(20, 1), "s")
    assert dict(thin.windows)["ctor"] == 60
    assert "ctor" not in thin.low_data and "aov" not in thin.low_data


def test_days_after_the_last_data_day_are_missing_not_zero():
    # data stops 3 days before the window end: F1: 27 real days, said as 27/30, never filled in
    rows = _rows(60, 5, last_day=END - timedelta(days=3))
    base = adaptive_base(rows, "s")
    assert base.total("orders") == Decimal(135)
    assert (base.days, base.window_days) == (27, 30)
    assert set(dict(base.daily)["orders"]) == {5.0}  # no zero day in the rates' history
    assert last_days(rows).orders == END - timedelta(days=3)


def test_stale_marker_follows_the_expected_lag_plus_two_days():
    last = last_days(_rows(60, 5, last_day=END))
    assert stale_marker(last, END + timedelta(days=2)) is None  # orders lag 0 + 2
    marker = stale_marker(last, END + timedelta(days=3))
    assert marker is not None and marker.dataset == "orders" and marker.through == END
    assert stale_marker(last, None) is None
    base = adaptive_base(_rows(60, 5), "s", today=END + timedelta(days=5))
    assert base.stale is not None and base.stale.through == END
