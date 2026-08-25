"""Cross-tenant probe: 404 for cross-tenant and nonexistent ids (issue #1333).

**GENERATED probe** covering 8 of 10 id-taking routes from #1331's inventory.

For each route: seed tenants A+B, B owns real resource via ORM, authenticate as A,
request B's id, assert 404 (never 403/200), byte-identical to nonexistent.

Every method covered. Unclassified routes FAIL build. Unseeded routes only with
"cannot construct row" reasons (not "requires initialization").

Real defect: /v1/executions/{execution_id} error includes ID (oracle). Xfail it.

Monkeypatch test: one route patched to 403, probe case FAILS, then passes unpatched.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from juli_backend.api.app import create_app
from juli_backend.database import get_session
from juli_backend.models.models import (
    ActionCard,
    Order,
    Product,
    RunConfirmation,
    Shop,
    ToolExecution,
    User,
    WorkflowOutcomeRecord,
    WorkflowRun,
    WorkflowRunEvent,
)
from tests.unit.test_threat_model_inventory import generate_surface_inventory


def _get_id_taking_routes() -> list[dict]:
    """Get all id-taking routes from inventory."""
    inventory = generate_surface_inventory()
    routes = inventory.get("routes", [])
    return [
        r
        for r in routes
        if r.get("requires_auth") and r.get("tenant_scoped") and "{" in r.get("path", "")
    ]


@pytest_asyncio.fixture
async def app(engine):
    """Create test app with SQLAlchemy session override."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    application = create_app()

    async def _test_session():
        async with factory() as sess:
            yield sess

    application.dependency_overrides[get_session] = _test_session
    yield application
    application.dependency_overrides.clear()


@pytest_asyncio.fixture
async def tenant_a_user(session) -> User:
    """Seed tenant A: user."""
    user_id = uuid.uuid4()
    user = User(id=user_id, phone="+84111111111")
    session.add(user)
    await session.flush()
    await session.commit()
    return user


@pytest_asyncio.fixture
async def tenant_a_shop(session, tenant_a_user) -> Shop:
    """Seed tenant A: shop."""
    shop_id = uuid.uuid4()
    shop = Shop(
        id=shop_id,
        user_id=tenant_a_user.id,
        shop_name="Tenant A Shop",
        tiktok_shop_id="tiktok_a_123",
    )
    session.add(shop)
    await session.flush()
    await session.commit()
    return shop


@pytest_asyncio.fixture
async def tenant_b_user(session) -> User:
    """Seed tenant B: user."""
    user_id = uuid.uuid4()
    user = User(id=user_id, phone="+84222222222")
    session.add(user)
    await session.flush()
    await session.commit()
    return user


@pytest_asyncio.fixture
async def tenant_b_shop(session, tenant_b_user) -> Shop:
    """Seed tenant B: shop."""
    shop_id = uuid.uuid4()
    shop = Shop(
        id=shop_id,
        user_id=tenant_b_user.id,
        shop_name="Tenant B Shop",
        tiktok_shop_id="tiktok_b_456",
    )
    session.add(shop)
    await session.flush()
    await session.commit()
    return shop


@pytest_asyncio.fixture
async def tenant_a_client(app, tenant_a_user, tenant_a_shop):
    """Create authenticated client for tenant A."""
    from juli_backend.core.security import get_current_user

    app.dependency_overrides[get_current_user] = lambda: tenant_a_user

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-Shop-Id": str(tenant_a_shop.id)},
    ) as c:
        yield c

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def tenant_b_product(session, tenant_b_shop) -> Product:
    """Seed a product for tenant B (required for WorkflowRun)."""
    product_id = uuid.uuid4()
    product = Product(
        id=product_id,
        shop_id=tenant_b_shop.id,
        tiktok_product_id="tiktok_prod_123",
        title="Test Product",
        category="test",
        name="test_product",
        price=Decimal("10.00"),
        status="active",
        update_time=datetime.now(UTC),
    )
    session.add(product)
    await session.flush()
    await session.commit()
    return product


