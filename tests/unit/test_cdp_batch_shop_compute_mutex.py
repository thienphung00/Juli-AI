"""Unit tests for CDP batch ShopComputeMutex (#618 / CDP-A2-4).

PR-safe: InMemory + FakeSyncRedis only — no live Redis, Partner HTTP, or speed wiring.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
import pytest_asyncio

from juli_backend.models.models import Shop, User
from juli_backend.repositories.repos import AnalyticsKpiEnvelopesRepo

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_MD = REPO_ROOT / "backend/src/juli_backend/services/cdp_batch/MODULE.md"
MUTEX_PATH = REPO_ROOT / "backend/src/juli_backend/services/cdp_batch/shop_compute_mutex.py"


class FakeSyncRedis:
    """Minimal sync Redis fake for ShopComputeMutex tests."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}
        self._expiries: dict[str, int] = {}

    def get(self, key: str) -> str | None:
        return self._store.get(key)

    def set(
        self,
        key: str,
        value: str,
        *,
        nx: bool = False,
        ex: int | None = None,
    ) -> bool:
        if nx and key in self._store:
            return False
        self._store[key] = value
        if ex is not None:
            self._expiries[key] = ex
        return True

    def delete(self, key: str) -> None:
        self._store.pop(key, None)
        self._expiries.pop(key, None)


def test_shop_compute_mutex_module_exists() -> None:
    assert MUTEX_PATH.is_file()


def test_compute_mutex_key_pattern() -> None:
    from juli_backend.services.cdp_batch.shop_compute_mutex import compute_mutex_key

    assert compute_mutex_key("shop-abc") == "compute:shop-abc"


def test_batch_entry_proceeds_when_lock_free() -> None:
    from juli_backend.services.cdp_batch.shop_compute_mutex import (
        InMemoryShopComputeMutex,
        try_begin_batch_compute,
    )

    mutex = InMemoryShopComputeMutex()
    result = try_begin_batch_compute(mutex, "shop-1")

    assert result.acquired is True
    assert result.defer_reason is None
    assert mutex.current_owner("shop-1") == "batch"


def test_batch_entry_defers_when_speed_active() -> None:
    from juli_backend.services.cdp_batch.shop_compute_mutex import (
        DEFER_REASON,
        InMemoryShopComputeMutex,
        try_begin_batch_compute,
    )

    mutex = InMemoryShopComputeMutex()
    assert mutex.try_acquire("shop-1", "speed") is True

    result = try_begin_batch_compute(mutex, "shop-1")

    assert result.acquired is False
    assert result.defer_reason == DEFER_REASON
    assert result.defer_reason == "speed_mutex_active"


def test_speed_and_batch_cannot_both_hold_lock() -> None:
    from juli_backend.services.cdp_batch.shop_compute_mutex import (
        InMemoryShopComputeMutex,
        try_begin_batch_compute,
    )

    mutex = InMemoryShopComputeMutex()
    assert mutex.try_acquire("shop-1", "speed") is True
    assert try_begin_batch_compute(mutex, "shop-1").acquired is False
    assert mutex.try_acquire("shop-1", "batch") is False

    mutex.release("shop-1", "speed")
    assert try_begin_batch_compute(mutex, "shop-1").acquired is True
    assert mutex.try_acquire("shop-1", "speed") is False


def test_redis_mutex_contention_matches_in_memory() -> None:
    from juli_backend.services.cdp_batch.shop_compute_mutex import (
        DEFER_REASON,
        RedisShopComputeMutex,
        try_begin_batch_compute,
    )

    redis = FakeSyncRedis()
    mutex = RedisShopComputeMutex(redis)
    assert mutex.try_acquire("shop-redis", "speed") is True

    result = try_begin_batch_compute(mutex, "shop-redis")

    assert result.acquired is False
    assert result.defer_reason == DEFER_REASON
    assert redis.get("compute:shop-redis") == "speed"


def test_release_allows_subsequent_batch_acquire() -> None:
    from juli_backend.services.cdp_batch.shop_compute_mutex import (
        InMemoryShopComputeMutex,
        try_begin_batch_compute,
    )

    mutex = InMemoryShopComputeMutex()
    first = try_begin_batch_compute(mutex, "shop-1")
    assert first.acquired is True

    mutex.release("shop-1", "batch")
    second = try_begin_batch_compute(mutex, "shop-1")
    assert second.acquired is True


def test_mutex_key_distinct_from_material_analytics_ingest() -> None:
    from juli_backend.services.cdp_batch.shop_compute_mutex import compute_mutex_key

    compute_key = compute_mutex_key("shop-1")
    material_key = "material_analytics:mutex:shop-1"

    assert compute_key != material_key
    assert compute_key.startswith("compute:")


@pytest_asyncio.fixture
async def shop(session, user_id):
    user = User(id=user_id, phone="+849305000618")
    session.add(user)
    await session.flush()
    s = Shop(
        id=uuid.uuid4(),
        user_id=user.id,
        shop_name="Mutex Gold Shop 618",
        tiktok_shop_id="tiktok_shop_618",
    )
    session.add(s)
    await session.flush()
    return s


