"""`mega_sale`: a composite card for a campaign window (e.g. 11/11) built from the other
families (contract 12).

Children (price levers, vouchers, combos, ads, affiliate) share ONE schedule, ONE budget cap
and ONE approval. The certain layer is NOT the sum of the children's own layers (they would
count the same order twice): the window's historical orders are re-priced ONCE with every
child stacked on them -- promo / flash price first, combo discount on lines that reach a tier,
the shop voucher on the order subtotal after those -- and compared with the same orders at
today's prices. Each line then carries exactly one price lever by precedence
combo > khuyen_mai > voucher (contract 3), so the by-lever table adds up to the total discount.
Floors are checked per SKU against the worst stack a buyer can get. The bundle is measured
as one (ADR-121 d.4): its children are never credited separately and the kind is excluded
from per-kind calibration.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from juli_backend.services.shopee_analytics.fmt import num, pct
from juli_backend.services.shopee_analytics.shared import five_json
from juli_backend.services.shopee_profit.five_numbers import (
    five_numbers,
    snapshot_from_orders,
)
from juli_backend.services.shopee_profit.money import ONE, ZERO, pct_points, safe_div, to_dong
from juli_backend.services.shopee_profit.order_profit import (
    OrderLine,
    ProfitBreakdown,
    profit_lines,
)
from juli_backend.services.shopee_recommendations import config, freshness
from juli_backend.services.shopee_recommendations.env import RecoEnv
from juli_backend.services.shopee_recommendations.evaluate import (
    D,
    evaluate,
    evaluator_key,
    new_price,
    voucher_rule_from,
)
from juli_backend.services.shopee_recommendations.kinds import FAMILY_LABELS, spec
from juli_backend.services.shopee_recommendations.model import Candidate, ProfitModel
from juli_backend.services.shopee_recommendations.plan import measurement_plan, stats_for
from juli_backend.services.shopee_recommendations.prediction import Lift, convert
from juli_backend.services.shopee_recommendations.sheet import build_sheet

PRICE_KINDS = ("product_discount", "flash_sale", "program_registration", "price")
BUNDLE_KINDS = ("bundle_deal", "variation_set")
VOUCHER_KINDS = ("min_spend_voucher", "review_voucher", "voucher_cap")
ADS_KINDS = (
    "ads_budget",
    "ads_roas_target",
    "ads_pause",
    "ads_add_product",
    "ads_remove_product",
    "ads_purpose",
)
MAX_CHILDREN = 12


@dataclass(frozen=True)
class MegaWindow:
    start: datetime
    end: datetime

    @property
    def days(self) -> int:
        return max(int((self.end - self.start).total_seconds() // 86400), 1)

    def json(self) -> dict[str, Any]:
        return {"start": self.start.isoformat(), "end": self.end.isoformat(), "days": self.days}


def _tiers(inputs: Mapping[str, Any], kind: str) -> dict[int, Decimal]:
    if kind == "variation_set":
        return {int(inputs.get("set_size", 2)): D(inputs.get("set_discount_pct", 5))}
    t = {2: D(inputs.get("tier2_pct", 0)), 3: D(inputs.get("tier3_pct", 0))}
    return {q: p for q, p in t.items() if p > 0}


def precedence_lever(ln: OrderLine) -> str:
    """Contract 3: combo > khuyen_mai > voucher > khong_uu_dai; exactly one per line."""
    if ln.bundle_discount > 0:
        return "combo"
    if ln.original_price * ln.qty > ln.order_value:
        return "khuyen_mai"
    if ln.shop_voucher_share > 0:
        return "voucher"
    return "khong_uu_dai"


def _groups(
    pairs: Sequence[tuple[OrderLine, ProfitBreakdown]],
) -> dict[str, list[tuple[OrderLine, ProfitBreakdown]]]:
    out: dict[str, list[tuple[OrderLine, ProfitBreakdown]]] = defaultdict(list)
    for ln, pb in pairs:
        out[ln.order_id].append((ln, pb))
    return dict(out)


def _profit(env: RecoEnv, lines: Sequence[OrderLine]) -> list[tuple[OrderLine, ProfitBreakdown]]:
    """Waterfall per fee schedule: whole orders are grouped by the schedule of their first
    line's product (per-order fees are charged once per order)."""
    by_order: dict[str, list[OrderLine]] = defaultdict(list)
    for ln in lines:
        by_order[ln.order_id].append(ln)
    by_sched: dict[int, list[OrderLine]] = defaultdict(list)
    scheds: dict[int, Any] = {}
    for oid, group in by_order.items():
        sched = env.schedule(group[0].product_id)
        by_sched[id(sched)].extend(group)
        scheds[id(sched)] = sched
    out: dict[tuple[str, int], tuple[OrderLine, ProfitBreakdown]] = {}
    for key, group in by_sched.items():
        for i, pair in enumerate(profit_lines(group, env.costs, schedule=scheds[key])):
            out[(group[i].order_id, id(group[i]))] = pair
    return [out[(ln.order_id, id(ln))] for ln in lines]


