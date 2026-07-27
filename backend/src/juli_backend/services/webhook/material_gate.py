"""Per-shop enqueue gate for material Analytics precompute (#532)."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Protocol

from juli_backend.services.tiktok.webhook_catalog import (
    COALESCE_68_SECONDS,
    INVENTORY_CHANGED_CATALOG_ID,
)

MUTEX_TTL_SECONDS = 300


class MaterialEnqueueGate(Protocol):
    def try_acquire(self, shop_key: str, catalog_id: int) -> bool: ...

    def release(self, shop_key: str) -> None: ...


class InMemoryMaterialEnqueueGate:
    """Test-friendly gate: #68 coalesce window + per-shop mutex."""

    def __init__(self, *, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._coalesce68: dict[str, float] = {}
        self._mutex_until: dict[str, float] = {}

    def try_acquire(self, shop_key: str, catalog_id: int) -> bool:
        now = self._clock()
        if catalog_id == INVENTORY_CHANGED_CATALOG_ID:
            last = self._coalesce68.get(shop_key)
            if last is not None and now - last < COALESCE_68_SECONDS:
                return False

        mutex_expiry = self._mutex_until.get(shop_key)
        if mutex_expiry is not None and now < mutex_expiry:
            return False

        self._mutex_until[shop_key] = now + MUTEX_TTL_SECONDS
        if catalog_id == INVENTORY_CHANGED_CATALOG_ID:
            self._coalesce68[shop_key] = now
        return True

    def release(self, shop_key: str) -> None:
        self._mutex_until.pop(shop_key, None)


class RedisMaterialEnqueueGate:
    """Production gate backed by Redis keys."""

    def __init__(
        self,
        redis_client: object,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._redis = redis_client
        self._clock = clock

    def _mutex_key(self, shop_key: str) -> str:
        return f"material_analytics:mutex:{shop_key}"

    def _coalesce68_key(self, shop_key: str) -> str:
        return f"material_analytics:coalesce68:{shop_key}"

    def try_acquire(self, shop_key: str, catalog_id: int) -> bool:
        now = self._clock()
        if catalog_id == INVENTORY_CHANGED_CATALOG_ID:
            last_raw = self._redis.get(self._coalesce68_key(shop_key))
            if last_raw is not None:
                last = float(last_raw)
                if now - last < COALESCE_68_SECONDS:
                    return False

        acquired = self._redis.set(
            self._mutex_key(shop_key),
            "1",
            nx=True,
            ex=MUTEX_TTL_SECONDS,
        )
        if not acquired:
            return False

        if catalog_id == INVENTORY_CHANGED_CATALOG_ID:
            self._redis.set(
                self._coalesce68_key(shop_key),
                str(now),
                ex=COALESCE_68_SECONDS,
            )
        return True

    def release(self, shop_key: str) -> None:
        self._redis.delete(self._mutex_key(shop_key))
