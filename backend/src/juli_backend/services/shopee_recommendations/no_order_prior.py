"""S5 (Q8): the prior of an affiliate / KOC card on a product with no orders in the window.

With no order of its own a product has nothing to scale a commission change from. The card is
estimated on a prior instead (owner 23/11: uplift only): the card's gain is
``config.NO_ORDER_UPLIFT`` (5 %) of ``baseline_orders``, over a base of 0 orders; the baseline
volume itself is never claimed. Per-order economics come from the shop as a whole.

``baseline_orders`` is the ONE place the baseline comes from; swap it to change the source.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from statistics import median

from juli_backend.services.shopee_profit.money import ZERO, safe_div
from juli_backend.services.shopee_recommendations import config
from juli_backend.services.shopee_recommendations.env import RecoEnv


@dataclass(frozen=True)
class OrderPrior:
    orders: Decimal  # the card's GAIN in orders over the window: baseline x uplift (base is 0)
    baseline: Decimal
    uplift: Decimal
    aov: Decimal  # the shop's order value per order
    profit_per_gmv: Decimal | None  # the shop's contribution per đồng of revenue

    def json(self) -> dict[str, object]:
        return {
            "basis": "shop_median_orders_per_product",
            "baseline_orders": float(self.baseline),
            "uplift": float(self.uplift),
            "gain_orders": float(self.orders),
        }


def baseline_orders(env: RecoEnv, item: str) -> Decimal | None:
    """The shop's median orders per product that sold in the window (None: nothing sold)."""
    del item  # this source is shop-wide; another source may use the product
    counts = [n for i in env.item_ids() if (n := env.orders_of(i)) > 0]
    return Decimal(str(median(counts))) if counts else None


def order_prior(env: RecoEnv, item: str) -> OrderPrior | None:
    """The prior of a product with no orders; None when the shop has no sale to build it from."""
    baseline = baseline_orders(env, item)
    if baseline is None:
        return None
    pairs = [(ln, pb) for ln, pb in env.sales_pairs if pb.excluded_reason is None]
    orders = len({ln.order_id for ln, _ in pairs})
    gmv = sum((ln.order_value for ln, _ in pairs), ZERO)
    aov = safe_div(gmv, Decimal(orders)) if orders else None
    if not aov:
        return None
    revenue = sum((pb.revenue for _, pb in pairs if pb.contribution is not None), ZERO)
    contribution = sum((pb.contribution or ZERO for _, pb in pairs), ZERO)
    uplift = Decimal(str(config.NO_ORDER_UPLIFT))
    return OrderPrior(
        orders=baseline * uplift,
        baseline=baseline,
        uplift=uplift,
        aov=aov,
        profit_per_gmv=safe_div(contribution, revenue) if revenue > 0 else None,
    )
