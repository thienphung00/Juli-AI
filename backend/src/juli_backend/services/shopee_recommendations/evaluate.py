"""The certain layer of a candidate: one evaluator per family, all arithmetic from
``services/shopee_profit`` over the shop's real order lines (contract 7, 12).

``evaluate(env, candidate, predicted=None)`` is the single entry the generators and the
what-if endpoint call. It returns an :class:`~.model.Evaluation`: the certain numbers, the five
numbers before -> after, the floor breaches and a :class:`~.model.ProfitModel` for the
predicted-range conversion. ``predicted`` is an optional :class:`PredictedRange` of extra orders
over the effect period; when given, the shopee_profit what-if functions fill their own
``predicted`` net profit (the card shows it as "dự kiến").

Nothing here forecasts: lifts come from ``prediction``; this module only multiplies them
through the shop's own per-order numbers.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import replace
from decimal import Decimal
from typing import Any

from juli_backend.services.shopee_analytics.fmt import num, pct, ratio
from juli_backend.services.shopee_analytics.shared import five_json
from juli_backend.services.shopee_profit.five_numbers import (
    FiveNumbers,
    Snapshot,
    five_numbers,
    snapshot_from,
)
from juli_backend.services.shopee_profit.floor import FloorResult
from juli_backend.services.shopee_profit.money import (
    ONE,
    ZERO,
    pct_points,
    round_down_to,
    safe_div,
    to_dong,
)
from juli_backend.services.shopee_profit.order_profit import (
    OrderLine,
    ProfitBreakdown,
    PromoKind,
    profit_lines,
)
from juli_backend.services.shopee_profit.whatif import (
    FloorBreach,
    PredictedRange,
    VoucherRule,
    price_change_whatif,
    voucher_whatif,
)
from juli_backend.services.shopee_recommendations import config
from juli_backend.services.shopee_recommendations.env import RecoEnv
from juli_backend.services.shopee_recommendations.kinds import spec
from juli_backend.services.shopee_recommendations.model import Candidate, Evaluation, ProfitModel


def D(value: Any) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _opt(value: Any) -> Decimal | None:
    return None if value is None else D(value)


# ----------------------------------------------------------------------------- helpers


def breach_json(breaches: Sequence[FloorBreach]) -> list[dict[str, Any]]:
    return [
        {
            "sku": b.sku,
            "kind": b.kind,
            "floor": num(b.floor),
            "min_unit_price": num(b.min_unit_price),
            "lines": b.lines,
        }
        for b in breaches
    ]


def _floors_for(env: RecoEnv, item_ids: Sequence[str]) -> dict[str, FloorResult]:
    out: dict[str, FloorResult] = {}
    for item in item_ids:
        out.update(env.floors(item))
    return out


def _lines_items(lines: Sequence[OrderLine]) -> list[str]:
    seen: dict[str, None] = {}
    for ln in lines:
        seen.setdefault(ln.product_id, None)
    return list(seen)


def _scope_gmv_per_day(env: RecoEnv, items: Sequence[str] | None) -> Decimal:
    wanted = None if not items else set(items)
    gmv = sum(
        (ln.order_value for ln, _ in env.view.pairs if wanted is None or ln.product_id in wanted),
        ZERO,
    )
    return gmv / Decimal(env.window_days)


def _scope_orders(env: RecoEnv, items: Sequence[str] | None) -> int:
    wanted = None if not items else set(items)
    return len(
        {ln.order_id for ln, _ in env.view.pairs if wanted is None or ln.product_id in wanted}
    )


def _scope_ad_spend(env: RecoEnv, items: Sequence[str] | None) -> Decimal:
    if not items:
        return env.view.ads.total_spend
    return sum((env.view.ads.product_spend.get(i, ZERO) for i in items), ZERO)


def scope_snapshot(
    env: RecoEnv,
    items: Sequence[str] | None,
    pairs: Sequence[tuple[OrderLine, ProfitBreakdown]],
    ad_spend: Decimal,
) -> Snapshot:
    wanted = None if not items else set(items)
    mine = [(ln, pb) for ln, pb in pairs if wanted is None or ln.product_id in wanted]
    return snapshot_from(mine, ad_spend, days=Decimal(env.window_days))


def _five(
    env: RecoEnv, before: Snapshot, after: Snapshot, *, needs_volume: bool = False
) -> tuple[FiveNumbers, dict[str, Any]]:
    five = five_numbers(before, after, spend_cap=env.daily_cap)
    if needs_volume:  # contract 9: number 2 only from the predicted range
        five = replace(
            five,
            extra_revenue_per_extra_spend=None,
            extra_revenue_pct=None,
            chi_status="needs_volume",
            below_one=False,
        )
    return five, five_json(five)


def _spend_check(env: RecoEnv, dchi_per_day: Decimal) -> dict[str, Any]:
    now = env.shop_chi_per_day()
    after = now + dchi_per_day
    cap = env.daily_cap
    return {
        "shop_chi_per_day_now": num(now),
        "card_dchi_per_day": num(dchi_per_day),
        "shop_chi_per_day_after": num(after),
        "cap": num(cap),
        "over_cap": None if cap is None else after > cap,
        "basis": "chi = quảng cáo + voucher + khuyến mãi + combo + hoa hồng",
    }


def _month_factor(effect_days: int) -> Decimal:
    return Decimal(min(effect_days, config.DAYS_PER_MONTH))


# ----------------------------------------------------------------------------- voucher


def voucher_rule_from(inputs: Mapping[str, Any]) -> VoucherRule:
    value, pct_in = inputs.get("value"), inputs.get("pct")
    return VoucherRule(
        min_spend=D(inputs.get("min_spend") or 0),
        amount=D(value) if value is not None and pct_in is None else None,
        pct=D(pct_in) / 100 if pct_in is not None else None,
        max_discount=_opt(inputs.get("max_value")),
        usage_limit=int(inputs["quantity"]) if inputs.get("quantity") is not None else None,
        per_user_limit=int(inputs["per_user_limit"]) if inputs.get("per_user_limit") else None,
    )


def eval_voucher(
    env: RecoEnv, cand: Candidate, inputs: Mapping[str, Any], predicted: PredictedRange | None
) -> Evaluation:
    items = list(cand.items) or None
    lines = env.lines_for(items)
    if not lines:
        return _refuse("no_order_lines")
    days = int(inputs.get("days") or config.VOUCHER_DAYS)
    rule = voucher_rule_from(inputs)
    base_inputs = inputs.get("baseline")
    baseline = voucher_rule_from(base_inputs) if base_inputs else None
    present = _lines_items(lines)
    main = (cand.items or tuple(present))[0]
    wi = voucher_whatif(
        lines,
        env.costs,
        scenario=rule,
        baseline=baseline,
        schedule=env.schedule(main),
        floors=_floors_for(env, present),
        target_margin_rate=env.margin_target_rate,
        predicted_extra_orders=predicted,
        usage_rate=env.usage_rate,
        voucher_days=days,
        window_days=env.window_days,
        ad_spend=_scope_ad_spend(env, items),
        spend_cap_per_day=env.daily_cap,
    )
    c = wi.certain
    aov = c.five_numbers.aov.vnd_after
    cpo = c.organic.contribution_per_order
    dchi = c.extra_cost / Decimal(days)
    profit = ProfitModel(
        effect_days=days,
        base_gmv_per_day=_scope_gmv_per_day(env, items),
        base_orders_per_day=Decimal(_scope_orders(env, items)) / env.window_days,
        aov=aov,
        profit_per_gmv=safe_div(cpo, aov) if cpo is not None and aov else None,
        extra_cost_per_day=dchi,
        dchi_per_day=dchi,
    )
    certain = {
        "kind": "voucher",
        "qualifying_orders": c.qualifying_orders,
        "total_orders": c.total_orders,
        "discount_pct_of_qualifying": pct(c.discount_pct_of_qualifying),
        "days": c.days,
        "window_days": c.window_days,
        "usage_rate": ratio(c.usage_rate, 4),
        "usage_rate_source": c.usage_rate_source,
        "usage_limit": c.usage_limit,
        "usage_capped": c.usage_capped,
        "per_user_limit": c.per_user_limit,
        "per_user_limit_status": c.per_user_limit_status,
        "expected_qualifying_orders": num(c.expected_qualifying_orders),
        "used_scenario": num(c.used_scenario),
        "used_baseline": num(c.used_baseline),
        "voucher_cost_scenario": num(c.voucher_cost_scenario),
        "voucher_cost_baseline": num(c.voucher_cost_baseline),
        "extra_cost": num(c.extra_cost),
        "voucher_spend_per_day": num(c.voucher_spend_per_day),
        "voucher_spend_check": None
        if c.voucher_spend_check is None
        else {
            "per_day": num(c.voucher_spend_check.spend),
            "cap": num(c.voucher_spend_check.cap),
            "over_cap": c.voucher_spend_check.over_cap,
        },
        "organic": _group_json(c.organic),
        "ad_attributed": _group_json(c.ad_attributed),
        "ad_margin_below_target": c.ad_margin_below_target,
        "orders_missing_cost": c.orders_missing_cost,
        "break_even_extra_orders": c.break_even_extra_orders,
        "break_even_reason": c.break_even_reason,
        "extra_orders_label": "Đơn thêm cần để hoà vốn",
    }
    if wi.predicted is not None:
        certain["predicted_net"] = {
            "net_profit_low": num(wi.predicted.net_profit_low),
            "net_profit_high": num(wi.predicted.net_profit_high),
            "extra_revenue_per_extra_spend_low": ratio(
                wi.predicted.extra_revenue_per_extra_spend_low, 2
            ),
            "extra_revenue_per_extra_spend_high": ratio(
                wi.predicted.extra_revenue_per_extra_spend_high, 2
            ),
            "source": wi.predicted.source,
        }
    five_dict = five_json(c.five_numbers)
    base = base_inputs or {}
    return Evaluation(
        certain=certain,
        five=five_dict,
        breaches=breach_json(c.floor_breaches),
        profit=profit,
        before={
            "value": base.get("value"),
            "pct": base.get("pct"),
            "min_spend": base.get("min_spend"),
            "max_value": base.get("max_value"),
            "quantity": base.get("quantity"),
            "label": "chưa có voucher này" if not base_inputs else "voucher hiện tại",
        },
        after={
            "value": inputs.get("value"),
            "pct": inputs.get("pct"),
            "min_spend": inputs.get("min_spend"),
            "max_value": inputs.get("max_value"),
            "quantity": inputs.get("quantity"),
            "days": days,
        },
        target={"voucher_id": (base_inputs or {}).get("voucher_id")},
        spend_check=_spend_check(env, dchi),
        floor_unknown_skus=_unknown_floors(env, present),
    )


def _group_json(g: Any) -> dict[str, Any]:
    return {
        "orders": g.orders,
        "profit_per_order": num(g.profit_per_order),
        "contribution_per_order": num(g.contribution_per_order),
        "margin_pct": pct(g.margin_pct),
    }


def _unknown_floors(env: RecoEnv, items: Sequence[str]) -> list[str]:
    out = []
    for item in items:
        for sku in env.skus_of(item):
            f = env.floors(item).get(sku)
            if f is None or (f.operating_floor is None and f.absolute_floor is None):
                out.append(sku)
    return out


def _refuse(reason: str) -> Evaluation:
    return Evaluation(
        certain={},
        five=None,
        breaches=[],
        profit=ProfitModel(),
        before={},
        after={},
        target={},
        refusal=reason,
    )


# ------------------------------------------------------------------------ price / sale


def new_price(env: RecoEnv, kind: str, sku: str, inputs: Mapping[str, Any]) -> Decimal | None:
    current = env.current_price(sku)
    listed = env.list_price(sku)
    if kind in ("product_discount", "flash_sale", "program_registration"):
        if listed is None:
            return None
        return round_down_to(listed * (ONE - D(inputs.get("discount_pct", 0)) / 100), Decimal(100))
    if current is None:
        return None
    return round_down_to(current * D(inputs.get("new_price_pct", 100)) / 100, Decimal(100))


def eval_price(
    env: RecoEnv, cand: Candidate, inputs: Mapping[str, Any], predicted: PredictedRange | None
) -> Evaluation:
    item = cand.item
    if item is None:
        return _refuse("no_item")
    lines = env.lines_for([item])
    skus = [s for s in env.skus_of(item) if env.current_price(s) is not None]
    if not lines or not skus:
        return _refuse("no_order_lines")
    floors = _floors_for(env, [item])
    schedule = env.schedule(item)
    window = Decimal(env.window_days)
    orders_by_sku = {
        s: len({ln.order_id for ln in lines if ln.sku == s and ln.product_id == item}) for s in skus
    }
    total_orders = sum(orders_by_sku.values()) or 1
    results: dict[str, Any] = {}
    repriced: dict[int, OrderLine] = {}
    new_prices: dict[str, Decimal] = {}
    for sku in skus:
        new = new_price(env, cand.kind, sku, inputs)
        if new is None:
            continue
        new_prices[sku] = new
        sku_range = None
        if predicted is not None:
            share = Decimal(orders_by_sku[sku]) / Decimal(total_orders)
            sku_range = PredictedRange(
                predicted.low * share, predicted.high * share, predicted.source
            )
        if cand.kind == "price":  # each line keeps its own price level: x factor
            factor = D(inputs.get("new_price_pct", 100)) / 100
            kw: dict[str, Any] = {"price_factor": factor}
        else:  # a discount to a price: lines already cheaper keep theirs
            kw = {"new_deal_price": new, "ceiling": True}
        results[sku] = price_change_whatif(
            lines,
            env.costs,
            sku=sku,
            schedule=schedule,
            floors=floors,
            predicted_extra_orders=sku_range,
            **kw,
        )
        for ln in lines:
            if ln.sku == sku and ln.product_id == item:
                if cand.kind == "price":
                    repriced[id(ln)] = replace(ln, deal_price=to_dong(ln.deal_price * factor))
                else:
                    repriced[id(ln)] = replace(ln, deal_price=min(ln.deal_price, new))
    if not results:
        return _refuse("no_price")
    after_lines = [repriced.get(id(ln), ln) for ln in lines]
    before_pairs = profit_lines(lines, env.costs, schedule=schedule)
    after_pairs = profit_lines(after_lines, env.costs, schedule=schedule)
    spend = _scope_ad_spend(env, [item])
    five, five_dict = _five(
        env,
        scope_snapshot(env, [item], before_pairs, spend),
        scope_snapshot(env, [item], after_pairs, spend),
    )
    n = sum(r.certain.orders for r in results.values())
    delta = sum((r.certain.profit_delta_same_volume or ZERO for r in results.values()), ZERO)
    delta_known = all(r.certain.profit_delta_same_volume is not None for r in results.values())
    pb_after = [
        (r.certain.orders, r.certain.profit_per_order_after)
        for r in results.values()
        if r.certain.profit_per_order_after is not None
    ]
    pi = (
        sum((Decimal(o) * p for o, p in pb_after), ZERO) / Decimal(sum(o for o, _ in pb_after))
        if pb_after and sum(o for o, _ in pb_after)
        else None
    )
    gmv_before = sum((ln.order_value for ln in lines if ln.product_id == item), ZERO)
    gmv_after = sum((ln.order_value for ln in after_lines if ln.product_id == item), ZERO)
    orders_item = _scope_orders(env, [item])
    aov = safe_div(gmv_after, Decimal(orders_item)) if orders_item else None
    effect_days = (
        int(inputs.get("slot_days") or 1)
        if cand.kind in ("flash_sale", "program_registration")
        else config.DAYS_PER_MONTH
    )
    profit = ProfitModel(
        effect_days=effect_days,
        base_gmv_per_day=_scope_gmv_per_day(env, [item]),
        base_orders_per_day=Decimal(orders_item) / window,
        aov=aov,
        profit_per_gmv=safe_div(pi, aov) if pi is not None and aov else None,
        extra_cost_per_day=(-delta / window) if delta_known else ZERO,
        certain_dgmv_per_day=(gmv_after - gmv_before) / window,
        dchi_per_day=safe_div(
            sum((pb.promo_discount for _, pb in after_pairs if pb.excluded_reason is None), ZERO)
            - sum(
                (pb.promo_discount for _, pb in before_pairs if pb.excluded_reason is None), ZERO
            ),
            window,
        )
        or ZERO,
        max_extra_units=_opt(inputs.get("units"))
        if cand.kind in ("flash_sale", "program_registration")
        else None,
    )
    skus_json = []
    for sku, r in results.items():
        c = r.certain
        fl = floors.get(sku)
        skus_json.append(
            {
                "sku": sku,
                "list_price": num(env.list_price(sku)),
                "price_before": num(env.current_price(sku)),
                "price_after": num(new_prices[sku]),
                "orders": c.orders,
                "profit_per_order_before": num(c.profit_per_order_before),
                "profit_per_order_after": num(c.profit_per_order_after),
                "profit_delta_same_volume": num(c.profit_delta_same_volume),
                "break_even_extra_orders": c.break_even_extra_orders,
                "break_even_reason": c.break_even_reason,
                "floor_absolute": num(fl.absolute_floor) if fl else None,
                "floor_operating": num(fl.operating_floor) if fl else None,
            }
        )
    breaches = []
    for sku, new in new_prices.items():
        # forward-looking: the proposed price against the SKU's floor (lines the history sold
        # below it for other reasons are not this change's doing)
        fl = floors.get(sku)
        floor_px = (
            None
            if fl is None
            else (fl.operating_floor if fl.operating_floor is not None else fl.absolute_floor)
        )
        if floor_px is not None and new < floor_px:
            breaches.append(
                {
                    "sku": sku,
                    "kind": "operating" if fl and fl.operating_floor is not None else "absolute",
                    "floor": num(floor_px),
                    "min_unit_price": num(new),
                    "lines": results[sku].certain.orders,
                }
            )
    certain = {
        "kind": "price",
        "skus": skus_json,
        "orders": n,
        "profit_delta_same_volume": num(delta) if delta_known else None,
        "gmv_delta_same_volume": num(gmv_after - gmv_before),
        "discount_pct_of_list": pct(
            pct_points(
                safe_div(
                    sum(
                        (ln.original_price * ln.qty for ln in after_lines if ln.product_id == item),
                        ZERO,
                    )
                    - gmv_after,
                    sum(
                        (ln.original_price * ln.qty for ln in after_lines if ln.product_id == item),
                        ZERO,
                    ),
                )
            )
        ),
        "break_even_extra_orders": max(
            (
                r.certain.break_even_extra_orders
                for r in results.values()
                if r.certain.break_even_extra_orders is not None
            ),
            default=None,
        ),
    }
    if predicted is not None:
        nets = [r.predicted for r in results.values() if r.predicted is not None]
        if nets:
            certain["predicted_net"] = {
                "net_profit_low": num(sum((x.net_profit_low for x in nets), ZERO)),
                "net_profit_high": num(sum((x.net_profit_high for x in nets), ZERO)),
                "source": nets[0].source,
            }
    first = skus_json[0]
    return Evaluation(
        certain=certain,
        five=five_dict,
        breaches=breaches,
        profit=profit,
        before={
            "price": first["price_before"],
            "list_price": first["list_price"],
            "skus": [{"sku": s["sku"], "price": s["price_before"]} for s in skus_json],
        },
        after={
            "price": first["price_after"],
            "skus": [{"sku": s["sku"], "price": s["price_after"]} for s in skus_json],
            "discount_pct": inputs.get("discount_pct"),
            "units": inputs.get("units"),
            "slot_days": inputs.get("slot_days"),
        },
        target={"item_id": item},
        spend_check=_spend_check(env, profit.dchi_per_day),
        floor_unknown_skus=_unknown_floors(env, [item]),
    )


# --------------------------------------------------------------------------------- ads


def campaign_profile(env: RecoEnv, campaign_key: str) -> dict[str, Any] | None:
    """Spend, direct revenue and break-even of one campaign from the ads report (placed
    orders): direct revenue x each product's contribution rate = profit before ads."""
    alloc = next((c for c in env.view.ads.campaigns if c.key == campaign_key), None)
    if alloc is None or alloc.spend <= 0:
        return None
    days = Decimal(env.window_days)
    figs = env.view.ads.product_figures
    before_ads = ZERO
    direct = ZERO
    for item, spend in alloc.products.items():
        fig = figs.get(item)
        pp = env.product(item)
        if fig is None or fig.direct_gmv is None or pp is None:
            continue
        share = safe_div(spend, env.view.ads.product_spend.get(item, spend)) or ONE
        rate = (
            safe_div(pp.contribution, pp.buyer_paid_covered) if pp.buyer_paid_covered > 0 else None
        )
        d = fig.direct_gmv * min(share, ONE)
        direct += d
        before_ads += d * (rate if rate is not None and rate > 0 else ZERO)
    if direct <= 0:
        direct = alloc.direct_gmv
    return {
        "alloc": alloc,
        "spend_per_day": alloc.spend / days,
        "direct_per_day": direct / days,
        "profit_before_ads_per_day": before_ads / days,
        "roas_direct": safe_div(direct, alloc.spend),
        "break_even_roas": safe_div(direct, before_ads) if before_ads > 0 else None,
        "rate": safe_div(before_ads, direct) if direct > 0 else None,
    }


