"""The stricter group verdict (D41.3, T3A; fast track P31). Pure.

D41's power simulation found the P30 verdict (80 % bootstrap interval of the
difference of medians) raises a false alarm on a 4 + 2 group 18 % of the time:
a bootstrap of a median over 2–5 products is far too optimistic. D41.3:

1. **90 % interval** (p5–p95 of the bootstrap) instead of 80 %.
2. **Permutation test when the control has fewer than 5 products.** The design
   is a random draw of which products are the control, so the exact test of "no
   effect" re-draws it: every way of choosing ``n_c`` controls among the
   ``n_t + n_c`` measured products (enumerated when there are at most
   :data:`PERMUTATION_EXACT_MAX`, else :data:`PERMUTATION_RANDOM` random draws),
   each giving median treated − median control. ``p`` = the share of draws at
   least as far from 0 as the observed one (two-sided). The change is "detected"
   only when ``p ≤`` :data:`ALPHA` (0.10) AND the bootstrap grade is not noise;
   the bootstrap grade (D31.7 against the 90 % interval's half-width) then gives
   "Thay đổi rõ" / "Có thể thay đổi". With ≥ 5 controls the bootstrap grade alone
   decides, as before.
3. **CUPED-style adjustment.** A product's after-period value is adjusted by
   what its own previous 14 days predict, on the log scale (so the result is
   still a % change): with ``x_i = ln(before_i)``, ``y_i = ln(after_i)``::

       θ    = Σ_i (x_i − x̄)(y_i − ȳ) / Σ_i (x_i − x̄)²      (all the group's products)
       d_i  = (y_i − x̄) − θ (x_i − x̄)
       adjusted change_i = 100 × (e^(d_i) − 1)   (points of %)

   ``θ`` pools the pre / post covariance across all the group's products, both
   arms (the assignment is random, so ``x`` is independent of the arm). One θ
   for every product, whatever its arm, keeps the adjustment the same under any
   re-drawn assignment, so the permutation test stays exact. ``θ = 1`` is exactly the
   unadjusted change ``after / before − 1``; ``θ < 1`` means a product's
   before-level only partly carries over, i.e. part of a low (or high) before
   value was noise that regresses back -- the adjustment removes that part
   instead of crediting it to the lever. ``θ`` is clipped to [0, 2] and is 1
   when the group has fewer than 3 products or no spread in ``x``.
4. **The group's own false-alarm rate.** :func:`false_alarm_rate` replays the
   whole rule (CUPED, interval, permutation) :data:`FALSE_ALARM_DRAWS` (500)
   times on data with no effect, seeded by the group's seed: each draw takes
   ``n_t + n_c`` (before, after) pairs from the group's null pool (a random
   permutation of the pool; with replacement only when the pool is smaller),
   re-draws the arms the way the group was drawn, and counts a false alarm when
   the rule calls a change. A verdict whose rate is above
   :data:`FALSE_ALARM_MAX` (15 %, T3.1) makes no strength claim and reads
   "Đang đo".
5. **The null pool (T3.1)** holds only pairs of two consecutive 14-day windows
   in which no lever ran, so the effect is zero by construction:

   - every member's **pre-period pair**: days −28..−15 against −14..−1 before
     launch;
   - every control member's **post-launch pairs**: the control is untouched
     until the seller approves its released card, so each consecutive pair of
     14-day windows from day −14 that ends on or before its last untouched
     day (−14..−1 vs 0..13 at day 14; + 0..13 vs 14..27 from day 28; …) is
     added. The pool grows as data accrues, and a group in "Đang đo" is
     re-gated at every measurement (day 14, 21, 28, …), so it can leave it.

   Each window needs ≥ 7 days with data. With fewer than 3 usable pairs, the
   pool is the group's own adjusted changes with each arm's median removed.
"""

from __future__ import annotations

import itertools
import math
import random
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from juli_backend.services.change_strength import STRENGTH_NOISE, change_strength

