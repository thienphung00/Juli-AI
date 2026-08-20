"""The five-minute reaper — #1130, ADR-074 decision 4; ADR-073's
`worker_lost` amendment (2026-08-12).

AC -> test map:
- stale running/queued -> worker_lost/failed through the sink ->
  test_stale_running_run_past_threshold_with_no_live_task_is_reaped_as_worker_lost,
  test_stale_queued_run_with_no_events_uses_created_at_fallback_and_is_reaped
- worker_lost additive + total-mapping -> already covered by
  test_workflow_run_status_mapping.py (status.py ships WORKER_LOST already);
  not re-asserted here to avoid a duplicate authority.
- expired waiting_approval -> confirmation_expired/cancelled ->
  test_waiting_approval_run_past_4h_is_reaped_as_confirmation_expired
- approval expiry is liveness-INDEPENDENT (ADR-073 design, not accidental) ->
  test_waiting_approval_run_past_4h_is_reaped_even_with_a_live_task
- explicit trap: never tool_error_unrecoverable ->
  test_reaper_module_never_references_tool_error_unrecoverable,
  test_reap_stop_reasons_are_limited_to_worker_lost_and_confirmation_expired
- no-false-kill-at-the-boundary ->
  test_stale_run_just_under_threshold_is_not_reaped,
  test_stale_run_past_threshold_but_with_live_task_is_not_reaped,
  test_stale_run_recent_event_overrides_old_started_at_and_is_not_reaped,
  test_waiting_approval_run_just_under_4h_boundary_is_not_reaped
- goes through the sink, not a side-channel UPDATE ->
  test_reap_never_mutates_status_without_the_sink_performing_it,
  test_reaper_event_sink_satisfies_event_sink_protocol,
  test_reaped_run_has_both_the_event_row_and_the_status_update
- beat schedule, every 5 minutes, existing entries unaffected ->
  test_reaper_beat_entry_runs_every_five_minutes,
  test_beat_schedule_has_exactly_the_six_expected_entries,
  test_reaper_task_is_registered_on_the_worker
- termination values are READ off TerminationPolicy, never a copied literal
  (this phase's architect lock) ->
  test_reap_stale_threshold_moves_with_injected_policy_not_the_default,
  test_reap_approval_threshold_moves_with_injected_policy_not_the_default
- liveness probe matches by keyword arg too, not positional-only ->
  test_default_has_live_task_true_when_matching_active_task_by_keyword_arg

Time is always injected (`now=`), and the Celery liveness probe is always
injected (`has_live_task=`) except in the small dedicated section testing
`_default_has_live_task`'s own fail-safe behaviour -- no real sleeping, no
real broker connection, anywhere in this file.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest_asyncio
from celery.schedules import crontab
from sqlalchemy import select

from juli_backend.models.models import Product, Shop, WorkflowRun
from juli_backend.models.models import WorkflowRunEvent as WorkflowRunEventRow
from juli_backend.services.agent.events.envelope import WorkflowFailedEvent
from juli_backend.services.agent.events.sink import EventSink
from juli_backend.services.agent.playbooks.base import TerminationPolicy
from juli_backend.services.agent.playbooks.optimize_product import (
    OPTIMIZE_PRODUCT_TERMINATION_POLICY,
)
from juli_backend.services.agent.runner.status import StopReason, WorkflowRunStatus
from juli_backend.workers.celery_app import celery_app
from juli_backend.workers.tasks import reaper

WALL_CLOCK_TIMEOUT_S = OPTIMIZE_PRODUCT_TERMINATION_POLICY.wall_clock_timeout_s
APPROVAL_TIMEOUT_H = OPTIMIZE_PRODUCT_TERMINATION_POLICY.approval_timeout_h
STALE_THRESHOLD_S = WALL_CLOCK_TIMEOUT_S + reaper.STALE_RUN_SLACK_S
APPROVAL_THRESHOLD_S = APPROVAL_TIMEOUT_H * 3600

NOW = datetime(2026, 8, 14, 12, 0, 0, tzinfo=UTC)


def _never_live(_run_id: uuid.UUID) -> bool:
    return False


def _always_live(_run_id: uuid.UUID) -> bool:
    return True


def _custom_policy(*, wall_clock_timeout_s: int, approval_timeout_h: int) -> TerminationPolicy:
    """A `TerminationPolicy` with unusual, non-default numbers -- used to
    prove the reaper's thresholds move with whatever policy it is given
    rather than a value copied at import time."""
    return TerminationPolicy(
        max_iterations=6,
        max_extensions=1,
        extension_iterations=2,
        wall_clock_timeout_s=wall_clock_timeout_s,
        approval_timeout_h=approval_timeout_h,
        required_steps=("some_step",),
    )


class _RecordingNoopSink:
    """A spy `EventSink` that records what it was asked to emit but performs
    NO database write of its own -- used to prove the reaper's scan/decision
    code never mutates `workflow_runs.status` itself; only a sink's `emit`
    is allowed to."""

    def __init__(self) -> None:
        self.events: list[WorkflowFailedEvent] = []

    async def emit(self, event: WorkflowFailedEvent) -> None:
        self.events.append(event)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def shop(session):
    s = Shop(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        shop_name="Reaper Test Shop",
        tiktok_shop_id="tiktok_shop_reaper",
    )
    session.add(s)
    await session.flush()
    return s


@pytest_asyncio.fixture
async def product(session, shop):
    p = Product(
        id=uuid.uuid4(),
        shop_id=shop.id,
        tiktok_product_id="tiktok_product_reaper",
        name="Reaper Test Product",
        status="active",
        update_time=datetime.now(UTC),
    )
    session.add(p)
    await session.flush()
    return p


async def _make_run(
    session,
    shop_id,
    product_id,
    *,
    status: str,
    started_at: datetime | None = None,
    waiting_approval_since: datetime | None = None,
    created_at: datetime | None = None,
    state: dict | None = None,
) -> WorkflowRun:
    run = WorkflowRun(
        id=uuid.uuid4(),
        shop_id=shop_id,
        product_id=product_id,
        state=state if state is not None else {},
        status=status,
        prompt_version="optimize_product_2/v1",
        prompt_sha256="a" * 64,
        started_at=started_at,
        waiting_approval_since=waiting_approval_since,
    )
    session.add(run)
    await session.flush()
    if created_at is not None:
        run.created_at = created_at
        await session.flush()
    return run


async def _seed_event(session, run_id, seq: int, *, timestamp: datetime) -> None:
    row = WorkflowRunEventRow(
        id=uuid.uuid4(),
        workflow_run_id=run_id,
        sequence_number=seq,
        event_type="assistant.text",
        timestamp=timestamp,
        payload={"text": "still going"},
        v=1,
    )
    session.add(row)
    await session.flush()


async def _reload(session, run: WorkflowRun) -> WorkflowRun:
    return await session.get(WorkflowRun, run.id)


async def _events_for(session, run_id) -> list[WorkflowRunEventRow]:
    result = await session.execute(
        select(WorkflowRunEventRow)
        .where(WorkflowRunEventRow.workflow_run_id == run_id)
        .order_by(WorkflowRunEventRow.sequence_number)
    )
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Closure 1 — stale running/queued -> worker_lost -> failed
# ---------------------------------------------------------------------------


async def test_stale_running_run_past_threshold_with_no_live_task_is_reaped_as_worker_lost(
    session, shop, product
):
    run = await _make_run(
        session,
        shop.id,
        product.id,
        status="running",
        started_at=NOW - timedelta(seconds=STALE_THRESHOLD_S + 100),
    )

    result = await reaper.reap_workflow_runs(session, now=NOW, has_live_task=_never_live)

    assert result.stale_runs_reaped == (run.id,)
    assert result.expired_approvals_reaped == ()

    reloaded = await _reload(session, run)
    assert reloaded.status == WorkflowRunStatus.FAILED.value
    assert reloaded.stop_reason == StopReason.WORKER_LOST.value
    assert reloaded.completed_at == NOW

    events = await _events_for(session, run.id)
    assert len(events) == 1
    assert events[0].event_type == "workflow.failed"
    assert events[0].sequence_number == 0
    assert events[0].payload["stop_reason"] == "worker_lost"
    assert events[0].payload["status"] == "failed"


# --- issue #1220: required_steps_completed is written on the worker_lost path,
# the same way the runner writes it on every path it produces itself. -------


async def test_worker_lost_still_records_required_steps_completed_true(session, shop, product):
    """A worker died (`worker_lost`) *after* the run had already completed
    both required writes -- `required_steps_completed` records that honest
    fact even though the run's own `stop_reason` is a failure the run
    itself never chose (ADR-073 decision 2: the two are independent)."""
    completed_window = [
        {
            "role": "tool",
            "tool_call_id": "c0",
            "tool_name": "update_product_listing",
            "content": {"title": "New Title"},
        },
        {
            "role": "tool",
            "tool_call_id": "c1",
            "tool_name": "update_product_price",
            "content": {"updated_skus": ["S1"]},
        },
    ]
    run = await _make_run(
        session,
        shop.id,
        product.id,
        status="running",
        started_at=NOW - timedelta(seconds=STALE_THRESHOLD_S + 100),
        state={"conversation_window": completed_window},
    )

    result = await reaper.reap_workflow_runs(session, now=NOW, has_live_task=_never_live)

    assert result.stale_runs_reaped == (run.id,)
    reloaded = await _reload(session, run)
    assert reloaded.stop_reason == StopReason.WORKER_LOST.value
    assert reloaded.required_steps_completed is True


async def test_worker_lost_records_required_steps_completed_false_when_nothing_completed(
    session, shop, product
):
    run = await _make_run(
        session,
        shop.id,
        product.id,
        status="running",
        started_at=NOW - timedelta(seconds=STALE_THRESHOLD_S + 100),
        state={"conversation_window": []},
    )

    await reaper.reap_workflow_runs(session, now=NOW, has_live_task=_never_live)

    reloaded = await _reload(session, run)
    assert reloaded.stop_reason == StopReason.WORKER_LOST.value
    assert reloaded.required_steps_completed is False


async def test_worker_lost_required_steps_completed_moves_with_injected_policy(
    session, shop, product
):
    """Proves `_ReaperEventSink` reads `required_steps` off whatever policy
    it is given, not the real playbook's copied at import time -- the same
    discipline `test_reap_stale_threshold_moves_with_injected_policy_not_
    the_default` already pins for the wall-clock threshold."""
    run = await _make_run(
        session,
        shop.id,
        product.id,
        status="running",
        started_at=NOW - timedelta(seconds=STALE_THRESHOLD_S + 100),
        state={
            "conversation_window": [
                {
                    "role": "tool",
                    "tool_call_id": "c0",
                    "tool_name": "some_step",
                    "content": {"ok": True},
                }
            ]
        },
    )
    policy = _custom_policy(wall_clock_timeout_s=WALL_CLOCK_TIMEOUT_S, approval_timeout_h=1)

    await reaper.reap_workflow_runs(session, now=NOW, has_live_task=_never_live, policy=policy)

    reloaded = await _reload(session, run)
    assert reloaded.required_steps_completed is True, (
        "the custom policy's required_steps=('some_step',) was satisfied by the "
        "seeded conversation_window -- proves the sink read the injected policy, "
        "not OPTIMIZE_PRODUCT_TERMINATION_POLICY.required_steps"
    )


async def test_stale_queued_run_with_no_events_uses_created_at_fallback_and_is_reaped(
    session, shop, product
):
    run = await _make_run(
        session,
        shop.id,
        product.id,
        status="queued",
        created_at=NOW - timedelta(seconds=STALE_THRESHOLD_S + 50),
    )

    result = await reaper.reap_workflow_runs(session, now=NOW, has_live_task=_never_live)

    assert result.stale_runs_reaped == (run.id,)
    reloaded = await _reload(session, run)
    assert reloaded.status == WorkflowRunStatus.FAILED.value
    assert reloaded.stop_reason == StopReason.WORKER_LOST.value


async def test_emitted_event_sequence_number_continues_from_existing_events(session, shop, product):
    run = await _make_run(
        session,
        shop.id,
        product.id,
        status="running",
        started_at=NOW - timedelta(seconds=STALE_THRESHOLD_S + 1000),
    )
    old = NOW - timedelta(seconds=STALE_THRESHOLD_S + 500)
    await _seed_event(session, run.id, 0, timestamp=old)
    await _seed_event(session, run.id, 1, timestamp=old + timedelta(seconds=1))

    result = await reaper.reap_workflow_runs(session, now=NOW, has_live_task=_never_live)

    assert result.stale_runs_reaped == (run.id,)
    events = await _events_for(session, run.id)
    assert [e.sequence_number for e in events] == [0, 1, 2]
    assert events[2].event_type == "workflow.failed"


# ---------------------------------------------------------------------------
# Closure 2 — expired waiting_approval -> confirmation_expired -> cancelled
# ---------------------------------------------------------------------------


async def test_waiting_approval_run_past_4h_is_reaped_as_confirmation_expired(
    session, shop, product
):
    run = await _make_run(
        session,
        shop.id,
        product.id,
        status="waiting_approval",
        waiting_approval_since=NOW - timedelta(seconds=APPROVAL_THRESHOLD_S + 1),
    )

    result = await reaper.reap_workflow_runs(session, now=NOW, has_live_task=_never_live)

    assert result.expired_approvals_reaped == (run.id,)
    assert result.stale_runs_reaped == ()

    reloaded = await _reload(session, run)
    assert reloaded.status == WorkflowRunStatus.CANCELLED.value
    assert reloaded.stop_reason == StopReason.CONFIRMATION_EXPIRED.value

    events = await _events_for(session, run.id)
    assert len(events) == 1
    assert events[0].payload["stop_reason"] == "confirmation_expired"
    assert events[0].payload["status"] == "cancelled"


async def test_waiting_approval_run_past_4h_is_reaped_even_with_a_live_task(session, shop, product):
    """Approval expiry is liveness-INDEPENDENT (ADR-073's design, not an
    accident): a seller's 4h approval window expires on time alone, whether
    or not a worker happens to be alive has no bearing on whether the
    seller answered. Every other waiting_approval test in this file uses
    `_never_live`, so nothing else proves the closure does not accidentally
    gate on liveness the way the stale-run closure legitimately does --
    this is that proof. A mutation that adds a `has_live_task` gate to
    `_reap_expired_waiting_approval` must fail this test."""
    run = await _make_run(
        session,
        shop.id,
        product.id,
        status="waiting_approval",
        waiting_approval_since=NOW - timedelta(seconds=APPROVAL_THRESHOLD_S + 1),
    )

    result = await reaper.reap_workflow_runs(session, now=NOW, has_live_task=_always_live)

    assert result.expired_approvals_reaped == (run.id,)
    reloaded = await _reload(session, run)
    assert reloaded.status == WorkflowRunStatus.CANCELLED.value
    assert reloaded.stop_reason == StopReason.CONFIRMATION_EXPIRED.value


async def test_waiting_approval_run_with_no_waiting_approval_since_is_skipped(
    session, shop, product
):
    """Defensive: a waiting_approval row with a null waiting_approval_since
    (should not happen in practice) must not crash the reaper or be reaped
    on a bogus epoch-zero comparison."""
    run = await _make_run(session, shop.id, product.id, status="waiting_approval")

    result = await reaper.reap_workflow_runs(session, now=NOW, has_live_task=_never_live)

    assert result.expired_approvals_reaped == ()
    reloaded = await _reload(session, run)
    assert reloaded.status == "waiting_approval"


# ---------------------------------------------------------------------------
# No-false-kill-at-the-boundary (mandatory per #1130)
# ---------------------------------------------------------------------------


async def test_stale_run_just_under_threshold_is_not_reaped(session, shop, product):
    run = await _make_run(
        session,
        shop.id,
        product.id,
        status="running",
        started_at=NOW - timedelta(seconds=STALE_THRESHOLD_S - 1),
    )

    result = await reaper.reap_workflow_runs(session, now=NOW, has_live_task=_never_live)

    assert result.stale_runs_reaped == ()
    reloaded = await _reload(session, run)
    assert reloaded.status == "running"
    assert reloaded.stop_reason is None
    assert await _events_for(session, run.id) == []


async def test_stale_run_past_threshold_but_with_live_task_is_not_reaped(session, shop, product):
    """Time alone is not sufficient: a live task signal must gate the
    closure even once the elapsed time has genuinely passed the boundary."""
    run = await _make_run(
        session,
        shop.id,
        product.id,
        status="running",
        started_at=NOW - timedelta(seconds=STALE_THRESHOLD_S + 500),
    )

    result = await reaper.reap_workflow_runs(session, now=NOW, has_live_task=_always_live)

    assert result.stale_runs_reaped == ()
    reloaded = await _reload(session, run)
    assert reloaded.status == "running"


async def test_stale_run_recent_event_overrides_old_started_at_and_is_not_reaped(
    session, shop, product
):
    """A run started long ago but with a recent event is alive -- the
    liveness reference is the latest event, not started_at."""
    run = await _make_run(
        session,
        shop.id,
        product.id,
        status="running",
        started_at=NOW - timedelta(seconds=STALE_THRESHOLD_S * 10),
    )
    await _seed_event(session, run.id, 0, timestamp=NOW - timedelta(seconds=5))

    result = await reaper.reap_workflow_runs(session, now=NOW, has_live_task=_never_live)

    assert result.stale_runs_reaped == ()
    reloaded = await _reload(session, run)
    assert reloaded.status == "running"


async def test_waiting_approval_run_just_under_4h_boundary_is_not_reaped(session, shop, product):
    run = await _make_run(
        session,
        shop.id,
        product.id,
        status="waiting_approval",
        waiting_approval_since=NOW - timedelta(seconds=APPROVAL_THRESHOLD_S - 1),
    )

    result = await reaper.reap_workflow_runs(session, now=NOW, has_live_task=_never_live)

    assert result.expired_approvals_reaped == ()
    reloaded = await _reload(session, run)
    assert reloaded.status == "waiting_approval"
    assert reloaded.stop_reason is None


# ---------------------------------------------------------------------------
# Sink path — never a side-channel UPDATE
# ---------------------------------------------------------------------------


def test_reaper_event_sink_satisfies_event_sink_protocol():
    sink = reaper._ReaperEventSink(session=None)  # protocol check needs no real session
    assert isinstance(sink, EventSink)


async def test_reap_never_mutates_status_without_the_sink_performing_it(session, shop, product):
    """With a spy sink that records but never writes, the reaper's own
    scan/decision code must leave `workflow_runs.status` untouched -- proof
    the only status-mutating code path is inside a sink's `emit`, never a
    bare assignment in the reap loop itself."""
    run = await _make_run(
        session,
        shop.id,
        product.id,
        status="running",
        started_at=NOW - timedelta(seconds=STALE_THRESHOLD_S + 100),
    )
    spy = _RecordingNoopSink()

    result = await reaper.reap_workflow_runs(session, now=NOW, has_live_task=_never_live, sink=spy)

    assert result.stale_runs_reaped == (run.id,), "decision layer must still identify the run"
    assert len(spy.events) == 1
    assert spy.events[0].payload.stop_reason == StopReason.WORKER_LOST

    reloaded = await _reload(session, run)
    assert reloaded.status == "running", (
        "status must be unchanged: the spy sink never wrote it, so nothing else may have"
    )
    assert reloaded.stop_reason is None
    assert await _events_for(session, run.id) == [], "no event row without the sink writing it"


async def test_reaped_run_has_both_the_event_row_and_the_status_update(session, shop, product):
    """The flip side of the spy-sink test: the REAL sink produces both the
    event row a connected SSE client would see AND the status flip, in the
    same operation -- never one without the other."""
    run = await _make_run(
        session,
        shop.id,
        product.id,
        status="waiting_approval",
        waiting_approval_since=NOW - timedelta(seconds=APPROVAL_THRESHOLD_S + 10),
    )

    await reaper.reap_workflow_runs(session, now=NOW, has_live_task=_never_live)

    reloaded = await _reload(session, run)
    events = await _events_for(session, run.id)
    assert reloaded.status == WorkflowRunStatus.CANCELLED.value
    assert len(events) == 1
    assert events[0].event_type == "workflow.failed"


# ---------------------------------------------------------------------------
# Explicit trap — never tool_error_unrecoverable
# ---------------------------------------------------------------------------


def test_reap_defaults_to_the_real_optimize_product_termination_policy(session, shop, product):
    """`reap_workflow_runs`'s `policy=` default (no override at all) really
    is `OPTIMIZE_PRODUCT_TERMINATION_POLICY` -- not a copy, the object
    itself -- so every other test in this file that never passes `policy=`
    is genuinely exercising the real policy, not a stand-in."""
    assert reaper._DEFAULT_TERMINATION_POLICY is OPTIMIZE_PRODUCT_TERMINATION_POLICY


async def test_reap_stale_threshold_moves_with_injected_policy_not_the_default(
    session, shop, product
):
    """Proves `wall_clock_timeout_s` is READ off whichever `TerminationPolicy`
    is passed in, not a value copied once at import time (this phase's
    architect lock: a literal reproducing a policy field anywhere else is a
    defect). 400s elapsed sits strictly between a tiny injected policy's
    threshold (10 + the fixed 300s slack = 310s -- reaped) and the real
    default's (300 + 300 = 600s -- not reaped): only the injected policy
    changes the outcome, proving the number really moved."""
    run = await _make_run(
        session,
        shop.id,
        product.id,
        status="running",
        started_at=NOW - timedelta(seconds=400),
    )

    default_result = await reaper.reap_workflow_runs(session, now=NOW, has_live_task=_never_live)
    assert default_result.stale_runs_reaped == ()

    tiny_policy = _custom_policy(wall_clock_timeout_s=10, approval_timeout_h=APPROVAL_TIMEOUT_H)
    custom_result = await reaper.reap_workflow_runs(
        session, now=NOW, has_live_task=_never_live, policy=tiny_policy
    )
    assert custom_result.stale_runs_reaped == (run.id,)


async def test_reap_approval_threshold_moves_with_injected_policy_not_the_default(
    session, shop, product
):
    """Same proof for `approval_timeout_h`: 2h elapsed is under the real
    default's 4h (not reaped) but past a tiny injected policy's 1h (reaped)."""
    run = await _make_run(
        session,
        shop.id,
        product.id,
        status="waiting_approval",
        waiting_approval_since=NOW - timedelta(hours=2),
    )

    default_result = await reaper.reap_workflow_runs(session, now=NOW, has_live_task=_never_live)
    assert default_result.expired_approvals_reaped == ()

    tiny_policy = _custom_policy(wall_clock_timeout_s=WALL_CLOCK_TIMEOUT_S, approval_timeout_h=1)
    custom_result = await reaper.reap_workflow_runs(
        session, now=NOW, has_live_task=_never_live, policy=tiny_policy
    )
    assert custom_result.expired_approvals_reaped == (run.id,)


def test_reaper_module_never_references_tool_error_unrecoverable():
    """AST-precise, not a substring scan: the module docstring and comments
    legitimately *discuss* `tool_error_unrecoverable` (explaining why the
    reaper does not reuse it), so a raw substring search over the source
    text would trip on the module's own explanation. What must never exist
    is actual code referencing `StopReason.TOOL_ERROR_UNRECOVERABLE` or
    constructing the bare string literal as a value."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(reaper))
    offending = [
        ast.dump(node)
        for node in ast.walk(tree)
        if (isinstance(node, ast.Attribute) and node.attr == "TOOL_ERROR_UNRECOVERABLE")
        or (isinstance(node, ast.Constant) and node.value == "tool_error_unrecoverable")
    ]
    assert not offending, (
        "the reaper must never construct StopReason.TOOL_ERROR_UNRECOVERABLE or the bare "
        f"string literal 'tool_error_unrecoverable': {offending}"
    )


