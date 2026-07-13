"""P2-B4 reopened dispatch infrastructure — Issue #305.

AC (reopened):
- workflow_key → tool_name routing for WORKFLOW_COPY_TEMPLATE_KEYS
- idempotency key threaded POST → ToolExecution → worker payload
- coarse error taxonomy on ToolExecution
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from juli_backend.models.models import Shop, User
from juli_backend.services.scoring.copy_layer import WORKFLOW_COPY_TEMPLATE_KEYS

EXPECTED_WORKFLOW_TOOL_ROUTES: dict[str, str] = {
    "create_hero_product_1": "listing.create_hero_product",
    "optimize_product_2": "listing.optimize_product",
    "replenish_inventory_3": "inventory.replenish",
    "clear_excess_4": "inventory.clear_excess",
    "process_order_5": "fulfillment.process_order",
    "create_activity_7a": "promotion.create_activity",
    "update_activity_7c": "promotion.update_activity",
    "delete_activity_7b": "promotion.delete_activity",
    "prevent_cancellation_8a": "returns.prevent_cancellation",
    "prevent_return_8b": "returns.prevent_return",
    "prevent_refund_8c": "returns.prevent_refund",
}


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
        shop_name="Routing Shop 305",
        tiktok_shop_id="tiktok_shop_305_routing",
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
    dispatcher.enqueue.return_value = "celery-task-id-305-routing"
    monkeypatch.setattr(
        "juli_backend.services.execution.dispatch.get_task_dispatcher",
        lambda: dispatcher,
    )
    return dispatcher


def test_ac1_resolve_tool_name_maps_all_workflow_copy_template_keys():
    """AC1: every WORKFLOW_COPY_TEMPLATE_KEYS entry resolves to a registered tool name."""
    from juli_backend.services.execution.tool_routing import resolve_tool_name

    assert len(WORKFLOW_COPY_TEMPLATE_KEYS) == 11
    for workflow_key in sorted(WORKFLOW_COPY_TEMPLATE_KEYS):
        assert resolve_tool_name(workflow_key) == EXPECTED_WORKFLOW_TOOL_ROUTES[workflow_key]


def test_ac1_resolve_tool_name_returns_none_for_unknown_workflow_key():
    from juli_backend.services.execution.tool_routing import resolve_tool_name

    assert resolve_tool_name("not_a_real_workflow") is None


@pytest.mark.asyncio
async def test_ac2_idempotency_key_persisted_and_passed_to_worker_payload(
    auth_client,
    mock_task_dispatcher,
    session,
    shop,
    engine,
    monkeypatch,
):
    """AC2: idempotency_key flows POST → ToolExecution → Celery worker payload."""
    from juli_backend.database.database import create_session_factory, init_session_factory
    from juli_backend.repositories.repos import ToolExecutionsRepo
    from juli_backend.workers.tasks import tool_execution

    factory = create_session_factory(engine)
    init_session_factory(factory)
    monkeypatch.setattr(tool_execution, "_ensure_session_factory", lambda: factory)

    response = await auth_client.post(
        "/v1/executions",
        json={
            "approval_id": "approval-305-idempotency",
            "tool_name": "noop.ping",
            "idempotency_key": "idem-305-abc",
            "payload": {"step": "write"},
        },
    )
    assert response.status_code == 202
    execution_id = uuid.UUID(response.json()["data"]["execution_id"])

    record = await ToolExecutionsRepo(session).get(shop.id, execution_id)
    assert record.idempotency_key == "idem-305-abc"
    await session.commit()

    await tool_execution._execute_async(execution_id)

    async with factory() as read_session:
        updated = await ToolExecutionsRepo(read_session).get(shop.id, execution_id)
    outcome = json.loads(updated.outcome_json or "{}")
    assert outcome["payload"]["idempotency_key"] == "idem-305-abc"


@pytest.mark.asyncio
async def test_ac3_failed_execution_records_error_category(
    session,
    shop,
    engine,
    monkeypatch,
):
    """AC3: worker classifies failures into a coarse error_category taxonomy."""
    from juli_backend.database.database import create_session_factory, init_session_factory
    from juli_backend.integrations.tiktok.exceptions import RateLimitError
    from juli_backend.repositories.repos import ToolExecutionsRepo
    from juli_backend.services.execution.dispatch import create_queued_execution
    from juli_backend.services.execution.runner import register_tool
    from juli_backend.services.execution.types import ExecutionErrorCategory, ExecutionStatus
    from juli_backend.workers.tasks import tool_execution

    def _rate_limited(_payload: dict) -> dict:
        raise RateLimitError(100005, "throttled")

    register_tool("test.rate_limited", _rate_limited)

    factory = create_session_factory(engine)
    init_session_factory(factory)
    monkeypatch.setattr(tool_execution, "_ensure_session_factory", lambda: factory)

    record = await create_queued_execution(
        session,
        shop_id=shop.id,
        approval_id="approval-305-error-taxonomy",
        tool_name="test.rate_limited",
        payload={},
        celery_task_id="sync-task",
    )
    shop_id = shop.id
    execution_id = record.id
    await session.commit()

    with pytest.raises(RateLimitError):
        await tool_execution._execute_async(execution_id)

    async with factory() as read_session:
        updated = await ToolExecutionsRepo(read_session).get(shop_id, execution_id)
    assert updated.status == ExecutionStatus.FAILED.value
    assert updated.error_category == ExecutionErrorCategory.TRANSIENT.value


@pytest.mark.asyncio
async def test_ac4_sandbox_guard_rejects_production_merchant_auth_id(session):
    """AC4: sandbox write helper enforces SANDBOX_VN merchant auth (#301)."""
    from juli_backend.integrations.tiktok.factories import ClientFactoryConfig, SandboxWriteClientFactory
    from juli_backend.integrations.tiktok.merchant import PRODUCTION_AUTH_ID
    from juli_backend.services.execution.sandbox_guard import build_sandbox_write_resources

    config = ClientFactoryConfig(
        app_key="test-app",
        app_secret="test-secret",
        access_token="token",
        merchant_auth_id=PRODUCTION_AUTH_ID,
    )
    with pytest.raises(ValueError, match="SANDBOX_VN"):
        build_sandbox_write_resources(config, factory=SandboxWriteClientFactory())
