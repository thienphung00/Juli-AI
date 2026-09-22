"""A run can wait on the world, and only its own workflow's clock ends it —
issue #1706 (W9-A/P-SHARED-6), ADR-091 decision 4, ADR-093 decision 2.

Two halves, and neither is worth anything without the other.

**A run gets INTO `waiting_external` through the real path.** Every test that
parks a run in the new state does it by calling
`WorkflowRunner.enter_external_wait` against a real `JsonbConversationStore`
over the shared `session` fixture, never by assigning `run.status =
"waiting_external"`. Direct assignment would prove the reaper's arithmetic
against a row no production code can produce -- the consumer-without-producer
shape #1365's audit catalogued, and the thing this wave's architect lock
exists to forbid. The row the reaper then judges is the row the runner really
wrote, `waiting_external_since` and all.

**A run gets OUT of it.** A new status nothing can leave is worse than no
status: the run sits forever holding its subject, invisible to both existing
reaper sweeps. So the reaping half asserts in both directions -- untouched
inside its own timeout, ended `external_wait_expired`/`timed_out` past it --
and, in `test_two_workflows_with_different_external_timeouts_are_each_judged_
by_their_own`, against two runs of identical age whose only difference is
which workflow they belong to. A reaper holding one global external timeout
cannot produce that outcome, which is the same shape #1702's executor used
when it deleted `_DEFAULT_TERMINATION_POLICY`.

**What the SQLite `session` fixture does and does not prove.** It is in-memory
SQLite, so `_enumerate_active_runs` takes its non-Postgres branch and neither
RLS nor `with_shop_scope` does anything, and SQLite does not enforce the
widened `ck_workflow_runs_status` CHECK. What is proven here is the transition,
the per-run policy resolution and the threshold arithmetic. That the CHECK and
the partial index really accept the new value is
`tests/unit/test_waiting_external_migration.py`'s job, and that the fleet
enumeration hands these rows to the reaper under RLS stays
`tests/integration/test_reaper_two_tenant.py`'s.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import Product, Shop, User, WorkflowRun
from juli_backend.services.agent import playbooks as playbooks_module
from juli_backend.services.agent.events import InMemoryEventSink
from juli_backend.services.agent.llm.fake import FakeLLMService
from juli_backend.services.agent.playbooks.optimize_product import (
    OPTIMIZE_PRODUCT_PLAYBOOK,
    OPTIMIZE_PRODUCT_TERMINATION_POLICY,
)
from juli_backend.services.agent.runner.conversation_store import JsonbConversationStore
from juli_backend.services.agent.runner.core import ExternalWaitNotPermitted, WorkflowRunner
from juli_backend.services.agent.runner.state import RunState
from juli_backend.services.agent.status import StopReason, WorkflowRunStatus
from juli_backend.services.agent.tools import ToolRegistry
from juli_backend.services.agent.tools.product import register_product_read_tools
from juli_backend.services.agent.tools.product_write import register_product_write_tools
from juli_backend.services.agent.tools.terminal import register_terminal_tools
from juli_backend.workers.tasks import reaper
from tests.support.workflow_registry import TEST_WORKFLOW_KEY, make_test_playbook

NOW = datetime(2026, 9, 22, 12, 0, 0, tzinfo=UTC)

#: The supplier-wait shape the acceptance criteria name: 72 hours, three days,
#: eighteen times `approval_timeout_h`. Large enough that a run judged by the
#: consent timer instead would die on its first tick.
EXTERNAL_WAIT_H = 72

#: A second registered workflow with a DIFFERENT external timeout. The pair is
#: what makes "its own workflow's timeout" checkable at all.
OTHER_WORKFLOW_KEY = "test_only_workflow_1706_short"
OTHER_EXTERNAL_WAIT_H = 24

WAIT_REASON = "supplier_delivery"


def _never_live(_run_id: uuid.UUID) -> bool:
    return False


def _full_registry() -> ToolRegistry:
    registry = ToolRegistry()
    register_product_read_tools(registry)
    register_product_write_tools(registry)
    register_terminal_tools(registry)
    return registry


@pytest_asyncio.fixture
async def shop(session: AsyncSession) -> Shop:
    user = User(id=uuid.uuid4(), phone=f"+8490{uuid.uuid4().int % 10_000_000:07d}")
    s = Shop(id=uuid.uuid4(), user_id=user.id, shop_name="External wait shop")
    session.add_all([user, s])
    await session.flush()
    return s


@pytest_asyncio.fixture
async def product(session: AsyncSession, shop: Shop) -> Product:
    p = Product(
        id=uuid.uuid4(),
        shop_id=shop.id,
        tiktok_product_id="tiktok_product_1706",
        name="External wait product",
        status="active",
        update_time=datetime.now(UTC),
    )
    session.add(p)
    await session.flush()
    return p


async def _seed_run(
    session: AsyncSession,
    shop: Shop,
    product: Product,
    *,
    workflow_key: str,
    subject_ref: str | None = None,
) -> uuid.UUID:
    """A `running` run, exactly as the worker leaves one mid-loop.

    Seeded `running` on purpose: the only way it reaches `waiting_external` in
    any test below is by the runner putting it there.
    """
    run = WorkflowRun(
        id=uuid.uuid4(),
        shop_id=shop.id,
        product_id=product.id,
        workflow_key=workflow_key,
        subject_ref=subject_ref or str(product.id),
        state=RunState().to_dict(),
        status=WorkflowRunStatus.RUNNING.value,
        prompt_version="optimize_product.v1",
        prompt_sha256="0" * 64,
    )
    session.add(run)
    await session.flush()
    return run.id


def _runner(session: AsyncSession, playbook) -> WorkflowRunner:
    """A real `WorkflowRunner` over a real `JsonbConversationStore`.

    The LLM service, tool executor and event sink are the repo's own fakes
    rather than doubles invented here, and none of them is reached:
    `enter_external_wait` composes no prompt and dispatches nothing. What
    matters is that the store and the playbook are the real objects, because
    they are what the transition actually reads and writes.
    """
    return WorkflowRunner(
        llm_service=FakeLLMService(script=[]),
        tool_executor=_NeverCalledToolExecutor(),
        event_sink=InMemoryEventSink(),
        conversation_store=JsonbConversationStore(session),
        registry=_full_registry(),
        playbook=playbook,
    )


class _NeverCalledToolExecutor:
    """`ToolExecutor`'s real keyword-only signature, dispatching nothing.

    Bound to the real shape rather than `**kwargs` so a future change to the
    protocol fails here instead of being silently absorbed.
    """

    def __init__(self) -> None:
        self.calls: list[str] = []

    def execute(self, *, tool_name: str, params, tool_call_id: str | None = None):
        self.calls.append(tool_name)
        raise AssertionError("enter_external_wait must dispatch no tool")


async def _reload(session: AsyncSession, run_id: uuid.UUID) -> WorkflowRun:
    row = await session.get(WorkflowRun, run_id)
    assert row is not None
    return row


async def _park_externally(
    session: AsyncSession,
    shop: Shop,
    product: Product,
    playbook,
    *,
    since: datetime,
    subject_ref: str | None = None,
    reason: str = WAIT_REASON,
) -> uuid.UUID:
    """Drive a real run into `waiting_external`, then move only the clock.

    The status, the stop reason and the reason string are all written by
    `enter_external_wait`. The single field overwritten afterwards is
    `waiting_external_since`, because the runner stamps "now" and these tests
    need a run that entered the state hours or days ago -- the alternative is
    sleeping, or injecting a clock into a column write that has none. The
    stamp itself is asserted to have been made by the runner in
    `test_a_run_enters_waiting_external_only_through_the_runner_transition`,
    so nothing here is standing in for the production write.
    """
    run_id = await _seed_run(
        session, shop, product, workflow_key=playbook.workflow_key, subject_ref=subject_ref
    )
    await _runner(session, playbook).enter_external_wait(run_id, reason=reason)
    row = await _reload(session, run_id)
    assert row.waiting_external_since is not None, "the runner must stamp the instant itself"
    row.waiting_external_since = since
    await session.flush()
    return run_id


# ---------------------------------------------------------------------------
# Entering the state -- the producer half.
# ---------------------------------------------------------------------------


async def test_a_run_enters_waiting_external_only_through_the_runner_transition(
    session: AsyncSession, shop: Shop, product: Product
):
    """AC1's producer: the real transition writes every field the reaper and
    #1708 later read, and writes none of the fields a TERMINAL exit would."""
    playbook = make_test_playbook(external_wait_timeout_h=EXTERNAL_WAIT_H)
    with playbooks_module.playbook_registered_for_test(playbook):
        run_id = await _seed_run(session, shop, product, workflow_key=TEST_WORKFLOW_KEY)

        result = await _runner(session, playbook).enter_external_wait(run_id, reason=WAIT_REASON)

        assert result.status == WorkflowRunStatus.WAITING_EXTERNAL
        assert result.stop_reason == StopReason.PAUSED_FOR_EXTERNAL_WAIT

        row = await _reload(session, run_id)
        assert row.status == "waiting_external"
        assert row.stop_reason == "paused_for_external_wait"
        assert row.waiting_external_since is not None
        assert row.external_wait_reason == WAIT_REASON
        # The three facts that separate SUSPENDED from TERMINAL. `completed_at`
        # is the one a derived "everything minus the exceptions" terminal set
        # would have stamped (`conversation_store.py::_TERMINAL_STATUSES`), and
        # a suspended run carrying a completion time reads as finished on every
        # surface that shows one.
        assert row.completed_at is None
        assert row.waiting_approval_since is None


