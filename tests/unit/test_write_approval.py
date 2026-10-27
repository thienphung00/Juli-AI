"""ADR-116 §6, DECISIONS D76 (grill D7): a change to a client's shop needs that shop's click.

On the SQLite unit substrate (the Postgres proof of migration 106, RLS and the append-only
audit is ``tests/integration/test_write_platform_columns_db.py``):

- who may click: a user who does not belong to the shop -- a staff account, another seller,
  a partner reviewer anywhere but its writable sandbox pin -- is refused at both clicks
  (card approve, CONFIRM approve), in the service, with nothing written; the shop's owner and
  the D73 reviewer on its sandbox pin are accepted;
- the CONFIRM click freezes the exact change (who, when, card approval + snapshot hash,
  "before", "after");
- the live write leg (``composition.resolve_agent_write_leg``): a member's valid approval goes
  live; a missing approval, a non-member's, one older than 72 h (the card goes back to
  pending), a snapshot / arguments mismatch are each refused BEFORE the authorization is
  looked up, audited with their reason code, and raise -- nothing is written, not even to the
  sandbox;
- the executor's read immediately before the write: a shop that no longer shows the approved
  "before" refuses the write (no vendor call) and audits ``read_back_changed``;
- migration 106: chain, id length, additive gate, the model columns; the operator backfill.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from juli_backend.integrations.tiktok import ProductionWriteResources, reviewer_session
from juli_backend.integrations.tiktok.factories import SandboxWriteResources
from juli_backend.models.models import (
    WRITE_PLATFORM_TIKTOK,
    ActionCard,
    ActionCardApproval,
    ProductionWriteAudit,
    ProductionWriteAuthorization,
    RunConfirmation,
    Shop,
    User,
    WorkflowRun,
)
from juli_backend.orm_base import Base
from juli_backend.services import run_changes
from juli_backend.services.agent import approval as approval_module
from juli_backend.services.agent import composition, write_approval
from juli_backend.services.agent.runner import compute_params_sha
from juli_backend.services.agent.runner.tool_executor import ProductToolExecutor
from juli_backend.services.agent.runner.write_capture import ApprovedBeforeChangedError
from juli_backend.services.agent.tools import ToolRegistry
from juli_backend.services.agent.tools.product import register_product_read_tools
from juli_backend.services.agent.tools.product_write import (
    UpdateProductListingInput,
    register_product_write_tools,
)
from juli_backend.services.agent_runs import (
    ERROR_APPROVER_NOT_SHOP_MEMBER,
    ConfirmationRejected,
    decide_confirmation,
)
from juli_backend.services.execution.production_write_resolver import PreconditionName
from juli_backend.services.operations import write_platform_backfill
from tests.unit import test_p61f_agent_production_write as p61f
from tests.unit.test_p61f_agent_production_write import (
    _arm,
    _authorize,
    _consumed,
    _enable,
    _seed_shop,
)

#: The P61-F fixtures: the sandbox loader as a recorder, the fake TikTok transport.
sandbox = p61f.sandbox
transport = p61f.transport

REPO = Path(__file__).resolve().parents[2]
MIGRATIONS = REPO / "backend/src/juli_backend/database/migrations"
MIGRATION = MIGRATIONS / "versions/106_write_platform_columns.py"
BACKFILL = MIGRATIONS / "deferred/101_write_mode_backfill.py"

LISTING = "update_product_listing"
PRODUCT = "2002"
DETAIL = {"id": PRODUCT, "title": "B old", "description": "B desc"}
ARGUMENTS = {"title": "B new title", "description": "B desc"}
CALL_ID = "call-1"


def teardown_function():
    from juli_backend.services.execution import production_write_resolver

    production_write_resolver._RLS_BOOT_CHECK_PASSED = False


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


# --- fixtures -----------------------------------------------------------------------------


async def _client_shop(session):
    shop, product = await _seed_shop(session, "b", "merchant-b", PRODUCT)
    return shop, product


async def _card(session, shop, product) -> ActionCard:
    card = ActionCard(
        id=uuid.uuid4(),
        shop_id=shop.id,
        workflow_key="optimize_product_2",
        priority=1,
        severity="high",
        title="Tối ưu tiêu đề",
        description="CTR giảm",
        recommendation_payload=json.dumps({}),
        status="active",
        computed_at=_now(),
        subject_type="product",
        subject_id=str(product.id),
    )
    session.add(card)
    await session.flush()
    return card


async def _stranger(session) -> User:
    user = User(id=uuid.uuid4(), phone=f"+8491{uuid.uuid4().int % 10**7:07d}")
    session.add(user)
    await session.flush()
    return user


async def _paused(session, run: WorkflowRun, arguments=ARGUMENTS) -> RunConfirmation:
    """The run paused at CONFIRM on a listing edit, with its pending confirmation row."""
    run.status = "waiting_approval"
    run.state = {
        "product_detail": copy.deepcopy(DETAIL),
        "pending_confirmation": {
            "call_id": CALL_ID,
            "tool_name": LISTING,
            "arguments": dict(arguments),
        },
    }
    confirmation = RunConfirmation(
        workflow_run_id=run.id,
        tool_call_id=CALL_ID,
        options=[
            {
                "option_id": "1",
                "proposed_change": dict(arguments),
                "rationale": "why",
                "params_sha": compute_params_sha(dict(arguments)),
            }
        ],
        status="pending",
        expires_at=datetime.now(UTC) + timedelta(hours=4),
    )
    session.add(confirmation)
    await session.flush()
    return confirmation


async def _approved_run(session, shop, product, *, approver=None, decider=None, at=None):
    """Card approved and CONFIRM approved by the shop's owner (or the given users)."""
    card = await _card(session, shop, product)
    result = await approval_module.approve_action_card(
        session,
        shop_id=shop.id,
        action_card_id=card.id,
        approved_by_user_id=approver or shop.user_id,
        now=(lambda: at) if at else None,
    )
    run = await session.get(WorkflowRun, result.run_id)
    await _paused(session, run)
    await decide_confirmation(
        session,
        run,
        tool_call_id=CALL_ID,
        decision="approve",
        option_id="1",
        decided_by_user_id=decider or shop.user_id,
    )
    await session.flush()
    return card, run


