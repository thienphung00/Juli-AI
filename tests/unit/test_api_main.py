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
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "test-jwt-secret-for-api-main-tests")
    module_name = "juli_backend.api.main"
    sys.modules.pop(module_name, None)
    module = importlib.import_module(module_name)
    yield module
    sys.modules.pop(module_name, None)


def _import_api_main_module():
    module_name = "juli_backend.api.main"
    sys.modules.pop(module_name, None)
    return importlib.import_module(module_name)


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
    from juli_backend.database import get_session

    async with api_main_module.app.router.lifespan_context(api_main_module.app):
        session_gen = get_session()
        session = await anext(session_gen)
        try:
            assert session is not None
        finally:
            await session_gen.aclose()


class TestLifespanAssertsJwtSecretAtStartup:
    """Issue #926 (ADR-061 "Startup assertions (fail to boot)") — a missing
    SUPABASE_JWT_SECRET must fail the process at boot, not on the first
    authenticated request. #894 asserted this only inside the per-request
    get_current_user dependency (see tests/unit/test_get_current_user.py,
    which calls that dependency directly and therefore never exercises
    startup). These tests boot the real api/main.py lifespan."""

    @pytest.mark.asyncio
    async def test_lifespan_raises_when_jwt_secret_absent(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
        monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)
        module = _import_api_main_module()
        try:
            with pytest.raises(RuntimeError, match="SUPABASE_JWT_SECRET") as exc_info:
                async with module.app.router.lifespan_context(module.app):
                    pytest.fail("lifespan must not yield when the secret is absent")
        finally:
            sys.modules.pop(module.__name__, None)

        # AC: message names the variable and carries no secret value — there
        # is none to leak since the variable is unset, but the message must
        # stay a static, non-secret-bearing string naming only the env var.
        assert str(exc_info.value) == "Missing required environment variable: SUPABASE_JWT_SECRET"

    @pytest.mark.asyncio
    async def test_lifespan_boots_normally_when_jwt_secret_present(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
        monkeypatch.setenv("SUPABASE_JWT_SECRET", "test-jwt-secret-for-api-main-tests")
        module = _import_api_main_module()
        try:
            async with module.app.router.lifespan_context(module.app):
                pass
        finally:
            sys.modules.pop(module.__name__, None)
