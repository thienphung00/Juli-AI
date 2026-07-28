"""Hourly Mock-mode Analytics reconciliation for the Demo reference shop (#533).

Phase 2.10 Mock-mode reconciliation only (ADR-038 §5): Celery Beat runs once per
hour and recomputes Analytics KPI envelopes for ``DEMO_REFERENCE_SHOP_ID`` only.
This is not global daily scoring and must not fan out to all shops.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from collections.abc import Callable

from juli_backend.models.models import Shop
from juli_backend.workers.celery_app import celery_app
from juli_backend.workers.tasks.material_analytics_precompute import (
    material_analytics_precompute_sync,
)

logger = logging.getLogger(__name__)


def get_demo_reference_shop_id() -> uuid.UUID | None:
    """Return configured Demo reference shop id, if set."""
    raw = os.getenv("DEMO_REFERENCE_SHOP_ID", "").strip()
    if not raw:
        return None
    return uuid.UUID(raw)


def _database_url() -> str:
    return os.getenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")


def _ensure_session_factory():
    from sqlalchemy.ext.asyncio import create_async_engine

    from juli_backend.database.database import create_session_factory, init_session_factory

    engine = create_async_engine(_database_url())
    factory = create_session_factory(engine)
    init_session_factory(factory)
    return factory


async def _lookup_tiktok_shop_key_async(shop_id: uuid.UUID) -> str | None:
    factory = _ensure_session_factory()
    async with factory() as session:
        shop = await session.get(Shop, shop_id)
        if shop is None or not shop.tiktok_shop_id:
            logger.warning(
                "mock_analytics_reconcile_unknown_shop",
                extra={"shop_id": str(shop_id)},
            )
            return None
        return shop.tiktok_shop_id


def _lookup_tiktok_shop_key(shop_id: uuid.UUID) -> str | None:
    return asyncio.run(_lookup_tiktok_shop_key_async(shop_id))


def run_mock_analytics_reconcile_sync(
    *,
    precompute_fn: Callable[[str], None] | None = None,
) -> None:
    """Recompute Analytics envelopes for the configured reference shop only."""
    shop_id = get_demo_reference_shop_id()
    if shop_id is None:
        logger.info(
            "mock_analytics_reconcile_skipped",
            extra={"reason": "missing_demo_reference_shop_id"},
        )
        return

    shop_key = _lookup_tiktok_shop_key(shop_id)
    if shop_key is None:
        return

    compute = precompute_fn or material_analytics_precompute_sync
    compute(shop_key)


@celery_app.task(name="juli_backend.mock_analytics_hourly_reconcile")
def mock_analytics_hourly_reconcile() -> None:
    """Hourly Celery Beat entrypoint for Mock-mode reference-shop reconciliation."""
    run_mock_analytics_reconcile_sync()