async def _leg(session, shop, product, run, pending=None):
    return await composition.resolve_agent_write_leg(
        session,
        shop_id=shop.id,
        run_id=run.id,
        tiktok_product_id=product.tiktok_product_id,
        tool_name=LISTING,
        pending=pending if pending is not None else run.state["pending_confirmation"],
    )


async def _audit_reasons(session):
    rows = (await session.execute(select(ProductionWriteAudit))).scalars().all()
    return [row.precondition_name for row in rows]


# --- who may click ------------------------------------------------------------------------


async def test_a_user_who_does_not_belong_to_the_shop_cannot_approve_its_card(session):
    shop, product = await _client_shop(session)
    card = await _card(session, shop, product)
    stranger = await _stranger(session)

    with pytest.raises(write_approval.ApproverNotShopMember):
        await approval_module.approve_action_card(
            session, shop_id=shop.id, action_card_id=card.id, approved_by_user_id=stranger.id
        )

    await session.refresh(card)
    assert card.status == "active" and card.approved_at is None
    assert (await session.execute(select(ActionCardApproval))).scalars().all() == []
    assert (await session.execute(select(WorkflowRun))).scalars().all() == []


async def test_the_owner_approves_and_the_card_snapshot_is_recorded(session):
    shop, product = await _client_shop(session)
    card = await _card(session, shop, product)

    result = await approval_module.approve_action_card(
        session, shop_id=shop.id, action_card_id=card.id, approved_by_user_id=shop.user_id
    )

    approval = await session.get(ActionCardApproval, result.approval_id)
    assert approval.approved_by_user_id == shop.user_id
    assert approval.card_snapshot["id"] == str(card.id)