def eval_ads(
    env: RecoEnv, cand: Candidate, inputs: Mapping[str, Any], predicted: PredictedRange | None
) -> Evaluation:
    key = cand.campaign_key
    prof = campaign_profile(env, key) if key else None
    if prof is None:
        return _refuse("no_campaign_report")
    alloc = prof["alloc"]
    setting = env.setting_for(key)
    spend_now: Decimal = prof["spend_per_day"]
    items = list(alloc.products) if alloc.products else list(cand.items)
    kind = cand.kind
    budget_before = setting.daily_budget if setting and setting.daily_budget is not None else None
    roas_before = setting.roas_target if setting else None
    roas_after = roas_before
    spend_after = spend_now
    item_share = ONE
    before_view: dict[str, Any] = {}
    after_view: dict[str, Any] = {}
    target: dict[str, Any] = {
        "campaign_id": setting.campaign_id if setting else None,
        "campaign_key": key,
    }
    if kind == "ads_budget":
        b1 = D(inputs["daily_budget"])
        ref = budget_before if budget_before is not None else spend_now
        spend_after = min(b1, spend_now) if b1 < ref else b1
        before_view = {"daily_budget": num(budget_before), "spend_per_day": num(spend_now)}
        after_view = {"daily_budget": num(b1)}
    elif kind == "ads_roas_target":
        roas_after = D(inputs["roas_target"])
        before_view = {"roas_target": num(roas_before)}
        after_view = {"roas_target": num(roas_after)}
    elif kind == "ads_pause":
        spend_after = ZERO
        before_view = {"state": "đang chạy", "spend_per_day": num(spend_now)}
        after_view = {"state": "tạm dừng"}
    elif kind in ("ads_remove_product", "ads_add_product"):
        item = cand.item or ""
        part = alloc.products.get(item, ZERO)
        item_share = safe_div(part, alloc.spend) or ZERO
        if kind == "ads_remove_product":
            spend_after = spend_now * (ONE - item_share)
            before_view = {"products": len(alloc.products)}
            after_view = {"products": max(len(alloc.products) - 1, 0), "removed_item_id": item}
        else:
            before_view = {"products": len(alloc.products)}
            after_view = {"products": len(alloc.products) + 1, "added_item_id": item}
        target["item_id"] = item
    else:  # ads_purpose
        before_view = {"purpose": setting.purpose if setting else None}
        after_view = {"purpose": inputs.get("purpose")}
    dspend = spend_after - spend_now
    be = prof["break_even_roas"]
    roas = prof["roas_direct"]
    target_roas = roas_after if roas_after is not None else roas
    profit_before_ads = prof["profit_before_ads_per_day"]
    certain = {
        "kind": "ads",
        "basis": {"key": "placed", "label": "đơn đã đặt"},
        "campaign": alloc.name,
        "spend_per_day_now": num(spend_now),
        "spend_per_day_after": num(spend_after),
        "roas_direct": ratio(roas, 2),
        "roas_broad": ratio(safe_div(alloc.gmv, alloc.spend), 2),
        "break_even_roas": ratio(be, 2),
        "below_break_even": None if be is None or roas is None else roas < be,
        "profit_before_ads_per_day": num(profit_before_ads),
        "profit_after_ads_at_current_revenue_per_day": num(profit_before_ads - spend_after),
        "max_budget_per_day_for_target_roas": None
        if not target_roas or target_roas <= 0
        else num(prof["direct_per_day"] / target_roas),
        "target_roas_vs_break_even": None
        if be is None or roas_after is None
        else {"target": ratio(roas_after, 2), "break_even": ratio(be, 2), "ok": roas_after >= be},
        "budget_binding": None
        if budget_before is None
        else spend_now >= budget_before * Decimal("0.95"),
    }
    certain["items"] = items
    pairs = env.view.pairs
    spend_window = alloc.spend
    before_snap = scope_snapshot(env, items or None, pairs, spend_window)
    after_snap = scope_snapshot(env, items or None, pairs, spend_window + dspend * env.window_days)
    _, five_dict = _five(env, before_snap, after_snap, needs_volume=dspend > 0)
    base_gmv_per_day = prof["direct_per_day"] * (
        item_share if kind in ("ads_remove_product", "ads_add_product") else ONE
    )
    if kind == "ads_add_product":
        pp = env.product(cand.item or "")
        rate = (
            safe_div(pp.contribution, pp.buyer_paid_covered)
            if pp and pp.buyer_paid_covered > 0
            else None
        )
        base_gmv_per_day = prof["direct_per_day"]
        ppg = rate
    else:
        ppg = prof["rate"]
    profit = ProfitModel(
        effect_days=config.DAYS_PER_MONTH,
        base_gmv_per_day=base_gmv_per_day,
        aov=None,
        profit_per_gmv=ppg,
        extra_cost_per_day=dspend,
        dchi_per_day=dspend,
        base_label="gmv_quang_cao_don_da_dat",
    )
    return Evaluation(
        certain=certain,
        five=five_dict,
        breaches=[],
        profit=profit,
        before=before_view,
        after=after_view,
        target=target,
        spend_check=_spend_check(env, dspend),
        notes=["Quảng cáo tính theo đơn đã đặt; không cộng vào tổng đơn đã xác nhận."],
    )


