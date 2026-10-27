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
6. **Pre-period rule by group size (D45.6 as amended by D47.1, fast track P36).**
   Large groups gain from a second pre-period window (research run
   ``20261015-212942`` §4a: 17 + 9 CTR SE −17 %). D45.6 also put small groups on the
   plain change (θ = 1), but the P36 v0.3 power check found that lowered their power
   (4 + 2 · 28 d at +40 %: 35 → 25 %), contradicting §4a, so D47.1 keeps step 3's
   fitted θ below 15 (to be re-checked on the first real D34 groups).
   :func:`adjust_changes`:

   - fewer than :data:`TWO_WINDOW_MIN_PRODUCTS` (15) measured products: step 3's
     single fitted ``θ`` -- the P31 rule (``method = one_window``);
   - from 15 products, when every product has its days −28..−15 (``Unit.pre``):
     ANCOVA on two pre-period windows, pooled over the group like step 3::

         (θ₁, θ₂) = OLS slopes of y on (x, z)   with x = ln(days −14..−1),
                                                     z = ln(days −28..−15)
         d_i = (y_i − x̄) − θ₁ (x_i − x̄) − θ₂ (z_i − z̄)

     (``method = two_windows``; ``θ₁`` clipped to [0, 2], ``θ₂`` to [−1, 1]);
   - from 15 products without the second window: step 3's single fitted ``θ``
     (``method = one_window``).

   The same rule runs inside the false-alarm replay (pool entries carry the
   earlier window when it is known: (days −42..−29, −28..−15, −14..−1) for the
   pre-period and (w − 1, w, w + 1) for a control's untouched windows), so the
   gate measures the rule that is applied. Applies to every group metric (CTR,
   CTOR, AOV, items per order).
7. **Empirical-Bayes shrunk lift, Ops only (D52, fast track P45).** A winner's-curse
   guard (Azevedo et al. 2019): the observed log-lift of a comparison is pulled toward
   what groups of the same lever type have shown. :func:`log_lift_of` reads it from the
   stored comparison -- ``y = ln(1 + diff / (100 + median_control))`` (exactly
   ``ln((100 + m_t) / (100 + m_c))``), and the 90 % interval of ``diff`` mapped through
   the same monotone map gives ``se = (y_hi − y_lo) / (2 × 1.645)``. Then::

       w     = τ² / (τ² + se²)
       shrunk = w · y + (1 − w) · μ
       var   = w · se² + (1 − w)² · var(μ)        (var(μ) = 0 for the default prior)

   and the 90 % interval ``shrunk ± 1.645 √var``, shown as % (``100 (e^x − 1)``).
   The prior (:func:`estimate_prior`) is per lever type (lever × metric × channel):
   with at least ``min_groups`` draws (one per shop: a shop's several groups are
   combined first by inverse variance; the group being shrunk is left out) μ and τ
   come from DerSimonian–Laird (:func:`dersimonian_laird`); otherwise the default
   N(0, 0.15²) on the log-lift (``DiagTunables.group_eb_prior_sd`` / ``group_eb_min_groups``).
   It never changes the label, the strength or the seller's sentence.
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
#: D45.6: the second pre-period window's slope is clipped to this range.
THETA_PRE_RANGE = (-1.0, 1.0)
#: D45.6 / D47.1 (P36): from this many measured products the change is adjusted on two
#: pre-period windows; below it the P31 fitted θ (one window). ``DiagTunables``
#: ``group_two_window_min`` overrides it per shop.
TWO_WINDOW_MIN_PRODUCTS = 15
ADJUST_CHANGE = "change"
ADJUST_ONE_WINDOW = "one_window"
ADJUST_TWO_WINDOWS = "two_windows"

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
    """One product's metric before (14 days) and after (14 days); both > 0.

    ``pre`` (D45.6): the 14 days before ``before`` (days −28..−15), when known and > 0.
    """

    arm: str
    before: float
    after: float
    pre: float | None = None

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


@dataclass(frozen=True)
class Adjustment:
    """The adjusted changes of a group (module docstring step 6)."""

    changes: list[float]
    method: str
    #: Slope on days −14..−1 (1 for the plain change).
    theta: float
    #: Slope on days −28..−15 (two windows only).
    theta_pre: float | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "theta": round(self.theta, 4),
            "theta_pre": None if self.theta_pre is None else round(self.theta_pre, 4),
        }