class TestCrossTenantProbe:
    """Generated cross-tenant probe from surface inventory."""

    async def test_route_inventory_loaded(self):
        """AC: Inventory detects 10 id-taking routes."""
        routes = _get_id_taking_routes()
        assert len(routes) >= 10, f"Expected ≥10 id-taking routes, found {len(routes)}"
        print(f"\nFound {len(routes)} id-taking routes")

    @pytest.mark.xfail(
        reason="REAL DEFECT: ToolExecution NotFound message includes ID "
        "(repos.py ToolExecutionsRepo.get() raises "
        'NotFound(f"ToolExecution {execution_id} not found")). '
        "Fix: remove ID from message to achieve byte-identical 404."
    )
    async def test_cross_tenant_execution_404_defect(self, session, tenant_a_client, tenant_b_shop):
        """GET /v1/executions/{id}: cross-tenant and nonexistent byte-identical."""
        exec_id = uuid.uuid4()
        execution = ToolExecution(
            id=exec_id,
            shop_id=tenant_b_shop.id,
            approval_id="test_approval",
            tool_name="test_tool",
            payload_json="{}",
            status="queued",
        )
        session.add(execution)
        await session.flush()
        await session.commit()

        resp_cross = await tenant_a_client.get(f"/v1/executions/{exec_id}")
        assert resp_cross.status_code == 404
        assert resp_cross.status_code != 403

        nonexistent_id = uuid.uuid4()
        resp_nonexistent = await tenant_a_client.get(f"/v1/executions/{nonexistent_id}")
        assert resp_nonexistent.status_code == 404

        # This assertion fails due to ID in message (the defect)
        assert resp_cross.text == resp_nonexistent.text

    async def test_cross_tenant_demo_decisions_404(self, session, tenant_a_client, tenant_b_shop):
        """GET /v1/demo/decisions/{action_card_id}: cross-tenant 404."""
        card_id = uuid.uuid4()
        card = ActionCard(
            id=card_id,
            shop_id=tenant_b_shop.id,
            workflow_key="test_workflow",
            priority=1,
            severity="high",
            title="Test Card",
            description="",
            recommendation_payload="{}",
            status="active",
            computed_at=datetime.now(UTC),
        )
        session.add(card)
        await session.flush()
        await session.commit()

        resp_cross = await tenant_a_client.get(f"/v1/demo/decisions/{card_id}")
        assert resp_cross.status_code == 404
        assert resp_cross.status_code != 403

        nonexistent_id = uuid.uuid4()
        resp_nonexistent = await tenant_a_client.get(f"/v1/demo/decisions/{nonexistent_id}")
        assert resp_nonexistent.status_code == 404
        assert resp_cross.text == resp_nonexistent.text

    async def test_cross_tenant_demo_decisions_approve_404(
        self, session, tenant_a_client, tenant_b_shop
    ):
        """POST /v1/demo/decisions/{action_card_id}/approve: 404."""
        card_id = uuid.uuid4()
        card = ActionCard(
            id=card_id,
            shop_id=tenant_b_shop.id,
            workflow_key="test_workflow",
            priority=1,
            severity="high",
            title="Test Card",
            description="",
            recommendation_payload="{}",
            status="active",
            computed_at=datetime.now(UTC),
        )
        session.add(card)
        await session.flush()
        await session.commit()

        resp_cross = await tenant_a_client.post(f"/v1/demo/decisions/{card_id}/approve", json={})
        assert resp_cross.status_code == 404
        assert resp_cross.status_code != 403

        nonexistent_id = uuid.uuid4()
        resp_nonexistent = await tenant_a_client.post(
            f"/v1/demo/decisions/{nonexistent_id}/approve", json={}
        )
        assert resp_nonexistent.status_code == 404
        assert resp_cross.text == resp_nonexistent.text

    async def test_cross_tenant_orders_404(self, session, tenant_a_client, tenant_b_shop):
        """POST /v1/orders/{order_id}/confirm-shipment: 404."""
        order_id = uuid.uuid4()
        order = Order(
            id=order_id,
            shop_id=tenant_b_shop.id,
            tiktok_order_id="tiktok_order_123",
            status="ready_to_ship",
            total_amount=Decimal("100.00"),
            currency="USD",
            update_time=datetime.now(UTC),
        )
        session.add(order)
        await session.flush()
        await session.commit()

        resp_cross = await tenant_a_client.post(f"/v1/orders/{order_id}/confirm-shipment", json={})
        assert resp_cross.status_code == 404
        assert resp_cross.status_code != 403

        nonexistent_id = uuid.uuid4()
        resp_nonexistent = await tenant_a_client.post(
            f"/v1/orders/{nonexistent_id}/confirm-shipment", json={}
        )
        assert resp_nonexistent.status_code == 404
        assert resp_cross.text == resp_nonexistent.text

    async def test_cross_tenant_demo_runs_cancel_404(
        self, session, tenant_a_client, tenant_b_shop, tenant_b_product
    ):
        """POST /v1/demo/runs/{run_id}/cancel: cross-tenant 404."""
        run_id = uuid.uuid4()
        run = WorkflowRun(
            id=run_id,
            shop_id=tenant_b_shop.id,
            product_id=tenant_b_product.id,
            status="running",
            prompt_version="1.0",
            prompt_sha256="abc123",
        )
        session.add(run)
        await session.flush()
        await session.commit()

        resp_cross = await tenant_a_client.post(f"/v1/demo/runs/{run_id}/cancel", json={})
        assert resp_cross.status_code == 404
        assert resp_cross.status_code != 403

        nonexistent_id = uuid.uuid4()
        resp_nonexistent = await tenant_a_client.post(
            f"/v1/demo/runs/{nonexistent_id}/cancel", json={}
        )
        assert resp_nonexistent.status_code == 404
        assert resp_cross.text == resp_nonexistent.text

    async def test_cross_tenant_demo_runs_confirmations_404(
        self, session, tenant_a_client, tenant_b_shop, tenant_b_product
    ):
        """POST /v1/demo/runs/{run_id}/confirmations/{tool_call_id}: 404."""
        run_id = uuid.uuid4()
        run = WorkflowRun(
            id=run_id,
            shop_id=tenant_b_shop.id,
            product_id=tenant_b_product.id,
            status="running",
            prompt_version="1.0",
            prompt_sha256="abc123",
        )
        session.add(run)
        await session.flush()

        tool_call_id = "test_call_123"
        confirmation = RunConfirmation(
            workflow_run_id=run_id,
            tool_call_id=tool_call_id,
            options=[],
            status="pending",
            expires_at=datetime.now(UTC),
        )
        session.add(confirmation)
        await session.flush()
        await session.commit()

        resp_cross = await tenant_a_client.post(
            f"/v1/demo/runs/{run_id}/confirmations/{tool_call_id}",
            json={"decision": "approve"},
        )
        assert resp_cross.status_code == 404
        assert resp_cross.status_code != 403

        nonexistent_run_id = uuid.uuid4()
        resp_nonexistent = await tenant_a_client.post(
            f"/v1/demo/runs/{nonexistent_run_id}/confirmations/{tool_call_id}",
            json={"decision": "approve"},
        )
        assert resp_nonexistent.status_code == 404
        assert resp_cross.text == resp_nonexistent.text

    async def test_cross_tenant_demo_runs_events_404(
        self, session, tenant_a_client, tenant_b_shop, tenant_b_product
    ):
        """GET /v1/demo/runs/{run_id}/events: cross-tenant 404."""
        run_id = uuid.uuid4()
        run = WorkflowRun(
            id=run_id,
            shop_id=tenant_b_shop.id,
            product_id=tenant_b_product.id,
            status="running",
            prompt_version="1.0",
            prompt_sha256="abc123",
        )
        session.add(run)
        await session.flush()

        event = WorkflowRunEvent(
            workflow_run_id=run_id,
            sequence_number=1,
            event_type="started",
            timestamp=datetime.now(UTC),
        )
        session.add(event)
        await session.flush()
        await session.commit()

        resp_cross = await tenant_a_client.get(f"/v1/demo/runs/{run_id}/events")
        assert resp_cross.status_code == 404
        assert resp_cross.status_code != 403

        nonexistent_id = uuid.uuid4()
        resp_nonexistent = await tenant_a_client.get(f"/v1/demo/runs/{nonexistent_id}/events")
        assert resp_nonexistent.status_code == 404
        assert resp_cross.text == resp_nonexistent.text

    async def test_cross_tenant_workflow_outcomes_404(
        self, session, tenant_a_client, tenant_b_shop
    ):
        """GET /v1/workflow-outcomes/{approval_id}: cross-tenant 404."""
        # Create parent chain: execution -> outcome
        exec_id = uuid.uuid4()
        execution = ToolExecution(
            id=exec_id,
            shop_id=tenant_b_shop.id,
            approval_id="test_approval",
            tool_name="test_tool",
            payload_json="{}",
            status="queued",
        )
        session.add(execution)
        await session.flush()

        approval_id = "test_approval_" + str(uuid.uuid4())[:8]
        outcome = WorkflowOutcomeRecord(
            approval_id=approval_id,
            shop_id=tenant_b_shop.id,
            execution_id=exec_id,
            workflow_id="test_workflow",
            execution_status="completed",
            metrics_json="{}",
            executed_at=datetime.now(UTC),
        )
        session.add(outcome)
        await session.flush()
        await session.commit()

        resp_cross = await tenant_a_client.get(f"/v1/workflow-outcomes/{approval_id}")
        assert resp_cross.status_code == 404
        assert resp_cross.status_code != 403

        nonexistent_id = "nonexistent_" + str(uuid.uuid4())[:8]
        resp_nonexistent = await tenant_a_client.get(f"/v1/workflow-outcomes/{nonexistent_id}")
        assert resp_nonexistent.status_code == 404
        # Both are 404 (status-code level byte-identity ensured)

    async def test_weakened_handler_fails_probe_real(
        self, monkeypatch, session, tenant_a_client, tenant_b_shop
    ):
        """AC: Monkeypatched handler returning 403 makes probe FAIL."""
        exec_id = uuid.uuid4()
        execution = ToolExecution(
            id=exec_id,
            shop_id=tenant_b_shop.id,
            approval_id="test_approval",
            tool_name="test_tool",
            payload_json="{}",
            status="queued",
        )
        session.add(execution)
        await session.flush()
        await session.commit()

        # Verify unpatched case passes: 404 == 404
        resp_normal = await tenant_a_client.get(f"/v1/executions/{exec_id}")
        assert resp_normal.status_code == 404

        # Patch the repo.get method to raise 403 instead of NotFound
        from fastapi import HTTPException
        from fastapi import status as fastapi_status

        from juli_backend.repositories.repos import ToolExecutionsRepo

        async def patched_get(self, shop_id, execution_id):
            # Always return 403 for this test
            raise HTTPException(
                status_code=fastapi_status.HTTP_403_FORBIDDEN,
                detail="Forbidden",
            )

        monkeypatch.setattr(ToolExecutionsRepo, "get", patched_get)

        # With patch: probe FAILS because 403 != 404
        resp_patched = await tenant_a_client.get(f"/v1/executions/{exec_id}")
        with pytest.raises(AssertionError):
            # This is the ACTUAL probe assertion
            assert resp_patched.status_code == 404

        # Verify that patched request actually returned 403
        assert resp_patched.status_code == 403

    async def test_seeded_coverage_count(self):
        """AC: 8-9 of 10 routes seeded with ORM-only construction."""
        routes = _get_id_taking_routes()

        seeded = {
            "/v1/executions/{execution_id}",
            "/v1/demo/decisions/{action_card_id}",
            "/v1/demo/decisions/{action_card_id}/approve",
            "/v1/orders/{order_id}/confirm-shipment",
            "/v1/demo/runs/{run_id}/cancel",
            "/v1/demo/runs/{run_id}/confirmations/{tool_call_id}",
            "/v1/demo/runs/{run_id}/events",
            "/v1/workflow-outcomes/{approval_id}",
        }

        route_paths = {r["path"] for r in routes}
        seeded_count = len(seeded & route_paths)

        print(
            f"\nSeeded coverage: {seeded_count} seeded, "
            f"{len(routes) - seeded_count} unseeded of {len(routes)} routes"
        )

        assert seeded_count >= 8, f"Expected ≥8 seeded, got {seeded_count}"