def _apply_voucher(lines: list[OrderLine], rule: Any) -> tuple[list[OrderLine], set[str], Decimal]:
    by_order: dict[str, list[OrderLine]] = defaultdict(list)
    for ln in lines:
        by_order[ln.order_id].append(ln)
    out: list[OrderLine] = []
    qual: set[str] = set()
    total = ZERO
    for oid, group in by_order.items():
        subtotal = sum((ln.order_value for ln in group), ZERO)
        discount = rule.discount_for(subtotal)
        if discount > 0:
            qual.add(oid)
        total += discount
        left = discount
        for i, ln in enumerate(group):
            share = (
                left
                if i == len(group) - 1
                else (to_dong(discount * ln.order_value / subtotal) if discount > 0 else ZERO)
            )
            left -= share
            out.append(replace(ln, shop_voucher_share=ln.shop_voucher_share + share))
    return out, qual, total


def evaluate_mega(
    env: RecoEnv,
    children: Sequence[Candidate],
    window: MegaWindow,
    budget_cap_per_day: Decimal | None,
) -> dict[str, Any]:
    """The stacked certain layer of a mega_sale. Returns the pieces ``build_mega_card`` freezes."""
    days = window.days
    scale = Decimal(days) / Decimal(env.window_days)
    child_items = sorted({i for c in children for i in c.items})
    price_children = [c for c in children if c.kind in PRICE_KINDS]
    bundle_children = [c for c in children if c.kind in BUNDLE_KINDS]
    voucher_children = [c for c in children if c.kind in VOUCHER_KINDS]
    other_children = [
        c for c in children if c.kind not in PRICE_KINDS + BUNDLE_KINDS + VOUCHER_KINDS
    ]

    scope_items = child_items or None
    raw_lines = env.lines_for(scope_items)
    if not raw_lines:
        return {"refusal": "no_order_lines"}
    # like for like (as the voucher what-if recomputes both sides): the vouchers and combos the
    # history happened to carry are taken off both the baseline and the scenario, so the
    # children below are the only vouchers / combos in the window
    base_lines = [replace(ln, shop_voucher_share=ZERO, bundle_discount=ZERO) for ln in raw_lines]
    # 1) price levers: new deal price per SKU
    price_by_sku: dict[str, Decimal] = {}
    for c in price_children:
        for sku in env.skus_of(c.items[0]):
            p = new_price(env, c.kind, sku, c.inputs)
            if p is not None:
                price_by_sku[sku] = min(p, price_by_sku.get(sku, p))
    tiers: dict[str, dict[int, Decimal]] = {}
    for c in bundle_children:
        for sku in env.skus_of(c.items[0]):
            tiers[sku] = _tiers(c.inputs, c.kind)
    free_lines: list[OrderLine] = []
    for ln in base_lines:
        new = price_by_sku.get(ln.sku)
        cur = replace(ln, deal_price=min(new, ln.deal_price)) if new is not None else ln
        t = tiers.get(ln.sku)
        if t:
            eligible = [q for q in t if q <= cur.qty]
            if eligible:
                off = t[max(eligible)]
                cur = replace(cur, bundle_discount=to_dong(cur.deal_price * cur.qty * off / 100))
        free_lines.append(cur)
    # 2) voucher on top, for the orders that use it
    vou_lines: list[OrderLine] | None = None
    qualifying: set[str] = set()
    phi = ZERO
    voucher_cost = ZERO
    if voucher_children:
        v = voucher_children[0]
        rule = voucher_rule_from({**v.inputs, "quantity": v.inputs.get("quantity")})
        vou_lines, qualifying, voucher_cost = _apply_voucher(list(free_lines), rule)
        q_expected = Decimal(len(qualifying)) * scale
        u = env.usage_rate if env.usage_rate is not None else ONE
        used = q_expected * u
        if rule.usage_limit is not None:
            used = min(used, Decimal(rule.usage_limit))
        phi = used / q_expected if q_expected > 0 else ZERO
    base_pairs = _profit(env, base_lines)
    free_pairs = _profit(env, free_lines)
    vou_pairs = _profit(env, vou_lines) if vou_lines is not None else None
    base_groups = _groups(base_pairs)
    free_groups = _groups(free_pairs)
    vou_groups = _groups(vou_pairs) if vou_pairs is not None else {}
    weighted_after: list[tuple[Decimal, Any]] = []
    for oid, g in free_groups.items():
        if oid in qualifying and oid in vou_groups:
            weighted_after.append((scale * phi, vou_groups[oid]))
            weighted_after.append((scale * (ONE - phi), g))
        else:
            weighted_after.append((scale, g))
    # 3) spend of the non-line children (ads, affiliate, add-on, gift)
    other_dchi = ZERO
    other_json: list[dict[str, Any]] = []
    ads_before = env.view.ads.total_spend
    ads_delta_day = ZERO
    for c in other_children:
        ev = evaluate(env, c)
        if ev.refusal:
            other_json.append({"kind": c.kind, "refusal": ev.refusal})
            continue
        other_dchi += ev.profit.dchi_per_day
        if spec(c.kind).family == "ads":
            ads_delta_day += ev.profit.dchi_per_day
        other_json.append({"kind": c.kind, "dchi_per_day": num(ev.profit.dchi_per_day)})
    ads_window_before = ads_before * scale
    ads_window_after = ads_window_before + ads_delta_day * days
    snap_before = snapshot_from_orders(
        [(scale, g) for g in base_groups.values()], ads_window_before, days=Decimal(days)
    )
    snap_after = snapshot_from_orders(weighted_after, ads_window_after, days=Decimal(days))
    five = five_numbers(snap_before, snap_after, spend_cap=env.daily_cap)
    from dataclasses import replace as _r

    five = _r(
        five,
        extra_revenue_per_extra_spend=None,
        extra_revenue_pct=None,
        chi_status="needs_volume",
        below_one=False,
    )
    # chi per day of the whole shop in the window, with the non-line children's spend
    chi_after_day = (snap_after.chi / Decimal(days)) + (other_dchi - ads_delta_day)
    chi_before_day = snap_before.chi / Decimal(days)
    cap_days = {
        "cap_per_day": num(budget_cap_per_day),
        "shop_cap_per_day": num(env.daily_cap),
        "mega_chi_per_day": num(chi_after_day),
        "baseline_chi_per_day": num(chi_before_day),
        "over_budget": None if budget_cap_per_day is None else chi_after_day > budget_cap_per_day,
        "over_shop_cap": None if env.daily_cap is None else chi_after_day > env.daily_cap,
    }
    # 4) levers: each line exactly one, by precedence; discount adds up
    lever_rows: dict[str, dict[str, Any]] = {
        k: {"lines": 0, "discount": ZERO}
        for k in ("combo", "khuyen_mai", "voucher", "khong_uu_dai")
    }
    total_discount = ZERO
    for oid, g in free_groups.items():
        use = vou_groups[oid] if oid in qualifying and oid in vou_groups and phi > 0 else g
        for ln, pb in use:
            lever = precedence_lever(ln)
            disc = ln.original_price * ln.qty - pb.buyer_paid
            lever_rows[lever]["lines"] += 1
            lever_rows[lever]["discount"] += disc
            total_discount += disc
    # 5) floors across the stack: worst unit price per SKU
    worst: dict[str, Decimal] = {}
    for pairs in (free_pairs, vou_pairs or []):
        for ln, pb in pairs:
            unit = pb.buyer_paid / ln.qty
            worst[ln.sku] = min(unit, worst.get(ln.sku, unit))
    base_worst: dict[str, Decimal] = {}
    for ln, pb in base_pairs:
        unit = pb.buyer_paid / ln.qty
        base_worst[ln.sku] = min(unit, base_worst.get(ln.sku, unit))
    breaches: list[dict[str, Any]] = []
    sku_rows: list[dict[str, Any]] = []
    item_of = {ln.sku: ln.product_id for ln in base_lines}
    for sku, unit in sorted(worst.items()):
        item = item_of[sku]
        floor = env.floors(item).get(sku)
        floor_px = env.floor_price(item, sku)
        changed = sku in price_by_sku or sku in tiers or bool(voucher_children)
        # a stack breaks a floor only if it takes the SKU lower than the history already was
        below = (
            floor_px is not None
            and unit < floor_px
            and changed
            and unit < base_worst.get(sku, unit)
        )
        if below and floor is not None:
            breaches.append(
                {
                    "sku": sku,
                    "kind": "operating" if floor.operating_floor is not None else "absolute",
                    "floor": num(floor_px),
                    "min_unit_price": num(unit),
                    "stacked": True,
                }
            )
        if changed:
            sku_rows.append(
                {
                    "sku": sku,
                    "worst_unit_net_revenue": num(unit),
                    "floor": num(floor_px),
                    "below_floor": bool(below),
                }
            )
    # 6) the bundle's ProfitModel (one lift for the whole bundle)
    contrib_after = snap_after.contribution
    paid_after = snap_after.buyer_paid
    orders_after = snap_after.orders
    dprofit_certain = (snap_after.contribution - snap_after.ad_spend) - (
        snap_before.contribution - snap_before.ad_spend
    )
    d = Decimal(days)
    profit = ProfitModel(
        effect_days=days,
        base_gmv_per_day=sum(
            (
                ln.order_value
                for ln in base_lines
                if not scope_items or ln.product_id in scope_items
            ),
            ZERO,
        )
        / Decimal(env.window_days),
        base_orders_per_day=Decimal(len({ln.order_id for ln in base_lines}))
        / Decimal(env.window_days),
        aov=safe_div(snap_after.gmv, orders_after) if orders_after else None,
        profit_per_gmv=safe_div(contrib_after, paid_after) if paid_after > 0 else None,
        extra_cost_per_day=-dprofit_certain / d,
        certain_dgmv_per_day=(snap_after.gmv - snap_before.gmv) / d,
        dchi_per_day=chi_after_day - chi_before_day,
    )
    certain = {
        "kind": "mega_sale",
        "window": window.json(),
        "orders_in_window_expected": num(snap_before.orders),
        "total_discount": num(total_discount * scale),
        "by_lever": [
            {"lever": k, "lines": v["lines"], "discount": num(v["discount"] * scale)}
            for k, v in lever_rows.items()
        ],
        "by_lever_adds_up": sum((v["discount"] for v in lever_rows.values()), ZERO)
        == total_discount,
        "voucher": None
        if not voucher_children
        else {
            "qualifying_orders": len(qualifying),
            "used_fraction": num(round(phi, 4)),
            "cost": num(voucher_cost * scale * phi),
        },
        "spend": cap_days,
        "skus": sku_rows,
        "dprofit_same_volume": num(dprofit_certain),
        "no_double_counting": "Đơn được tính lại một lần với mọi thay đổi chồng lên nhau; mỗi "
        "dòng đơn một đòn bẩy giá (combo > khuyến mãi > voucher).",
        "other_children": other_json,
    }
    return {
        "certain": certain,
        "five": five_json(five),
        "breaches": breaches,
        "profit": profit,
        "chi_after_day": chi_after_day,
        "cap": cap_days,
        "refusal": None,
    }


