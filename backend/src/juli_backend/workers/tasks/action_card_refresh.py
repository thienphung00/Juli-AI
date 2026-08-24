"""Celery task entrypoint for manual action-card refresh (#303)."""

from __future__ import annotations

import asyncio
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from juli_backend.models.models import TikTokCredential
from juli_backend.services.action_cards.refresh import run_action_card_refresh
from juli_backend.workers.celery_app import celery_app
from juli_backend.workers.services.polling.sync import (
    check_sandbox_write_catalog_identity_mismatch,
    sync_products_with_local_upsert,
)
from juli_backend.workers.tasks.database import get_async_database_url

logger = logging.getLogger(__name__)


def _database_url() -> str:
    return get_async_database_url()


def _ensure_session_factory() -> async_sessionmaker:
    from juli_backend.database.database import ensure_worker_session_factory

    return ensure_worker_session_factory(_database_url())


async def _refresh_async(shop_id: uuid.UUID) -> None:
    factory = _ensure_session_factory()
    async with factory() as session:
        # Sync sandbox_write catalog before refresh if credential exists
        await _sync_sandbox_write_catalog_if_needed(session, shop_id)

        # Check for credential identity mismatch
        await check_sandbox_write_catalog_identity_mismatch(session, shop_id)

        # Run the standard refresh
        await run_action_card_refresh(session, shop_id)
        await session.commit()


async def _sync_sandbox_write_catalog_if_needed(session: AsyncSession, shop_id: uuid.UUID) -> None:
    """Sync sandbox_write seller's catalog to shop if sandbox_write credential exists.

    This ensures ADR-082 product binding can resolve to products owned by the
    write credential's merchant. Errors are logged but do not abort the refresh.
    """
    # Check if shop has a sandbox_write credential
    stmt = select(TikTokCredential).where(
        TikTokCredential.shop_id == shop_id,
        TikTokCredential.capability == "sandbox_write",
    )
    result = await session.execute(stmt)
    sandbox_write_cred = result.scalar_one_or_none()

    if sandbox_write_cred is None:
        # No sandbox_write credential, skip sync
        return

    try:
        # Build sandbox_write client and sync products
        # Get TikTok app credentials from environment
        import os

        from juli_backend.integrations.tiktok import (
            SANDBOX_AUTH_ID,
            ClientFactoryConfig,
            SandboxWriteClientFactory,
        )
        from juli_backend.repositories.repos import ProductsRepo

        app_key = os.getenv("TIKTOK_APP_KEY", "")
        app_secret = os.getenv("TIKTOK_APP_SECRET", "")

        if not app_key or not app_secret:
            logger.info(
                "sandbox_write_catalog_sync_skipped",
                extra={"shop_id": str(shop_id), "reason": "no_tiktok_app_credentials"},
            )
            return

        # Create client config and resources
        config = ClientFactoryConfig(
            app_key=app_key,
            app_secret=app_secret,
            access_token=sandbox_write_cred.access_token,
            merchant_auth_id=SANDBOX_AUTH_ID,
            shop_cipher=sandbox_write_cred.shop_cipher,
        )
        resources = SandboxWriteClientFactory.create(config)

        # Create products repo and sync state
        products_repo = ProductsRepo(session)
        sync_state = {}

        # Mock rate limiter for task context (not in polling loop)
        mock_rate_limiter = _MockRateLimiter()

        # Empty handoff (we only care about local upsert in task)
        async def noop_handoff(channel: str, shop_key: str, value: bytes) -> None:
            pass

        # Run the sync with local upsert
        await sync_products_with_local_upsert(
            resource=resources.products,
            rate_limiter=mock_rate_limiter,
            handoff_fn=noop_handoff,
            products_repo=products_repo,
            app_id="refresh_task",
            shop_id=str(shop_id),
            sync_state=sync_state,
        )

        logger.info(
            "sandbox_write_catalog_sync_completed",
            extra={"shop_id": str(shop_id), "products_synced": len(sync_state)},
        )

    except Exception:
        logger.warning(
            "sandbox_write_catalog_sync_failed",
            extra={"shop_id": str(shop_id)},
            exc_info=True,
        )


class _MockRateLimiter:
    """Minimal rate limiter mock for sandbox sync in task context."""

    def acquire(self, app_id: str, shop_id: str, endpoint: str, **kwargs) -> bool:
        return True


def refresh_action_cards_sync(shop_id: str) -> None:
    asyncio.run(_refresh_async(uuid.UUID(shop_id)))


@celery_app.task(name="juli_backend.refresh_action_cards")
def refresh_action_cards(shop_id: str) -> None:
    """Run poll → scoring → persist outside the HTTP request cycle."""
    refresh_action_cards_sync(shop_id)
