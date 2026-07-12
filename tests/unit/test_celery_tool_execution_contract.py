"""P2-B4 Celery-backed tool execution contract tests — Issue #305.

AC1 → test_ac1_post_executions_returns_after_enqueue_without_inline_run
AC2 → test_ac2_tool_execution_dispatched_to_celery_worker
AC3 → test_ac3_get_execution_returns_queryable_outcome_status
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from juli_backend.models.models import Shop, User

pytestmark = pytest.mark.asyncio


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
async def authenticated_user(session, user_id):
    user = User(id=user_id, phone="+849305000305")
    session.add(user)
    await session.flush()
    return user


@pytest_asyncio.fixture
async def shop(session, authenticated_user):
    s = Shop(
        id=uuid.uuid4(),
        user_id=authenticated_user.id,
        shop_name="Execution API Shop 305",
        tiktok_shop_id="tiktok_shop_305",
    )
    session.add(s)
    await session.flush()
    return s


@pytest_asyncio.fixture
async def auth_client(app, authenticated_user, shop):
    from juli_backend.api.dependencies import get_active_shop
    from juli_backend.core.security import get_current_user

    app.dependency_overrides[get_current_user] = lambda: authenticated_user
    app.dependency_overrides[get_active_shop] = lambda: shop

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


@pytest.fixture
def mock_task_dispatcher(monkeypatch):
    dispatcher = MagicMock()
    dispatcher.enqueue.return_value = "celery-task-id-305"
    monkeypatch.setattr(
        "juli_backend.services.execution.dispatch.get_task_dispatcher",
        lambda: dispatcher,
    )
    return dispatcher


@pytest.fixture
def track_inline_runner(monkeypatch):
    calls: list[str] = []

    def _runner(tool_name: str, payload: dict) -> dict:
        calls.append(tool_name)
        return {"tool_name": tool_name, "ok": True}

    monkeypatch.setattr(
        "juli_backend.services.execution.runner.run_tool",
        _runner,
    )
    return calls


async def test_ac1_post_executions_returns_after_enqueue_without_inline_run(
    auth_client,
    mock_task_dispatcher,
    track_inline_runner,
):
    """AC1: HTTP handler returns 202 after enqueue; tool runner not called inline."""
    response = await auth_client.post(
        "/v1/executions",
        json={
            "approval_id": "approval-305-ac1",
            "tool_name": "noop.ping",
            "payload": {"message": "hello"},
        },
    )
    assert response.status_code == 202
    body = response.json()
    assert body["success"] is True
    assert body["data"]["execution_id"]
    assert body["data"]["status"] == "queued"
    assert body["data"]["celery_task_id"] == "celery-task-id-305"
    assert track_inline_runner == []
    mock_task_dispatcher.enqueue.assert_called_once()


async def test_ac2_tool_execution_dispatched_to_celery_worker(
    auth_client,
    mock_task_dispatcher,
):
    """AC2: enqueue receives the persisted execution id for the Celery worker."""
    response = await auth_client.post(
        "/v1/executions",
        json={
            "approval_id": "approval-305-ac2",
            "tool_name": "noop.ping",
            "payload": {},
        },
    )
    execution_id = response.json()["data"]["execution_id"]
    mock_task_dispatcher.enqueue.assert_called_once_with(execution_id)


async def test_ac3_get_execution_returns_queryable_outcome_status(
    auth_client,
    mock_task_dispatcher,
    session,
    shop,
):
    """AC3: GET /v1/executions/{id} returns persisted status and outcome."""
    from juli_backend.services.execution.dispatch import mark_execution_finished
    from juli_backend.services.execution.types import ExecutionStatus

    create = await auth_client.post(
        "/v1/executions",
        json={
            "approval_id": "approval-305-ac3",
            "tool_name": "noop.ping",
            "payload": {"step": 1},
        },
    )
    execution_id = uuid.UUID(create.json()["data"]["execution_id"])

    queued = await auth_client.get(f"/v1/executions/{execution_id}")
    assert queued.status_code == 200
    assert queued.json()["data"]["status"] == ExecutionStatus.QUEUED.value

    await mark_execution_finished(
        session,
        shop.id,
        execution_id,
        status=ExecutionStatus.SUCCEEDED,
        outcome={"tool_name": "noop.ping", "ok": True},
    )
    await session.commit()

    done = await auth_client.get(f"/v1/executions/{execution_id}")
    assert done.status_code == 200
    data = done.json()["data"]
    assert data["status"] == ExecutionStatus.SUCCEEDED.value
    assert data["outcome"]["ok"] is True


async def test_celery_task_runs_tool_and_updates_status(session, shop, engine, monkeypatch):
    """Worker task executes tool via runner and persists terminal status."""
    from juli_backend.database.database import create_session_factory, init_session_factory
    from juli_backend.repositories.repos import ToolExecutionsRepo
    from juli_backend.services.execution.dispatch import create_queued_execution
    from juli_backend.services.execution.types import ExecutionStatus
    from juli_backend.workers.tasks import tool_execution

    factory = create_session_factory(engine)
    init_session_factory(factory)
    monkeypatch.setattr(tool_execution, "_ensure_session_factory", lambda: factory)

    record = await create_queued_execution(
        session,
        shop_id=shop.id,
        approval_id="worker-305",
        tool_name="noop.ping",
        payload={"worker": True},
        celery_task_id="sync-task",
    )
    shop_id = shop.id
    execution_id = record.id
    await session.commit()

    await tool_execution._execute_async(execution_id)

    async with factory() as read_session:
        repo = ToolExecutionsRepo(read_session)
        updated = await repo.get(shop_id, execution_id)
    assert updated.status == ExecutionStatus.SUCCEEDED.value
    outcome = json.loads(updated.outcome_json or "{}")
    assert outcome.get("ok") is True
