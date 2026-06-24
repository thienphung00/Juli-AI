"""Production API ASGI entrypoint tests."""

from __future__ import annotations

import importlib
import sys

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def api_main_module(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    module_name = "src.apps.api_gateway.api.main"
    sys.modules.pop(module_name, None)
    module = importlib.import_module(module_name)
    yield module
    sys.modules.pop(module_name, None)


@pytest_asyncio.fixture
async def api_client(api_main_module):
    transport = ASGITransport(app=api_main_module.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
async def test_api_main_health(api_client):
    response = await api_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_api_main_exposes_openapi_docs(api_client):
    response = await api_client.get("/docs")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_api_main_configures_session_factory(api_main_module):
    from src.shared.utils.data import get_session

    async with api_main_module.app.router.lifespan_context(api_main_module.app):
        session_gen = get_session()
        session = await anext(session_gen)
        try:
            assert session is not None
        finally:
            await session_gen.aclose()
