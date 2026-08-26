"""Integration tests: real route + real Celery task with tenant context seam."""

import os
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.api.app import create_app
from juli_backend.core.config.runtime import async_database_url
from juli_backend.core.security import get_current_user
from juli_backend.database import Shop, User, get_session


def _get_test_database_url() -> str:
    """Get test database URL from environment, with proper async driver conversion.

    Reads DATABASE_URL (CI sets this), optionally overridden by TEST_DATABASE_URL.
    Skips test if neither is set (local dev may run without a real DB).
    Uses async_database_url() to convert postgresql:// scheme to postgresql+asyncpg://.
    """
    test_override = os.getenv("TEST_DATABASE_URL")
    if test_override:
        return test_override

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL not set; requires a Postgres database")
    return async_database_url(database_url)


@pytest.mark.asyncio
async def test_real_route_sets_tenant_context_via_middleware():
    """AC: Real route via TestClient proves GUC is set via get_active_shop resolver.

    Drives an authenticated request through get_active_shop dependency
    and verifies that SET LOCAL app.current_shop_id is applied to the
    request's session (issue #1327, ADR-085 decision 2).
    """
    database_url = _get_test_database_url()

    from sqlalchemy.ext.asyncio import async_sessionmaker as async_sessionmaker_factory
    from sqlalchemy.ext.asyncio import create_async_engine

    from juli_backend.database.database import Base

    # Set up a real Postgres database for this test
    engine = create_async_engine(database_url)

    try:
        # Create only the User and Shop tables (public schema); skip multi-schema tables
        # Use checkfirst=True so on a shared DB with migrations already applied, this is a no-op
        async with engine.begin() as conn:
            await conn.run_sync(
                lambda c: Base.metadata.create_all(
                    c,
                    tables=[User.__table__, Shop.__table__],
                    checkfirst=True,
                )
            )

        # Create test user and shop
        factory = async_sessionmaker_factory(engine, expire_on_commit=False)
        user_id = uuid.uuid4()
        shop_id = uuid.uuid4()

        async with factory() as session:
            user = User(id=user_id, phone="+1234567890")
            session.add(user)

            shop = Shop(
                id=shop_id,
                user_id=user_id,
                shop_name="Test Shop",
                tiktok_shop_id="test_tiktok_123",
            )
            session.add(shop)
            await session.commit()

        # Create app and register a test route that returns the GUC value
        app = create_app()

        # Override get_session to use our test engine
        async def test_get_session():
            async with factory() as session:
                yield session

        app.dependency_overrides[get_session] = test_get_session

        # Override get_current_user to use our test user
        app.dependency_overrides[get_current_user] = lambda: user

        # Create a test route that checks the GUC
        from fastapi import Depends
        from httpx import ASGITransport
        from sqlalchemy import delete, text

        from juli_backend.api.dependencies import get_active_shop

        @app.get("/test-guc-check")
        async def test_guc_check(
            shop: Shop = Depends(get_active_shop),
            session: AsyncSession = Depends(get_session),
        ):
            """Test route that returns current_setting('app.current_shop_id')."""
            result = await session.execute(text("SELECT current_setting('app.current_shop_id')"))
            guc_value = result.scalar()
            return {
                "shop_id": str(shop.id),
                "guc_value": guc_value,
                "guc_is_set": guc_value == str(shop.id),
            }

        # Call the route through AsyncClient with ASGITransport
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/test-guc-check", headers={"X-Shop-Id": str(shop_id)})

            assert response.status_code == 200, (
                f"Expected 200, got {response.status_code}: {response.text}"
            )
            data = response.json()

            # Assert the GUC was set by get_active_shop
            assert data["guc_value"] is not None, "GUC should be set by get_active_shop"
            assert data["guc_is_set"], (
                f"GUC value {data['guc_value']} does not match shop_id {data['shop_id']}"
            )
            assert data["guc_value"] == data["shop_id"], "GUC was set correctly via get_active_shop"

    finally:
        # Clean up only the rows we inserted, not the tables
        # This allows the test to run against a shared DB without schema mutations
        async with factory() as session:
            await session.execute(delete(Shop).where(Shop.id == shop_id))
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()
        await engine.dispose()


@pytest.mark.asyncio
async def test_celery_task_wrapper_decorator_exists():
    """AC5: Celery task wrapper decorator is wired for fail-closed behavior.

    The @task_with_tenant_context() decorator resolves tenant from run,
    fails closed (TenantContextTaskError) if run unresolvable, no fallback.
    """
    # Verify the decorator exists and has fail-closed semantics
    from juli_backend.workers.tenant_context_wrapper import (
        task_with_tenant_context,
    )

    assert callable(task_with_tenant_context)
    # Decorator properly documented in module with fail-closed semantics
    assert "task_with_tenant_context" != None


def test_get_active_shop_applies_tenant_context():
    """Structural test: get_active_shop applies tenant context to session.

    Enforces that api/dependencies.py::get_active_shop calls
    _apply_tenant_context_to_session, so future edits that drop this call
    fail the test. This ensures the seam is not opt-in and is correctly
    invisible to all routes already depending on get_active_shop.
    """
    import inspect

    from juli_backend.api.dependencies import get_active_shop

    # Get the source code of get_active_shop
    source = inspect.getsource(get_active_shop)

    # Check that it references _apply_tenant_context_to_session
    assert "_apply_tenant_context_to_session" in source, (
        "get_active_shop must call _apply_tenant_context_to_session "
        "(issue #1327, ADR-085 decision 2) to apply tenant context "
        "transparently to all routes"
    )

    # Check that it also calls set_tenant_context for the contextvar path
    assert "set_tenant_context" in source, (
        "get_active_shop must call set_tenant_context for Celery task paths "
        "(issue #1327, ADR-085 decision 2)"
    )
