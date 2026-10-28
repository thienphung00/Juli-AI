"""P70 (owner, 2026-10-28): the partner reviewer may "Hoàn tác" on the writable sandbox pin.

``POST /v1/demo/runs/{run_id}/revert`` (``demo_run_changes:start_run_revert``) is on
``api/reviewer.py`` ``SANDBOX_RUN_ENDPOINTS``, exactly like Duyệt:

- on the sandbox pin, for a run the reviewer started (P66: it approved the run's card), it
  creates a queued revert run that is the reviewer's (same card, ``started_by_user_id`` in its
  plan, ``started_by_viewer`` on the runs list), audited ``reviewer_sandbox_revert``; the run
  pauses at the same CONFIRM step before any TikTok write, and the confirmed write is resolved
  on the same sandbox write leg as Duyệt's (``_write_resources_for_leg``);
- a run the reviewer did not start is a 404 -- nothing created;
- on any other pin (Fujiwa, another seller, the sandbox shop turned production) it is 403
  ``sandbox_only`` with a ``reviewer_write_refused`` audit row -- nothing created, no client.

Real signed tokens through the real ``get_current_user`` (the gate lives there), SQLite.
"""

from __future__ import annotations

import copy
import uuid
from typing import Any

import pytest
from sqlalchemy import select

from juli_backend.api.routes import demo_run_changes
from juli_backend.models.models import (
    ActionCard,
    ActionCardApproval,
    ProductionWriteShop,
    WorkflowRun,
)
from juli_backend.models.ops import OpsAuditLog
from juli_backend.models.run_changes import RunWriteValue
from juli_backend.repositories import utc_now_naive
from juli_backend.services import run_changes
from juli_backend.services.agent.events import InMemoryEventSink
from juli_backend.services.agent.runner.concurrency import ConcurrencyGuard
from juli_backend.services.agent.runner.core import WorkflowRunner
from juli_backend.services.agent.runner.tool_executor import ProductToolExecutor
from juli_backend.services.agent.status import WorkflowRunStatus
from juli_backend.services.reviewer.config import shop_alias_id
from tests.support.api import build_app, client_for
from tests.unit import test_reviewer_sandbox_live as p64
from tests.unit import test_run_changes_revert as p8c

reviewer_env = p64.reviewer_env
world = p64.world
#: SQLite's ``uq_workflow_runs_active_shop_product`` recreated partial, as Postgres has it, so a
#: finished run and its revert may share a subject (``test_run_changes_revert.db``).
db = p8c.db


@pytest.fixture(autouse=True)
def _partial_active_run_index(db):
    return db


ORIGINAL_TITLE = "Sandbox áo thun"
JULI_TITLE = "Áo thun cotton Juli viết"
REASON = {"reason_code": "metrics_dropped"}


async def _written_run(session, shop, product, *, approved_by: uuid.UUID) -> WorkflowRun:
    """A finished listing run on ``shop``, its card approved by ``approved_by``; wrote a title."""
    card = ActionCard(
        id=uuid.uuid4(), shop_id=shop.id, workflow_key="optimize_product_2",
        subject_type="product", subject_id=str(product.id), revision=7, priority=0,
        severity="medium", title="Tối ưu tiêu đề", description="", recommendation_payload="{}",
        status="approved",
    )  # fmt: skip
    session.add(card)
    await session.flush()
    session.add(
        ActionCardApproval(
            action_card_id=card.id,
            approved_by_user_id=approved_by,
            approved_at=utc_now_naive(),
            card_snapshot={},
        )
    )
    run = WorkflowRun(
        shop_id=shop.id, product_id=product.id, action_card_id=card.id,
        workflow_key="optimize_product_2", subject_type="product",
        subject_ref=f"{product.id}#7", state={}, status="completed",
        stop_reason="final_response", prompt_version="v", prompt_sha256="a" * 64,
        write_mode="simulated", completed_at=utc_now_naive(),
    )  # fmt: skip
    session.add(run)
    await session.flush()
    session.add(
        RunWriteValue(
            shop_id=shop.id,
            workflow_run_id=run.id,
            tool_call_id="call_w1",
            tool_name="update_product_listing",
            tiktok_product_id=product.tiktok_product_id,
            field="title",
            before_value=ORIGINAL_TITLE,
            after_value=JULI_TITLE,
            after_source="read_back",
        )
    )
    await session.commit()
    return run


def _live(title: str):
    async def _read(session, shop_id, tiktok_product_id, write_mode=None):
        return {"id": tiktok_product_id, "title": title}

    return _read


@pytest.fixture
def enqueued(monkeypatch) -> list[uuid.UUID]:
    queued: list[uuid.UUID] = []
    monkeypatch.setattr(
        demo_run_changes,
        "_enqueue_run_agent_workflow",
        lambda run_id: queued.append(run_id) or "celery-revert",
    )
    return queued