#: The test's level, and the interval it matches (90 %, two-sided).
ALPHA = 0.10
INTERVAL_LOW, INTERVAL_HIGH = ALPHA / 2, 1 - ALPHA / 2
#: Fewer controls than this: the permutation test decides "detected".
PERMUTATION_BELOW_CONTROL = 5
PERMUTATION_EXACT_MAX = 20_000
PERMUTATION_RANDOM = 10_000
#: The false-alarm simulation (cheap, in-process).
FALSE_ALARM_DRAWS = 500
#: T3.1 (owner, after the v0.3 power check of P31, 2026-10-13): above this simulated
#: false-alarm rate the verdict reads "Đang đo". At 17 + 9 products × 28 days a gate at
#: 10 % (+ a 1.7-point Monte-Carlo margin, ≈ 11.7 %) sent 27 % of groups to "Đang đo"
#: for good; at 15 % only 12 %, while the rule's real false-alarm rate stayed ≤ 9.6 %
#: in every design checked (4+2, 5+3, 5+5, 4+6, 17+9; 14 and 28 days). Flat, no margin.
FALSE_ALARM_MAX = 0.15
SIM_BOOTSTRAP = 200
SIM_PERMUTATION_EXACT_MAX = 500
SIM_PERMUTATION_RANDOM = 200
#: Fewer usable pre-period pairs than this: the null pool is the centred changes.
MIN_NULL_POOL = 3
THETA_RANGE = (0.0, 2.0)

NULL_PRE_PERIOD = "pre_period"
NULL_CENTRED = "centred_changes"
#: Pre-period pairs plus the control arm's post-launch pairs (T3.1).
NULL_PRE_AND_CONTROL = "pre_period+control_after"
TEST_PERMUTATION = "permutation"
TEST_BOOTSTRAP = "bootstrap"

ARM_TREATED = "treated"
ARM_CONTROL = "control"


def quantile(values: Sequence[float], q: float) -> float:
    """Linear-interpolated quantile (``q`` in [0, 1])."""
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = q * (len(ordered) - 1)
    low = int(pos)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (pos - low)


def median_difference(treated: Sequence[float], control: Sequence[float]) -> float:
    return statistics.median(treated) - statistics.median(control)


# --------------------------------------------------------------------------- CUPED


@dataclass(frozen=True)
class Unit:
    """One product's metric before (14 days) and after (14 days); both > 0."""

    arm: str
    before: float
    after: float

    @property
    def change_pct(self) -> float:
        return (self.after / self.before - 1) * 100


def unit_from_change(arm: str, change_pct: float) -> Unit | None:
    """A unit carrying only a change (before = 1): CUPED leaves it unadjusted."""
    after = 1 + change_pct / 100
    return Unit(arm, 1.0, after) if after > 0 else None


def cuped_theta(units: Sequence[Unit]) -> float:
    """``θ`` from the pooled covariance of ``ln before`` and ``ln after`` over the group."""
    if len(units) < 3:
        return 1.0
    xs = [math.log(u.before) for u in units]
    ys = [math.log(u.after) for u in units]
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    var = sum((x - mx) ** 2 for x in xs)
    if var <= 1e-12:
        return 1.0
    low, high = THETA_RANGE
    return min(max(cov / var, low), high)


def cuped_adjust(units: Sequence[Unit]) -> tuple[list[float], float]:
    """Each unit's adjusted change (points of %, module docstring step 3), and ``θ``."""
    if not units:
        return [], 1.0
    theta = cuped_theta(units)
    x_bar = statistics.fmean(math.log(u.before) for u in units)
    out = []
    for u in units:
        d = (math.log(u.after) - x_bar) - theta * (math.log(u.before) - x_bar)
        out.append((math.exp(d) - 1) * 100)
    return out, theta


# --------------------------------------------------------------------------- tests


