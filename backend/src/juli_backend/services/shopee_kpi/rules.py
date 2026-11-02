"""Phụ lục 01 arithmetic: baseline, ±D, stability windows, data sufficiency, acceptance.

A port of ``juli-client-ops/tools/kpi.py`` (the reference; numbers must match it). Pure:
no database, no clock. The inputs are the contract terms (``ContractTerms``, built from a
``kpi_contracts`` row, its ``kpi_targets`` / ``kpi_exclusions`` and the
``kpi_adjustments`` of its versions) and one daily series per KPI flow
(``Series``: day -> impressions, clicks, orders, gmv).

Rules (Phụ lục 01, Mục 1-4), per flow on its own metrics:

- excluded days (Mục 2.5): every MM-DD of ``sale_days`` ± ``pad_days`` plus the
  contract's extra days; dropped from the baseline, the ±D weeks and every window.
- baseline: the 30 days before ``measure_start`` minus excluded days, as a ratio of sums
  (CTR = Σclicks/Σimpressions, CTOR = Σorders/Σclicks, AOV = Σgmv/Σorders,
  impressions = mean per kept day).
- ±D: (high week − low week) / 2 / baseline over the 4 full weeks ending the day before
  ``measure_start``, clamped to [``d_min``, ``d_max``].
- stability window: ``stable_days`` (14), or ``stable_days_long`` (28) for a flow with fewer
  than ``long_if_clicks_14d_below`` baseline clicks per 14 days and for CTOR / AOV. A
  flow's metrics are optimised at the same time (Mục 2.1): each gets its own first window
  (inside the measurement period) whose value reaches the pass level.
- data sufficiency (Mục 2.3): baseline impressions ≥ ``min_impressions`` and clicks ≥
  ``min_clicks``; CTOR / AOV: ≥ ``min_orders_28d`` orders in the 28 days before
  ``measure_start`` (kept days).
- tracking flows are reported, never counted.
- acceptance: passed ≥ ⌈``acceptance_share`` × sufficient KPI metrics⌉ AND every metric of
  each ``required_flows`` flow (the product card) passed.
"""

from __future__ import annotations

import calendar
import math
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from fractions import Fraction
from typing import Any

#: (impressions, clicks, orders, gmv) of one day.
DayTotals = tuple[float, float, float, float]
Series = Mapping[date, DayTotals]

METRICS: tuple[str, ...] = ("impressions", "ctr", "ctor", "aov")
ORDER_METRICS: frozenset[str] = frozenset({"ctor", "aov"})
BASELINE_DAYS = 30
ORDERS_WINDOW_DAYS = 28

KIND_BASELINE_PCT = "baseline_pct"
KIND_ACHIEVED = "achieved"

#: ``params`` keys that have a Phụ lục 01 default; ``pass`` and ``target`` have none.
PARAM_DEFAULTS: dict[str, Any] = {
    "D_min": 0.05,
    "D_max": 0.15,
    "max_baseline_adj": 0.10,
    "min_impressions": 3000,
    "min_clicks": 100,
    "min_orders_28d": 100,
    "stable_days": 14,
    "stable_days_long": 28,
    "long_if_clicks_14d_below": 1000,
    "acceptance_share": 0.7,
    "required_flows": ["the_san_pham"],
    "exclusions": {"sale_days": ["10-10", "11-11", "12-12", "01-01"], "pad_days": 1},
}
REQUIRED_PARAMS: tuple[str, ...] = ("pass", "target")


class ContractTermsError(ValueError):
    """The contract row cannot drive the calculation (missing parameter, bad flow)."""


@dataclass(frozen=True)
class FlowSpec:
    flow: str
    metrics: tuple[str, ...]
    tracking: bool = False


@dataclass(frozen=True)
class Adjustment:
    """A ``kpi_adjustments`` row the calculation understands."""

    flow: str
    metric: str
    kind: str
    value: float
    effective_on: date


