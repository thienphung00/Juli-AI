"""``optimize_product_2`` vocabulary gap + legacy envelope fill from
``impact_readings`` (#1044, ADR-077 decision 5 / d.1).

``optimize_product_2`` is the system-wide workflow key (the Playbook uses
it too — see ``services/execution/tool_routing.py`` and
``services/scoring/kpi_catalog.py``), not ``optimize_product``.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import ImpactReading, Shop, ToolExecution, User
from juli_backend.services.operations.outcome_tracking import (
    VALIDATED_WORKFLOW_IDS,
    WORKFLOW_OUTCOME_SUCCESS_CRITERIA,
    build_workflow_outcome_metrics,
    load_workflow_outcome_metrics,
    record_workflow_outcome,
)


def test_workflow_outcome_success_criteria_has_optimize_product_2():
    assert "optimize_product_2" in WORKFLOW_OUTCOME_SUCCESS_CRITERIA
    criteria = WORKFLOW_OUTCOME_SUCCESS_CRITERIA["optimize_product_2"]
    assert criteria["metric"]
    assert criteria["period"]
    assert criteria["threshold"]


def test_optimize_product_2_is_a_validated_workflow_id():
    """Being present in the success-criteria dict is not enough on its own —
    ``build_workflow_outcome_metrics``/``extract_workflow_id`` gate on
    ``VALIDATED_WORKFLOW_IDS`` first, so a run against this workflow key must
    not be silently skipped as 'Unknown workflow_id'."""
    assert "optimize_product_2" in VALIDATED_WORKFLOW_IDS


def test_build_workflow_outcome_metrics_accepts_optimize_product_2():
    metrics = build_workflow_outcome_metrics(
        workflow_id="optimize_product_2",
        execution_status="succeeded",
        executed_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert metrics["workflow_id"] == "optimize_product_2"
    cadence_ids = [c["cadence"] for c in metrics["cadences"]]
    assert cadence_ids == ["realtime", "daily", "weekly", "monthly"]
    # realtime keeps its existing execution-status meaning — untouched by this change.
    assert metrics["cadences"][0]["execution_status"] == "Tool execution completed successfully"


@pytest_asyncio.fixture
async def shop(session: AsyncSession) -> Shop:
    user = User(id=uuid.uuid4(), phone="+84909991045")
    shop_row = Shop(
        id=uuid.uuid4(),
        user_id=user.id,
        shop_name="Envelope Fill Shop",
        tiktok_shop_id="tts_envelope_fill",
    )
    session.add_all([user, shop_row])
    await session.flush()
    return shop_row


@pytest_asyncio.fixture
async def execution(session: AsyncSession, shop: Shop) -> ToolExecution:
    row = ToolExecution(
        id=uuid.uuid4(),
        shop_id=shop.id,
        approval_id="approval-1044-envelope",
        tool_name="listing.optimize_product",
        payload_json=json.dumps(
            {
                "product_id": "prod-envelope",
                "workflow_id": "optimize_product_2",
                "price_update": {"price": "9.99"},
            }
        ),
        status="succeeded",
    )
    session.add(row)
    await session.flush()
    return row


def _reading(
    execution_id: uuid.UUID, *, kind: str, metric: str, confidence: str, incremental
) -> ImpactReading:
    return ImpactReading(
        id=uuid.uuid4(),
        run_id=None,
        tool_execution_id=execution_id,
        metric=metric,
        kind=kind,
        pre=Decimal("100.00"),
        post=Decimal("110.00"),
        expected=Decimal("105.00"),
        incremental=incremental,
        impact_pct=None,
        confidence=confidence,
        control_set_json="{}",
        computed_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_envelope_fills_weekly_from_preliminary_and_monthly_from_final(
    session: AsyncSession, shop: Shop, execution: ToolExecution
):
    outcome = await record_workflow_outcome(session, execution, execution_status="succeeded")
    await session.flush()

    metrics_before = await load_workflow_outcome_metrics(session, shop.id, outcome.approval_id)
    cadences_before = {c["cadence"]: c for c in metrics_before["cadences"]}
    assert cadences_before["weekly"]["readings"][0]["value"] == "pending"
    assert cadences_before["monthly"]["readings"][0]["value"] == "pending"

    session.add(
        _reading(
            execution.id,
            kind="preliminary",
            metric="gmv",
            confidence="trung_binh",
            incremental=Decimal("15.00"),
        )
    )
    await session.flush()

    metrics = await load_workflow_outcome_metrics(session, shop.id, outcome.approval_id)
    cadence_by_id = {c["cadence"]: c for c in metrics["cadences"]}

    weekly_reading = cadence_by_id["weekly"]["readings"][0]
    assert weekly_reading["label"] == "gmv"
    assert weekly_reading["status"] == "trung_binh"
    assert Decimal(weekly_reading["value"]) == Decimal("15.00")

    # monthly untouched (no final reading yet) — stays the pending placeholder.
    assert cadence_by_id["monthly"]["readings"][0]["value"] == "pending"
    # realtime keeps its existing execution-status meaning — untouched.
    assert cadence_by_id["realtime"]["execution_status"] == "Tool execution completed successfully"
    assert "readings" in cadence_by_id["daily"]

    session.add(
        _reading(
            execution.id,
            kind="final",
            metric="gmv",
            confidence="cao",
            incremental=Decimal("20.00"),
        )
    )
    await session.flush()

    metrics2 = await load_workflow_outcome_metrics(session, shop.id, outcome.approval_id)
    cadence_by_id2 = {c["cadence"]: c for c in metrics2["cadences"]}
    monthly_reading = cadence_by_id2["monthly"]["readings"][0]
    assert monthly_reading["status"] == "cao"
    assert Decimal(monthly_reading["value"]) == Decimal("20.00")
    # weekly stays filled from the earlier preliminary reading.
    assert Decimal(cadence_by_id2["weekly"]["readings"][0]["value"]) == Decimal("15.00")


@pytest.mark.asyncio
async def test_envelope_suppressed_reading_renders_as_na_not_a_fabricated_number(
    session: AsyncSession, shop: Shop, execution: ToolExecution
):
    outcome = await record_workflow_outcome(session, execution, execution_status="succeeded")
    session.add(
        _reading(
            execution.id,
            kind="preliminary",
            metric="gmv",
            confidence="suppressed",
            incremental=None,
        )
    )
    await session.flush()

    metrics = await load_workflow_outcome_metrics(session, shop.id, outcome.approval_id)
    cadence_by_id = {c["cadence"]: c for c in metrics["cadences"]}
    weekly_reading = cadence_by_id["weekly"]["readings"][0]
    assert weekly_reading["status"] == "suppressed"
    assert weekly_reading["value"] == "n/a"
