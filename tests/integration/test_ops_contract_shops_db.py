"""Contract-client shops on real Postgres, as ``juli_app`` under RLS (ADR-118).

The Ops routes run as the app role: creating the login-less owner and its shop, reading
whether it is a contract client and granting consent must all pass the existing
``users`` / ``shops`` / ``data_use_consents`` policies with no new grant. A shop with a
seller login stays refused.

Synthetic rows only; no downgrade, so it runs on the shared database.
"""

from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from juli_backend.services.consent import TERMS_SCOPES, has_consent
from juli_backend.services.ops import contract_shops
from tests.integration.two_tenant import RUNTIME_ROLE
from tests.support.postgres import requires_postgres

pytestmark = [requires_postgres]


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@asynccontextmanager
async def app_session():
    """A ``juli_app`` session (SET ROLE on the owner connection, like production's login)."""
    from juli_backend.core.config.runtime import async_database_url

    engine = create_async_engine(async_database_url(os.environ["DATABASE_URL"]))
    try:
        async with engine.connect() as conn:
            await conn.execute(text(f"SET ROLE {RUNTIME_ROLE}"))
            await conn.commit()
            session = AsyncSession(bind=conn, expire_on_commit=False)
            try:
                yield session
            finally:
                await session.close()
    finally:
        await engine.dispose()


async def test_the_app_role_creates_a_contract_shop_and_enables_its_consent():
    async with app_session() as session:
        shop = await contract_shops.create_contract_shop(
            session, shop_name=f"Synthetic {uuid.uuid4().hex[:6]}", shopee_shop_id=None, now=_now()
        )
        await session.commit()
        shop_id, owner_id = shop.id, shop.user_id

        state = await contract_shops.consent_state(session, shop_id, owner_id)
        assert state.contract_client is True and state.enabled is False

        granted = await contract_shops.enable_consent(
            session, shop_id, owner_id, staff_id=uuid.uuid4(), now=_now()
        )
        await session.commit()
        assert granted == list(TERMS_SCOPES)
        assert (await contract_shops.consent_state(session, shop_id, owner_id)).enabled
        from juli_backend.database.tenant_context import with_shop_scope

        async with with_shop_scope(session, shop_id):
            assert await has_consent(session, shop_id, "service")

        # "Tạo mã kết nối" as the app role, then the (empty) token list.
        issued = await contract_shops.issue_pairing_code(
            session, shop_id, owner_id, created_by=None, now=_now()
        )
        await session.commit()
        assert len(issued.code.replace("-", "")) == 10
        assert await contract_shops.list_tokens(session, shop_id, owner_id) == []


async def test_a_shop_whose_owner_signed_in_is_not_a_contract_client(two_tenants):
    tenant = two_tenants[0]
    async with app_session() as session:
        assert not await contract_shops.is_contract_client(session, tenant.shop_id, tenant.user_id)
        with pytest.raises(contract_shops.NotAContractShop):
            await contract_shops.enable_consent(
                session, tenant.shop_id, tenant.user_id, staff_id=None, now=_now()
            )
