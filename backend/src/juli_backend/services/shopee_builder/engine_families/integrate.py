"""P98 W3-H: one builder version -> its stored funnel base -> its family's ``OptionInput`` ->
``engine.run`` -> ``OptionResult`` (ADR-122 d.1-d.5). The one calculation behind every builder
number: ``before_after`` and the outcome's ``delta`` are laid out from this result, never computed
again.

- **Base** = the stored funnel of the version's scope (the shop for a shop-wide option, else its
  products) over the request's window (the env's 30 days ending at the Tổng quan anchor; the env is
  loaded with ``funnel=True``, so this is ``funnel.load_funnel_base`` without a second read).
- **Seed** = a hash of the version's JSON: the same version gives the same numbers.
- **Several targets** (``multi.SUM``: one giảm giá % over several products): one result per
  expanded single-target version (``multi.expand``) and the version's result is their column-wise
  sum (P10 + P10, P50 + P50, P90 + P90 -- the existing aggregation of the target rows). A voucher
  over a product list (``multi.JOINT``) is one offer: one result on the union of the products.
- **Facts the context lacks** (``FamilyExtras``): the contribution rate and profit per order of the
  base, the Ads history (campaigns + the product's days with / without ads from the stored
  funnel), the KOL rates and sample costs, a combo row's pack evidence (E3).

Pure apart from reading the already-loaded env.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import timedelta
from decimal import Decimal
from typing import Any, Literal, cast

from juli_backend.services.shopee_analytics import funnel
from juli_backend.services.shopee_builder import multi
from juli_backend.services.shopee_builder import specs as sp
from juli_backend.services.shopee_builder.context import BuilderContext
from juli_backend.services.shopee_builder.engine import engine
from juli_backend.services.shopee_builder.engine.contract import (
    RESIDUAL,
    AdsEvaluation,
    Band,
    Basis,
    BuildUpPart,
    Driver,
    FunnelBase,
    OptionInput,
    OptionResult,
    Scenario,
)
from juli_backend.services.shopee_builder.engine.vn import count, vnd
from juli_backend.services.shopee_builder.engine_families import (
    FamilyExtras,
    FamilyRefused,
    option_for,
)
from juli_backend.services.shopee_builder.engine_families.facts import (
    AdsEditFacts,
    AdsFacts,
    AdsNewCampaign,
    AffiliatePlan,
    KolFacts,
    NewComboListing,
    PackEvidence,
    ProductAdRow,
)
from juli_backend.services.shopee_builder.engine_families.measure import (
    AdCampaignHist,
    AdDay,
    CampaignDay,
    KolRates,
)
from juli_backend.services.shopee_profit import shop_profit
from juli_backend.services.shopee_recommendations.env import RecoEnv

ZERO = Decimal(0)
#: Ad type of a Dịch vụ Hiển thị Sản phẩm campaign, past or new (``measure.ad_rates``).
AD_TYPE = "product_search"
_BASIS_ORDER: tuple[Basis, ...] = ("measured", "product_history", "shop", "prior", "not_estimable")


# -- base ----------------------------------------------------------------------------------------


def scope_items(spec: sp.VersionSpec) -> tuple[str, ...]:
    """The products whose funnel is the option's "before"; () = the shop (a shop-wide voucher, a
    gift on a minimum spend)."""
    if isinstance(spec, sp.VoucherSpec):
        return tuple(spec.item_ids) if spec.scope == "product" else ()
    if isinstance(spec, sp.AddOnSpec):
        return (spec.main_item_id,)
    if isinstance(spec, sp.GiftSpec):
        t = spec.trigger
        return (t.item_id,) if t.type == "buy_item" and t.item_id else ()
    return tuple(sp.items_of(spec))


def base_for(env: RecoEnv, item_ids: Sequence[str], shop_id: str = "") -> FunnelBase:
    """``funnel.load_funnel_base`` on the env's own window and stored rows (read once)."""
    rows = env.view.data.funnel
    if not isinstance(rows, funnel.FunnelRows):
        rows = funnel.FunnelRows(env.view.window)
    items = tuple(dict.fromkeys(i for i in item_ids if i))
    return funnel.base_from_rows(
        rows,
        shop_id,
        item_ids=items,
        contribution_rate=funnel.contribution_rate(env.view, items),
    )