async def test_reap_stop_reasons_are_limited_to_worker_lost_and_confirmation_expired(
    session, shop, product
):
    # A second product: workflow_runs enforces one active run per
    # (shop_id, product_id) (ADR-073 decision 4), and both "running" and
    # "waiting_approval" are active statuses -- two active rows for the
    # same product would violate that guard regardless of this test's
    # purpose.
    other_product = Product(
        id=uuid.uuid4(),
        shop_id=shop.id,
        tiktok_product_id="tiktok_product_reaper_2",
        name="Reaper Test Product 2",
        status="active",
        update_time=datetime.now(UTC),
    )
    session.add(other_product)
    await session.flush()

    stale_run = await _make_run(
        session,
        shop.id,
        product.id,
        status="running",
        started_at=NOW - timedelta(seconds=STALE_THRESHOLD_S + 10),
    )
    expired_run = await _make_run(
        session,
        shop.id,
        other_product.id,
        status="waiting_approval",
        waiting_approval_since=NOW - timedelta(seconds=APPROVAL_THRESHOLD_S + 10),
    )

    await reaper.reap_workflow_runs(session, now=NOW, has_live_task=_never_live)

    all_stop_reasons = {
        e.payload["stop_reason"]
        for run_id in (stale_run.id, expired_run.id)
        for e in await _events_for(session, run_id)
    }
    assert all_stop_reasons == {"worker_lost", "confirmation_expired"}
    assert "tool_error_unrecoverable" not in all_stop_reasons


