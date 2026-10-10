"""Two-tenant proof for the P14-C cost tables as `juli_app` (migration 081).

The SQLite tests (`tests/unit/test_order_costs.py`) prove the store filters on
the caller's shop. This proves the database agrees, under row-level security,
as the runtime role, with real commits:

- price-detail, finance and fetch rows stored under shop A are invisible from B;
- B can insert none of them for A, and B's idempotent "replace this order's
  rows" (a DELETE + INSERT) for the same order id removes nothing of A's.
"""

from __future__ import annotations

import json
import os
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from juli_backend.services import order_costs
from tests.integration.two_tenant import RUNTIME_ROLE

requires_postgres = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").strip().startswith("postgresql"),
    reason="DATABASE_URL is not set to a Postgres instance",
)

pytestmark = [requires_postgres, pytest.mark.migration_heavy]

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/tiktok_order_costs"
ORDER_ID = "5793990727963214852"
NOW = datetime(2026, 10, 10, 9, 0, tzinfo=UTC).replace(tzinfo=None)
TABLES = ("order_price_details", "order_finance_transactions", "order_cost_fetches")


def _data(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))["response"]["data"]


@asynccontextmanager
async def committing_juli_app_session(shop_id: uuid.UUID):
    from juli_backend.core.config.runtime import async_database_url

    engine = create_async_engine(async_database_url(os.environ["DATABASE_URL"]))
    try:
        async with engine.connect() as conn:
            await conn.execute(text(f"SET ROLE {RUNTIME_ROLE}"))
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


def _count(owner_engine, table: str, shop_id: uuid.UUID) -> int:
    with owner_engine.connect() as conn:
        return conn.execute(
            text(f"SELECT COUNT(*) FROM public.{table} WHERE shop_id = :shop"),  # nosec B608
            {"shop": str(shop_id)},
        ).scalar_one()


async def _write_all(session, shop_id: uuid.UUID, *, with_skus: bool) -> None:
    skus = {
        "577958834469570826": ("1729700293904534135", "1729700293904403063"),
        "577958834469570827": ("1729700293904534135", "1729700293904403063"),
        "577958834469570828": ("1729700293904534999", "1729700293904403999"),
    }
    price = order_costs.parse_price_detail(
        _data("price_detail_response.json"), skus if with_skus else {}
    )
    finance = order_costs.parse_statement_transactions(
        _data("statement_transactions_response.json")
    )
    await order_costs.replace_price_rows(session, shop_id, ORDER_ID, price, fetched_at=NOW)
    await order_costs.replace_finance_rows(session, shop_id, ORDER_ID, finance, fetched_at=NOW)
    await order_costs.record_price_fetch(
        session, shop_id, ORDER_ID, order_update_time=NOW, fetched_at=NOW
    )
    await order_costs.record_finance_fetch(
        session, shop_id, ORDER_ID, settled=finance.settled, fetched_at=NOW
    )


@pytest.mark.asyncio
async def test_cost_rows_are_invisible_and_unwritable_across_tenants(owner_engine, two_tenants):
    tenant_a, tenant_b = two_tenants

    async with committing_juli_app_session(tenant_a.shop_id) as session:
        await _write_all(session, tenant_a.shop_id, with_skus=True)
    async with committing_juli_app_session(tenant_a.shop_id) as session:
        # Idempotent: the same read again leaves the same rows.
        await _write_all(session, tenant_a.shop_id, with_skus=True)
    a_counts = {t: _count(owner_engine, t, tenant_a.shop_id) for t in TABLES}
    assert a_counts == {
        "order_price_details": 3,
        "order_finance_transactions": 3,
        "order_cost_fetches": 1,
    }

    async with committing_juli_app_session(tenant_b.shop_id) as session:
        for table in TABLES:
            visible = (await session.execute(text(f"SELECT shop_id FROM public.{table}"))).all()  # nosec B608
            assert {row[0] for row in visible} <= {tenant_b.shop_id}, table
        assert (await order_costs.sku_deductions(session, tenant_a.shop_id, since=NOW)) == {}, (
            "A's rows are invisible from B"
        )
        with pytest.raises(Exception, match="row-level security"):
            await _write_all(session, tenant_a.shop_id, with_skus=True)
        await session.rollback()
        # B's own read of the same order id replaces only B's rows.
        await _write_all(session, tenant_b.shop_id, with_skus=False)

    assert {t: _count(owner_engine, t, tenant_a.shop_id) for t in TABLES} == a_counts
    assert _count(owner_engine, "order_price_details", tenant_b.shop_id) == 1
    assert _count(owner_engine, "order_finance_transactions", tenant_b.shop_id) == 3