async def test_the_reason_reaches_the_column_the_webhook_dispatcher_will_match_on(
    session: AsyncSession, shop: Shop, product: Product
):
    """`reason` is a recorded fact, not a decorative argument.

    #1708 finds "the single run in `waiting_external` whose subject and awaited
    condition match" a persisted webhook signal. The subject is already on the
    row; the awaited condition is this column. A `reason` that went nowhere
    would leave every externally-waiting run unwakeable, and the defect would
    surface two slices later as "the dispatcher matches nothing".
    """
    playbook = make_test_playbook(external_wait_timeout_h=EXTERNAL_WAIT_H)
    with playbooks_module.playbook_registered_for_test(playbook):
        run_id = await _seed_run(session, shop, product, workflow_key=TEST_WORKFLOW_KEY)
        await _runner(session, playbook).enter_external_wait(run_id, reason="activity_expiry")

        row = await _reload(session, run_id)
        assert row.external_wait_reason == "activity_expiry"
        # ...and it survives a reload of the state blob too, so a resume leg
        # reading `RunState` sees the same string the column holds.
        assert RunState.from_dict(row.state).external_wait_reason == "activity_expiry"


async def test_an_unnamed_wait_is_refused(session: AsyncSession, shop: Shop, product: Product):
    """A wait with no named condition is a run nothing can ever wake."""
    playbook = make_test_playbook(external_wait_timeout_h=EXTERNAL_WAIT_H)
    with playbooks_module.playbook_registered_for_test(playbook):
        run_id = await _seed_run(session, shop, product, workflow_key=TEST_WORKFLOW_KEY)
        runner = _runner(session, playbook)

        with pytest.raises(ValueError, match="non-empty reason"):
            await runner.enter_external_wait(run_id, reason="   ")

        assert (await _reload(session, run_id)).status == "running"


