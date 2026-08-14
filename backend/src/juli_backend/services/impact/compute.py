"""The ratio-form DiD formula steps — ADR-077 decision 2 (#1041).

Each function below is one formula step, independently unit-testable against
hand-computed values (acceptance criterion) rather than only the end-to-end
number:

    pre         = mean(target metric, T-14 … T-1)
    post        = mean(target metric, T+1 … T+7 or T+1 … T+14)
    growth      = mean(control metric, post window) ÷ mean(control metric, pre window)
    expected    = pre × growth
    incremental = post − expected
    impact_pct  = incremental ÷ expected           (suppressed for pre = 0 or expected ≤ 0)

All arithmetic is plain ``Decimal`` — no ``numpy``/``pandas``/``scipy``. Every
function is pure: same inputs in, same output out, in any process, forever.
None of them read a clock or perform I/O.

**Suppression, not exceptions.** ``pre = 0`` and ``expected ≤ 0`` are two
*different* inputs that both reach the same designed output state — the ``%``
form (``impact_pct``) is suppressed (returned as ``None``) rather than
raising ``ZeroDivisionError`` or a nonsensical value. They are kept as
distinct reasons (see ``PercentSuppressedReason``) precisely because they are
different inputs: ``pre = 0`` means the target metric itself was silent
before the run; ``expected ≤ 0`` can occur with ``pre`` strictly positive,
whenever the control cohort's growth ratio is non-positive (e.g. the control
metric went to zero in the post window). A third state, "insufficient data"
(a window with no recorded days at all, so ``pre``/``post``/``expected``
computed to ``None``), is also never an exception — every step here returns
``None`` on missing inputs and lets ``None`` propagate.

**No rate-vs-count threshold comparisons live here.** The only comparisons
in this module are ``control_pre == 0``, ``pre == 0``, and ``expected <= 0``
— all comparisons of a metric's own computed value against its own zero,
which is meaningful and unit-agnostic for a rate exactly as much as for a
count. Nothing here compares one metric's values against a threshold
calibrated for a *different* metric (that failure mode — a count-calibrated
volume floor compared against a rate metric's own ~0.01-0.30 values — lives
strictly in downstream, out-of-scope code; see
``metric_map.MetricSpec.is_rate`` for the seam that code must use).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from juli_backend.services.impact.windows import (
    WindowKind,
    mean_over_window,
    post_window,
    pre_window,
)

PercentSuppressedReason = Literal["pre_zero", "expected_non_positive", "insufficient_data"]


def compute_pre(daily: dict[date, Decimal | None], t: date) -> Decimal | None:
    """``mean(metric, T-14 … T-1)``, day T excluded (structurally, and again
    defensively inside ``mean_over_window``)."""
    start, end = pre_window(t)
    return mean_over_window(daily, start, end, exclude=t)


def compute_post(daily: dict[date, Decimal | None], t: date, kind: WindowKind) -> Decimal | None:
    """``mean(metric, T+1 … T+7)`` (preliminary) or ``T+1 … T+14`` (final),
    day T excluded."""
    start, end = post_window(t, kind)
    return mean_over_window(daily, start, end, exclude=t)


def compute_growth(control_pre: Decimal | None, control_post: Decimal | None) -> Decimal | None:
    """``mean(controls, post) ÷ mean(controls, pre)``.

    ``None`` (not an exception, not an arbitrary growth of 1) when either
    input is missing or ``control_pre`` is zero — a control cohort silent in
    its own pre-period gives no basis to project the target's counterfactual
    growth.
    """
    if control_pre is None or control_post is None or control_pre == 0:
        return None
    return control_post / control_pre


def compute_expected(pre: Decimal | None, growth: Decimal | None) -> Decimal | None:
    """``expected = pre × growth``."""
    if pre is None or growth is None:
        return None
    return pre * growth


def compute_incremental(post: Decimal | None, expected: Decimal | None) -> Decimal | None:
    """``incremental = post − expected``."""
    if post is None or expected is None:
        return None
    return post - expected


def compute_impact_pct(
    pre: Decimal | None,
    incremental: Decimal | None,
    expected: Decimal | None,
) -> tuple[Decimal | None, PercentSuppressedReason | None]:
    """``impact_pct = incremental ÷ expected`` — suppressed (``None``) for
    ``pre = 0`` or ``expected ≤ 0``, each reported as its own reason.

    Priority when both conditions hold (``pre = 0`` forces ``expected = pre ×
    growth = 0`` too, whenever ``growth`` is defined): ``"pre_zero"`` wins,
    because it is the more specific, upstream cause — ``expected`` being
    non-positive is then just a downstream consequence of it, not an
    independent trigger. ``"expected_non_positive"`` is reachable on its own
    with ``pre`` strictly positive, e.g. when the control cohort's growth
    ratio is zero or negative.
    """
    if pre is None or incremental is None or expected is None:
        return None, "insufficient_data"
    if pre == 0:
        return None, "pre_zero"
    if expected <= 0:
        return None, "expected_non_positive"
    return incremental / expected, None
