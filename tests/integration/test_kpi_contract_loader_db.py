"""Loading a contract appendix on real Postgres, as ``juli_app`` (ADR-117 §4, G7).

The loader writes ``kpi_contracts`` through ``ops_role`` like the KPI job reads it. Same
file twice is a no-op, a status change updates in place, changed terms insert version
n+1 and supersede n, and the KPI job then reads the new version.

Synthetic rows only; no downgrade, so it runs on the shared database.
"""

from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from juli_backend.models.kpi_contracts import KpiContract
from juli_backend.services.ops import contract_shops, ops_role
from juli_backend.services.shopee_kpi.contracts import (
    OUTCOME_CREATED,
    OUTCOME_NEW_VERSION,
    OUTCOME_STATUS_UPDATED,
    OUTCOME_UNCHANGED,
    ContractFileError,
    load_contract,
    parse_contract_file,
)
from juli_backend.services.shopee_kpi.job import current_contract
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


def _file(target: float = 0.05):
    return parse_contract_file(
        {
            "contract": "SYN/LOADER (synthetic)",
            "measure_start": "2099-01-01",
            "pass": 0.03,
            "target": target,
            "flows": {"the_san_pham": {"metrics": ["impressions", "ctr"]}},
        }
    )


async def test_loading_is_idempotent_and_changed_terms_make_a_new_version():
    async with app_session() as session:
        shop = await contract_shops.create_contract_shop(
            session,
            shop_name=f"Synthetic loader {uuid.uuid4().hex[:6]}",
            shopee_shop_id=None,
            now=_now(),
        )
        await session.commit()
        shop_id = shop.id  # the rollback below expires `shop`

        first = await load_contract(session, shop_id, _file(), status="sent")
        await session.commit()
        assert (first.outcome, first.version) == (OUTCOME_CREATED, 1)

        again = await load_contract(session, shop_id, _file(), status="sent")
        await session.commit()
        assert (again.outcome, again.contract_id) == (OUTCOME_UNCHANGED, first.contract_id)

        signed = await load_contract(
            session, shop_id, _file(), status="signed", signed_on=date(2099, 1, 2)
        )
        await session.commit()
        assert (signed.outcome, signed.version) == (OUTCOME_STATUS_UPDATED, 1)

        with pytest.raises(ContractFileError, match="email-ref"):
            await load_contract(session, shop_id, _file(target=0.06), status="signed")
        await session.rollback()

        second = await load_contract(
            session, shop_id, _file(target=0.06), status="signed", email_ref="2099-01-03 Phụ lục"
        )
        await session.commit()
        assert (second.outcome, second.version) == (OUTCOME_NEW_VERSION, 2)
        assert second.superseded_id == first.contract_id

        async with ops_role(session):
            rows = (
                (
                    await session.execute(
                        select(KpiContract.version, KpiContract.status, KpiContract.signed_on)
                        .where(KpiContract.shop_id == shop_id)
                        .order_by(KpiContract.version)
                    )
                )
                .tuples()
                .all()
            )
        await session.commit()
        assert rows == [(1, "superseded", date(2099, 1, 2)), (2, "signed", None)]

        current = await current_contract(session, shop_id)
        await session.commit()
        assert current.id == second.contract_id