@dataclass(frozen=True)
class ContractTerms:
    measure_start: date
    pass_pct: float
    target_pct: float
    d_min: float
    d_max: float
    max_baseline_adj: float
    min_impressions: float
    min_clicks: float
    min_orders_28d: float
    stable_days: int
    stable_days_long: int
    long_if_clicks_14d_below: float
    acceptance_share: float
    required_flows: tuple[str, ...]
    sale_days: tuple[str, ...]
    pad_days: int
    flows: tuple[FlowSpec, ...]
    extra_excluded: frozenset[date] = frozenset()
    adjustments: tuple[Adjustment, ...] = ()

    @classmethod
    def from_params(
        cls,
        params: Mapping[str, Any],
        *,
        measure_start: date,
        flows: Iterable[FlowSpec],
        extra_excluded: Iterable[date] = (),
        adjustments: Iterable[Adjustment] = (),
    ) -> ContractTerms:
        missing = [k for k in REQUIRED_PARAMS if params.get(k) is None]
        if missing:
            raise ContractTermsError(f"contract params missing: {', '.join(missing)}")
        p = {**PARAM_DEFAULTS, **{k: v for k, v in params.items() if v is not None}}
        ex = {**PARAM_DEFAULTS["exclusions"], **(params.get("exclusions") or {})}
        extra = set(extra_excluded) | {date.fromisoformat(x) for x in ex.get("extra", [])}
        specs = tuple(flows)
        for spec in specs:
            bad = [m for m in spec.metrics if m not in METRICS]
            if bad:
                raise ContractTermsError(f"{spec.flow}: unknown metric {bad}")
        if not specs:
            raise ContractTermsError("contract has no flows")
        return cls(
            measure_start=measure_start,
            pass_pct=float(p["pass"]),
            target_pct=float(p["target"]),
            d_min=float(p["D_min"]),
            d_max=float(p["D_max"]),
            max_baseline_adj=float(p["max_baseline_adj"]),
            min_impressions=float(p["min_impressions"]),
            min_clicks=float(p["min_clicks"]),
            min_orders_28d=float(p["min_orders_28d"]),
            stable_days=int(p["stable_days"]),
            stable_days_long=int(p["stable_days_long"]),
            long_if_clicks_14d_below=float(p["long_if_clicks_14d_below"]),
            acceptance_share=float(p["acceptance_share"]),
            required_flows=tuple(p["required_flows"]),
            sale_days=tuple(ex.get("sale_days", ())),
            pad_days=int(ex.get("pad_days", 1)),
            flows=specs,
            extra_excluded=frozenset(extra),
            adjustments=tuple(adjustments),
        )

    def with_measure_start(self, measure_start: date) -> ContractTerms:
        """A proposal run on another start date (the reference's ``--measure-start``)."""
        return replace(self, measure_start=measure_start)


def flows_from_params(params: Mapping[str, Any]) -> list[FlowSpec]:
    """``params["flows"]`` in the reference's ``kpi.json`` shape -> flow specs."""
    out = []
    for flow, cfg in (params.get("flows") or {}).items():
        role = str(cfg.get("role") or "kpi")
        out.append(
            FlowSpec(
                flow=flow,
                metrics=tuple(cfg.get("metrics") or ()),
                tracking=role in ("theo_doi", "tracking"),
            )
        )
    return out


def excluded_days(terms: ContractTerms, first: date, last: date) -> frozenset[date]:
    """Mục 2.5 excluded dates in [first, last]."""
    out: set[date] = set()
    for year in range(first.year - 1, last.year + 2):
        for md in terms.sale_days:
            centre = date(year, int(md[:2]), int(md[3:]))
            out |= {centre + timedelta(k) for k in range(-terms.pad_days, terms.pad_days + 1)}
    out |= set(terms.extra_excluded)
    return frozenset(x for x in out if first <= x <= last)


def days_between(start: date, end: date) -> list[date]:
    return [start + timedelta(i) for i in range((end - start).days + 1)]


def window_value(
    series: Series, start: date, end: date, metric: str, excl: frozenset[date] = frozenset()
) -> float | None:
    """The metric over [start, end] minus excluded days.

    None when no day is kept, a kept day is missing, or the denominator is 0 (and, for
    impressions, when the sum is 0) -- the reference's ``value``.
    """
    kept = [x for x in days_between(start, end) if x not in excl]
    rows = [series.get(x) for x in kept]
    if not rows:
        return None
    present = [r for r in rows if r is not None]
    if len(present) != len(rows):
        return None
    imp, clk, ordr, gmv = (sum(r[i] for r in present) for i in range(4))
    if metric == "impressions":
        return imp / len(present) if imp else None
    num, den = {"ctr": (clk, imp), "ctor": (ordr, clk), "aov": (gmv, ordr)}[metric]
    return num / den if den else None


def months_later(start: date, k: int) -> date:
    """The same calendar date ``k`` months later (clamped to the month's last day)."""
    y, m0 = divmod(start.month - 1 + k, 12)
    year, month = start.year + y, m0 + 1
    return date(year, month, min(start.day, calendar.monthrange(year, month)[1]))


def milestone_end(start: date, k: int) -> date:
    """Month ``k`` of the measurement ends the day before the same date (29/10 -> 28/11)."""
    return months_later(start, k) - timedelta(1)


