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
- Number 2 of the five numbers is NOT shown from the certain layer (``chi_status`` is
  ``needs_volume``; the certain layer exposes ``break_even_extra_orders``); it appears only
  in ``predicted`` when a :class:`PredictedRange` of extra orders is passed: dGMV = n x AOV,
  dchi = extra voucher cost + n x average discount of a qualifying order.
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
from juli_backend.services.shopee_profit.five_numbers import (
    FiveNumbers,
    OrderGroup,
    SpendCap,
    five_numbers,
    snapshot_from_orders,
)
from juli_backend.services.shopee_profit.floor import FloorResult
from juli_backend.services.shopee_profit.money import ONE, ZERO, pct_points, safe_div, to_dong
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
    # voucher card only: number 2 ("dự kiến") = dGMV / dchi at the low / high extra orders
    extra_revenue_per_extra_spend_low: Decimal | None = None
    extra_revenue_per_extra_spend_high: Decimal | None = None


@dataclass(frozen=True)
class FloorBreach:
    sku: str
    kind: str  # "absolute" | "operating"
    floor: Decimal
    min_unit_price: Decimal
    lines: int


@dataclass(frozen=True)
class VoucherRule:
    """A shop voucher: value (``amount`` d, or ``pct`` of the order subtotal with
    ``max_discount``), minimum spend, ``usage_limit`` (so luong voucher, None = unlimited) and
    ``per_user_limit`` (uses per buyer: accepted and reported, but NOT ENFORCEABLE -- order lines
    carry no buyer identifier (contract 9), so it never affects a number)."""

    min_spend: Decimal
    amount: Decimal | None = None
    pct: Decimal | None = None  # fraction of the order subtotal
    max_discount: Decimal | None = None
    usage_limit: int | None = None
    per_user_limit: int | None = None

    def __post_init__(self) -> None:
        if (self.amount is None) == (self.pct is None):
            raise ValueError("exactly one of amount / pct")
        if self.usage_limit is not None and self.usage_limit < 0:
            raise ValueError("usage_limit must be >= 0")
        if self.per_user_limit is not None and self.per_user_limit < 1:
            raise ValueError("per_user_limit must be >= 1")

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
    profit_per_order: Decimal | None  # after the display line-level ad split
    margin_rate: Decimal | None  # profit / buyer_paid
    contribution_per_order: Decimal | None = None  # before ads

    @property
    def margin_pct(self) -> Decimal | None:
        return pct_points(self.margin_rate)


@dataclass(frozen=True)
class VoucherCertain:
    # history window (orders as they happened)
    total_orders: int
    qualifying_orders: int
    qualifying_value: Decimal
    discount_pct_of_qualifying: Decimal | None
    # usage model (contract 7): Q scaled to the voucher's days, u explicit, used = min(Q*u, limit)
    days: int
    window_days: int
    usage_rate: Decimal
    usage_rate_source: str  # "input" | "default_1"
    usage_limit: int | None
    per_user_limit: int | None
    per_user_limit_status: str | None  # "not_enforceable" when an input was given (no buyer key)
    expected_qualifying_orders: Decimal  # Q
    used_baseline: Decimal
    used_scenario: Decimal
    usage_capped: bool  # the usage limit (not u) bound the scenario
    # cost over the voucher's days
    voucher_cost_baseline: Decimal
    voucher_cost_scenario: Decimal
    extra_cost: Decimal
    voucher_spend_per_day: Decimal
    voucher_spend_check: SpendCap | None
    # per order
    organic: OrderGroupStats
    ad_attributed: OrderGroupStats
    ad_margin_below_target: bool | None
    orders_missing_cost: int
    floor_breaches: tuple[FloorBreach, ...]
    break_even_extra_orders: int | None
    break_even_reason: str | None
    five_numbers: FiveNumbers


@dataclass(frozen=True)
class VoucherWhatIf:
    certain: VoucherCertain
    predicted: PredictedNet | None


@dataclass(frozen=True)
class _Plan:
    lines: list[OrderLine]
    qualifying: set[str]
    hist_cost: Decimal  # voucher total over the history window
    expected_q: Decimal  # Q: qualifying orders scaled to the voucher's days
    used: Decimal  # min(Q*u, usage_limit)
    capped: bool

    @property
    def fraction(self) -> Decimal:
        """Share of qualifying orders that carry the voucher (used / Q)."""
        return self.used / self.expected_q if self.expected_q > 0 else ZERO


