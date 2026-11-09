"""P98 / ADR-122 d.1, d.4, d.5: the funnel engine. One option in, one ``OptionResult`` out.

Method (pure; the only randomness is a ``random.Random(seed)`` -- stdlib, no new dependency):

* **Before** = the base scaled to the duration (sums x days / window days), per source, no range.
* **Each driver's band** (P10 / P50 / P90) is fitted by a *split normal at the median*: the median
  is P50, the left sigma is (P50 - P10) / z90 and the right sigma (P90 - P50) / z90, half of the
  mass on each side, so the fitted distribution reproduces the three given quantiles exactly
  (a skewed band stays skewed; a flat band is a constant). Drivers, extra shares and offer use
  shares are drawn **independently**, in a fixed order, so the same seed gives the same numbers.
* **A scenario** propagates the draws through the funnel per source: lifts multiply the base
  metric on the driver's sources only (views, CTR, CTOR, AOV; CTR and CTOR are capped at 100 %),
  ``AddedTraffic`` adds views, clicks and orders (views x ctr x ctor x extra share) to its first
  source. Ratios are always derived from the sums, so Views x CTR x CTOR = Orders and
  Orders x AOV = GMV hold exactly in every column and per source.
* **Profit** = before profit + (extra orders x profit per order) + price effect + AOV effect
  (change in AOV x orders x contribution rate) - offers - fixed cost. Offers and the fixed cost are
  allocated to the sources by order share, so the sources add up to the total.
* **Ranking.** All ``n`` scenarios are ranked by delta profit (by delta GMV when profit is unknown);
  low / likely / high are whole scenarios at P10 / P50 / P90.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field, replace
from decimal import Decimal
from typing import Literal

from juli_backend.services.shopee_builder.engine.contract import (
    RESIDUAL,
    AddedTraffic,
    Band,
    Basis,
    BuildUpPart,
    Driver,
    DriverEffect,
    FunnelBase,
    OptionInput,
    OptionResult,
    Scenario,
)
from juli_backend.services.shopee_builder.engine.vn import (
    DRIVER_LABELS,
    SOURCE_LABELS,
    count,
    vnd,
)

Z90 = 1.2815515655446004  # standard normal quantile at 0.90 (config.Z_P90)
DEFAULT_DAYS = 30
_BASIS_ORDER: tuple[Basis, ...] = ("measured", "product_history", "shop", "prior", "not_estimable")


# -- band sampling -------------------------------------------------------------------------------


def _draw(rng: random.Random, band: Band) -> float:
    """One draw from the split normal fitted through the band's P10 / P50 / P90."""
    p10, p50, p90 = float(band.p10), float(band.p50), float(band.p90)
    z = rng.gauss(0.0, 1.0)
    if z < 0:
        return p50 + max(0.0, p50 - p10) / Z90 * z
    return p50 + max(0.0, p90 - p50) / Z90 * z


def _clamp01(x: float) -> float:
    return min(1.0, max(0.0, x))


# -- prepared inputs -----------------------------------------------------------------------------


@dataclass(frozen=True)
class _Src:
    key: str
    v: float | None
    k: float | None
    o: float
    g: float
    p: float | None
    capable: bool  # views and clicks > 0: views / CTR / CTOR levers can act
    aov: float | None
    ppo: float | None


@dataclass
class _Eff:
    """The draws of one scenario (multipliers per base source; 1.0 = untouched)."""

    mv: list[float]
    mc: list[float]
    mt: list[float]
    ma: list[float]
    added_idx: int | None = None
    added_views: float = 0.0
    added_share: float = 0.0
    use_shares: list[float] = field(default_factory=list)


@dataclass
class _Draw:
    rows: list[tuple[float | None, float | None, float, float, float | None]]  # v k o g profit
    orders: float
    gmv: float
    profit: float | None
    offer_cost: float
    offer_uses: list[float]
    orders_term: float
    price_term: float
    aov_term: float
    aov_orders: float  # orders after the change on the sources an AOV lever acts on


def _neutral(n_src: int, n_offers: int) -> _Eff:
    one = [1.0] * n_src
    return _Eff(list(one), list(one), list(one), list(one), None, 0.0, 0.0, [0.0] * n_offers)


