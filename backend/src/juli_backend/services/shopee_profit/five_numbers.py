"""The five numbers (contract section 5) for a before/after pair, plus spend per day vs cap.

1. % giam gia = (khuyen mai discount + shop voucher + combo discount) / GMV at LIST price.
   VND = the same numerator. (Equals list value - buyer_paid.)
2. Doanh thu them / chi them = delta GMV / delta chi, chi = ads + voucher + khuyen mai + combo
   + affiliate commission. Shown "x d / 1d chi" and as % of the before-GMV; ``below_one`` is
   the red state (< 1d per 1d); when delta chi <= 0 the ratio is not shown and
   ``chi_status`` is ``"giam_chi"``.
3. Bien cuoi = profit / buyer_paid. Profit = contribution - ad spend - other costs (the shop
   profit definition of :mod:`.shop_profit`); with cost coverage < 100 % it is PARTIAL
   (covered lines only, never extrapolated) and ``margin_is_partial`` says so.
4. So don (confirmed orders). 5. AOV = GMV / orders (GMV = deal x qty before voucher).
6. Chi marketing / ngay vs tran: chi / days against the daily cap.

A :class:`Snapshot` holds already-summed period figures; ``orders`` and money may be
fractional when a what-if scales a window to a voucher's days or mixes states by an expected
usage fraction. Ad spend is the period total from the ads report (not the line-level split).
Percentages are percent points rounded to 0.1; undefined -> ``None``.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal

from juli_backend.services.shopee_profit.money import ONE, ZERO, pct_points, safe_div
from juli_backend.services.shopee_profit.order_profit import OrderLine, ProfitBreakdown


@dataclass(frozen=True)
class Snapshot:
    list_value: Decimal
    gmv: Decimal  # deal x qty, before the shop voucher
    buyer_paid: Decimal
    buyer_paid_covered: Decimal  # lines with every cost known
    orders: Decimal
    promo: Decimal  # khuyen mai discount
    voucher: Decimal  # shop voucher
    combo: Decimal  # combo / bundle discount
    commission: Decimal
    contribution: Decimal  # covered lines, before ads
    ad_spend: Decimal
    other_costs: Decimal = ZERO
    days: Decimal = ONE

    @property
    def chi(self) -> Decimal:
        return self.ad_spend + self.voucher + self.promo + self.combo + self.commission

    @property
    def discount(self) -> Decimal:
        return self.promo + self.voucher + self.combo

    @property
    def profit(self) -> Decimal | None:
        """None when no revenue has a known cost (nothing to be partial about)."""
        if self.buyer_paid_covered <= 0:
            return None
        return self.contribution - self.ad_spend - self.other_costs

    @property
    def margin_is_partial(self) -> bool:
        return self.buyer_paid_covered < self.buyer_paid

    @property
    def cost_coverage_pct(self) -> Decimal | None:
        return pct_points(safe_div(self.buyer_paid_covered, self.buyer_paid))


OrderGroup = Sequence[tuple[OrderLine, ProfitBreakdown]]


def snapshot_from_orders(
    weighted_orders: Iterable[tuple[Decimal, OrderGroup]],
    ad_spend: Decimal,
    *,
    other_costs: Decimal = ZERO,
    days: Decimal = ONE,
) -> Snapshot:
    """Snapshot from whole orders, each with a weight (1 = counted once; what-if mixes use
    fractions). A group is ALL lines of one order."""
    acc: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for w, group in weighted_orders:
        acc["orders"] += w
        for ln, pb in group:
            acc["list_value"] += w * pb.list_value
            acc["gmv"] += w * ln.order_value
            acc["buyer_paid"] += w * pb.buyer_paid
            acc["promo"] += w * pb.promo_discount
            acc["voucher"] += w * pb.voucher
            acc["combo"] += w * pb.bundle
            acc["commission"] += w * (pb.commission or ZERO)
            if pb.contribution is not None:
                acc["covered"] += w * pb.buyer_paid
                acc["contribution"] += w * pb.contribution
    return Snapshot(
        list_value=acc["list_value"],
        gmv=acc["gmv"],
        buyer_paid=acc["buyer_paid"],
        buyer_paid_covered=acc["covered"],
        orders=acc["orders"],
        promo=acc["promo"],
        voucher=acc["voucher"],
        combo=acc["combo"],
        commission=acc["commission"],
        contribution=acc["contribution"],
        ad_spend=ad_spend,
        other_costs=other_costs,
        days=days,
    )


def snapshot_from(
    pairs: Iterable[tuple[OrderLine, ProfitBreakdown]],
    ad_spend: Decimal,
    *,
    other_costs: Decimal = ZERO,
    days: Decimal = ONE,
) -> Snapshot:
    by_order: dict[str, list[tuple[OrderLine, ProfitBreakdown]]] = defaultdict(list)
    for ln, pb in pairs:
        by_order[ln.order_id].append((ln, pb))
    return snapshot_from_orders(
        ((ONE, g) for g in by_order.values()), ad_spend, other_costs=other_costs, days=days
    )


@dataclass(frozen=True)
class Pair:
    vnd_before: Decimal | None
    vnd_after: Decimal | None
    pct_before: Decimal | None
    pct_after: Decimal | None


@dataclass(frozen=True)
class SpendCap:
    spend: Decimal  # chi per day (after)
    cap: Decimal  # cap per day
    remaining: Decimal
    used_pct: Decimal | None
    over_cap: bool


@dataclass(frozen=True)
class FiveNumbers:
    discount: Pair  # VND = promo + voucher + combo ; % of list-price GMV
    extra_revenue: Decimal  # delta GMV
    extra_spend: Decimal  # delta chi
    extra_revenue_per_extra_spend: Decimal | None  # "x d / 1d chi"; None when chi did not rise
    extra_revenue_pct: Decimal | None  # delta GMV / GMV before
    chi_status: str  # "per_vnd" | "giam_chi" | "undefined"
    below_one: bool  # red: < 1d of GMV per 1d of chi
    margin: Pair  # VND profit ; % of buyer_paid (covered lines when partial)
    margin_is_partial: bool
    cost_coverage_pct: Decimal | None  # after
    orders: tuple[Decimal, Decimal, Decimal | None]  # before, after, % change
    aov: Pair  # VND AOV = GMV / orders ; pct_* unused (None)
    aov_change_pct: Decimal | None
    spend_cap: SpendCap | None


def _margin(s: Snapshot) -> Decimal | None:
    return pct_points(safe_div(s.profit, s.buyer_paid_covered)) if s.profit is not None else None


def five_numbers(
    before: Snapshot, after: Snapshot, *, spend_cap: Decimal | None = None
) -> FiveNumbers:
    """``spend_cap`` is the daily cap (Cai dat > Muc tieu); compared with chi per day (after)."""
    d0, d1 = before.discount, after.discount
    extra_revenue = after.gmv - before.gmv
    extra_spend = after.chi - before.chi
    a0, a1 = safe_div(before.gmv, before.orders), safe_div(after.gmv, after.orders)
    ratio: Decimal | None = None
    status = "undefined"
    if extra_spend > 0:
        ratio, status = extra_revenue / extra_spend, "per_vnd"
    elif extra_spend < 0:
        status = "giam_chi"
    cap = None
    if spend_cap is not None:
        per_day = safe_div(after.chi, after.days) or ZERO
        cap = SpendCap(
            spend=per_day,
            cap=spend_cap,
            remaining=spend_cap - per_day,
            used_pct=pct_points(safe_div(per_day, spend_cap)),
            over_cap=per_day > spend_cap,
        )
    return FiveNumbers(
        discount=Pair(
            d0,
            d1,
            pct_points(safe_div(d0, before.list_value)),
            pct_points(safe_div(d1, after.list_value)),
        ),
        extra_revenue=extra_revenue,
        extra_spend=extra_spend,
        extra_revenue_per_extra_spend=ratio,
        extra_revenue_pct=pct_points(safe_div(extra_revenue, before.gmv)),
        chi_status=status,
        below_one=ratio is not None and ratio < 1,
        margin=Pair(before.profit, after.profit, _margin(before), _margin(after)),
        margin_is_partial=after.margin_is_partial,
        cost_coverage_pct=after.cost_coverage_pct,
        orders=(
            before.orders,
            after.orders,
            pct_points(safe_div(after.orders - before.orders, before.orders)),
        ),
        aov=Pair(a0, a1, None, None),
        aov_change_pct=pct_points(safe_div(a1 - a0, a0))
        if a0 is not None and a1 is not None
        else None,
        spend_cap=cap,
    )
