"""C1 (owner 2026-11-19): a day without product traffic rows is unavailable, not 0 views."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from juli_backend.services.shopee_analytics.forecast_base import MIN_TRAFFIC_DAYS, adaptive_base
from juli_backend.services.shopee_analytics.funnel import FunnelRows, ScopeDay, SourceDay
from juli_backend.services.shopee_analytics.windows import Window

END = date(2026, 11, 10)
DAYS = 14


def _day(ago: int) -> date:
    return END - timedelta(days=ago)


def _rows(missing: frozenset[int], zero_views: frozenset[int] = frozenset()) -> FunnelRows:
    """14 days of one product: 1000 views, 100 clicks, 5 orders a day on days with a traffic row;
    on the ``missing`` days only orders (50, deliberately large) and no views / clicks."""
    product, shop = [], []
    for i in range(DAYS):
        day = _day(i)
        if i in missing:
            product.append(ScopeDay(day, "A", 50, Decimal(5000), Decimal(50)))
        elif i in zero_views:
            product.append(ScopeDay(day, "A", 0, Decimal(0), Decimal(0), 0, 0))
        else:
            product.append(ScopeDay(day, "A", 5, Decimal(500), Decimal(5), 1000, 100))
        shop.append(ScopeDay(day, None, 60, Decimal(6000), Decimal(60)))
    return FunnelRows(Window(_day(DAYS - 1), END), (), tuple(shop), tuple(product))


def test_t3_1_missing_days_are_unavailable_the_rate_is_the_mean_of_the_present_days():
    base = adaptive_base(_rows(frozenset(range(6))), "s", item_ids=("A",))
    # 8 present days x 1000 views -> 1000 a day -> 30 000 over the 30-day base (not 8/14 of it)
    assert base.total("views") == Decimal(30000)
    assert base.total("clicks") == Decimal(3000)
    assert base.total("orders") == Decimal(150)


def test_t3_2_a_row_with_zero_views_is_a_real_zero_day():
    base = adaptive_base(_rows(frozenset(range(6)), frozenset({8, 9})), "s", item_ids=("A",))
    # 8 present days, 2 of them real zeros: 6000 views / 8 days = 750 a day
    assert base.total("views") == Decimal(22500)


def test_t3_3_too_few_available_days_is_not_estimable():
    assert MIN_TRAFFIC_DAYS == 5
    base = adaptive_base(_rows(frozenset(range(DAYS - 4))), "s", item_ids=("A",))
    assert base.total("views") is None and base.total("clicks") is None
    assert "ctr" in base.low_data and "ctor" in base.low_data


def test_t3_4_the_shop_scope_reads_shop_rows_unchanged():
    src = tuple(
        SourceDay(_day(i), None, "the_san_pham_khac", 1000, 100, 5, Decimal(500), Decimal(5))
        for i in range(DAYS)
    )
    shop = tuple(ScopeDay(_day(i), None, 5, Decimal(500), Decimal(5)) for i in range(DAYS))
    # product rows carry traffic on 3 days only: irrelevant to the shop scope
    product = tuple(ScopeDay(_day(i), "A", 1, Decimal(100), Decimal(1), 10, 1) for i in range(3))
    rows = FunnelRows(Window(_day(DAYS - 1), END), src, shop, product)
    base = adaptive_base(rows, "s")
    assert base.total("views") == Decimal(30000)
    assert base.total("orders") == Decimal(150)


def test_orders_of_a_day_without_traffic_rows_do_not_enter_ctor():
    base = adaptive_base(_rows(frozenset(range(6))), "s", item_ids=("A",))
    # CTOR = 5 / 100 on the present days; the 6 missing days' 300 orders must not inflate it
    assert base.total("orders") / base.total("clicks") == Decimal("0.05")
