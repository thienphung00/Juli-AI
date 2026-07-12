from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Literal


class HealthDataSource(StrEnum):
    API = "api"
    PROXY = "proxy"
    UNAVAILABLE = "unavailable"


class ShopProfile(StrEnum):
    NEW_SHOP = "NEW_SHOP"
    MID_LARGE_SHOP = "MID_LARGE_SHOP"


ProbationStatus = Literal["active", "graduated", "not_applicable"]


@dataclass(frozen=True)
class ShopProfileSignals:
    probation_status: ProbationStatus
    shop_age_days: int
    sps_current: float | None = None
    sps_threshold: float | None = None
    ahr_current: float | None = None
    ahr_threshold: float | None = None
    product_gmv_total: Decimal = Decimal("0")
    product_units_sold_total: int = 0
    ad_revenue_total: Decimal = Decimal("0")
    ad_spend_total: Decimal = Decimal("0")


@dataclass(frozen=True)
class ShopLifecycleContext:
    """Lifecycle and health inputs not yet persisted on Shop rows."""

    probation_status: ProbationStatus = "not_applicable"
    health_data_source: HealthDataSource = HealthDataSource.UNAVAILABLE
    api_sps_score: float | None = None
    api_vp_score: float | None = None
    api_ahr_score: float | None = None


@dataclass(frozen=True)
class ProxyHealthSignals:
    return_rate_proxy: float | None
    product_count: int
    order_count: int


@dataclass(frozen=True)
class HealthSnapshot:
    health_data_source: HealthDataSource
    sps_score: float | None
    vp_score: float | None
    ahr_score: float | None
    proxy_signals: ProxyHealthSignals | None = None


@dataclass(frozen=True)
class FeatureAggregateSnapshot:
    shop_id: uuid.UUID
    shop_profile: ShopProfile
    health_data_source: HealthDataSource
    sps_score: float | None
    vp_score: float | None
    ahr_score: float | None
    order_count: int
    product_count: int
    return_count: int
    total_order_value: Decimal
    total_product_revenue: Decimal
    total_units_sold: int
    return_rate_proxy: float | None
    data_sources: list[str]
    proxy_signals: ProxyHealthSignals | None = None
