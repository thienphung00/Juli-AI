"""Huyền's five numbers for a before/after pair, plus spend against its cap.

(1) discount: VND and % of list value       (4) orders: count and % change
(2) extra revenue / extra spend: VND both, ratio (3) final margin: VND profit and % of revenue
(5) AOV: VND and % change

Revenue = buyer-paid revenue; profit is after COGS, packaging, platform fees, ads,
voucher/promo and affiliate commission (a :class:`Snapshot` is built from breakdowns by
:func:`snapshot_from`, which refuses to sum unknown profit as zero). ``spend`` is the cost
the seller put in the period (ads + voucher/promo cost) -- the caller defines it, the cap
check is arithmetic only. Percentages are percent points rounded to 0.1; undefined -> None.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from juli_backend.services.shopee_profit.money import ZERO, pct_points, safe_div
from juli_backend.services.shopee_profit.order_profit import OrderLine, ProfitBreakdown


@dataclass(frozen=True)
class Snapshot:
    list_value: Decimal
    revenue: Decimal
    orders: int
    profit: Decimal | None
    spend: Decimal


def snapshot_from(pairs: Iterable[tuple[OrderLine, ProfitBreakdown]], spend: Decimal) -> Snapshot:
    items = list(pairs)
    profits = [pb.profit for _, pb in items]
    return Snapshot(
        list_value=sum((pb.list_value for _, pb in items), ZERO),
        revenue=sum((pb.buyer_paid for _, pb in items), ZERO),
        orders=len({ln.order_id for ln, _ in items}),
        profit=None if any(p is None for p in profits) else sum((p or ZERO for p in profits), ZERO),
        spend=spend,
    )


@dataclass(frozen=True)
class Pair:
    vnd_before: Decimal | None
    vnd_after: Decimal | None
    pct_before: Decimal | None
    pct_after: Decimal | None


@dataclass(frozen=True)
class SpendCap:
    spend: Decimal
    cap: Decimal
    remaining: Decimal
    used_pct: Decimal | None
    over_cap: bool


@dataclass(frozen=True)
class FiveNumbers:
    discount: Pair  # VND = list - revenue ; % of list
    extra_revenue: Decimal
    extra_spend: Decimal
    extra_revenue_per_extra_spend: Decimal | None
    margin: Pair  # VND profit ; % of revenue
    orders: tuple[int, int, Decimal | None]  # before, after, % change
    aov: Pair  # VND AOV ; pct_* unused (None); change in aov_change_pct
    aov_change_pct: Decimal | None
    spend_cap: SpendCap | None


def _discount(s: Snapshot) -> tuple[Decimal, Decimal | None]:
    d = s.list_value - s.revenue
    return d, pct_points(safe_div(d, s.list_value))


def _aov(s: Snapshot) -> Decimal | None:
    return safe_div(s.revenue, Decimal(s.orders))


def five_numbers(
    before: Snapshot, after: Snapshot, *, spend_cap: Decimal | None = None
) -> FiveNumbers:
    d0, dp0 = _discount(before)
    d1, dp1 = _discount(after)
    extra_revenue = after.revenue - before.revenue
    extra_spend = after.spend - before.spend
    a0, a1 = _aov(before), _aov(after)
    cap = None
    if spend_cap is not None:
        cap = SpendCap(
            spend=after.spend,
            cap=spend_cap,
            remaining=spend_cap - after.spend,
            used_pct=pct_points(safe_div(after.spend, spend_cap)),
            over_cap=after.spend > spend_cap,
        )
    return FiveNumbers(
        discount=Pair(d0, d1, dp0, dp1),
        extra_revenue=extra_revenue,
        extra_spend=extra_spend,
        extra_revenue_per_extra_spend=safe_div(extra_revenue, extra_spend)
        if extra_spend > 0
        else None,
        margin=Pair(
            before.profit,
            after.profit,
            pct_points(safe_div(before.profit, before.revenue))
            if before.profit is not None
            else None,
            pct_points(safe_div(after.profit, after.revenue)) if after.profit is not None else None,
        ),
        orders=(
            before.orders,
            after.orders,
            pct_points(safe_div(Decimal(after.orders - before.orders), Decimal(before.orders))),
        ),
        aov=Pair(a0, a1, None, None),
        aov_change_pct=pct_points(safe_div(a1 - a0, a0))
        if a0 is not None and a1 is not None
        else None,
        spend_cap=cap,
    )
