"""The Shopee KPI job on real Postgres, as ``juli_app`` (ADR-117 step 3).

The route and the CLI run the job in the app role: the daily metrics are read under
the shop's own scope (tenant-direct RLS on ``platform_daily_metrics``), the contract,
lever plan, targets and forecasts through ``ops_role`` (Ops-only tables, no
``juli_app`` grant). The run must pass both with no new grant; outside ``ops_role``
the app role still cannot read a forecast.

Synthetic rows only; no downgrade, so it runs on the shared database.
"""

from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.models.ingest import PlatformDailyMetric
from juli_backend.models.kpi_contracts import KpiContract, KpiForecast, KpiTarget, LeverPlan
from juli_backend.services import shopee_kpi
from juli_backend.services.ops import contract_shops, ops_role
from tests.integration.two_tenant import RUNTIME_ROLE
from tests.support.postgres import requires_postgres

pytestmark = [requires_postgres]

START = date(2026, 6, 20)


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


def _metric(shop_id, day, stream, segment, dataset, imp, clk, ordr, gmv) -> PlatformDailyMetric:
    now = _now()
    return PlatformDailyMetric(
        shop_id=shop_id,
        platform="shopee",
        dataset=dataset,
        day=day,
        item_id="",
        stream=stream,
        segment=segment,
        order_type="confirmed",
        impressions=Decimal(imp),
        clicks=Decimal(clk),
        orders=Decimal(ordr),
        gmv=Decimal(gmv),
        extra={},
        source="file",
        source_rank=2,
        source_version="synthetic",
        confidence="high",
        captured_at=now,
        updated_at=now,
    )


async def _seed(session: AsyncSession) -> uuid.UUID:
    shop = await contract_shops.create_contract_shop(
        session, shop_name=f"Synthetic KPI {uuid.uuid4().hex[:6]}", shopee_shop_id=None, now=_now()
    )
    await session.commit()
    async with with_shop_scope(session, shop.id):
        day = START - timedelta(120)
        while day <= START + timedelta(20):
            session.add_all(
                [
                    _metric(
                        shop.id,
                        day,
                        "product_card",
                        "all",
                        "traffic_overview",
                        2000,
                        60,
                        6,
                        600_000,
                    ),
                    _metric(
                        shop.id,
                        day,
                        "product_card",
                        "shop_page",
                        "traffic_overview",
                        300,
                        12,
                        1,
                        100_000,
                    ),
                    _metric(shop.id, day, "total", "all", "shop_overview", 0, 400, 20, 3_000_000),
                ]
            )
            day += timedelta(1)
        await session.flush()
    async with ops_role(session):
        session.add(
            KpiContract(
                shop_id=shop.id,
                contract_ref="SYNTHETIC",
                version=1,
                status="draft",
                measure_start=START,
                params={
                    "pass": 0.035,
                    "target": 0.05,
                    "flows": {
                        "the_san_pham": {"metrics": ["impressions", "ctr"]},
                        "trang_shop": {"metrics": ["impressions", "ctr"]},
                        "ca_shop": {"metrics": ["ctor", "aov"], "role": "theo_doi"},
                    },
                },
            )
        )
        session.add(
            LeverPlan(
                shop_id=shop.id,
                lever_key="W1",
                wave=1,
                name="Synthetic lever",
                starts_on=START,
                flow="the_san_pham",
                metric="ctr",
                low=Decimal("0"),
                high=Decimal("0.08"),
            )
        )
    await session.commit()
    return shop.id


async def test_the_app_role_runs_the_job_and_reads_it_back():
    async with app_session() as session:
        shop_id = await _seed(session)
        result = await shopee_kpi.run_shop_kpi(session, shop_id, now=_now())
        await session.commit()
        assert result.targets_written == 6
        assert result.as_of == START + timedelta(20)
        card = next(f for f in result.report.flows if f.flow == "the_san_pham")
        assert card.metrics[0].baseline == pytest.approx(2000)  # shop_page not added in

        rows = await shopee_kpi.latest_forecasts(session, shop_id)
        await session.commit()
        assert len([r for r in rows if r.method_version == "expected_move_v1"]) == 48
        assert {r.method_version for r in rows} == {"expected_move_v1", "flow_glm_v2"}
        assert {r.inputs_sha256 for r in rows} == {result.inputs_sha256}

        async with ops_role(session):
            targets = (
                (
                    await session.execute(
                        select(KpiTarget).where(KpiTarget.contract_id == result.contract_id)
                    )
                )
                .scalars()
                .all()
            )
        await session.commit()
        assert len(targets) == 6

        # A second run appends forecasts and leaves the targets alone.
        again = await shopee_kpi.run_shop_kpi(session, shop_id, now=_now())
        await session.commit()
        assert again.targets_written == 0

        _, report = await shopee_kpi.current_report(session, shop_id)
        await session.commit()
        assert report.acceptance.eligible == 4


async def test_the_app_role_alone_cannot_read_forecasts():
    async with app_session() as session:
        with pytest.raises(DBAPIError, match="permission denied") as refused:
            await session.execute(select(KpiForecast.id).limit(1))
        await session.rollback()
    assert "kpi_forecasts" in str(refused.value)