async def test_a_staff_or_another_sellers_session_cannot_approve_on_the_clients_behalf(
    session,
):
    """Ops staff own no client shop; another seller owns a different one. Neither belongs."""
    shop, product = await _client_shop(session)
    other_shop, _other_product = await _seed_shop(session, "a", "merchant-a", "1001")
    staff = await _stranger(session)
    card = await _card(session, shop, product)
    for user_id in (staff.id, other_shop.user_id):
        with pytest.raises(write_approval.ApproverNotShopMember):
            await write_approval.approver_kind(session, shop_id=shop.id, user_id=user_id)
        with pytest.raises(write_approval.ApproverNotShopMember):
            await approval_module.approve_action_card(
                session, shop_id=shop.id, action_card_id=card.id, approved_by_user_id=user_id
            )
    assert (await session.execute(select(ActionCardApproval))).scalars().all() == []


def _reviewer(monkeypatch, *, pin: uuid.UUID, user_id: uuid.UUID, sandbox_pin: bool):
    from juli_backend.services import reviewer as reviewer_service
    from juli_backend.services.reviewer.sandbox import (
        MODE_MASKED,
        MODE_SANDBOX,
        REASON_NOT_SANDBOX,
        PinMode,
    )

    account = SimpleNamespace(
        user_id=user_id, status=lambda: reviewer_service.accounts.STATUS_ACTIVE
    )

    async def _load(_session, uid):
        return account if uid == user_id else None

    async def _classify(_session, _shop_id):
        if sandbox_pin:
            return PinMode(MODE_SANDBOX, writes_enabled=True)
        return PinMode(MODE_MASKED, writes_enabled=False, writes_disabled_reason=REASON_NOT_SANDBOX)

    monkeypatch.setattr(reviewer_service.config, "reviewer_shop_id", lambda: pin)
    monkeypatch.setattr(reviewer_service.accounts, "load_account", _load)
    monkeypatch.setattr(reviewer_service.pin_cache, "cached", lambda _shop_id: None)
    monkeypatch.setattr(reviewer_service.sandbox, "classify_pin", _classify)


async def test_the_partner_reviewer_approves_only_its_writable_sandbox_pin(session, monkeypatch):
    """D73: the reviewer approves its pinned sandbox shop as today, and no other shop."""
    sandbox_shop, _p = await _seed_shop(session, "s", "merchant-s", "3003")
    client_shop, _product = await _client_shop(session)
    reviewer = await _stranger(session)

    _reviewer(monkeypatch, pin=sandbox_shop.id, user_id=reviewer.id, sandbox_pin=True)
    with reviewer_session():
        assert (
            await write_approval.approver_kind(
                session, shop_id=sandbox_shop.id, user_id=reviewer.id
            )
            == write_approval.APPROVER_SANDBOX_REVIEWER
        )
        with pytest.raises(write_approval.ApproverNotShopMember):
            await write_approval.approver_kind(session, shop_id=client_shop.id, user_id=reviewer.id)
    # Not a reviewer request (the marker is per request): no reviewer exception at all.
    with pytest.raises(write_approval.ApproverNotShopMember):
        await write_approval.approver_kind(session, shop_id=sandbox_shop.id, user_id=reviewer.id)
    # A pin that is not Juli's writable sandbox (a client shop pinned masked): refused.
    _reviewer(monkeypatch, pin=client_shop.id, user_id=reviewer.id, sandbox_pin=False)
    with reviewer_session(), pytest.raises(write_approval.ApproverNotShopMember):
        await write_approval.approver_kind(session, shop_id=client_shop.id, user_id=reviewer.id)


async def test_a_non_member_cannot_approve_the_confirm_step_and_the_row_stays_pending(session):
    shop, product = await _client_shop(session)
    card = await _card(session, shop, product)
    result = await approval_module.approve_action_card(
        session, shop_id=shop.id, action_card_id=card.id, approved_by_user_id=shop.user_id
    )
    run = await session.get(WorkflowRun, result.run_id)
    confirmation = await _paused(session, run)
    stranger = await _stranger(session)

    with pytest.raises(ConfirmationRejected) as refused:
        await decide_confirmation(
            session,
            run,
            tool_call_id=CALL_ID,
            decision="approve",
            option_id="1",
            decided_by_user_id=stranger.id,
        )

    assert refused.value.error_code == ERROR_APPROVER_NOT_SHOP_MEMBER
    assert refused.value.http_status == 403
    await session.refresh(confirmation)
    assert confirmation.status == "pending"
    assert write_approval.APPROVED_CHANGE_KEY not in run.state["pending_confirmation"]