# ------------------------------------------------------------------------------ combo


def _bundle_line(line: OrderLine, qty: int, pct_off: Decimal) -> OrderLine:
    gross = line.deal_price * qty
    return replace(
        line,
        qty=qty,
        bundle_discount=to_dong(gross * pct_off / 100),
        shop_voucher_share=ZERO,
        order_id=f"bundle:{line.sku}:{qty}",
        promo_kind=PromoKind.NONE,
    )


def eval_bundle(
    env: RecoEnv, cand: Candidate, inputs: Mapping[str, Any], predicted: PredictedRange | None
) -> Evaluation:
    """Combo tiers / set size: per tier the bundle's margin and floor check, AOV and units per
    order; certain cost = the discount on today's orders that already carry that many units."""
    item = cand.item
    if item is None:
        return _refuse("no_item")
    lines = env.lines_for([item])
    skus = env.skus_of(item)
    if not lines or not skus:
        return _refuse("no_order_lines")
    tiers: dict[int, Decimal]
    if cand.kind == "variation_set":
        tiers = {int(inputs.get("set_size", 2)): D(inputs.get("set_discount_pct", 5))}
    else:
        tiers = {2: D(inputs.get("tier2_pct", 0)), 3: D(inputs.get("tier3_pct", 0))}
        tiers = {q: p for q, p in tiers.items() if p > 0}
    if not tiers:
        return _refuse("no_tier")
    schedule = env.schedule(item)
    window = Decimal(env.window_days)
    sku = max(skus, key=lambda s: sum((ln.order_value for ln in lines if ln.sku == s), ZERO))
    ref = max(
        (ln for ln in lines if ln.sku == sku and ln.product_id == item),
        key=lambda ln: ln.order_date,
    )
    floor = env.floors(item).get(sku)
    floor_px = env.floor_price(item, sku)
    single = profit_lines([_bundle_line(ref, 1, ZERO)], env.costs, schedule=schedule)[0][1]
    tier_rows: list[dict[str, Any]] = []
    breaches: list[dict[str, Any]] = []
    extra_cost = ZERO
    for qty, off in sorted(tiers.items()):
        bl = _bundle_line(ref, qty, off)
        pb = profit_lines([bl], env.costs, schedule=schedule)[0][1]
        unit_paid = pb.buyer_paid / qty
        breach = floor_px is not None and unit_paid < floor_px
        if breach and floor is not None:
            breaches.append(
                {
                    "sku": sku,
                    "kind": "operating" if floor.operating_floor is not None else "absolute",
                    "floor": num(floor_px),
                    "min_unit_price": num(unit_paid),
                    "lines": 1,
                    "tier": qty,
                }
            )
        history = [ln for ln in lines if ln.sku == sku and ln.product_id == item and ln.qty >= qty]
        cost = sum((to_dong(ln.deal_price * ln.qty * off / 100) for ln in history), ZERO)
        extra_cost += cost if qty == max(tiers) or not tier_rows else ZERO
        tier_rows.append(
            {
                "units": qty,
                "discount_pct": num(off),
                "unit_price_after": num(unit_paid),
                "bundle_net_revenue": num(pb.buyer_paid),
                "bundle_profit": num(pb.contribution),
                "margin_pct": pct(pct_points(safe_div(pb.contribution, pb.buyer_paid)))
                if pb.contribution is not None
                else None,
                "profit_per_unit": num(pb.contribution / qty)
                if pb.contribution is not None
                else None,
                "floor_operating": num(floor.operating_floor) if floor else None,
                "below_floor": bool(breach),
                "existing_orders_with_tier": len(history),
                "discount_cost_on_existing": num(cost),
                "aov_of_bundle": num(bl.order_value),
            }
        )
    extra_cost = sum((D(r["discount_cost_on_existing"] or 0) for r in tier_rows), ZERO)
    biggest = tier_rows[-1]
    gmv_item = sum((ln.order_value for ln in lines if ln.product_id == item), ZERO)
    orders_item = _scope_orders(env, [item])
    aov = safe_div(gmv_item, Decimal(orders_item)) if orders_item else None
    contrib = D(biggest["bundle_profit"]) if biggest["bundle_profit"] is not None else None
    ppg = safe_div(contrib, D(biggest["bundle_net_revenue"])) if contrib is not None else None
    profit = ProfitModel(
        effect_days=config.DAYS_PER_MONTH,
        base_gmv_per_day=_scope_gmv_per_day(env, [item]),
        base_orders_per_day=Decimal(orders_item) / window,
        aov=aov,
        profit_per_gmv=ppg,
        extra_cost_per_day=extra_cost / window,
        dchi_per_day=extra_cost / window,
    )
    pairs_before = profit_lines(lines, env.costs, schedule=schedule)
    sp = _scope_ad_spend(env, [item])
    snap = scope_snapshot(env, [item], pairs_before, sp)
    after_lines = [
        replace(
            ln,
            bundle_discount=to_dong(
                ln.deal_price * ln.qty * tiers[max(q for q in tiers if q <= ln.qty)] / 100
            ),
        )
        if ln.product_id == item and ln.qty >= min(tiers)
        else ln
        for ln in lines
    ]
    snap_after = scope_snapshot(
        env, [item], profit_lines(after_lines, env.costs, schedule=schedule), sp
    )
    _, five_dict = _five(env, snap, snap_after, needs_volume=True)
    certain = {
        "kind": "combo",
        "tiers": tier_rows,
        "single_unit_profit": num(single.contribution),
        "single_unit_margin_pct": pct(pct_points(safe_div(single.contribution, single.buyer_paid)))
        if single.contribution is not None
        else None,
        "units_per_order_now": num(
            safe_div(
                Decimal(sum(ln.qty for ln in lines if ln.product_id == item)), Decimal(orders_item)
            )
        ),
        "aov_now": num(aov),
        "extra_cost_on_existing_orders": num(extra_cost),
    }
    return Evaluation(
        certain=certain,
        five=five_dict,
        breaches=breaches,
        profit=profit,
        before={"tiers": []},
        after={"tiers": [{"units": q, "discount_pct": num(p)} for q, p in sorted(tiers.items())]},
        target={"item_id": item},
        spend_check=_spend_check(env, profit.dchi_per_day),
        floor_unknown_skus=_unknown_floors(env, [item]),
    )


