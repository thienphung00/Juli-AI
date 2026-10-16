"""Fast track D47.5 (P38): a run that ends ``cancelled`` or ``timed_out`` puts its
approved card back to ``active`` exactly like a ``failed`` run -- through ONE
helper, ``services/agent/card_reactivation.py``.

- every terminal writer reactivates: the runner's own persist (cancelled /
  timed_out / failed), the reaper (consent lapse -> cancelled, external wait ->
  timed_out, worker_lost -> failed) and the worker crash handler (failed);
- ``completed`` never does;
- a seller decline stays ``dismissed`` (7-day cooldown): "Không thực hiện" at
  the consent step (even when the reaper then lapses the consent), "Không thực
  hiện" while a lever flow waits for the seller, and "Hoàn tác" (whose own run
  carries the same card);
- idempotent: a second transition is a no-op;
- tenant-scoped: a card of another shop is never touched;
- the 7-day expiry still applies to a reactivated card (``surfaced_at`` kept).

The Postgres / RLS half of the two-tenant proof is
``tests/integration/test_reaper_two_tenant.py``.
"""

from __future__ import annotations

import ast
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import ActionCard, WorkflowRun
from juli_backend.services.action_cards.emission_budget import apply_emission_budget
from juli_backend.services.agent import card_reactivation
from juli_backend.services.agent.playbooks.optimize_product import OPTIMIZE_PRODUCT_PLAYBOOK
from juli_backend.services.agent.runner.conversation_store import JsonbConversationStore
from juli_backend.services.agent.runner.state import RunState
from juli_backend.services.agent.status import StopReason, WorkflowRunStatus
from juli_backend.services.lever_flows import AWAITING_PHOTO
from juli_backend.workers.tasks import reaper
from tests.support.api import authenticate, authenticated_client, build_app, client_for
from tests.support.builders import make_product, make_tenant, make_workflow_run
from tests.unit import test_p10a_card_reasons_edits as p10a
from tests.unit.test_p10a_card_reasons_edits import (
    _finished_run,
    _live_title,
    _surfaced_card,
    _waiting_run,
)

#: P10-A's fixtures, reused as they are (pytest collects module attributes).
enqueued = p10a.enqueued
partial_active_run_index = p10a.partial_active_run_index

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend" / "src" / "juli_backend"


def _never_live(_run_id: uuid.UUID) -> bool:
    return False


async def _approved_card_run(
    session: AsyncSession,
    shop,
    *,
    status: str = "running",
    surfaced_days_ago: float = 1,
    **run_values,
) -> tuple[WorkflowRun, ActionCard]:
    product = await make_product(session, shop, tiktok_product_id=f"p-{uuid.uuid4().hex[:8]}")
    card = await _surfaced_card(session, shop, product)
    card.status = "approved"
    card.approved_at = datetime.now(UTC)
    card.surfaced_at = datetime.now(UTC) - timedelta(days=surfaced_days_ago)
    run = await make_workflow_run(
        session,
        shop,
        product=product,
        status=status,
        action_card_id=card.id,
        subject_ref=str(product.id),
        workflow_key=OPTIMIZE_PRODUCT_PLAYBOOK.workflow_key,
        state=RunState().to_dict(),
        **run_values,
    )
    await session.commit()
    return run, card


async def _persist_terminal(session: AsyncSession, run: WorkflowRun, status, reason) -> None:
    store = JsonbConversationStore(session)
    await store.persist(run.id, RunState(), status=status, stop_reason=reason)
    await session.commit()


async def _card(session: AsyncSession, card: ActionCard) -> ActionCard:
    await session.refresh(card)
    return card


# =========================================================================== the runner


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "reason"),
    [
        (WorkflowRunStatus.CANCELLED, StopReason.CANCELLED_BY_SELLER),
        (WorkflowRunStatus.TIMED_OUT, StopReason.WALL_CLOCK_TIMEOUT),
        (WorkflowRunStatus.TIMED_OUT, StopReason.ITERATION_CAP_EXCEEDED),
        (WorkflowRunStatus.FAILED, StopReason.LLM_ERROR),
    ],
)
async def test_runner_terminal_persist_reactivates_the_card(session, status, reason):
    _user, shop = await make_tenant(session)
    run, card = await _approved_card_run(session, shop)

    await _persist_terminal(session, run, status, reason)

    card = await _card(session, card)
    assert (card.status, card.approved_at) == ("active", None)
    assert card.surfaced_at is not None, "surfaced_at is kept: the 7-day expiry still applies"


@pytest.mark.asyncio
async def test_completed_and_suspended_runs_keep_the_card_approved(session):
    _user, shop = await make_tenant(session)
    run, card = await _approved_card_run(session, shop)
    store = JsonbConversationStore(session)
    await store.persist(
        run.id,
        RunState(),
        status=WorkflowRunStatus.WAITING_APPROVAL,
        stop_reason=StopReason.PAUSED_FOR_CONFIRMATION,
    )
    await session.commit()
    assert (await _card(session, card)).status == "approved"

    await _persist_terminal(session, run, WorkflowRunStatus.COMPLETED, StopReason.FINAL_RESPONSE)
    card = await _card(session, card)
    assert card.status == "approved" and card.approved_at is not None