def fit_children(
    env: RecoEnv,
    children: Sequence[Candidate],
    window: MegaWindow,
    cap: Decimal | None,
) -> tuple[list[Candidate], list[dict[str, Any]]]:
    """Drop children, lowest-ranked first, until the stack keeps every SKU above its floor and
    the window's chi per day inside the cap. Returns the kept children (rank order kept) and
    what was dropped and why -- the card never ships a stack that breaks either rule."""
    kept = list(children)
    removed: list[dict[str, Any]] = []
    while kept:
        res = evaluate_mega(env, kept, window, cap)
        if res.get("refusal"):
            break
        over = bool(res["cap"]["over_budget"])
        if not res["breaches"] and not over:
            break
        pick = None
        reason = "over_budget"
        if res["breaches"]:
            reason = "stacked_floor"
            skus = {b["sku"] for b in res["breaches"]}
            breached = {i for i in env.item_ids() if skus & set(env.skus_of(i))}
            pick = next((c for c in reversed(kept) if breached & set(c.items)), None)
            if pick is None:  # a shop-wide voucher on mixed orders breaks another product
                pick = next((c for c in reversed(kept) if c.kind in VOUCHER_KINDS), None)
        if pick is None:
            pick = kept[-1]
        kept.remove(pick)
        removed.append({"kind": pick.kind, "reason": reason})
    return kept, removed


