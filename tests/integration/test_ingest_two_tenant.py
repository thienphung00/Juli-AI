"""Two-tenant proof for the P24 ingest tables as `juli_app` (fast track, migration 088).

The SQLite tests (`tests/unit/test_ingest_gateway.py`) prove the services and
routes. This proves the database agrees, under row-level security, as the
runtime role, with real commits:

- a pairing code is invisible with no context, visible to its own shop, and to
  a redeemer ONLY through the hash of that very code (the GUC helper);
- the redeem → token → ingest chain runs as `juli_app` with no other context,
  and the upsert (ON CONFLICT DO UPDATE) works under the policies;
- shop B sees none of A's codes, tokens, raw payloads, normalized rows or
  status, cannot write a row for A, and a token forged with B's prefix and A's
  secret resolves to nothing.
"""

from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import column, func, select, table, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.services import ingest as svc
from juli_backend.services.ingest import pairing
from tests.integration.two_tenant import RUNTIME_ROLE

requires_postgres = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").strip().startswith("postgresql"),
    reason="DATABASE_URL is not set to a Postgres instance",
)

pytestmark = [requires_postgres, pytest.mark.migration_heavy]

DAY = date(2026, 10, 11)
NOW = datetime(2026, 10, 12, 3, 0)
TABLES = (
    "ingest_pairing_codes",
    "ingest_tokens",
    "ingest_raw_payloads",
    "platform_daily_metrics",
    "ingest_dataset_status",
)


@asynccontextmanager
async def juli_app_session():
    """A `juli_app` session with NO tenant context; each test scopes what it needs."""
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
                await session.rollback()
                await session.close()
    finally:
        await engine.dispose()


@pytest.fixture(scope="module")
def shopee_tenants(owner_engine, two_tenants):
    with owner_engine.begin() as conn:
        for tenant in two_tenants:
            conn.execute(
                text("UPDATE public.shops SET platform = 'shopee' WHERE id = :id"),
                {"id": str(tenant.shop_id)},
            )
            # ADR-116 §4: the gateway accepts a post only from a shop with an open
            # `service` consent.
            conn.execute(
                text(
                    "INSERT INTO public.data_use_consents (id, shop_id, scope, method, "
                    " terms_version, evidence_ref, granted_by, granted_at) "
                    "VALUES (:id, :shop, 'service', 'contract_paper', 'v1', 'contract.pdf', "
                    " 'client', now())"
                ),
                {"id": str(uuid.uuid4()), "shop": str(tenant.shop_id)},
            )
    return two_tenants


def _body(sales: int) -> svc.IngestBody:
    return svc.IngestBody.model_validate(
        {
            "source": "extension",
            "source_version": "0.1.0",
            "captured_at": "2026-10-12T09:30:00+07:00",
            "period": {"start": DAY.isoformat(), "end": DAY.isoformat(), "granularity": "day"},
            "order_type": "confirmed",
            "rows": [
                {
                    "date": DAY.isoformat(),
                    "source": "psd_label_product_card",
                    "sales": sales,
                    "orders": 2.5,
                    "product_impressions": 1000,
                    "product_clicks": 50,
                    "ctr": 0.05,
                }
            ],
        }
    )


async def _count(session: AsyncSession, name: str, shop_id: uuid.UUID) -> int:
    shop_col = column("shop_id")
    stmt = (
        select(func.count())
        .select_from(table(name, shop_col, schema="public"))
        .where(shop_col == shop_id)
    )
    return int((await session.execute(stmt)).scalar_one())


async def _pair_and_ingest(shop_id: uuid.UUID, sales: int) -> str:
    async with juli_app_session() as session:
        from juli_backend.models.models import Shop

        async with with_shop_scope(session, shop_id):
            shop = await session.get(Shop, shop_id)
            assert shop is not None, "a shop must read its own row under its scope"
            code = (await svc.create_pairing_code(session, shop=shop, user_id=None, now=NOW)).code
        await session.commit()

    async with juli_app_session() as session:
        issued = await svc.redeem_pairing_code(
            session, code=code, platform="shopee", platform_shop_id=None, client_label=None, now=NOW
        )
        await session.commit()
        assert issued.shop_id == shop_id

    async with juli_app_session() as session:
        principal = await svc.resolve_token(session, issued.token, NOW)
        assert principal is not None and principal.shop_id == shop_id
        async with with_shop_scope(session, shop_id):
            await svc.ingest(
                session,
                shop_id=shop_id,
                platform="shopee",
                dataset="traffic_overview",
                body=_body(sales),
                token_id=principal.token_id,
                now=NOW,
            )
        await session.commit()
    return issued.token


