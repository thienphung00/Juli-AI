"""Expected move per KPI milestone (Phụ lục 01 Mục 4.1): INTERNAL, Ops only, never seller-facing.

A port of ``juli-client-ops/tools/expected_move.py`` plus the flow-GMV block of its
simulator page (``tools/dashboards/kpi_simulator.html``). Pure: no database, no clock.

Per (flow, metric) of the contract, for milestone k = 1, 2, 3 (the stability window of
:mod:`.rules` ending the day before the same date k months after ``measure_start`` --
29/10 -> 28/11, 28/12, 28/01):

- baseline: as :func:`.rules.window_value` over the 30 days before ``measure_start``.
- drift: the empirical "no change" move, log(window value / its own trailing 30-day
  baseline) over every past window of the series, every double day ± 1 excluded. Mean =
  trend per ~30 days, SD = noise + month-to-month drift. Fewer than 20 windows -> none.
- levers (``lever_plans``): each effect is uniform on [low, high], active from
  ``starts_on + lag_days``; inside a window it counts by the share of kept days it is
  active; effects multiply. ``wave`` = the month's change batch.
- expected = baseline × exp(trend_weight × trend × k) × Π(1 + share × mid); log-normal
  with SD² = drift SD² + Σ (share × range)² / 12; P(pass) = P(value ≥ pass level).
  ``trend_weight`` 0 = no trend, 1 = the historical trend (the reference's two scenarios).
  log(expected) is linear in the weight and SD does not depend on it, so a reader can
  interpolate any weight from the two stored rows.
- flow GMV / 30 days = impressions × CTR × CTOR × AOV × 30 with the log moves added and
  the variances added: impressions and CTR from the flow's own projection, CTOR and AOV
  from the whole-shop (``ca_shop``) projection's move applied to the flow's own baseline.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from juli_backend.services.shopee_kpi.rules import (
    BASELINE_DAYS,
    ContractTerms,
    FlowSpec,
    Series,
    excluded_days,
    milestone_end,
    window_days_for,
    window_value,
)

METHOD_VERSION = "expected_move_v1"
MILESTONES: tuple[int, ...] = (1, 2, 3)
TREND_WEIGHTS: tuple[float, ...] = (0.0, 1.0)
Z90 = 1.645
MIN_DRIFT_WINDOWS = 20
HISTORY_DAYS = 400
HORIZON_DAYS = 90
GMV_METRIC = "gmv_30d"
SHOP_FLOW = "ca_shop"
GMV_DAYS = 30


@dataclass(frozen=True)
class LeverEffect:
    """One ``lever_plans`` row: a lever's effect on one (flow, metric)."""

    lever_key: str
    wave: int
    starts_on: date
    lag_days: int
    flow: str
    metric: str
    low: float
    high: float
    ends_on: date | None = None

    @property
    def active_from(self) -> date:
        return self.starts_on + timedelta(self.lag_days)


@dataclass(frozen=True)
class Drift:
    mean: float
    sd: float
    n_windows: int


@dataclass(frozen=True)
class Projection:
    """log-normal law of one (flow, metric) window value at one milestone."""

    base: float
    mu: float
    sd: float
    lever_log_effect: float
    window_end: date
    window_days: int
    waves: tuple[int, ...]


@dataclass(frozen=True)
class Forecast:
    flow: str
    metric: str
    milestone: int
    window_end: date
    window_days: int
    trend_weight: float
    baseline: float
    expected: float
    lo90: float
    hi90: float
    p_pass: float | None
    sd_log: float
    lever_log_effect: float
    waves: tuple[int, ...]


def phi(z: float) -> float:
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def all_double_days(first: date, last: date, pad: int = 1) -> frozenset[date]:
    """Every MM-MM double day ± pad of the years first..last (01/01 included)."""
    out: set[date] = set()
    for year in range(first.year, last.year + 1):
        for month in range(1, 13):
            centre = date(year, month, month)
            out |= {centre + timedelta(k) for k in range(-pad, pad + 1)}
    return frozenset(out)


