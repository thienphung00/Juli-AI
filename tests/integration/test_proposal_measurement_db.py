"""ADR-118 §3 (D81): the proposal-results job on real Postgres, as ``juli_app``.

The job reads the item's daily rows and writes ``shop_proposal_results`` and the
proposal's status under the shop's own scope (tenant-direct RLS, ``juli_app`` has SELECT
and INSERT on results and UPDATE on proposals), and reads the contract's extra excluded
days through ``ops_role`` (Ops-only tables). It must pass with no new grant, and one shop
must never read or write another's rows.

Synthetic rows only; no downgrade, so it runs on the shared database.
"""

from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.models.ingest import PlatformDailyMetric
from juli_backend.models.kpi_contracts import KpiContract, KpiExclusion
from juli_backend.models.platform_data import PlatformItem
from juli_backend.models.shop_proposals import ShopProposal, ShopProposalResult
from juli_backend.services import shop_proposals as cycle
from juli_backend.services.ops import contract_shops, ops_role
from tests.integration.two_tenant import RUNTIME_ROLE
from tests.support.postgres import requires_postgres

pytestmark = [requires_postgres]

DAY0 = date(2026, 3, 10)
DAY0_AT_MIDNIGHT = datetime.combine(DAY0, datetime.min.time())
WEEKLY = [100, 104, 98, 102, 96, 110, 106, 100]  # clicks per day, oldest week first; max 110


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


def _metric(shop_id: uuid.UUID, day: date, clicks: int, item_id: str = "1001"):
    now = _now()
    return PlatformDailyMetric(
        shop_id=shop_id,
        platform="shopee",
        dataset="item_performance",
        day=day,
        item_id=item_id,
        stream="total",
        segment="all",
        order_type="confirmed",
        impressions=Decimal(2000),
        clicks=Decimal(clicks),
        extra={},
        source="file",
        source_rank=2,
        source_version="synthetic",
        confidence="high",
        captured_at=now,
        updated_at=now,
    )


async def _shop_with_executed_proposal(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    shop = await contract_shops.create_contract_shop(
        session,
        shop_name=f"Synthetic results {uuid.uuid4().hex[:6]}",
        shopee_shop_id=None,
        now=_now(),
    )
    await session.commit()
    now = _now()
    async with with_shop_scope(session, shop.id):
        session.add(
            PlatformItem(
                id=uuid.uuid4(),
                shop_id=shop.id,
                platform="shopee",
                item_id="1001",
                name="Synthetic item",
                source="file",
                source_rank=2,
                source_version="synthetic",
                captured_at=now,
                updated_at=now,
            )
        )
        for index, clicks in enumerate(WEEKLY):
            for offset in range(7):
                day = DAY0 - timedelta(7 * (8 - index)) + timedelta(offset)
                session.add(_metric(shop.id, day, clicks))
        for offset in range(1, 8):
            session.add(_metric(shop.id, DAY0 + timedelta(offset), 120))
        await session.flush()
        staff = uuid.uuid4()
        proposal = await cycle.create(
            session,
            shop.id,
            "shopee",
            cycle.ProposalDraft(
                cycle="2026-03 Đợt 1",
                kind="title",
                subject_type="item",
                item_id="1001",
                subject_label="Synthetic item",
                change_after={"text": "New"},
                reason="Synthetic reason.",
            ),
            staff_id=staff,
            now=now,
        )
        await cycle.send(session, proposal, now=now)
        await cycle.record_approval(
            session,
            proposal,
            decision="approved",
            channel="email",
            decided_at=now,
            now=now,
            recorded_by_staff_id=staff,
            evidence_ref="mail:synthetic",
        )
        execution = await cycle.record_execution(
            session,
            proposal,
            executed_at=DAY0_AT_MIDNIGHT,
            executor_role="client_representative",
            channel="ops",
            now=now,
            recorded_by_staff_id=staff,
        )
        await cycle.verify_execution(
            session,
            shop.id,
            execution.id,
            verified_how="export_readback",
            verified_state={},
            verified_at=now,
        )
    async with ops_role(session):
        contract = KpiContract(
            shop_id=shop.id,
            contract_ref="SYNTHETIC",
            version=1,
            status="draft",
            measure_start=DAY0,
            params={"pass": 0.035, "target": 0.05},
        )
        session.add(contract)
        await session.flush()
        # An extra excluded day inside the post week: Ops-only table, read through ops_role.
        session.add(
            KpiExclusion(contract_id=contract.id, day=DAY0 + timedelta(3), reason="synthetic")
        )
    await session.commit()
    return shop.id, proposal.id


async def test_the_app_role_measures_an_executed_proposal_and_stops_when_nothing_is_new():
    from juli_backend.services.shop_proposals import measurement

    async with app_session() as session:
        shop_id, proposal_id = await _shop_with_executed_proposal(session)

        counts = await measurement.measure_shop_proposals(session, shop_id, now=_now())
        await session.commit()
        assert (counts.written, counts.measured) == (3, 1)

        async with with_shop_scope(session, shop_id):
            rows = (
                await session.execute(
                    select(
                        ShopProposalResult.metric,
                        ShopProposalResult.verdict,
                        ShopProposalResult.detail,
                    ).where(ShopProposalResult.proposal_id == proposal_id)
                )
            ).all()
            status = await session.scalar(
                select(ShopProposal.status).where(ShopProposal.id == proposal_id)
            )
        await session.commit()
        assert status == "measured"
        by_metric = {m: (v, d) for m, v, d in rows}
        assert by_metric["ctr"][0] == "dat"
        assert by_metric["ctr"][1]["post_days_kept"] == 6  # the contract's extra excluded day

        again = await measurement.measure_shop_proposals(session, shop_id, now=_now())
        await session.commit()
        assert again.considered == 0  # measured proposals are no longer candidates


async def test_the_fleet_run_reaches_the_shop_and_another_shop_sees_nothing():
    from juli_backend.services.shop_proposals import measurement

    async with app_session() as session:
        shop_id, proposal_id = await _shop_with_executed_proposal(session)
        other_id, _ = await _shop_with_executed_proposal(session)

        @asynccontextmanager
        async def open_session():
            async with app_session() as fresh:
                yield fresh

        summary = await measurement.measure_all(open_session, now=_now())
        assert summary.failed == 0 and summary.counts.measured >= 2

        async with with_shop_scope(session, other_id):
            leaked = await session.scalar(
                select(ShopProposalResult.id).where(ShopProposalResult.proposal_id == proposal_id)
            )
        await session.commit()
        assert leaked is None
