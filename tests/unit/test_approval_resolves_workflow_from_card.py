"""Approving a card runs THAT CARD's workflow on THAT CARD's subject
(issue #1702, W9-A/P-SHARED-2; finding F3 of #1365's audit).

The defect these tests exist to keep closed is silent substitution, so every
test here is written so that the pre-#1702 code would fail it:

* the card under test carries a workflow key that is NOT
  `optimize_product_2`, and the assertion is on the playbook the worker
  would execute for the run that approval created -- resolved by the real
  `workers/tasks/agent_workflow.py::_playbook_for_run` off the real
  `workflow_runs` row, not by looking the key up in the registry a second
  time from the test;
* the card's product subject is deliberately the shop's WORST-selling
  product while a far larger one exists, so the deleted highest-revenue
  rule and the card-subject rule give different answers.

Approving a card is a PRODUCER. None of these tests hands `approve_action_
card` a workflow key or a subject as an argument and reads it back -- they
write a card row, approve it, and read the run row the transaction produced.

**What the SQLite `session` fixture does and does not prove.** It is an
in-memory SQLite database (`tests/unit/conftest.py`), so what is proven here
is the Python decision logic: which playbook is resolved, which product the
run is bound to, which named exception is raised, and that no run row exists
after a refusal *within this transaction*. What is NOT proven here is
anything Postgres-specific -- the partial unique index on
`(shop_id, workflow_key, subject_type, subject_ref)`, the real FK's
behaviour on a bad subject, RLS, or a genuine cross-connection race. Those
belong to `tests/integration/test_agent_approval_concurrency.py` and
`tests/integration/test_reaper_two_tenant.py`, against real Postgres.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from juli_backend.models.models import ActionCard, Product, Shop, User
from juli_backend.models.models import WorkflowRun as WorkflowRunRow
from juli_backend.services.agent import approval as approval_module
from juli_backend.services.agent import playbooks as playbooks_module
from juli_backend.services.agent.playbooks.optimize_product import OPTIMIZE_PRODUCT_PLAYBOOK
from juli_backend.workers.tasks import agent_workflow
from tests.support.workflow_registry import (
    TEST_WORKFLOW_KEY,
    make_test_playbook,
    prompt_binding_registered_for_test,
)


def _naive_utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@pytest.fixture
async def shop(session):
    user = User(id=uuid.uuid4(), phone=f"+8490{uuid.uuid4().int % 10_000_000:07d}")
    s = Shop(id=uuid.uuid4(), user_id=user.id, shop_name="W9A-1702 Shop")
    session.add_all([user, s])
    await session.flush()
    return s


def _make_product(shop_id: uuid.UUID, *, revenue: str, tiktok_product_id: str) -> Product:
    return Product(
        id=uuid.uuid4(),
        shop_id=shop_id,
        tiktok_product_id=tiktok_product_id,
        name=f"Product {tiktok_product_id}",
        status="active",
        revenue=Decimal(revenue),
        update_time=_naive_utc_now(),
    )


def _make_card(
    shop_id: uuid.UUID,
    *,
    workflow_key: str,
    subject_product_id: uuid.UUID | None = None,
) -> ActionCard:
    fields: dict = {
        "id": uuid.uuid4(),
        "shop_id": shop_id,
        "workflow_key": workflow_key,
        "priority": 1,
        "severity": "high",
        "title": "A card about one specific listing",
        "description": "Sell-through on this listing stalled.",
        "recommendation_payload": json.dumps({}),
        "status": "active",
        "computed_at": _naive_utc_now(),
    }
    if subject_product_id is not None:
        fields["subject_type"] = "product"
        fields["subject_id"] = str(subject_product_id)
    return ActionCard(**fields)


async def test_approving_a_card_runs_that_cards_playbook(session, shop):
    """AC 1: with a registry holding two keys -- the real
    `optimize_product_2` and a test-only playbook -- a card carrying the
    test key is approved, and the playbook the WORKER would execute for the
    resulting run is the test one, whose first step is not Optimize
    Product's.

    The playbook is resolved by calling the real production function
    (`agent_workflow._playbook_for_run`, the same call `_construct_runner`
    makes) on the real `workflow_runs` row read back out of the database --
    not by re-reading the registry with a key the test already knows.
    """
    test_playbook = make_test_playbook()
    product = _make_product(shop.id, revenue="10.00", tiktok_product_id="tt-subject")
    session.add(product)
    await session.flush()

    with playbooks_module.playbook_registered_for_test(test_playbook):
        with prompt_binding_registered_for_test(test_playbook):
            card = _make_card(
                shop.id, workflow_key=TEST_WORKFLOW_KEY, subject_product_id=product.id
            )
            session.add(card)
            await session.flush()

            result = await approval_module.approve_action_card(
                session,
                shop_id=shop.id,
                action_card_id=card.id,
                approved_by_user_id=uuid.uuid4(),
            )

            run = (
                await session.execute(
                    select(WorkflowRunRow).where(WorkflowRunRow.id == result.run_id)
                )
            ).scalar_one()

            assert run.workflow_key == TEST_WORKFLOW_KEY, (
                "the run must carry the approved card's own workflow_key, not the "
                "one workflow that happened to be registered first"
            )

            resolved = agent_workflow._playbook_for_run(run)

            assert resolved is test_playbook
            assert resolved.steps[0].tools == ("check_product_status",)
            assert resolved.steps[0].tools != OPTIMIZE_PRODUCT_PLAYBOOK.steps[0].tools, (
                "the test playbook's first step must differ from Optimize Product's, "
                "or this assertion could not tell the two playbooks apart"
            )


async def test_unknown_workflow_key_is_refused_with_no_run(session, shop):
    """AC 2: a card whose key is registered nowhere fails closed with the
    named `WorkflowNotExecutable` (#1350 / #1309's refusal, reached through
    the registry rather than reimplemented) and leaves no run row.

    The card carries a perfectly good product subject, so the ONLY thing
    wrong with it is its workflow key -- otherwise this could pass on
    #1702's subject refusal and prove nothing. The card is also asserted
    still `active`: the refusal happens before the status flip, so a
    mis-keyed card stays approvable once its workflow is registered.
    """
    product = _make_product(shop.id, revenue="10.00", tiktok_product_id="tt-subject")
    session.add(product)
    await session.flush()
    card = _make_card(shop.id, workflow_key="no_such_workflow_1702", subject_product_id=product.id)
    session.add(card)
    await session.flush()

    assert not playbooks_module.is_workflow_executable("no_such_workflow_1702")

    with pytest.raises(approval_module.WorkflowNotExecutable) as exc:
        await approval_module.approve_action_card(
            session,
            shop_id=shop.id,
            action_card_id=card.id,
            approved_by_user_id=uuid.uuid4(),
        )
    assert "no_such_workflow_1702" in str(exc.value)

    runs = (await session.execute(select(WorkflowRunRow))).scalars().all()
    assert runs == []

    refreshed = await session.get(ActionCard, card.id)
    assert refreshed.status == "active"
    assert refreshed.approved_at is None


async def test_run_subject_is_the_cards_subject_not_the_shops_top_product(session, shop):
    """AC 3: the run's subject equals the card's subject, proven on a shop
    where the card's subject and the shop's highest-revenue product are
    DIFFERENT rows -- so the deleted ADR-082 rule and the new one cannot
    agree by coincidence -- and `ProductsRepo.get_highest_revenue_product`
    is gone from the repository entirely.
    """
    from juli_backend.repositories.repos import ProductsRepo

    subject = _make_product(shop.id, revenue="1.00", tiktok_product_id="tt-aaa-subject")
    best_seller = _make_product(shop.id, revenue="999999.00", tiktok_product_id="tt-zzz-best")
    session.add_all([subject, best_seller])
    await session.flush()
    card = _make_card(shop.id, workflow_key="optimize_product_2", subject_product_id=subject.id)
    session.add(card)
    await session.flush()

    result = await approval_module.approve_action_card(
        session,
        shop_id=shop.id,
        action_card_id=card.id,
        approved_by_user_id=uuid.uuid4(),
    )

    run = (
        await session.execute(select(WorkflowRunRow).where(WorkflowRunRow.id == result.run_id))
    ).scalar_one()
    assert run.subject_type == "product"
    assert run.subject_ref == str(subject.id)
    assert run.product_id == subject.id
    assert run.product_id != best_seller.id

    assert not hasattr(ProductsRepo, "get_highest_revenue_product"), (
        "the highest-revenue derivation must be removed, not merely unreferenced"
    )


async def test_a_card_with_no_subject_cannot_be_approved(session, shop):
    """The other half of AC 3, and the coexistence hazard of this slice:
    every card a producer writes today is `subject_type='unscoped'` (#1701's
    backfill; subject-scoped emission is #1703). Approve refuses it by name
    rather than falling back to the shop's best seller.
    """
    product = _make_product(shop.id, revenue="10.00", tiktok_product_id="tt-any")
    session.add(product)
    await session.flush()
    card = _make_card(shop.id, workflow_key="optimize_product_2")
    session.add(card)
    await session.flush()

    with pytest.raises(approval_module.CardSubjectNotApprovable):
        await approval_module.approve_action_card(
            session,
            shop_id=shop.id,
            action_card_id=card.id,
            approved_by_user_id=uuid.uuid4(),
        )

    runs = (await session.execute(select(WorkflowRunRow))).scalars().all()
    assert runs == []