def _two_window_slopes(
    xs: Sequence[float], zs: Sequence[float], ys: Sequence[float]
) -> tuple[float, float] | None:
    """OLS slopes of ``y`` on ``(x, z)`` with an intercept; ``None`` when singular."""
    mx, mz, my = statistics.fmean(xs), statistics.fmean(zs), statistics.fmean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    szz = sum((z - mz) ** 2 for z in zs)
    sxz = sum((x - mx) * (z - mz) for x, z in zip(xs, zs, strict=True))
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    szy = sum((z - mz) * (y - my) for z, y in zip(zs, ys, strict=True))
    det = sxx * szz - sxz**2
    if det <= 1e-12 * max(sxx * szz, 1e-300) or sxx <= 1e-12 or szz <= 1e-12:
        return None
    return (szz * sxy - sxz * szy) / det, (sxx * szy - sxz * sxy) / det


def adjust_changes(
    units: Sequence[Unit], *, two_window_min: int | None = TWO_WINDOW_MIN_PRODUCTS
) -> Adjustment:
    """D45.6: each unit's adjusted change (points of %) by the group-size rule (step 6).

    ``two_window_min = None`` is the P31 rule (step 3's fitted ``θ`` at every size),
    kept for the power check's "before" column.
    """
    if not units:
        return Adjustment([], ADJUST_CHANGE, 1.0)
    if two_window_min is None:
        changes, theta = cuped_adjust(units)
        return Adjustment(changes, ADJUST_ONE_WINDOW, theta)
    if len(units) < two_window_min:  # D47.1: small groups keep the P31 θ
        changes, theta = cuped_adjust(units)
        return Adjustment(changes, ADJUST_ONE_WINDOW, theta)
    if all(u.pre is not None and u.pre > 0 for u in units):
        xs = [math.log(u.before) for u in units]
        zs = [math.log(u.pre) for u in units if u.pre is not None]
        ys = [math.log(u.after) for u in units]
        slopes = _two_window_slopes(xs, zs, ys)
        if slopes is not None:
            t1 = min(max(slopes[0], THETA_RANGE[0]), THETA_RANGE[1])
            t2 = min(max(slopes[1], THETA_PRE_RANGE[0]), THETA_PRE_RANGE[1])
            mx, mz = statistics.fmean(xs), statistics.fmean(zs)
            out = [
                (math.exp((y - mx) - t1 * (x - mx) - t2 * (z - mz)) - 1) * 100
                for x, z, y in zip(xs, zs, ys, strict=True)
            ]
            return Adjustment(out, ADJUST_TWO_WINDOWS, t1, t2)
    changes, theta = cuped_adjust(units)
    return Adjustment(changes, ADJUST_ONE_WINDOW, theta)


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


#: A no-effect pair (before, after), or a triple (pre, before, after) when the window
#: before "before" is known too (D45.6: the two-window rule needs it in the replay).
NullEntry = tuple[float, ...]


def _usable(entry: Sequence[float]) -> NullEntry | None:
    """``(b, a)`` or ``(p, b, a)``, every value > 0; a triple with a bad ``p`` keeps ``(b, a)``."""
    if len(entry) == 3:
        p, b, a = entry
        if b > 0 and a > 0:
            return (p, b, a) if p is not None and p > 0 else (b, a)
        return None
    b, a = entry[-2], entry[-1]
    return (b, a) if b > 0 and a > 0 else None


def null_pool(
    pre_pairs: Sequence[Sequence[float]],
    adjusted: Sequence[tuple[str, float]],
    control_pairs: Sequence[Sequence[float]] = (),
) -> tuple[list[NullEntry], str]:
    """No-effect (before, after) pairs (module docstring step 5), else the centred changes.

    ``pre_pairs``: per member (days −28..−15, days −14..−1), both > 0 -- or the triple
    (days −42..−29, −28..−15, −14..−1) when the earlier window is known (step 6).
    ``control_pairs``: the control members' consecutive untouched post-launch pairs
    (or triples with the window before).
    ``adjusted``: per product (arm, adjusted change %), the fallback.
    """
    pre = [e for e in (_usable(tuple(x)) for x in pre_pairs) if e is not None]
    post = [e for e in (_usable(tuple(x)) for x in control_pairs) if e is not None]
    if len(pre) + len(post) >= MIN_NULL_POOL:
        return [*pre, *post], (NULL_PRE_AND_CONTROL if post else NULL_PRE_PERIOD)
    out: list[NullEntry] = []
    for arm in (ARM_TREATED, ARM_CONTROL):
        logs = [math.log1p(c / 100) for a, c in adjusted if a == arm and c > -100]
        if not logs:
            continue
        centre = statistics.median(logs)
        out.extend((1.0, math.exp(v - centre)) for v in logs)
    return out, NULL_CENTRED


