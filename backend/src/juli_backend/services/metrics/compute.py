"""The only place metric formulas run: a pure evaluator over :data:`~.registry.METRICS`.

Rules (doc §2): ratios come from summed components (a formula reads components, never an
average of a metric); a missing component is ``None`` and every metric over it is ``None``
(missing is not zero); a division by 0 or ``None`` is ``None``; rounding happens once, on the
metric asked for -- the metrics it reads are used unrounded. No database, no clock.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal
from enum import StrEnum

from juli_backend.services.metrics.components import COMPONENTS, Components
from juli_backend.services.metrics.registry import (
    DERIVATION_VERSION,
    METRICS,
    PARAMS,
    Basis,
    Expr,
    Rounding,
)
from juli_backend.services.shopee_profit.money import ONE, ZERO, pct_points, safe_div, to_dong

Value = Decimal | date | None


@dataclass(frozen=True)
class MetricValue:
    value: Value
    basis: Basis
    #: 0-1 for a cost-dependent metric, else ``None``
    coverage: Decimal | None
    as_of: date | None
    derivation_version: str
    partial: bool


class _Context:
    def __init__(
        self, components: Components, as_of: date | None, params: Mapping[str, Decimal]
    ) -> None:
        self.components = components
        self.as_of = as_of
        self.params = params
        self.memo: dict[str, Value] = {}

    def ref(self, id: str) -> Value:
        if id in COMPONENTS:
            return self.components.get(id)
        if id in self.memo:
            return self.memo[id]
        metric = METRICS.get(id)
        if metric is None:
            raise KeyError(f"unknown component or metric id {id!r}")
        if isinstance(metric.formula, tuple) and metric.formula[0] == "helper":
            raise ValueError(f"{id} is computed by compute.{metric.formula[1]}, not evaluate()")
        self.memo[id] = self.eval(metric.formula)
        return self.memo[id]

    def eval(self, expr: Expr) -> Value:
        if isinstance(expr, str):
            return self.ref(expr)
        op, *args = expr
        if op == "const":
            return Decimal(args[0])
        if op == "param":
            return self.params.get(args[0], PARAMS[args[0]])
        if op == "date_offset":
            days = self.eval(args[0])
            if self.as_of is None or not isinstance(days, Decimal):
                return None
            return self.as_of + timedelta(
                days=int(_settle(days).to_integral_value(rounding=ROUND_FLOOR))
            )
        values = [self.eval(a) for a in args]
        if any(v is None for v in values):
            return None
        nums = [v for v in values if isinstance(v, Decimal)]
        if len(nums) != len(values):
            raise TypeError(f"{op} over a date")
        if op == "sum":
            return sum(nums, ZERO)
        if op == "sub":
            return nums[0] - sum(nums[1:], ZERO)
        if op == "mul":
            return nums[0] * nums[1]
        if op == "div":
            return safe_div(nums[0], nums[1])
        if op == "min":
            return min(nums)
        if op == "clamp0":
            return max(nums[0], ZERO)
        raise ValueError(f"unknown operator {op!r}")


def _quantize(value: Decimal, step: str, rounding: str = ROUND_HALF_UP) -> Decimal:
    return value.quantize(Decimal(step), rounding=rounding)


def _settle(value: Decimal) -> Decimal:
    """Drop division dust (10/7 × 21 = 30.000…01) before a ceiling or a floor."""
    return _quantize(value, "0.000001")


def round_value(rule: Rounding, value: Value) -> Value:
    """Apply one registry rounding rule (``money.py`` for đồng and percent points)."""
    if not isinstance(value, Decimal):
        return value
    if rule is Rounding.dong:
        return to_dong(value)
    if rule is Rounding.pct_0_1:
        return pct_points(value)
    if rule is Rounding.whole:
        return to_dong(value)
    if rule is Rounding.units_ceil:
        return _settle(value).to_integral_value(rounding=ROUND_CEILING)
    if rule is Rounding.days_floor:
        return _settle(value).to_integral_value(rounding=ROUND_FLOOR)
    if rule in (Rounding.x_0_1, Rounding.one_decimal):
        return _quantize(value, "0.1")
    if rule is Rounding.ratio_0_001:
        return _quantize(value, "0.001")
    return value


def evaluate(
    metric_id: str,
    components: Components,
    *,
    as_of: date | None = None,
    params: Mapping[str, Decimal] | None = None,
) -> MetricValue:
    """One metric over one scope's components, rounded by its registry rule."""
    metric = METRICS[metric_id]
    ctx = _Context(components, as_of, params or {})
    raw = ctx.ref(metric_id)
    coverage: Decimal | None = None
    if metric.coverage is not None:
        cov = ctx.ref(metric.coverage)
        coverage = cov if isinstance(cov, Decimal) else None
    return MetricValue(
        value=round_value(metric.rounding, raw),
        basis=metric.basis,
        coverage=coverage,
        as_of=as_of,
        derivation_version=DERIVATION_VERSION,
        partial=raw is not None and coverage is not None and coverage < ONE,
    )


