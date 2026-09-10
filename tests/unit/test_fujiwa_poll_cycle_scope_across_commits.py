"""RED->GREEN regression test for #1880's second unpatched site: the Fujiwa
production-read poll path.

``run_fujiwa_poll_cycle`` / ``run_fujiwa_material_resource_fetch`` resolve
their credential via ``resolve_production_read_credential`` -> ``_lazy_refresh``
-> ``core/security/credential_refresh.py::refresh_credential``, whose first
``session.commit()`` runs unconditionally (even on the fresh path) and, under
the caller's ``with_shop_scope`` (``SET LOCAL``), discards
``app.current_shop_id``. Both functions then read tenant rows on the same
session immediately after: ``TikTokSyncStateRepo.load`` (a direct-GUC policy
-- unscoped means a silent empty read, not an exception) and
``session.get(Shop, credential.shop_id)`` (``shops_shop_scope_select`` ->
``None`` -> this module's own ``ValueError``).

Real-COMMIT session factory reused from
``tests/unit/test_action_card_refresh_task_scope.py::_juli_app_engine_session_factory``
-- the same reasoning as ``test_credential_refresh_scope_across_commits.py``:
the shared ``juli_app_session`` fixture only joins a SAVEPOINT on
``session.commit()``, which would pass whether or not the reapply fix is
applied.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import create_engine, text

from juli_backend.core.config.runtime import sync_database_url
from juli_backend.core.security.tiktok_oauth import TikTokOAuthService
from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.integrations.tiktok import PRODUCTION_AUTH_ID, TikTokCapability
from juli_backend.models.models import TikTokCredential
from juli_backend.workers.services.polling.orchestrate import (
    FujiwaPollConfig,
    run_fujiwa_poll_cycle,
)
from tests.unit.test_action_card_refresh_task_scope import _juli_app_engine_session_factory

requires_postgres = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").strip().startswith("postgresql"),
    reason="DATABASE_URL is not set to a Postgres instance",
)

APP_KEY = "test_app_key"
APP_SECRET = "test_app_secret"


@pytest.fixture
def owner_engine():
    """A sync engine connected as the table owner, on the shared database."""
    url = os.environ.get("DATABASE_URL", "").strip()
    engine = create_engine(sync_database_url(url))
    try:
        yield engine
    finally:
        engine.dispose()


def _seed_fujiwa_shop_and_credential(engine, *, label: str) -> tuple[uuid.UUID, uuid.UUID]:
    """Seed one shop (with ``tiktok_shop_id``) and one production-read
    credential, far from expiry so the fake resolver -- not
    ``refresh_credential`` itself -- controls when the commit happens.

    Returns ``(shop_id, credential_id)``.
    """
    now = datetime.now(UTC).replace(tzinfo=None)
    user_id = uuid.uuid4()
    shop_id = uuid.uuid4()
    credential_id = uuid.uuid4()

    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO public.users (id, phone, created_at, updated_at) "
                "VALUES (:id, :phone, :now, :now)"
            ),
            {"id": str(user_id), "phone": f"+1555{user_id.hex[:7]}", "now": now},
        )
        conn.execute(
            text(
                "INSERT INTO public.shops "
                "(id, user_id, shop_name, tiktok_shop_id, created_at, updated_at) "
                "VALUES (:id, :user_id, :name, :tiktok_shop_id, :now, :now)"
            ),
            {
                "id": str(shop_id),
                "user_id": str(user_id),
                "name": f"{label} shop",
                "tiktok_shop_id": f"tt-{shop_id.hex[:10]}",
                "now": now,
            },
        )
        conn.execute(
            text(
                "INSERT INTO public.tiktok_credentials "
                "(id, shop_id, merchant_authorization_id, capability, shop_cipher, "
                " access_token, refresh_token, token_expires_at, status, refresh_count, "
                " created_at, updated_at) "
                "VALUES (:id, :shop_id, :merchant_id, :capability, :cipher, "
                " :access, :refresh, :expires, 'active', 0, :now, :now)"
            ),
            {
                "id": str(credential_id),
                "shop_id": str(shop_id),
                "merchant_id": PRODUCTION_AUTH_ID,
                "capability": TikTokCapability.PRODUCTION_READ.value,
                "cipher": "ROW_test_cipher",
                "access": "fujiwa-access",
                "refresh": "fujiwa-refresh",
                "expires": now.replace(year=now.year + 1),
                "now": now,
            },
        )

    return shop_id, credential_id


def _mock_resources() -> MagicMock:
    """Mirrors ``test_fujiwa_polling_orchestration.py``'s ``mock_resources``
    fixture -- every collaborator every ``_FUJIWA_POLL_STEPS`` entry plus
    ``sync_analytics`` touches."""
    resources = MagicMock()
    resources.orders.search_all.return_value = []
    resources.products.search_all.return_value = []
    resources.returns.search_returns_all.return_value = []
    resources.inventory.search.return_value = {"code": 0, "data": {"inventory": []}}
    resources.analytics.list_sku_performance_all.return_value = []
    resources.analytics.list_product_performance_all.return_value = []
    resources.analytics.get_shop_performance.return_value = {}
    resources.analytics.get_shop_performance_per_hour.return_value = {}
    resources.analytics.get_bestselling_products.return_value = {}
    resources.analytics.get_bestselling_videos.return_value = {}
    resources.promotion.get_activity.return_value = {}
    return resources


@requires_postgres
@pytest.mark.asyncio
async def test_poll_cycle_survives_the_resolvers_own_commit_under_shop_scope(owner_engine):
    """The resolver's commit must not strand the rest of the cycle unscoped.

    RED on the pre-fix code: the fake resolver below commits the session
    exactly like ``refresh_credential`` does; without the reapply, the
    following ``session.get(Shop, credential.shop_id)`` sees no row under
    ``shops_shop_scope_select`` and `run_fujiwa_poll_cycle` raises
    ``ValueError('Fujiwa polling requires a shop with tiktok_shop_id...')``.
    """
    shop_id, credential_id = _seed_fujiwa_shop_and_credential(owner_engine, label="poll-scope")

    async def _resolve_that_commits(session) -> TikTokCredential:
        # Real signature, real session, real commit -- mirrors what
        # `resolve_production_read_credential` -> `_lazy_refresh` ->
        # `refresh_credential` does in production (#1880).
        credential = await session.get(TikTokCredential, credential_id, populate_existing=True)
        assert credential is not None
        await session.commit()
        return credential

    mock_resources = _mock_resources()
    mock_rate_limiter = MagicMock()
    mock_rate_limiter.acquire.return_value = True
    mock_rate_limiter.is_exhausted.return_value = False
    mock_rate_limiter.time_until_reset.return_value = 0

    async def _handoff(channel: str, shop_key: str, value: bytes) -> None:
        return None

    async with _juli_app_engine_session_factory() as factory, factory() as session:
        async with with_shop_scope(session, shop_id):
            # No ValueError, no NotFound: the regression this issue exists to close.
            await run_fujiwa_poll_cycle(
                session=session,
                config=FujiwaPollConfig(app_key=APP_KEY, app_secret=APP_SECRET),
                oauth_service=MagicMock(spec=TikTokOAuthService),
                rate_limiter=mock_rate_limiter,
                handoff_fn=_handoff,
                resolve_credential=AsyncMock(side_effect=_resolve_that_commits),
                create_resources=lambda _cfg: mock_resources,
            )
        await session.commit()

    # `orders.search_all` is only reached after the shop-read guard clause and
    # the sync-state load both succeeded -- so this proves the cycle actually
    # ran the poll steps under scope, not merely that no exception surfaced.
    mock_resources.orders.search_all.assert_called_once()
    mock_resources.products.search_all.assert_called_once()
    mock_resources.returns.search_returns_all.assert_called_once()
    mock_resources.inventory.search.assert_called_once()
