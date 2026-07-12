"""P2-B5 Outcome tracking instrumentation contract tests — Issue #306.

AC1 → test_ac1_worker_records_workflow_outcome_in_oltp
AC2 → test_ac2_metrics_available_for_internal_validation
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
    user = User(id=user_id, phone="+849306000306")
    session.add(user)
    await session.flush()
    return user


@pytest_asyncio.fixture
async def shop(session, authenticated_user):
    s = Shop(
        id=uuid.uuid4(),
        user_id=authenticated_user.id,
        shop_name="Outcome Tracking Shop 306",
        tiktok_shop_id="tiktok_shop_306",
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
    dispatcher.enqueue.return_value = "celery-task-id-306"
    monkeypatch.setattr(
        "juli_backend.services.execution.dispatch.get_task_dispatcher",
        lambda: dispatcher,
    )
    return dispatcher


async def test_ac1_worker_records_workflow_outcome_in_oltp(
    session,
    shop,
    engine,
    monkeypatch,
):
    """AC1: Terminal execution persists workflow_outcome_records in OLTP."""
    from juli_backend.database.database import create_session_factory, init_session_factory
    from juli_backend.repositories.repos import ToolExecutionsRepo, WorkflowOutcomeRecordsRepo
    from juli_backend.services.execution.dispatch import create_queued_execution
    from juli_backend.services.execution.types import ExecutionStatus
    from juli_backend.workers.tasks import tool_execution

    factory = create_session_factory(engine)
    init_session_factory(factory)
    monkeypatch.setattr(tool_execution, "_ensure_session_factory", lambda: factory)

    record = await create_queued_execution(
        session,
        shop_id=shop.id,
        approval_id="approval-306-ac1",
        tool_name="noop.ping",
        payload={"workflow_id": "npl"},
        celery_task_id="sync-task-306",
    )
    shop_id = shop.id
    execution_id = record.id
    await session.commit()

    await tool_execution._execute_async(execution_id)

    async with factory() as read_session:
        exec_repo = ToolExecutionsRepo(read_session)
        updated = await exec_repo.get(shop_id, execution_id)
        assert updated.status == ExecutionStatus.SUCCEEDED.value

        outcome_repo = WorkflowOutcomeRecordsRepo(read_session)
        outcome = await outcome_repo.get_by_approval_id(shop_id, "approval-306-ac1")
        assert outcome.approval_id == "approval-306-ac1"
        assert outcome.execution_id == execution_id
        assert outcome.workflow_id == "npl"
        metrics = json.loads(outcome.metrics_json)
        assert metrics["workflow_id"] == "npl"
        assert metrics["success_criteria"]["metric"] == "SPS change"
        assert metrics["cadences"][0]["cadence"] == "realtime"


async def test_ac2_metrics_available_for_internal_validation(
    auth_client,
    mock_task_dispatcher,
    session,
    shop,
    engine,
    monkeypatch,
):
    """AC2: GET /v1/workflow-outcomes/{approval_id} returns metrics envelope."""
    from juli_backend.database.database import create_session_factory, init_session_factory
    from juli_backend.workers.tasks import tool_execution

    factory = create_session_factory(engine)
    init_session_factory(factory)
    monkeypatch.setattr(tool_execution, "_ensure_session_factory", lambda: factory)

    approval_id = "approval-306-ac2"
    create = await auth_client.post(
        "/v1/executions",
        json={
            "approval_id": approval_id,
            "tool_name": "noop.ping",
            "payload": {"workflow_id": "budget_optimization"},
        },
    )
    assert create.status_code == 202
    execution_id = uuid.UUID(create.json()["data"]["execution_id"])

    await tool_execution._execute_async(execution_id)
    await session.commit()

    response = await auth_client.get(f"/v1/workflow-outcomes/{approval_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    data = body["data"]
    assert data["workflow_id"] == "budget_optimization"
    assert data["success_criteria"]["threshold"]
    assert len(data["cadences"]) == 4
    cadence_ids = [slice_["cadence"] for slice_ in data["cadences"]]
    assert cadence_ids == ["realtime", "daily", "weekly", "monthly"]
    assert data["cadences"][0]["execution_status"]
