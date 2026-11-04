"""The learning loop (ADR-121 d.4-d.6), pure math over observations and events.

- **Calibration** per (change_kind, metric): each observation is measured / predicted-mid with
  the variance of the measurement; inverse-variance pooled within the shop; the factor the
  prediction uses is shrunk to the prior (``prediction.factor_from``: ``MIN_SHOP_RESULTS`` = 5,
  ``K`` = 5). ORY learns from ORY only -- there is no pooled state.
- **Coverage**: the share of results inside the predicted P10-P90; below 70 % the range widens,
  above 95 % it narrows (``range_scale``).
- **Bundles**: stacked / mega_sale changes are measured as one bundle and excluded from the
  per-kind calibration (their observation is kept, flagged).
- **Acceptance statistics** from approved / dismissed / expired / whatif_adjusted events feed
  slider defaults and the ranking tie-break -- never an effect estimate (this module has no
  import path into ``prediction``'s lift).
- **Executed-change days**: the days a verified change was running, for the flow baseline to
  leave out.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from statistics import median
from typing import Any

from juli_backend.services.shopee_recommendations import config

MIN_VARIANCE = 1e-6


@dataclass(frozen=True)
class Observation:
    """One scored prediction: a card's final reading, or a natural experiment."""

    change_kind: str
    metric: str
    predicted_low: float
    predicted_high: float
    measured: float  # relative effect (0.08 = +8 %)
    se: float | None = None  # standard error of ``measured`` (relative); None = equal weight
    source: str = "card"  # card | natural
    bundle: bool = False
    ref: str = ""  # card id / event key (never a product name)
    #: False = read without a control series (plain pre / post, tier Thấp): kept and counted,
    #: but it feeds neither the factor nor the coverage (a confounded reading must not move a range)
    controlled: bool = True
    #: ``engine`` or ``manual`` (P91 D-3): manual cards are calibrated and reported apart
    origin: str = "engine"
    #: weight in the pooled ratio: 1 for a clean single-card reading, ``MULTI_CARD_WEIGHT``
    #: (0.25) for a card that was one of several in a change set (P91 D-7)
    weight: float = 1.0

    @property
    def predicted_mid(self) -> float:
        return (self.predicted_low + self.predicted_high) / 2

    @property
    def in_range(self) -> bool:
        lo, hi = sorted((self.predicted_low, self.predicted_high))
        return lo <= self.measured <= hi

    def ratio_and_variance(self) -> tuple[float, float] | None:
        m = self.predicted_mid
        if m == 0:
            return None
        ratio = self.measured / m
        var = 1.0 if self.se is None else max((self.se / abs(m)) ** 2, MIN_VARIANCE)
        return ratio, var / max(self.weight, MIN_VARIANCE)  # a lighter sample = a larger variance

    def json(self) -> dict[str, Any]:
        return {
            "change_kind": self.change_kind,
            "metric": self.metric,
            "predicted_low": self.predicted_low,
            "predicted_high": self.predicted_high,
            "measured": self.measured,
            "se": self.se,
            "source": self.source,
            "bundle": self.bundle,
            "ref": self.ref,
            "controlled": self.controlled,
            "origin": self.origin,
            "weight": self.weight,
        }

    @classmethod
    def from_json(cls, d: Mapping[str, Any]) -> Observation:
        return cls(
            d["change_kind"],
            d["metric"],
            float(d["predicted_low"]),
            float(d["predicted_high"]),
            float(d["measured"]),
            None if d.get("se") is None else float(d["se"]),
            d.get("source", "card"),
            bool(d.get("bundle")),
            d.get("ref", ""),
            bool(d.get("controlled", True)),
            str(d.get("origin") or "engine"),
            float(d.get("weight", 1.0)),
        )


@dataclass(frozen=True)
class CalibrationState:
    change_kind: str
    metric: str
    n_results: int = 0
    pooled_ratio: float | None = None
    coverage_n: int = 0
    coverage_hits: int = 0
    range_scale: float = 1.0
    n_bundle_excluded: int = 0
    sources: Mapping[str, int] = field(default_factory=dict)

    @property
    def coverage(self) -> float | None:
        return None if self.coverage_n == 0 else self.coverage_hits / self.coverage_n


