"""The FastAPI app wired to a test session and an authenticated tenant.

Twenty-plus route test modules used to carry this stack verbatim. Use the
``app`` / ``tenant`` / ``auth_client`` fixtures from ``tests/unit/conftest.py``
in the common case; call these directly when a test needs two tenants or an
unauthenticated client.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.api.app import create_app
from juli_backend.api.dependencies import get_active_shop
from juli_backend.core.security import get_current_user
from juli_backend.database import get_session
from juli_backend.models.models import Shop, User


def build_app(session: AsyncSession) -> FastAPI:
    """The real app, with every route's session dependency yielding ``session``."""
    application = create_app()

    async def _test_session() -> AsyncIterator[AsyncSession]:
        yield session

    application.dependency_overrides[get_session] = _test_session
    return application


def authenticate(app: FastAPI, *, user: User, shop: Shop) -> None:
    """Make every request to ``app`` act as ``user`` operating ``shop``."""
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_active_shop] = lambda: shop


@asynccontextmanager
async def client_for(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


@asynccontextmanager
async def authenticated_client(
    session: AsyncSession, *, user: User, shop: Shop
) -> AsyncIterator[AsyncClient]:
    """One-shot: app + session + auth for ``(user, shop)``, torn down on exit."""
    app = build_app(session)
    authenticate(app, user=user, shop=shop)
    try:
        async with client_for(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


__all__ = ["authenticate", "authenticated_client", "build_app", "client_for"]