async def test_the_confirm_click_freezes_the_exact_change(session):
    shop, product = await _client_shop(session)
    card, run = await _approved_run(session, shop, product)

    block = run.state["pending_confirmation"][write_approval.APPROVED_CHANGE_KEY]
    approval = await write_approval.latest_card_approval(session, card.id)
    assert block["decided_by_user_id"] == str(shop.user_id)
    assert block["action_card_approval_id"] == str(approval.id)
    assert block["card_snapshot_sha256"] == write_approval.card_snapshot_sha256(
        approval.card_snapshot
    )
    assert block["before"] == {"title": "B old", "description": "B desc"}
    assert block["after"] == ARGUMENTS
    assert len(block["sha256"]) == 64


# --- the live write leg -------------------------------------------------------------------


async def test_a_members_approval_then_the_write_goes_live(
    session, sandbox, transport, monkeypatch, tmp_path
):
    _arm(monkeypatch, tmp_path)
    shop, product = await _client_shop(session)
    await _enable(session, shop.id)
    authorization = await _authorize(session, shop.id, PRODUCT)
    _card_row, run = await _approved_run(session, shop, product)

    leg = await _leg(session, shop, product, run)

    assert leg.live and isinstance(leg.resources, ProductionWriteResources)
    assert leg.approved_before == {"title": "B old", "description": "B desc"}
    assert await _consumed(session, authorization)
    (audit,) = (await session.execute(select(ProductionWriteAudit))).scalars().all()
    assert audit.authorization_id == authorization.id and audit.precondition_name is None
    # Migration 106: the old column and the per-platform pair are both written.
    assert (audit.tiktok_product_id, audit.platform, audit.platform_product_id) == (
        PRODUCT,
        WRITE_PLATFORM_TIKTOK,
        PRODUCT,
    )


async def _refused(session, shop, product, run, authorization, reason, pending=None):
    with pytest.raises(write_approval.WriteApprovalRefused) as refused:
        await _leg(session, shop, product, run, pending=pending)
    assert refused.value.reason == reason.value
    assert not await _consumed(session, authorization)
    assert await _audit_reasons(session) == [reason.value]


async def test_no_approval_on_the_run_is_refused_and_audited(
    session, sandbox, transport, monkeypatch, tmp_path
):
    _arm(monkeypatch, tmp_path)
    shop, product = await _client_shop(session)
    await _enable(session, shop.id)
    authorization = await _authorize(session, shop.id, PRODUCT)
    run = WorkflowRun(
        shop_id=shop.id,
        product_id=product.id,
        status="waiting_approval",
        prompt_version="optimize_product.v3",
        prompt_sha256="0" * 64,
        state={},
        subject_ref=str(product.id),
    )
    session.add(run)
    await session.flush()
    pending = {"call_id": CALL_ID, "tool_name": LISTING, "arguments": dict(ARGUMENTS)}

    await _refused(
        session,
        shop,
        product,
        run,
        authorization,
        PreconditionName.NO_SHOP_MEMBER_APPROVAL,
        pending=pending,
    )
    sandbox.assert_not_awaited()
    assert transport.calls == []


async def test_an_approval_by_a_user_who_no_longer_owns_the_shop_is_refused(
    session, sandbox, transport, monkeypatch, tmp_path
):
    _arm(monkeypatch, tmp_path)
    shop, product = await _client_shop(session)
    await _enable(session, shop.id)
    authorization = await _authorize(session, shop.id, PRODUCT)
    _card_row, run = await _approved_run(session, shop, product)
    new_owner = await _stranger(session)
    shop.user_id = new_owner.id  # the shop changed hands after the clicks
    await session.flush()

    await _refused(
        session, shop, product, run, authorization, PreconditionName.APPROVER_NOT_SHOP_MEMBER
    )
    assert transport.calls == []