@dataclass(frozen=True)
class Permutation:
    p_value: float
    draws: int
    exact: bool

    def to_json(self) -> dict[str, Any]:
        return {"p_value": round(self.p_value, 4), "draws": self.draws, "exact": self.exact}


def permutation_test(
    treated: Sequence[float],
    control: Sequence[float],
    *,
    rng: random.Random,
    exact_max: int = PERMUTATION_EXACT_MAX,
    random_draws: int = PERMUTATION_RANDOM,
) -> Permutation:
    """Two-sided permutation test of median treated − median control over the assignment.

    Exact (every choice of ``len(control)`` controls among all products, the observed
    one included) when there are at most ``exact_max`` choices; else ``random_draws``
    random re-assignments, ``p = (1 + hits) / (1 + draws)``.
    """
    values = [*treated, *control]
    n, n_c = len(values), len(control)
    observed = abs(median_difference(treated, control)) - 1e-9
    total = math.comb(n, n_c)
    if total <= exact_max:
        hits = 0
        indices = range(n)
        for chosen in itertools.combinations(indices, n_c):
            picked = set(chosen)
            c = [values[i] for i in chosen]
            t = [values[i] for i in indices if i not in picked]
            if abs(median_difference(t, c)) >= observed:
                hits += 1
        return Permutation(hits / total, total, True)
    hits = 0
    pool = list(values)
    for _ in range(random_draws):
        rng.shuffle(pool)
        if abs(median_difference(pool[n_c:], pool[:n_c])) >= observed:
            hits += 1
    return Permutation((1 + hits) / (1 + random_draws), random_draws, False)


def bootstrap_interval(
    treated: Sequence[float], control: Sequence[float], *, rng: random.Random, samples: int
) -> tuple[float, float]:
    """The 90 % (p5–p95) bootstrap interval of median treated − median control."""
    n_t, n_c = len(treated), len(control)
    boots = [
        statistics.median(rng.choices(treated, k=n_t))
        - statistics.median(rng.choices(control, k=n_c))
        for _ in range(samples)
    ]
    return quantile(boots, INTERVAL_LOW), quantile(boots, INTERVAL_HIGH)


@dataclass(frozen=True)
class Assessment:
    """The rule's call on one treated / control comparison (module docstring 1–2)."""

    difference: float
    interval: tuple[float, float]
    #: D31.7 grade of the difference against the interval's half-width.
    grade: str | None
    #: The claimed strength: the grade when detected, else ``noise``.
    strength: str | None
    test: str
    permutation: Permutation | None

    @property
    def detected(self) -> bool:
        return self.strength is not None and self.strength != STRENGTH_NOISE


def assess(
    treated: Sequence[float],
    control: Sequence[float],
    *,
    rng: random.Random,
    samples: int,
    exact_max: int = PERMUTATION_EXACT_MAX,
    random_draws: int = PERMUTATION_RANDOM,
) -> Assessment:
    diff = median_difference(treated, control)
    low, high = bootstrap_interval(treated, control, rng=rng, samples=samples)
    grade = change_strength(diff, (high - low) / 2, 0.0)
    if len(control) < PERMUTATION_BELOW_CONTROL:
        perm = permutation_test(
            treated, control, rng=rng, exact_max=exact_max, random_draws=random_draws
        )
        detected = perm.p_value <= ALPHA + 1e-12 and grade not in (None, STRENGTH_NOISE)
        strength = grade if detected else (None if grade is None else STRENGTH_NOISE)
        return Assessment(diff, (low, high), grade, strength, TEST_PERMUTATION, perm)
    return Assessment(diff, (low, high), grade, grade, TEST_BOOTSTRAP, None)


# --------------------------------------------------------------------------- false alarm