def _base_total(base: FunnelBase, name: str) -> Decimal | None:
    """``base.total(name)`` for the totals the metrics side adds (``profit_orders``,
    ``profit_days``, ``days``); ``None`` while the base does not carry them yet."""
    total = cast(Callable[[str], Decimal | None], base.total)
    try:
        return total(name)
    except (AttributeError, KeyError, TypeError):
        return None


def profit_per_order(base: FunnelBase) -> Decimal | None:
    """Profit ÷ the orders of the days whose profit is known (P99: ``profit_orders``; the funnel
    sums profit over the days with costs, so a day without giá vốn no longer makes it unknown).
    A base built from the stored rows (it counts its days) with no order on a day with costs has
    no profit per order (``None``); only a base that carries no day counts at all divides by
    every order."""
    profit = base.total("profit")
    orders = _base_total(base, "profit_orders")
    if not orders and _days_total(base, "days"):
        # P99b: the base carries its days, so 0 orders on days with costs means the profit per
        # order is unknown -- never silently every order of the window
        return None
    if not orders:  # a base that does not carry the metrics side's totals at all
        orders = base.total("orders")
    if orders is None or profit is None or orders <= 0:
        return None
    return profit / orders


def _days_total(base: FunnelBase, name: str) -> int | None:
    """A day count of the scope (``profit_days`` / ``days``): every source covers the same days,
    so it is the largest source's count, not their sum."""
    counts: list[int] = []
    for s in base.sources:
        v = getattr(s, name, None)
        if v is not None:
            counts.append(int(v))
    if counts:
        return max(counts)
    v = getattr(base, name, None)
    if v is None:
        v = _base_total(base, name)
    return None if v is None else int(v)


def profit_coverage_note(base: FunnelBase) -> str | None:
    """ "Lợi nhuận mỗi đơn trên N ngày có dữ liệu chi phí" when some days of the window had no
    cost data (P99); ``None`` when every day had it or the base does not say."""
    known, days = _days_total(base, "profit_days"), _days_total(base, "days")
    if known is None or days is None or known >= days or base.total("profit") is None:
        return None
    window = getattr(base, "window_days", None)
    if isinstance(window, int) and window > 0:  # P100-A (A.7): on the window's coverage
        return (
            f"Lợi nhuận mỗi đơn tính trên {known} ngày có dữ liệu chi phí "
            f"(trong {days}/{window} ngày có dữ liệu)."
        )
    return f"Lợi nhuận mỗi đơn tính trên {known} ngày có dữ liệu chi phí (trong {days} ngày)."


def scope_today(env: RecoEnv, base: FunnelBase) -> dict[str, Any]:
    """ "Hôm nay" of an option's own scope (P99, like with like): the stored funnel ``base`` the
    option's result was computed on (đơn, GMV, lợi nhuận, lượt xem / nhấp of the window) and the
    scope's one margin (``shop_profit.scope_margin_pct``, Luồng sản phẩm's math). The builder's
    So sánh, the saved card and Kế hoạch read the same block for the same scope."""
    orders, gmv = base.total("orders"), base.total("gmv")
    views, clicks = funnel.known_total(base, "views"), funnel.known_total(base, "clicks")
    margin = shop_profit.scope_margin_pct(env.view.profit, base.item_ids)
    return {
        "scope": base.scope if base.scope == "shop" else "product",
        "items": list(base.item_ids),
        "as_of": env.as_of.isoformat(),
        "window": {
            "from": base.window_start.isoformat(),
            "to": base.window_end.isoformat(),
            "days": base.window_days,
        },
        "gmv_30d": None if gmv is None else float(gmv),
        "orders_30d": None if orders is None else float(orders),
        "aov": float(gmv / orders) if gmv is not None and orders else None,
        "margin_pct": None if margin is None else float(margin),
        "profit_30d": _float(base.total("profit")),
        "views_30d": _float(views),
        "clicks_30d": _float(clicks),
        "ctr": float(clicks / views) if views and clicks is not None else None,
        "ctor": float(orders / clicks) if clicks and orders is not None else None,
    }