def _prepare(base: FunnelBase, scale: float) -> list[_Src]:
    out: list[_Src] = []
    for s in base.sources:
        v = None if s.views is None else float(s.views) * scale
        k = None if s.clicks is None else float(s.clicks) * scale
        o = float(s.orders) * scale
        g = float(s.gmv) * scale
        p = None if s.profit is None else float(s.profit) * scale
        capable = v is not None and k is not None and v > 0 and k > 0
        out.append(
            _Src(
                s.source,
                v,
                k,
                o,
                g,
                p,
                capable,
                g / o if o > 0 else None,
                p / o if (p is not None and o > 0) else None,
            )
        )
    return out


def _carriers(srcs: list[_Src], driver: DriverEffect) -> list[int]:
    """Indexes of the base sources the driver can act on."""
    idx = {s.key: i for i, s in enumerate(srcs)}
    if driver.added is not None:
        i = idx.get(driver.sources[0]) if driver.sources else None
        if i is None or srcs[i].v is None or srcs[i].k is None:
            return []
        return [i]
    out = []
    for key in driver.sources:
        i = idx.get(key)
        if i is None:
            continue
        ok = srcs[i].aov is not None if driver.metric == "aov" else srcs[i].capable
        if ok:
            out.append(i)
    return out


def _scenario(
    srcs: list[_Src],
    eff: _Eff,
    option: OptionInput,
    cr: float | None,
    profit_known: bool,
    aov_idx: set[int],
    added: AddedTraffic | None,
    with_fixed: bool,
) -> _Draw:
    n_src = len(srcs)
    vs: list[float | None] = []
    ks: list[float | None] = []
    os_: list[float] = []
    gs: list[float] = []
    ps: list[float] = []  # gross profit per source (before offers / fixed)
    orders_term = price_term = aov_term = aov_orders = 0.0
    ppo_after = (
        None if option.profit_per_order_after is None else float(option.profit_per_order_after)
    )
    for i, s in enumerate(srcs):
        mv, mc, mt, ma = eff.mv[i], eff.mc[i], eff.mt[i], eff.ma[i]
        v, k, o = s.v, s.k, s.o
        if s.capable and v is not None and k is not None:
            if mc != 1.0:
                mc = min(mc, v / k)  # CTR <= 100 %
            if mt != 1.0 and s.o > 0:
                mt = min(mt, k / s.o)  # CTOR <= 100 %
            if mv != 1.0:
                v, k, o = v * mv, k * mv, o * mv
            if mc != 1.0:
                k, o = k * mc, o * mc
            if mt != 1.0:
                o = o * mt
        g = s.g * (o / s.o) if (s.o > 0 and o != s.o) else s.g
        p = s.p if s.p is not None else 0.0
        if s.ppo is not None:
            orders_term += (o - s.o) * s.ppo
            p += (o - s.o) * s.ppo
            if ppo_after is not None:
                price_term += o * (ppo_after - s.ppo)
                p += o * (ppo_after - s.ppo)
        if ma != 1.0 and s.aov is not None:
            g = g * ma
            # a price change states its new profit per order (``profit_per_order_after``): the
            # price effect is already in ``price_term``: the AOV term moves GMV only (counted once)
            a = 0.0 if ppo_after is not None else s.aov * (ma - 1.0) * o * (cr or 0.0)
            aov_term += a
            p += a
        if i in aov_idx:
            aov_orders += o
        vs.append(v)
        ks.append(k)
        os_.append(o)
        gs.append(g)
        ps.append(p)
    if added is not None and eff.added_idx is not None:
        i = eff.added_idx
        av = eff.added_views
        oa = av * float(added.ctr) * float(added.ctor) * eff.added_share
        vs[i] = (vs[i] or 0.0) + av
        ks[i] = (ks[i] or 0.0) + av * float(added.ctr)
        os_[i] += oa
        gs[i] += oa * float(added.aov)
        if added.profit_per_order is not None:
            t = oa * float(added.profit_per_order)
            orders_term += t
            ps[i] += t
    total_o = sum(os_)
    offer_cost = 0.0
    uses: list[float] = []
    for offer, share in zip(option.offers, eff.use_shares, strict=True):
        n_use = total_o * share
        if offer.use_cap is not None:
            n_use = min(n_use, float(offer.use_cap))
        uses.append(n_use)
        offer_cost += n_use * float(offer.per_use)
    costs = offer_cost + (float(option.fixed_cost) if with_fixed else 0.0)
    rows: list[tuple[float | None, float | None, float, float, float | None]] = []
    for i in range(n_src):
        share_i = os_[i] / total_o if total_o > 0 else 1.0 / n_src
        prof = ps[i] - costs * share_i if profit_known else None
        rows.append((vs[i], ks[i], os_[i], gs[i], prof))
    total_p = sum(r[4] for r in rows if r[4] is not None) if profit_known else None
    return _Draw(
        rows,
        total_o,
        sum(gs),
        total_p,
        offer_cost,
        uses,
        orders_term,
        price_term,
        aov_term,
        aov_orders,
    )