def _app(session, *, live_title: str = JULI_TITLE):
    app = build_app(session)
    app.dependency_overrides[demo_run_changes.get_live_product_reader] = lambda: _live(live_title)
    return app


async def _reverts(session, original_id: uuid.UUID) -> list[WorkflowRun]:
    session.expire_all()
    return list(
        (
            await session.execute(
                select(WorkflowRun).where(WorkflowRun.reverts_run_id == original_id)
            )
        )
        .scalars()
        .all()
    )


async def _audits(session, action: str) -> list[dict[str, Any]]:
    session.expire_all()
    rows = await session.execute(select(OpsAuditLog.after).where(OpsAuditLog.action == action))
    return [after for (after,) in rows.all()]


async def test_reviewer_reverts_its_own_run_on_the_sandbox_pin(
    session, world, monkeypatch, enqueued
):
    sandbox, _, _, reviewer_id = world
    shop_id = sandbox.shop.id
    original = await _written_run(session, sandbox.shop, sandbox.product, approved_by=reviewer_id)
    original_id, card_id = original.id, original.action_card_id
    recorder = p64.FactoryRecorder(monkeypatch)

    async with client_for(_app(session)) as client:
        response = await client.post(
            f"/v1/demo/runs/{original_id}/revert",
            json=REASON,
            headers=p64._headers(reviewer_id, shop_id),
        )
        listed = await client.get("/v1/demo/runs", headers=p64._headers(reviewer_id, shop_id))

    assert response.status_code == 202, response.text
    data = response.json()["data"]
    assert data["reverts_run_id"] == str(original_id)
    assert data["status"] == "queued" and data["fields"] == ["title"]
    [revert] = await _reverts(session, original_id)
    assert str(revert.id) == data["run_id"]
    assert enqueued == [revert.id]
    # The revert run is the reviewer's: the card it approved, and it is named as the starter.
    assert revert.action_card_id == card_id
    assert revert.shop_id == shop_id
    plan = run_changes.revert_plan_from_state(revert.state)
    assert plan is not None
    assert plan.started_by_user_id == str(reviewer_id)
    assert plan.restore == {"title": ORIGINAL_TITLE}
    by_id = {item["id"]: item for item in listed.json()["data"]}
    assert by_id[str(revert.id)]["started_by_viewer"] is True
    # The request built no TikTok client (the live check is the reader seam here).
    assert recorder.forbidden == []
    revert_id = revert.id
    [audit] = await _audits(session, "reviewer_sandbox_revert")
    assert audit["run_id"] == str(revert_id)
    assert audit["reverts_run_id"] == str(original_id)
    assert audit["platform"] == "shopee"


async def test_the_reviewers_revert_run_pauses_for_its_confirmation_before_writing(
    session, world, monkeypatch, enqueued
):
    """The plan the route stored drives the real runner to the CONFIRM pause: nothing written."""
    sandbox, _, _, reviewer_id = world
    original = await _written_run(session, sandbox.shop, sandbox.product, approved_by=reviewer_id)
    async with client_for(_app(session)) as client:
        response = await client.post(
            f"/v1/demo/runs/{original.id}/revert",
            json=REASON,
            headers=p64._headers(reviewer_id, sandbox.shop.id),
        )
    assert response.status_code == 202, response.text
    [revert] = await _reverts(session, original.id)
    plan = run_changes.revert_plan_from_state(revert.state)
    assert plan is not None

    detail = copy.deepcopy(p8c.DETAIL)
    detail["title"] = JULI_TITLE
    products = p8c.FakeProducts(detail)
    resources = p8c._resources(products)
    registry = p8c._registry()
    guard = ConcurrencyGuard()
    store, sink = p8c.InMemoryStore(), InMemoryEventSink()
    runner = WorkflowRunner(
        llm_service=run_changes.RevertPlanner(plan),
        tool_executor=ProductToolExecutor(
            registry=registry,
            read_resources=resources,
            write_resources=resources,
            product_id=p8c.PRODUCT_ID,
            concurrency_guard=guard,
            revert_expected=plan.expected,
            revert_expected_hashes=plan.expected_hashes,
        ),
        event_sink=sink,
        conversation_store=store,
        registry=registry,
        playbook=run_changes.REVERT_LISTING_PLAYBOOK,
        concurrency_guard=guard,
    )
    paused = await runner.run(revert.id, product_ref=p8c.PRODUCT_ID)

    assert paused.status == WorkflowRunStatus.WAITING_APPROVAL
    assert products.edits == [], "nothing is written before the reviewer confirms"
    [approval] = [e for e in sink.events if e.event_type == "workflow.approval_required"]
    assert approval.payload.tool_name == "update_product_listing"
    assert approval.payload.proposed_change == {"title": ORIGINAL_TITLE}