def _float(x: Decimal | None) -> float | None:
    return None if x is None else float(x)


def seed_of(payload: Any) -> int:
    """A stable seed from a JSON-able payload (the version spec): same version, same numbers."""
    text = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)
    return int(hashlib.sha256(text.encode()).hexdigest()[:12], 16)


def _flat(b: Band | None) -> bool:
    return b is None or b.p10 == b.p50 == b.p90


def deterministic(option: OptionInput) -> bool:
    """Every band is a point: all scenarios are the same, one draw is enough."""
    for d in option.drivers:
        if d.basis == "not_estimable":
            continue
        if not _flat(d.lift):
            return False
        if d.added is not None and not (_flat(d.added.views) and _flat(d.added.extra_share)):
            return False
    return all(_flat(o.use_share) for o in option.offers)


def run(base: FunnelBase, option: OptionInput, seed: int) -> OptionResult:
    result = engine.run(base, option, seed=seed, n=1 if deterministic(option) else 4000)
    note = profit_coverage_note(base)
    if note is None or note in result.notes:
        return result
    return replace(result, notes=(*result.notes, note))


# -- one evaluation -------------------------------------------------------------------------------


@dataclass(frozen=True)
class Evaluated:
    """The base, and the result or why the family refused (``refusal.code``)."""

    base: FunnelBase
    result: OptionResult | None
    refusal: FamilyRefused | None = None

    def result_json(self) -> dict[str, Any] | None:
        return None if self.result is None else self.result.json()

    def refusal_json(self) -> dict[str, str] | None:
        if self.refusal is None:
            return None
        return {"code": self.refusal.code, "message": self.refusal.text or self.refusal.code}


def extras_for(base: FunnelBase) -> FamilyExtras:
    return FamilyExtras(
        contribution_rate=base.contribution_rate, profit_per_order=profit_per_order(base)
    )


def evaluate(
    ctx: BuilderContext, spec: sp.VersionSpec, shop_id: str = ""
) -> tuple[Evaluated, list[tuple[str, Evaluated]]]:
    """One version: ``(its evaluation, one evaluation per target)``. The per-target list is
    empty for a single-target version. Raises nothing: a refusal is carried."""
    base = base_for(ctx.env, scope_items(spec), shop_id)
    mode = multi.mode(spec)
    targets: list[tuple[str, Evaluated]] = []
    if mode is not None:
        for target, single in multi.expand(spec, ctx):
            targets.append((target, _one(ctx, single, shop_id)))
    if mode == multi.SUM:
        done = [e.result for _, e in targets if e.result is not None]
        if not done:
            first = next((e.refusal for _, e in targets if e.refusal is not None), None)
            return Evaluated(base, None, first or FamilyRefused("multi_target")), targets
        label = spec.label or done[0].label
        return Evaluated(base, sum_results(done, label)), targets
    return _one(ctx, spec, shop_id, base), targets


def _one(
    ctx: BuilderContext, spec: sp.VersionSpec, shop_id: str, base: FunnelBase | None = None
) -> Evaluated:
    base = base or base_for(ctx.env, scope_items(spec), shop_id)
    if isinstance(spec, sp.AdsNewSpec):  # P99: the Ads tab's new campaign, saved as a version
        return ads_result(
            ctx.env, ads_campaign(spec), shop_id=shop_id, seed_payload=spec.model_dump(mode="json")
        )
    if isinstance(spec, sp.AdsSpec):  # P100 B.15: an edit of a running campaign
        return ads_edit_result(ctx, spec, shop_id)
    try:
        option = option_for(spec, ctx, extras_for(base))
    except FamilyRefused as exc:
        return Evaluated(base, None, exc)
    return Evaluated(base, run(base, option, seed_of(spec.model_dump(mode="json"))))


