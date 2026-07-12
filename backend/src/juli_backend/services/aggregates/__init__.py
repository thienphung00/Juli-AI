"""Rules-only feature aggregates over production-synced Postgres (#300, #374)."""

from juli_backend.services.aggregates.builder import (
    SYNCED_DATA_SOURCES,
    build_feature_aggregates,
)
from juli_backend.services.aggregates.computed_kpis import ComputedKpiMetrics, compute_all_kpis
from juli_backend.services.aggregates.health_source import resolve_health_snapshot
from juli_backend.services.aggregates.shop_profile import classify_shop_profile
from juli_backend.services.aggregates.types import (
    FeatureAggregateSnapshot,
    HealthDataSource,
    HealthSnapshot,
    ProxyHealthSignals,
    ShopLifecycleContext,
    ShopProfile,
    ShopProfileSignals,
)

__all__ = [
    "SYNCED_DATA_SOURCES",
    "ComputedKpiMetrics",
    "FeatureAggregateSnapshot",
    "HealthDataSource",
    "HealthSnapshot",
    "ProxyHealthSignals",
    "ShopLifecycleContext",
    "ShopProfile",
    "ShopProfileSignals",
    "build_feature_aggregates",
    "classify_shop_profile",
    "compute_all_kpis",
    "resolve_health_snapshot",
]
