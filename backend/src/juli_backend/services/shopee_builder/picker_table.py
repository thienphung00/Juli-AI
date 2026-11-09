"""P97 D85.12: the extra columns and filters of the table picker.

One table serves every kind of the builder: besides the catalogue columns (``catalogue.picker``)
a row carries what the filters need -- ngành hàng, biên (profit / buyer paid of the last 30 days),
CTOR of the last 30 days against the 30 days before it, whether the product has a proposal waiting,
and whether it runs Quảng cáo or KOL / Affiliate orders. Everything is read from views the builder
already loads; a figure that cannot be known is ``None`` (a filter never matches it), never 0.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from decimal import Decimal
from typing import Any

from juli_backend.services.shopee_analytics.compute import PeriodView
from juli_backend.services.shopee_profit.money import ZERO

#: a CTOR that fell by at least this share of the earlier one is "giảm"
CTOR_DROP_SHARE = 0.05


def _ctor_by_item(view: PeriodView | None) -> dict[str, float]:
    """item -> orders / clicks over the view's window, for items with flow clicks."""
    if view is None or view.flows is None:
        return {}
    out: dict[str, float] = {}
    for item, table in view.flows.products.items():
        orders = sum(int(r.orders) for r in table.rows if not r.is_residual)
        clicks = sum(int(r.clicks or 0) for r in table.rows if not r.is_residual)
        if clicks > 0:
            out[item] = orders / clicks
    return out


def _margin_by_item(view: PeriodView) -> dict[str, float]:
    profit: dict[str, Decimal] = defaultdict(lambda: ZERO)
    paid: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for ln, pb in view.pairs:
        if pb.profit is None or pb.buyer_paid <= 0:
            continue
        profit[ln.product_id] += pb.profit
        paid[ln.product_id] += pb.buyer_paid
    return {i: float(profit[i] / paid[i] * 100) for i in paid if paid[i] > 0}


def extras(
    view30: PeriodView,
    prev30: PeriodView | None,
    *,
    proposal_items: Iterable[str] = (),
) -> dict[str, dict[str, Any]]:
    """item id -> the filter columns, over the items the 30-day view knows."""
    margin = _margin_by_item(view30)
    now, before = _ctor_by_item(view30), _ctor_by_item(prev30)
    ads = {i for i, v in view30.ads.product_spend.items() if v > 0}
    kol: set[str] = set()
    for ln, _ in view30.pairs:
        if ln.ad_attributed:
            ads.add(ln.product_id)
        if ln.affiliate:
            kol.add(ln.product_id)
    kol |= set(view30.data.affiliate.product_commission)
    waiting = set(proposal_items)
    out: dict[str, dict[str, Any]] = {}
    for item in set(margin) | set(now) | ads | kol | waiting:
        c_now, c_before = now.get(item), before.get(item)
        down = (
            None if c_now is None or c_before is None else c_now < c_before * (1 - CTOR_DROP_SHARE)
        )
        out[item] = {
            "margin_pct": None if item not in margin else round(margin[item], 1),
            "ctor_30d": None if c_now is None else round(c_now * 100, 2),
            "ctor_prev_30d": None if c_before is None else round(c_before * 100, 2),
            "ctor_down": down,
            "has_proposal": item in waiting,
            "in_ads": item in ads,
            "in_kol": item in kol,
        }
    return out


def blank() -> Mapping[str, Any]:
    """A row with no 30-day figures at all (every filter column unknown / false)."""
    return {
        "margin_pct": None,
        "ctor_30d": None,
        "ctor_prev_30d": None,
        "ctor_down": None,
        "has_proposal": False,
        "in_ads": False,
        "in_kol": False,
    }


__all__ = ["CTOR_DROP_SHARE", "blank", "extras"]