def raw_value(metric_id: str, components: Components, *, as_of: date | None = None) -> Value:
    """The unrounded value (for allocation sums that must add up before rounding)."""
    return _Context(components, as_of, {}).ref(metric_id)


def change(value: Decimal | None, ref: Decimal | None) -> Decimal | None:
    """ "Thay đổi" = value ÷ ref − 1; ``None`` when either is missing or ref is 0."""
    if value is None or ref is None:
        return None
    ratio = safe_div(value, ref)
    return None if ratio is None else ratio - ONE


def per_day(metric_id: str, value: Decimal | None, days: int) -> Decimal | None:
    """ "/ ngày" of a summable metric; a ratio is the same per day and is refused."""
    if not METRICS[metric_id].summable:
        raise ValueError(f"{metric_id} is not summable: it has no per-day value")
    if value is None or days <= 0:
        return None
    return value / Decimal(days)


# -- kol_status (owner 2026-11-15: decided by the KOC's own data) ----------------------------


class KolState(StrEnum):
    effective = "Hiệu quả"
    not_effective = "Không hiệu quả"
    not_enough_data = "Chưa đủ dữ liệu"


@dataclass(frozen=True)
class KolStatus:
    state: KolState
    roi: Decimal | None
    low: Decimal | None
    high: Decimal | None


#: two-sided 90 % normal quantile
Z_90 = Decimal("1.6448536269514722")


def kol_status(
    order_net_profits: Sequence[Decimal], samples_cost: Decimal | None, commission: Decimal
) -> KolStatus:
    """The three states from a 90 % interval of ``roi_kol``.

    ``order_net_profits`` are the KOC's orders' net profits after commission over the period
    (n orders, sum P, mean m, sample standard deviation sd). With samples S and commission C,
    ``roi_kol = (P − S) ÷ (C + S) = (n·m − S) ÷ (C + S)``, which is increasing in m because
    C + S > 0. The interval of m is the closed-form normal approximation
    ``m ± z·sd ÷ √n`` (z = 1.645, two-sided 90 %); mapping both ends through the formula gives
    the interval of ``roi_kol``. No resampling, so the result is deterministic.

    **Hiệu quả** when the lower bound > 1, **Không hiệu quả** when the upper bound < 1, else
    **Chưa đủ dữ liệu** -- also when there are fewer than two orders (no spread) or C + S ≤ 0.
    """
    samples = samples_cost or ZERO
    denominator = commission + samples
    n = len(order_net_profits)
    total = sum(order_net_profits, ZERO)
    roi = safe_div(total - samples, denominator) if denominator > 0 else None
    if n < 2 or denominator <= 0:
        return KolStatus(KolState.not_enough_data, roi, None, None)
    mean = total / n
    var = sum(((p - mean) ** 2 for p in order_net_profits), ZERO) / (n - 1)
    half = Z_90 * var.sqrt() / Decimal(n).sqrt()
    low = (n * (mean - half) - samples) / denominator
    high = (n * (mean + half) - samples) / denominator
    if low > ONE:
        state = KolState.effective
    elif high < ONE:
        state = KolState.not_effective
    else:
        state = KolState.not_enough_data
    return KolStatus(state, roi, low, high)
