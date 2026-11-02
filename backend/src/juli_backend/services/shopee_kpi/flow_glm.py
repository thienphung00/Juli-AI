"""CTR / CTOR flow model (v2): one quasi-binomial GLM per (flow, metric).

A port of ``juli-client-ops/tools/flow_model.py`` without statsmodels / patsy / pandas
(not backend dependencies): IRLS in numpy and a patsy-compatible cubic B-spline.

    logit(rate) ~ C(dow) + double_day + day1 + day15 + day25 + bs(t, df=4)

Calendar terms follow Shopee's campaign calendar: double days (MM-MM, 01/01 included) =
"Spike"; day 1 (not January), day 15 and day 25 = "Mini Spike". ``C(dow)`` is treatment
coded against the first weekday present; ``bs(t, df=4)`` is patsy's: degree 3, one
interior knot at the median of ``t``, boundary knots at its min / max, first basis column
dropped. Dispersion = max(1, Pearson χ² / residual df) (quasi-binomial).

The fitted parameters are client data (ADR-116 §3): they are never stored. The job stores
only the forecast band (``kpi_forecasts``, ``method_version = "flow_glm_v2"``) and
recomputes the model from ``platform_daily_metrics`` whenever it runs, so deleting the
shop's metrics and forecasts deletes everything the model was.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import numpy.typing as npt

from juli_backend.services.shopee_kpi.rules import Series

METHOD_VERSION = "flow_glm_v2"
FORMULA = "C(dow) + double_day + day1 + day15 + day25 + bs(t, df=4)"
#: metric -> (numerator, denominator) index into a day's (impressions, clicks, orders, gmv).
RATE_METRICS: dict[str, tuple[int, int]] = {"ctr": (1, 0), "ctor": (2, 1)}
#: Same "enough data" floor as Phụ lục 01 Mục 2.3 (denominator / numerator sums).
MIN_DEN, MIN_NUM = 3000.0, 100.0
CALENDAR_TERMS: tuple[str, ...] = ("double_day", "day1", "day15", "day25")
SPLINE_DF = 4
SPLINE_DEGREE = 3
Z90 = 1.645
#: The reference converts the 95 % mean interval back to an SE with this literal.
Z95_LITERAL = 1.96
Z95 = 1.959963984540054
MAX_ITER = 100
TOL = 1e-12

FloatArray = npt.NDArray[np.float64]


def calendar_row(day: date) -> dict[str, float]:
    return {
        "double_day": float(day.month == day.day),
        "day1": float(day.day == 1 and day.month != 1),
        "day15": float(day.day == 15),
        "day25": float(day.day == 25),
    }


@dataclass(frozen=True)
class SplineBasis:
    """patsy ``bs(x, df=4)``: knots fixed on the fitting data, reused for prediction."""

    knots: tuple[float, ...]
    degree: int = SPLINE_DEGREE

    @classmethod
    def fit(cls, x: FloatArray, df: int = SPLINE_DF, degree: int = SPLINE_DEGREE) -> SplineBasis:
        order = degree + 1
        n_inner = df - order + 1  # patsy: include_intercept=False adds one inner knot
        inner: list[float] = []
        if n_inner > 0:
            inner = [float(k) for k in np.percentile(x, np.linspace(0, 100, n_inner + 2)[1:-1])]
        lo, hi = float(np.min(x)), float(np.max(x))
        knots = [lo] * order + inner + [hi] * order
        return cls(knots=tuple(knots), degree=degree)

    def __call__(self, x: FloatArray) -> FloatArray:
        """Basis columns 1.. (column 0 dropped, as patsy without intercept)."""
        return _bspline_design(np.asarray(x, dtype=float), np.array(self.knots), self.degree)[:, 1:]


def _bspline_design(x: FloatArray, t: FloatArray, k: int) -> FloatArray:
    """Cox-de Boor B-spline basis; the right boundary belongs to the last interval."""
    n_basis = len(t) - k - 1
    # degree 0: indicator of [t_i, t_{i+1}); x == t_max goes to the last non-empty interval.
    b = np.zeros((len(x), len(t) - 1))
    for i in range(len(t) - 1):
        if t[i] < t[i + 1]:
            b[:, i] = (x >= t[i]) & (x < t[i + 1])
    last = max(i for i in range(len(t) - 1) if t[i] < t[i + 1])
    b[x == t[-1], last] = 1.0
    for d in range(1, k + 1):
        nxt = np.zeros((len(x), len(t) - 1 - d))
        for i in range(len(t) - 1 - d):
            left_den = t[i + d] - t[i]
            right_den = t[i + d + 1] - t[i + 1]
            left = (x - t[i]) / left_den * b[:, i] if left_den > 0 else 0.0
            right = (t[i + d + 1] - x) / right_den * b[:, i + 1] if right_den > 0 else 0.0
            nxt[:, i] = left + right
        b = nxt
    return b[:, :n_basis]


@dataclass(frozen=True)
class Design:
    """Column layout of one fit, so new days get the same columns."""

    dow_levels: tuple[int, ...]  # the weekday levels after the reference level
    spline: SplineBasis
    columns: tuple[str, ...]

    def matrix(self, days: Sequence[date], t: FloatArray, calendar: bool = True) -> FloatArray:
        n = len(days)
        cols: list[FloatArray] = [np.ones(n)]
        dows = np.array([d.weekday() for d in days])
        cols += [(dows == lvl).astype(float) for lvl in self.dow_levels]
        cal = [calendar_row(d) for d in days]
        for term in CALENDAR_TERMS:
            cols.append(np.array([c[term] if calendar else 0.0 for c in cal]))
        spline = self.spline(t)
        cols += [spline[:, j] for j in range(spline.shape[1])]
        return np.column_stack(cols)


def make_design(days: Sequence[date], t: FloatArray) -> Design:
    present = sorted({d.weekday() for d in days})
    levels = tuple(present[1:])
    spline = SplineBasis.fit(t)
    columns = (
        ("Intercept",)
        + tuple(f"C(dow)[T.{lvl}]" for lvl in levels)
        + CALENDAR_TERMS
        + tuple(f"bs(t, df={SPLINE_DF})[{j}]" for j in range(SPLINE_DF))
    )
    return Design(dow_levels=levels, spline=spline, columns=columns)


@dataclass(frozen=True)
class GlmFit:
    beta: FloatArray
    cov_unscaled: FloatArray  # (X' W X)^+ at the optimum
    dispersion: float
    n_obs: int
    rank: int

    @property
    def cov(self) -> FloatArray:
        return self.dispersion * self.cov_unscaled

    @property
    def se(self) -> FloatArray:
        return np.sqrt(np.clip(np.diag(self.cov), 0.0, None))


def _expit(eta: FloatArray) -> FloatArray:
    return 1.0 / (1.0 + np.exp(-eta))


def fit_quasi_binomial(x: FloatArray, successes: FloatArray, trials: FloatArray) -> GlmFit:
    """Binomial GLM (logit) by IRLS; dispersion from Pearson χ², floored at 1."""
    y = successes / trials
    mu = (trials * y + 0.5) / (trials + 1.0)
    eta = np.log(mu / (1 - mu))
    beta = np.zeros(x.shape[1])
    dev_old = np.inf
    for _ in range(MAX_ITER):
        w = trials * mu * (1 - mu)
        z = eta + (y - mu) / (mu * (1 - mu))
        sw = np.sqrt(w)
        beta, *_ = np.linalg.lstsq(x * sw[:, None], z * sw, rcond=None)
        eta = x @ beta
        mu = np.clip(_expit(eta), 1e-12, 1 - 1e-12)
        dev = _deviance(y, mu, trials)
        if abs(dev - dev_old) <= TOL * (abs(dev) + 1e-30):
            break
        dev_old = dev
    w = trials * mu * (1 - mu)
    xtwx = x.T @ (x * w[:, None])
    rank = int(np.linalg.matrix_rank(x))
    pearson = float(np.sum(trials * (y - mu) ** 2 / (mu * (1 - mu))))
    df_resid = max(len(y) - rank, 1)
    return GlmFit(
        beta=beta,
        cov_unscaled=np.linalg.pinv(xtwx),
        dispersion=max(1.0, pearson / df_resid),
        n_obs=len(y),
        rank=rank,
    )


def _deviance(y: FloatArray, mu: FloatArray, n: FloatArray) -> float:
    with np.errstate(divide="ignore", invalid="ignore"):
        a = np.where(y > 0, y * np.log(y / mu), 0.0)
        b = np.where(y < 1, (1 - y) * np.log((1 - y) / (1 - mu)), 0.0)
    return float(2 * np.sum(n * (a + b)))


@dataclass(frozen=True)
class RateModel:
    flow: str
    metric: str
    design: Design
    fit: GlmFit
    days: tuple[date, ...]
    t: FloatArray
    num: FloatArray
    den: FloatArray
    dropped_num_gt_den: int

    @property
    def coef(self) -> dict[str, float]:
        return dict(zip(self.design.columns, (float(b) for b in self.fit.beta), strict=True))

    @property
    def se(self) -> dict[str, float]:
        return dict(zip(self.design.columns, (float(s) for s in self.fit.se), strict=True))


@dataclass(frozen=True)
class RateBand:
    flow: str
    metric: str
    raw_rate: float
    adjusted_rate: float
    forecast_mean: float
    band90_low: float
    band90_high: float
    band90_halfwidth_pct: float | None
    noise90_halfwidth_pct: float | None
    dispersion: float
    n_days: int
    window_days: int
    last_day: date
    horizon_days: int


def fit_rate(
    flow: str, metric: str, series: Series, origin: date | None = None
) -> RateModel | None:
    """The flow's model, or None below the data floor (the reference's "không đủ dữ liệu")."""
    ni, di = RATE_METRICS[metric]
    days_all = sorted(series)
    if not days_all:
        return None
    origin = origin or days_all[0]
    keep = [d for d in days_all if series[d][di] > 0 and series[d][ni] <= series[d][di]]
    dropped = sum(1 for d in days_all if series[d][di] > 0 and series[d][ni] > series[d][di])
    num = np.array([series[d][ni] for d in keep], dtype=float)
    den = np.array([series[d][di] for d in keep], dtype=float)
    if den.sum() < MIN_DEN or num.sum() < MIN_NUM:
        return None
    t = np.array([(d - origin).days for d in keep], dtype=float)
    design = make_design(keep, t)
    fit = fit_quasi_binomial(design.matrix(keep, t), num, den)
    return RateModel(
        flow=flow,
        metric=metric,
        design=design,
        fit=fit,
        days=tuple(keep),
        t=t,
        num=num,
        den=den,
        dropped_num_gt_den=dropped,
    )


def band(model: RateModel, window: int = 30, horizon: int = 14) -> RateBand:
    """Raw and calendar-adjusted rate over the last ``window`` days; 90 % band of a
    ``horizon``-day mean if nothing changes (trend held at its last value)."""
    t_max = float(model.t.max())
    last_mask = model.t > t_max - window
    last_days = [d for d, m in zip(model.days, last_mask, strict=True) if m]
    num, den = model.num[last_mask], model.den[last_mask]
    raw = float(num.sum() / den.sum())
    beta = model.fit.beta
    x_adj = model.design.matrix(last_days, model.t[last_mask], calendar=False)
    adj_rate = float(np.average(_expit(x_adj @ beta), weights=den))

    last_day = model.days[-1]
    future = [last_day + timedelta(i) for i in range(1, horizon + 1)]
    x_fut = model.design.matrix(future, np.full(horizon, t_max), calendar=False)
    eta = x_fut @ beta
    p = _expit(eta)
    se_eta = np.sqrt(np.clip(np.einsum("ij,jk,ik->i", x_fut, model.fit.cov, x_fut), 0.0, None))
    upper, lower = _expit(eta + Z95 * se_eta), _expit(eta - Z95 * se_eta)
    n = float(np.median(den))
    var_samp = model.fit.dispersion * float(np.sum(p * (1 - p) * n)) / (n * horizon) ** 2
    se_lin = float(np.mean(np.log(upper) - np.log(lower))) / (2 * Z95_LITERAL)
    mean_p = float(p.mean())
    sd = float(np.sqrt(var_samp + (mean_p * se_lin) ** 2))
    logit = np.log(mean_p / (1 - mean_p))
    lo, hi = (
        float(_expit(np.array(logit + z * sd / (mean_p * (1 - mean_p))))) for z in (-Z90, Z90)
    )
    return RateBand(
        flow=model.flow,
        metric=model.metric,
        raw_rate=raw,
        adjusted_rate=adj_rate,
        forecast_mean=mean_p,
        band90_low=lo,
        band90_high=hi,
        band90_halfwidth_pct=Z90 * sd / mean_p if mean_p else None,
        noise90_halfwidth_pct=Z90 * float(np.sqrt(var_samp)) / mean_p if mean_p else None,
        dispersion=model.fit.dispersion,
        n_days=len(model.days),
        window_days=int(last_mask.sum()),
        last_day=last_day,
        horizon_days=horizon,
    )