async def test_workflow_without_external_wait_cannot_enter_it(
    session: AsyncSession, shop: Shop, product: Product
):
    """AC3, and the guarantee that `optimize_product_2` is untouched by this
    slice BY CONSTRUCTION rather than by convention.

    `external_wait_timeout_h = None` means "may not wait", never "wait
    forever" -- and the refusal is what makes that reading safe, because a run
    parked in a state its own policy has no timeout for could never be reaped.
    Asserted against the REAL Optimize Product playbook, not a stand-in with
    the field blanked: the claim is about the shipped workflow.
    """
    assert OPTIMIZE_PRODUCT_TERMINATION_POLICY.external_wait_timeout_h is None

    run_id = await _seed_run(
        session, shop, product, workflow_key=OPTIMIZE_PRODUCT_PLAYBOOK.workflow_key
    )
    runner = _runner(session, OPTIMIZE_PRODUCT_PLAYBOOK)

    with pytest.raises(ExternalWaitNotPermitted, match=OPTIMIZE_PRODUCT_PLAYBOOK.workflow_key):
        await runner.enter_external_wait(run_id, reason=WAIT_REASON)

    row = await _reload(session, run_id)
    assert row.status == "running", "the refusal must happen before anything is persisted"
    assert row.waiting_external_since is None
    assert row.external_wait_reason is None


async def test_the_running_clock_is_not_charged_for_the_wait(
    session: AsyncSession, shop: Shop, product: Product
):
    """The wall-clock budget is paused while waiting (ADR-073 d.2's rule,
    extended to the new state).

    Asserted on the value the runner computes and persists, not on wall-clock
    arithmetic in the test: `enter_external_wait` writes the accumulator it
    was given and adds nothing to it, and nothing accumulates while the run
    sits. A run that waits three days comes back with the running budget it
    had when it left.
    """
    playbook = make_test_playbook(external_wait_timeout_h=EXTERNAL_WAIT_H)
    with playbooks_module.playbook_registered_for_test(playbook):
        run_id = await _seed_run(session, shop, product, workflow_key=TEST_WORKFLOW_KEY)
        row = await _reload(session, run_id)
        state = RunState.from_dict(row.state)
        state.running_seconds_elapsed = 41.6
        row.state = state.to_dict()
        row.running_seconds_elapsed = 42
        await session.flush()

        await _runner(session, playbook).enter_external_wait(run_id, reason=WAIT_REASON)

        row = await _reload(session, run_id)
        assert row.running_seconds_elapsed == 42
        assert RunState.from_dict(row.state).running_seconds_elapsed == 41.6