# -- several targets: the column-wise sum ---------------------------------------------------------


def _add(a: Decimal | None, b: Decimal | None) -> Decimal | None:
    return None if a is None or b is None else a + b


def _sum_scenarios(cols: Sequence[Scenario]) -> Scenario:
    def total(name: str) -> Decimal | None:
        out: Decimal | None = ZERO
        for c in cols:
            out = _add(out, getattr(c, name))
        return out

    by_source: dict[str, dict[str, Decimal | None]] = {}
    for c in cols:
        for key, row in c.by_source.items():
            acc = by_source.setdefault(
                key, {"views": ZERO, "clicks": ZERO, "orders": ZERO, "gmv": ZERO, "profit": ZERO}
            )
            for f in ("views", "clicks", "orders", "gmv", "profit"):
                acc[f] = _add(acc[f], row.get(f))
    for row in by_source.values():
        v, k, o, g = row["views"], row["clicks"], row["orders"] or ZERO, row["gmv"] or ZERO
        row["ctr"] = k / v if v and k is not None else None
        row["ctor"] = o / k if k else None
        row["aov"] = g / o if o > 0 else None
    return Scenario(
        total("views"),
        total("clicks"),
        total("orders") or ZERO,
        total("gmv") or ZERO,
        total("profit"),
        total("offer_cost") or ZERO,
        by_source,
    )


def _sum_build_up(results: Sequence[OptionResult]) -> tuple[BuildUpPart, ...]:
    amounts: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for r in results:
        for p in r.build_up:
            amounts[p.key] += p.amount
    d_orders = sum(
        (r.likely.orders - r.before.orders for r in results if r.likely is not None), ZERO
    )
    out: list[BuildUpPart] = []
    keys: tuple[Literal["extra_orders", "price", "aov", "offer", "fixed"], ...] = (
        "extra_orders",
        "price",
        "aov",
        "offer",
        "fixed",
    )
    for key in keys:
        if key not in amounts:
            continue
        amt = amounts[key]
        if key == "extra_orders" and d_orders:
            text = f"{'+' if d_orders > 0 else '−'}{count(d_orders)} đơn × {vnd(amt / d_orders)}"
        elif key == "price":
            text = f"Lợi nhuận mỗi đơn {'cao' if amt > 0 else 'thấp'} hơn {vnd(abs(amt))}"
        elif key == "aov":
            text = f"AOV {'cao' if amt > 0 else 'thấp'} hơn {vnd(abs(amt))}"
        else:
            text = f"− chi phí {vnd(-amt)}"
        out.append(BuildUpPart(key, amt, text))
    while len(out) > 3:  # at most three parts: the last two become one cost line
        b, a = out.pop(), out.pop()
        out.append(
            BuildUpPart("offer", a.amount + b.amount, f"− chi phí {vnd(-(a.amount + b.amount))}")
        )
    return tuple(out)


def sum_results(results: Sequence[OptionResult], label: str) -> OptionResult:
    """Several single-target results as one: the columns added up (the funnel identity holds on
    sums), costs added, the weakest basis. One result is returned as it is."""
    if len(results) == 1:
        return results[0]
    first = results[0]
    estimable = all(r.estimable for r in results)
    drivers: list[Driver] = []
    for r in results:
        drivers += [d for d in r.drivers if d not in drivers]

    def col(name: str) -> Scenario | None:
        cols = [getattr(r, name) for r in results]
        return None if any(c is None for c in cols) else _sum_scenarios(cols)

    be = [r.break_even_orders for r in results]
    notes: list[str] = []
    for r in results:
        notes += [n for n in r.notes if n not in notes]
    return OptionResult(
        kind=first.kind,
        label=label,
        days=max(r.days for r in results),
        horizon=first.horizon,
        drivers=tuple(drivers),
        estimable=estimable,
        basis=max((r.basis for r in results), key=_BASIS_ORDER.index),
        before=_sum_scenarios([r.before for r in results]),
        low=col("low") if estimable else None,
        likely=col("likely") if estimable else None,
        high=col("high") if estimable else None,
        build_up=_sum_build_up(results) if estimable else (),
        cost_total=sum((r.cost_total for r in results), ZERO),
        break_even_orders=None
        if any(b is None for b in be)
        else sum((b or ZERO for b in be), ZERO),
        break_even_aov=None,
        notes=tuple(notes),
        ads=_sum_ads([r.ads for r in results]),
    )


