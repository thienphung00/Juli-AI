"""The predicted range ("dự kiến"): ``optimize_product/prediction.py`` ported to Shopee kinds.

relative lift on the kind's target metric = preset prior x calibration factor (shop evidence
shrunk toward the prior: ``MIN_SHOP_RESULTS`` = 5, ``K`` = 5; no pooling across shops, ADR-116)
x coverage range scale; the simulation prior enters weighted by its per-change_kind gate
(ADR-121 d.4) -- weight 0 leaves the no-simulation path byte-identical. The lift is then
turned into dGMV / dprofit per month (P10 ... P90) by the GMV identity
(GMV = views x CTR x CTOR x AOV is linear in each factor) and the scenario's own per-order
profit from ``services/shopee_profit``.

Acceptance statistics never reach this module (they move slider defaults and the ranking
tie-break only).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from juli_backend.services.shopee_profit.money import ZERO, safe_div
from juli_backend.services.shopee_recommendations import config
from juli_backend.services.shopee_recommendations.kinds import KindSpec
from juli_backend.services.shopee_recommendations.model import Candidate, ProfitModel

if TYPE_CHECKING:
    from juli_backend.services.shopee_recommendations.env import RecoEnv

#: The simulation's metric for each target metric of ours.
SIM_METRIC = {"ctr": "ctr", "ctor": "ctor", "aov": "aov", "orders": "ctor"}
_SIM_80_FROM_90 = config.Z_P90 / 1.6448536269514722

QUANTILES = ("p10", "p25", "p50", "p75", "p90")


def gap_bucket(gap_pct: float | None) -> str:
    """How far below its reference the metric is (percent, positive = below)."""
    if gap_pct is None:
        return "unknown"
    if gap_pct >= config.GAP_LARGE_PCT:
        return "large"
    if gap_pct >= config.GAP_MEDIUM_PCT:
        return "medium"
    return "small"


def factor_from(pooled_ratio: float | None, results: int) -> tuple[float, str]:
    """Shop factor shrunk to the prior (1.0): ``n / (n + K)`` of the evidence is trusted, and
    only once the shop has ``MIN_SHOP_RESULTS`` results. Ratio clamped to the factor limits."""
    if pooled_ratio is None or results < config.MIN_SHOP_RESULTS:
        return 1.0, "prior"
    clamped = min(max(pooled_ratio, config.FACTOR_MIN), config.FACTOR_MAX)
    weight = results / (results + config.SHRINKAGE_K)
    return 1.0 + weight * (clamped - 1.0), "shop"


@dataclass(frozen=True)
class Lift:
    """Relative lift on the target metric: quantiles of a normal with the P10-P90 range."""

    metric: str
    low: float  # P10
    high: float  # P90
    factor: float
    source: str  # "prior" | "shop"
    range_scale: float = 1.0
    gap_bucket: str = "unknown"
    sim: dict[str, Any] = field(default_factory=dict)

    @property
    def mid(self) -> float:
        return (self.low + self.high) / 2

    @property
    def sigma(self) -> float:
        return (self.high - self.low) / (2 * config.Z_P90)

    def at(self, q: str) -> float:
        z = {
            "p10": -config.Z_P90,
            "p25": -config.Z_P75,
            "p50": 0.0,
            "p75": config.Z_P75,
            "p90": config.Z_P90,
        }[q]
        if q == "p10":
            return self.low
        if q == "p90":
            return self.high
        return self.mid + z * self.sigma

    def json(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "lift": {q: round(self.at(q), 5) for q in QUANTILES},
            "factor": round(self.factor, 4),
            "source": self.source,
            "range_scale": round(self.range_scale, 4),
            "gap_bucket": self.gap_bucket,
            "sim": self.sim,
        }


def _concave(magnitude_pct: float) -> float:
    """P96: beyond ``PRICE_CONCAVE_FROM_PCT`` each further percent of price change counts half."""
    knee = config.PRICE_CONCAVE_FROM_PCT
    size = abs(magnitude_pct)
    if size <= knee:
        return magnitude_pct
    return (knee + (size - knee) / 2) * (1 if magnitude_pct > 0 else -1)


def _price_capped(lo: float, hi: float) -> tuple[float, float]:
    """P96: a price response stays within ``PRICE_LIFT_MIN`` .. ``PRICE_LIFT_MAX``."""
    cap_lo, cap_hi = config.PRICE_LIFT_MIN, config.PRICE_LIFT_MAX
    return (min(max(lo, cap_lo), cap_hi), min(max(hi, cap_lo), cap_hi))


def size_scale(size: float | None, reference: float) -> Decimal:
    """P96: the lift a change of ``size`` earns against the prior's ``reference`` size, clamped to
    0 .. ``MAGNITUDE_SCALE_MAX``. Unknown size = the prior as it is (1)."""
    if size is None or reference <= 0:
        return Decimal(1)
    scaled = min(max(size / reference, 0.0), config.MAGNITUDE_SCALE_MAX)
    return Decimal(str(round(scaled, 6)))


def prior_range(spec: KindSpec, magnitude: float | None, bucket: str) -> tuple[float, float]:
    """(P10, P90) before calibration. ``magnitude`` = percent size of the change for scaled
    kinds: price cut percent (positive = cheaper) / budget change percent / ROAS target change
    percent."""
    lo, hi = spec.prior
    if spec.price_scaled:
        m = _concave(0.0 if magnitude is None else magnitude)
        e_lo, e_hi = config.PRICE_ELASTICITY_PER_PCT
        a, b = e_lo * m, e_hi * m
        return _price_capped(min(a, b), max(a, b))
    if spec.key == "ads_budget":
        k = 0.0 if magnitude is None else magnitude / config.ADS_BUDGET_STEP_PCT
        a, b = lo * k, hi * k
        return (min(a, b), max(a, b))
    if spec.key == "ads_roas_target":
        k = 0.0 if magnitude is None else magnitude / 10.0
        a, b = lo * k, hi * k
        return (min(a, b), max(a, b))
    if spec.key in ("ads_pause", "ads_remove_product", "ads_purpose"):
        return (lo, hi)
    if spec.key == "listing_combo":
        # P97 D85.16: the relative GMV change of the baskets that switch, from none (P10) to all
        # (P90) of them; ``magnitude`` is the combo price against the sum of its members, in %
        r = 0.0 if magnitude is None else magnitude / 100
        return (min(0.0, r), max(0.0, r))
    scale = config.GAP_BUCKET_SCALE[bucket]
    return (lo * scale, hi * scale)


def predict_lift(
    spec: KindSpec,
    cand: Candidate,
    env: RecoEnv | None,
    magnitude: float | None,
    *,
    sim_variant: Sequence[str] | str | None = None,
) -> Lift:
    bucket = gap_bucket(cand.gap_pct)
    lo, hi = prior_range(spec, magnitude, bucket)
    factor, source = 1.0, "prior"
    scale = 1.0
    own = None
    if env is not None and spec.price_scaled and magnitude is not None:
        # P92 B-3: this product's own past response to a price cut first, then the shop's other
        # products, before the preset prior and its calibration
        by_item = getattr(env, "response_by_item", None) or {}
        own = (by_item.get(cand.item) if cand.item else None) or getattr(env, "response_shop", None)
    if own is not None:
        a, b = own.per_pct_low * magnitude, own.per_pct_high * magnitude
        lo, hi, source = min(a, b), max(a, b), own.source
    elif env is not None:
        state = env.calibration.get((spec.key, spec.target_metric))
        if state is not None:
            factor, source = factor_from(state.pooled_ratio, state.n_results)
            scale = state.range_scale
    lo, hi = lo * factor, hi * factor
    sim_info: dict[str, Any] = {"applied": False}
    if env is not None and env.sim is not None and spec.sim_kind and cand.item:
        metric = SIM_METRIC.get(spec.target_metric)
        row = env.sim.lookup(cand.item, spec.sim_kind, metric, sim_variant) if metric else None
        weight = env.sim.gate_weight(spec.sim_kind)
        sim_info = {
            "run_id": env.sim.run_id,
            "change_kind": spec.sim_kind,
            "gate_weight": weight,
            "gate_status": env.sim.gate_status(spec.sim_kind),
            "row_found": row is not None,
            "applied": False,
        }
        if row is not None:
            sim_info["variant"] = row.variant
            sim_info["kg_value"] = row.kg_value
        if row is not None and weight > 0:
            mid_p, half_p = (lo + hi) / 2, (hi - lo) / 2
            mid_s = row.med
            half_s = (row.hi90 - row.lo90) / 2 * _SIM_80_FROM_90
            mid = (1 - weight) * mid_p + weight * mid_s
            half = (1 - weight) * half_p + weight * half_s
            lo, hi = mid - half, mid + half
            sim_info["applied"] = True
    if scale != 1.0:
        mid, half = (lo + hi) / 2, (hi - lo) / 2 * scale
        lo, hi = mid - half, mid + half
    if spec.price_scaled:  # P96: the shop's own response is held to the same limits
        lo, hi = _price_capped(lo, hi)
    return Lift(spec.target_metric, lo, hi, factor, source, scale, bucket, sim_info)


# ----------------------------------------------------------------------- money conversion

ORDER_METRICS = ("views", "ctr", "ctor", "orders")


def _predicted_dgmv(lift: Lift, pm: ProfitModel, q: str, days: Decimal) -> Decimal:
    """Predicted ΔGMV over ``days`` at quantile ``q``: the lift scaled by the change's own size
    (``lift_scale``), capped by the units a slot can sell, and never below losing the scope's
    whole GMV (P96)."""
    d_gmv = pm.base_gmv_per_day * days * Decimal(str(lift.at(q))) * pm.lift_scale
    if pm.max_extra_units is not None and pm.aov:
        d_gmv = min(d_gmv, pm.max_extra_units * pm.aov)
    return max(d_gmv, -pm.base_gmv_per_day * days)


def _ordered(block: dict[str, Any]) -> None:
    """P96: each figure's P10 .. P90 run low to high. Profit falls as GMV rises when the extra
    GMV loses money, so the profit quantiles are sorted on their own."""
    for key in ("dgmv", "dorders", "dprofit"):
        values = [block[q].get(key) for q in QUANTILES if q in block]
        if len(values) != len(QUANTILES) or any(v is None for v in values):
            continue
        for q, v in zip(QUANTILES, sorted(values), strict=True):
            block[q][key] = v


def convert(lift: Lift, pm: ProfitModel) -> dict[str, Any]:
    """dGMV / dorders / dprofit per month at each quantile: certain layer + predicted lift.

    ``month`` = the effect period capped at 30 days (a persistent change counts 30). Money
    is VND; ``None`` where the scenario's per-đồng profit is unknown (never 0)."""
    days = Decimal(min(pm.effect_days, config.DAYS_PER_MONTH))
    certain_gmv = pm.certain_dgmv_per_day * days
    certain_profit = -pm.extra_cost_per_day * days
    out: dict[str, Any] = {
        "days": int(days),
        "certain": {
            "dgmv": float(certain_gmv),
            "dprofit": float(certain_profit),
            "dchi": float(pm.dchi_per_day * days),
        },
        "predicted": {},
        "total": {},
    }
    for q in QUANTILES:
        d_gmv = _predicted_dgmv(lift, pm, q, days)
        d_orders = d_gmv / pm.aov if pm.aov and lift.metric in ORDER_METRICS else None
        d_profit = d_gmv * pm.profit_per_gmv if pm.profit_per_gmv is not None else None
        out["predicted"][q] = {
            "dgmv": float(d_gmv),
            "dorders": None if d_orders is None else float(d_orders),
            "dprofit": None if d_profit is None else float(d_profit),
        }
        out["total"][q] = {
            "dgmv": float(certain_gmv + d_gmv),
            "dorders": None if d_orders is None else float(d_orders),
            "dprofit": None if d_profit is None else float(certain_profit + d_profit),
        }
    _ordered(out["predicted"])
    _ordered(out["total"])
    out.update(_units(lift, pm))
    return out


