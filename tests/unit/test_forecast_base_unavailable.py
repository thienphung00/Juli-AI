"""F2 (owner, forecast grill 2026-11-16): out-of-stock and unlisted days of a product leave its
forecast base, the same way a missing day does."""

from __future__ import annotations

import ast
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from juli_backend.services.shopee_analytics import unavailable_days as ud
from juli_backend.services.shopee_analytics.forecast_base import adaptive_base
from juli_backend.services.shopee_analytics.funnel import FunnelRows, ScopeDay
from juli_backend.services.shopee_analytics.windows import Window

END = date(2026, 11, 10)
DAYS = 30


def _day(ago: int) -> date:
    return END - timedelta(days=ago)


def _rows(
    items=("A",),
    unavailable: dict[str, frozenset[date]] | None = None,
    *,
    per_day: int = 3,
    zero_on: frozenset[date] = frozenset(),
) -> FunnelRows:
    """30 days of ``per_day`` orders per product per day (0 on ``zero_on``), plus shop days."""
    window = Window(_day(DAYS - 1), END)
    product, shop = [], []
    for i in range(DAYS):
        day = _day(i)
        n = 0 if day in zero_on else per_day
        for item in items:
            product.append(ScopeDay(day, item, n, Decimal(n * 100), Decimal(n), n * 50, n * 5))
        total = per_day * len(items)  # the shop keeps selling other products
        shop.append(ScopeDay(day, None, total, Decimal(total * 100), Decimal(total)))
    extra = {} if unavailable is None else {"unavailable": unavailable}
    return FunnelRows(window, (), tuple(shop), tuple(product), **extra)


TEN = frozenset(_day(i) for i in range(10))


def test_a1_ten_unavailable_days_leave_the_order_rate_denominator():
    rows = _rows(unavailable={"A": TEN}, zero_on=TEN)
    base = adaptive_base(rows, "s", item_ids=("A",))
    # 20 available days x 3 orders = 60 -> 3 a day -> 90 over the 30-day base (not 60)
    assert base.total("orders") == Decimal(90)
    assert dict(base.windows)["aov"] == 30


def test_a2_unlisted_days_are_excluded_the_same_way():
    reads = [
        ud.StockRead("A", "", _day(i), datetime(2026, 11, 1), 5, "unlisted" if i < 10 else "active")
        for i in range(30)
    ]
    unavailable = ud.unavailable_by_item(reads)
    assert unavailable == {"A": TEN}
    base = adaptive_base(_rows(unavailable=unavailable, zero_on=TEN), "s", item_ids=("A",))
    assert base.total("orders") == Decimal(90)


def test_a3_no_read_day_and_a_positive_read_are_not_unavailable():
    d1, d2, d3 = _day(1), _day(2), _day(3)
    reads = [
        ud.StockRead("A", "m1", d1, datetime(2026, 11, 9, 1), 0, "active"),
        ud.StockRead("A", "m2", d1, datetime(2026, 11, 9, 1), 4, "active"),  # sum 4 -> in stock
        ud.StockRead("A", "", d2, datetime(2026, 11, 8, 1), 0, "active"),
        ud.StockRead("A", "", d2, datetime(2026, 11, 8, 9), 2, "active"),  # one read > 0
        ud.StockRead("A", "", d3, datetime(2026, 11, 7, 1), None, "active"),  # unknown
    ]
    assert ud.unavailable_by_item(reads) == {}  # nothing; the day with no read is not listed
    out = ud.unavailable_by_item(
        [ud.StockRead("A", "m1", d1, datetime(2026, 11, 9, 1), 0, "active"),
         ud.StockRead("A", "m2", d1, datetime(2026, 11, 9, 1), 0, "active"),
         ud.StockRead("A", "", d3, datetime(2026, 11, 7, 1), None, "active")]
    )  # fmt: skip
    assert out == {"A": frozenset({d1})}  # all variations 0 -> out of stock; all-None day is not
    # a day without any read keeps its place in the base
    base = adaptive_base(_rows(unavailable={"A": frozenset({d1})}), "s", item_ids=("A",))
    assert base.total("orders") == Decimal(3) * 30  # 29 days x 3 over 29 days -> 3 a day


def test_a4_a_day_is_dropped_when_any_product_of_the_scope_is_unavailable():
    a_days = frozenset(_day(i) for i in range(0, 5))
    b_days = frozenset(_day(i) for i in range(3, 8))
    un = {"A": a_days, "B": b_days}
    assert ud.scope_unavailable(un, ("A", "B")) == a_days | b_days
    assert ud.scope_unavailable(un, ("A",)) == a_days
    assert ud.scope_unavailable(un, ()) == frozenset()
    rows = _rows(items=("A", "B"), unavailable=un, zero_on=a_days | b_days)
    base = adaptive_base(rows, "s", item_ids=("A", "B"))
    # 8 days dropped, 22 left, 6 orders a day (3 + 3) -> 6 x 30
    assert base.total("orders") == Decimal(180)
    # one product alone only loses its own 5 days
    assert adaptive_base(rows, "s", item_ids=("A",)).total("orders") == Decimal(90)


def test_a5_shop_scope_is_identical_with_and_without_unavailable_data():
    plain = adaptive_base(_rows(), "s")
    withdata = adaptive_base(_rows(unavailable={"A": TEN}), "s")
    assert plain == withdata


def test_a6_windows_count_only_available_days_and_all_unavailable_is_low_data():
    # 1 order a day; the newest 20 days are unavailable -> the 14 and 30 windows hold < 30 events
    recent = frozenset(_day(i) for i in range(20))
    rows = _rows(per_day=1, unavailable={"A": recent}, zero_on=recent)
    base = adaptive_base(rows, "s", item_ids=("A",))
    assert dict(base.windows)["aov"] == 60  # only 10 available days: no window reaches 30 events
    assert base.total("orders") == Decimal(30)  # 10 orders over 10 days -> 1 a day
    # every day unavailable -> no event at all -> ít dữ liệu, not a zero rate shown as data
    everything = frozenset(_day(i) for i in range(DAYS))
    gone = adaptive_base(
        _rows(unavailable={"A": everything}, zero_on=everything), "s", item_ids=("A",)
    )
    assert "ctor" in gone.low_data and "aov" in gone.low_data
    assert not gone.total("orders")


def test_a7_the_daily_series_omits_excluded_days():
    rows = _rows(unavailable={"A": TEN}, zero_on=TEN)
    base = adaptive_base(rows, "s", item_ids=("A",))
    series = dict(base.daily)
    assert len(series["orders"]) == 20 and len(series["gmv"]) == 20
    assert all(v == 3.0 for v in series["orders"])
    shop = dict(adaptive_base(rows, "s").daily)
    assert len(shop["orders"]) == 14  # shop scope keeps every day of its 14-day window


def test_a9_the_helper_imports_nothing_shopee_specific():
    src = Path(ud.__file__).read_text()
    names = []
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            names += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names.append(node.module or "")
    assert names
    assert all(
        n.split(".")[0] in {"__future__", "collections", "dataclasses", "datetime"} for n in names
    )
