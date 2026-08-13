"""Incremental impact measurement — funnel-first metric map, ratio-form DiD
compute, and control-pool selection (ADR-077 decisions 1, 2 and 3; #1041,
#1042).

This package answers three questions: **which metric** does a mutation act
on (``metric_map.py``), **which sibling products form its control cohort**
(``control_pool.py``), and **what is the control-adjusted incremental
impact** for that metric given a target series, a control series, and the
write's execution date T (``windows.py`` + ``compute.py`` + ``reading.py``).
Everything else ADR-077 describes is explicitly out of scope here and owned
by later, stacked issues in the same package:

- Control-pool **candidate discovery I/O** — querying same-shop siblings,
  detecting a Juli-run touch, and resolving a product's first-active date —
  is not performed here; ``control_pool.select_control_pool`` receives an
  already-fetched ``Sequence[ControlCandidate]`` and the volume-floor value
  as plain arguments, mirroring how ``reading.py`` receives
  ``confounded: bool``.
- **Confidence tiers**, per-metric volume-floor *config* (the numeric
  thresholds themselves), and the seller-facing copy layer arrive with #1043.
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
    "CONVERSION_RATE",
    "CTR",
    "GMV",
    "GMV_PER_ORDER",
    "IMPRESSIONS",
    "ITEMS_SOLD",
    "METRIC_MAP",
    "MIN_ACTIVE_DAYS",
    "MIN_CANDIDATES",
    "MIN_MEAN_CORRELATION",
    "POST_WINDOW_DAYS",
    "PRE_WINDOW_DAYS",
    "SKU_ORDERS",
    "TOP_K",
    "ControlCandidate",
    "ControlPoolResult",
    "FallbackReason",
    "POST_WINDOW_DAYS",
    "PRE_WINDOW_DAYS",
    "SKU_ORDERS",
    "MetricReading",
    "MetricSpec",
    "MutationKind",
    "MutationMetrics",
    "MutationReadings",
    "PercentSuppressedReason",
    "RawDailyRecord",
    "ReadingStatus",
    "RunReadings",
    "SelectedControl",
    "WindowKind",
    "Windows",
    "compute_expected",
    "compute_growth",
    "compute_impact_pct",
    "compute_incremental",
    "compute_metric_reading",
    "compute_mutation_readings",
    "compute_post",
    "compute_pre",
    "compute_run_readings",
    "compute_windows",
    "date_range",
    "mean_over_window",
    "post_window",
    "pre_window",
    "resolve_metric",
    "select_control_pool",
]