# ---------------------------------------------------------------------------
# Beat schedule
# ---------------------------------------------------------------------------


def test_reaper_beat_entry_runs_every_five_minutes():
    entry = celery_app.conf.beat_schedule["reap-abandoned-workflow-runs"]
    assert entry["task"] == "juli_backend.reap_abandoned_workflow_runs"
    assert entry["schedule"] == crontab(minute="*/5")


def test_beat_schedule_has_exactly_the_six_expected_entries():
    """#1232, ADR-081 decision 1 row 1: `credential-refresh-beat` joins this
    set as the fleet's first credential refresh schedule."""
    schedule = celery_app.conf.beat_schedule
    assert set(schedule) == {
        "mock-analytics-hourly-reconcile",
        "cdp-batch-staggered-reconcile",
        "analytics-backfill-topup",
        "daily-impact-reader",
        "reap-abandoned-workflow-runs",
        "credential-refresh-beat",
    }


def test_reaper_task_is_registered_on_the_worker():
    celery_app.loader.import_default_modules()
    assert "juli_backend.reap_abandoned_workflow_runs" in celery_app.tasks
    assert reaper.reap_abandoned_workflow_runs.name == "juli_backend.reap_abandoned_workflow_runs"


# ---------------------------------------------------------------------------
# `_default_has_live_task` — fail-safe behaviour (no real broker call)
# ---------------------------------------------------------------------------


