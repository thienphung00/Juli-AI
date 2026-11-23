"""Registry metrics over values Chat already holds. No formula lives here: the registry's own
expression is evaluated; only a derived input (`contribution`, defined by the registry as profit
before ads) is handed in as a value."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from juli_backend.services.metrics.compute import _Context


def roas_break_even(net_revenue_known: Any, contribution: Any) -> float | None:
    """`roas_break_even` = net_revenue_known / contribution (registry); None when either is
    missing or the contribution is not positive."""
    if net_revenue_known is None or contribution is None:
        return None
    ctx = _Context({"net_revenue_known": Decimal(str(net_revenue_known))}, None, {})
    ctx.memo["contribution"] = Decimal(str(contribution))
    v = ctx.ref("roas_break_even")
    return float(v) if isinstance(v, Decimal) and v > 0 else None


def roas_direct(ads_gmv_direct: Any, cost_ads: Any) -> float | None:
    """`roas_direct` = ads_gmv_direct / cost_ads (registry); `cost_ads` is a derived metric there,
    handed in as a value."""
    if ads_gmv_direct is None or cost_ads is None:
        return None
    ctx = _Context({"ads_gmv_direct": Decimal(str(ads_gmv_direct))}, None, {})
    ctx.memo["cost_ads"] = Decimal(str(cost_ads))
    v = ctx.ref("roas_direct")
    return float(v) if isinstance(v, Decimal) else None
