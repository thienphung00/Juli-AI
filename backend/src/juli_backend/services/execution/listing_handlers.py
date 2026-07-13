"""Listing workflow Celery tool handlers — P2-B6 (#379)."""

from __future__ import annotations

import os
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.services.execution.listing import (
    run_create_hero_product_chain,
    run_optimize_product_chain,
)
from juli_backend.services.execution.runner import register_async_tool
from juli_backend.services.execution.sandbox_guard import load_sandbox_write_resources


def _tiktok_app_credentials() -> tuple[str, str]:
    app_key = os.getenv("TIKTOK_APP_KEY", "").strip()
    app_secret = os.getenv("TIKTOK_APP_SECRET", "").strip()
    if not app_key or not app_secret:
        raise ValueError("TIKTOK_APP_KEY and TIKTOK_APP_SECRET must be set for listing executors")
    return app_key, app_secret


async def _load_listing_resources(session: AsyncSession):
    app_key, app_secret = _tiktok_app_credentials()
    return await load_sandbox_write_resources(
        session,
        app_key=app_key,
        app_secret=app_secret,
    )


async def create_hero_product_handler(
    session: AsyncSession,
    payload: dict[str, Any],
) -> dict[str, Any]:
    resources = await _load_listing_resources(session)
    return run_create_hero_product_chain(resources, payload)


async def optimize_product_handler(
    session: AsyncSession,
    payload: dict[str, Any],
) -> dict[str, Any]:
    resources = await _load_listing_resources(session)
    return run_optimize_product_chain(resources, payload)


register_async_tool("listing.create_hero_product", create_hero_product_handler)
register_async_tool("listing.optimize_product", optimize_product_handler)
