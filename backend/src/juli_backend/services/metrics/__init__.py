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
    shop_lines,
)
from juli_backend.services.metrics.components import COMPONENTS, ComponentDef, Components
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
    METRICS,
    Comparison,
    MetricDef,
    SourceSpec,
)

__all__ = [
    "COMPONENTS",
    "DERIVATION_VERSION",
    "METRICS",
    "Comparison",
    "ComponentDef",
    "Components",
    "KolState",
    "KolStatus",
    "MetricDef",
    "MetricValue",
    "ShopLine",
    "ShopLines",
    "SourceSpec",
    "change",
    "channel_partition",
    "evaluate",
    "kol_status",
    "per_day",
    "shop_lines",
]