def eval_add_on(
    env: RecoEnv, cand: Candidate, inputs: Mapping[str, Any], predicted: PredictedRange | None
) -> Evaluation:
    """Mua kèm deal sốc: main product A + add-on product B at a discount. Floor check on B."""
    main = cand.item
    addon = cand.extra.get("addon_item")
    if main is None or addon is None:
        return _refuse("no_addon")
    a_lines = env.lines_for([addon])
    if not a_lines:
        return _refuse("no_order_lines")
    off = D(inputs.get("addon_discount_pct", 0))
    sku = env.skus_of(addon)[0]
    ref = max(
        (ln for ln in a_lines if ln.product_id == addon and ln.sku == sku),
        key=lambda ln: ln.order_date,
    )
    sched = env.schedule(addon)
    line = _bundle_line(ref, 1, off)
    pb = profit_lines([line], env.costs, schedule=sched)[0][1]
    floor_px = env.floor_price(addon, sku)
    paid = pb.buyer_paid
    floor = env.floors(addon).get(sku)
    breaches = []
    if floor_px is not None and paid < floor_px:
        breaches.append(
            {
                "sku": sku,
                "kind": "operating" if floor and floor.operating_floor is not None else "absolute",
                "floor": num(floor_px),
                "min_unit_price": num(paid),
                "lines": 1,
            }
        )
    both = {ln.order_id for ln in env.lines_for([main]) if ln.product_id == main} & {
        ln.order_id for ln in a_lines if ln.product_id == addon
    }
    cost_existing = to_dong(ref.deal_price * off / 100) * len(both)
    window = Decimal(env.window_days)
    ppg = safe_div(pb.contribution, paid) if pb.contribution is not None else None
    base_gmv = _scope_gmv_per_day(env, [main])
    orders_main = _scope_orders(env, [main])
    aov = safe_div(base_gmv * window, Decimal(orders_main)) if orders_main else None
    profit = ProfitModel(
        effect_days=config.DAYS_PER_MONTH,
        base_gmv_per_day=base_gmv,
        base_orders_per_day=Decimal(orders_main) / window,
        aov=aov,
        profit_per_gmv=ppg,
        extra_cost_per_day=cost_existing / window,
        dchi_per_day=cost_existing / window,
    )
    certain = {
        "kind": "combo",
        "addon": {
            "item_id": addon,
            "price_before": num(ref.deal_price),
            "price_after": num(paid),
            "discount_pct": num(off),
            "profit_per_unit": num(pb.contribution),
            "margin_pct": pct(pct_points(safe_div(pb.contribution, paid)))
            if pb.contribution is not None
            else None,
            "floor": num(floor_px),
            "below_floor": bool(breaches),
            "orders_with_both_today": len(both),
            "discount_cost_on_existing": num(cost_existing),
        },
        "aov_now": num(aov),
    }
    return Evaluation(
        certain=certain,
        five=None,
        breaches=breaches,
        profit=profit,
        before={"addon_price": num(ref.deal_price)},
        after={"addon_item_id": addon, "addon_price": num(paid), "discount_pct": num(off)},
        target={"item_id": main, "addon_item_id": addon},
        spend_check=_spend_check(env, profit.dchi_per_day),
    )