# ---------------------------------------------------------------------------
# Leaving the state -- the reaper half.
# ---------------------------------------------------------------------------


async def test_external_wait_is_reaped_by_its_own_timeout_not_the_approval_timeout(
    session: AsyncSession, shop: Shop, product: Product
):
    """AC2, both directions, through the REAL `reap_workflow_runs` with no
    policy injected and no sink injected.

    At 5 h the run is untouched -- and 5 h is chosen deliberately: it is PAST
    `approval_timeout_h` (4 h), so a reaper that judged this run by the
    approval timer would kill it here. At 73 h, one hour past its own 72, it
    ends `external_wait_expired`/`timed_out`.
    """
    assert OPTIMIZE_PRODUCT_TERMINATION_POLICY.approval_timeout_h == 4
    playbook = make_test_playbook(external_wait_timeout_h=EXTERNAL_WAIT_H, approval_timeout_h=4)
    with playbooks_module.playbook_registered_for_test(playbook):
        run_id = await _park_externally(
            session, shop, product, playbook, since=NOW - timedelta(hours=5)
        )

        result = await reaper.reap_workflow_runs(session, now=NOW, has_live_task=_never_live)

        assert result.expired_external_waits_reaped == ()
        assert result.expired_approvals_reaped == (), (
            "the approval sweep must not even SELECT an externally-waiting run -- "
            "5h is past its 4h approval_timeout_h"
        )
        row = await _reload(session, run_id)
        assert row.status == "waiting_external"
        assert row.stop_reason == "paused_for_external_wait"

        # Move only the clock: same run, same policy, 73 hours of waiting.
        row.waiting_external_since = NOW - timedelta(hours=73)
        await session.flush()

        result = await reaper.reap_workflow_runs(session, now=NOW, has_live_task=_never_live)

        assert result.expired_external_waits_reaped == (run_id,)

    row = await _reload(session, run_id)
    assert row.status == "timed_out"
    assert row.stop_reason == "external_wait_expired"
    assert row.completed_at is not None


async def test_two_workflows_with_different_external_timeouts_are_each_judged_by_their_own(
    session: AsyncSession, shop: Shop, product: Product
):
    """The mutation-proof shape, copied from #1702's per-workflow policy tests.

    Two runs, identical in every respect including how long they have been
    waiting (30 h), differing only in which workflow they belong to: one with
    a 72 h external timeout, one with 24 h. Exactly one is reaped. A reaper
    holding a single global external timeout produces "both" or "neither" for
    every possible value of that constant, and so cannot pass this test.
    """
    long_playbook = make_test_playbook(external_wait_timeout_h=EXTERNAL_WAIT_H)
    short_playbook = make_test_playbook(
        workflow_key=OTHER_WORKFLOW_KEY, external_wait_timeout_h=OTHER_EXTERNAL_WAIT_H
    )
    with (
        playbooks_module.playbook_registered_for_test(long_playbook),
        playbooks_module.playbook_registered_for_test(short_playbook),
    ):
        waited_30h = NOW - timedelta(hours=30)
        long_run = await _park_externally(
            session, shop, product, long_playbook, since=waited_30h, subject_ref="subject-long"
        )
        short_run = await _park_externally(
            session, shop, product, short_playbook, since=waited_30h, subject_ref="subject-short"
        )

        result = await reaper.reap_workflow_runs(session, now=NOW, has_live_task=_never_live)

        assert result.expired_external_waits_reaped == (short_run,), (
            "only the run whose OWN workflow expires at 24h is past its timeout at "
            "30h; the other workflow's is 72h"
        )

    assert (await _reload(session, long_run)).status == "waiting_external"
    short = await _reload(session, short_run)
    assert short.status == "timed_out"
    assert short.stop_reason == "external_wait_expired"