def drift(series: Series, metric: str, window: int, excl: frozenset[date]) -> Drift | None:
    days = sorted(series)
    if not days:
        return None
    first, last = days[0], days[-1]
    xs: list[float] = []
    t = first + timedelta(BASELINE_DAYS)
    while t + timedelta(window - 1) <= last:
        b = window_value(series, t - timedelta(BASELINE_DAYS), t - timedelta(1), metric, excl)
        w = window_value(series, t, t + timedelta(window - 1), metric, excl)
        if b and w:
            xs.append(math.log(w / b))
        t += timedelta(1)
    if len(xs) < MIN_DRIFT_WINDOWS:
        return None
    mu = sum(xs) / len(xs)
    sd = math.sqrt(sum((x - mu) ** 2 for x in xs) / (len(xs) - 1))
    return Drift(mean=mu, sd=sd, n_windows=len(xs))


def lever_move(
    levers: Iterable[LeverEffect], flow: str, metric: str, window: Sequence[date]
) -> tuple[float, float]:
    """(Σ log(1 + share·mid), Σ (share·range)²/12) of the effects on (flow, metric)."""
    logm, var = 0.0, 0.0
    if not window:
        return logm, var
    for lv in levers:
        if lv.flow != flow or lv.metric != metric:
            continue
        on, off = lv.active_from, lv.ends_on
        share = sum(1 for x in window if x >= on and (off is None or x < off)) / len(window)
        if share > 0:
            mid, rng = (lv.low + lv.high) / 2, lv.high - lv.low
            logm += math.log(1 + share * mid)
            var += (share * rng) ** 2 / 12
    return logm, var


