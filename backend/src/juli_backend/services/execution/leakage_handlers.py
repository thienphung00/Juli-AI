"""Leakage workflow Celery tool handlers — P2-B7 (#380, inventory + promotion sub-PR)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.services.execution.inventory_leakage import (
    run_clear_excess_inventory_chain,
    run_replenish_inventory_chain,
)
from juli_backend.services.execution.production_write_resolver import (
    resolve_write_capability,
)
from juli_backend.services.execution.promotion_leakage import (
    run_create_activity_chain,
    run_delete_activity_chain,
    run_update_activity_chain,
)
from juli_backend.services.execution.runner import register_async_tool


async def _load_leakage_resources_for_tool(
    session: AsyncSession,
    payload: dict[str, Any],
    tool_name: str,
):
    """Load leakage resources via the production write resolver.

    The resolver checks all four production write preconditions:
    1. PRODUCTION_WRITE_ENABLED flag is on (default off)
    2. Matching authorization exists
    3. RLS boot check passed
    4. Red-team attestation for release SHA

    With flag off (default), returns SandboxWriteResources. With all four met,
    returns a production capability marker dict. Otherwise raises PreconditionFailure.
    """
    shop_id_str = payload.get("_execution_shop_id")
    if not shop_id_str:
        raise ValueError("Payload missing _execution_shop_id; required for resolver")
    shop_id = uuid.UUID(shop_id_str)

    # Call the resolver to check all four preconditions
    return await resolve_write_capability(
        session,
        tool_name=tool_name,
        payload=payload,
        shop_id=shop_id,
    )


async def replenish_inventory_handler(
    session: AsyncSession,
    payload: dict[str, Any],
) -> dict[str, Any]:
    resources = await _load_leakage_resources_for_tool(
        session,
        payload,
        tool_name="inventory.replenish",
    )
    if isinstance(resources, dict) and resources.get("capability") == "production_write":
        return {
            "status": "production_authorized",
            "authorization_id": resources.get("authorization_id"),
        }
    return run_replenish_inventory_chain(resources, payload)


async def clear_excess_inventory_handler(
    session: AsyncSession,
    payload: dict[str, Any],
) -> dict[str, Any]:
    resources = await _load_leakage_resources_for_tool(
        session,
        payload,
        tool_name="inventory.clear_excess",
    )
    if isinstance(resources, dict) and resources.get("capability") == "production_write":
        return {
            "status": "production_authorized",
            "authorization_id": resources.get("authorization_id"),
        }
    return run_clear_excess_inventory_chain(resources, payload)


async def create_activity_handler(
    session: AsyncSession,
    payload: dict[str, Any],
) -> dict[str, Any]:
    resources = await _load_leakage_resources_for_tool(
        session,
        payload,
        tool_name="promotion.create_activity",
    )
    if isinstance(resources, dict) and resources.get("capability") == "production_write":
        return {
            "status": "production_authorized",
            "authorization_id": resources.get("authorization_id"),
        }
    return run_create_activity_chain(resources, payload)


async def update_activity_handler(
    session: AsyncSession,
    payload: dict[str, Any],
) -> dict[str, Any]:
    resources = await _load_leakage_resources_for_tool(
        session,
        payload,
        tool_name="promotion.update_activity",
    )
    if isinstance(resources, dict) and resources.get("capability") == "production_write":
        return {
            "status": "production_authorized",
            "authorization_id": resources.get("authorization_id"),
        }
    return run_update_activity_chain(resources, payload)


async def delete_activity_handler(
    session: AsyncSession,
    payload: dict[str, Any],
) -> dict[str, Any]:
    resources = await _load_leakage_resources_for_tool(
        session,
        payload,
        tool_name="promotion.delete_activity",
    )
    if isinstance(resources, dict) and resources.get("capability") == "production_write":
        return {
            "status": "production_authorized",
            "authorization_id": resources.get("authorization_id"),
        }
    return run_delete_activity_chain(resources, payload)


register_async_tool("inventory.replenish", replenish_inventory_handler)
register_async_tool("inventory.clear_excess", clear_excess_inventory_handler)
register_async_tool("promotion.create_activity", create_activity_handler)
register_async_tool("promotion.update_activity", update_activity_handler)
register_async_tool("promotion.delete_activity", delete_activity_handler)