def false_alarm_rate(
    pool: Sequence[Sequence[float]],
    n_treated: int,
    n_control: int,
    *,
    seed: int,
    source: str,
    draws: int = FALSE_ALARM_DRAWS,
    two_window_min: int | None = TWO_WINDOW_MIN_PRODUCTS,
) -> FalseAlarm | None:
    """Share of ``draws`` no-effect replays in which the rule calls a change (step 4).

    Each replay adjusts with the same group-size rule as the verdict (step 6,
    :func:`adjust_changes`); a triple's first value is the unit's ``pre``.
    """
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
            Unit(
                ARM_CONTROL if i < n_control else ARM_TREATED,
                entry[-2],
                entry[-1],
                entry[0] if len(entry) == 3 else None,
            )
            for i, entry in enumerate(picks)
        ]
        adjusted = adjust_changes(units, two_window_min=two_window_min).changes
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


# --------------------------------------------------------------------------- EB lift (D52)

#: z of the two-sided 90 % interval (the interval the verdict reports).
Z90 = 1.6448536269514722
#: D52 default prior on the log-lift: N(0, 0.15²); ``DiagTunables`` overrides both.
EB_PRIOR_SD = 0.15
EB_MIN_GROUPS = 3
PRIOR_DEFAULT = "default"
PRIOR_POOLED = "pooled"
#: D76 / D11 (ADR-116 §3): the shop holds no open ``pooled_training`` grant, so its Ops
#: estimate uses only its own data -- the default prior's numbers, never other shops'.
PRIOR_OWN = "own"
#: D14 (owner, 2026-10-27): the pooled cell a prior came from -- the lever type itself
#: (lever × metric × channel), else the wider metric × channel over every lever.
CELL_LEVER_TYPE = "lever_type"
CELL_METRIC_CHANNEL = "metric_channel"
#: A comparison whose interval has no width carries no usable SE (computational floor).
_MIN_SE = 1e-6


@dataclass(frozen=True)
class LogLift:
    """One comparison's observed log-lift and its standard error (step 7)."""

    value: float
    se: float


def log_lift_of(comparison: Any) -> LogLift | None:
    """``y`` and ``se`` from a stored ``compare`` output; ``None`` without numbers."""
    if not isinstance(comparison, dict):
        return None
    diff = comparison.get("difference")
    med_c = comparison.get("median_control")
    interval = comparison.get("interval")
    if not (
        isinstance(diff, int | float)
        and isinstance(med_c, int | float)
        and isinstance(interval, list | tuple)
        and len(interval) == 2
        and all(isinstance(v, int | float) for v in interval)
    ):
        return None
    base = 100.0 + float(med_c)
    low, high = float(interval[0]), float(interval[1])
    if base <= 0 or base + diff <= 0 or base + low <= 0 or base + high <= 0:
        return None
    y = math.log1p(diff / base)
    y_lo, y_hi = math.log1p(low / base), math.log1p(high / base)
    se = (y_hi - y_lo) / (2 * Z90)
    if not se > _MIN_SE:
        return None
    return LogLift(y, se)


@dataclass(frozen=True)
class Prior:
    """The prior on a lever type's log-lift: N(mean, tau²), with var(mean)."""

    mean: float
    tau: float
    source: str
    #: Draws (shops) behind a pooled prior; 0 for the default.
    n_groups: int = 0
    mean_var: float = 0.0
    #: D14: the pooled cell (``CELL_*``); ``None`` for the default.
    cell: str | None = None

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "source": self.source,
            "mean": round(self.mean, 5),
            "tau": round(self.tau, 5),
            "n_groups": self.n_groups,
        }
        if self.cell is not None:
            out["cell"] = self.cell
        return out


def default_prior(sd: float = EB_PRIOR_SD) -> Prior:
    return Prior(0.0, sd, PRIOR_DEFAULT)


def own_data_prior(sd: float = EB_PRIOR_SD) -> Prior:
    """The prior of a shop that did not opt into pooling (D11): :func:`default_prior`'s
    N(0, sd²) -- no other shop's draw -- labelled so Ops says the estimate is its own."""
    return Prior(0.0, sd, PRIOR_OWN)