def pool_ratios(pairs: Iterable[tuple[float, float]]) -> float | None:
    """Inverse-variance pooled mean of (ratio, variance) pairs."""
    num = den = 0.0
    for r, v in pairs:
        w = 1.0 / max(v, MIN_VARIANCE)
        num += w * r
        den += w
    return None if den == 0 else num / den


def range_scale_for(hits: int, n: int) -> float:
    """Widen a P10-P90 range that holds too few results, narrow one that holds nearly all."""
    if n < config.COVERAGE_MIN_RESULTS:
        return 1.0
    cov = hits / n
    if cov < config.COVERAGE_WIDEN_BELOW:
        return min(config.RANGE_SCALE_MAX, config.COVERAGE_TARGET / max(cov, 0.2))
    if cov > config.COVERAGE_NARROW_ABOVE:
        return config.RANGE_SCALE_MIN
    return 1.0


def calibrate(
    observations: Sequence[Observation], origin: str | None = "engine"
) -> dict[tuple[str, str], CalibrationState]:
    """One state per (change_kind, metric) among the observations of one ``origin`` (default the
    engine's own cards; ``None`` = all). Bundle observations are counted, not pooled. A
    weighted observation (a card that was one of several in a change set) counts as its weight
    in ``n_results`` and in the pooled ratio."""
    groups: dict[tuple[str, str], list[Observation]] = defaultdict(list)
    for o in observations:
        if origin is None or o.origin == origin:
            groups[(o.change_kind, o.metric)].append(o)
    out: dict[tuple[str, str], CalibrationState] = {}
    for key, obs in groups.items():
        usable = [o for o in obs if not o.bundle and o.controlled]
        pairs = [rv for o in usable if (rv := o.ratio_and_variance()) is not None]
        hits = sum(1 for o in usable if o.in_range)
        out[key] = CalibrationState(
            change_kind=key[0],
            metric=key[1],
            n_results=int(sum(o.weight for o in usable if o.ratio_and_variance() is not None)),
            pooled_ratio=pool_ratios(pairs),
            coverage_n=len(usable),
            coverage_hits=hits,
            range_scale=range_scale_for(hits, len(usable)),
            n_bundle_excluded=sum(1 for o in obs if o.bundle),
            sources={
                **Counter(o.source for o in usable),
                **(
                    {"uncontrolled": n}
                    if (n := sum(1 for o in obs if not o.bundle and not o.controlled))
                    else {}
                ),
            },
        )
    return out


def calibrate_all(observations: Sequence[Observation]) -> dict[tuple[str, str], CalibrationState]:
    """The shop's stored calibration: the engine's states, plus an empty state for a
    (change_kind, metric) only manual cards have observations for (so their observations are
    kept; they never move the engine's factor)."""
    states = calibrate(observations, "engine")
    for key in calibrate(observations, None):
        states.setdefault(key, CalibrationState(key[0], key[1]))
    return states


def coverage_report(states: Mapping[tuple[str, str], CalibrationState]) -> list[dict[str, Any]]:
    return [
        {
            "change_kind": s.change_kind,
            "metric": s.metric,
            "results": s.n_results,
            "coverage_n": s.coverage_n,
            "coverage_hits": s.coverage_hits,
            "coverage": None if s.coverage is None else round(s.coverage, 3),
            "range_scale": round(s.range_scale, 3),
            "pooled_ratio": None if s.pooled_ratio is None else round(s.pooled_ratio, 3),
            "bundle_excluded": s.n_bundle_excluded,
            "sources": dict(s.sources),
        }
        for s in sorted(states.values(), key=lambda s: (s.change_kind, s.metric))
    ]


# --------------------------------------------------------------------------- acceptance


