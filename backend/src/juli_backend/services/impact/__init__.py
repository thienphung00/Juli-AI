"""Incremental impact measurement — funnel-first metric map, ratio-form DiD
compute, control-pool selection, and confidence tiers / seller-facing copy
(ADR-077 decisions 1-4; #1041, #1042, #1043).

This package answers four questions: **which metric** does a mutation act
on (``metric_map.py``), **which sibling products form its control cohort**
(``control_pool.py``), **what is the control-adjusted incremental impact**
for that metric given a target series, a control series, and the write's
execution date T (``windows.py`` + ``compute.py`` + ``reading.py``), and
**how confident is that number, and what does a seller actually read**
(``confidence.py`` + ``copy.py``). Everything else ADR-077 describes is
explicitly out of scope here and owned by later, stacked issues in the same
package:

compute, and control-pool selection (ADR-077 decisions 1, 2 and 3; #1041,
#1042).

This package answers three questions: **which metric** does a mutation act
on (``metric_map.py``), **which sibling products form its control cohort**
(``control_pool.py``), and **what is the control-adjusted incremental
impact** for that metric given a target series, a control series, and the
write's execution date T (``windows.py`` + ``compute.py`` + ``reading.py``).
Everything else ADR-077 describes is explicitly out of scope here and owned
by later, stacked issues in the same package:
compute, control-pool selection, and confidence tiers / seller-facing copy
(ADR-077 decisions 1-4; #1041, #1042, #1043).

This package answers four questions: **which metric** does a mutation act
on (``metric_map.py``), **which sibling products form its control cohort**
(``control_pool.py``), **what is the control-adjusted incremental impact**
for that metric given a target series, a control series, and the write's
execution date T (``windows.py`` + ``compute.py`` + ``reading.py``), and
**how confident is that number, and what does a seller actually read**
(``confidence.py`` + ``copy.py``). Everything else ADR-077 describes is
explicitly out of scope here and owned by later, stacked issues in the same
package:

- Control-pool **candidate discovery I/O** — querying same-shop siblings,
  detecting a Juli-run touch, and resolving a product's first-active date —
  is not performed here; ``control_pool.select_control_pool`` receives an
  already-fetched ``Sequence[ControlCandidate]`` and the volume-floor value
  as plain arguments, mirroring how ``reading.py`` receives
  ``confounded: bool``.
- **Confidence tiers**, per-metric volume-floor *config* (the numeric
  thresholds themselves), and the seller-facing copy layer arrive with #1043.
- The **daily impact-reader beat task**, legacy-envelope compatibility, and
  ``WORKFLOW_OUTCOME_SUCCESS_CRITERIA`` wiring — ADR-077 decision 5, #1044.
  Detecting a confounding second run (a `tool_executions` query) and
  building ``RawDailyRecord`` series from ``AnalyticsPerformanceInterval``
  rows (a DB read) are both I/O and belong there; this package receives the
  already-resolved `confounded: bool` and already-built daily series as
  plain arguments.

**The formula (ADR-077 decision 2), ratio-form DiD:**

    pre         = mean(metric, T-14 … T-1)
    post        = mean(metric, T+1 … T+7)   ("preliminary")
                = mean(metric, T+1 … T+14)  ("final")
    growth      = mean(control metric, post window) ÷ mean(control metric, pre window)
    expected    = pre × growth
    incremental = post − expected
    impact_pct  = incremental ÷ expected

**Rules, all implemented here:**

- Day **T is excluded everywhere** — from `pre`, from `post`, and from the
  control windows (the control series is read over the *same* window
  boundaries as the target series). See ``windows.mean_over_window``'s
  ``exclude`` parameter.
- A second Juli run on the same product inside either window marks the
  reading ``confounded`` — the caller decides this (it requires a DB query)
  and passes ``confounded=True`` in; every numeric field on the resulting
  reading is then ``None``.
- **Rate metrics use the arithmetic mean of daily values in v1** (``ctr``,
  ``conversion_rate``, and the derived ``gmv_per_order``) — not a pooled
  rate (sum of numerators ÷ sum of denominators). This is a documented,
  deliberate approximation: raw daily click/visit counts behind
  ``ctr``/``conversion_rate`` are not stored, only the pre-computed ratio
  column is, so a pooled rate is not computable from the data this package
  can read. The pooled-rate upgrade is named future work, not a silent
  approximation — see ``metric_map.MetricSpec.is_rate``.
- ``pre = 0`` and ``expected ≤ 0`` are two *different* inputs that both
  suppress the ``%`` form (``impact_pct``) without raising — see
  ``compute.compute_impact_pct`` and its ``PercentSuppressedReason``.

**Purity.** No function in this package performs network I/O, calls a model,
touches the filesystem, or reads the wall clock (no ``date.today()`` /
``datetime.now()`` anywhere in this package). Every function's output is a
deterministic function of its arguments — the same fixture in produces the
same reading out, in any process, forever.
"""

