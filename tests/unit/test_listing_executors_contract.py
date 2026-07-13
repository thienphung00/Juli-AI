"""P2-B6 listing executor contract tests — Issue #379.

AC:
- listing.create_hero_product / listing.optimize_product registered and routed
- Sandbox-guarded Product API chain (mocked)
- POST /v1/executions → Celery worker → ToolExecution outcome
- API failure → failed status + error_message + error_category
"""

from __future__ import annotations

import base64
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

LISTING_TOOL_NAMES = frozenset(
    {"listing.create_hero_product", "listing.optimize_product"}
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
    user = User(id=user_id, phone="+849305000379")
    session.add(user)
    await session.flush()
    return user


@pytest_asyncio.fixture
async def shop(session, authenticated_user):
    s = Shop(
        id=uuid.uuid4(),
        user_id=authenticated_user.id,
        shop_name="Listing Executor Shop 379",
        tiktok_shop_id="tiktok_shop_379",
    )
    session.add(s)
    await session.flush()
    return s


@pytest_asyncio.fixture
async def sandbox_credential(session, shop):
    return await TikTokCredentialRepo(session).create(
        shop_id=shop.id,
        access_token="sandbox_access_379",
        refresh_token="sandbox_refresh_379",
        token_expires_at=datetime.now(UTC) + timedelta(days=7),
        merchant_authorization_id=SANDBOX_AUTH_ID,
        capability=TikTokCapability.SANDBOX_WRITE.value,
        shop_cipher="ROW_sandbox379cipher",
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
    dispatcher.enqueue.return_value = "celery-task-id-379"
    monkeypatch.setattr(
        "juli_backend.services.execution.dispatch.get_task_dispatcher",
        lambda: dispatcher,
    )
    return dispatcher


@pytest.fixture
def tiktok_env(monkeypatch):
    monkeypatch.setenv("TIKTOK_APP_KEY", "test-app-key-379")
    monkeypatch.setenv("TIKTOK_APP_SECRET", "test-app-secret-379")


def test_ac1_listing_tools_registered():
    """AC1: listing tool handlers are registered in the runner catalog."""
    from juli_backend.services.execution.runner import is_tool_registered

    for tool_name in LISTING_TOOL_NAMES:
        assert is_tool_registered(tool_name), f"missing registration: {tool_name}"


def test_ac1_workflow_keys_resolve_to_listing_tools():
    """AC1: workflow_key routing maps listing workflows to registered tool names."""
    from juli_backend.services.execution.tool_routing import resolve_tool_name

    assert resolve_tool_name("create_hero_product_1") == "listing.create_hero_product"
    assert resolve_tool_name("optimize_product_2") == "listing.optimize_product"


@pytest.mark.asyncio
async def test_ac4_create_hero_product_e2e_mocked_chain(
    auth_client,
    mock_task_dispatcher,
    session,
    shop,
    engine,
    sandbox_credential,
    tiktok_env,
    monkeypatch,
):
    """AC4: POST /v1/executions → worker → succeeded ToolExecution with product_id."""
    from juli_backend.database.database import create_session_factory, init_session_factory
    from juli_backend.repositories.repos import ToolExecutionsRepo
    from juli_backend.workers.tasks import tool_execution

    mock_resources = MagicMock()
    mock_resources.products.check_listing_prerequisites.return_value = {"check_results": []}
    mock_resources.products.get_category_attributes.return_value = {"attributes": []}
    mock_resources.products.upload_product_image.return_value = {
        "uri": "tos-alisg-i-aphluv4xwc-sg/test-image-uri"
    }
    mock_resources.products.create.return_value = {
        "product_id": "1736405947247986307",
        "skus": [{"id": "1736405690908575363"}],
    }
    mock_resources.products.search.return_value = {"products": [{"id": "1736405947247986307"}]}

    monkeypatch.setattr(
        "juli_backend.services.execution.listing_handlers.load_sandbox_write_resources",
        AsyncMock(return_value=mock_resources),
    )

    factory = create_session_factory(engine)
    init_session_factory(factory)
    monkeypatch.setattr(tool_execution, "_ensure_session_factory", lambda: factory)

    image_bytes = base64.b64encode(b"fake-png-bytes").decode()
    response = await auth_client.post(
        "/v1/executions",
        json={
            "approval_id": "approval-379-create-hero",
            "tool_name": "listing.create_hero_product",
            "payload": {
                "category_id": "605254",
                "title": "Premium Stainless Steel Water Bottle 750ml",
                "description": "Durable bottle",
                "image_content_base64": image_bytes,
                "seller_sku": "water-bottle-100ml",
                "warehouse_id": "7657265511696664340",
                "price": {"amount": "100000", "currency": "VND"},
                "product_attributes": [
                    {"id": "100149", "values": [{"id": "1000854"}]},
                ],
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
    assert outcome["product_id"] == "1736405947247986307"
    assert outcome["tool_name"] == "listing.create_hero_product"
    mock_resources.products.upload_product_image.assert_called_once()
    mock_resources.products.create.assert_called_once()


@pytest.mark.asyncio
async def test_ac5_create_hero_product_api_failure_records_failed_status(
    session,
    shop,
    engine,
    sandbox_credential,
    tiktok_env,
    monkeypatch,
):
    """AC5: TikTok API failure → failed ToolExecution with useful error_message."""
    from juli_backend.database.database import create_session_factory, init_session_factory
    from juli_backend.repositories.repos import ToolExecutionsRepo
    from juli_backend.services.execution.dispatch import create_queued_execution
    from juli_backend.workers.tasks import tool_execution

    mock_resources = MagicMock()
    mock_resources.products.check_listing_prerequisites.return_value = {"check_results": []}
    mock_resources.products.get_category_attributes.return_value = {"attributes": []}
    mock_resources.products.upload_product_image.return_value = {"uri": "tos-uri"}
    mock_resources.products.create.side_effect = TikTokAPIError(
        100004, "Invalid product parameters"
    )

    monkeypatch.setattr(
        "juli_backend.services.execution.listing_handlers.load_sandbox_write_resources",
        AsyncMock(return_value=mock_resources),
    )

    factory = create_session_factory(engine)
    init_session_factory(factory)
    monkeypatch.setattr(tool_execution, "_ensure_session_factory", lambda: factory)

    record = await create_queued_execution(
        session,
        shop_id=shop.id,
        approval_id="approval-379-failure",
        tool_name="listing.create_hero_product",
        payload={
            "category_id": "605254",
            "title": "Bad Product",
            "description": "x",
            "image_uri": "tos-alisg-i-aphluv4xwc-sg/existing-uri",
            "seller_sku": "sku-1",
            "warehouse_id": "7657265511696664340",
            "price": {"amount": "100000", "currency": "VND"},
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
    assert "Invalid product parameters" in (updated.error_message or "")


@pytest.mark.asyncio
async def test_ac4_optimize_product_e2e_mocked_chain(
    session,
    shop,
    engine,
    sandbox_credential,
    tiktok_env,
    monkeypatch,
):
    """AC4: optimize_product executor runs get → edit → price update chain."""
    from juli_backend.database.database import create_session_factory, init_session_factory
    from juli_backend.repositories.repos import ToolExecutionsRepo
    from juli_backend.services.execution.dispatch import create_queued_execution
    from juli_backend.workers.tasks import tool_execution

    product_id = "1736405947247986307"
    mock_resources = MagicMock()
    mock_resources.products.get_details.return_value = {
        "id": product_id,
        "title": "Old Title",
    }
    mock_resources.products.get_seo_words.return_value = {
        "products": [{"id": product_id, "seo_words": []}]
    }
    mock_resources.products.get_suggestions.return_value = {
        "products": [
            {
                "id": product_id,
                "suggestions": [
                    {"field": "TITLE", "items": [{"text": "Suggested Hero Title"}]},
                ],
            }
        ]
    }
    mock_resources.products.edit.return_value = {
        "product_id": product_id,
        "audit": {"status": "APPROVED"},
    }
    mock_resources.products.update_prices.return_value = {}

    monkeypatch.setattr(
        "juli_backend.services.execution.listing_handlers.load_sandbox_write_resources",
        AsyncMock(return_value=mock_resources),
    )

    factory = create_session_factory(engine)
    init_session_factory(factory)
    monkeypatch.setattr(tool_execution, "_ensure_session_factory", lambda: factory)

    record = await create_queued_execution(
        session,
        shop_id=shop.id,
        approval_id="approval-379-optimize",
        tool_name="listing.optimize_product",
        payload={
            "product_id": product_id,
            "price_update": {
                "skus": [{"id": "1736433041572857475", "price": {"currency": "VND", "amount": "80000"}}]
            },
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
    assert outcome["product_id"] == product_id
    mock_resources.products.get_details.assert_called_once_with(product_id)
    mock_resources.products.edit.assert_called_once()
    edit_body = mock_resources.products.edit.call_args.kwargs["body"]
    assert edit_body["title"] == "Suggested Hero Title"
    mock_resources.products.update_prices.assert_called_once()


def test_create_hero_product_derives_brand_id_from_catalog():
    """Brand_id is resolved from Get Brands when attributes require a brand."""
    from juli_backend.services.execution.listing import run_create_hero_product_chain

    mock_products = MagicMock()
    mock_products.check_listing_prerequisites.return_value = {"check_results": []}
    mock_products.get_category_attributes.return_value = {
        "attributes": [{"id": "1", "name": "Brand", "is_requried": True, "values": []}]
    }
    mock_products.get_brands.return_value = {
        "brands": [{"id": "brand-999", "authorized_status": "AUTHORIZED"}]
    }
    mock_products.upload_product_image.return_value = {"uri": "tos-uri"}
    mock_products.create.return_value = {"product_id": "pid-1", "skus": []}
    mock_products.search.return_value = {"products": []}

    mock_resources = MagicMock()
    mock_resources.products = mock_products

    outcome = run_create_hero_product_chain(
        mock_resources,
        {
            "category_id": "605254",
            "title": "Bottle",
            "description": "Steel bottle",
            "image_content_base64": base64.b64encode(b"img").decode(),
            "seller_sku": "sku-1",
            "warehouse_id": "wh-1",
            "price": {"amount": "100000", "currency": "VND"},
        },
    )

    assert outcome["brand_id"] == "brand-999"
    create_body = mock_products.create.call_args.kwargs["body"]
    assert create_body["brand_id"] == "brand-999"


def test_listing_catalog_endpoints_documented_in_contract_collection():
    """Contract-collection documents listing chain endpoints used by executors."""
    from pathlib import Path

    contracts = (
        Path(__file__).resolve().parents[2]
        / "docs/integrations/tiktok_api/contract-collection.md"
    )
    text = contracts.read_text(encoding="utf-8")
    assert "GET /product/202309/categories" in text
    assert "GET /product/202309/categories/{category_id}/attributes" in text
    assert "POST /product/202309/images/upload" in text
    assert "POST /product/202309/products" in text


def test_execution_md_p2_b6_checkbox_complete():
    """EXECUTION.md marks P2-B6 complete for issue #379."""
    import re
    from pathlib import Path

    execution = Path(__file__).resolve().parents[2] / "EXECUTION.md"
    text = execution.read_text(encoding="utf-8")
    assert re.search(r"- \[x\] \*\*P2-B6\*\*", text)
    assert "#379" in text