def _units(lift: Lift, pm: ProfitModel) -> dict[str, Any]:
    """The same money in the units the seller reads: per DAY (flows), per ORDER (unit economics)
    and the total over the change's own days (``period``, not capped at a month). Orders and AOV
    ranges come from the model layer; the certain layer keeps AOV and orders as they were."""
    n = Decimal(max(pm.effect_days, 1))
    certain_gmv = pm.certain_dgmv_per_day * n
    certain_profit = -pm.extra_cost_per_day * n
    base_orders = pm.base_orders_per_day
    basis_day = pm.orders_basis_per_day if pm.orders_basis_per_day is not None else base_orders
    basis_orders = basis_day * n
    base_aov = safe_div(pm.base_gmv_per_day, base_orders) if base_orders > 0 else None

    def per(value: Decimal | None, d: Decimal) -> float | None:
        return None if value is None or d <= 0 else float(value / d)

    period: dict[str, Any] = {
        "days": int(n),
        "certain": {
            "dgmv": float(certain_gmv),
            "dprofit": float(certain_profit),
            "dchi": float(pm.dchi_per_day * n),
        },
        "total": {},
    }
    per_day: dict[str, Any] = {
        "certain": {
            "dgmv": float(pm.certain_dgmv_per_day),
            "dprofit": float(-pm.extra_cost_per_day),
            "dchi": float(pm.dchi_per_day),
        },
        "total": {},
    }
    per_order: dict[str, Any] = {
        "basis": pm.orders_basis,
        "orders_in_period": float(basis_orders),
        "certain": {
            "dprofit": per(certain_profit, basis_orders),
            "cost": per(pm.extra_cost_per_day * n, basis_orders),
        },
        "total": {},
    }
    orders: dict[str, Any] = {"base_per_day": float(base_orders), "total": {}}
    aov: dict[str, Any] = {
        "base": None if base_aov is None else float(base_aov),
        "certain": None if pm.aov is None else float(pm.aov),
        "total": {},
    }
    for q in QUANTILES:
        d_gmv = _predicted_dgmv(lift, pm, q, n)
        d_orders = d_gmv / pm.aov if pm.aov and lift.metric in ORDER_METRICS else None
        d_profit = d_gmv * pm.profit_per_gmv if pm.profit_per_gmv is not None else None
        tot_gmv = certain_gmv + d_gmv
        tot_profit = None if d_profit is None else certain_profit + d_profit
        period["total"][q] = {
            "dgmv": float(tot_gmv),
            "dorders": None if d_orders is None else float(d_orders),
            "dprofit": None if tot_profit is None else float(tot_profit),
        }
        per_day["total"][q] = {
            "dgmv": float(tot_gmv / n),
            "dorders": None if d_orders is None else float(d_orders / n),
            "dprofit": None if tot_profit is None else float(tot_profit / n),
        }
        per_order["total"][q] = {"dprofit": per(tot_profit, basis_orders)}
        after_orders = base_orders * n + (d_orders or ZERO)
        orders["total"][q] = {
            "per_day": float(after_orders / n),
            "period": float(after_orders),
            "changes": d_orders is not None,
        }
        aov["total"][q] = (
            None if after_orders <= 0 else float((pm.base_gmv_per_day * n + tot_gmv) / after_orders)
        )
    for block in (period["total"], per_day["total"]):
        _ordered(block)
    return {
        "period": period,
        "per_day": per_day,
        "per_order": per_order,
        "orders": orders,
        "aov": aov,
    }