@pytest.mark.asyncio
async def test_a_double_transition_is_idempotent(session):
    _user, shop = await make_tenant(session)
    run, card = await _approved_card_run(session, shop)

    await _persist_terminal(
        session, run, WorkflowRunStatus.CANCELLED, StopReason.CANCELLED_BY_SELLER
    )
    first = await _card(session, card)
    assert first.status == "active"
    # The seller dismisses it afterwards; a late second terminal write changes nothing.
    first.status = "dismissed"
    await session.commit()
    await _persist_terminal(
        session, run, WorkflowRunStatus.TIMED_OUT, StopReason.WALL_CLOCK_TIMEOUT
    )
    assert (await _card(session, card)).status == "dismissed"

    run2, card2 = await _approved_card_run(session, shop)
    assert await card_reactivation.reactivate_card_for_ended_run(
        session, run2, WorkflowRunStatus.TIMED_OUT
    )
    assert not await card_reactivation.reactivate_card_for_ended_run(
        session, run2, WorkflowRunStatus.TIMED_OUT
    )
    assert card2.status == "active"


@pytest.mark.asyncio
async def test_another_shops_card_is_never_touched(session):
    _user_a, shop_a = await make_tenant(session)
    _user_b, shop_b = await make_tenant(session)
    _run_b, card_b = await _approved_card_run(session, shop_b)
    run_a, _card_a = await _approved_card_run(session, shop_a)
    run_a.action_card_id = card_b.id  # a corrupt link must not cross tenants
    await session.commit()

    await _persist_terminal(session, run_a, WorkflowRunStatus.FAILED, StopReason.LLM_ERROR)

    card_b = await _card(session, card_b)
    assert card_b.status == "approved" and card_b.approved_at is not None


@pytest.mark.asyncio
async def test_unknown_or_non_reactivating_status_is_a_no_op(session):
    _user, shop = await make_tenant(session)
    run, card = await _approved_card_run(session, shop)
    for status in ("completed", "waiting_external", "nonsense"):
        assert not await card_reactivation.reactivate_card_for_ended_run(session, run, status)
    assert card.status == "approved"
    assert card_reactivation.REACTIVATING_RUN_STATUSES == {
        WorkflowRunStatus.FAILED,
        WorkflowRunStatus.CANCELLED,
        WorkflowRunStatus.TIMED_OUT,
    }


# =========================================================================== the reaper


@pytest.mark.asyncio
async def test_consent_lapse_cancels_the_run_and_reactivates_the_card(session):
    _user, shop = await make_tenant(session)
    now = datetime.now(UTC)
    run, card = await _approved_card_run(
        session,
        shop,
        status="waiting_approval",
        waiting_approval_since=now - timedelta(hours=5),
    )

    result = await reaper.reap_workflow_runs(session, now=now, has_live_task=_never_live)

    assert run.id in result.expired_approvals_reaped
    await session.refresh(run)
    assert (run.status, run.stop_reason) == ("cancelled", "confirmation_expired")
    card = await _card(session, card)
    assert (card.status, card.approved_at) == ("active", None)


@pytest.mark.asyncio
async def test_external_wait_timeout_times_out_the_run_and_reactivates_the_card(session):
    _user, shop = await make_tenant(session)
    now = datetime.now(UTC)
    run, card = await _approved_card_run(
        session,
        shop,
        status="waiting_external",
        external_wait_reason=AWAITING_PHOTO,
        waiting_external_since=now - timedelta(days=4),
    )

    result = await reaper.reap_workflow_runs(session, now=now, has_live_task=_never_live)

    assert run.id in result.expired_external_waits_reaped
    await session.refresh(run)
    assert (run.status, run.stop_reason) == ("timed_out", "external_wait_expired")
    card = await _card(session, card)
    assert (card.status, card.approved_at) == ("active", None)


@pytest.mark.asyncio
async def test_worker_lost_fails_the_run_and_reactivates_the_card(session):
    _user, shop = await make_tenant(session)
    now = datetime.now(UTC)
    run, card = await _approved_card_run(session, shop, started_at=now - timedelta(days=1))
    run.created_at = now - timedelta(days=1)
    await session.commit()

    result = await reaper.reap_workflow_runs(session, now=now, has_live_task=_never_live)

    assert run.id in result.stale_runs_reaped
    await session.refresh(run)
    assert (run.status, run.stop_reason) == ("failed", "worker_lost")
    assert (await _card(session, card)).status == "active"


