"""Regression tests for TikTok webhook ingress on the main API (Issue #381).

Root cause: TikTok Partner Center calls ``POST /webhooks/tiktok`` against the
deployed ``juli_backend.api.main:app`` process, but that route only existed on
the separate, undeployed ``juli_backend.services.webhook`` app — so production
returned 404. These tests assert the route now resolves on the app that is
actually deployed (`juli_backend.api.app.create_app`), using the same DI
session pattern as every other `/v1/*` route, while unrelated paths still 404.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from juli_backend.models.models import Shop, User
from juli_backend.services.webhook.app import WEBHOOK_PATH

APP_KEY = "test_app_key"
APP_SECRET = "test_app_secret"


def _sign(app_key: str, app_secret: str, path: str, body: bytes) -> str:
    sign_string = f"{app_key}{path}{body.decode()}"
    return hmac.new(app_secret.encode(), sign_string.encode(), hashlib.sha256).hexdigest()


@pytest_asyncio.fixture
async def app(engine, monkeypatch):
    from juli_backend.api.app import create_app
    from juli_backend.database import get_session

    monkeypatch.setenv("TIKTOK_APP_KEY", APP_KEY)
    monkeypatch.setenv("TIKTOK_APP_SECRET", APP_SECRET)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    application = create_app()

    async def _test_session():
        async with factory() as sess:
            yield sess

    application.dependency_overrides[get_session] = _test_session
    yield application
    application.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


def test_webhook_route_is_registered_on_the_main_api(app):
    """AC: the deployed app (not just the standalone webhook app) exposes the route."""
    paths = set(app.openapi()["paths"])
    assert WEBHOOK_PATH in paths


@pytest.mark.asyncio
async def test_unrelated_path_still_returns_404(client):
    """Verification: invalid paths keep returning 404 (no over-broad catch-all)."""
    resp = await client.post("/webhooks/not-tiktok")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_missing_signature_returns_401(client):
    resp = await client.post(
        WEBHOOK_PATH,
        content=b"{}",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_webhook_not_configured_returns_503(engine, monkeypatch):
    """Missing TikTok credentials fail closed (503), matching sibling TikTok routes."""
    from juli_backend.api.app import create_app
    from juli_backend.database import get_session

    monkeypatch.delenv("TIKTOK_APP_KEY", raising=False)
    monkeypatch.delenv("TIKTOK_APP_SECRET", raising=False)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    application = create_app()

    async def _test_session():
        async with factory() as sess:
            yield sess

    application.dependency_overrides[get_session] = _test_session

    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as unconfigured_client:
        resp = await unconfigured_client.post(
            WEBHOOK_PATH,
            content=b"{}",
            headers={"Content-Type": "application/json"},
        )
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_valid_webhook_delivery_is_accepted_and_persists_side_effects(
    client, session, user_id
):
    """End-to-end: signed delivery -> 200 ack, and the DI session actually commits."""
    shop = Shop(
        id=uuid.uuid4(),
        user_id=user_id,
        shop_name="Regression Shop",
        tiktok_shop_id="shop_381",
        is_active=True,
    )
    session.add(User(id=user_id, phone="+84123456789"))
    session.add(shop)
    await session.commit()

    body = json.dumps(
        {
            "type": "SELLER_DEAUTHORIZATION",
            "shop_id": "shop_381",
            "timestamp": 1_700_000_000,
            "data": {},
        }
    ).encode()
    signature = _sign(APP_KEY, APP_SECRET, WEBHOOK_PATH, body)

    resp = await client.post(
        WEBHOOK_PATH,
        content=body,
        headers={"Authorization": signature, "Content-Type": "application/json"},
    )

    assert resp.status_code == 200
    assert resp.json() == {"code": 0}

    await session.refresh(shop)
    assert shop.is_active is False, "handler must persist through the DI session, not a fixture-local one"
