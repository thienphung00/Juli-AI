"""Contract: Ưu đãi as a COST counts known orders only, so Tổng chi phí is the sum of the rows
shown beside it, for the shop and for one product, on the screen figures and in the export.
Synthetic lines only (one order is partly unknown)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from juli_backend.services.exports import collect
from juli_backend.services.shopee_analytics import channel_split
from juli_backend.services.shopee_profit.ladder import affiliate_cost, ladder_of

D = Decimal


def _pair(order: str, product: str, known: bool, aff: bool = False) -> tuple[Any, Any]:
    ln = SimpleNamespace(
        order_id=order, affiliate=aff, product_id=product, sku=product, order_value=D(200),
        status="x", order_date=date(2026, 11, 20),
    )  # fmt: skip
    c = D(100) if known else None
    pb = SimpleNamespace(
        excluded_reason=None, contribution=c, organic_contribution=c, revenue=D(200),
        cogs=D(50), vat_input_credit=D(0), packaging=D(5), fees_total=D(10),
        income_costs_total=D(5), commission=D(7) if aff else D(0), promo_discount=D(11),
        voucher=D(3), bundle=D(1), offer_cost=D(15),
    )  # fmt: skip
    return ln, pb


# o1 spans p1 (known line) and p2 (UNKNOWN line): the whole order is out; o2, o3 fully known
PAIRS = [
    _pair("o1", "p1", True),
    _pair("o1", "p2", False),
    _pair("o2", "p1", True, aff=True),
    _pair("o3", "p2", True),
]
VIEW: Any = SimpleNamespace(pairs=PAIRS)


def _kpis(product: str | None) -> dict[str, Any]:
    pairs = [(ln, pb) for ln, pb in PAIRS if product is None or ln.product_id == product]
    ads, other = D(40), D(0)
    ladder = ladder_of(pairs, ads_spend=ads, other_marketing=other, basis=PAIRS)
    return channel_split.kpis_of(
        D(1000),
        D(3),
        D(0),
        ads,
        affiliate_cost(pairs, basis=PAIRS),
        channel_split._offers_cost(VIEW, product),
        ladder,
    )


def _check(k: dict[str, Any]) -> None:
    ads, aff, offers = (D(str(k[x])) for x in ("cost_ads", "cost_affiliate", "cost_offers"))
    assert D(str(k["cost_marketing"])) == ads + aff + offers
    parts = sum(D(str(k[x])) for x in ("cost_cogs", "cost_packaging", "cost_fees", "cost_shipping"))
    assert D(str(k["cost_total"])) == parts + ads + aff + offers  # other_marketing is 0 here


def test_shop_parts_add_up_to_the_total() -> None:
    k = _kpis(None)
    assert D(str(k["cost_offers"])) == D(30)  # o2 + o3 only; o1 (partly unknown) is out
    _check(k)


def test_one_product_parts_add_up_to_the_total() -> None:
    k = _kpis("p1")
    assert D(str(k["cost_offers"])) == D(15)  # o2 only: o1 is out although p1's line is known
    _check(k)


def test_export_offers_follow_the_screen() -> None:
    assert collect._offer_cost(VIEW, None) == float(_kpis(None)["cost_offers"])
    assert collect._offer_cost(VIEW, "p1") == float(_kpis("p1")["cost_offers"])
    assert collect._offer_cost(VIEW, "p1", date(2026, 11, 20)) == 15.0


def test_channel_rows_offers_known_orders_only() -> None:
    assert channel_split._sums(PAIRS, PAIRS)["cost_offers"] == D(30)