# -- conversion ----------------------------------------------------------------------------------


def _d(x: float) -> Decimal:
    return Decimal(repr(float(x)))


def _opt(x: float | None) -> Decimal | None:
    return None if x is None else _d(x)


def _to_scenario(draw: _Draw, keys: list[str]) -> Scenario:
    by_source: dict[str, dict[str, Decimal | None]] = {}
    for key, (v, k, o, g, p) in zip(keys, draw.rows, strict=True):
        by_source[key] = {
            "views": _opt(v),
            "clicks": _opt(k),
            "ctr": _opt(k / v) if (v and k is not None) else None,
            "ctor": _opt(o / k) if (k and k > 0) else None,
            "orders": _d(o),
            "aov": _opt(g / o) if o > 0 else None,
            "gmv": _d(g),
            "profit": _opt(p),
        }
    # the residual carries orders but never traffic: it counts as 0 views / clicks (contract
    # FunnelBase.total, ADR-122 d.2), so the shop's CTOR = all orders ÷ clicks
    traffic = [r for key, r in zip(keys, draw.rows, strict=True) if key != RESIDUAL]
    vals_v = [r[0] for r in traffic]
    vals_k = [r[1] for r in traffic]
    views = (
        None
        if any(x is None for x in vals_v)
        else sum((by_source[k]["views"] or Decimal(0) for k in keys if k != RESIDUAL), Decimal(0))
    )
    clicks = (
        None
        if any(x is None for x in vals_k)
        else sum((by_source[k]["clicks"] or Decimal(0) for k in keys if k != RESIDUAL), Decimal(0))
    )
    profit = None if draw.profit is None else _d(draw.profit)
    if draw.profit is not None:
        # keep the exact sum of the (rounded-to-repr) sources
        profit = sum((by_source[k]["profit"] or Decimal(0) for k in keys), Decimal(0))
    return Scenario(
        views,
        clicks,
        sum((by_source[k]["orders"] or Decimal(0) for k in keys), Decimal(0)),
        sum((by_source[k]["gmv"] or Decimal(0) for k in keys), Decimal(0)),
        profit,
        _d(draw.offer_cost),
        by_source,
    )


# -- build-up and break-even ---------------------------------------------------------------------


def _build_up(
    draw: _Draw,
    d_orders: float,
    d_profit: float,
    option: OptionInput,
) -> tuple[BuildUpPart, ...]:
    fixed = float(option.fixed_cost)
    parts: dict[str, tuple[float, str]] = {}

    def orders_text(amount: float) -> str:
        if abs(d_orders) < 1e-9:
            return ""
        sign = "+" if d_orders > 0 else "−"
        return f"{sign}{count(d_orders)} đơn × {vnd(amount / d_orders)}"

    if abs(draw.orders_term) > 1e-9:
        parts["extra_orders"] = (draw.orders_term, orders_text(draw.orders_term))
    if abs(draw.price_term) > 1e-9:
        word = "cao" if draw.price_term > 0 else "thấp"
        parts["price"] = (
            draw.price_term,
            f"Lợi nhuận mỗi đơn {word} hơn {vnd(abs(draw.price_term))}",
        )
    if abs(draw.aov_term) > 1e-9:
        word = "cao" if draw.aov_term > 0 else "thấp"
        parts["aov"] = (draw.aov_term, f"AOV {word} hơn {vnd(abs(draw.aov_term))}")
    if draw.offer_cost > 1e-9:
        if len(option.offers) == 1:
            o = option.offers[0]
            text = f"− {o.label or 'ưu đãi'} {count(draw.offer_uses[0])} lượt × {vnd(o.per_use)}"
        else:
            text = f"− ưu đãi {vnd(draw.offer_cost)}"
        parts["offer"] = (-draw.offer_cost, text)
    if fixed > 1e-9:
        parts["fixed"] = (-fixed, f"− chi phí cố định {vnd(fixed)}")
    if len(parts) > 3 and "price" in parts:
        amt, _ = parts.pop("price")
        e_amt, _ = parts.get("extra_orders", (0.0, ""))
        total = e_amt + amt
        text = orders_text(total) or f"Lợi nhuận mỗi đơn thay đổi {vnd(amt)}"
        parts["extra_orders"] = (total, text)
    if len(parts) > 3 and "fixed" in parts and "offer" in parts:
        a1, _ = parts.pop("fixed")
        a2, _ = parts["offer"]
        parts["offer"] = (a1 + a2, f"− chi phí {vnd(-(a1 + a2))}")
    order: tuple[Literal["extra_orders", "price", "aov", "offer", "fixed"], ...] = (
        "extra_orders",
        "price",
        "aov",
        "offer",
        "fixed",
    )
    keys: list[Literal["extra_orders", "price", "aov", "offer", "fixed"]] = [
        k for k in order if k in parts
    ]
    total_r = int(round(d_profit))
    out: list[BuildUpPart] = []
    acc = 0
    for j, key in enumerate(keys):
        amt, text = parts[key]
        r = total_r - acc if j == len(keys) - 1 else int(round(amt))
        acc += r
        out.append(BuildUpPart(key, Decimal(r), text))
    return tuple(out)


