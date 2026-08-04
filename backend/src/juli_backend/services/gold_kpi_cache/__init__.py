"""Gold KPI envelope Redis cache — read-through cache with last-good fallback (#631)."""

from __future__ import annotations

from juli_backend.services.gold_kpi_cache.cache import (
    close_shared_redis_client,
    create_redis_client,
    envelope_cache_key,
    get_gold_kpi_envelope,
    get_gold_kpi_envelope_with_last_good_fallback,
    get_shared_redis_client,
    refresh_gold_kpi_envelope_cache,
    reset_shared_redis_client_for_tests,
)

__all__ = [
    "envelope_cache_key",
    "get_gold_kpi_envelope",
    "get_gold_kpi_envelope_with_last_good_fallback",
    "refresh_gold_kpi_envelope_cache",
    "create_redis_client",
    "get_shared_redis_client",
    "close_shared_redis_client",
    "reset_shared_redis_client_for_tests",
]
