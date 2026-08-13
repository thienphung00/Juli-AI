"""ADR-077 §6 gate suite — envelope-shape compatibility through the existing
outcome route (#1045, issue area 6).

Proves `GET /v1/workflow-outcomes/{approval_id}` (the "existing outcome
route" — #306/ADR-013, extended by #1044's ADR-077 decision 5 legacy-
envelope fill) still returns the stable 4-cadence envelope shape once a
GENUINE, pipeline-computed `impact_readings` row exists for an
`optimize_product_2` run — the row comes from actually running
`run_daily_impact_reader` against the gate suite's own golden-shaped
fixtures, never a hand-inserted row, so this proves the reading is
computable end-to-end and served through the real route, not merely that
the envelope-fill function can be called directly (already covered at the
unit level by `tests/unit/test_outcome_tracking_optimize_product_2.py`).

**Not covered here** (explicitly out of this slice, per the issue body):
the one real end-to-end reading for a sandbox run with a backdated T. That
waits for W3-A's `workflow_runs` table and runner — there is nothing to
attach a real workflow run to yet.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import ImpactReading, User
from juli_backend.services.operations.outcome_tracking import record_workflow_outcome
from juli_backend.workers.impact_reader.pipeline import run_daily_impact_reader
from tests.unit._impact_gate_support import (
    REFERENCE_DATE,
    add_control_siblings,
    add_daily_rows,
    anchor_gmv_per_order,
    make_execution,
    make_product,
    make_shop,
)

pytestmark = pytest.mark.asyncio

_T = REFERENCE_DATE - timedelta(days=7)
_SCALES = [Decimal("0.6"), Decimal("0.8"), Decimal("1.0"), Decimal("1.2"), Decimal("1.4")]


@pytest_asyncio.fixture
async def app(engine, session):
    from juli_backend.api.app import create_app
    from juli_backend.database import get_session

    application = create_app()

    async def _test_session():
        yield session

    application.dependency_overrides[get_session] = _test_session
    yield application
    application.dependency_overrides.clear()


@pytest_asyncio.fixture
async def envelope_shop(session: AsyncSession):
    return await make_shop(session, phone_suffix="1045envelope", name="Envelope Compat Shop")


@pytest_asyncio.fixture
async def auth_client(app, envelope_shop):
    from juli_backend.api.dependencies import get_active_shop
    from juli_backend.core.security import get_current_user

    fake_user = User(id=envelope_shop.user_id, phone="+8491045envelopeu")
    app.dependency_overrides[get_current_user] = lambda: fake_user
    app.dependency_overrides[get_active_shop] = lambda: envelope_shop

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


async def test_envelope_shape_survives_a_real_pipeline_computed_reading(
    session: AsyncSession, envelope_shop, auth_client
):
    gmv_base = anchor_gmv_per_order() * Decimal(8)
    product_id = "prod-envelope"
    series_start = _T - timedelta(days=14)
    series_end = _T + timedelta(days=14)

    await make_product(session, envelope_shop, product_id, created=_T - timedelta(days=60))
    execution = await make_execution(
        session,
        envelope_shop,
        tiktok_product_id=product_id,
        t=_T,
        approval_suffix="envelope",
    )
    await add_daily_rows(
        session,
        envelope_shop,
        product_id,
        series_start,
        series_end,
        gmv_base=gmv_base,
        shock_from=_T + timedelta(days=1),
        shock=Decimal("1.20"),
    )
    await add_control_siblings(
        session,
        envelope_shop,
        scales=_SCALES,
        gmv_base=gmv_base,
        start=series_start,
        end=series_end,
        name_prefix="ctrl-envelope",
        created=_T - timedelta(days=60),
    )

    outcome = await record_workflow_outcome(session, execution, execution_status="succeeded")
    await session.flush()

    # Before any reading lands, weekly/monthly must still show the legacy
    # "pending" placeholder — the un-filled envelope shape.
    before = await auth_client.get(f"/v1/workflow-outcomes/{outcome.approval_id}")
    assert before.status_code == 200
    cadences_before = {c["cadence"]: c for c in before.json()["data"]["cadences"]}
    assert cadences_before["weekly"]["readings"][0]["value"] == "pending"

    # Run the REAL pipeline — never hand-insert the ImpactReading row.
    result = await run_daily_impact_reader(session, REFERENCE_DATE)
    await session.commit()
    assert result.readings_written > 0

    stmt = select(ImpactReading).where(
        ImpactReading.tool_execution_id == execution.id, ImpactReading.metric == "gmv"
    )
    db_row = (await session.execute(stmt)).scalars().one()

    response = await auth_client.get(f"/v1/workflow-outcomes/{outcome.approval_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    data = body["data"]
    assert data["workflow_id"] == "optimize_product_2"

    cadence_ids = [c["cadence"] for c in data["cadences"]]
    assert cadence_ids == ["realtime", "daily", "weekly", "monthly"], (
        "the legacy envelope's cadence shape must stay exactly as it was before "
        "ADR-077 — only the weekly/monthly readings get filled in"
    )
    assert data["cadences"][0]["execution_status"] == "Tool execution completed successfully"
    assert "readings" in data["cadences"][1]  # daily cadence untouched, still present

    weekly = data["cadences"][2]
    assert weekly["cadence"] == "weekly"
    weekly_gmv = next(r for r in weekly["readings"] if r["label"] == "gmv")
    assert weekly_gmv["status"] == db_row.confidence
    assert Decimal(weekly_gmv["value"]) == db_row.incremental

    # monthly still pending — only the preliminary (T+7) window has elapsed.
    assert data["cadences"][3]["readings"][0]["value"] == "pending"