async def test_ingest_isolation_proof_pairing_ingest_and_two_tenant_reads(shopee_tenants):
    tenant_a, tenant_b = shopee_tenants
    token_a = await _pair_and_ingest(tenant_a.shop_id, sales=100)
    await _pair_and_ingest(tenant_b.shop_id, sales=200)
    # The upsert path (ON CONFLICT DO UPDATE) under the UPDATE policy and grant.
    async with juli_app_session() as session:
        async with with_shop_scope(session, tenant_a.shop_id):
            await svc.ingest(
                session,
                shop_id=tenant_a.shop_id,
                platform="shopee",
                dataset="traffic_overview",
                body=_body(150),
                token_id=None,
                now=NOW,
            )
            gmv = (
                await session.execute(
                    text("SELECT gmv FROM public.platform_daily_metrics WHERE shop_id = :s"),
                    {"s": str(tenant_a.shop_id)},
                )
            ).scalar_one()
            assert int(gmv) == 150
        await session.commit()

    async with juli_app_session() as session:
        # No context: nothing at all.
        for table in TABLES:
            assert await _count(session, table, tenant_a.shop_id) == 0, table

        async with with_shop_scope(session, tenant_a.shop_id):
            for table in TABLES:
                assert await _count(session, table, tenant_a.shop_id) >= 1, table
                assert await _count(session, table, tenant_b.shop_id) == 0, table

        async with with_shop_scope(session, tenant_b.shop_id):
            for table in TABLES:
                assert await _count(session, table, tenant_a.shop_id) == 0, table
            # A token forged with B's prefix and A's secret resolves to nothing.
            secret = token_a.rsplit("_", 1)[1]
        forged = f"{pairing.TOKEN_PREFIX}{tenant_b.shop_id.hex}_{secret}"
        assert await svc.resolve_token(session, forged, NOW) is None
        assert await svc.resolve_token(session, token_a, NOW) is not None


async def test_ingest_isolation_proof_pairing_hash_reveals_only_that_code(shopee_tenants):
    tenant_a, tenant_b = shopee_tenants
    async with juli_app_session() as session:
        from juli_backend.models.models import Shop

        async with with_shop_scope(session, tenant_a.shop_id):
            shop = await session.get(Shop, tenant_a.shop_id)
            code = (
                await svc.create_pairing_code(
                    session, shop=shop, user_id=None, now=datetime.now(UTC).replace(tzinfo=None)
                )
            ).code
        await session.commit()

    async with juli_app_session() as session:
        count_sql = text("SELECT count(*) FROM public.ingest_pairing_codes")
        assert (await session.execute(count_sql)).scalar_one() == 0
        await session.execute(
            text("SELECT set_config('app.pairing_code_hash', :v, true)"),
            {"v": pairing.code_hash(code)},
        )
        assert (await session.execute(count_sql)).scalar_one() == 1
        await session.execute(
            text("SELECT set_config('app.pairing_code_hash', :v, true)"),
            {"v": pairing.code_hash("ZZZZZ-ZZZZZ")},
        )
        assert (await session.execute(count_sql)).scalar_one() == 0
        await session.rollback()

        # The hash GUC grants no write: B cannot claim A's code.
        async with with_shop_scope(session, tenant_b.shop_id):
            await session.execute(
                text("SELECT set_config('app.pairing_code_hash', :v, true)"),
                {"v": pairing.code_hash(code)},
            )
            claimed = await session.execute(
                text("UPDATE public.ingest_pairing_codes SET used_at = now() WHERE code_hash = :h"),
                {"h": pairing.code_hash(code)},
            )
            assert claimed.rowcount == 0
        await session.rollback()


async def test_ingest_isolation_proof_insert_for_another_shop_is_rejected(shopee_tenants):
    tenant_a, tenant_b = shopee_tenants
    async with juli_app_session() as session:
        async with with_shop_scope(session, tenant_b.shop_id):
            with pytest.raises(DBAPIError, match="row-level security"):
                await session.execute(
                    text(
                        "INSERT INTO public.platform_daily_metrics (id, shop_id, platform, "
                        " dataset, day, item_id, stream, segment, order_type, extra, source, "
                        " source_rank, source_version, confidence, captured_at, updated_at) "
                        "VALUES (:id, :shop, 'shopee', 'traffic_overview', :day, '', "
                        " 'product_card', 'all', 'confirmed', '{}'::jsonb, 'extension', 2, "
                        " '0.1.0', 'high', :now, :now)"
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "shop": str(tenant_a.shop_id),
                        "day": DAY - timedelta(days=1),
                        "now": NOW,
                    },
                )
        await session.rollback()