def _weakest(drivers: tuple[DriverEffect, ...]) -> Basis:
    rank = [_BASIS_ORDER.index(d.basis) for d in drivers]
    return _BASIS_ORDER[max(rank)] if rank else "measured"


# -- run -----------------------------------------------------------------------------------------


def run(base: FunnelBase, option: OptionInput, seed: int = 0, n: int = 4000) -> OptionResult:
    """Simulate ``option`` on ``base``: ``n`` whole scenarios, ranked, P10 / P50 / P90 columns."""
    days = option.duration_days or DEFAULT_DAYS
    horizon: Literal["duration", "first_30_days"] = (
        "duration" if option.duration_days else "first_30_days"
    )
    scale = days / max(1, base.window_days)
    srcs = _prepare(base, scale)
    keys = [s.key for s in srcs]
    cr = None if base.contribution_rate is None else float(base.contribution_rate)
    notes: list[str] = []
    if option.note:
        notes.append(option.note)
    metrics: list[Driver] = []
    for d in option.drivers:
        if d.metric not in metrics:
            metrics.append(d.metric)
    basis = _weakest(option.drivers)

    estimable = True
    carriers: list[list[int]] = []
    aov_idx: set[int] = set()
    for d in option.drivers:
        if d.note:
            notes.append(d.note)
        if d.basis == "not_estimable":
            estimable = False
            carriers.append([])
            continue
        c = _carriers(srcs, d)
        carriers.append(c)
        if not c:
            estimable = False
            notes.append(
                f"Chưa có dữ liệu để đòn bẩy {DRIVER_LABELS[d.metric]} tác động lên nguồn đã chọn."
            )
            continue
        if d.metric == "aov":
            aov_idx.update(c)
        named = {srcs[i].key for i in c}
        if d.added is None:
            for key in d.sources:
                if key in keys and key not in named and key != RESIDUAL:
                    notes.append(
                        f"Nguồn {SOURCE_LABELS.get(key, key)} chưa có dữ liệu nên không tính vào."
                    )
    added_driver = next((d for d in option.drivers if d.added is not None), None)
    added = None if added_driver is None else added_driver.added
    has_aov = any(d.metric == "aov" for d in option.drivers)
    profit_known = (
        all(s.p is not None for s in srcs)
        and (not has_aov or cr is not None or option.profit_per_order_after is not None)
        and (added is None or added.profit_per_order is not None)
    )

    # "before" is today: the option's new profit per order (a price change) never applies to it
    before_draw = _scenario(
        srcs,
        _neutral(len(srcs), len(option.offers)),
        replace(option, profit_per_order_after=None),
        cr,
        profit_known,
        aov_idx,
        added,
        False,
    )
    before = _to_scenario(before_draw, keys)
    fixed = float(option.fixed_cost)
    ppo_be = _break_even_ppo(option, added, before_draw, srcs)

    if not estimable:
        mid = _neutral(len(srcs), len(option.offers))
        mid.use_shares = [float(o.use_share.p50) for o in option.offers]
        cost_draw = _scenario(srcs, mid, option, cr, profit_known, aov_idx, None, True)
        cost = cost_draw.offer_cost + fixed
        return OptionResult(
            kind=option.kind,
            label=option.label,
            days=days,
            horizon=horizon,
            drivers=tuple(metrics),
            estimable=False,
            basis=basis,
            before=before,
            low=None,
            likely=None,
            high=None,
            build_up=(),
            cost_total=_d(cost),
            break_even_orders=_be_orders(cost, ppo_be),
            break_even_aov=_be_aov(
                cost, 0.0, 0.0, srcs, aov_idx, before_draw.aov_orders, cr, has_aov
            ),
            notes=tuple(notes),
        )

    rng = random.Random(seed)
    draws: list[_Draw] = []
    n = max(1, n)
    for _ in range(n):
        eff = _neutral(len(srcs), len(option.offers))
        for d, cs in zip(option.drivers, carriers, strict=True):
            if d.basis == "not_estimable":
                continue
            if d.added is not None:
                eff.added_idx = cs[0]
                eff.added_views = max(0.0, _draw(rng, d.added.views))
                eff.added_share = _clamp01(_draw(rng, d.added.extra_share))
            elif d.lift is not None:
                m = max(0.0, 1.0 + _draw(rng, d.lift))
                arr = {"views": eff.mv, "ctr": eff.mc, "ctor": eff.mt, "aov": eff.ma}[d.metric]
                for i in cs:
                    arr[i] *= m
        eff.use_shares = [_clamp01(_draw(rng, o.use_share)) for o in option.offers]
        draws.append(_scenario(srcs, eff, option, cr, profit_known, aov_idx, added, True))

    if profit_known and before_draw.profit is not None:
        bp = before_draw.profit
        keyed = [(x.profit - bp) if x.profit is not None else 0.0 for x in draws]
    else:
        keyed = [x.gmv - before_draw.gmv for x in draws]
    ranked = sorted(range(n), key=lambda i: keyed[i])

    def pick(q: float) -> _Draw:
        return draws[ranked[int(round(q * (n - 1)))]]

    d10, d50, d90 = pick(0.10), pick(0.50), pick(0.90)
    likely = d50
    cost = likely.offer_cost + fixed
    d_profit = (
        None
        if likely.profit is None or before_draw.profit is None
        else likely.profit - before_draw.profit
    )
    build_up = (
        ()
        if d_profit is None
        else _build_up(likely, likely.orders - before_draw.orders, d_profit, option)
    )
    return OptionResult(
        kind=option.kind,
        label=option.label,
        days=days,
        horizon=horizon,
        drivers=tuple(metrics),
        estimable=True,
        basis=basis,
        before=before,
        low=_to_scenario(d10, keys),
        likely=_to_scenario(d50, keys),
        high=_to_scenario(d90, keys),
        build_up=build_up,
        cost_total=_d(cost),
        break_even_orders=_be_orders(cost, ppo_be),
        break_even_aov=_be_aov(
            cost,
            likely.orders_term,
            likely.price_term,
            srcs,
            aov_idx,
            likely.aov_orders,
            cr,
            has_aov,
        ),
        notes=tuple(notes),
    )