class ExpectedMove:
    """Projections for one contract over its flows' series and a lever plan."""

    def __init__(
        self,
        terms: ContractTerms,
        series_by_flow: Mapping[str, Series],
        levers: Sequence[LeverEffect],
    ) -> None:
        self.terms = terms
        self.series = series_by_flow
        self.levers = list(levers)
        start = terms.measure_start
        b0 = start - timedelta(BASELINE_DAYS)
        self.excl = excluded_days(
            terms, b0 - timedelta(HISTORY_DAYS), start + timedelta(HORIZON_DAYS)
        )
        self.hist_excl = self.excl | all_double_days(
            b0 - timedelta(HISTORY_DAYS), start - timedelta(1)
        )
        self._drift: dict[tuple[str, str], Drift | None] = {}
        self._window: dict[str, int] = {}

    def window_days(self, spec: FlowSpec) -> int:
        if spec.flow not in self._window:
            self._window[spec.flow] = window_days_for(
                self.terms, spec, self.series.get(spec.flow, {})
            )
        return self._window[spec.flow]

    def baseline(self, flow: str, metric: str) -> float | None:
        start = self.terms.measure_start
        return window_value(
            self.series.get(flow, {}),
            start - timedelta(BASELINE_DAYS),
            start - timedelta(1),
            metric,
            self.excl,
        )

    def drift_of(self, spec: FlowSpec, metric: str) -> Drift | None:
        key = (spec.flow, metric)
        if key not in self._drift:
            self._drift[key] = drift(
                self.series.get(spec.flow, {}), metric, self.window_days(spec), self.hist_excl
            )
        return self._drift[key]

    def project(
        self, spec: FlowSpec, metric: str, k: int, trend_weight: float
    ) -> Projection | None:
        base = self.baseline(spec.flow, metric)
        dr = self.drift_of(spec, metric)
        if not base or dr is None:
            return None
        window = self.window_days(spec)
        end = milestone_end(self.terms.measure_start, k)
        kept = [end - timedelta(i) for i in range(window) if end - timedelta(i) not in self.excl]
        logm, var = lever_move(self.levers, spec.flow, metric, kept)
        hit_waves = sorted(
            {
                lv.wave
                for lv in self.levers
                if lv.flow == spec.flow and lv.metric == metric and lv.active_from <= end
            }
        )
        sd = math.sqrt(dr.sd**2 + var)
        mu = math.log(base) + logm + trend_weight * dr.mean * k
        return Projection(
            base=base,
            mu=mu,
            sd=sd,
            lever_log_effect=logm,
            window_end=end,
            window_days=window,
            waves=tuple(hit_waves),
        )

    def forecasts(self, trend_weights: Sequence[float] = TREND_WEIGHTS) -> list[Forecast]:
        out: list[Forecast] = []
        for spec in self.terms.flows:
            for metric in spec.metrics:
                for k in MILESTONES:
                    for weight in trend_weights:
                        p = self.project(spec, metric, k, weight)
                        if p is None:
                            continue
                        pass_level = p.base * (1 + self.terms.pass_pct)
                        out.append(_forecast(spec.flow, metric, k, weight, p, pass_level))
        out.extend(self.gmv_forecasts(trend_weights))
        return out

    def gmv_forecasts(self, trend_weights: Sequence[float] = TREND_WEIGHTS) -> list[Forecast]:
        shop = next((s for s in self.terms.flows if s.flow == SHOP_FLOW), None)
        if shop is None:
            return []
        shop_spec = FlowSpec(flow=SHOP_FLOW, metrics=("ctor", "aov"), tracking=shop.tracking)
        out: list[Forecast] = []
        for spec in self.terms.flows:
            if spec.flow == SHOP_FLOW or not {"impressions", "ctr"} <= set(spec.metrics):
                continue
            for k in MILESTONES:
                for weight in trend_weights:
                    parts: list[Projection] = []
                    for metric in ("impressions", "ctr"):
                        p = self.project(spec, metric, k, weight)
                        if p is not None:
                            parts.append(p)
                    for metric in ("ctor", "aov"):
                        own = self.baseline(spec.flow, metric)
                        p = self.project(shop_spec, metric, k, weight)
                        if p is not None and own:
                            parts.append(
                                Projection(
                                    base=own,
                                    mu=p.mu - math.log(p.base) + math.log(own),
                                    sd=p.sd,
                                    lever_log_effect=p.lever_log_effect,
                                    window_end=p.window_end,
                                    window_days=p.window_days,
                                    waves=p.waves,
                                )
                            )
                    if len(parts) != 4:
                        continue
                    base = math.prod(p.base for p in parts) * GMV_DAYS
                    mu = sum(p.mu for p in parts) + math.log(GMV_DAYS)
                    sd = math.sqrt(sum(p.sd**2 for p in parts))
                    gmv = Projection(
                        base=base,
                        mu=mu,
                        sd=sd,
                        lever_log_effect=sum(p.lever_log_effect for p in parts),
                        window_end=parts[0].window_end,
                        window_days=parts[0].window_days,
                        waves=tuple(sorted({w for p in parts for w in p.waves})),
                    )
                    out.append(_forecast(spec.flow, GMV_METRIC, k, weight, gmv, None))
        return out


def _forecast(
    flow: str, metric: str, k: int, weight: float, p: Projection, pass_level: float | None
) -> Forecast:
    p_pass = None
    if pass_level is not None:
        p_pass = (
            1 - phi((math.log(pass_level) - p.mu) / p.sd)
            if p.sd > 0
            else float(math.exp(p.mu) >= pass_level)
        )
    return Forecast(
        flow=flow,
        metric=metric,
        milestone=k,
        window_end=p.window_end,
        window_days=p.window_days,
        trend_weight=weight,
        baseline=p.base,
        expected=math.exp(p.mu),
        lo90=math.exp(p.mu - Z90 * p.sd),
        hi90=math.exp(p.mu + Z90 * p.sd),
        p_pass=p_pass,
        sd_log=p.sd,
        lever_log_effect=p.lever_log_effect,
        waves=p.waves,
    )