@dataclass
class AcceptanceStats:
    """Decisions per change kind. Feeds slider defaults and the ranking tie-break only."""

    approved: Counter[str] = field(default_factory=Counter)
    dismissed: Counter[str] = field(default_factory=Counter)
    expired: Counter[str] = field(default_factory=Counter)
    adjusted: Counter[str] = field(default_factory=Counter)
    reasons: dict[str, Counter[str]] = field(default_factory=lambda: defaultdict(Counter))
    #: kind -> slider key -> final/default ratios of approved cards
    ratios: dict[str, dict[str, list[float]]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(list))
    )

    def decided(self, kind: str) -> int:
        return self.approved[kind] + self.dismissed[kind] + self.expired[kind]

    def rate(self, kind: str) -> float | None:
        """Smoothed approval rate; None before any decision."""
        n = self.decided(kind)
        if n == 0:
            return None
        a, b = config.ACCEPTANCE_PRIOR
        return (self.approved[kind] + a) / (n + b)

    def default_for(
        self, kind: str, key: str, base: float, minimum: float, maximum: float
    ) -> float:
        """The slider default the generator proposed, moved toward what approved cards ended
        with (median final/default ratio, at least 3 approved adjustments, within +-30 %)."""
        r = self.ratios.get(kind, {}).get(key, [])
        if len(r) < 3:
            return base
        moved = base * min(max(median(r), 0.7), 1.3)
        return min(max(moved, minimum), maximum)

    def json(self) -> dict[str, Any]:
        kinds = sorted({*self.approved, *self.dismissed, *self.expired, *self.adjusted})
        return {
            k: {
                "approved": self.approved[k],
                "dismissed": self.dismissed[k],
                "expired": self.expired[k],
                "whatif_adjusted": self.adjusted[k],
                "rate": self.rate(k),
                "dismiss_reasons": dict(self.reasons.get(k, {})),
            }
            for k in kinds
        }


def origin_of(payload: Mapping[str, Any]) -> str:
    return str(payload.get("origin") or "engine")


def acceptance_by_origin(events: Iterable[Mapping[str, Any]]) -> dict[str, AcceptanceStats]:
    """``{"engine": stats, "manual": stats}``: the decisions split by who made the card."""
    rows = list(events)
    return {o: acceptance_from_events(rows, o) for o in ("engine", "manual")}


def acceptance_from_events(
    events: Iterable[Mapping[str, Any]], origin: str | None = "engine"
) -> AcceptanceStats:
    """``events``: dicts with ``event_type``, ``reason_code`` and the card event ``payload``
    (``change_kind`` is on the event payload of every event this package writes). Only events of
    cards made by ``origin`` count (default the engine's: a manual card never moves the defaults
    or the ranking tie-break the engine's cards use); ``None`` = every origin."""
    stats = AcceptanceStats()
    for e in events:
        payload = e.get("payload") or {}
        if origin is not None and origin_of(payload) != origin:
            continue
        kind = payload.get("change_kind")
        if not kind:
            continue
        et = e.get("event_type")
        if et == "accepted":
            stats.approved[kind] += 1
            for key, ratio in (payload.get("final_vs_default") or {}).items():
                stats.ratios[kind][key].append(float(ratio))
        elif et == "dismissed":
            stats.dismissed[kind] += 1
            stats.reasons[kind][e.get("reason_code") or "unspecified"] += 1
        elif et == "expired":
            stats.expired[kind] += 1
        elif et == "whatif_adjusted":
            stats.adjusted[kind] += 1
    return stats


# ------------------------------------------------------------------ executed-change days


def executed_change_days(
    changes: Iterable[tuple[datetime, int]], first: date, last: date
) -> frozenset[date]:
    """Days a verified change was running: ``(verified_at, planned_days)`` -> the day itself
    and the plan's days after it, within ``[first, last]``. The flow baseline leaves these
    out so it does not learn an executed change as the shop's normal."""
    out: set[date] = set()
    for at, days in changes:
        start = at.date()
        for i in range(max(days, 1) + 1):
            d = start + timedelta(days=i)
            if first <= d <= last:
                out.add(d)
    return frozenset(out)