async def test_an_approval_older_than_72_hours_is_refused_and_the_card_returns_to_pending(
    session, sandbox, transport, monkeypatch, tmp_path
):
    _arm(monkeypatch, tmp_path)
    shop, product = await _client_shop(session)
    await _enable(session, shop.id)
    authorization = await _authorize(session, shop.id, PRODUCT)
    stale = _now() - timedelta(hours=write_approval.APPROVAL_TTL_HOURS, minutes=1)
    card, run = await _approved_run(session, shop, product, at=stale)

    await _refused(session, shop, product, run, authorization, PreconditionName.APPROVAL_EXPIRED)

    await session.refresh(card)
    assert card.status == "active" and card.approved_at is None
    assert transport.calls == []


async def test_a_confirm_click_older_than_72_hours_is_refused_too(session):
    shop, product = await _client_shop(session)
    _card_row, run = await _approved_run(session, shop, product)
    pending = run.state["pending_confirmation"]

    later = _now() + write_approval.APPROVAL_TTL + timedelta(minutes=1)
    with pytest.raises(write_approval.WriteApprovalRefused) as refused:
        await write_approval.verify_write_approval(
            session, shop_id=shop.id, run_id=run.id, tool_name=LISTING, pending=pending, now=later
        )
    assert refused.value.reason == PreconditionName.APPROVAL_EXPIRED.value
    within = _now() + write_approval.APPROVAL_TTL - timedelta(minutes=5)
    approved = await write_approval.verify_write_approval(
        session, shop_id=shop.id, run_id=run.id, tool_name=LISTING, pending=pending, now=within
    )
    assert approved.before["title"] == "B old"


def test_the_ttl_is_a_named_72_hour_constant():
    assert write_approval.APPROVAL_TTL_HOURS == 72
    assert write_approval.APPROVAL_TTL == timedelta(hours=72)


@pytest.mark.parametrize("tamper", ["arguments", "card_snapshot", "block", "tool", "no_before"])
async def test_a_mismatch_with_the_approved_values_is_refused_and_audited(
    session, sandbox, transport, monkeypatch, tmp_path, tamper
):
    _arm(monkeypatch, tmp_path)
    shop, product = await _client_shop(session)
    await _enable(session, shop.id)
    authorization = await _authorize(session, shop.id, PRODUCT)
    card, run = await _approved_run(session, shop, product)
    pending = copy.deepcopy(run.state["pending_confirmation"])
    block = pending[write_approval.APPROVED_CHANGE_KEY]
    if tamper == "arguments":
        pending["arguments"]["title"] = "a title the seller never saw"
    elif tamper == "card_snapshot":
        approval = await write_approval.latest_card_approval(session, card.id)
        approval.card_snapshot = {**approval.card_snapshot, "title": "changed afterwards"}
        await session.flush()
    elif tamper == "block":
        block["before"] = {"title": "another before"}
    elif tamper == "tool":
        block["tool_name"] = "update_product_price"
        block["sha256"] = write_approval._block_sha256(block)
    else:
        block["before"] = {}
        block["sha256"] = write_approval._block_sha256(block)

    await _refused(
        session,
        shop,
        product,
        run,
        authorization,
        PreconditionName.APPROVAL_SNAPSHOT_MISMATCH,
        pending=pending,
    )
    assert transport.calls == []


async def test_the_refusals_do_not_touch_a_shop_that_is_not_production_enabled(
    session, sandbox, transport, monkeypatch, tmp_path
):
    """No live path, no approval check: today's sandbox run, no audit (D73 sandbox pin too)."""
    _arm(monkeypatch, tmp_path)
    shop, product = await _client_shop(session)
    run = WorkflowRun(
        shop_id=shop.id,
        product_id=product.id,
        status="waiting_approval",
        prompt_version="optimize_product.v3",
        prompt_sha256="0" * 64,
        state={},
        subject_ref=str(product.id),
    )
    session.add(run)
    await session.flush()

    leg = await _leg(session, shop, product, run, pending={"tool_name": LISTING})

    assert not leg.live and leg.refusal is None
    assert await _audit_reasons(session) == []