@dataclass(frozen=True)
class FalseAlarm:
    """The rule's simulated false-alarm rate on this group's own no-effect data."""

    rate: float
    draws: int
    source: str
    pool: int

    @property
    def acceptable(self) -> bool:
        """Not above :data:`FALSE_ALARM_MAX` (15 %)."""
        return self.rate <= FALSE_ALARM_MAX + 1e-12

    def to_json(self) -> dict[str, Any]:
        return {
            "rate": round(self.rate, 4),
            "max": FALSE_ALARM_MAX,
            "acceptable": self.acceptable,
            "draws": self.draws,
            "source": self.source,
            "pool": self.pool,
        }


def null_pool(
    pre_pairs: Sequence[tuple[float, float]],
    adjusted: Sequence[tuple[str, float]],
    control_pairs: Sequence[tuple[float, float]] = (),
) -> tuple[list[tuple[float, float]], str]:
    """No-effect (before, after) pairs (module docstring step 5), else the centred changes.

    ``pre_pairs``: per member (days −28..−15, days −14..−1), both > 0.
    ``control_pairs``: the control members' consecutive untouched post-launch pairs.
    ``adjusted``: per product (arm, adjusted change %), the fallback.
    """
    pre = [(b, a) for b, a in pre_pairs if b > 0 and a > 0]
    post = [(b, a) for b, a in control_pairs if b > 0 and a > 0]
    if len(pre) + len(post) >= MIN_NULL_POOL:
        return [*pre, *post], (NULL_PRE_AND_CONTROL if post else NULL_PRE_PERIOD)
    out: list[tuple[float, float]] = []
    for arm in (ARM_TREATED, ARM_CONTROL):
        logs = [math.log1p(c / 100) for a, c in adjusted if a == arm and c > -100]
        if not logs:
            continue
        centre = statistics.median(logs)
        out.extend((1.0, math.exp(v - centre)) for v in logs)
    return out, NULL_CENTRED


def false_alarm_rate(
    pool: Sequence[tuple[float, float]],
    n_treated: int,
    n_control: int,
    *,
    seed: int,
    source: str,
    draws: int = FALSE_ALARM_DRAWS,
) -> FalseAlarm | None:
    """Share of ``draws`` no-effect replays in which the rule calls a change (step 4)."""
    if not pool or n_treated < 1 or n_control < 1:
        return None
    rng = random.Random(f"false-alarm:{seed}")
    n = n_treated + n_control
    hits = 0
    for _ in range(draws):
        if len(pool) >= n:
            picks = rng.sample(pool, n)  # permute the group's own null data
        else:
            picks = [rng.choice(pool) for _ in range(n)]  # too few: bootstrap it
        units = [
            Unit(ARM_CONTROL if i < n_control else ARM_TREATED, b, a)
            for i, (b, a) in enumerate(picks)
        ]
        adjusted, _theta = cuped_adjust(units)
        control = adjusted[:n_control]
        treated = adjusted[n_control:]
        call = assess(
            treated,
            control,
            rng=rng,
            samples=SIM_BOOTSTRAP,
            exact_max=SIM_PERMUTATION_EXACT_MAX,
            random_draws=SIM_PERMUTATION_RANDOM,
        )
        if call.detected:
            hits += 1
    return FalseAlarm(hits / draws, draws, source, len(pool))


__all__ = [
    "ALPHA",
    "FALSE_ALARM_DRAWS",
    "FALSE_ALARM_MAX",
    "INTERVAL_HIGH",
    "INTERVAL_LOW",
    "NULL_CENTRED",
    "NULL_PRE_AND_CONTROL",
    "NULL_PRE_PERIOD",
    "PERMUTATION_BELOW_CONTROL",
    "TEST_BOOTSTRAP",
    "TEST_PERMUTATION",
    "Assessment",
    "FalseAlarm",
    "Permutation",
    "Unit",
    "assess",
    "bootstrap_interval",
    "cuped_adjust",
    "cuped_theta",
    "false_alarm_rate",
    "median_difference",
    "null_pool",
    "permutation_test",
    "quantile",
    "unit_from_change",
]
