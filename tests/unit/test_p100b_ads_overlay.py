"""P100 B.4a/b: the day's "trong đó Quảng cáo" overlay of Thẻ sản phẩm (materialize).

ORY 11/10-09/11 showed Thẻ sản phẩm (organic) at −24 đơn: the overlay's placed orders were
subtracted from the sources' confirmed orders. Pure; synthetic rows.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from juli_backend.services.shopee_analytics.materialize import ads_overlay

D = Decimal
DAY = date(2026, 11, 10)


def _r(order_type, segment="all", *, impressions=None, clicks=None, orders=None, gmv=None, cost=0):
    return SimpleNamespace(
        order_type=order_type,
        segment=segment,
        impressions=None if impressions is None else D(impressions),
        clicks=None if clicks is None else D(clicks),
        orders=None if orders is None else D(orders),
        gmv=None if gmv is None else D(gmv),
        extra={"ads_expense": cost},
    )


def test_the_confirmed_ads_row_is_used_so_it_matches_the_sources_basis():
    rows = [
        _r("placed", impressions=4000, clicks=120, orders=30, gmv=3_000_000, cost=500_000),
        _r("confirmed", impressions=4000, clicks=120, orders=24, gmv=2_400_000),
    ]
    a = ads_overlay(rows, [])
    assert a is not None
    assert (a.views, a.clicks, a.orders, a.gmv) == (4000, 120, 24, D(2_400_000))
    assert a.spend == D(500_000)


def test_placed_only_is_put_on_the_confirmed_basis_by_the_card_ratio():
    rows = [_r("placed", impressions=4000, orders=30, gmv=3_000_000)]
    card = [_r("placed", orders=50, gmv=5_000_000), _r("confirmed", orders=40, gmv=4_500_000)]
    a = ads_overlay(rows, card)
    assert a is not None and a.orders == 24 and a.gmv == D(2_700_000)


def test_placed_only_without_a_card_ratio_stays_as_read():
    a = ads_overlay([_r("placed", impressions=10, orders=3, gmv=300)], [])
    assert a is not None and a.orders == 3 and a.gmv == D(300)


def test_the_overlay_never_borrows_clicks_from_another_report():
    """P100 B.4a (owner, 2026-11-14): one basis per CTR. The stored overlay keeps its own views
    and clicks; the Quảng cáo row takes BOTH from the ads report at read time (channel_split)."""
    a = ads_overlay([_r("placed", impressions=4000, orders=3, gmv=300)], [])
    assert a is not None and a.views == 4000 and a.clicks is None


def test_the_types_are_not_added_to_their_own_total():
    rows = [
        _r("placed", impressions=4000, clicks=100, orders=30, gmv=3_000, cost=50),
        _r("placed", "ads_roas_custom", impressions=3000, clicks=80, orders=20, gmv=2_000, cost=30),
        _r("placed", "ads_shop", impressions=1000, clicks=20, orders=10, gmv=1_000, cost=20),
    ]
    a = ads_overlay(rows, [])
    assert a is not None and (a.views, a.orders, a.spend) == (4000, 30, D(50))
    only_types = ads_overlay(rows[1:], [])
    assert only_types is not None and (only_types.views, only_types.orders) == (4000, 30)


def test_no_rows_no_overlay():
    assert ads_overlay([], []) is None
