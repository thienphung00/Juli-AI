"""health_data_source tier handling per endpoints.md degraded-mode contract."""

from __future__ import annotations

from decimal import Decimal

from juli_backend.services.aggregates.types import (
    HealthDataSource,
    HealthSnapshot,
    ProxyHealthSignals,
)


def resolve_health_snapshot(
    *,
    health_data_source: HealthDataSource,
    api_sps_score: float | None = None,
    api_vp_score: float | None = None,
    api_ahr_score: float | None = None,
    order_count: int = 0,
    return_count: int = 0,
    product_count: int = 0,
) -> HealthSnapshot:
    if health_data_source == HealthDataSource.UNAVAILABLE:
        return HealthSnapshot(
            health_data_source=HealthDataSource.UNAVAILABLE,
            sps_score=None,
            vp_score=None,
            ahr_score=None,
            proxy_signals=None,
        )

    if health_data_source == HealthDataSource.API:
        return HealthSnapshot(
            health_data_source=HealthDataSource.API,
            sps_score=api_sps_score,
            vp_score=api_vp_score,
            ahr_score=api_ahr_score,
            proxy_signals=None,
        )

    return_rate_proxy: float | None = None
    if order_count > 0:
        return_rate_proxy = float(Decimal(return_count) / Decimal(order_count))

    proxy = ProxyHealthSignals(
        return_rate_proxy=return_rate_proxy,
        product_count=product_count,
        order_count=order_count,
    )
    return HealthSnapshot(
        health_data_source=HealthDataSource.PROXY,
        sps_score=None,
        vp_score=None,
        ahr_score=None,
        proxy_signals=proxy,
    )
