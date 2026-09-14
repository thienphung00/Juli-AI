"""The impact reader stamps ``impact_readings.run_id`` (#1858, W8-F / P10-7,
parent PRD #1652, ADR-077 decision 5).

``workers/impact_reader/queries.py::build_reading_row`` used to hardcode
``run_id=None`` on every row it built, even though its only caller already
holds the owning ``ToolExecution`` (and therefore ``workflow_run_id``) in
scope. This is the first slice that ever writes a non-``NULL`` value into
that column, which means migration 034's FK to ``workflow_runs.id`` is
exercised on INSERT for the first time -- a real Postgres runtime path, not a
formality.

**Real Postgres, real role, real pipeline -- never a shortcut.** Every
assertion here drives the REAL ``run_daily_impact_reader`` and reads the
persisted row back from the database, never a hand-built ``ImpactReading``
and never the value the test itself passed in. The reader runs as
``juli_app`` with RLS enabled (``tests.support.postgres.
juli_app_async_sessionmaker``) -- an owner connection is exempt from every
row policy, so an RLS/FK claim made on one would not be a claim at all.
Seeding (and the plain read-backs that are not themselves under test) uses
an owner connection, per that same module's own documented convention:
seeding is set-up, not the thing under test, and a read-back assertion
should see what is in the table, not what one particular scope is allowed
to see.

**No analytics rows are seeded anywhere in this file.** Every reading these
fixtures produce lands ``confidence='suppressed'`` (the below-floor/missing-
daily-rows path ``test_missing_daily_rows_suppress_never_crash`` already
covers) -- deliberately, because a suppressed row with a correctly-populated
``run_id`` is a full pass of this slice, and it keeps every fixture here
down to a ``ToolExecution`` row and nothing else.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from juli_backend.core.config.runtime import async_database_url, sync_database_url
from juli_backend.services.operations.outcome_chain import EmptyLink, load_outcome_chain
from juli_backend.workers.impact_reader.pipeline import run_daily_impact_reader
from juli_backend.workers.impact_reader.queries import build_reading_row
from tests.support.postgres import database_url, juli_app_async_sessionmaker, requires_postgres

pytestmark = requires_postgres

# ---------------------------------------------------------------------------
# One reference point every date in this file derives from.
# ---------------------------------------------------------------------------
REFERENCE_T = date(2026, 1, 15)


def _stamp(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, 12, 0)


# ---------------------------------------------------------------------------
# Seeding -- owner connection. Set-up, not the thing under test.
# ---------------------------------------------------------------------------


@pytest.fixture
def owner_engine():
    engine = create_engine(sync_database_url(database_url()))
    try:
        yield engine
    finally:
        engine.dispose()


def _seed_shop_and_run(engine, *, tiktok_product_id: str) -> tuple[uuid.UUID, uuid.UUID]:
    """One user, one shop, one product and one ``workflow_runs`` row.
    Returns ``(shop_id, run_id)``."""
    now = datetime.now(UTC).replace(tzinfo=None)
    user_id = uuid.uuid4()
    shop_id = uuid.uuid4()
    product_id = uuid.uuid4()
    run_id = uuid.uuid4()

    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO public.users (id, phone, created_at, updated_at) "
                "VALUES (:id, :phone, :now, :now)"
            ),
            {"id": str(user_id), "phone": f"+1555{user_id.hex[:7]}", "now": now},
        )
        conn.execute(
            text(
                "INSERT INTO public.shops "
                "(id, user_id, shop_name, tiktok_shop_id, created_at, updated_at) "
                "VALUES (:id, :user_id, :name, :tiktok_id, :now, :now)"
            ),
            {
                "id": str(shop_id),
                "user_id": str(user_id),
                "name": "Issue 1858 Run Id Shop",
                "tiktok_id": f"tt-{shop_id.hex[:10]}",
                "now": now,
            },
        )
        conn.execute(
            text(
                "INSERT INTO public.products "
                "(id, shop_id, tiktok_product_id, name, status, update_time, "
                " created_at, updated_at) "
                "VALUES (:id, :shop_id, :tiktok_id, :name, 'active', :now, :now, :now)"
            ),
            {
                "id": str(product_id),
                "shop_id": str(shop_id),
                "tiktok_id": tiktok_product_id,
                "name": "Issue 1858 Run Id Product",
                "now": now,
            },
        )
        conn.execute(
            text(
                "INSERT INTO public.workflow_runs "
                "(id, shop_id, product_id, state, status, prompt_version, prompt_sha256, "
                " created_at, updated_at) "
                "VALUES (:id, :shop_id, :product_id, CAST(:state AS jsonb), 'completed', "
                " :prompt_version, :prompt_sha256, :now, :now)"
            ),
            {
                "id": str(run_id),
                "shop_id": str(shop_id),
                "product_id": str(product_id),
                "state": json.dumps({}),
                "prompt_version": "agt-w8f-1858/v1",
                "prompt_sha256": "0" * 64,
                "now": now,
            },
        )
    return shop_id, run_id


def _seed_shop_only(engine, *, tiktok_product_id: str) -> uuid.UUID:
    """A shop with no ``workflow_runs`` row at all -- the legacy case a
    ``tool_executions`` row with ``workflow_run_id IS NULL`` predates."""
    now = datetime.now(UTC).replace(tzinfo=None)
    user_id = uuid.uuid4()
    shop_id = uuid.uuid4()

    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO public.users (id, phone, created_at, updated_at) "
                "VALUES (:id, :phone, :now, :now)"
            ),
            {"id": str(user_id), "phone": f"+1555{user_id.hex[:7]}", "now": now},
        )
        conn.execute(
            text(
                "INSERT INTO public.shops "
                "(id, user_id, shop_name, tiktok_shop_id, created_at, updated_at) "
                "VALUES (:id, :user_id, :name, :tiktok_id, :now, :now)"
            ),
            {
                "id": str(shop_id),
                "user_id": str(user_id),
                "name": "Issue 1858 Legacy Shop",
                "tiktok_id": f"tt-{shop_id.hex[:10]}",
                "now": now,
            },
        )
    return shop_id


def _insert_tool_execution(
    engine,
    *,
    shop_id: uuid.UUID,
    workflow_run_id: uuid.UUID | None,
    tool_name: str,
    payload: dict,
    t: date,
    approval_id: str,
) -> uuid.UUID:
    execution_id = uuid.uuid4()
    stamp = _stamp(t)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO public.tool_executions "
                "(id, shop_id, approval_id, tool_name, payload_json, status, "
                " workflow_run_id, updated_at, created_at) "
                "VALUES (:id, :shop_id, :approval_id, :tool_name, :payload, 'succeeded', "
                " :run_id, :ts, :ts)"
            ),
            {
                "id": str(execution_id),
                "shop_id": str(shop_id),
                "approval_id": approval_id,
                "tool_name": tool_name,
                "payload": json.dumps(payload),
                "run_id": str(workflow_run_id) if workflow_run_id is not None else None,
                "ts": stamp,
            },
        )
    return execution_id


def _price_payload(tiktok_product_id: str) -> dict:
    return {
        "product_id": tiktok_product_id,
        "price_update": {"price": "199000", "currency": "VND"},
    }


def _readings_for_execution(engine, execution_id: uuid.UUID) -> list[tuple]:
    """Read ``(id, run_id, metric, kind, confidence)`` back for one execution,
    directly from the database -- never the row the reader's own session
    handed back, and never the argument this test constructed."""
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT id, run_id, metric, kind, confidence FROM public.impact_readings "
                "WHERE tool_execution_id = :id"
            ),
            {"id": str(execution_id)},
        ).all()
    return list(rows)


async def _run_reader(reference_date: date):
    async with juli_app_async_sessionmaker() as factory:
        async with factory() as session:
            result = await run_daily_impact_reader(session, reference_date)
            await session.commit()
    return result


# ---------------------------------------------------------------------------
# AC1/AC2 -- a real reading carries the execution's own workflow_run_id.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reader_persists_run_id_equal_to_executions_workflow_run_id(owner_engine):
    tiktok_product_id = f"agt-w8f-1858-{uuid.uuid4().hex[:10]}"
    shop_id, run_id = _seed_shop_and_run(owner_engine, tiktok_product_id=tiktok_product_id)
    execution_id = _insert_tool_execution(
        owner_engine,
        shop_id=shop_id,
        workflow_run_id=run_id,
        tool_name="update_product_price",
        payload=_price_payload(tiktok_product_id),
        t=REFERENCE_T,
        approval_id="agt-1858-approval-1",
    )

    result = await _run_reader(REFERENCE_T + timedelta(days=7))

    assert result.readings_written > 0, "the price mutation must classify and write readings"

    rows = _readings_for_execution(owner_engine, execution_id)
    assert rows, "no impact_readings row was persisted for the seeded execution"
    # AC2: every row in the batched flush carries the run id, not only the
    # first -- PRICE alone yields at least two metrics (primary + secondary),
    # so a fix that threads run_id into only one branch would still leave
    # this failing.
    assert len(rows) >= 2, f"expected at least two metrics from a PRICE mutation, got {rows}"
    for _reading_id, run_id_value, metric, kind, confidence in rows:
        assert run_id_value == run_id, (
            f"reading for metric={metric!r} kind={kind!r} carries run_id={run_id_value!s}, "
            f"expected the execution's own workflow_run_id {run_id!s}"
        )
        # Confirms this file's own premise: with no analytics rows seeded,
        # every reading is honestly suppressed, never fabricated.
        assert confidence == "suppressed"


# ---------------------------------------------------------------------------
# AC4 -- a legacy execution (workflow_run_id IS NULL) is untouched.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reader_persists_null_run_id_for_legacy_execution_without_raising(owner_engine):
    tiktok_product_id = f"agt-w8f-1858-legacy-{uuid.uuid4().hex[:10]}"
    shop_id = _seed_shop_only(owner_engine, tiktok_product_id=tiktok_product_id)
    execution_id = _insert_tool_execution(
        owner_engine,
        shop_id=shop_id,
        workflow_run_id=None,
        tool_name="update_product_price",
        payload=_price_payload(tiktok_product_id),
        t=REFERENCE_T,
        approval_id="agt-1858-approval-legacy-1",
    )

    result = await _run_reader(REFERENCE_T + timedelta(days=7))

    assert result.readings_written > 0

    rows = _readings_for_execution(owner_engine, execution_id)
    assert rows, "a legacy (workflow_run_id IS NULL) execution must still get a row"
    for _reading_id, run_id_value, _metric, _kind, confidence in rows:
        assert run_id_value is None, (
            f"a legacy execution's reading must persist run_id=NULL, got {run_id_value!s}"
        )
        assert confidence == "suppressed"


# ---------------------------------------------------------------------------
# AC5 -- the parameter shape is the contract: required, keyword-only, no default.
# ---------------------------------------------------------------------------


def test_build_reading_row_requires_run_id_as_a_keyword_argument():
    """The precedent is ``series_source`` (ADR-099 d.2, #1766): a value that
    can be forgotten will be forgotten, and the forgotten value here is the
    exact bug this slice fixes. Omitting ``run_id`` must be a ``TypeError``,
    never a silently-inherited ``None``.

    The arguments are assembled into a plain ``dict`` and splatted in, rather
    than passed as literal keywords with ``run_id`` left out: a literal
    omission is also a *static* type error (mypy's own ``call-arg``), and this
    slice's suppression ratchet forbids a new ``# type: ignore`` to silence
    it. Building the call this way keeps the omission a runtime fact only,
    which is exactly what this test asserts.
    """
    kwargs: dict[str, object] = {
        "tool_execution_id": uuid.uuid4(),
        "metric": "gmv",
        "kind": "preliminary",
        "pre": None,
        "post": None,
        "expected": None,
        "incremental": None,
        "impact_pct": None,
        "confidence": "suppressed",
        "control_set_json": "{}",
        "computed_at": datetime.now(UTC),
        "series_source": "measured",
    }
    assert "run_id" not in kwargs
    with pytest.raises(TypeError):
        build_reading_row(**kwargs)


# ---------------------------------------------------------------------------
# AC6/AC7 -- the OR-join's row-count multiplication does not leak into the
# outcome chain's deduplicated output.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_write_executions_one_run_chain_reports_readings_once_not_multiplied(
    owner_engine,
):
    """``outcome_chain._chain_statement`` outer-joins ``impact_readings`` on
    ``or_(run_id == WorkflowRun.id, tool_execution_id == ToolExecution.id)``.
    Once ``run_id`` is populated, a reading matches the run arm for EVERY
    ``tool_executions`` row belonging to that run -- so a run with two write
    executions and readings only on one of them produces a join whose raw row
    count is doubled. ``_collect_readings`` dedupes by ``reading_id``; this
    test proves that dedup actually holds against the real multiplied join,
    not merely that it appears to on a single-execution run.
    """
    tiktok_product_id = f"agt-w8f-1858-multi-{uuid.uuid4().hex[:10]}"
    shop_id, run_id = _seed_shop_and_run(owner_engine, tiktok_product_id=tiktok_product_id)

    due_execution_id = _insert_tool_execution(
        owner_engine,
        shop_id=shop_id,
        workflow_run_id=run_id,
        tool_name="update_product_price",
        payload=_price_payload(tiktok_product_id),
        t=REFERENCE_T,
        approval_id="agt-1858-approval-multi-due",
    )
    # A second write execution on the SAME run, whose own window has not
    # elapsed yet -- the impact reader never touches it, but it still
    # contributes a second `tool_executions` row to the chain's join.
    reference_date = REFERENCE_T + timedelta(days=7)
    _insert_tool_execution(
        owner_engine,
        shop_id=shop_id,
        workflow_run_id=run_id,
        tool_name="update_product_price",
        payload=_price_payload(f"{tiktok_product_id}-sibling"),
        t=reference_date,
        approval_id="agt-1858-approval-multi-sibling",
    )

    await _run_reader(reference_date)

    direct_rows = _readings_for_execution(owner_engine, due_execution_id)
    assert direct_rows, "the due execution must have produced readings"
    direct_reading_count = len(direct_rows)

    owner_async_engine = create_async_engine(async_database_url(database_url()))
    try:
        session_factory = async_sessionmaker(owner_async_engine, expire_on_commit=False)
        async with session_factory() as session:
            chain = await load_outcome_chain(session, run_id)
    finally:
        await owner_async_engine.dispose()

    assert len(chain.action.executions) == 2, (
        "the action link must show both dispatched executions for this run, "
        f"got {chain.action.executions!r}"
    )

    assert isinstance(chain.incremental_impact, EmptyLink), (
        "every reading in this fixture is suppressed (no analytics rows seeded), so "
        "the incremental-impact link must be an EmptyLink carrying them as excluded"
    )
    excluded = chain.incremental_impact.excluded_readings
    assert len(excluded) == direct_reading_count, (
        f"the chain reported {len(excluded)} excluded reading(s) but the database holds "
        f"exactly {direct_reading_count} -- the OR-join's row-count multiplication across "
        "this run's two tool_executions rows has leaked into the chain's output instead "
        "of being deduplicated away"
    )
    assert {r.reading_id for r in excluded} == {row[0] for row in direct_rows}, (
        "the chain's excluded readings must be exactly the database's own reading ids "
        "for the due execution, never a subset, a superset, or a sibling's reading"
    )