def test_default_has_live_task_fails_safe_true_when_broker_probe_raises(monkeypatch):
    class _BoomInspect:
        def active(self):
            raise ConnectionError("broker unreachable")

    def _boom_inspect():
        return _BoomInspect()

    monkeypatch.setattr(celery_app.control, "inspect", _boom_inspect)

    assert reaper._default_has_live_task(uuid.uuid4()) is True


def test_default_has_live_task_false_when_no_worker_responds(monkeypatch):
    class _EmptyInspect:
        def active(self):
            return None

        def reserved(self):
            return None

        def scheduled(self):
            return None

    monkeypatch.setattr(celery_app.control, "inspect", lambda: _EmptyInspect())

    assert reaper._default_has_live_task(uuid.uuid4()) is False


def test_default_has_live_task_true_when_matching_active_task_found(monkeypatch):
    run_id = uuid.uuid4()

    class _MatchingInspect:
        def active(self):
            return {
                "worker1@host": [{"name": "juli_backend.run_agent_workflow", "args": [str(run_id)]}]
            }

        def reserved(self):
            return None

        def scheduled(self):
            return None

    monkeypatch.setattr(celery_app.control, "inspect", lambda: _MatchingInspect())

    assert reaper._default_has_live_task(run_id) is True
    assert reaper._default_has_live_task(uuid.uuid4()) is False


def test_default_has_live_task_true_when_matching_active_task_by_keyword_arg(monkeypatch):
    """No caller in this repo enqueues `run_agent_workflow`/`resume_agent_workflow`
    by keyword today, but matching `args[0]` only would read a future
    `enqueue(run_id=...)` call as "no live task" and expose a genuinely
    live run to a false reap -- the costly failure direction. This proves
    the keyword path is checked too, not just positional."""
    run_id = uuid.uuid4()

    class _KeywordMatchingInspect:
        def active(self):
            return {
                "worker1@host": [
                    {
                        "name": "juli_backend.run_agent_workflow",
                        "args": [],
                        "kwargs": {"run_id": str(run_id)},
                    }
                ]
            }

        def reserved(self):
            return None

        def scheduled(self):
            return None

    monkeypatch.setattr(celery_app.control, "inspect", lambda: _KeywordMatchingInspect())

    assert reaper._default_has_live_task(run_id) is True
    assert reaper._default_has_live_task(uuid.uuid4()) is False