def _sum_ads(evals: Sequence[AdsEvaluation | None]) -> AdsEvaluation | None:
    """Several campaigns under one budget / ROAS edit (P100 B.15): spend / orders / GMV added;
    break-even CPA and the incremental share weighted by today's ad orders."""
    done = [a for a in evals if a is not None]
    if not done or len(done) != len(evals):
        return None
    if len(done) == 1:
        return done[0]

    def total(name: str) -> Decimal | None:
        vals = [getattr(a, name) for a in done]
        return None if any(v is None for v in vals) else sum(vals, ZERO)

    weight = sum((a.orders_now for a in done), ZERO)

    def weighted(vals: Sequence[Decimal | None]) -> Decimal | None:
        if weight <= 0 or any(v is None for v in vals):
            return None
        return sum(((v or ZERO) * a.orders_now for v, a in zip(vals, done, strict=True)), ZERO) / (
            weight
        )

    shares = [a.incremental_share for a in done]
    share = None
    if all(b is not None for b in shares):
        lo = weighted([b.p10 if b else None for b in shares])
        mid = weighted([b.p50 if b else None for b in shares])
        hi = weighted([b.p90 if b else None for b in shares])
        share = None if lo is None or mid is None or hi is None else Band(lo, mid, hi)
    bases = {a.spend_basis for a in done}
    texts = list(dict.fromkeys(f"{a.campaign}: {a.spend_text}" for a in done))
    return AdsEvaluation(
        lever=done[0].lever,
        campaign=", ".join(a.campaign for a in done),
        days=max(a.days for a in done),
        spend_basis=done[0].spend_basis if len(bases) == 1 else "mixed",
        spend_text=" ".join(texts),
        spend_now=sum((a.spend_now for a in done), ZERO),
        spend_after=total("spend_after"),
        orders_now=weight,
        orders_after=total("orders_after"),
        gmv_now=sum((a.gmv_now for a in done), ZERO),
        gmv_after=total("gmv_after"),
        break_even_cpa=weighted([a.break_even_cpa for a in done]),
        incremental_share=share,
        cancel_rate=done[0].cancel_rate,
    )


# -- the P98 builders' facts ----------------------------------------------------------------------


def _source_views(base: FunnelBase) -> tuple[Decimal | None, Decimal | None]:
    return funnel.known_total(base, "views"), funnel.known_total(base, "clicks")


def pack_evidence(
    base: FunnelBase,
    *,
    variation_orders: int,
    product_orders: int,
    price: Decimal,
    profit_per_order: Decimal | None,
) -> PackEvidence | None:
    """E3: a new pack size of one product takes its matching variation's measured rates -- the
    product's CTR / CTOR (the stored funnel), views = the product's views × the variation's share
    of the product's orders, AOV = the pack's price. ``None`` without traffic or orders."""
    views, clicks = _source_views(base)
    orders = base.total("orders")
    if not views or not clicks or not orders or product_orders <= 0 or variation_orders <= 0:
        return None
    share = Decimal(variation_orders) / Decimal(product_orders)
    return PackEvidence(
        views=views * share,
        window_days=base.window_days,
        ctr=clicks / views,
        ctor=orders / clicks,
        aov=price,
        profit_per_order=profit_per_order,
    )


