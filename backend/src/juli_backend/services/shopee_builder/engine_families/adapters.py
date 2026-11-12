"""Facts from the recommendation environment: order lines, the evaluators' certain layer and the
prediction's lift. Everything here reads ``RecoEnv`` (never the database)."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

from juli_backend.services.shopee_builder import specs as sp
from juli_backend.services.shopee_builder.engine.contract import Band, Basis, OfferCost
from juli_backend.services.shopee_builder.engine_families import common
from juli_backend.services.shopee_builder.engine_families.common import FamilyRefused
from juli_backend.services.shopee_builder.engine_families.facts import (
    AffiliateRateFacts,
    ComboFacts,
    LiftEvidence,
    ListingComboFacts,
    NewComboListing,
    PackEvidence,
    PriceFacts,
    VoucherFacts,
)
from juli_backend.services.shopee_profit.order_profit import OrderLine
from juli_backend.services.shopee_recommendations import kinds as reco_kinds
from juli_backend.services.shopee_recommendations.bundle_tiers import (
    Tier,
    best_tier,
    effective_pct,
)
from juli_backend.services.shopee_recommendations.env import RecoEnv
from juli_backend.services.shopee_recommendations.model import Candidate
from juli_backend.services.shopee_recommendations.prediction import Lift, predict_lift

ZERO = Decimal(0)
ONE = Decimal(1)

#: ``Lift.source`` (prediction.py) -> the engine's basis
_BASIS: dict[str, Basis] = {
    "prior": "prior",
    "shop": "shop",
    "shop_products": "shop",
    "product_history": "product_history",
}


def band_of(lift: Lift) -> Band:
    d = [Decimal(str(round(lift.at(q), 6))) for q in ("p10", "p50", "p90")]
    return Band(min(d), d[1], max(d))


def lift_evidence(
    kind: str, items: Sequence[str], env: RecoEnv, magnitude: float | None = None
) -> LiftEvidence:
    """The lift of ``kind`` on its target metric: this product's own history > the shop's
    results > the preset prior (``predict_lift`` already orders them)."""
    spec = reco_kinds.spec(kind)
    lift = predict_lift(spec, Candidate(kind=kind, items=tuple(items)), env, magnitude)
    return LiftEvidence(band_of(lift), _BASIS.get(lift.source, "prior"))


# -- order statistics ---------------------------------------------------------------------------


def order_values(lines: Sequence[OrderLine]) -> dict[str, Decimal]:
    out: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for ln in lines:
        out[ln.order_id] += ln.order_value
    return dict(out)


def profit_per_order(env: RecoEnv, order_ids: set[str]) -> Decimal | None:
    """Contribution per order of the orders (None when any line's cost is unknown)."""
    total = ZERO
    for ln, pb in env.view.pairs:
        if ln.order_id not in order_ids or pb.excluded_reason is not None:
            continue
        if pb.contribution is None:
            return None
        total += pb.contribution
    return total / len(order_ids) if order_ids else None


def measured_reach(near: int, n: int, below: int) -> Band | None:
    """ADR-122 d.13 E2: the share of ALL ``n`` orders that reach a minimum / tier = the ``near``
    orders sitting within 20 % below it today, with a binomial spread (z of P90); never above the
    ``below`` share. ``None`` with fewer than ``MIN_REACH_ORDERS`` orders (then the tagged
    prior)."""
    if n < common.MIN_REACH_ORDERS:
        return None
    m = Decimal(near) / n
    cap = Decimal(below) / n
    se = (m * (ONE - m) / n).sqrt()
    return Band(
        min(max(m - common.Z90 * se, ZERO), cap), m, min(max(m + common.Z90 * se, ZERO), cap)
    )


def qualifying_share(env: RecoEnv, minimum: Decimal) -> Decimal:
    """Share of the shop's orders at / over ``minimum`` (a gift on a minimum spend), the basket
    counted after the programme price and the combo discount (P100 B.11; the gift's own rule is
    not confirmed in Seller Centre yet)."""
    values: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for ln in env.lines_for(None):
        values[ln.order_id] += ln.order_value - getattr(ln, "bundle_discount", ZERO)
    if not values:
        return ZERO
    return Decimal(sum(1 for v in values.values() if v >= minimum)) / len(values)


def voucher_facts(spec: sp.VoucherSpec, env: RecoEnv) -> VoucherFacts:
    lines = env.lines_for(spec.item_ids or None)
    values = order_values(lines)
    n = len(values)
    minimum = Decimal(spec.min_spend)
    if n == 0:
        return VoucherFacts(None, None, ZERO, ZERO, ZERO, ZERO)
    total = sum(values.values(), ZERO)
    qualifying = [v for v in values.values() if v >= minimum]
    below = [v for v in values.values() if v < minimum]
    ref = (sum(qualifying, ZERO) / len(qualifying)) if qualifying else total / n
    if spec.discount_type == "amount":
        per_use = Decimal(str(spec.value))
    else:
        per_use = ref * Decimal(str(spec.value)) / 100
        if spec.max_value is not None:
            per_use = min(per_use, Decimal(spec.max_value))
    near = [v for v in below if v >= minimum * (ONE - common.REACH_WINDOW)]
    return VoucherFacts(
        aov_now=total / n,
        profit_per_order=profit_per_order(env, set(values)),
        per_use=per_use,
        qualifying_share=Decimal(len(qualifying)) / n,
        raise_gap_per_order=sum((minimum - v for v in below), ZERO) / n,
        below_share=Decimal(len(below)) / n,
        usage_rate=env.usage_rate if env.usage_rate is not None else ONE,
        reach=measured_reach(len(near), n, len(below)),
        reach_gap=sum((minimum - v for v in near), ZERO) / len(near) if near else ZERO,
        near_share=Decimal(len(near)) / n,
    )


#: P100-C: the combo refusals as the seller reads them (codes as ``bundle_tiers``)
COMBO_REFUSAL_TEXT: dict[str, str] = {
    "combo_discount_over_max": "Combo giảm tối đa 90% tổng giá bán hiện tại.",
    "combo_price_not_below_value": (
        "Giá đặc biệt phải thấp hơn tổng giá bán hiện tại của số sản phẩm đó."
    ),
    "combo_price_too_low": "Giá combo quá thấp (dưới 1.000đ) — bạn muốn nhập % giảm?",
    "combo_tiers_not_increasing": sp.COMBO_TIERS_NOT_INCREASING,
}


def effective_tiers(spec: sp.ComboSpec, unit_price: Decimal) -> tuple[tuple[int, Decimal], ...]:
    """P100-C (B.9): each tier of each Loại Combo as an effective percent off N × đơn giá (giảm %
    = itself; giảm số tiền = amount ÷ (N × đơn giá); giá đặc biệt = 1 − giá ÷ (N × đơn giá)),
    by quantity. Refuses a tier at ≤ 0 % or over the 90 % cap (so never ≥ 100 %) and tiers whose
    percent does not rise with N."""
    rows = sorted((Tier(t.qty, Decimal(str(t.value))) for t in spec.tiers), key=lambda t: t.qty)
    out: list[tuple[int, Decimal]] = []
    for t in rows:
        try:
            eff = effective_pct(spec.discount_type, t, unit_price)
        except ValueError as exc:
            code = str(exc)
            raise FamilyRefused(code, COMBO_REFUSAL_TEXT.get(code, code)) from None
        if eff <= 0 or eff >= 100:
            code = "combo_price_not_below_value" if eff <= 0 else "combo_discount_over_max"
            raise FamilyRefused(code, COMBO_REFUSAL_TEXT[code])
        if out and eff <= out[-1][1]:
            code = "combo_tiers_not_increasing"
            raise FamilyRefused(code, COMBO_REFUSAL_TEXT[code])
        out.append((t.qty, eff))
    return tuple(out)


def gift_offer(certain: Mapping[str, Any]) -> OfferCost | None:
    """P100-C (A.9): Quà tặng's cost inside the OptionResult -- giá vốn + đóng gói of the gift(s)
    on every qualifying order (``eval_gift``'s certain layer)."""
    gift = certain.get("gift") or {}
    per, q, n = gift.get("cost_per_gift"), gift.get("qualifying_orders"), gift.get("total_orders")
    if per is None or not n:
        return None
    share = Decimal(str(q or 0)) / Decimal(str(n))
    return OfferCost(Decimal(str(per)), Band(share, share, share), None, "quà tặng")


def add_on_offer(certain: Mapping[str, Any], aov_lift: Band) -> OfferCost | None:
    """P100-C (A.9): Mua kèm's cost inside the OptionResult -- the add-on discount on every
    attach, today's and the ones the AOV lift brings. ``per_use`` = the discount of one main
    order taking the add-on(s); ``use_share`` = today's attach share + lift × AOV ÷ the add-on
    value per main order."""
    n = certain.get("main_orders")
    value = certain.get("attach_value_per_order")
    rate = certain.get("discount_per_attach_gmv")
    if not n or not value or rate is None:
        return None
    v = Decimal(str(value))
    per = Decimal(str(rate)) * v
    if per <= 0:
        return None
    now = common.clamp01(Decimal(str(certain.get("discount_cost_on_existing") or 0)) / (per * n))
    aov = Decimal(str(certain.get("aov_now") or 0))
    shares = [common.clamp01(now + x * aov / v) for x in (aov_lift.p10, aov_lift.p50, aov_lift.p90)]
    return OfferCost(per, Band(*sorted(shares)), None, "giảm giá mua kèm")


def combo_fee_rate(env: RecoEnv, item_ids: Sequence[str]) -> Decimal:
    """P100-C (J, verified on a real ORY order): Shopee's % fees (phí cố định, dịch vụ, xử lý giao
    dịch) are charged on the item total after the combo, so the discount saves them. The mean
    % rate of the combo's products' fee formulas; 0 when none has one (the gross discount)."""
    schedule = getattr(env, "schedule", None)  # test fakes carry no fee schedule
    as_of = getattr(env, "as_of", None)
    if schedule is None or as_of is None:
        return ZERO
    rates = [
        f.pct_rate_on_buyer_paid
        for f in (schedule(i).formula_on(as_of) for i in item_ids)
        if f is not None
    ]
    return common.clamp01(sum(rates, ZERO) / len(rates)) if rates else ZERO


def combo_facts(spec: sp.ComboSpec, env: RecoEnv) -> ComboFacts:
    """P100-C (J): the tiers apply ON TOP of the Chương Trình Của Shop price -- ``deal_price`` is
    the programme price (Giá sau giảm), so N × đơn giá is N × that price (list 100.000 →
    programme 78.100 → −20 % for 2 = 124.960)."""
    wanted = set(spec.item_ids)
    lines = env.lines_for(list(wanted))
    values = order_values(lines)
    units: dict[str, int] = defaultdict(int)
    unit_value = ZERO
    unit_count = 0
    for ln in lines:
        if ln.product_id in wanted:
            units[ln.order_id] += ln.qty
            unit_value += ln.deal_price * ln.qty
            unit_count += ln.qty
    n = len(values)
    if n == 0 or unit_count == 0:
        return ComboFacts(None, None, ZERO, ZERO, ZERO, ZERO)
    avg_price = unit_value / unit_count
    tiers = sorted((Tier(t.qty, Decimal(str(t.value))) for t in spec.tiers), key=lambda t: t.qty)
    discounts: list[Decimal] = []
    near: list[int] = []  # units short of the lowest tier, for the orders within reach of it
    below = 0
    lowest = tiers[0].qty
    # E2: within 20 % below the tier, and at least one unit (a tier of 2-5 is one unit away)
    floor_units = min(lowest - 1, math.ceil(lowest * (ONE - common.REACH_WINDOW)))
    eff_of = dict(effective_tiers(spec, avg_price))
    for oid in values:
        u = units.get(oid, 0)
        tier = best_tier(u, tiers)
        if tier is not None:
            eff = eff_of[tier.qty]
            discounts.append((u // tier.qty) * tier.qty * avg_price * eff / 100)
        elif u > 0:
            below += 1
            if u >= floor_units:
                near.append(lowest - u)
    return ComboFacts(
        aov_now=sum(values.values(), ZERO) / n,
        profit_per_order=profit_per_order(env, set(values)),
        # nobody at a tier today: an order moving up to the lowest tier gets its discount
        per_use=sum(discounts, ZERO) / len(discounts)
        if discounts
        else lowest * avg_price * eff_of[lowest] / 100,
        use_share_now=Decimal(len(discounts)) / n,
        near_share=Decimal(len(near)) / n,
        unit_price=avg_price,
        reach=measured_reach(len(near), n, below),
        reach_units=Decimal(sum(near)) / len(near) if near else ONE,
        fee_rate=combo_fee_rate(env, list(spec.item_ids)),
    )


def listing_combo_facts(
    spec: sp.ListingComboSpec, env: RecoEnv, pack: PackEvidence | None
) -> ListingComboFacts:
    """Orders that already hold every member product switch to the new listing."""
    members = set(spec.member_ids)
    lines = env.lines_for(list(members))
    values = order_values(lines)
    held: dict[str, set[str]] = defaultdict(set)
    member_value: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for ln in lines:
        if ln.product_id in members:
            held[ln.order_id].add(ln.product_id)
            member_value[ln.order_id] += ln.order_value
    switching = [oid for oid, h in held.items() if h == members]
    n = len(values)
    return ListingComboFacts(
        aov_now=sum(values.values(), ZERO) / n if n else None,
        profit_per_order=profit_per_order(env, set(values)) if n else None,
        switch_share=Decimal(len(switching)) / n if n else ZERO,
        value_now=sum((member_value[o] for o in switching), ZERO) / len(switching)
        if switching
        else ZERO,
        new_price=Decimal(spec.price),
        profit_per_order_after=None,
        pack=pack,
    )


def new_listing_facts(
    row: NewComboListing,
    env: RecoEnv,
    pack: PackEvidence | None,
    base_profit_per_order: Decimal | None = None,
) -> ListingComboFacts:
    """A combo builder row: the orders that already hold every member at its quantity switch to
    the new listing (their lines' value today vs the row's price). The profit per order after
    switching is the base's (``base_profit_per_order``, the funnel's) plus the switching share x
    (the row's profit per order - those orders' profit per order today) (E3)."""
    wanted = {i for i, _, _ in row.members}
    lines = env.lines_for(sorted(wanted))
    values = order_values(lines)
    held: dict[str, dict[tuple[str, str], int]] = defaultdict(lambda: defaultdict(int))
    price: dict[tuple[str, str], Decimal] = {}
    for ln in lines:
        key = (ln.product_id, ln.sku)
        held[ln.order_id][key] += ln.qty
        price[key] = ln.deal_price
    need = {(i, sku): q for i, sku, q in row.members}
    switching = [oid for oid, h in held.items() if all(h.get(k, 0) >= q for k, q in need.items())]
    n = len(values)
    value_now = (
        sum((price[k] * q for k, q in need.items() if k in price), ZERO) if switching else ZERO
    )
    ppo_now = profit_per_order(env, set(values)) if n else None
    ppo_switch = profit_per_order(env, set(switching)) if switching else None
    share = Decimal(len(switching)) / n if n else ZERO
    ppo_after = None
    if (
        base_profit_per_order is not None
        and row.profit_per_order is not None
        and ppo_switch is not None
    ):
        ppo_after = base_profit_per_order + share * (row.profit_per_order - ppo_switch)
    return ListingComboFacts(
        aov_now=sum(values.values(), ZERO) / n if n else None,
        profit_per_order=ppo_now,
        switch_share=share,
        value_now=value_now,
        new_price=row.price,
        profit_per_order_after=ppo_after,
        pack=None if row.pack_sold_today else pack,
        pack_sold_today=row.pack_sold_today,
    )


def price_facts_from_evaluation(
    ev: Any,
    *,
    aov_now: Decimal | None,
    contribution_rate: Decimal | None,
    ctor: LiftEvidence,
) -> PriceFacts:
    """The price evaluator's certain layer (``certain["skus"]``: price and profit per order
    before / after per SKU) -> orders-weighted price factor and profit per order."""
    rows = [r for r in ev.certain.get("skus", []) if r.get("orders")]
    w = sum((Decimal(str(r["orders"])) for r in rows), ZERO)

    def avg(key: str) -> Decimal | None:
        vals = [(Decimal(str(r["orders"])), r.get(key)) for r in rows]
        if w <= 0 or any(v is None for _, v in vals):
            return None
        return sum((o * Decimal(str(v)) for o, v in vals), ZERO) / w

    ratios = [
        (
            Decimal(str(r["orders"])),
            Decimal(str(r["price_after"])) / Decimal(str(r["price_before"])),
        )
        for r in rows
        if r.get("price_before") and r.get("price_after") is not None
    ]
    ratio_w = sum((o for o, _ in ratios), ZERO)
    factor = sum((o * x for o, x in ratios), ZERO) / ratio_w if ratio_w > 0 else ONE
    before, after = avg("profit_per_order_before"), avg("profit_per_order_after")
    discount: Decimal | None = None
    if before is not None and after is not None:
        discount = max(ZERO, before - after)  # net of the % fees the lower price saves
    elif aov_now and factor < ONE:
        discount = aov_now * (ONE - factor)  # profit unknown: the gross discount on a basket
    return PriceFacts(
        aov_now=aov_now,
        profit_per_order=avg("profit_per_order_before"),
        profit_per_order_after=avg("profit_per_order_after"),
        price_factor=factor,
        contribution_rate=contribution_rate,
        ctor=ctor,
        discount_per_order=discount,
    )


def affiliate_rate_facts(
    spec: sp.AffiliateSpec, env: RecoEnv, sample_cost: Decimal | None
) -> AffiliateRateFacts:
    """P99: the product's Liên kết GMV of the window (its affiliate order lines)."""
    item = spec.item_id or ""
    lines = env.lines_for([item])
    gmv = sum((ln.order_value for ln in lines if ln.product_id == item and ln.affiliate), ZERO)
    return AffiliateRateFacts(
        item_id=item,
        affiliate_gmv=gmv,
        window_days=env.window_days,
        sample_cost=sample_cost,
        sample_qty=spec.sample_qty,
    )