# --- the read immediately before the write ------------------------------------------------


#: A detail the listing edit can build its body from (category, weight, images, SKUs).
EXEC_DETAIL: dict[str, Any] = {
    **DETAIL,
    "status": "ACTIVATE",
    "category_chains": [{"id": "601693", "is_leaf": True, "local_name": "Nồi điện"}],
    "package_weight": {"unit": "KILOGRAM", "value": "0.2"},
    "main_images": [{"uri": "tos-old-1", "width": 800, "height": 800}],
    "skus": [{"id": "sku-1", "price": {"currency": "VND", "tax_exclusive_price": "599000"}}],
}


class _Products:
    def __init__(self, detail: dict[str, Any]) -> None:
        self.detail = copy.deepcopy(detail)
        self.edits: list[dict[str, Any]] = []

    def get_details(self, product_id: str) -> dict[str, Any]:
        return copy.deepcopy(self.detail)

    def edit(self, *, product_id: str, body: dict[str, Any]) -> dict[str, Any]:
        self.edits.append(copy.deepcopy(body))
        for key in ("title", "description"):
            if key in body:
                self.detail[key] = body[key]
        return {}


class _Audit:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)


def _executor(products: _Products, audit: _Audit, *, before=None, tool=LISTING):
    registry = ToolRegistry()
    register_product_read_tools(registry)
    register_product_write_tools(registry)
    resources = cast(SandboxWriteResources, SimpleNamespace(products=products))
    return ProductToolExecutor(
        registry=registry,
        read_resources=resources,
        write_resources=resources,
        product_id=PRODUCT,
        product_detail=copy.deepcopy(EXEC_DETAIL),
        approved_before=before if before is not None else {"title": "B old"},
        approved_tool_name=tool,
        on_read_back_refused=audit,
    )


def test_a_read_back_that_still_shows_the_approved_before_lets_the_write_through():
    products, audit = _Products(EXEC_DETAIL), _Audit()
    _executor(products, audit).execute(
        tool_name=LISTING, params=UpdateProductListingInput(title="B new title"), tool_call_id="c"
    )
    assert len(products.edits) == 1 and audit.calls == []


def test_a_changed_read_back_refuses_the_write_and_audits_it():
    changed = {**EXEC_DETAIL, "title": "the seller changed it meanwhile"}
    products, audit = _Products(changed), _Audit()

    with pytest.raises(ApprovedBeforeChangedError) as refused:
        _executor(products, audit).execute(
            tool_name=LISTING,
            params=UpdateProductListingInput(title="B new title"),
            tool_call_id="c",
        )

    assert refused.value.fields == ("title",)
    assert products.edits == []  # no vendor write
    assert audit.calls == [
        {"tool_name": LISTING, "tiktok_product_id": PRODUCT, "fields": ["title"]}
    ]


def test_a_live_leg_refuses_any_write_but_the_approved_one():
    products, audit = _Products(EXEC_DETAIL), _Audit()
    with pytest.raises(ApprovedBeforeChangedError):
        _executor(products, audit, tool="update_product_price").execute(
            tool_name=LISTING, params=UpdateProductListingInput(title="x"), tool_call_id="c"
        )
    assert products.edits == [] and len(audit.calls) == 1


def _sync_session() -> Session:
    engine = create_engine(
        "sqlite://",
        execution_options={
            "schema_translate_map": {"ops": None, "bronze": None, "gold": None, "silver": None}
        },
    )
    Base.metadata.create_all(engine)
    return Session(bind=engine)