def eval_gift(
    env: RecoEnv, cand: Candidate, inputs: Mapping[str, Any], predicted: PredictedRange | None
) -> Evaluation:
    """Quà tặng kèm: a gift item with a cost per qualifying order (giá vốn + đóng gói)."""
    main = cand.item
    gift = cand.extra.get("gift_item")
    lines = env.lines_for([main] if main else None)
    if not lines or gift is None:
        return _refuse("no_order_lines")
    min_spend = D(inputs.get("min_spend", 0))
    gift_sku = env.skus_of(gift)[0] if env.skus_of(gift) else None
    cost = env.costs.get(gift_sku) if gift_sku else None
    if cost is None or cost.cogs is None:
        return _refuse("gift_cost_unknown")
    gift_cost = cost.cogs + (cost.packaging or ZERO)
    by_order: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for ln in lines:
        by_order[ln.order_id] += ln.order_value
    qualifying = [o for o, v in by_order.items() if v >= min_spend]
    total_cost = gift_cost * len(qualifying)
    pairs = profit_lines(lines, env.costs, schedule=env.schedule(main or ""))
    contrib = [
        pb.contribution
        for _, pb in pairs
        if pb.excluded_reason is None and pb.contribution is not None
    ]
    n_orders = len(by_order)
    cpo = sum(contrib, ZERO) / Decimal(n_orders) if contrib and n_orders else None
    window = Decimal(env.window_days)
    be = None if not cpo or cpo <= 0 else math.ceil(total_cost / cpo)
    gmv_per_order = safe_div(sum(by_order.values(), ZERO), Decimal(n_orders))
    profit = ProfitModel(
        effect_days=config.DAYS_PER_MONTH,
        base_gmv_per_day=_scope_gmv_per_day(env, [main] if main else None),
        base_orders_per_day=Decimal(n_orders) / window,
        aov=gmv_per_order,
        profit_per_gmv=safe_div(cpo, gmv_per_order) if cpo is not None and gmv_per_order else None,
        extra_cost_per_day=total_cost / window,
        dchi_per_day=total_cost / window,
    )
    certain = {
        "kind": "combo",
        "gift": {
            "item_id": gift,
            "cost_per_gift": num(gift_cost),
            "qualifying_orders": len(qualifying),
            "total_orders": n_orders,
            "gift_cost_window": num(total_cost),
            "break_even_extra_orders": be,
        },
    }
    return Evaluation(
        certain=certain,
        five=None,
        breaches=[],
        profit=profit,
        before={},
        after={"gift_item_id": gift, "min_spend": num(min_spend)},
        target={"item_id": main, "gift_item_id": gift},
        spend_check=_spend_check(env, profit.dchi_per_day),
    )