def _apply_rule(
    lines: Sequence[OrderLine], rule: VoucherRule | None
) -> tuple[list[OrderLine], set[str], Decimal]:
    by_order: dict[str, list[OrderLine]] = defaultdict(list)
    for ln in lines:
        by_order[ln.order_id].append(ln)
    subtotals = {oid: sum((ln.order_value for ln in g), ZERO) for oid, g in by_order.items()}
    discounts = {oid: (rule.discount_for(subtotals[oid]) if rule else ZERO) for oid in by_order}
    out: list[OrderLine] = []
    qualifying: set[str] = set()
    total = ZERO
    for order_id, group in by_order.items():
        subtotal, discount = subtotals[order_id], discounts[order_id]
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


def _plan(
    lines: Sequence[OrderLine],
    rule: VoucherRule | None,
    scale: Decimal,
    usage_rate: Decimal,
) -> _Plan:
    new_lines, qualifying, total = _apply_rule(lines, rule)
    q = Decimal(len(qualifying)) * scale
    by_rate = q * usage_rate
    limit = Decimal(rule.usage_limit) if rule and rule.usage_limit is not None else None
    used = min(by_rate, limit) if limit is not None else by_rate
    return _Plan(new_lines, qualifying, total, q, used, limit is not None and limit < by_rate)


def _stats(orders: list[tuple[Decimal | None, Decimal | None, Decimal]]) -> OrderGroupStats:
    """orders: (profit, contribution, buyer_paid) -- None = a cost is unknown."""
    known = [(p, b) for p, _, b in orders if p is not None]
    known_c = [c for _, c, _ in orders if c is not None]
    c_per = sum(known_c, ZERO) / len(known_c) if known_c else None
    if not known:
        return OrderGroupStats(len(orders), None, None, c_per)
    profit = sum((p for p, _ in known), ZERO)
    paid = sum((b for _, b in known), ZERO)
    return OrderGroupStats(len(orders), profit / len(known), safe_div(profit, paid), c_per)