async def test_the_confirmed_revert_write_takes_the_same_sandbox_leg_as_duyet(
    session, world, monkeypatch, enqueued
):
    """The resume leg of the reviewer's revert run resolves to the default (sandbox) write
    resources, exactly as an approved Duyệt run on the sandbox shop does -- never production."""
    from juli_backend.workers.tasks import agent_workflow

    sandbox, _, _, reviewer_id = world
    original = await _written_run(session, sandbox.shop, sandbox.product, approved_by=reviewer_id)
    async with client_for(_app(session)) as client:
        response = await client.post(
            f"/v1/demo/runs/{original.id}/revert",
            json=REASON,
            headers=p64._headers(reviewer_id, sandbox.shop.id),
        )
    assert response.status_code == 202, response.text
    [revert] = await _reverts(session, original.id)
    revert.state = {
        **revert.state,
        "pending_confirmation": {
            "call_id": "call_revert",
            "tool_name": "update_product_listing",
            "arguments": {"title": ORIGINAL_TITLE},
        },
    }
    await session.commit()

    sandbox_resources = object()

    async def _sandbox(_session):
        return sandbox_resources

    monkeypatch.setattr(agent_workflow, "_default_write_resources", _sandbox)
    product = sandbox.product
    await session.refresh(revert)
    await session.refresh(product)
    resources, live_call, live_leg = await agent_workflow._write_resources_for_leg(
        session,
        revert,
        product,
        resume_approved=True,
        staged_image=False,
        is_revert=True,
    )
    assert resources is sandbox_resources
    assert live_call is None and live_leg is None
    assert revert.write_mode != "live"


async def test_reviewer_cannot_revert_a_run_it_did_not_start(session, world, monkeypatch, enqueued):
    sandbox, _, _, reviewer_id = world
    team_run = await _written_run(
        session, sandbox.shop, sandbox.product, approved_by=sandbox.owner.id
    )
    team_run_id = team_run.id
    async with client_for(_app(session)) as client:
        response = await client.post(
            f"/v1/demo/runs/{team_run_id}/revert",
            json=REASON,
            headers=p64._headers(reviewer_id, sandbox.shop.id),
        )
    assert response.status_code == 404, response.text
    assert await _reverts(session, team_run_id) == []
    assert enqueued == []
    assert await _audits(session, "reviewer_sandbox_revert") == []


async def test_a_seller_still_reverts_its_own_run(session, world, monkeypatch, enqueued):
    """The sandbox shop's own owner (a plain seller token): unchanged, and never audited."""
    sandbox, _, _, _ = world
    owner = sandbox.owner.id
    run = await _written_run(session, sandbox.shop, sandbox.product, approved_by=owner)
    async with client_for(_app(session)) as client:
        response = await client.post(
            f"/v1/demo/runs/{run.id}/revert",
            json=REASON,
            headers=p64._headers(owner, sandbox.shop.id, platform=None, email="o@gmail.com"),
        )
    assert response.status_code == 202, response.text
    assert len(await _reverts(session, run.id)) == 1
    assert await _audits(session, "reviewer_sandbox_revert") == []


@pytest.mark.parametrize("pin", ["fujiwa", "seller", "production_sandbox"])
async def test_reviewer_revert_on_any_other_pin_is_403_sandbox_only_and_audited(
    session, world, monkeypatch, enqueued, pin
):
    sandbox, fujiwa, seller, reviewer_id = world
    target = {"fujiwa": fujiwa, "seller": seller, "production_sandbox": sandbox}[pin]
    if pin == "production_sandbox":
        # The sandbox shop turned production: writes disabled, masked again.
        session.add(ProductionWriteShop(shop_id=sandbox.shop.id, enabled_by="owner"))
        await session.commit()
    run = await _written_run(session, target.shop, target.product, approved_by=reviewer_id)
    monkeypatch.setenv("REVIEWER_SHOP_ID", str(target.shop.id))
    recorder = p64.FactoryRecorder(monkeypatch)
    async with client_for(_app(session)) as client:
        response = await client.post(
            f"/v1/demo/runs/{run.id}/revert",
            json=REASON,
            headers=p64._headers(reviewer_id, shop_alias_id(target.shop.id)),
        )
    assert response.status_code == 403, response.text
    assert response.headers["x-juli-reviewer-denied"] == "sandbox_only"
    assert await _reverts(session, run.id) == []
    assert enqueued == [] and recorder.forbidden == []
    refusals = await _audits(session, "reviewer_write_refused")
    assert [r["endpoint"].rsplit(":", 1)[1] for r in refusals] == ["start_run_revert"]
    assert {r["reason"] for r in refusals} == {"sandbox_only"}