def window_days_for(terms: ContractTerms, spec: FlowSpec, series: Series) -> int:
    """14 days, or 28 for a low-click flow and for a flow measured on CTOR / AOV."""
    start = terms.measure_start
    b0 = start - timedelta(BASELINE_DAYS)
    excl = excluded_days(terms, b0 - timedelta(BASELINE_DAYS), start)
    kept = [x for x in days_between(b0, start - timedelta(1)) if x not in excl]
    clicks = sum(series[x][1] for x in kept if x in series)
    clicks14 = clicks / len(kept) * 14 if kept else 0.0
    long_window = any(m in ORDER_METRICS for m in spec.metrics) or (
        clicks14 < terms.long_if_clicks_14d_below
    )
    return terms.stable_days_long if long_window else terms.stable_days


@dataclass
class MetricResult:
    metric: str
    tracking: bool
    baseline: float | None
    d_pct: float | None
    d_raw: float | None
    window_days: int
    last_window: float | None
    vs_baseline: float | None
    pass_level: float | None = None
    target_level: float | None = None
    first_stable_pass: dict[str, Any] | None = None
    achieved_floor: float | None = None
    achieved_ok: bool | None = None

    @property
    def passed(self) -> bool:
        return self.first_stable_pass is not None and self.achieved_ok is not False


@dataclass
class FlowResult:
    flow: str
    tracking: bool
    eligible: bool
    baseline_days_kept: int
    baseline_impressions_30d: float
    baseline_clicks_30d: float
    orders_28d: float
    metrics: list[MetricResult]
    weekly: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Acceptance:
    eligible: int
    passed: int
    needed: int
    required_flows_passed: bool

    @property
    def accepted(self) -> bool:
        return self.eligible > 0 and self.passed >= self.needed and self.required_flows_passed


@dataclass
class KpiReport:
    as_of: date
    measure_start: date
    flows: list[FlowResult]
    acceptance: Acceptance
    excluded_baseline: list[date]
    excluded_measure: list[date]
    warnings: list[str]

    def to_json(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of.isoformat(),
            "measure_start": self.measure_start.isoformat(),
            "excluded_baseline": [x.isoformat() for x in self.excluded_baseline],
            "excluded_measure": [x.isoformat() for x in self.excluded_measure],
            "flows": [
                {
                    "flow": f.flow,
                    "tracking": f.tracking,
                    "eligible": f.eligible,
                    "baseline_days_kept": f.baseline_days_kept,
                    "baseline_impressions_30d": f.baseline_impressions_30d,
                    "baseline_clicks_30d": f.baseline_clicks_30d,
                    "orders_28d": f.orders_28d,
                    "metrics": [{**m.__dict__, "passed": m.passed} for m in f.metrics],
                    "weekly": f.weekly,
                }
                for f in self.flows
            ],
            "acceptance": {**self.acceptance.__dict__, "accepted": self.acceptance.accepted},
            "warnings": self.warnings,
        }


def _pct(v: float | None, base: float | None) -> float | None:
    return None if v is None or not base else v / base - 1


def _d_pct(
    terms: ContractTerms, series: Series, metric: str, base: float | None, excl: frozenset[date]
) -> tuple[float | None, float | None]:
    """(clamped ±D, raw ±D) over the 4 full weeks ending the day before measure_start."""
    b0 = terms.measure_start - timedelta(BASELINE_DAYS)
    weeks = [
        window_value(series, b0 + timedelta(2 + 7 * w), b0 + timedelta(8 + 7 * w), metric, excl)
        for w in range(4)
    ]
    if not base or any(x is None for x in weeks):
        return None, None
    vals = [x for x in weeks if x is not None]
    raw = (max(vals) - min(vals)) / 2 / base
    return min(max(raw, terms.d_min), terms.d_max), raw