def _order_rollup(
    pairs: Sequence[tuple[OrderLine, ProfitBreakdown]], only: set[str] | None
) -> dict[str, tuple[Decimal | None, Decimal | None, Decimal, bool]]:
    """order_id -> (profit, contribution -- None if any line unknown, buyer_paid, any ad)."""
    acc: dict[str, list[tuple[OrderLine, ProfitBreakdown]]] = defaultdict(list)
    for ln, pb in pairs:
        if pb.excluded_reason is None and (only is None or ln.order_id in only):
            acc[ln.order_id].append((ln, pb))
    res: dict[str, tuple[Decimal | None, Decimal | None, Decimal, bool]] = {}
    for oid, items in acc.items():
        profits = [pb.profit for _, pb in items]
        contribs = [pb.contribution for _, pb in items]
        res[oid] = (
            None if any(p is None for p in profits) else sum((p or ZERO for p in profits), ZERO),
            None if any(c is None for c in contribs) else sum((c or ZERO for c in contribs), ZERO),
            sum((pb.revenue for _, pb in items), ZERO),
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


def _groups(pairs: Sequence[tuple[OrderLine, ProfitBreakdown]]) -> dict[str, OrderGroup]:
    out: dict[str, list[tuple[OrderLine, ProfitBreakdown]]] = defaultdict(list)
    for ln, pb in pairs:
        out[ln.order_id].append((ln, pb))
    return dict(out)


def _mixed(
    none_groups: Mapping[str, OrderGroup],
    plan: _Plan | None,
    plan_groups: Mapping[str, OrderGroup] | None,
    scale: Decimal,
) -> list[tuple[Decimal, OrderGroup]]:
    """Expected orders in the voucher period: qualifying orders carry the voucher with
    probability used/Q, otherwise they are voucher-free; every weight is scaled to the days."""
    out: list[tuple[Decimal, OrderGroup]] = []
    phi = plan.fraction if plan else ZERO
    for oid, group in none_groups.items():
        if plan is not None and plan_groups is not None and oid in plan.qualifying:
            out.append((scale * phi, plan_groups[oid]))
            out.append((scale * (ONE - phi), group))
        else:
            out.append((scale, group))
    return out


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
    usage_rate: Decimal | None = None,
    voucher_days: int | None = None,
    window_days: int | None = None,
    ad_spend: Decimal = ZERO,
    other_costs: Decimal = ZERO,
    spend_cap_per_day: Decimal | None = None,
) -> VoucherWhatIf:
    """Contract 7. ``lines`` are the history window (whole orders). ``usage_rate`` is u, the
    usage rate of the shop's comparable past vouchers (default 1, reported as ``default_1``);
    ``voucher_days`` / ``window_days`` scale Q (default: no scaling; window = date span of the
    lines). ``ad_spend`` / ``other_costs`` are the window's totals, scaled with the orders, and
    identical before and after (the voucher does not change them)."""
    u = Decimal(1) if usage_rate is None else usage_rate
    if not ZERO <= u <= 1:
        raise ValueError("usage_rate must be within [0, 1]")
    if lines:
        dates = [ln.order_date for ln in lines]
        window = window_days or ((max(dates) - min(dates)).days + 1)
    else:
        window = window_days or 1
    days = voucher_days or window
    if window <= 0 or days <= 0:
        raise ValueError("days must be positive")
    scale = Decimal(days) / Decimal(window)

    def run(ls: Sequence[OrderLine]) -> list[tuple[OrderLine, ProfitBreakdown]]:
        return profit_lines(
            ls, costs, schedule=schedule, ads_pools=ads_pools, affiliate_rate=affiliate_rate
        )

    base_plan = _plan(lines, baseline, scale, u)
    plan = _plan(lines, scenario, scale, u)
    pairs = run(plan.lines)
    rollup = _order_rollup(pairs, plan.qualifying)
    organic = [(p, c, b) for p, c, b, ad in rollup.values() if not ad]
    ads = [(p, c, b) for p, c, b, ad in rollup.values() if ad]
    organic_stats, ad_stats = _stats(organic), _stats(ads)
    qualifying_value = sum(
        (ln.order_value for ln in plan.lines if ln.order_id in plan.qualifying), ZERO
    )

    # cost over the voucher's days: used orders x average discount of a qualifying order
    n_q = len(plan.qualifying)
    cost_s = plan.hist_cost * scale * plan.fraction
    cost_b = base_plan.hist_cost * scale * base_plan.fraction
    extra = cost_s - cost_b

    basis = (
        organic_stats
        if organic_stats.contribution_per_order is not None
        else _stats([(p, c, b) for p, c, b, _ in rollup.values()])
    )
    cpo = basis.contribution_per_order
    be: int | None = None
    reason: str | None = None
    if extra <= 0:
        be, reason = 0, "no_extra_cost"
    elif cpo is None:
        reason = "profit_per_order_unknown"
    elif cpo <= 0:
        reason = "profit_per_order_non_positive"
    else:
        be = math.ceil(extra / cpo)

    below: bool | None = None
    if target_margin_rate is not None and ad_stats.margin_rate is not None:
        below = ad_stats.margin_rate < target_margin_rate

    # five numbers: before = baseline voucher (or none), after = scenario, same orders
    none_pairs = run(_apply_rule(lines, None)[0])
    none_groups = _groups(none_pairs)
    base_groups = _groups(run(base_plan.lines)) if baseline is not None else None
    scaled_ads, scaled_other = ad_spend * scale, other_costs * scale
    d = Decimal(days)
    snap_before = snapshot_from_orders(
        _mixed(none_groups, base_plan if baseline else None, base_groups, scale),
        scaled_ads,
        other_costs=scaled_other,
        days=d,
    )
    snap_after = snapshot_from_orders(
        _mixed(none_groups, plan, _groups(pairs), scale),
        scaled_ads,
        other_costs=scaled_other,
        days=d,
    )
    five = five_numbers(snap_before, snap_after, spend_cap=spend_cap_per_day)
    # contract 9: the certain layer has no volume change -> number 2 is not shown from it
    five = replace(
        five,
        extra_revenue_per_extra_spend=None,
        extra_revenue_pct=None,
        chi_status="needs_volume",
        below_one=False,
    )

    per_day = cost_s / d
    check = None
    if spend_cap_per_day is not None:
        check = SpendCap(
            per_day,
            spend_cap_per_day,
            spend_cap_per_day - per_day,
            pct_points(safe_div(per_day, spend_cap_per_day)),
            per_day > spend_cap_per_day,
        )

    certain = VoucherCertain(
        total_orders=len({ln.order_id for ln in lines}),
        qualifying_orders=n_q,
        qualifying_value=qualifying_value,
        discount_pct_of_qualifying=pct_points(safe_div(plan.hist_cost, qualifying_value)),
        days=days,
        window_days=window,
        usage_rate=u,
        usage_rate_source="default_1" if usage_rate is None else "input",
        usage_limit=scenario.usage_limit,
        per_user_limit=scenario.per_user_limit,
        per_user_limit_status="not_enforceable" if scenario.per_user_limit is not None else None,
        expected_qualifying_orders=plan.expected_q,
        used_baseline=base_plan.used,
        used_scenario=plan.used,
        usage_capped=plan.capped,
        voucher_cost_baseline=cost_b,
        voucher_cost_scenario=cost_s,
        extra_cost=extra,
        voucher_spend_per_day=per_day,
        voucher_spend_check=check,
        organic=organic_stats,
        ad_attributed=ad_stats,
        ad_margin_below_target=below,
        orders_missing_cost=sum(1 for _, c, _, _ in rollup.values() if c is None),
        floor_breaches=_breaches(pairs, plan.qualifying, floors),
        break_even_extra_orders=be,
        break_even_reason=reason,
        five_numbers=five,
    )
    predicted = _predicted(cpo, extra, predicted_extra_orders)
    if predicted is not None and predicted_extra_orders is not None:
        aov = safe_div(snap_after.gmv, snap_after.orders)
        avg_discount = safe_div(plan.hist_cost, Decimal(n_q)) or ZERO

        def ratio(n: Decimal) -> Decimal | None:
            denom = extra + n * avg_discount
            return safe_div(n * aov, denom) if aov is not None and denom > 0 else None

        predicted = replace(
            predicted,
            extra_revenue_per_extra_spend_low=ratio(predicted_extra_orders.low),
            extra_revenue_per_extra_spend_high=ratio(predicted_extra_orders.high),
        )
    return VoucherWhatIf(certain, predicted)


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
    new_deal_price: Decimal | None = None,
    schedule: FeeSchedule | None = None,
    ads_pools: Mapping[str, AdsPool] | None = None,
    affiliate_rate: Decimal | None = None,
    floors: Mapping[str, FloorResult] | None = None,
    predicted_extra_orders: PredictedRange | None = None,
    price_factor: Decimal | None = None,
    ceiling: bool = False,
) -> PriceChangeWhatIf:
    """Re-price one SKU's historical lines at the same volume.

    Three ways to say the new price (exactly one): ``new_deal_price`` sets every line to it
    (``ceiling=True``: lines already cheaper keep their price -- a discount cap), and
    ``price_factor`` scales each line's own deal price (a 5 % rise on lines sold at different
    prices is x 1,05 on each, not one price for all).

    Break-even extra orders = ceil(profit lost on the existing orders / new profit per order);
    0 when the new price earns at least as much, ``None`` + reason when new profit/order <= 0.
    Vouchers and bundle discounts stay as they were (absolute amounts).
    """
    if (new_deal_price is None) == (price_factor is None):
        raise ValueError("exactly one of new_deal_price / price_factor")
    if price_factor is not None and price_factor <= 0:
        raise ValueError("price_factor must be positive")

    def reprice(ln: OrderLine) -> OrderLine:
        if price_factor is not None:
            return replace(ln, deal_price=to_dong(ln.deal_price * price_factor))
        assert new_deal_price is not None
        return replace(
            ln, deal_price=min(ln.deal_price, new_deal_price) if ceiling else new_deal_price
        )

    mine = [ln for ln in lines if ln.sku == sku]
    repriced = [reprice(ln) for ln in mine]

    def run(ls: Sequence[OrderLine]) -> list[tuple[OrderLine, ProfitBreakdown]]:
        return profit_lines(
            ls, costs, schedule=schedule, ads_pools=ads_pools, affiliate_rate=affiliate_rate
        )

    # whole orders go through the waterfall so per-order fixed fees are split correctly
    swap = {id(ln): new for ln, new in zip(mine, repriced, strict=True)}
    whole_after = [swap.get(id(ln), ln) for ln in lines]
    before = [p for p in run(lines) if p[0].sku == sku]
    after = [p for p in run(whole_after) if p[0].sku == sku]

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
    pairs = [
        p
        for p in profit_lines(
            lines,
            costs,
            schedule=schedule,
            ads_pools={sku: pool},
            affiliate_rate=affiliate_rate,
        )
        if p[0].sku == sku and p[0].ad_attributed
    ]
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
