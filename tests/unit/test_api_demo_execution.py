"""Public Demo approve -> execute HTTP path (#717, B-5) — POST /v1/demo/decisions/{id}/approve.

Unauthenticated, server-bound reference shop (same DEMO_REFERENCE_SHOP_ID pattern
as GET /v1/demo/analytics, #531). No X-Shop-Id header, no bearer token, no TikTok
credentials required — ADR-037 Demo no-auth + dry-run.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from juli_backend.models.models import ActionCard, Shop, User


@pytest.fixture
def demo_reference_shop_id() -> uuid.UUID:
    return uuid.UUID("b2c3d4e5-f6a7-8901-bcde-f12345678901")


@pytest.fixture
def demo_env(monkeypatch, demo_reference_shop_id):
    monkeypatch.setenv("DEMO_REFERENCE_SHOP_ID", str(demo_reference_shop_id))


@pytest_asyncio.fixture
async def reference_shop(session, user_id, demo_reference_shop_id):
    user = User(id=user_id, phone="+849170000717")
    shop = Shop(
        id=demo_reference_shop_id,
        user_id=user_id,
        shop_name="Reference Shop 717",
        tiktok_shop_id="tiktok_ref_717",
    )
    session.add_all([user, shop])
    await session.flush()
    return shop


@pytest_asyncio.fixture
async def reference_action_card(session, reference_shop):
    card = ActionCard(
        id=uuid.uuid4(),
        shop_id=reference_shop.id,
        workflow_key="replenish_inventory_3",
        priority=1,
        severity="high",
        title="Replenish low-stock SKU",
        description="Stock is running low.",
        recommendation_payload="{}",
        status="active",
    )
    session.add(card)
    await session.flush()
    return card


@pytest_asyncio.fixture
async def demo_client(engine, demo_env):
    from juli_backend.api.app import create_app
    from juli_backend.database import get_session

    factory = async_sessionmaker(engine, expire_on_commit=False)
    application = create_app()

    async def _test_session():
        async with factory() as sess:
            yield sess

    application.dependency_overrides[get_session] = _test_session
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        yield client
    application.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_approve_endpoint_creates_local_execution_record_without_auth(
    demo_client, reference_action_card
):
    resp = await demo_client.post(f"/v1/demo/decisions/{reference_action_card.id}/approve")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    data = body["data"]
    assert data["action_card_id"] == str(reference_action_card.id)
    assert data["status"] == "done"
    states = [step["state"] for step in data["narrative"]]
    assert states == ["queued", "running", "done"]
    # Internal identifiers stay out of the public response body.
    assert "workflow_key" not in data
    assert "tool_name" not in data


@pytest.mark.asyncio
async def test_approve_endpoint_rejects_unknown_decision(demo_client, reference_shop):
    resp = await demo_client.post(f"/v1/demo/decisions/{uuid.uuid4()}/approve")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_approve_endpoint_never_invokes_the_partner_write_module(
    demo_client, reference_action_card
):
    from unittest.mock import patch

    with (
        patch("juli_backend.services.execution.dispatch.enqueue_approved_tool") as enqueue_mock,
        patch("juli_backend.services.execution.runner.run_tool_async") as run_mock,
    ):
        resp = await demo_client.post(f"/v1/demo/decisions/{reference_action_card.id}/approve")

        assert resp.status_code == 200, resp.text
        enqueue_mock.assert_not_called()
        run_mock.assert_not_called()


@pytest.mark.asyncio
async def test_approve_endpoint_succeeds_without_live_shop_credentials(
    demo_client, reference_action_card, session
):
    """AC4 at the HTTP boundary: no TikTokCredential row exists for the reference shop."""
    from sqlalchemy import select

    from juli_backend.models.models import TikTokCredential

    creds = (
        (
            await session.execute(
                select(TikTokCredential).where(
                    TikTokCredential.shop_id == reference_action_card.shop_id
                )
            )
        )
        .scalars()
        .all()
    )
    assert creds == []

    resp = await demo_client.post(f"/v1/demo/decisions/{reference_action_card.id}/approve")
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["status"] == "done"
