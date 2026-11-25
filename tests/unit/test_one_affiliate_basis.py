"""One affiliate basis: the orders whose every counted line has its costs (the orders Lợi nhuận
ròng uses). An affiliate line of an order with another unknown line is in no reader's sum.
Synthetic lines only."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from juli_backend.services.shopee_analytics import channel_split
from juli_backend.services.shopee_profit.ladder import affiliate_cost


def _pair(
    order: str, *, affiliate: bool, commission: str, known: bool, status: str = "delivered"
) -> tuple[Any, Any]:
    ln = SimpleNamespace(
        order_id=order,
        affiliate=affiliate,
        product_id="p1",
        sku="s",
        order_value=Decimal(200),
        status=status,
    )
    c = Decimal("100") if known else None
    pb = SimpleNamespace(
        excluded_reason=None,
        contribution=c,
        organic_contribution=c,
        commission=Decimal(commission),
        revenue=Decimal(200),
        offer_cost=Decimal(0),
    )
    return ln, pb


# o1: one known affiliate line (commission 10) + one UNKNOWN line; o2: fully known (commission 5)
PAIRS = [
    _pair("o1", affiliate=True, commission="10", known=True),
    _pair("o1", affiliate=False, commission="0", known=False),
    _pair("o2", affiliate=True, commission="5", known=True),
]


def test_affiliate_cost_counts_only_orders_with_every_line_known() -> None:
    assert affiliate_cost(PAIRS) == Decimal(5)


def test_a_slice_of_affiliate_lines_reads_the_orders_from_the_basis() -> None:
    aff_only = [(ln, pb) for ln, pb in PAIRS if ln.affiliate]
    assert affiliate_cost(aff_only) == Decimal(15)  # the slice alone cannot see o1's unknown line
    assert affiliate_cost(aff_only, basis=PAIRS) == Decimal(5)


def test_channel_split_ttlk_cost_is_the_same_sum() -> None:
    out = channel_split.split_scope(PAIRS, ads_gmv=None, ads_spend=None, basis=PAIRS)
    assert out["affiliate"]["cost_affiliate"] == affiliate_cost(PAIRS) == Decimal(5)


def test_no_known_affiliate_order_is_none() -> None:
    only_unknown = [PAIRS[0], PAIRS[1]]
    assert affiliate_cost(only_unknown) is None