def combo_listing_result(
    env: RecoEnv,
    row: NewComboListing,
    *,
    pack_rows: Mapping[str, Sequence[Mapping[str, Any]]],
    shop_id: str = "",
) -> Evaluated:
    """A combo builder row -> the listing combo family (d.7, E3) -> the engine."""
    base = base_for(env, row.item_ids, shop_id)
    pack = None
    if len(row.item_ids) == 1 and not row.pack_sold_today:
        item = row.item_ids[0]
        rows = pack_rows.get(item, ())
        product_orders = env.orders_of(item)
        sku = row.members[0][1]
        v_orders = next((int(r.get("orders_30d") or 0) for r in rows if r.get("sku_key") == sku), 0)
        pack = pack_evidence(
            base,
            variation_orders=v_orders,
            product_orders=product_orders,
            price=row.price,
            profit_per_order=row.profit_per_order,
        )
    extras = FamilyExtras(
        pack=pack,
        contribution_rate=base.contribution_rate,
        profit_per_order=profit_per_order(base),
    )
    ctx = BuilderContext(env=env)
    try:
        option = option_for(row, ctx, extras)
    except FamilyRefused as exc:
        return Evaluated(base, None, exc)
    return Evaluated(base, run(base, option, seed_of({"combo_row": row.key, "price": row.price})))


def pack_sold_today(rows: Iterable[Mapping[str, Any]], member_pack: int, quantity: int) -> bool:
    """E3: the product already has a variation holding ``quantity`` × the member's pack count."""
    want = member_pack * quantity
    return any(int(r.get("pack_count") or 1) == want for r in rows)


def ads_history(env: RecoEnv) -> tuple[AdCampaignHist, ...]:
    """The window's campaigns (spend, impressions, clicks, direct orders / GMV) with their live
    settings (daily budget, ROAS target) -- ``ads_campaign_daily`` / settings via the env."""
    days = env.window_days
    out: list[AdCampaignHist] = []
    for c in env.view.ads.campaigns:
        setting = env.setting_for(c.key)
        direct_orders = c.orders * c.direct_gmv / c.gmv if c.gmv > 0 else ZERO
        out.append(
            AdCampaignHist(
                key=c.key,
                item_ids=frozenset(c.products),
                ad_type=AD_TYPE,
                spend=c.spend,
                impressions=c.impressions,
                clicks=c.clicks,
                direct_orders=direct_orders,
                direct_gmv=c.direct_gmv,
                days=days,
                daily_budget=None if setting is None else setting.daily_budget,
                roas_target=None if setting is None else setting.roas_target,
                gmv=c.gmv,
            )
        )
    return tuple(out)


def ad_days(env: RecoEnv, item_ids: Sequence[str]) -> tuple[AdDay, ...]:
    """Per day of the stored funnel, the products' organic Thẻ sản phẩm orders and whether an ad
    ran for them (``ads_spend`` > 0). Product rows carry ad GMV, not ad orders: the ad orders of a
    day are its ad GMV ÷ the day's card AOV, and organic = card orders − ad orders."""
    rows = env.view.data.funnel
    if not isinstance(rows, funnel.FunnelRows):
        return ()
    wanted = set(item_ids)
    per: dict[Any, list[Decimal]] = defaultdict(lambda: [ZERO, ZERO, ZERO, ZERO])
    for r in rows.sources:
        if r.item_id not in wanted or r.source != funnel.ADS_SOURCE:
            continue
        acc = per[r.day]
        acc[0] += Decimal(r.orders)
        acc[1] += r.gmv
        acc[2] += r.ads_spend or ZERO
        acc[3] += r.ads_gmv or ZERO
    out: list[AdDay] = []
    for day in sorted(per):
        orders, gmv, spend, ad_gmv = per[day]
        ad_orders = ad_gmv / (gmv / orders) if orders > 0 and gmv > 0 else ZERO
        ad_orders = min(ad_orders, orders)
        out.append(AdDay(on=spend > 0, organic_orders=orders - ad_orders, ad_orders=ad_orders))
    return tuple(out)


