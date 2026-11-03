"""What-if scenarios over historical order lines: voucher, price change, ads budget.

Every result splits ``certain`` (recomputed from the real lines through the same waterfall
as :mod:`.order_profit`) from ``predicted`` (the caller's range, multiplied through the
certain per-order numbers). This module never forecasts volume or revenue itself.

Voucher rules:
- An order qualifies when its subtotal (sum of ``order_value`` of its lines) >= ``min_spend``.
- The voucher is a fixed ``amount`` or a ``pct`` of the subtotal (capped by ``max_discount``),
  never above the subtotal; it is spread over the order's lines by ``order_value``, remainder
  on the last line, so the lines sum to the voucher exactly.
- Both baseline and scenario vouchers are recomputed from their rules (the historical
  ``shop_voucher_share`` is replaced), so the comparison is like for like.
- Extra cost = scenario voucher total - baseline voucher total over the history.
- Margins per order are split organic (no ad-attributed line) vs ad-attributed; an order with
  an unknown cost is excluded from profit figures and counted in ``orders_missing_cost``.
- Break-even extra orders = ceil(extra cost / organic profit per order in the scenario)
  (falls back to all qualifying orders when none are organic); ``None`` + reason when that
  profit is <= 0 or unknown.
- Floor breach: a qualifying line whose buyer-paid price per unit is under the SKU's
  absolute or operating floor.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal

from juli_backend.services.shopee_profit.fees import FeeSchedule
from juli_backend.services.shopee_profit.floor import FloorResult
from juli_backend.services.shopee_profit.money import ZERO, pct_points, safe_div, to_dong
from juli_backend.services.shopee_profit.order_profit import (
    AdsPool,
    OrderLine,
    ProfitBreakdown,
    SkuCost,
    profit_lines,
)


@dataclass(frozen=True)
class PredictedRange:
    """Caller-supplied range of extra orders (or ad revenue); this package never predicts."""

    low: Decimal
    high: Decimal
    source: str = ""

    def __post_init__(self) -> None:
        if self.low > self.high:
            raise ValueError("low must be <= high")


@dataclass(frozen=True)
class PredictedNet:
    net_profit_low: Decimal
    net_profit_high: Decimal
    source: str


@dataclass(frozen=True)
class FloorBreach:
    sku: str
    kind: str  # "absolute" | "operating"
    floor: Decimal
    min_unit_price: Decimal
    lines: int


@dataclass(frozen=True)
class VoucherRule:
    min_spend: Decimal
    amount: Decimal | None = None
    pct: Decimal | None = None  # fraction of the order subtotal
    max_discount: Decimal | None = None

    def __post_init__(self) -> None:
        if (self.amount is None) == (self.pct is None):
            raise ValueError("exactly one of amount / pct")

    def discount_for(self, subtotal: Decimal) -> Decimal:
        if subtotal < self.min_spend or subtotal <= 0:
            return ZERO
        raw = self.amount if self.amount is not None else to_dong(subtotal * (self.pct or ZERO))
        if self.max_discount is not None:
            raw = min(raw, self.max_discount)
        return min(raw, subtotal)


@dataclass(frozen=True)
class OrderGroupStats:
    orders: int
    profit_per_order: Decimal | None
    margin_rate: Decimal | None

    @property
    def margin_pct(self) -> Decimal | None:
        return pct_points(self.margin_rate)


@dataclass(frozen=True)
class VoucherCertain:
    total_orders: int
    qualifying_orders: int
    qualifying_value: Decimal
    discount_pct_of_qualifying: Decimal | None
    voucher_cost_baseline: Decimal
    voucher_cost_scenario: Decimal
    extra_cost: Decimal
    organic: OrderGroupStats
    ad_attributed: OrderGroupStats
    ad_margin_below_target: bool | None
    orders_missing_cost: int
    floor_breaches: tuple[FloorBreach, ...]
    break_even_extra_orders: int | None
    break_even_reason: str | None


@dataclass(frozen=True)
class VoucherWhatIf:
    certain: VoucherCertain
    predicted: PredictedNet | None


def _apply_rule(
    lines: Sequence[OrderLine], rule: VoucherRule | None
) -> tuple[list[OrderLine], set[str], Decimal]:
    by_order: dict[str, list[OrderLine]] = defaultdict(list)
    for ln in lines:
        by_order[ln.order_id].append(ln)
    out: list[OrderLine] = []
    qualifying: set[str] = set()
    total = ZERO
    for order_id, group in by_order.items():
        subtotal = sum((ln.order_value for ln in group), ZERO)
        discount = rule.discount_for(subtotal) if rule else ZERO
        if discount > 0:
            qualifying.add(order_id)
        total += discount
        left = discount
        for i, ln in enumerate(group):
            share = (
                left
                if i == len(group) - 1
                else to_dong(discount * ln.order_value / subtotal)
                if discount > 0
                else ZERO
            )
            left -= share
            out.append(replace(ln, shop_voucher_share=share))
    return out, qualifying, total


def _stats(orders: list[tuple[Decimal | None, Decimal]]) -> OrderGroupStats:
    known = [(p, b) for p, b in orders if p is not None]
    if not known:
        return OrderGroupStats(len(orders), None, None)
    profit = sum((p for p, _ in known), ZERO)
    paid = sum((b for _, b in known), ZERO)
    return OrderGroupStats(len(orders), profit / len(known), safe_div(profit, paid))


def _order_rollup(
    pairs: Sequence[tuple[OrderLine, ProfitBreakdown]], only: set[str] | None
) -> dict[str, tuple[Decimal | None, Decimal, bool]]:
    """order_id -> (profit or None if any line unknown, buyer_paid, any ad-attributed)."""
    acc: dict[str, list[tuple[OrderLine, ProfitBreakdown]]] = defaultdict(list)
    for ln, pb in pairs:
        if only is None or ln.order_id in only:
            acc[ln.order_id].append((ln, pb))
    res: dict[str, tuple[Decimal | None, Decimal, bool]] = {}
    for oid, items in acc.items():
        profits = [pb.profit for _, pb in items]
        known = all(p is not None for p in profits)
        profit = sum((p for p in profits if p is not None), ZERO) if known else None
        res[oid] = (
            profit,
            sum((pb.buyer_paid for _, pb in items), ZERO),
            any(ln.ad_attributed for ln, _ in items),
        )
    return res


def _breaches(
    pairs: Sequence[tuple[OrderLine, ProfitBreakdown]],
    qualifying: set[str],
    floors: Mapping[str, FloorResult] | None,
) -> tuple[FloorBreach, ...]:
    if not floors:
        return ()
    low: dict[tuple[str, str], tuple[Decimal, Decimal, int]] = {}
    for ln, pb in pairs:
        floor = floors.get(ln.sku)
        if floor is None or ln.order_id not in qualifying:
            continue
        unit = pb.buyer_paid / ln.qty
        for kind, value in (
            ("absolute", floor.absolute_floor),
            ("operating", floor.operating_floor),
        ):
            if value is not None and unit < value:
                prev = low.get((ln.sku, kind), (value, unit, 0))
                low[(ln.sku, kind)] = (value, min(prev[1], unit), prev[2] + 1)
    return tuple(FloorBreach(sku, kind, v[0], v[1], v[2]) for (sku, kind), v in sorted(low.items()))


def _predicted(
    per_order: Decimal | None, extra_cost: Decimal, rng: PredictedRange | None
) -> PredictedNet | None:
    if rng is None or per_order is None:
        return None
    return PredictedNet(
        rng.low * per_order - extra_cost, rng.high * per_order - extra_cost, rng.source
    )


def voucher_whatif(
    lines: Sequence[OrderLine],
    costs: Mapping[str, SkuCost],
    *,
    scenario: VoucherRule,
    baseline: VoucherRule | None = None,
    schedule: FeeSchedule | None = None,
    ads_pools: Mapping[str, AdsPool] | None = None,
    affiliate_rate: Decimal | None = None,
    floors: Mapping[str, FloorResult] | None = None,
    target_margin_rate: Decimal | None = None,
    predicted_extra_orders: PredictedRange | None = None,
) -> VoucherWhatIf:
    _, _, baseline_cost = _apply_rule(lines, baseline)
    new_lines, qualifying, scenario_cost = _apply_rule(lines, scenario)
    pairs = profit_lines(
        new_lines, costs, schedule=schedule, ads_pools=ads_pools, affiliate_rate=affiliate_rate
    )
    rollup = _order_rollup(pairs, qualifying)
    organic = [(p, b) for p, b, ad in rollup.values() if not ad]
    ads = [(p, b) for p, b, ad in rollup.values() if ad]
    organic_stats, ad_stats = _stats(organic), _stats(ads)
    qualifying_value = sum((ln.order_value for ln in new_lines if ln.order_id in qualifying), ZERO)
    extra = scenario_cost - baseline_cost

    basis = (
        organic_stats
        if organic_stats.profit_per_order is not None
        else _stats([(p, b) for p, b, _ in rollup.values()])
    )
    ppo = basis.profit_per_order
    be: int | None = None
    reason: str | None = None
    if extra <= 0:
        be, reason = 0, "no_extra_cost"
    elif ppo is None:
        reason = "profit_per_order_unknown"
    elif ppo <= 0:
        reason = "profit_per_order_non_positive"
    else:
        be = math.ceil(extra / ppo)

    below: bool | None = None
    if target_margin_rate is not None and ad_stats.margin_rate is not None:
        below = ad_stats.margin_rate < target_margin_rate

    certain = VoucherCertain(
        total_orders=len({ln.order_id for ln in lines}),
        qualifying_orders=len(qualifying),
        qualifying_value=qualifying_value,
        discount_pct_of_qualifying=pct_points(safe_div(scenario_cost, qualifying_value)),
        voucher_cost_baseline=baseline_cost,
        voucher_cost_scenario=scenario_cost,
        extra_cost=extra,
        organic=organic_stats,
        ad_attributed=ad_stats,
        ad_margin_below_target=below,
        orders_missing_cost=sum(1 for p, _, _ in rollup.values() if p is None),
        floor_breaches=_breaches(pairs, qualifying, floors),
        break_even_extra_orders=be,
        break_even_reason=reason,
    )
    return VoucherWhatIf(certain, _predicted(ppo, extra, predicted_extra_orders))


# ---------------------------------------------------------------- price change


@dataclass(frozen=True)
class PriceChangeCertain:
    orders: int
    profit_per_order_before: Decimal | None
    profit_per_order_after: Decimal | None
    profit_delta_same_volume: Decimal | None
    floor_breaches: tuple[FloorBreach, ...]
    break_even_extra_orders: int | None
    break_even_reason: str | None


@dataclass(frozen=True)
class PriceChangeWhatIf:
    certain: PriceChangeCertain
    predicted: PredictedNet | None


def price_change_whatif(
    lines: Sequence[OrderLine],
    costs: Mapping[str, SkuCost],
    *,
    sku: str,
    new_deal_price: Decimal,
    schedule: FeeSchedule | None = None,
    ads_pools: Mapping[str, AdsPool] | None = None,
    affiliate_rate: Decimal | None = None,
    floors: Mapping[str, FloorResult] | None = None,
    predicted_extra_orders: PredictedRange | None = None,
) -> PriceChangeWhatIf:
    """Re-price one SKU's historical lines at the same volume.

    Break-even extra orders = ceil(profit lost on the existing orders / new profit per order);
    0 when the new price earns at least as much, ``None`` + reason when new profit/order <= 0.
    Vouchers and bundle discounts stay as they were (absolute amounts).
    """
    mine = [ln for ln in lines if ln.sku == sku]
    repriced = [replace(ln, deal_price=new_deal_price) for ln in mine]
    kw = {"schedule": schedule, "ads_pools": ads_pools, "affiliate_rate": affiliate_rate}
    before = profit_lines(mine, costs, **kw)  # type: ignore[arg-type]
    after = profit_lines(repriced, costs, **kw)  # type: ignore[arg-type]

    def per_order(pairs: list[tuple[OrderLine, ProfitBreakdown]]) -> Decimal | None:
        profits = [pb.profit for _, pb in pairs]
        if not profits or any(p is None for p in profits):
            return None
        return sum((p for p in profits if p is not None), ZERO) / len(profits)

    pb_before, pb_after = per_order(before), per_order(after)
    n = len(mine)
    delta = (pb_after - pb_before) * n if pb_before is not None and pb_after is not None else None
    be: int | None = None
    reason: str | None = None
    if delta is None:
        reason = "profit_unknown"
    elif delta >= 0:
        be = 0
    elif pb_after is None or pb_after <= 0:
        reason = "profit_per_order_non_positive"
    else:
        be = math.ceil(-delta / pb_after)
    certain = PriceChangeCertain(
        orders=n,
        profit_per_order_before=pb_before,
        profit_per_order_after=pb_after,
        profit_delta_same_volume=delta,
        floor_breaches=_breaches(after, {ln.order_id for ln in repriced}, floors),
        break_even_extra_orders=be,
        break_even_reason=reason,
    )
    extra_cost = -delta if delta is not None else ZERO
    return PriceChangeWhatIf(certain, _predicted(pb_after, extra_cost, predicted_extra_orders))


# ------------------------------------------------------------------ ads budget


@dataclass(frozen=True)
class AdsCertain:
    ad_orders: int
    current_ad_cost: Decimal
    ad_revenue: Decimal  # buyer-paid revenue of the ad-attributed lines
    current_roas: Decimal | None
    profit_before_ads: Decimal | None
    break_even_roas: Decimal | None  # revenue / profit before ads; spend above revenue/this loses
    profit_at_current_revenue: Decimal | None  # profit before ads - new budget
    max_budget_for_target_roas: Decimal | None
    reason: str | None


@dataclass(frozen=True)
class AdsWhatIf:
    certain: AdsCertain
    predicted: PredictedNet | None


def ads_whatif(
    lines: Sequence[OrderLine],
    costs: Mapping[str, SkuCost],
    *,
    sku: str,
    pool: AdsPool,
    new_budget: Decimal,
    target_roas: Decimal | None = None,
    schedule: FeeSchedule | None = None,
    affiliate_rate: Decimal | None = None,
    predicted_ad_revenue: PredictedRange | None = None,
) -> AdsWhatIf:
    """Ads-budget / ROAS-target scenario for one SKU from its ad-attributed lines.

    ROAS = ad revenue (buyer paid) / ad cost. ``profit_before_ads`` = those lines' profit with
    the allocated ad cost added back. Break-even ROAS = revenue / profit-before-ads. The
    predicted layer turns a caller range of ad revenue at ``new_budget`` into net profit using
    the observed profit-before-ads ratio.
    """
    ad_lines = [ln for ln in lines if ln.sku == sku and ln.ad_attributed]
    pairs = profit_lines(
        ad_lines,
        costs,
        schedule=schedule,
        ads_pools={sku: pool},
        affiliate_rate=affiliate_rate,
    )
    revenue = sum((pb.buyer_paid for _, pb in pairs), ZERO)
    reason: str | None = None
    before_ads: Decimal | None = None
    if not pairs:
        reason = "no_ad_attributed_lines"
    elif any(pb.profit is None for _, pb in pairs):
        reason = "profit_unknown"
    else:
        before_ads = sum(((pb.profit or ZERO) + (pb.ads or ZERO) for _, pb in pairs), ZERO)
    break_even = (
        safe_div(revenue, before_ads) if before_ads is not None and before_ads > 0 else None
    )
    if before_ads is not None and before_ads <= 0:
        reason = "profit_before_ads_non_positive"
    cap = revenue / target_roas if target_roas is not None and target_roas > 0 else None
    predicted: PredictedNet | None = None
    if predicted_ad_revenue and before_ads is not None and revenue > 0:
        ratio = before_ads / revenue
        predicted = PredictedNet(
            predicted_ad_revenue.low * ratio - new_budget,
            predicted_ad_revenue.high * ratio - new_budget,
            predicted_ad_revenue.source,
        )
    certain = AdsCertain(
        ad_orders=len({ln.order_id for ln in ad_lines}),
        current_ad_cost=pool.sku_ad_cost,
        ad_revenue=revenue,
        current_roas=safe_div(revenue, pool.sku_ad_cost),
        profit_before_ads=before_ads,
        break_even_roas=break_even,
        profit_at_current_revenue=None if before_ads is None else before_ads - new_budget,
        max_budget_for_target_roas=cap,
        reason=reason,
    )
    return AdsWhatIf(certain, predicted)
