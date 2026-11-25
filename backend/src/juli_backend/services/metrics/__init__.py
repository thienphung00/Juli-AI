"""The metric registry (T5/T6): one id, one formula, one rounding rule per number Juli shows.

``registry`` declares the metrics, ``components`` the canonical sums they read, ``compute`` is
the only place a formula runs, ``allocation`` holds the written channel and "Cả shop" rules.
Design: ``docs/architecture/metric-registry.md``. Step 1: nothing reads this package yet.
"""

from __future__ import annotations

from juli_backend.services.metrics.allocation import (
    ShopLine,
    ShopLines,
    channel_partition,
    deoverlap_periods,
    shop_lines,
)
from juli_backend.services.metrics.components import (
    COMPONENTS,
    ComponentDef,
    Components,
    Dim,
    InvalidSum,
    can_sum,
    check_sum,
)
from juli_backend.services.metrics.compute import (
    KolState,
    KolStatus,
    MetricValue,
    change,
    evaluate,
    kol_status,
    per_day,
)
from juli_backend.services.metrics.registry import (
    DERIVATION_VERSION,
    METRIC_ALIASES,
    METRICS,
    Comparison,
    MetricDef,
    Platform,
    SourceSpec,
)

__all__ = [
    "COMPONENTS",
    "DERIVATION_VERSION",
    "METRICS",
    "METRIC_ALIASES",
    "Comparison",
    "ComponentDef",
    "Components",
    "Dim",
    "InvalidSum",
    "KolState",
    "KolStatus",
    "MetricDef",
    "MetricValue",
    "Platform",
    "ShopLine",
    "ShopLines",
    "SourceSpec",
    "can_sum",
    "change",
    "channel_partition",
    "check_sum",
    "deoverlap_periods",
    "evaluate",
    "kol_status",
    "per_day",
    "shop_lines",
]
