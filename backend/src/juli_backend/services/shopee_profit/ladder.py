"""Decision #44: the profit ladder of a scope, evaluated by the metric registry (no formula here).

Doanh thu thực → Lợi nhuận gộp (− giá vốn − đóng gói) → Lợi nhuận đóng góp (− phí sàn − vận
chuyển ròng; the card basis) → Lợi nhuận ròng (− QC − AFF − marketing khác). The three margins
are ÷ doanh thu thực, ROI = lợi nhuận ròng ÷ Tổng chi phí (``cost_total``).

The components come from the scope's **covered** order lines (every cost known, outside the
profit base excluded: the same lines as ``shop_profit``): ``net_revenue_known`` = revenue after
VAT, ``cogs`` = giá vốn less the input VAT credited, ``shipping_net`` = the income export's other
costs, ``affiliate_commission`` the lines' commission, the three offers the lines' discounts. The
ads spend and the other marketing are the scope's (the caller's resolver), and the shown profit is
handed in as a value, so the ladder ends on the very figure the screen shows.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from juli_backend.services.metrics.compute import _Context
from juli_backend.services.shopee_profit.money import ZERO
from juli_backend.services.shopee_profit.order_profit import OrderLine, ProfitBreakdown

#: the registry ids a ladder answers (``Ladder.get``)
LADDER_METRICS = (
    "gross_profit",
    "contribution",
    "profit",
    "margin_gross",
    "margin_contribution",
    "margin",
    "cost_cogs",
    "cost_packaging",
    "cost_fees",
    "cost_shipping",
    "cost_ads",
    "cost_affiliate",
    "cost_offers",
    "cost_other",
    "cost_marketing",
    "cost_total",
    "roi",
)


@dataclass(frozen=True)
class Ladder:
    components: dict[str, Decimal | None]
    values: dict[str, Decimal | None]

    def get(self, metric_id: str) -> Decimal | None:
        return self.values.get(metric_id)


def components_of(pairs: Iterable[tuple[OrderLine, ProfitBreakdown]]) -> dict[str, Decimal]:
    """The covered lines' ladder components (whole-window sums)."""
    c = dict.fromkeys(
        (
            "net_revenue_known",
            "cogs",
            "packaging",
            "fees",
            "shipping_net",
            "affiliate_commission",
            "offer_promo",
            "offer_voucher",
            "offer_combo",
        ),
        ZERO,
    )
    for _, pb in pairs:
        if pb.excluded_reason is not None or pb.contribution is None:
            continue
        c["net_revenue_known"] += pb.revenue
        c["cogs"] += (pb.cogs or ZERO) - pb.vat_input_credit
        c["packaging"] += pb.packaging or ZERO
        c["fees"] += pb.fees_total or ZERO
        c["shipping_net"] += pb.income_costs_total or ZERO
        c["affiliate_commission"] += pb.commission or ZERO
        c["offer_promo"] += pb.promo_discount
        c["offer_voucher"] += pb.voucher_borne or ZERO  # what the seller bore (settlement)
        c["offer_combo"] += pb.bundle
    return c


def ladder_of(
    pairs: Iterable[tuple[OrderLine, ProfitBreakdown]],
    *,
    ads_spend: Decimal | None,
    other_marketing: Decimal | None = ZERO,
    profit: Decimal | None = None,
) -> Ladder:
    """The scope's ladder. ``profit`` (the shown Lợi nhuận ròng) wins over the registry's own
    difference when given, so the ROI and the margin end on the screen's figure."""
    comps: dict[str, Decimal | None] = dict(components_of(pairs))
    comps["ads_spend"] = ads_spend
    comps["other_marketing"] = other_marketing
    ctx = _Context(comps, None, {})
    if profit is not None:
        ctx.memo["profit"] = profit
    values: dict[str, Decimal | None] = {}
    for m in LADDER_METRICS:
        v = ctx.ref(m)
        values[m] = v if isinstance(v, Decimal) else None
    return Ladder(comps, values)


__all__ = ["LADDER_METRICS", "Ladder", "components_of", "ladder_of"]