def test_the_sql_read_back_audit_appends_a_named_refusal_row(monkeypatch):
    monkeypatch.setenv("RELEASE_SHA", "b" * 40)
    session = _sync_session()
    user = User(id=uuid.uuid4(), phone="+84910000002")
    shop = Shop(id=uuid.uuid4(), user_id=user.id, shop_name="s", is_active=True)
    run = WorkflowRun(
        id=uuid.uuid4(),
        shop_id=shop.id,
        subject_ref="p",
        state={},
        status="running",
        prompt_version="optimize_product.v3",
        prompt_sha256="0" * 64,
    )
    session.add_all([user, shop, run])
    session.commit()

    run_changes.SqlReadBackRefusalAudit(session, shop_id=shop.id, workflow_run_id=run.id)(
        tool_name=LISTING, tiktok_product_id=PRODUCT, fields=["title"]
    )

    (row,) = session.execute(select(ProductionWriteAudit)).scalars().all()
    assert (row.run_id, row.shop_id, row.authorization_id) == (run.id, shop.id, None)
    assert row.precondition_name == PreconditionName.READ_BACK_CHANGED.value
    assert (row.platform, row.platform_product_id, row.tiktok_product_id) == (
        WRITE_PLATFORM_TIKTOK,
        PRODUCT,
        PRODUCT,
    )


# --- migration 106 and the per-platform columns -------------------------------------------


def _migration_module():
    spec = importlib.util.spec_from_file_location("mig106", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_106_fits_alembic_and_the_deferred_tail_moved_onto_it():
    mig = _migration_module()
    assert len(mig.revision) <= 32
    assert mig.down_revision == "105_llm_call_log"
    # Migration 107 went on top of 106 and took the deferred tail.
    later = (MIGRATIONS / "versions/107_ops_pooled_consent.py").read_text("utf-8")
    assert f'down_revision: str | None = "{mig.revision}"' in later
    assert 'down_revision: str | None = "107_ops_pooled_consent"' in BACKFILL.read_text("utf-8")
    assert mig.DEFAULT_PLATFORM == WRITE_PLATFORM_TIKTOK


def test_the_additive_gate_accepts_migration_106_and_it_moves_no_data():
    sys.path.insert(0, str(REPO / "infra/scripts"))
    from migration_additive_gate import evaluate_migration_paths

    result = evaluate_migration_paths([MIGRATION])
    assert result.accepted, result.report()
    upgrade = MIGRATION.read_text("utf-8").split("def upgrade")[1].split("def downgrade")[0]
    for verb in ("UPDATE", "DELETE", "INSERT", "GRANT", "POLICY"):
        assert verb not in upgrade


def test_the_models_carry_the_per_platform_columns():
    for model in (ProductionWriteAuthorization, ProductionWriteAudit):
        columns = model.__table__.columns
        assert not columns["platform"].nullable
        assert columns["platform"].server_default is not None
        assert columns["platform_product_id"].nullable
        assert "tiktok_product_id" in columns  # expand-only: the old column stays


async def test_the_authorization_lookup_prefers_the_new_column_and_falls_back(session):
    from juli_backend.repositories.repos import ProductionWriteAuthorizationsRepo

    shop, _product = await _client_shop(session)
    repo = ProductionWriteAuthorizationsRepo(session)
    issued = await repo.issue(
        shop.id, PRODUCT, LISTING, authorized_by="owner", expires_at=_now() + timedelta(hours=1)
    )
    assert (issued.platform, issued.platform_product_id) == (WRITE_PLATFORM_TIKTOK, PRODUCT)
    assert (await repo.lookup(shop.id, PRODUCT, LISTING)).id == issued.id
    # A row written before 106: no platform_product_id yet -- still found.
    issued.platform_product_id = None
    await session.flush()
    assert (await repo.lookup(shop.id, PRODUCT, LISTING)).id == issued.id
    # Another platform's row never satisfies a TikTok lookup.
    issued.platform = "shopee"
    await session.flush()
    assert await repo.lookup(shop.id, PRODUCT, LISTING) is None


def test_the_backfill_is_literal_owner_sql_on_the_two_tables_only():
    assert write_platform_backfill.TABLES == (
        "production_write_authorizations",
        "production_write_audit",
    )
    for table, sql in write_platform_backfill._UPDATE_SQL.items():
        assert sql.startswith(f"UPDATE public.{table} SET platform_product_id = tiktok_product_id")
        assert "WHERE platform_product_id IS NULL AND platform = 'tiktok'" in sql
    assert "DRY RUN" in write_platform_backfill.render({}, applied=False)
