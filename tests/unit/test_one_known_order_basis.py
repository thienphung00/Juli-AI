"""One known-order basis: net_revenue_known, cogs, the costs, gross / contribution / net, their
margins, Tổng chi phí and ROI all use WHOLE known orders (an order with any counted unknown line
is out), the rule of known_cost_profit. Synthetic lines only."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from juli_backend.services.shopee_analytics import channel_split
from juli_backend.services.shopee_profit.ladder import components_of, ladder_of

D = Decimal


def _pair(order: str, known: bool, rev: int = 200, aff: bool = False) -> tuple[Any, Any]:
    ln = SimpleNamespace(
        order_id=order, affiliate=aff, product_id="p1", sku="s", order_value=D(rev), status="x"
    )
    c = D(rev) / 2 if known else None
    pb = SimpleNamespace(
        excluded_reason=None, contribution=c, organic_contribution=c, revenue=D(rev),
        cogs=D(50), vat_input_credit=D(0), packaging=D(5), fees_total=D(10),
        income_costs_total=D(5), commission=D(7), promo_discount=D(1), voucher=D(2),
        bundle=D(0), offer_cost=D(3),
    )  # fmt: skip
    return ln, pb


# o1: one known line + one UNKNOWN line (the whole order is out); o2: fully known
MIXED = [_pair("o1", True), _pair("o1", False), _pair("o2", True)]
ONLY_O2 = [_pair("o2", True)]


def test_components_exclude_the_whole_mixed_order() -> None:
    assert components_of(MIXED) == components_of(ONLY_O2)
    assert components_of(MIXED)["net_revenue_known"] == D(200)


def test_a_slice_reads_the_orders_from_the_basis() -> None:
    slice_ = [MIXED[0]]  # only o1's known line
    assert components_of(slice_)["net_revenue_known"] == D(200)  # alone it looks fully known
    assert components_of(slice_, basis=MIXED)["net_revenue_known"] == D(0)


def test_every_level_shares_the_order_set() -> None:
    a = ladder_of(MIXED, ads_spend=D(10), other_marketing=D(0), profit=None)
    b = ladder_of(ONLY_O2, ads_spend=D(10), other_marketing=D(0), profit=None)
    assert a.values == b.values and a.get("cost_total") is not None


def test_channel_split_sums_use_the_same_orders() -> None:
    a = channel_split._sums(MIXED)
    b = channel_split._sums(ONLY_O2)
    assert a["net_revenue"] == b["net_revenue"] and a["contribution"] == b["contribution"]
    sliced = channel_split._sums([MIXED[0]], MIXED)
    assert sliced["net_revenue"] == D(0) and sliced["contribution"] == D(0)


def test_fully_known_orders_are_unchanged() -> None:
    full = [_pair("a", True), _pair("b", True, aff=True)]
    assert components_of(full)["net_revenue_known"] == D(400)
