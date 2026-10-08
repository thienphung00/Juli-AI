"""Two-tenant proof for stored ADR-109 metric rankings as `juli_app` (fast track AC-8.1).

The SQLite tests in `tests/unit/test_shop_metric_rankings_daily.py` prove the
job and the route filter on the caller's shop. This proves the database agrees,
under row-level security, as the runtime role, with real commits:

- the job for shop A stores A's rankings and nothing for B;
- `shop_metric_rankings` is invisible across tenants and refuses a
  cross-tenant write;
- the read service under B's scope never returns A's ranking.
"""

from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from juli_backend.services.shop_diagnosis.channels import Channel
from juli_backend.services.shop_diagnosis.rankings import Metric
from juli_backend.services.shop_diagnosis_daily import (
    build_and_store_shop_diagnosis,
    latest_metric_ranking,
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
                    "merchant": f"rank-merchant-{label}-{tenant.shop_id.hex[:6]}",
                    "cipher": f"rank-cipher-{label}",
                    "id": str(tenant.fresh_credential_id),
                },
            )
    return tenant_a, tenant_b


def _count(owner_engine, shop_id: uuid.UUID) -> int:
    with owner_engine.connect() as conn:
        return conn.execute(
            text("SELECT COUNT(*) FROM public.shop_metric_rankings WHERE shop_id = :shop"),
            {"shop": str(shop_id)},
        ).scalar_one()


@pytest.mark.asyncio
async def test_the_job_for_one_shop_stores_only_that_shops_rankings(
    owner_engine, tenants, tmp_path, monkeypatch
):
    monkeypatch.delenv("TIKTOK_APP_KEY", raising=False)
    monkeypatch.delenv("TIKTOK_APP_SECRET", raising=False)
    tenant_a, tenant_b = tenants

    result = await build_and_store_shop_diagnosis(
        session_factory=committing_juli_app_session,
        shop_id=tenant_a.shop_id,
        app_key="app-key",
        app_secret="app-secret",
        create_resources=lambda _config: FakeTikTokReadResources(),
        now=NOW,
        tmp_root=tmp_path,
        sleep_s=0,
        backoff_sleep=lambda _s: None,
        force=True,
    )

    assert result.built
    assert _count(owner_engine, tenant_a.shop_id) == len(result.metric_rankings) == 13
    assert _count(owner_engine, tenant_b.shop_id) == 0

    async with committing_juli_app_session(shop_id=tenant_b.shop_id) as session:
        assert (
            await latest_metric_ranking(session, tenant_a.shop_id, Channel.PRODUCT_CARD, Metric.CTR)
            is None
        )
    async with committing_juli_app_session(shop_id=tenant_a.shop_id) as session:
        stored = await latest_metric_ranking(
            session, tenant_a.shop_id, Channel.PRODUCT_CARD, Metric.CTR
        )
    assert stored is not None and stored.as_of == END
    assert stored.ranking["stream_label"] == "Thẻ sản phẩm của người bán"


@pytest.mark.asyncio
async def test_rankings_are_invisible_and_unwritable_across_tenants(owner_engine, tenants):
    tenant_a, tenant_b = tenants
    with owner_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO public.shop_metric_rankings "
                "(id, shop_id, end_date, stream, metric, ranking, built_at) "
                "VALUES (:id, :shop, '2026-01-01', 'shop_tab', 'aov', '{}', now()) "
                "ON CONFLICT DO NOTHING"
            ),
            {"id": str(uuid.uuid4()), "shop": str(tenant_a.shop_id)},
        )

    async with committing_juli_app_session(shop_id=tenant_b.shop_id) as session:
        visible = (
            await session.execute(text("SELECT shop_id FROM public.shop_metric_rankings"))
        ).all()
        assert {row[0] for row in visible} <= {tenant_b.shop_id}

        with pytest.raises(Exception, match="row-level security"):
            await session.execute(
                text(
                    "INSERT INTO public.shop_metric_rankings "
                    "(id, shop_id, end_date, stream, metric, ranking, built_at) "
                    "VALUES (:id, :shop, '2026-01-02', 'shop_tab', 'aov', '{}', now())"
                ),
                {"id": str(uuid.uuid4()), "shop": str(tenant_a.shop_id)},
            )
        await session.rollback()


def test_unknown_streams_and_metrics_are_refused_by_the_table(owner_engine, tenants):
    tenant_a, _ = tenants
    with pytest.raises(Exception, match="ck_shop_metric_rankings_metric"):
        with owner_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO public.shop_metric_rankings "
                    "(id, shop_id, end_date, stream, metric, ranking, built_at) "
                    "VALUES (:id, :shop, '2026-01-03', 'shop_tab', 'gmv', '{}', now())"
                ),
                {"id": str(uuid.uuid4()), "shop": str(tenant_a.shop_id)},
            )