@pytest.mark.asyncio
async def test_a_reactivated_card_older_than_seven_days_expires_and_does_not_linger(session):
    _user, shop = await make_tenant(session)
    now = datetime.now(UTC)
    old_run, old_card = await _approved_card_run(
        session,
        shop,
        status="waiting_approval",
        waiting_approval_since=now - timedelta(hours=5),
        surfaced_days_ago=8,
    )
    fresh_run, fresh_card = await _approved_card_run(
        session,
        shop,
        status="waiting_approval",
        waiting_approval_since=now - timedelta(hours=5),
        surfaced_days_ago=2,
    )
    await reaper.reap_workflow_runs(session, now=now, has_live_task=_never_live)
    assert (await _card(session, old_card)).status == "active"

    outcome = await apply_emission_budget(session, shop.id, now=now)
    await session.commit()

    assert old_card.id in {c.id for c in outcome.expired}
    assert (await _card(session, old_card)).status == "expired"
    # The fresh one is open again (it counts toward the open limit), surfaced_at kept.
    assert fresh_card.id in {c.id for c in outcome.surfaced}
    fresh_card = await _card(session, fresh_card)
    assert fresh_card.status == "active"
    assert now - fresh_card.surfaced_at.replace(tzinfo=UTC) >= timedelta(days=2) - timedelta(
        seconds=5
    )


# =========================================================================== seller declines


@pytest.mark.asyncio
async def test_declined_consent_stays_dismissed_even_when_the_consent_then_lapses(
    session, enqueued
):
    user, shop = await make_tenant(session)
    run, card, _product = await _waiting_run(session, shop)
    run.workflow_key = OPTIMIZE_PRODUCT_PLAYBOOK.workflow_key
    await session.commit()

    async with authenticated_client(session, user=user, shop=shop) as client:
        resp = await client.post(f"/v1/demo/runs/{run.id}/decline", json={"reason_code": "tone"})
    assert resp.status_code == 200, resp.text
    assert (await _card(session, card)).status == "dismissed"

    # The resume task has not run yet and the 4 h consent window passes: the
    # reaper cancels the run, and the dismissed card stays dismissed.
    run.waiting_approval_since = datetime.now(UTC) - timedelta(hours=5)
    await session.commit()
    await reaper.reap_workflow_runs(session, now=datetime.now(UTC), has_live_task=_never_live)
    await session.refresh(run)
    assert run.status == "cancelled"
    assert (await _card(session, card)).status == "dismissed"


@pytest.mark.asyncio
async def test_declining_a_lever_flow_wait_stays_dismissed(session, enqueued):
    user, shop = await make_tenant(session)
    run, card = await _approved_card_run(
        session,
        shop,
        status="waiting_external",
        external_wait_reason=AWAITING_PHOTO,
        waiting_external_since=datetime.now(UTC),
    )

    async with authenticated_client(session, user=user, shop=shop) as client:
        resp = await client.post(f"/v1/demo/runs/{run.id}/decline", json={"reason_code": "tone"})

    assert resp.status_code == 200, resp.text
    await session.refresh(run)
    assert (run.status, run.stop_reason) == ("cancelled", "cancelled_by_seller")
    card = await _card(session, card)
    assert card.status == "dismissed" and card.dismissed_at is not None


@pytest.mark.asyncio
@pytest.mark.usefixtures("partial_active_run_index")
async def test_revert_stays_dismissed_when_the_revert_run_itself_ends_badly(session, enqueued):
    from juli_backend.api.routes import demo_run_changes

    user, shop = await make_tenant(session)
    run, card, _product = await _finished_run(session, shop)
    app = build_app(session)
    authenticate(app, user=user, shop=shop)
    app.dependency_overrides[demo_run_changes.get_live_product_reader] = lambda: _live_title(
        "Juli viết"
    )
    async with client_for(app) as client:
        resp = await client.post(
            f"/v1/demo/runs/{run.id}/revert", json={"reason_code": "metrics_dropped"}
        )
    assert resp.status_code == 202, resp.text
    assert (await _card(session, card)).status == "dismissed"

    revert_run = await session.get(WorkflowRun, uuid.UUID(resp.json()["data"]["run_id"]))
    assert revert_run is not None and revert_run.action_card_id == card.id
    await _persist_terminal(
        session, revert_run, WorkflowRunStatus.CANCELLED, StopReason.CANCELLED_BY_SELLER
    )
    assert (await _card(session, card)).status == "dismissed"


# =========================================================================== one helper


def test_every_terminal_writer_uses_the_one_helper_and_no_inline_copy_is_left():
    callers = {
        "services/agent/runner/conversation_store.py",
        "workers/tasks/agent_workflow.py",
        "workers/tasks/reaper.py",
    }
    for rel in callers:
        source = (BACKEND / rel).read_text(encoding="utf-8")
        assert "reactivate_card_for_ended_run" in source, rel
    # Nobody but the helper writes ``approved_at = None``.
    writers = []
    for path in BACKEND.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if (
                    isinstance(target, ast.Attribute)
                    and target.attr == "approved_at"
                    and isinstance(node.value, ast.Constant)
                    and node.value.value is None
                ):
                    writers.append(str(path.relative_to(BACKEND)))
    assert writers == ["services/agent/card_reactivation.py"]
