"""ImpactReading model — ADR-077 decision 5, I9 (#1040).

Structural checks run without a database at all; behavioral checks use the
sqlite in-memory `session`/`engine` fixtures from `tests/unit/conftest.py` —
SQLite enforces CHECK and UNIQUE constraints unconditionally (unlike foreign
keys, which need a pragma this test suite does not enable), which is exactly
what the acceptance criteria for this table need proven: a duplicate
`(tool_execution_id, metric, kind)` raises, and an unknown `kind`/`confidence`
value is rejected rather than stored.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import ImpactReading, Shop, ToolExecution, User

# ---------------------------------------------------------------------------
# Structural checks — no database needed.
# ---------------------------------------------------------------------------


def test_impact_readings_table_columns():
    mapper = sa_inspect(ImpactReading)
    column_names = {c.key for c in mapper.columns}
    assert column_names == {
        "id",
        "run_id",
        "tool_execution_id",
        "metric",
        "kind",
        "pre",
        "post",
        "expected",
        "incremental",
        "impact_pct",
        "confidence",
        "control_set_json",
        "computed_at",
    }


def test_run_id_has_no_foreign_key_but_tool_execution_id_does():
    """ADR-077 d.5 known dependency constraint: `workflow_runs` does not exist
    yet (W3-A/ADR-073), so `run_id` must be a plain nullable UUID column with
    no FK, while `tool_execution_id` — which targets the pre-existing
    `tool_executions` table — does get a real FK."""
    table = ImpactReading.__table__
    assert table.c.run_id.foreign_keys == set()
    assert table.c.run_id.nullable is True

    execution_fks = table.c.tool_execution_id.foreign_keys
    assert len(execution_fks) == 1
    fk = next(iter(execution_fks))
    assert fk.target_fullname == "tool_executions.id"
    assert table.c.tool_execution_id.nullable is False


def test_numeric_precisions_match_analytics_performance_interval():
    """Do not invent new precisions — reuse exactly what
    `AnalyticsPerformanceInterval` already established: Numeric(18, 2) for the
    gmv-like absolute reading columns, Numeric(10, 6) for the impact_pct
    ratio (always a rate regardless of the underlying metric)."""
    table = ImpactReading.__table__
    for column_name in ("pre", "post", "expected", "incremental"):
        col_type = table.c[column_name].type
        assert (col_type.precision, col_type.scale) == (18, 2), column_name

    impact_pct_type = table.c["impact_pct"].type
    assert (impact_pct_type.precision, impact_pct_type.scale) == (10, 6)


def test_unique_constraint_on_execution_metric_kind():
    table = ImpactReading.__table__
    unique_constraints = [
        c for c in table.constraints if c.__class__.__name__ == "UniqueConstraint"
    ]
    assert len(unique_constraints) == 1
    constraint = unique_constraints[0]
    assert [c.name for c in constraint.columns] == ["tool_execution_id", "metric", "kind"]


def test_check_constraints_present_for_kind_and_confidence():
    table = ImpactReading.__table__
    check_constraints = {
        c.name: str(c.sqltext)
        for c in table.constraints
        if c.__class__.__name__ == "CheckConstraint"
    }
    assert "ck_impact_readings_kind" in check_constraints
    assert "ck_impact_readings_confidence" in check_constraints
    kind_sql = check_constraints["ck_impact_readings_kind"]
    for value in ("preliminary", "final"):
        assert value in kind_sql
    confidence_sql = check_constraints["ck_impact_readings_confidence"]
    for value in ("cao", "trung_binh", "thap", "suppressed", "confounded"):
        assert value in confidence_sql


def test_control_set_json_is_required():
    table = ImpactReading.__table__
    assert table.c.control_set_json.nullable is False


# ---------------------------------------------------------------------------
# Behavioral checks — sqlite in-memory session (CHECK/UNIQUE enforced).
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def shop(session: AsyncSession) -> Shop:
    user = User(id=uuid.uuid4(), phone="+84909991122")
    shop_row = Shop(
        id=uuid.uuid4(),
        user_id=user.id,
        shop_name="Impact Reading Shop",
        tiktok_shop_id="tts_impact_reading",
    )
    session.add_all([user, shop_row])
    await session.flush()
    return shop_row


@pytest_asyncio.fixture
async def tool_execution(session: AsyncSession, shop: Shop) -> ToolExecution:
    execution = ToolExecution(
        id=uuid.uuid4(),
        shop_id=shop.id,
        approval_id="approval-impact-1040",
        tool_name="optimize_product_2",
        payload_json="{}",
        status="completed",
    )
    session.add(execution)
    await session.flush()
    return execution


def _reading(tool_execution_id: uuid.UUID, **overrides) -> ImpactReading:
    fields = dict(
        id=uuid.uuid4(),
        run_id=None,
        tool_execution_id=tool_execution_id,
        metric="gmv",
        kind="preliminary",
        pre=Decimal("100.00"),
        post=Decimal("120.00"),
        expected=Decimal("105.00"),
        incremental=Decimal("15.00"),
        impact_pct=Decimal("0.142857"),
        confidence="trung_binh",
        control_set_json='{"control_ids": [], "correlations": [], "windows": {}}',
        computed_at=datetime.now(UTC),
    )
    fields.update(overrides)
    return ImpactReading(**fields)


@pytest.mark.asyncio
async def test_insert_valid_reading_round_trips(session: AsyncSession, tool_execution):
    reading = _reading(tool_execution.id)
    session.add(reading)
    await session.flush()

    fetched = await session.get(ImpactReading, reading.id)
    assert fetched is not None
    assert fetched.metric == "gmv"
    assert fetched.kind == "preliminary"
    assert fetched.confidence == "trung_binh"
    assert fetched.run_id is None


@pytest.mark.asyncio
async def test_duplicate_execution_metric_kind_raises(session: AsyncSession, tool_execution):
    """Acceptance criterion: inserting a duplicate raises — this is what makes
    the daily impact-reader beat task idempotent."""
    session.add(_reading(tool_execution.id))
    await session.flush()

    session.add(_reading(tool_execution.id))
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_same_execution_different_kind_is_allowed(session: AsyncSession, tool_execution):
    """preliminary -> final upgrade in place is the designed flow (ADR-077 d.5)."""
    session.add(_reading(tool_execution.id, kind="preliminary"))
    await session.flush()

    session.add(_reading(tool_execution.id, kind="final", id=uuid.uuid4()))
    await session.flush()


@pytest.mark.asyncio
async def test_unknown_kind_is_rejected(session: AsyncSession, tool_execution):
    session.add(_reading(tool_execution.id, kind="in_progress"))
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_unknown_confidence_is_rejected(session: AsyncSession, tool_execution):
    session.add(_reading(tool_execution.id, confidence="high"))
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_every_documented_confidence_value_is_accepted(session: AsyncSession, tool_execution):
    for i, value in enumerate(("cao", "trung_binh", "thap", "suppressed", "confounded")):
        reading = _reading(
            tool_execution.id,
            id=uuid.uuid4(),
            metric=f"metric_{i}",
            confidence=value,
        )
        session.add(reading)
    await session.flush()


@pytest.mark.asyncio
async def test_both_documented_kind_values_are_accepted(session: AsyncSession, tool_execution):
    for i, value in enumerate(("preliminary", "final")):
        reading = _reading(
            tool_execution.id,
            id=uuid.uuid4(),
            metric=f"kind_metric_{i}",
            kind=value,
        )
        session.add(reading)
    await session.flush()