# -------------------------------------------------------------------------- affiliate


def current_commission_pct(env: RecoEnv, item: str) -> Decimal | None:
    est = env.view.data.affiliate.product_commission.get(item)
    gmv = ZERO
    if env.view.flows is not None:
        table = env.view.flows.products.get(item)
        if table is not None:
            gmv = sum((r.gmv for r in table.rows if r.key == "lien_ket"), ZERO)
    if est is None or gmv <= 0:
        return None
    return est / gmv * 100


def eval_affiliate(
    env: RecoEnv, cand: Candidate, inputs: Mapping[str, Any], predicted: PredictedRange | None
) -> Evaluation:
    item = cand.item
    if item is None:
        return _refuse("no_item")
    lines = env.lines_for([item])
    if not lines:
        return _refuse("no_order_lines")
    new_rate = D(inputs["commission_pct"]) / 100
    cur = current_commission_pct(env, item)
    schedule = env.schedule(item)
    window = Decimal(env.window_days)
    aff_lines = [ln for ln in lines if ln.product_id == item and ln.affiliate]
    reprice = [replace(ln, commission=None, affiliate=True) if ln.affiliate else ln for ln in lines]
    before_pairs = profit_lines(lines, env.costs, schedule=schedule)
    after_pairs = profit_lines(reprice, env.costs, schedule=schedule, affiliate_rate=new_rate)
    comm_before = sum(
        (pb.commission or ZERO for ln, pb in before_pairs if ln.product_id == item), ZERO
    )
    comm_after = sum(
        (pb.commission or ZERO for ln, pb in after_pairs if ln.product_id == item), ZERO
    )
    sp = _scope_ad_spend(env, [item])
    before_snap = scope_snapshot(env, [item], before_pairs, sp)
    after_snap = scope_snapshot(env, [item], after_pairs, sp)
    _, five_dict = _five(env, before_snap, after_snap, needs_volume=True)
    floors_raw = env.floors(item)
    breaches: list[dict[str, Any]] = []
    unit_rows = []
    for sku, fl in floors_raw.items():
        mine = [(ln, pb) for ln, pb in after_pairs if ln.sku == sku and pb.excluded_reason is None]
        units = sum(ln.qty for ln, _ in mine)
        if not units:
            continue
        unit_paid = sum((pb.revenue for _, pb in mine), ZERO) / units
        # operating floor with the new commission rate (contract 6)
        floor_px = _floor_with_commission(env, item, sku, new_rate)
        if floor_px is not None and unit_paid < floor_px:
            breaches.append(
                {
                    "sku": sku,
                    "kind": "operating",
                    "floor": num(floor_px),
                    "min_unit_price": num(unit_paid),
                    "lines": len(mine),
                }
            )
        unit_rows.append(
            {"sku": sku, "unit_net_revenue": num(unit_paid), "floor_with_commission": num(floor_px)}
        )
    aff_orders = len({ln.order_id for ln in aff_lines})
    lien_ket_gmv = _flow_gmv(env, item, "lien_ket")
    gmv_item = sum((ln.order_value for ln in lines if ln.product_id == item), ZERO)
    n_orders = _scope_orders(env, [item])
    aov = safe_div(gmv_item, Decimal(n_orders)) if n_orders else None
    contrib_after = sum(
        (
            pb.contribution or ZERO
            for ln, pb in after_pairs
            if ln.product_id == item and pb.excluded_reason is None
        ),
        ZERO,
    )
    paid_after = sum(
        (
            pb.revenue
            for ln, pb in after_pairs
            if ln.product_id == item and pb.excluded_reason is None
        ),
        ZERO,
    )
    aff_paid = sum(
        (
            pb.revenue
            for ln, pb in after_pairs
            if ln.product_id == item and ln.affiliate and pb.excluded_reason is None
        ),
        ZERO,
    )
    aff_contrib = sum(
        (
            pb.contribution or ZERO
            for ln, pb in after_pairs
            if ln.product_id == item and ln.affiliate and pb.excluded_reason is None
        ),
        ZERO,
    )
    ppg = (
        safe_div(aff_contrib, aff_paid)
        if aff_paid > 0
        else safe_div(contrib_after, paid_after)
        if paid_after > 0
        else None
    )
    profit = ProfitModel(
        effect_days=config.DAYS_PER_MONTH,
        base_gmv_per_day=lien_ket_gmv / window,
        base_orders_per_day=Decimal(aff_orders) / window,
        aov=aov,
        profit_per_gmv=ppg,
        extra_cost_per_day=(comm_after - comm_before) / window,
        dchi_per_day=(comm_after - comm_before) / window,
        base_label="gmv_lien_ket",
    )
    certain = {
        "kind": "affiliate",
        "commission_pct_before": None if cur is None else num(round(cur, 2)),
        "commission_pct_after": num(new_rate * 100),
        "commission_cost_before": num(comm_before),
        "commission_cost_after": num(comm_after),
        "commission_per_affiliate_order_after": num(safe_div(comm_after, Decimal(aff_orders)))
        if aff_orders
        else None,
        "affiliate_orders": aff_orders,
        "skus": unit_rows,
        "margin_after_pct": pct(pct_points(safe_div(contrib_after, paid_after))),
    }
    return Evaluation(
        certain=certain,
        five=five_dict,
        breaches=breaches,
        profit=profit,
        before={"commission_pct": None if cur is None else num(round(cur, 2))},
        after={"commission_pct": num(new_rate * 100)},
        target={"item_id": item},
        spend_check=_spend_check(env, profit.dchi_per_day),
        floor_unknown_skus=_unknown_floors(env, [item]),
        notes=[] if cur is not None else ["Chưa biết hoa hồng hiện tại của sản phẩm này."],
    )