def _sample_payload(*, shop_id: uuid.UUID, computed_at: datetime) -> dict:
    return {
        "envelope_version": 1,
        "kind": "analytics",
        "shop_id": str(shop_id),
        "computed_at": computed_at.isoformat(),
        "currency": "VND",
        "kpis": {
            "gmv_tiktok": {
                "availability": "available",
                "label": "GMV (TikTok)",
                "series": [{"t": "2026-07-01", "v": 618.0}],
            }
        },
        "meta": {"source_partitions": ["A-36"], "notes": []},
    }


@pytest.mark.asyncio
async def test_active_speed_lock_leaves_last_good_gold_unchanged(session, shop) -> None:
    from juli_backend.services.cdp_batch.shop_compute_mutex import (
        DEFER_REASON,
        InMemoryShopComputeMutex,
        try_begin_batch_compute,
    )

    computed_at = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)
    payload = _sample_payload(shop_id=shop.id, computed_at=computed_at)
    repo = AnalyticsKpiEnvelopesRepo(session)
    await repo.upsert(
        shop_id=shop.id,
        kind="analytics",
        envelope_version=1,
        payload=payload,
        computed_at=computed_at,
    )
    await session.flush()

    mutex = InMemoryShopComputeMutex()
    assert mutex.try_acquire(str(shop.id), "speed") is True

    result = try_begin_batch_compute(mutex, str(shop.id))
    assert result.acquired is False
    assert result.defer_reason == DEFER_REASON

    stored = await repo.get_by_kind(shop.id, "analytics")
    assert stored is not None
    assert stored.payload == payload


def test_mutex_ttl_documented_and_applied() -> None:
    from juli_backend.services.cdp_batch.shop_compute_mutex import (
        COMPUTE_MUTEX_TTL_SECONDS,
        InMemoryShopComputeMutex,
    )

    now = {"t": 1000.0}

    def clock() -> float:
        return now["t"]

    mutex = InMemoryShopComputeMutex(clock=clock, ttl_seconds=COMPUTE_MUTEX_TTL_SECONDS)
    assert mutex.try_acquire("shop-ttl", "speed") is True
    assert mutex.current_owner("shop-ttl") == "speed"

    now["t"] += COMPUTE_MUTEX_TTL_SECONDS
    assert mutex.current_owner("shop-ttl") is None


def test_mutex_acquire_release_api_documented_for_batch_and_speed_callers() -> None:
    import inspect

    from juli_backend.services import cdp_batch
    from juli_backend.services.cdp_batch.shop_compute_mutex import (
        COMPUTE_MUTEX_TTL_SECONDS,
        DEFER_REASON,
        InMemoryShopComputeMutex,
        RedisShopComputeMutex,
    )

    content = MODULE_MD.read_text(encoding="utf-8")
    assert "ShopComputeMutex" in content
    assert "try_acquire" in content
    assert "release" in content
    assert "speed" in content
    assert "batch" in content
    assert "compute:{shop_id}" in content
    assert "COMPUTE_MUTEX_TTL_SECONDS" in content
    assert "speed_mutex_active" in content

    for export_name in (
        "ShopComputeMutex",
        "InMemoryShopComputeMutex",
        "RedisShopComputeMutex",
        "compute_mutex_key",
        "try_begin_batch_compute",
        "COMPUTE_MUTEX_TTL_SECONDS",
        "SPEED_MUTEX_DEFER_REASON",
    ):
        assert hasattr(cdp_batch, export_name), export_name
    assert cdp_batch.SPEED_MUTEX_DEFER_REASON == DEFER_REASON
    assert COMPUTE_MUTEX_TTL_SECONDS > 0

    mutex = InMemoryShopComputeMutex()
    assert mutex.try_acquire("shop-api", "speed") is True
    assert mutex.current_owner("shop-api") == "speed"
    mutex.release("shop-api", "speed")
    assert mutex.current_owner("shop-api") is None

    assert mutex.try_acquire("shop-api", "batch") is True
    assert mutex.current_owner("shop-api") == "batch"
    mutex.release("shop-api", "batch")

    for backend in (InMemoryShopComputeMutex, RedisShopComputeMutex):
        assert callable(getattr(backend, "try_acquire", None))
        assert callable(getattr(backend, "release", None))
        acquire_params = inspect.signature(backend.try_acquire).parameters
        release_params = inspect.signature(backend.release).parameters
        assert "shop_id" in acquire_params
        assert "owner" in acquire_params
        assert "shop_id" in release_params
        assert "owner" in release_params


def test_does_not_implement_a1_material_webhook_handoff_or_speed_precompute() -> None:
    import ast

    from juli_backend.services import cdp_batch

    source = MUTEX_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    import_modules = [
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    ]
    forbidden_prefixes = (
        "juli_backend.services.webhook",
        "juli_backend.services.cdp_speed",
    )
    for module in import_modules:
        assert not any(module.startswith(prefix) for prefix in forbidden_prefixes), module

    forbidden_symbols = {
        "material_handoff",
        "material_dispatch",
        "material_worker",
        "MaterialEnqueueGate",
        "precompute_shop_analytics",
        "dispatch_material_webhook",
    }
    for symbol in forbidden_symbols:
        assert symbol not in source

    public_exports = set(cdp_batch.__all__)
    assert not public_exports & forbidden_symbols

    module_md = MODULE_MD.read_text(encoding="utf-8")
    assert "speed wiring is A1" in module_md
    assert "material_analytics:mutex" in module_md