def schedule_for(
    window: MegaWindow, children: Sequence[Candidate], child_ids: Sequence[str]
) -> list[dict[str, Any]]:
    """Day-by-day on / off times: every child goes live at the window start and off at its end;
    ads children ramp from the day before (budget up 24 h ahead is a choice the person makes)."""
    out: list[dict[str, Any]] = []
    first = window.start.date()
    last = (window.end - timedelta(seconds=1)).date()
    day = first
    while day <= last:
        events: list[dict[str, Any]] = []
        for c, cid in zip(children, child_ids, strict=True):
            if day == first:
                events.append(
                    {
                        "child_id": cid,
                        "kind": c.kind,
                        "action": "bat",
                        "at": window.start.strftime("%H:%M"),
                    }
                )
            if day == last:
                events.append(
                    {
                        "child_id": cid,
                        "kind": c.kind,
                        "action": "tat",
                        "at": window.end.strftime("%H:%M"),
                    }
                )
        out.append({"date": day.isoformat(), "events": events})
        day += timedelta(days=1)
    return out


def build_mega_card(
    env: RecoEnv,
    children: Sequence[Candidate],
    window: MegaWindow,
    *,
    now: datetime,
    budget_cap_per_day: Decimal | None = None,
    child_ids: Sequence[str] | None = None,
    source_card_ids: Sequence[str | None] | None = None,
    title: str | None = None,
) -> dict[str, Any] | None:
    if not children or len(children) > MAX_CHILDREN:
        return None
    cap = budget_cap_per_day if budget_cap_per_day is not None else env.daily_cap
    res = evaluate_mega(env, children, window, cap)
    if res.get("refusal"):
        return None
    s = spec("mega_sale")
    profit: ProfitModel = res["profit"]
    from juli_backend.services.shopee_recommendations.prediction import gap_bucket, prior_range

    bucket = gap_bucket(None)
    lo, hi = prior_range(s, None, bucket)
    lift = Lift(
        s.target_metric,
        lo,
        hi,
        1.0,
        "prior",
        1.0,
        bucket,
        {"applied": False, "note": "bundle: not calibrated per kind"},
    )
    money = convert(lift, profit)
    ids = list(child_ids or [f"child-{i + 1}" for i in range(len(children))])
    child_json: list[dict[str, Any]] = []
    for i, (c, cid) in enumerate(zip(children, ids, strict=True)):
        ev = None if spec(c.kind).family == "mega_sale" else evaluate(env, c)
        sheet = (
            build_sheet(c.kind, ev.target, ev.before, ev.after, dict(c.inputs))
            if ev and not ev.refusal
            else None
        )
        child_json.append(
            {
                "child_id": cid,
                "source_card_id": None if not source_card_ids else source_card_ids[i],
                "change_kind": c.kind,
                "family": spec(c.kind).family,
                "label": spec(c.kind).label,
                "items": list(c.items),
                "campaign_key": c.campaign_key,
                "inputs": dict(c.inputs),
                "extra": dict(c.extra),
                "evaluator": evaluator_key(c.kind),
                "summary": None if ev is None or ev.refusal else ev.after,
                "page": None if sheet is None else sheet["page"],
                "changes": [] if sheet is None else sheet["changes"],
                "starts": window.start.isoformat(),
            }
        )
    locked = sorted({i for c in children for i in c.items})
    sheet = build_sheet(
        "mega_sale",
        {},
        {},
        {},
        {},
        time_window=window.json(),
        children=child_json,
    )
    plan = measurement_plan("orders", stats_for(env, locked or None, "orders"))
    dprofit_p50 = money["total"]["p50"]["dprofit"]
    if dprofit_p50 is None:
        dprofit_p50 = money["certain"]["dprofit"]
    card: dict[str, Any] = {
        "schema": config.SCHEMA,
        "family": "mega_sale",
        "family_label": FAMILY_LABELS["mega_sale"],
        "change_kind": "mega_sale",
        "title": title
        or f"Mega sale {window.start:%d/%m} — {len(children)} thay đổi, "
        "một ngân sách, một lần duyệt",
        "reason": "Các thay đổi được xếp chung một lịch, một trần chi, tính trên cùng các đơn "
        "(không cộng trùng).",
        "platform": "shopee",
        "model_version": config.MODEL_VERSION,
        "generated_at": now.isoformat(),
        "as_of": env.as_of.isoformat(),
        "window": env.view.window.json(),
        "mega_window": window.json(),
        "order_basis": {"key": "confirmed", "label": "Đơn đã xác nhận"},
        "metric": {
            "key": "orders",
            "critical_id": None,
            "critical_kpi": None,
            "flow": None,
            "at_stake_per_day": None,
        },
        "wiring": {"critical_metric": None, "allowed_kinds": [c.kind for c in children]},
        "scope": {
            "level": "shop",
            "product_ids": locked,
            "sku_ids": sorted({sk for i in locked for sk in env.skus_of(i)}),
            "campaign_key": None,
        },
        "change": {
            "change_kind": "mega_sale",
            "target": {"children": ids},
            "before": {},
            "after": {"window": window.json()},
        },
        "inputs": {"budget_cap_per_day": None if cap is None else num(cap)},
        "children": child_json,
        "schedule": schedule_for(window, children, ids),
        "whatif": {
            "sliders": [
                {
                    "key": "budget_cap_per_day",
                    "label": "Trần chi / ngày",
                    "unit": "vnd",
                    "min": 0,
                    "max": 1_000_000_000,
                    "step": 10_000,
                    "default": None if cap is None else num(cap),
                    "default_source": "generator",
                }
            ],
            "children_editable": True,
        },
        "certain": {**res["certain"], "label": "Chắc chắn"},
        "five_numbers": res["five"],
        "floor": {"breaches": res["breaches"], "unknown_skus": [], "ok": not res["breaches"]},
        "spend": {
            "shop_chi_per_day_now": res["cap"]["baseline_chi_per_day"],
            "card_dchi_per_day": num(profit.dchi_per_day),
            "shop_chi_per_day_after": res["cap"]["mega_chi_per_day"],
            "cap": res["cap"]["cap_per_day"],
            "over_cap": res["cap"]["over_budget"],
        },
        "predicted": {
            "label": "Dự kiến",
            "model_version": config.MODEL_VERSION,
            "lift": lift.json(),
            "money_per_month": money,
            "base": profit.base_label,
            "sim": {"applied": False},
        },
        "measurement_plan": {
            **plan,
            "bundle": True,
            "note": "Đo như một gói; các thay đổi con không được tính riêng.",
        },
        "execution_sheet": sheet,
        "notes": [],
        "locked_items": locked,
        "lock": {
            "products": locked,
            "from": window.start.isoformat(),
            "until": window.end.isoformat(),
        },
        "rank_inputs": {
            "kpi_p25": _kpi_deltas(env, money),
            "dgmv_p25": money["total"]["p25"]["dgmv"],
            "dprofit_p50": dprofit_p50,
            "floor_breach": bool(res["breaches"]),
            "spend_after": res["cap"]["mega_chi_per_day"],
            "spend_cap": res["cap"]["cap_per_day"],
            "in_stock": True,
            "kg_value": None,
            "items": locked,
        },
        "bundle": True,
        "freshness": freshness.stamp(env, locked, now),
    }
    return card


