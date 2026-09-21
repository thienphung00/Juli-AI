"""The reaper judges each run by ITS OWN workflow's termination policy
(issue #1702, W9-A/P-SHARED-2).

Before this slice `workers/tasks/reaper.py` held one module constant,
`_DEFAULT_TERMINATION_POLICY = OPTIMIZE_PRODUCT_TERMINATION_POLICY`, and
scored every row against it. Its `policy=` parameter was an injection seam
no production call site used, which meant the tests proving "the thresholds
move with the policy" were the ones supplying the policy. That seam is gone:
`reap_workflow_runs` takes no policy at all, and the only path to a
threshold is `workflow_runs.workflow_key` -> the playbook registry.

Every test below calls `reap_workflow_runs` with NO policy argument and
asserts on WHICH runs were reaped, with two runs of identical age differing
only in their workflow key. A reaper holding one global threshold cannot
produce these outcomes.

**What the SQLite `session` fixture does and does not prove.** It is an
in-memory SQLite database, so `_enumerate_active_runs` takes its non-Postgres
branch (an ordinary `SELECT`) and neither RLS nor `with_shop_scope` does
anything. What is proven here is the per-run resolution and the threshold
arithmetic. That the same resolution survives the real fleet enumeration --
the `enumerate_active_workflow_runs()` SECURITY DEFINER function, the
per-run `with_shop_scope`, and RLS as `juli_app` -- is proven against real
Postgres by `tests/integration/test_reaper_two_tenant.py::
test_each_run_is_reaped_by_its_own_workflows_policy_as_juli_app`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest_asyncio

from juli_backend.models.models import Product, Shop, WorkflowRun
from juli_backend.services.agent import playbooks as playbooks_module
from juli_backend.services.agent.playbooks.optimize_product import (
    OPTIMIZE_PRODUCT_PLAYBOOK,
    OPTIMIZE_PRODUCT_TERMINATION_POLICY,
)
from juli_backend.workers.tasks import reaper
from tests.support.workflow_registry import TEST_WORKFLOW_KEY, make_test_playbook

NOW = datetime(2026, 9, 21, 12, 0, 0, tzinfo=UTC)
PROD_WORKFLOW_KEY = OPTIMIZE_PRODUCT_PLAYBOOK.workflow_key


def _never_live(_run_id: uuid.UUID) -> bool:
    return False


@pytest_asyncio.fixture
async def shop(session):
    s = Shop(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        shop_name="Per-workflow policy shop",
        tiktok_shop_id="tiktok_shop_1702",
    )
    session.add(s)
    await session.flush()
    return s


@pytest_asyncio.fixture
async def product(session, shop):
    p = Product(
        id=uuid.uuid4(),
        shop_id=shop.id,
        tiktok_product_id="tiktok_product_1702",
        name="Per-workflow policy product",
        status="active",
        update_time=datetime.now(UTC),
    )
    session.add(p)
    await session.flush()
    return p


async def _make_run(
    session,
    shop_id: uuid.UUID,
    product_id: uuid.UUID,
    *,
    workflow_key: str,
    status: str,
    started_at: datetime | None = None,
    waiting_approval_since: datetime | None = None,
) -> WorkflowRun:
    run = WorkflowRun(
        id=uuid.uuid4(),
        shop_id=shop_id,
        product_id=product_id,
        workflow_key=workflow_key,
        state={},
        status=status,
        prompt_version="optimize_product.v3",
        prompt_sha256="a" * 64,
        started_at=started_at,
        waiting_approval_since=waiting_approval_since,
    )
    session.add(run)
    await session.flush()
    return run


async def test_reaper_uses_each_runs_own_policy(session, shop, product):
    """AC 4: two runs whose registered policies differ in
    `approval_timeout_h` are judged by their own policy.

    Both runs have been waiting exactly 2 hours. Optimize Product's
    `approval_timeout_h` is 4 (not expired); the test workflow's is moved to
    1 (expired). Only the test workflow's run is reaped, and the other is
    left in `waiting_approval` -- neither "reap everything" nor "reap
    nothing" passes.
    """
    assert OPTIMIZE_PRODUCT_TERMINATION_POLICY.approval_timeout_h == 4

    playbook = make_test_playbook(approval_timeout_h=1)
    with playbooks_module.playbook_registered_for_test(playbook):
        prod_run = await _make_run(
            session,
            shop.id,
            product.id,
            workflow_key=PROD_WORKFLOW_KEY,
            status="waiting_approval",
            waiting_approval_since=NOW - timedelta(hours=2),
        )
        test_run = await _make_run(
            session,
            shop.id,
            product.id,
            workflow_key=TEST_WORKFLOW_KEY,
            status="waiting_approval",
            waiting_approval_since=NOW - timedelta(hours=2),
        )

        result = await reaper.reap_workflow_runs(session, now=NOW, has_live_task=_never_live)

        assert result.expired_approvals_reaped == (test_run.id,), (
            "only the run whose OWN workflow expires at 1h is past its timeout at "
            "2h; the optimize_product_2 run's timeout is 4h"
        )

    await session.refresh(prod_run)
    await session.refresh(test_run)
    assert prod_run.status == "waiting_approval"
    assert prod_run.stop_reason is None
    assert test_run.status == "cancelled"
    assert test_run.stop_reason == "confirmation_expired"


async def test_a_run_whose_workflow_is_not_registered_is_left_alone(session, shop, product):
    """A run carrying a key with no registered playbook must NOT be reaped
    under some other workflow's timeout -- a silent fallback to Optimize
    Product's 4h would reintroduce exactly the defect this slice removes.

    The run here is 100 hours past a timeout it would fail under ANY
    registered policy, so "not reaped" can only mean the reaper declined to
    judge it at all.
    """
    run = await _make_run(
        session,
        shop.id,
        product.id,
        workflow_key="retired_workflow_1702",
        status="waiting_approval",
        waiting_approval_since=NOW - timedelta(hours=100),
    )

    result = await reaper.reap_workflow_runs(session, now=NOW, has_live_task=_never_live)

    assert run.id not in result.expired_approvals_reaped
    await session.refresh(run)
    assert run.status == "waiting_approval"
    assert run.stop_reason is None


async def test_an_unregistered_workflow_key_is_reported_not_swallowed(
    session, shop, product, caplog
):
    """Leaving the row alone is only half of failing closed: the reaper must
    also SAY it could not judge the run, naming the run and the key, or an
    operator has no way to find a row the reaper will silently skip forever.
    """
    run = await _make_run(
        session,
        shop.id,
        product.id,
        workflow_key="retired_workflow_1702",
        status="waiting_approval",
        waiting_approval_since=NOW - timedelta(hours=100),
    )

    with caplog.at_level("WARNING", logger="juli_backend.workers.tasks.reaper"):
        await reaper.reap_workflow_runs(session, now=NOW, has_live_task=_never_live)

    records = [r for r in caplog.records if r.message == "reaper_unregistered_workflow_key"]
    assert records, "the reaper must log the run it could not judge"
    assert records[0].workflow_key == "retired_workflow_1702"
    assert records[0].run_id == str(run.id)


async def test_the_stale_run_threshold_also_comes_from_the_runs_own_workflow(
    session, shop, product
):
    """The same proof for the other closure. 400s of silence sits strictly
    between the test workflow's threshold (a 10s wall clock + the fixed 300s
    slack = 310s) and Optimize Product's (300 + 300 = 600s), so exactly one
    of two identically-aged runs is stale.
    """
    assert OPTIMIZE_PRODUCT_TERMINATION_POLICY.wall_clock_timeout_s == 300
    assert reaper.STALE_RUN_SLACK_S == 300

    playbook = make_test_playbook(wall_clock_timeout_s=10)
    with playbooks_module.playbook_registered_for_test(playbook):
        prod_run = await _make_run(
            session,
            shop.id,
            product.id,
            workflow_key=PROD_WORKFLOW_KEY,
            status="running",
            started_at=NOW - timedelta(seconds=400),
        )
        test_run = await _make_run(
            session,
            shop.id,
            product.id,
            workflow_key=TEST_WORKFLOW_KEY,
            status="running",
            started_at=NOW - timedelta(seconds=400),
        )

        result = await reaper.reap_workflow_runs(session, now=NOW, has_live_task=_never_live)

        assert result.stale_runs_reaped == (test_run.id,)

    await session.refresh(prod_run)
    await session.refresh(test_run)
    assert prod_run.status == "running"
    assert test_run.status == "failed"
    assert test_run.stop_reason == "worker_lost"


def test_the_reaper_holds_no_default_termination_policy():
    """The module constant that made the old behaviour possible is gone.

    Asserted on the module rather than on behaviour because its absence is
    the structural guarantee: while a `_DEFAULT_TERMINATION_POLICY` exists,
    any future edit can quietly reach for it as a fallback and every test
    above would still pass.
    """
    assert not hasattr(reaper, "_DEFAULT_TERMINATION_POLICY")