def _break_even_ppo(
    option: OptionInput, added: AddedTraffic | None, before: _Draw, srcs: list[_Src]
) -> float | None:
    if added is not None:
        return None if added.profit_per_order is None else float(added.profit_per_order)
    if option.profit_per_order_after is not None:
        return float(option.profit_per_order_after)
    if before.profit is None or before.orders <= 0:
        return None
    return before.profit / before.orders


def _be_orders(cost: float, ppo: float | None) -> Decimal | None:
    if cost <= 0 or ppo is None or ppo <= 0:
        return None
    return _d(cost / ppo)


def _be_aov(
    cost: float,
    orders_term: float,
    price_term: float,
    srcs: list[_Src],
    aov_idx: set[int],
    orders_after: float,
    cr: float | None,
    has_aov: bool,
) -> Decimal | None:
    if not has_aov or not aov_idx or cr is None or cr <= 0 or orders_after <= 0:
        return None
    o0 = sum(srcs[i].o for i in aov_idx)
    g0 = sum(srcs[i].g for i in aov_idx)
    if o0 <= 0:
        return None
    aov_b = g0 / o0
    need = max(0.0, cost - orders_term - price_term)
    return _d(aov_b + need / (orders_after * cr))


def compare(results: list[OptionResult]) -> list[OptionResult]:
    """Sort by per-30-day delta profit, best first; an unknown profit goes last."""
    from juli_backend.services.shopee_builder.engine.wire import per_30d_profit

    def key(r: OptionResult) -> tuple[int, float]:
        v = per_30d_profit(r)
        return (1, 0.0) if v is None else (0, -float(v))

    return sorted(results, key=key)


__all__ = ["compare", "run"]