def _kpi_deltas(env: RecoEnv, money: dict[str, Any]) -> dict[str, float]:
    from juli_backend.services.shopee_recommendations.cards import shop_deltas

    return shop_deltas(env, money)


def children_from_card(card: Mapping[str, Any]) -> list[Candidate]:
    return [
        Candidate(
            kind=c["change_kind"],
            items=tuple(c["items"]),
            inputs=dict(c["inputs"]),
            campaign_key=c.get("campaign_key"),
            extra=dict(c.get("extra", {})),
        )
        for c in card["children"]
    ]


def window_from_card(card: Mapping[str, Any]) -> MegaWindow:
    w = card["mega_window"]
    return MegaWindow(datetime.fromisoformat(w["start"]), datetime.fromisoformat(w["end"]))


def select_children(
    cards: Sequence[Mapping[str, Any]], *, per_family: int = 2
) -> list[Mapping[str, Any]]:
    """The best (already ranked, eligible) non-mega cards: at most ``per_family`` per family,
    and no two PRICE levers on one product."""
    out: list[Mapping[str, Any]] = []
    used_price: set[str] = set()
    n: dict[str, int] = defaultdict(int)
    for c in cards:
        if c["family"] == "mega_sale" or n[c["family"]] >= per_family:
            continue
        if c["change_kind"] in ("affiliate_sample", "affiliate_invite"):
            continue  # a KOL card is about one creator, not part of a shop-wide schedule
        if c["change_kind"] in PRICE_KINDS:
            item = c["scope"]["product_ids"][0] if c["scope"]["product_ids"] else ""
            if item in used_price:
                continue
            used_price.add(item)
        n[c["family"]] += 1
        out.append(c)
    return out[:MAX_CHILDREN]


def candidate_of_card(card: Mapping[str, Any]) -> Candidate:
    return Candidate(
        kind=card["change_kind"],
        items=tuple(card["scope"]["product_ids"]),
        inputs=dict(card["inputs"]),
        campaign_key=card["scope"].get("campaign_key"),
        extra=dict(card.get("candidate_extra", {})),
        wiring_key=card.get("wiring_key"),
        gap_pct=card.get("gap_pct"),
    )


__all__ = ["date", "pct", "pct_points"]