def flow_result(
    terms: ContractTerms, spec: FlowSpec, series: Series, as_of: date, warnings: list[str]
) -> FlowResult:
    start = terms.measure_start
    b0, b1 = start - timedelta(BASELINE_DAYS), start - timedelta(1)
    excl = excluded_days(terms, b0 - timedelta(BASELINE_DAYS), max(as_of, start))
    mets = spec.metrics
    base: dict[str, float | None] = {m: window_value(series, b0, b1, m, excl) for m in mets}
    kept = [x for x in days_between(b0, b1) if x not in excl]
    tot_imp = sum(series[x][0] for x in kept if x in series)
    tot_clk = sum(series[x][1] for x in kept if x in series)
    o28 = [start - timedelta(i) for i in range(1, ORDERS_WINDOW_DAYS + 1)]
    tot_ord28 = sum(series[x][2] for x in o28 if x in series and x not in excl)
    if any(m in ORDER_METRICS for m in mets):
        eligible = tot_ord28 >= terms.min_orders_28d
    else:
        eligible = tot_imp >= terms.min_impressions and tot_clk >= terms.min_clicks
    window = window_days_for(terms, spec, series)

    # Baseline adjustments confirmed by email, cumulative, applied as of as_of.
    month_adj: dict[tuple[str, str], float] = defaultdict(float)
    for adj in terms.adjustments:
        if (
            adj.flow == spec.flow
            and adj.kind == KIND_BASELINE_PCT
            and adj.effective_on <= as_of
            and adj.metric in base
        ):
            current = base[adj.metric]
            base[adj.metric] = current * (1 + adj.value) if current else None
            month_adj[(adj.metric, adj.effective_on.isoformat()[:7])] += adj.value
    for (metric, month), total in month_adj.items():
        if abs(total) > terms.max_baseline_adj + 1e-9:
            warnings.append(
                f"{spec.flow}/{metric}: baseline adjustment {total:+.0%} in {month} exceeds "
                f"±{terms.max_baseline_adj:.0%} (needs a separate agreement)"
            )

    achieved = {
        a.metric: a.value
        for a in terms.adjustments
        if a.flow == spec.flow and a.kind == KIND_ACHIEVED and a.effective_on <= as_of
    }
    win_start = as_of - timedelta(window - 1)
    rows: list[MetricResult] = []
    for m in mets:
        d_pct, d_raw = _d_pct(terms, series, m, base[m], excl)
        last = window_value(series, win_start, as_of, m, excl) if win_start >= start else None
        row = MetricResult(
            metric=m,
            tracking=spec.tracking,
            baseline=base[m],
            d_pct=d_pct,
            d_raw=d_raw,
            window_days=window,
            last_window=last,
            vs_baseline=_pct(last, base[m]),
        )
        b = base[m]
        if b:
            row.pass_level = b * (1 + terms.pass_pct)
            row.target_level = b * (1 + terms.target_pct)
            end = start + timedelta(window - 1)
            while end <= as_of:
                v = window_value(series, end - timedelta(window - 1), end, m, excl)
                if v is not None and v >= row.pass_level:
                    row.first_stable_pass = {"window_end": end.isoformat(), "value": v}
                    break
                end += timedelta(1)
        if d_pct is not None:
            floor_of = achieved.get(m)
            if floor_of is None and row.first_stable_pass is not None:
                floor_of = float(row.first_stable_pass["value"])  # not yet confirmed by email
            if floor_of is not None:
                row.achieved_floor = floor_of * (1 - d_pct)
                row.achieved_ok = None if last is None else last >= row.achieved_floor
        rows.append(row)

    weekly = []
    w0 = start
    while w0 + timedelta(6) <= as_of:
        w1 = w0 + timedelta(6)
        weekly.append(
            {
                "from": w0.isoformat(),
                "to": w1.isoformat(),
                **{m: window_value(series, w0, w1, m, excl) for m in mets},
            }
        )
        w0 += timedelta(7)

    return FlowResult(
        flow=spec.flow,
        tracking=spec.tracking,
        eligible=eligible,
        baseline_days_kept=len(kept),
        baseline_impressions_30d=tot_imp,
        baseline_clicks_30d=tot_clk,
        orders_28d=tot_ord28,
        metrics=rows,
        weekly=weekly,
    )


def acceptance(terms: ContractTerms, flows: list[FlowResult]) -> Acceptance:
    counted = [m for f in flows if f.eligible and not f.tracking for m in f.metrics]
    passed = sum(1 for m in counted if m.passed)
    needed = math.ceil(Fraction(str(terms.acceptance_share)) * len(counted))
    required = [f for f in flows if f.flow in terms.required_flows and not f.tracking]
    required_ok = all(f.eligible and all(m.passed for m in f.metrics) for f in required)
    return Acceptance(
        eligible=len(counted), passed=passed, needed=needed, required_flows_passed=required_ok
    )


def kpi_report(
    terms: ContractTerms, series_by_flow: Mapping[str, Series], as_of: date
) -> KpiReport:
    start = terms.measure_start
    b0, b1 = start - timedelta(BASELINE_DAYS), start - timedelta(1)
    excl = excluded_days(terms, b0 - timedelta(BASELINE_DAYS), max(as_of, start))
    warnings: list[str] = []
    flows = [
        flow_result(terms, spec, series_by_flow.get(spec.flow, {}), as_of, warnings)
        for spec in terms.flows
    ]
    return KpiReport(
        as_of=as_of,
        measure_start=start,
        flows=flows,
        acceptance=acceptance(terms, flows),
        excluded_baseline=sorted(x for x in excl if b0 <= x <= b1),
        excluded_measure=sorted(x for x in excl if start <= x <= as_of),
        warnings=warnings,
    )