def _floor_with_commission(env: RecoEnv, item: str, sku: str, rate: Decimal) -> Decimal | None:
    """Operating floor of the SKU with ``rate`` as its affiliate commission rate."""
    from juli_backend.services.shopee_profit.floor import FloorInputs, compute_floor

    view = env.view
    formula = view.fees.schedule(item).formula_on(env.as_of)
    cost = view.costs.by_key.get(sku)
    if formula is None or cost is None:
        return None
    items = [
        pb
        for ln, pb in view.pairs
        if ln.product_id == item and ln.sku == sku and pb.excluded_reason is None
    ]
    paid = sum((pb.revenue for pb in items), ZERO)
    product = env.product(item)
    paid_total = product.buyer_paid if product else ZERO
    spend = view.ads.product_spend.get(item, ZERO)
    ad_rate = safe_div(spend * paid / paid_total, paid) if paid > 0 and paid_total > 0 else ZERO
    margin = env.margin_target_rate
    res = compute_floor(
        FloorInputs(
            list_price=view.costs.list_price.get(sku),
            cogs=cost.cogs,
            packaging=cost.packaging,
            fixed_fee_per_order=formula.fixed_per_order,
            platform_fee_rate=formula.pct_rate_on_buyer_paid,
            ads_rate=ad_rate or ZERO,
            affiliate_rate=rate,
            target_margin_rate=margin,
        )
    )
    return res.operating_floor if res.operating_floor is not None else res.absolute_floor