def extra_orders_range(lift: Lift, pm: ProfitModel) -> tuple[Decimal, Decimal] | None:
    """Extra orders over the effect period at P10 / P90, for the shopee_profit what-ifs'
    ``predicted_extra_orders`` (an AOV lift is expressed as the equivalent orders)."""
    if not pm.aov:
        return None
    days = Decimal(pm.effect_days)
    lo = _predicted_dgmv(lift, pm, "p10", days) / pm.aov
    hi = _predicted_dgmv(lift, pm, "p90", days) / pm.aov
    return (min(lo, hi), max(lo, hi))


def magnitude_of(
    cand: Candidate, before: dict[str, Any], after: dict[str, Any], pm_aov: Decimal | None = None
) -> float | None:
    """Percent size of the change, for the scaled priors."""
    k = cand.kind
    inputs = cand.inputs
    if k in ("product_discount", "flash_sale", "program_registration", "price"):
        # the buyer's price falls from what it is today: only that part moves orders
        before_price, after_price = before.get("price"), after.get("price")
        if before_price and after_price:
            return (float(before_price) - float(after_price)) / float(before_price) * 100
        return None
    if k == "ads_budget":
        b0 = before.get("daily_budget") or before.get("spend_per_day")
        b1 = inputs.get("daily_budget")
        return None if not b0 or b1 is None else (float(b1) - float(b0)) / float(b0) * 100
    if k == "ads_roas_target":
        r0 = before.get("roas_target")
        r1 = inputs.get("roas_target")
        return None if not r0 or r1 is None else (float(r1) - float(r0)) / float(r0) * 100
    return None


__all__ = [
    "Lift",
    "convert",
    "extra_orders_range",
    "factor_from",
    "predict_lift",
    "safe_div",
    "ZERO",
]
