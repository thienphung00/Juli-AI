"""Production webhook ASGI entrypoint tests."""

from __future__ import annotations

import importlib
import sys

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def webhook_main_module(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("TIKTOK_APP_KEY", "test_app_key")
    monkeypatch.setenv("TIKTOK_APP_SECRET", "test_app_secret")
    module_name = "src.apps.api_gateway.services.webhook.main"
    sys.modules.pop(module_name, None)
    module = importlib.import_module(module_name)
    yield module
    sys.modules.pop(module_name, None)


@pytest_asyncio.fixture
async def webhook_client(webhook_main_module):
    transport = ASGITransport(app=webhook_main_module.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
async def test_webhook_main_health(webhook_client):
    response = await webhook_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_webhook_main_rejects_unsigned_request(webhook_client):
    response = await webhook_client.post(
        "/webhooks/tiktok",
        content=b"{}",
    )
    assert response.status_code == 401