def ads_campaign(spec: sp.AdsNewSpec) -> AdsNewCampaign:
    """A saved new-campaign version as the ads family's input (the same as ``ads_builder``'s
    setups: no end date = a 30-day horizon from the start)."""
    end = spec.end or spec.start + timedelta(days=engine.DEFAULT_DAYS - 1)
    return AdsNewCampaign(
        item_ids=tuple(spec.item_ids),
        daily_budget=Decimal(spec.daily_budget),
        start=spec.start,
        end=end,
        roas_target=None if spec.roas_target is None else Decimal(str(spec.roas_target)),
        ad_type=AD_TYPE,
        label=spec.name or spec.label,
    )


def ads_result(
    env: RecoEnv, setup: AdsNewCampaign, *, shop_id: str = "", seed_payload: Any = None
) -> Evaluated:
    base = base_for(env, setup.item_ids, shop_id)
    facts = AdsFacts(
        campaigns=ads_history(env),
        days=ad_days(env, setup.item_ids),
        profit_per_order=profit_per_order(base),
    )
    ctx = BuilderContext(env=env)
    option = option_for(setup, ctx, FamilyExtras(ads=facts))
    return Evaluated(base, run(base, option, seed_of(seed_payload or repr(setup))))


def profit_per_order_before_ads(base: FunnelBase) -> Decimal | None:
    """P100 B.15: the break-even CPA -- profit per order of the scope BEFORE ads: the stored
    profit is after the ad spend (the one shop profit), so the spend per order is added back."""
    ppo = profit_per_order(base)
    if ppo is None:
        return None
    orders = base.total("orders")
    spend = sum(
        ((s.ads.spend or ZERO) for s in base.sources if s.ads is not None and s.ads.spend),
        ZERO,
    )
    if not orders or orders <= 0:
        return ppo
    return ppo + spend / orders


def product_ad_rows(env: RecoEnv) -> tuple[ProductAdRow, ...]:
    """The per-product lines of the window's ads reports (campaign × product, placed orders)."""
    out: list[ProductAdRow] = []
    for r in env.view.data.ads_reports.campaign_rows:
        if not r.item_id:
            continue
        start, end = r.period
        out.append(
            ProductAdRow(
                campaign_key=r.key,
                item_id=r.item_id,
                spend=r.spend,
                impressions=r.impressions,
                clicks=r.clicks,
                orders=r.orders,
                gmv=r.gmv,
                direct_gmv=r.direct_gmv,
                days=(end - start).days + 1,
            )
        )
    return tuple(out)


def ads_edit_facts(
    ctx: BuilderContext, spec: sp.AdsSpec, shop_id: str = ""
) -> tuple[AdsEditFacts, FunnelBase]:
    """P100 B.15: the edited campaign's own history and the base its result stands on (the
    campaign's products, + the product being added; the shop when the products are unknown)."""
    env = ctx.env
    key = spec.campaign_key or ""
    setting = env.setting_for(key)
    allocs = env.view.ads.campaigns
    alloc = next((a for a in allocs if a.key == key), None)
    if alloc is None and setting is not None:
        alloc = next((a for a in allocs if a.key == setting.key or a.name == setting.name), None)
    campaigns = ads_history(env)
    camp = None if alloc is None else next((c for c in campaigns if c.key == alloc.key), None)
    rows = product_ad_rows(env)
    own_key = alloc.key if alloc is not None else key
    items = list(alloc.products) if alloc is not None else []
    items += [r.item_id for r in rows if r.campaign_key == own_key]
    if spec.lever == "add_product" and spec.item_id:
        items.append(spec.item_id)
    item_ids = tuple(dict.fromkeys(i for i in items if i))
    base = base_for(env, item_ids, shop_id)
    day_items = (spec.item_id,) if spec.lever in ("add_product", "remove_product") else item_ids
    name = alloc.name if alloc is not None else (setting.name if setting is not None else key)
    facts = AdsEditFacts(
        campaign=camp,
        name=name,
        daily_budget=None if setting is None else setting.daily_budget,
        daily=()
        if setting is None
        else tuple(CampaignDay(spend, budget) for spend, budget in setting.days),
        product_rows=rows,
        days=ad_days(env, [i for i in day_items if i]),
        campaigns=campaigns,
        profit_per_order_before_ads=profit_per_order_before_ads(base),
        cancel_rate=env.cancel_rate,
    )
    return facts, base