def combine_within_shop(draws: Sequence[LogLift]) -> LogLift:
    """A shop's groups as one draw: the inverse-variance mean and its SE."""
    weights = [1 / (d.se**2) for d in draws]
    total = sum(weights)
    value = sum(w * d.value for w, d in zip(weights, draws, strict=True)) / total
    return LogLift(value, math.sqrt(1 / total))


def dersimonian_laird(draws: Sequence[LogLift]) -> tuple[float, float, float]:
    """Random-effects ``(μ, τ, var μ)`` by DerSimonian–Laird (method of moments)."""
    weights = [1 / (d.se**2) for d in draws]
    total = sum(weights)
    fixed = sum(w * d.value for w, d in zip(weights, draws, strict=True)) / total
    q = sum(w * (d.value - fixed) ** 2 for w, d in zip(weights, draws, strict=True))
    c = total - sum(w**2 for w in weights) / total
    tau2 = max(0.0, (q - (len(draws) - 1)) / c) if c > 0 else 0.0
    re_weights = [1 / (d.se**2 + tau2) for d in draws]
    re_total = sum(re_weights)
    mean = sum(w * d.value for w, d in zip(re_weights, draws, strict=True)) / re_total
    return mean, math.sqrt(tau2), 1 / re_total


def estimate_prior(
    draws: Sequence[tuple[str, str, LogLift]],
    *,
    exclude_group: str | None = None,
    min_groups: int = EB_MIN_GROUPS,
    default_sd: float = EB_PRIOR_SD,
) -> Prior:
    """The lever type's prior from ``(shop, group, log-lift)`` draws (step 7).

    Leave-one-out: ``exclude_group`` is dropped; each shop's remaining groups are
    combined into one draw; with fewer than ``min_groups`` draws, the default prior.
    """
    by_shop: dict[str, list[LogLift]] = {}
    for shop, group, lift in draws:
        if group == exclude_group:
            continue
        by_shop.setdefault(shop, []).append(lift)
    if len(by_shop) < max(min_groups, 2):
        return default_prior(default_sd)
    shops = [combine_within_shop(v) for _, v in sorted(by_shop.items())]
    mean, tau, mean_var = dersimonian_laird(shops)
    return Prior(mean, tau, PRIOR_POOLED, len(shops), mean_var)


def _pct(x: float) -> float:
    return round((math.exp(x) - 1) * 100, 2)


def shrink_lift(lift: LogLift, prior: Prior) -> dict[str, Any]:
    """The EB block stored / shown next to a raw comparison (step 7)."""
    tau2, se2 = prior.tau**2, lift.se**2
    w = tau2 / (tau2 + se2) if tau2 + se2 > 0 else 0.0
    mean = w * lift.value + (1 - w) * prior.mean
    var = w * se2 + (1 - w) ** 2 * prior.mean_var
    half = Z90 * math.sqrt(max(var, 0.0))
    return {
        "observed_log_lift": round(lift.value, 5),
        "se": round(lift.se, 5),
        "observed_pct": _pct(lift.value),
        "weight": round(w, 4),
        "shrunk_log_lift": round(mean, 5),
        "shrunk_pct": _pct(mean),
        "interval_pct": [_pct(mean - half), _pct(mean + half)],
        "prior": prior.to_json(),
    }


__all__ = [
    "ADJUST_CHANGE",
    "ADJUST_ONE_WINDOW",
    "ADJUST_TWO_WINDOWS",
    "ALPHA",
    "EB_MIN_GROUPS",
    "EB_PRIOR_SD",
    "PRIOR_DEFAULT",
    "CELL_LEVER_TYPE",
    "CELL_METRIC_CHANNEL",
    "PRIOR_OWN",
    "PRIOR_POOLED",
    "Z90",
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
    "TWO_WINDOW_MIN_PRODUCTS",
    "Adjustment",
    "LogLift",
    "Prior",
    "Assessment",
    "FalseAlarm",
    "Permutation",
    "NullEntry",
    "Unit",
    "adjust_changes",
    "assess",
    "bootstrap_interval",
    "combine_within_shop",
    "default_prior",
    "dersimonian_laird",
    "estimate_prior",
    "log_lift_of",
    "own_data_prior",
    "cuped_adjust",
    "cuped_theta",
    "false_alarm_rate",
    "median_difference",
    "null_pool",
    "permutation_test",
    "quantile",
    "shrink_lift",
    "unit_from_change",
]
