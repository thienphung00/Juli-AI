"""HTTP-level tests for `POST /v1/demo/runs` -- issue #1145 Gap 2: nothing
enqueues a run. Before this change no production code created a
`workflow_runs` row or called `run_agent_workflow.delay(...)`; this route is
that missing trigger.

AC -> test map (issue #1145, scope-update comment "Remaining scope / Gap 2"):
- creates a `workflow_runs` row and enqueues `run_agent_workflow.delay(str(run_id))`
  -> test_create_run_creates_row_and_enqueues_run_agent_workflow
- tenant-scoped via `get_active_shop`, 404 (never 403) for another shop's
  product, no existence oracle -> test_create_run_for_other_shops_product_returns_404,
  test_create_run_for_nonexistent_product_returns_404
- respects #1122's partial unique index (one active run per (shop_id,
  product_id)); a second concurrent start fails cleanly, never a 500 ->
  test_second_concurrent_start_same_product_returns_409_not_500
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from juli_backend.models.models import Product, Shop, User
from juli_backend.models.models import WorkflowRun as WorkflowRunRow

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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
    s = Shop(user_id=user.id, shop_name="AGT-1145-G2 Shop")
    session.add(s)
    await session.flush()
    return s


@pytest_asyncio.fixture
async def other_shop(session):
    other_user = User(phone=f"+1555{uuid.uuid4().int % 10_000_000:07d}")
    session.add(other_user)
    await session.flush()
    s = Shop(user_id=other_user.id, shop_name="AGT-1145-G2 Other Shop")
    session.add(s)
    await session.flush()
    return s


@pytest_asyncio.fixture
async def product(session, shop):
    p = Product(
        shop_id=shop.id,
        tiktok_product_id=f"agt-1145-g2-{uuid.uuid4()}",
        name="Test Widget",
        status="active",
        update_time=datetime.now(UTC).replace(tzinfo=None),
    )
    session.add(p)
    await session.flush()
    await session.commit()
    return p


@pytest_asyncio.fixture
async def other_shop_product(session, other_shop):
    p = Product(
        shop_id=other_shop.id,
        tiktok_product_id=f"agt-1145-g2-other-{uuid.uuid4()}",
        name="Other Shop Widget",
        status="active",
        update_time=datetime.now(UTC).replace(tzinfo=None),
    )
    session.add(p)
    await session.flush()
    await session.commit()
    return p


def _client_for(app, user: User, shop: Shop) -> AsyncClient:
    from juli_backend.api.dependencies import get_active_shop
    from juli_backend.core.security import get_current_user

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_active_shop] = lambda: shop
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _mock_run_agent_workflow_task():
    mock_task = MagicMock()
    mock_async_result = MagicMock()
    mock_async_result.id = "celery-task-id-1145"
    mock_task.delay.return_value = mock_async_result
    return mock_task


# ---------------------------------------------------------------------------
# AC -- creates the row and enqueues run_agent_workflow.delay(str(run_id))
# ---------------------------------------------------------------------------


async def test_create_run_creates_row_and_enqueues_run_agent_workflow(
    app, session, user, shop, product
):
    mock_task = _mock_run_agent_workflow_task()

    with patch("juli_backend.workers.tasks.agent_workflow.run_agent_workflow", mock_task):
        async with _client_for(app, user, shop) as client:
            resp = await client.post("/v1/demo/runs", json={"product_id": str(product.id)})

    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "queued"
    assert body["celery_task_id"] == "celery-task-id-1145"
    run_id = uuid.UUID(body["id"])

    result = await session.execute(select(WorkflowRunRow).where(WorkflowRunRow.id == run_id))
    run = result.scalar_one()
    assert run.shop_id == shop.id
    assert run.product_id == product.id
    assert run.status == "queued"
    assert run.prompt_version
    assert run.prompt_sha256
    assert run.cancel_requested is False

    mock_task.delay.assert_called_once_with(str(run_id))


# ---------------------------------------------------------------------------
# AC -- tenant scoping, no existence oracle
# ---------------------------------------------------------------------------


async def test_create_run_for_other_shops_product_returns_404_never_403(
    app, user, shop, other_shop_product
):
    mock_task = _mock_run_agent_workflow_task()

    with patch("juli_backend.workers.tasks.agent_workflow.run_agent_workflow", mock_task):
        async with _client_for(app, user, shop) as client:
            resp = await client.post(
                "/v1/demo/runs", json={"product_id": str(other_shop_product.id)}
            )

    assert resp.status_code == 404
    assert resp.status_code != 403
    mock_task.delay.assert_not_called()


async def test_create_run_for_nonexistent_product_returns_404(app, user, shop):
    mock_task = _mock_run_agent_workflow_task()

    with patch("juli_backend.workers.tasks.agent_workflow.run_agent_workflow", mock_task):
        async with _client_for(app, user, shop) as client:
            resp = await client.post("/v1/demo/runs", json={"product_id": str(uuid.uuid4())})

    assert resp.status_code == 404
    mock_task.delay.assert_not_called()


# ---------------------------------------------------------------------------
# AC -- #1122's partial unique index: a second concurrent start fails clean
# ---------------------------------------------------------------------------


async def test_second_concurrent_start_same_product_returns_409_not_500(
    app, session, user, shop, product
):
    # Captured up front: the route commits (success) / rolls back (conflict)
    # the SAME session object this test shares via the `get_session`
    # dependency override, and a rollback expires every attribute on every
    # ORM object the test still holds a reference to -- accessing an
    # expired attribute after that point needs an explicit async refresh,
    # not a bare sync attribute read (`MissingGreenlet`). Capturing the
    # plain UUID up front sidesteps that entirely.
    product_id = product.id

    mock_task = _mock_run_agent_workflow_task()

    with patch("juli_backend.workers.tasks.agent_workflow.run_agent_workflow", mock_task):
        async with _client_for(app, user, shop) as client:
            first = await client.post("/v1/demo/runs", json={"product_id": str(product_id)})
            second = await client.post("/v1/demo/runs", json={"product_id": str(product_id)})

    assert first.status_code == 202
    assert second.status_code == 409
    assert second.status_code != 500
    mock_task.delay.assert_called_once()

    result = await session.execute(
        select(WorkflowRunRow).where(WorkflowRunRow.product_id == product_id)
    )
    rows = result.scalars().all()
    assert len(rows) == 1