def ads_edit_result(ctx: BuilderContext, spec: sp.AdsSpec, shop_id: str = "") -> Evaluated:
    facts, base = ads_edit_facts(ctx, spec, shop_id)
    extras = replace(extras_for(base), ads_edit=facts)
    try:
        option = option_for(spec, ctx, extras)
    except FamilyRefused as exc:
        return Evaluated(base, None, exc)
    return Evaluated(base, run(base, option, seed_of(spec.model_dump(mode="json"))))


def kol_rates(
    kol_key: str,
    handle: str,
    rows: Iterable[Any],
    item_ids: Sequence[str],
    *,
    partner_clicks: Decimal | None,
    partner_orders: Decimal | None,
    days: int,
) -> KolRates | None:
    """A KOL's own measured row for the chosen products: orders and GMV from the KOL report rows,
    clicks = the KOL's clicks × the products' share of the KOL's orders; views are not reported
    by Shopee (``None``: the affiliate family then gives cost and break-even only)."""
    wanted = set(item_ids)
    mine = [r for r in rows if r.kol_key == kol_key and r.item_id in wanted]
    if not mine or days <= 0:
        return None
    orders = Decimal(sum(r.orders for r in mine))
    gmv = sum((r.gmv for r in mine), ZERO)
    clicks = ZERO
    if partner_clicks and partner_orders:
        clicks = partner_clicks * min(Decimal(1), orders / partner_orders)
    return KolRates(kol_key, handle, days, None, clicks, orders, gmv)


def kol_result(
    env: RecoEnv,
    plan: AffiliatePlan,
    facts: KolFacts,
    *,
    shop_id: str = "",
    seed_payload: Any = None,
) -> Evaluated:
    items = tuple(dict.fromkeys(i for k in plan.kols for i in k.item_ids))
    base = base_for(env, items, shop_id)
    facts = KolFacts(
        rates=facts.rates,
        before_after=facts.before_after,
        sample_unit_cost=facts.sample_unit_cost,
        profit_per_order=profit_per_order(base),
        extra_cashback_names=facts.extra_cashback_names,
    )
    ctx = BuilderContext(env=env)
    option = option_for(plan, ctx, FamilyExtras(kol=facts))
    return Evaluated(base, run(base, option, seed_of(seed_payload or repr(plan))))


def compare_keys(results: Sequence[tuple[str, OptionResult | None]]) -> list[str]:
    """The keys in the comparison order (per-30-day Δ profit, best first; unknown last)."""
    done = [(k, r) for k, r in results if r is not None]
    order = engine.compare([r for _, r in done])
    keyed: list[str] = []
    used: set[int] = set()
    for r in order:
        for i, (k, rr) in enumerate(done):
            if rr is r and i not in used:
                keyed.append(k)
                used.add(i)
                break
    return keyed + [k for k, r in results if r is None]


__all__ = [
    "AD_TYPE",
    "RESIDUAL",
    "Evaluated",
    "ad_days",
    "ads_edit_facts",
    "ads_edit_result",
    "ads_campaign",
    "ads_history",
    "ads_result",
    "base_for",
    "combo_listing_result",
    "compare_keys",
    "deterministic",
    "evaluate",
    "extras_for",
    "kol_rates",
    "kol_result",
    "pack_evidence",
    "pack_sold_today",
    "product_ad_rows",
    "profit_per_order",
    "profit_per_order_before_ads",
    "run",
    "profit_coverage_note",
    "scope_items",
    "scope_today",
    "seed_of",
    "sum_results",
]
