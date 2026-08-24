"""`POST /v1/demo/decisions/{action_card_id}/approve` -- approve-is-run-
creation (ADR-075 decision 1, ADR-082, #1222).

**Retired here.** This route used to be public/unauthenticated dry-run
record creation (#717, B-5): no auth, `DEMO_REFERENCE_SHOP_ID`-bound, and it
created a `DemoExecutionRecord` rather than a real `workflow_runs` row. As
of #1222 it is real, authenticated agent-run creation -- see
`api/routes/demo_execution.py`'s own module docstring for the full
retirement rationale, and `services/demo_execution/MODULE.md`'s "Retired
call site" section for why `services.demo_execution` itself is left in
place rather than deleted. `tests/unit/test_demo_execution_dry_run.py`
still directly and fully covers `approve_decision_dry_run` (the function,
called with a session, no HTTP involved) -- unaffected by this file's
rewrite, since nothing here touches that function.

These are HTTP-level tests: auth wiring, the 404/409 status-code
translation, and the response shape. The transaction itself is unit-tested
directly (no HTTP) in `test_agent_approval_transaction.py`; the real-
concurrency race and the mid-transaction-crash rollback proof (both need a
real Postgres connection) live in
`tests/integration/test_agent_approval_concurrency.py`.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from juli_backend.models.models import (
    ActionCard,
    ActionCardApproval,
    DemoExecutionRecord,
    Product,
    Shop,
    User,
)
from juli_backend.models.models import WorkflowRun as WorkflowRunRow

pytestmark = pytest.mark.asyncio


def _naive_utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@pytest_asyncio.fixture
async def app(engine, session):
    from juli_backend.api.app import create_app
    from juli_backend.database import get_session

    application = create_app()

    async def _test_session():
        yield session

    application.dependency_overrides[get_session] = _test_session
    yield application
    application.dependency_overrides.clear()


@pytest_asyncio.fixture
async def user(session):
    u = User(phone=f"+1555{uuid.uuid4().int % 10_000_000:07d}")
    session.add(u)
    await session.flush()
    return u


@pytest_asyncio.fixture
async def shop(session, user):
    s = Shop(user_id=user.id, shop_name="AGT-1222 HTTP Shop")
    session.add(s)
    await session.flush()
    return s


@pytest_asyncio.fixture
async def other_shop(session):
    other_user = User(phone=f"+1555{uuid.uuid4().int % 10_000_000:07d}")
    session.add(other_user)
    await session.flush()
    s = Shop(user_id=other_user.id, shop_name="AGT-1222 Other HTTP Shop")
    session.add(s)
    await session.flush()
    return s


@pytest_asyncio.fixture
async def product(session, shop):
    p = Product(
        shop_id=shop.id,
        tiktok_product_id=f"agt-1222-{uuid.uuid4()}",
        name="Test Widget",
        status="active",
        revenue=Decimal("100.00"),
        update_time=_naive_utc_now(),
    )
    session.add(p)
    await session.flush()
    await session.commit()
    return p


@pytest_asyncio.fixture
async def card(session, shop):
    c = ActionCard(
        shop_id=shop.id,
        workflow_key="optimize_product_2",
        priority=1,
        severity="high",
        title="Optimize this listing",
        description="CTR fell 18% week over week on this listing.",
        recommendation_payload=json.dumps({}),
        status="active",
        computed_at=_naive_utc_now(),
    )
    session.add(c)
    await session.flush()
    await session.commit()
    return c


def _client_for(app, user: User, shop: Shop) -> AsyncClient:
    from juli_backend.api.dependencies import get_active_shop
    from juli_backend.core.security import get_current_user

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_active_shop] = lambda: shop
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _mock_run_agent_workflow_task():
    mock_task = MagicMock()
    mock_async_result = MagicMock()
    mock_async_result.id = "celery-task-id-1222"
    mock_task.delay.return_value = mock_async_result
    return mock_task


# ---------------------------------------------------------------------------
# AC -- success: 202, creates the run + approval audit row, enqueues
# ---------------------------------------------------------------------------


async def test_approve_creates_run_and_returns_202(app, session, user, shop, card, product):
    mock_task = _mock_run_agent_workflow_task()

    with patch("juli_backend.workers.tasks.agent_workflow.run_agent_workflow", mock_task):
        async with _client_for(app, user, shop) as client:
            resp = await client.post(f"/v1/demo/decisions/{card.id}/approve")

    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["success"] is True
    data = body["data"]
    assert data["action_card_id"] == str(card.id)
    assert data["product_id"] == str(product.id)
    assert data["status"] == "queued"
    assert data["celery_task_id"] == "celery-task-id-1222"
    run_id = uuid.UUID(data["run_id"])

    run = (
        await session.execute(select(WorkflowRunRow).where(WorkflowRunRow.id == run_id))
    ).scalar_one()
    assert run.shop_id == shop.id
    assert run.product_id == product.id
    assert run.action_card_id == card.id
    assert run.status == "queued"

    approvals = (
        (
            await session.execute(
                select(ActionCardApproval).where(ActionCardApproval.action_card_id == card.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(approvals) == 1
    assert approvals[0].approved_by_user_id == user.id

    refreshed_card = await session.get(ActionCard, card.id)
    assert refreshed_card.status == "approved"

    mock_task.delay.assert_called_once_with(str(run_id))


async def test_approve_never_creates_a_demo_execution_record(
    app, session, user, shop, card, product
):
    """Regression: proves the dry-run path this route retired is genuinely
    unreachable from HTTP, not merely uncalled by coincidence."""
    mock_task = _mock_run_agent_workflow_task()

    with patch("juli_backend.workers.tasks.agent_workflow.run_agent_workflow", mock_task):
        async with _client_for(app, user, shop) as client:
            resp = await client.post(f"/v1/demo/decisions/{card.id}/approve")

    assert resp.status_code == 202, resp.text
    rows = (
        (
            await session.execute(
                select(DemoExecutionRecord).where(DemoExecutionRecord.action_card_id == card.id)
            )
        )
        .scalars()
        .all()
    )
    assert rows == []


# ---------------------------------------------------------------------------
# AC -- 404, indistinguishable for cross-tenant vs. nonexistent
# ---------------------------------------------------------------------------


async def test_approve_nonexistent_card_returns_404(app, user, shop):
    mock_task = _mock_run_agent_workflow_task()
    with patch("juli_backend.workers.tasks.agent_workflow.run_agent_workflow", mock_task):
        async with _client_for(app, user, shop) as client:
            resp = await client.post(f"/v1/demo/decisions/{uuid.uuid4()}/approve")

    assert resp.status_code == 404
    mock_task.delay.assert_not_called()


async def test_approve_cross_tenant_card_returns_404_never_403(
    app, user, shop, other_shop, session
):
    other_card = ActionCard(
        shop_id=other_shop.id,
        workflow_key="optimize_product_2",
        priority=1,
        severity="high",
        title="Other shop's card",
        description="",
        recommendation_payload=json.dumps({}),
        status="active",
        computed_at=_naive_utc_now(),
    )
    session.add(other_card)
    await session.commit()

    mock_task = _mock_run_agent_workflow_task()
    with patch("juli_backend.workers.tasks.agent_workflow.run_agent_workflow", mock_task):
        async with _client_for(app, user, shop) as client:
            resp = await client.post(f"/v1/demo/decisions/{other_card.id}/approve")

    assert resp.status_code == 404
    assert resp.status_code != 403
    mock_task.delay.assert_not_called()


# ---------------------------------------------------------------------------
# AC -- 409 for a non-active card
# ---------------------------------------------------------------------------


async def test_approve_non_active_card_returns_409(app, session, user, shop, card, product):
    card.status = "dismissed"
    await session.commit()

    mock_task = _mock_run_agent_workflow_task()
    with patch("juli_backend.workers.tasks.agent_workflow.run_agent_workflow", mock_task):
        async with _client_for(app, user, shop) as client:
            resp = await client.post(f"/v1/demo/decisions/{card.id}/approve")

    assert resp.status_code == 409
    mock_task.delay.assert_not_called()


async def test_repeat_approve_of_the_same_card_returns_409_on_the_second_call(
    app, session, user, shop, card, product
):
    mock_task = _mock_run_agent_workflow_task()
    with patch("juli_backend.workers.tasks.agent_workflow.run_agent_workflow", mock_task):
        async with _client_for(app, user, shop) as client:
            first = await client.post(f"/v1/demo/decisions/{card.id}/approve")
            second = await client.post(f"/v1/demo/decisions/{card.id}/approve")

    assert first.status_code == 202
    assert second.status_code == 409
    mock_task.delay.assert_called_once()

    runs = (
        (
            await session.execute(
                select(WorkflowRunRow).where(WorkflowRunRow.action_card_id == card.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(runs) == 1


# ---------------------------------------------------------------------------
# AC (ADR-082 decision 4) -- 409 for zero products, never a 500
# ---------------------------------------------------------------------------


async def test_approve_with_zero_products_returns_409_not_500(app, user, shop, card):
    mock_task = _mock_run_agent_workflow_task()
    with patch("juli_backend.workers.tasks.agent_workflow.run_agent_workflow", mock_task):
        async with _client_for(app, user, shop) as client:
            resp = await client.post(f"/v1/demo/decisions/{card.id}/approve")

    assert resp.status_code == 409
    assert resp.status_code != 500
    mock_task.delay.assert_not_called()


# ---------------------------------------------------------------------------
# AC -- the in-transaction partial-unique-index rejection surfaces as 409,
# never 500, at the HTTP layer too (two different cards, one product)
# ---------------------------------------------------------------------------


async def test_second_active_run_for_the_same_derived_product_returns_409_not_500(
    app, session, user, shop, product
):
    card_one = ActionCard(
        shop_id=shop.id,
        workflow_key="optimize_product_2",
        priority=1,
        severity="high",
        title="Card one",
        description="",
        recommendation_payload=json.dumps({}),
        status="active",
        computed_at=_naive_utc_now(),
    )
    card_two = ActionCard(
        shop_id=shop.id,
        # action_cards uniques on (shop_id, workflow_key) -- distinct key so
        # both cards can coexist; prompt-pin resolution ignores the card's
        # own workflow_key regardless (see approval.py's
        # _resolve_optimize_product_prompt_pin docstring).
        workflow_key="optimize_product_2_alt",
        priority=1,
        severity="high",
        title="Card two",
        description="",
        recommendation_payload=json.dumps({}),
        status="active",
        computed_at=_naive_utc_now(),
    )
    session.add_all([card_one, card_two])
    await session.commit()
    # Captured before the requests run: the route rolls back this SAME
    # session (shared via the get_session override) on the conflict branch,
    # which EXPIRES every attribute on every ORM object the test still
    # holds -- accessing product.id afterward needs an explicit refresh, not
    # a bare sync attribute read (MissingGreenlet). Same gotcha
    # test_agent_run_create_route.py's (now-removed) equivalent conflict
    # test already documented for create_run's identical rollback shape.
    product_id = product.id

    mock_task = _mock_run_agent_workflow_task()
    with patch("juli_backend.workers.tasks.agent_workflow.run_agent_workflow", mock_task):
        async with _client_for(app, user, shop) as client:
            first = await client.post(f"/v1/demo/decisions/{card_one.id}/approve")
            second = await client.post(f"/v1/demo/decisions/{card_two.id}/approve")

    assert first.status_code == 202
    assert second.status_code == 409
    assert second.status_code != 500
    mock_task.delay.assert_called_once()

    session.expunge_all()
    runs = (
        (
            await session.execute(
                select(WorkflowRunRow).where(WorkflowRunRow.product_id == product_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(runs) == 1


# ---------------------------------------------------------------------------
# AC (#1145 Review convention, carried forward) -- state-mutating outcomes
# are logged
# ---------------------------------------------------------------------------


async def test_approve_success_is_logged(app, session, user, shop, card, product, caplog):
    mock_task = _mock_run_agent_workflow_task()
    with (
        caplog.at_level("INFO", logger="juli_backend.api.routes.demo_execution"),
        patch("juli_backend.workers.tasks.agent_workflow.run_agent_workflow", mock_task),
    ):
        async with _client_for(app, user, shop) as client:
            resp = await client.post(f"/v1/demo/decisions/{card.id}/approve")

    assert resp.status_code == 202
    records = [r for r in caplog.records if r.message == "agent_run_approved"]
    assert len(records) == 1
    record = records[0]
    assert getattr(record, "shop_id", None) == str(shop.id)
    assert getattr(record, "action_card_id", None) == str(card.id)
    assert getattr(record, "celery_task_id", None) == "celery-task-id-1222"


async def test_approve_conflict_is_logged(app, session, user, shop, card, product, caplog):
    mock_task = _mock_run_agent_workflow_task()
    with (
        caplog.at_level("WARNING", logger="juli_backend.api.routes.demo_execution"),
        patch("juli_backend.workers.tasks.agent_workflow.run_agent_workflow", mock_task),
    ):
        async with _client_for(app, user, shop) as client:
            await client.post(f"/v1/demo/decisions/{card.id}/approve")
            second_card = ActionCard(
                shop_id=shop.id,
                workflow_key="optimize_product_2_alt",
                priority=1,
                severity="high",
                title="Second card",
                description="",
                recommendation_payload=json.dumps({}),
                status="active",
                computed_at=_naive_utc_now(),
            )
            session.add(second_card)
            await session.commit()
            resp = await client.post(f"/v1/demo/decisions/{second_card.id}/approve")

    assert resp.status_code == 409
    records = [r for r in caplog.records if r.message == "agent_run_approve_conflict"]
    assert len(records) == 1