from __future__ import annotations

from juli_backend.services.impact.compute import (
    PercentSuppressedReason,
    compute_expected,
    compute_growth,
    compute_impact_pct,
    compute_incremental,
    compute_post,
    compute_pre,
)
from juli_backend.services.impact.confidence import (
    BAND_MULTIPLIER_CAO,
    BAND_MULTIPLIER_TRUNG_BINH,
    FLOOR_MULTIPLIER_CAO,
    VOLUME_FLOORS,
    ConfidenceResult,
    MetricFamily,
    TierOutcome,
    assign_confidence,
    compute_confidence,
    compute_noise_band,
    metric_family_of,
    pre_period_volume,
    volume_floor_for,
)
from juli_backend.services.impact.control_pool import (
    MIN_ACTIVE_DAYS,
    MIN_CANDIDATES,
    MIN_MEAN_CORRELATION,
    TOP_K,
    ControlCandidate,
    ControlPoolResult,
    FallbackReason,
    SelectedControl,
    select_control_pool,
)
from juli_backend.services.impact.copy import (
    BELOW_FLOOR_MESSAGE,
    METHOD_DISCLAIMER_FALLBACK,
    METHOD_DISCLAIMER_FULL_PATH,
    RenderedReadingCopy,
    metric_label_vi,
    render_below_floor,
    render_confounded,
    render_reading,
    render_suppressed,
    render_tiered_reading,
)
from juli_backend.services.impact.metric_map import (
    ALL_METRICS,
    CONVERSION_RATE,
    CTR,
    GMV,
    GMV_PER_ORDER,
    IMPRESSIONS,
    ITEMS_SOLD,
    METRIC_MAP,
    SKU_ORDERS,
    MetricSpec,
    MutationKind,
    MutationMetrics,
    RawDailyRecord,
    resolve_metric,
)
from juli_backend.services.impact.reading import (
    MetricReading,
    MutationReadings,
    ReadingStatus,
    RunReadings,
    compute_metric_reading,
    compute_mutation_readings,
    compute_run_readings,
)
from juli_backend.services.impact.windows import (
    POST_WINDOW_DAYS,
    PRE_WINDOW_DAYS,
    WindowKind,
    Windows,
    compute_windows,
    date_range,
    mean_over_window,
    post_window,
    pre_window,
)

__all__ = [
    "ALL_METRICS",
    "BAND_MULTIPLIER_CAO",
    "BAND_MULTIPLIER_TRUNG_BINH",
    "BELOW_FLOOR_MESSAGE",
    "CONVERSION_RATE",
    "CTR",
    "ConfidenceResult",
    "ControlCandidate",
    "ControlPoolResult",
    "FLOOR_MULTIPLIER_CAO",
    "FallbackReason",
    "GMV",
    "GMV_PER_ORDER",
    "IMPRESSIONS",
    "ITEMS_SOLD",
    "METHOD_DISCLAIMER_FALLBACK",
    "METHOD_DISCLAIMER_FULL_PATH",
    "METRIC_MAP",
    "MIN_ACTIVE_DAYS",
    "MIN_CANDIDATES",
    "MIN_MEAN_CORRELATION",
    "MetricFamily",
    "MetricReading",
    "MetricSpec",
    "MutationKind",
    "MutationMetrics",
    "MutationReadings",
    "POST_WINDOW_DAYS",
    "PRE_WINDOW_DAYS",
    "PercentSuppressedReason",
    "RawDailyRecord",
    "ReadingStatus",
    "RenderedReadingCopy",
    "RunReadings",
    "SKU_ORDERS",
    "SelectedControl",
    "TOP_K",
    "TierOutcome",
    "VOLUME_FLOORS",
    "WindowKind",
    "Windows",
    "assign_confidence",
    "compute_confidence",
    "compute_expected",
    "compute_growth",
    "compute_impact_pct",
    "compute_incremental",
    "compute_metric_reading",
    "compute_mutation_readings",
    "compute_noise_band",
    "compute_post",
    "compute_pre",
    "compute_run_readings",
    "compute_windows",
    "date_range",
    "mean_over_window",
    "metric_family_of",
    "metric_label_vi",
    "post_window",
    "pre_period_volume",
    "pre_window",
    "render_below_floor",
    "render_confounded",
    "render_reading",
    "render_suppressed",
    "render_tiered_reading",
    "resolve_metric",
    "select_control_pool",
    "volume_floor_for",
]
