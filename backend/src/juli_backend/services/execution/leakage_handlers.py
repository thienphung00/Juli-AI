"""Leakage workflow Celery tool handlers — P2-B7 (#380, inventory + promotion sub-PR)."""

from __future__ import annotations

import os
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.services.execution.inventory_leakage import (
    run_clear_excess_inventory_chain,
    run_replenish_inventory_chain,
)
from juli_backend.services.execution.promotion_leakage import (
    run_create_activity_chain,
    run_delete_activity_chain,
    run_update_activity_chain,
)
from juli_backend.services.execution.runner import register_async_tool
from juli_backend.services.execution.sandbox_guard import load_sandbox_write_resources


def _tiktok_app_credentials() -> tuple[str, str]:
    app_key = os.getenv("TIKTOK_APP_KEY", "").strip()
    app_secret = os.getenv("TIKTOK_APP_SECRET", "").strip()
    if not app_key or not app_secret:
        raise ValueError(
            "TIKTOK_APP_KEY and TIKTOK_APP_SECRET must be set for leakage executors"
        )
    return app_key, app_secret


async def _load_leakage_resources(session: AsyncSession):
    app_key, app_secret = _tiktok_app_credentials()
    return await load_sandbox_write_resources(
        session,
        app_key=app_key,
        app_secret=app_secret,
    )


async def replenish_inventory_handler(
    session: AsyncSession,
    payload: dict[str, Any],
) -> dict[str, Any]:
    resources = await _load_leakage_resources(session)
    return run_replenish_inventory_chain(resources, payload)


async def clear_excess_inventory_handler(
    session: AsyncSession,
    payload: dict[str, Any],
) -> dict[str, Any]:
    resources = await _load_leakage_resources(session)
    return run_clear_excess_inventory_chain(resources, payload)


async def create_activity_handler(
    session: AsyncSession,
    payload: dict[str, Any],
) -> dict[str, Any]:
    resources = await _load_leakage_resources(session)
    return run_create_activity_chain(resources, payload)


async def update_activity_handler(
    session: AsyncSession,
    payload: dict[str, Any],
) -> dict[str, Any]:
    resources = await _load_leakage_resources(session)
    return run_update_activity_chain(resources, payload)


async def delete_activity_handler(
    session: AsyncSession,
    payload: dict[str, Any],
) -> dict[str, Any]:
    resources = await _load_leakage_resources(session)
    return run_delete_activity_chain(resources, payload)


register_async_tool("inventory.replenish", replenish_inventory_handler)
register_async_tool("inventory.clear_excess", clear_excess_inventory_handler)
register_async_tool("promotion.create_activity", create_activity_handler)
register_async_tool("promotion.update_activity", update_activity_handler)
register_async_tool("promotion.delete_activity", delete_activity_handler)
