"""`optimize_product_2` workflow vocabulary entry + legacy envelope fill from
`impact_readings` — ADR-077 decision 5 / d.1 (#1044).

**Why `_2`.** An earlier attempt used `"optimize_product"` — the *prompt
directory* name (see `services/execution/tool_routing.py` /
`services/scoring/kpi_catalog.py`), not the workflow key this envelope keys
on. This suite pins the correct key and explicitly asserts the wrong one is
absent, so a future edit cannot silently reintroduce that mismatch.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import ImpactReading, Shop, ToolExecution, User
from juli_backend.repositories.repos import WorkflowOutcomeRecordsRepo
from juli_backend.services.operations.outcome_tracking import (
    VALIDATED_WORKFLOW_IDS,
    WORKFLOW_DISPLAY_NAMES,
    WORKFLOW_OUTCOME_SUCCESS_CRITERIA,
    build_workflow_outcome_metrics,
    load_workflow_outcome_metrics,
)


def test_workflow_outcome_success_criteria_has_optimize_product_2_key():
    assert "optimize_product_2" in WORKFLOW_OUTCOME_SUCCESS_CRITERIA
    assert "optimize_product_2" in VALIDATED_WORKFLOW_IDS
    assert "optimize_product_2" in WORKFLOW_DISPLAY_NAMES


def test_the_prompt_directory_name_is_not_the_workflow_key():
    """Pins the exact mistake ADR-077 decision 5 flags by name: the prompt
    *directory* is `optimize_product`, the workflow *key* is
    `optimize_product_2` — they must never be conflated again."""
    assert "optimize_product" not in WORKFLOW_OUTCOME_SUCCESS_CRITERIA
    assert "optimize_product" not in VALIDATED_WORKFLOW_IDS


def test_build_workflow_outcome_metrics_accepts_optimize_product_2():
    metrics = build_workflow_outcome_metrics(
        workflow_id="optimize_product_2",
        execution_status="succeeded",
        executed_at=datetime(2026, 1, 15, tzinfo=UTC),
    )
    assert metrics["workflow_id"] == "optimize_product_2"
    cadence_ids = [c["cadence"] for c in metrics["cadences"]]
    assert cadence_ids == ["realtime", "daily", "weekly", "monthly"]
    weekly = next(c for c in metrics["cadences"] if c["cadence"] == "weekly")
    assert weekly["readings"][0]["value"] == "pending"


# ---------------------------------------------------------------------------
# Envelope fill: preliminary -> weekly, final -> monthly, from impact_readings.
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def shop(session: AsyncSession) -> Shop:
    user = User(id=uuid.uuid4(), phone="+84909991155")
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
        approval_id="approval-envelope-1",
        tool_name="listing.optimize_product",
        payload_json=json.dumps({"product_id": "tt-envelope-1", "price_update": {"price": "1"}}),
        status="succeeded",
    )
    session.add(row)
    await session.flush()
    return row


async def _record_outcome(session: AsyncSession, shop: Shop, execution: ToolExecution) -> None:
    metrics = build_workflow_outcome_metrics(
        workflow_id="optimize_product_2",
        execution_status="succeeded",
        executed_at=datetime(2026, 1, 15, tzinfo=UTC),
    )
    await WorkflowOutcomeRecordsRepo(session).create(
        shop_id=shop.id,
        approval_id=execution.approval_id,
        execution_id=execution.id,
        workflow_id="optimize_product_2",
        execution_status="succeeded",
        metrics_json=json.dumps(metrics),
        executed_at=datetime(2026, 1, 15, tzinfo=UTC),
    )


async def test_envelope_stays_pending_with_no_impact_readings_yet(
    session: AsyncSession, shop: Shop, execution: ToolExecution
):
    await _record_outcome(session, shop, execution)
    await session.commit()

    metrics = await load_workflow_outcome_metrics(session, shop.id, execution.approval_id)
    weekly = next(c for c in metrics["cadences"] if c["cadence"] == "weekly")
    assert weekly["readings"][0]["value"] == "pending"


async def test_preliminary_reading_fills_weekly_and_final_fills_monthly(
    session: AsyncSession, shop: Shop, execution: ToolExecution
):
    await _record_outcome(session, shop, execution)
    session.add(
        ImpactReading(
            id=uuid.uuid4(),
            run_id=None,
            tool_execution_id=execution.id,
            metric="gmv",
            kind="preliminary",
            pre=Decimal("100.00"),
            post=Decimal("120.00"),
            expected=Decimal("100.00"),
            incremental=Decimal("20.00"),
            impact_pct=Decimal("0.200000"),
            confidence="thap",
            control_set_json="{}",
            computed_at=datetime(2026, 1, 22, tzinfo=UTC),
        )
    )
    session.add(
        ImpactReading(
            id=uuid.uuid4(),
            run_id=None,
            tool_execution_id=execution.id,
            metric="gmv",
            kind="final",
            pre=Decimal("100.00"),
            post=Decimal("130.00"),
            expected=Decimal("100.00"),
            incremental=Decimal("30.00"),
            impact_pct=Decimal("0.300000"),
            confidence="trung_binh",
            control_set_json="{}",
            computed_at=datetime(2026, 1, 29, tzinfo=UTC),
        )
    )
    await session.commit()

    metrics = await load_workflow_outcome_metrics(session, shop.id, execution.approval_id)
    cadences = {c["cadence"]: c for c in metrics["cadences"]}

    weekly_reading = cadences["weekly"]["readings"][0]
    assert weekly_reading["label"] == "gmv"
    assert weekly_reading["value"] == "20.00"
    assert weekly_reading["status"] == "thap"

    monthly_reading = cadences["monthly"]["readings"][0]
    assert monthly_reading["label"] == "gmv"
    assert monthly_reading["value"] == "30.00"
    assert monthly_reading["status"] == "trung_binh"

    # realtime and daily are untouched by this fill.
    assert cadences["realtime"]["execution_status"] == "Tool execution completed successfully"
    assert cadences["daily"]["readings"][0]["value"] == "pending"


async def test_suppressed_or_confounded_reading_renders_as_na_not_a_fabricated_number(
    session: AsyncSession, shop: Shop, execution: ToolExecution
):
    session.add(
        ImpactReading(
            id=uuid.uuid4(),
            run_id=None,
            tool_execution_id=execution.id,
            metric="gmv",
            kind="preliminary",
            pre=None,
            post=None,
            expected=None,
            incremental=None,
            impact_pct=None,
            confidence="suppressed",
            control_set_json="{}",
            computed_at=datetime(2026, 1, 22, tzinfo=UTC),
        )
    )
    await _record_outcome(session, shop, execution)
    await session.commit()

    metrics = await load_workflow_outcome_metrics(session, shop.id, execution.approval_id)
    weekly = next(c for c in metrics["cadences"] if c["cadence"] == "weekly")
    assert weekly["readings"][0]["value"] == "n/a"
    assert weekly["readings"][0]["status"] == "suppressed"
