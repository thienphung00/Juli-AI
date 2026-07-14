"""P2-B7 leakage executor contract tests — Issue #380 (sub-PR 1: inventory + promotion).

AC:
- inventory.replenish / inventory.clear_excess / promotion.* registered and routed
- Sandbox-guarded API chains (mocked)
- POST /v1/executions → Celery worker → ToolExecution outcome
- API failure → failed status + error_message + error_category
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from juli_backend.integrations.tiktok.capabilities import SANDBOX_AUTH_ID
from juli_backend.integrations.tiktok.exceptions import TikTokAPIError
from juli_backend.integrations.tiktok.merchant import TikTokCapability
from juli_backend.models.models import Shop, User
from juli_backend.repositories.repos import TikTokCredentialRepo
from juli_backend.services.execution.types import ExecutionErrorCategory, ExecutionStatus

LEAKAGE_TOOL_NAMES = frozenset(
    {
        "inventory.replenish",
        "inventory.clear_excess",
        "promotion.create_activity",
        "promotion.update_activity",
        "promotion.delete_activity",
    }
)


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
    user = User(id=user_id, phone="+849305000380")
    session.add(user)
    await session.flush()
    return user


@pytest_asyncio.fixture
async def shop(session, authenticated_user):
    s = Shop(
        id=uuid.uuid4(),
        user_id=authenticated_user.id,
        shop_name="Leakage Executor Shop 380",
        tiktok_shop_id="tiktok_shop_380",
    )
    session.add(s)
    await session.flush()
    return s


@pytest_asyncio.fixture
async def sandbox_credential(session, shop):
    return await TikTokCredentialRepo(session).create(
        shop_id=shop.id,
        access_token="sandbox_access_380",
        refresh_token="sandbox_refresh_380",
        token_expires_at=datetime.now(UTC) + timedelta(days=7),
        merchant_authorization_id=SANDBOX_AUTH_ID,
        capability=TikTokCapability.SANDBOX_WRITE.value,
        shop_cipher="ROW_sandbox380cipher",
    )


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
    dispatcher.enqueue.return_value = "celery-task-id-380"
    monkeypatch.setattr(
        "juli_backend.services.execution.dispatch.get_task_dispatcher",
        lambda: dispatcher,
    )
    return dispatcher


@pytest.fixture
def tiktok_env(monkeypatch):
    monkeypatch.setenv("TIKTOK_APP_KEY", "test-app-key-380")
    monkeypatch.setenv("TIKTOK_APP_SECRET", "test-app-secret-380")


def test_ac1_leakage_tools_registered():
    """AC1: inventory/promotion leakage handlers are registered."""
    from juli_backend.services.execution.runner import is_tool_registered

    for tool_name in LEAKAGE_TOOL_NAMES:
        assert is_tool_registered(tool_name), f"missing registration: {tool_name}"


def test_ac1_workflow_keys_resolve_to_leakage_tools():
    """AC1: workflow_key routing maps leakage workflows to registered tool names."""
    from juli_backend.services.execution.tool_routing import resolve_tool_name

    assert resolve_tool_name("replenish_inventory_3") == "inventory.replenish"
    assert resolve_tool_name("clear_excess_4") == "inventory.clear_excess"
    assert resolve_tool_name("create_activity_7a") == "promotion.create_activity"
    assert resolve_tool_name("update_activity_7c") == "promotion.update_activity"
    assert resolve_tool_name("delete_activity_7b") == "promotion.delete_activity"


@pytest.mark.asyncio
async def test_ac4_replenish_inventory_e2e_mocked_chain(
    auth_client,
    mock_task_dispatcher,
    session,
    shop,
    engine,
    sandbox_credential,
    tiktok_env,
    monkeypatch,
):
    """AC4: replenish executor runs inventory search → update chain."""
    from juli_backend.database.database import create_session_factory, init_session_factory
    from juli_backend.repositories.repos import ToolExecutionsRepo
    from juli_backend.workers.tasks import tool_execution

    product_id = "1736363193934775939"
    sku_id = "1736404513645233795"
    mock_resources = MagicMock()
    mock_resources.inventory.search.return_value = {
        "inventory": [
            {
                "product_id": product_id,
                "skus": [{"id": sku_id, "inventory": [{"quantity": 2, "warehouse_id": "wh-1"}]}],
            }
        ]
    }
    mock_resources.inventory.update.return_value = {}

    monkeypatch.setattr(
        "juli_backend.services.execution.leakage_handlers.load_sandbox_write_resources",
        AsyncMock(return_value=mock_resources),
    )

    factory = create_session_factory(engine)
    init_session_factory(factory)
    monkeypatch.setattr(tool_execution, "_ensure_session_factory", lambda: factory)

    response = await auth_client.post(
        "/v1/executions",
        json={
            "approval_id": "approval-380-replenish",
            "tool_name": "inventory.replenish",
            "payload": {
                "sku_ids": [sku_id],
                "quantity": 15,
                "warehouse_id": "7657265511696664340",
            },
        },
    )
    assert response.status_code == 202
    execution_id = uuid.UUID(response.json()["data"]["execution_id"])

    await tool_execution._execute_async(execution_id)

    async with factory() as read_session:
        record = await ToolExecutionsRepo(read_session).get(shop.id, execution_id)
    assert record.status == ExecutionStatus.SUCCEEDED.value
    outcome = json.loads(record.outcome_json or "{}")
    assert outcome["product_id"] == product_id
    assert outcome["sku_id"] == sku_id
    mock_resources.inventory.search.assert_called_once()
    mock_resources.inventory.update.assert_called_once()


@pytest.mark.asyncio
async def test_ac5_replenish_inventory_api_failure_records_failed_status(
    session,
    shop,
    engine,
    sandbox_credential,
    tiktok_env,
    monkeypatch,
):
    """AC5: TikTok API failure → failed ToolExecution with error_category."""
    from juli_backend.database.database import create_session_factory, init_session_factory
    from juli_backend.repositories.repos import ToolExecutionsRepo
    from juli_backend.services.execution.dispatch import create_queued_execution
    from juli_backend.workers.tasks import tool_execution

    mock_resources = MagicMock()
    mock_resources.inventory.update.side_effect = TikTokAPIError(100004, "Invalid inventory")

    monkeypatch.setattr(
        "juli_backend.services.execution.leakage_handlers.load_sandbox_write_resources",
        AsyncMock(return_value=mock_resources),
    )

    factory = create_session_factory(engine)
    init_session_factory(factory)
    monkeypatch.setattr(tool_execution, "_ensure_session_factory", lambda: factory)

    record = await create_queued_execution(
        session,
        shop_id=shop.id,
        approval_id="approval-380-failure",
        tool_name="inventory.replenish",
        payload={
            "product_id": "pid-1",
            "sku_id": "sku-1",
            "quantity": 10,
        },
        celery_task_id="sync-task",
    )
    shop_id = shop.id
    execution_id = record.id
    await session.commit()

    with pytest.raises(TikTokAPIError):
        await tool_execution._execute_async(execution_id)

    async with factory() as read_session:
        updated = await ToolExecutionsRepo(read_session).get(shop_id, execution_id)
    assert updated.status == ExecutionStatus.FAILED.value
    assert updated.error_category == ExecutionErrorCategory.TIKTOK_API.value


@pytest.mark.asyncio
async def test_ac4_create_activity_e2e_mocked_chain(
    session,
    shop,
    engine,
    sandbox_credential,
    tiktok_env,
    monkeypatch,
):
    """AC4: create_activity runs create → update_activity_products chain."""
    from juli_backend.database.database import create_session_factory, init_session_factory
    from juli_backend.repositories.repos import ToolExecutionsRepo
    from juli_backend.services.execution.dispatch import create_queued_execution
    from juli_backend.workers.tasks import tool_execution

    activity_id = "7660009586606409490"
    mock_resources = MagicMock()
    mock_resources.promotion.create_activity.return_value = {"activity_id": activity_id}
    mock_resources.promotion.update_activity_products.return_value = {"activity_id": activity_id}

    monkeypatch.setattr(
        "juli_backend.services.execution.leakage_handlers.load_sandbox_write_resources",
        AsyncMock(return_value=mock_resources),
    )

    factory = create_session_factory(engine)
    init_session_factory(factory)
    monkeypatch.setattr(tool_execution, "_ensure_session_factory", lambda: factory)

    record = await create_queued_execution(
        session,
        shop_id=shop.id,
        approval_id="approval-380-create-activity",
        tool_name="promotion.create_activity",
        payload={
            "activity": {
                "title": "7/7 Flash Sale",
                "activity_type": "FLASHSALE",
                "product_level": "VARIATION",
                "duration_type": "FIXED_TIME",
                "begin_time": 1783411200,
                "end_time": 1783432800,
            },
            "products": [
                {
                    "id": "1736405947247986307",
                    "skus": [
                        {
                            "id": "1736433041572857475",
                            "activity_price_amount": "80000",
                        }
                    ],
                }
            ],
        },
        celery_task_id="sync-task",
    )
    execution_id = record.id
    await session.commit()

    await tool_execution._execute_async(execution_id)

    async with factory() as read_session:
        updated = await ToolExecutionsRepo(read_session).get(shop.id, execution_id)
    assert updated.status == ExecutionStatus.SUCCEEDED.value
    outcome = json.loads(updated.outcome_json or "{}")
    assert outcome["activity_id"] == activity_id
    mock_resources.promotion.create_activity.assert_called_once()
    mock_resources.promotion.update_activity_products.assert_called_once()


def test_replenish_derives_product_id_from_inventory_search():
    """product_id/sku_id resolved from Inventory Search when omitted from payload."""
    from juli_backend.services.execution.inventory_leakage import run_replenish_inventory_chain

    mock_inventory = MagicMock()
    mock_inventory.search.return_value = {
        "inventory": [
            {
                "product_id": "pid-from-search",
                "skus": [{"id": "sku-from-search", "inventory": [{"quantity": 1}]}],
            }
        ]
    }
    mock_inventory.update.return_value = {}

    mock_resources = MagicMock()
    mock_resources.inventory = mock_inventory

    outcome = run_replenish_inventory_chain(
        mock_resources,
        {"sku_ids": ["sku-from-search"], "quantity": 20},
    )

    assert outcome["product_id"] == "pid-from-search"
    assert outcome["sku_id"] == "sku-from-search"
    mock_inventory.search.assert_called_once_with(sku_ids=["sku-from-search"])


def test_leakage_catalog_endpoints_documented_in_contract_collection():
    """Contract-collection documents inventory/promotion chain endpoints."""
    from pathlib import Path

    contracts = (
        Path(__file__).resolve().parents[2]
        / "docs/integrations/tiktok_api/contract-collection.md"
    )
    text = contracts.read_text(encoding="utf-8")
    assert "POST /product/202309/inventory/search" in text or "inventory/search" in text
    assert "POST /product/202309/products/{product_id}/inventory/update" in text
    assert "POST /promotion/202309/activities" in text
    assert "POST /promotion/202309/activities/{activity_id}/deactivate" in text
