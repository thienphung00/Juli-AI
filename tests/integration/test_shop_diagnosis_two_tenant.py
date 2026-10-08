"""Two-tenant proof for stored shop diagnosis reports as `juli_app` (fast track AC-7.1, AC-7.2).

The SQLite tests in `tests/unit/test_shop_diagnosis_daily.py` prove the job and
the route filter on the caller's shop. This proves the database agrees, under
row-level security, as the runtime role, with real commits:

- the job for shop A, resolving A's own credential, stores A's report and
  nothing for B;
- `shop_diagnosis_reports` is invisible across tenants and refuses a
  cross-tenant write;
- the read service under B's scope never returns A's report.
"""

from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from juli_backend.services.shop_diagnosis_daily import (
    build_and_store_shop_diagnosis,
    latest_shop_diagnosis,
)
from tests.integration.two_tenant import RUNTIME_ROLE
from tests.support.shop_diagnosis import FakeTikTokReadResources

requires_postgres = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").strip().startswith("postgresql"),
    reason="DATABASE_URL is not set to a Postgres instance",
)

pytestmark = [requires_postgres, pytest.mark.migration_heavy]

NOW = datetime(2026, 10, 7, 10, 0, tzinfo=UTC)
END = date(2026, 10, 6)


@asynccontextmanager
async def committing_juli_app_session(shop_id: uuid.UUID | None = None):
    """A `juli_app` session whose commits really commit (see the P1-B two-tenant test)."""
    from juli_backend.core.config.runtime import async_database_url

    engine = create_async_engine(async_database_url(os.environ["DATABASE_URL"]))
    try:
        async with engine.connect() as conn:
            await conn.execute(text(f"SET ROLE {RUNTIME_ROLE}"))
            if shop_id is not None:
                await conn.execute(
                    text("SELECT set_config('app.current_shop_id', :v, false)").bindparams(
                        v=str(shop_id)
                    )
                )
            await conn.commit()
            session = AsyncSession(bind=conn, expire_on_commit=False)
            try:
                yield session
                await session.commit()
            finally:
                await session.close()
    finally:
        await engine.dispose()


@pytest.fixture(scope="module")
def tenants(owner_engine, two_tenants):
    """Give each seeded tenant a SELLER_CONNECT read credential."""
    tenant_a, tenant_b = two_tenants
    with owner_engine.begin() as conn:
        for tenant, label in ((tenant_a, "a"), (tenant_b, "b")):
            conn.execute(
                text(
                    "UPDATE public.tiktok_credentials "
                    "SET capability = 'seller_connect', merchant_authorization_id = :merchant, "
                    "    shop_cipher = :cipher "
                    "WHERE id = :id"
                ),
                {
                    "merchant": f"diag-merchant-{label}-{tenant.shop_id.hex[:6]}",
                    "cipher": f"diag-cipher-{label}",
                    "id": str(tenant.fresh_credential_id),
                },
            )
    return tenant_a, tenant_b


def _count(owner_engine, shop_id: uuid.UUID) -> int:
    with owner_engine.connect() as conn:
        return conn.execute(
            text("SELECT COUNT(*) FROM public.shop_diagnosis_reports WHERE shop_id = :shop"),
            {"shop": str(shop_id)},
        ).scalar_one()


@pytest.mark.asyncio
async def test_the_job_for_one_shop_stores_only_that_shops_report(
    owner_engine, tenants, tmp_path, monkeypatch
):
    monkeypatch.delenv("TIKTOK_APP_KEY", raising=False)
    monkeypatch.delenv("TIKTOK_APP_SECRET", raising=False)
    tenant_a, tenant_b = tenants
    configs = []

    def create_resources(config):
        configs.append(config)
        return FakeTikTokReadResources()

    result = await build_and_store_shop_diagnosis(
        session_factory=committing_juli_app_session,
        shop_id=tenant_a.shop_id,
        app_key="app-key",
        app_secret="app-secret",
        create_resources=create_resources,
        now=NOW,
        tmp_root=tmp_path,
        sleep_s=0,
        backoff_sleep=lambda _s: None,
    )

    assert result.built
    assert configs[0].merchant_auth_id.startswith("diag-merchant-a-")
    assert _count(owner_engine, tenant_a.shop_id) == 2  # 60d + 30d
    assert _count(owner_engine, tenant_b.shop_id) == 0

    async with committing_juli_app_session(shop_id=tenant_b.shop_id) as session:
        assert await latest_shop_diagnosis(session, tenant_a.shop_id) is None
        assert await latest_shop_diagnosis(session, tenant_b.shop_id) is None
    async with committing_juli_app_session(shop_id=tenant_a.shop_id) as session:
        stored = await latest_shop_diagnosis(session, tenant_a.shop_id)
    assert stored is not None and stored.as_of == END


@pytest.mark.asyncio
async def test_reports_are_invisible_and_unwritable_across_tenants(owner_engine, tenants):
    tenant_a, tenant_b = tenants
    with owner_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO public.shop_diagnosis_reports "
                "(id, shop_id, end_date, ranking, report, built_at) "
                "VALUES (:id, :shop, '2026-01-01', '60d', '{}', now()) "
                "ON CONFLICT DO NOTHING"
            ),
            {"id": str(uuid.uuid4()), "shop": str(tenant_a.shop_id)},
        )

    async with committing_juli_app_session(shop_id=tenant_b.shop_id) as session:
        visible = (
            await session.execute(text("SELECT shop_id FROM public.shop_diagnosis_reports"))
        ).all()
        assert {row[0] for row in visible} <= {tenant_b.shop_id}

        with pytest.raises(Exception, match="row-level security"):
            await session.execute(
                text(
                    "INSERT INTO public.shop_diagnosis_reports "
                    "(id, shop_id, end_date, ranking, report, built_at) "
                    "VALUES (:id, :shop, '2026-01-02', '60d', '{}', now())"
                ),
                {"id": str(uuid.uuid4()), "shop": str(tenant_a.shop_id)},
            )
        await session.rollback()