def _flow_gmv(env: RecoEnv, item: str, flow_key: str) -> Decimal:
    if env.view.flows is None:
        return ZERO
    table = env.view.flows.products.get(item)
    if table is None:
        return ZERO
    return sum((r.gmv for r in table.rows if r.key == flow_key), ZERO)


# ---------------------------------------------------------------------------- listing


def listing_base(env: RecoEnv, item: str, kind: str) -> tuple[Decimal, str]:
    """GMV per day the lever can move, and which GMV it is: a title / keyword moves search
    views (the Thẻ sản phẩm "search" child when the daily per-source rows exist), a cover or
    price display moves the click rate on the product card (Thẻ sản phẩm outside Trang shop).
    No flow data for the product = 0: nothing is predicted from a base that is not known."""
    window = Decimal(env.window_days)
    if kind in ("title", "keyword"):
        kids = env.view.data.product_flows.children.get(item)
        search = None if not kids else kids.get("search")
        if search is not None and search.views:
            return search.gmv / window, "gmv_tim_kiem"
    return _flow_gmv(env, item, "the_san_pham_khac") / window, "gmv_the_san_pham"


def _listing_before_after(
    kind: str, cand: Candidate, inputs: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    x = cand.extra
    if kind == "title":
        old, new = x["current_title"], str(inputs["title"])
        return {"title": old, "chars": len(old)}, {"title": new, "chars": len(new)}
    if kind == "keyword":
        promote, demote = inputs["promote"], inputs.get("demote")
        before = list(x["core_before"])
        after = [k for k in before if k != demote] + ([promote] if promote not in before else [])
        return {"core": before}, {"core": after, "promote": promote, "demote": demote}
    return (
        {"cover_url": x.get("cover_url"), "text": x.get("before_text")},
        {"text": x.get("after_text"), "line": x.get("line")},
    )


def eval_listing(
    env: RecoEnv, cand: Candidate, inputs: Mapping[str, Any], predicted: PredictedRange | None
) -> Evaluation:
    """Title / keyword / cover / price display: a traffic lever, so no certain layer (the card
    says so); the predicted range comes from the lift model on views (title, keyword) or CTR
    (cover, price display), over the GMV the lever can reach."""
    from juli_backend.services.shopee_recommendations import listing as lst

    item = cand.item
    if item is None or item not in env.listings:
        return _refuse("no_listing")
    kind = cand.kind
    certain: dict[str, Any] = {
        "kind": "listing",
        "traffic_lever": True,
        "note": "Đổi hiển thị chỉ tác động lượt xem / tỉ lệ bấm nên không có phần chắc chắn về "
        "doanh thu hay lợi nhuận; chỉ có phần dự kiến.",
    }
    notes: list[str] = []
    if kind == "title":
        new_title = str(inputs.get("title") or "").strip()
        if not new_title or len(new_title) > config.MAX_TITLE_CHARS:
            return _refuse("title_length")
        if not lst.is_clean(new_title, env.banned_terms):
            return _refuse("banned_term")
        core = cand.extra.get("core", [])
        certain["audit_before"] = lst.audit_title(cand.extra["current_title"], core).json()
        certain["audit_after"] = lst.audit_title(new_title, core).json()
        certain["banned_terms_in_title"] = 0
        notes += cand.extra.get("notes", [])
        inputs = {**inputs, "title": new_title}
    elif kind == "keyword":
        if inputs.get("promote") is None:
            return _refuse("no_keyword")
        certain["core_slots"] = {
            "used": len(cand.extra["core_before"]),
            "max": config.MAX_CORE_KEYWORDS,
        }
    before, after = _listing_before_after(kind, cand, inputs)
    gmv_day, base_label = listing_base(env, item, kind)
    pp = env.product(item)
    ppg = safe_div(pp.contribution, pp.buyer_paid_covered) if pp else None
    n_orders = _scope_orders(env, [item])
    gmv_item = sum((ln.order_value for ln, _ in env.view.pairs if ln.product_id == item), ZERO)
    window = Decimal(env.window_days)
    profit = ProfitModel(
        effect_days=config.DAYS_PER_MONTH,
        base_gmv_per_day=gmv_day,
        base_orders_per_day=Decimal(n_orders) / window,
        aov=safe_div(gmv_item, Decimal(n_orders)) if n_orders else None,
        profit_per_gmv=ppg,
        base_label=base_label,
    )
    if gmv_day <= 0:
        notes.append("Chưa có lưu lượng theo nguồn của sản phẩm này: chưa dự kiến được.")
    return Evaluation(
        certain=certain,
        five=None,
        breaches=[],
        profit=profit,
        before=before,
        after=after,
        target={"item_id": item},
        spend_check=_spend_check(env, ZERO),
        notes=notes,
    )


# ------------------------------------------------------------------------------ entry

_EVALUATORS = {
    "voucher": eval_voucher,
    "price": eval_price,
    "ads": eval_ads,
    "bundle": eval_bundle,
    "add_on": eval_add_on,
    "gift": eval_gift,
    "affiliate": eval_affiliate,
    "listing": eval_listing,
}


def evaluator_key(kind: str) -> str:
    s = spec(kind)
    if s.family == "voucher":
        return "voucher"
    if s.family in ("promotion", "sale"):
        return "price"
    if s.family == "ads":
        return "ads"
    if s.family == "affiliate":
        return "affiliate"
    if s.family == "listing":
        return "listing"
    return {"add_on": "add_on", "gift": "gift"}.get(kind, "bundle")


def evaluate(
    env: RecoEnv,
    cand: Candidate,
    *,
    inputs: Mapping[str, Any] | None = None,
    predicted: PredictedRange | None = None,
) -> Evaluation:
    """The certain layer of ``cand`` (optionally with other ``inputs`` -- the what-if)."""
    use = dict(cand.inputs if inputs is None else inputs)
    if spec(cand.kind).family == "mega_sale":
        raise ValueError("mega_sale is evaluated by mega.evaluate_mega")
    return _EVALUATORS[evaluator_key(cand.kind)](env, cand, use, predicted)