async def test_a_waiting_external_run_whose_policy_forbids_waiting_is_left_alone_and_logged(
    session: AsyncSession, shop: Shop, product: Product, caplog
):
    """A row the runner refuses to create means this module and the runner
    disagree, and the destructive act is the wrong answer to a disagreement.

    The run here has waited 1000 hours, so "not reaped" can only mean the
    reaper declined to judge it -- not that some other threshold happened to
    spare it. It is skipped AND named, because a row the reaper will silently
    ignore forever is a row nobody can find.
    """
    permitting = make_test_playbook(external_wait_timeout_h=EXTERNAL_WAIT_H)
    with playbooks_module.playbook_registered_for_test(permitting):
        run_id = await _park_externally(
            session, shop, product, permitting, since=NOW - timedelta(hours=1000)
        )

    # Re-register the SAME key with the capability withdrawn -- the state the
    # row can outlive a policy edit into.
    forbidding = make_test_playbook(external_wait_timeout_h=None)
    with playbooks_module.playbook_registered_for_test(forbidding):
        with caplog.at_level("WARNING", logger="juli_backend.workers.tasks.reaper"):
            result = await reaper.reap_workflow_runs(session, now=NOW, has_live_task=_never_live)

        assert result.expired_external_waits_reaped == ()
        records = [r for r in caplog.records if r.message == "reaper_external_wait_without_timeout"]
        assert records, "the reaper must say which run it could not judge"
        assert records[0].run_id == str(run_id)
        assert records[0].workflow_key == TEST_WORKFLOW_KEY

    row = await _reload(session, run_id)
    assert row.status == "waiting_external"
    assert row.stop_reason == "paused_for_external_wait"


async def test_an_unregistered_workflow_key_never_reaps_an_external_wait(
    session: AsyncSession, shop: Shop, product: Product
):
    """The same fail-closed direction `_policy_for_run` already takes for the
    other two sweeps, reproduced for this one: an unresolvable policy is never
    a licence to use some other workflow's numbers."""
    playbook = make_test_playbook(external_wait_timeout_h=EXTERNAL_WAIT_H)
    with playbooks_module.playbook_registered_for_test(playbook):
        run_id = await _park_externally(
            session, shop, product, playbook, since=NOW - timedelta(hours=1000)
        )

    # Outside the context the key resolves to nothing at all.
    result = await reaper.reap_workflow_runs(session, now=NOW, has_live_task=_never_live)

    assert run_id not in result.expired_external_waits_reaped
    assert (await _reload(session, run_id)).status == "waiting_external"


async def test_the_stale_sweep_never_selects_an_externally_waiting_run(
    session: AsyncSession, shop: Shop, product: Product
):
    """The third sweep's boundary, asserted from the other side.

    `_reap_stale_running_and_queued` reaps on SILENCE -- no event for
    `wall_clock_timeout_s` plus the slack, with no live Celery task. An
    externally-waiting run emits nothing for days by design and has no live
    task by design, so if it were in that sweep's status filter it would be
    stamped `worker_lost`/`failed` within minutes of entering the state: the
    single most misleading verdict available, since nothing was lost.
    """
    playbook = make_test_playbook(external_wait_timeout_h=EXTERNAL_WAIT_H)
    with playbooks_module.playbook_registered_for_test(playbook):
        run_id = await _park_externally(
            session, shop, product, playbook, since=NOW - timedelta(hours=5)
        )

        result = await reaper.reap_workflow_runs(session, now=NOW, has_live_task=_never_live)

        assert result.stale_runs_reaped == ()

    row = await _reload(session, run_id)
    assert row.status == "waiting_external"
    assert row.stop_reason != "worker_lost"


async def test_the_three_sweeps_report_separately(
    session: AsyncSession, shop: Shop, product: Product
):
    """One tick, one run in each state, three independent verdicts.

    `ReapResult` keeps the external waits in their own field for exactly this:
    a test that could not tell the sweeps apart could not prove the approval
    timer left the supplier wait alone, which is the whole acceptance
    criterion.
    """
    playbook = make_test_playbook(external_wait_timeout_h=EXTERNAL_WAIT_H, approval_timeout_h=1)
    with playbooks_module.playbook_registered_for_test(playbook):
        external_run = await _park_externally(
            session,
            shop,
            product,
            playbook,
            since=NOW - timedelta(hours=100),
            subject_ref="subject-external",
        )
        approval_run_id = await _seed_run(
            session, shop, product, workflow_key=TEST_WORKFLOW_KEY, subject_ref="subject-approval"
        )
        approval_row = await _reload(session, approval_run_id)
        approval_row.status = WorkflowRunStatus.WAITING_APPROVAL.value
        approval_row.waiting_approval_since = NOW - timedelta(hours=2)
        await session.flush()

        result = await reaper.reap_workflow_runs(session, now=NOW, has_live_task=_never_live)

        assert result.expired_external_waits_reaped == (external_run,)
        assert result.expired_approvals_reaped == (approval_run_id,)
        assert result.stale_runs_reaped == ()

    assert (await _reload(session, external_run)).stop_reason == "external_wait_expired"
    assert (await _reload(session, approval_run_id)).stop_reason == "confirmation_expired"
