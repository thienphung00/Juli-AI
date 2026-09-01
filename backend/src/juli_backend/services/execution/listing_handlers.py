"""Listing workflow Celery tool handlers — P2-B6 (#379)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.services.execution.listing import (
    run_create_hero_product_chain,
    run_optimize_product_chain,
)
from juli_backend.services.execution.production_write_resolver import (
    resolve_write_capability,
)
from juli_backend.services.execution.runner import register_async_tool


async def _load_listing_resources_for_tool(
    session: AsyncSession,
    payload: dict[str, Any],
    tool_name: str,
):
    """Load listing resources via the production write resolver.

    The resolver checks four preconditions:
    1. PRODUCTION_WRITE_ENABLED flag is on (default off)
    2. Matching authorization exists
    3. RLS boot check passed
    4. Red-team attestation for release SHA

    With the flag off (default), returns actual SandboxWriteResources. With all four met,
    returns a production capability marker dict. Otherwise raises PreconditionFailure with
    a distinct named reason.

    Args:
        session: AsyncSession for database queries
        payload: tool payload dict with _execution_shop_id and tool-specific fields
        tool_name: the tool name (e.g., "listing.create_hero_product")

    Returns:
        SandboxWriteResources (sandbox path), or dict marker (production path)

    Raises:
        PreconditionFailure: with distinct precondition name if any precondition unmet
    """
    shop_id_str = payload.get("_execution_shop_id")
    if not shop_id_str:
        raise ValueError("Payload missing _execution_shop_id; required for resolver")
    shop_id = uuid.UUID(shop_id_str)

    # Call the resolver to check all four preconditions and determine sandbox vs production
    return await resolve_write_capability(
        session,
        tool_name=tool_name,
        payload=payload,
        shop_id=shop_id,
    )


async def create_hero_product_handler(
    session: AsyncSession,
    payload: dict[str, Any],
) -> dict[str, Any]:
    # Call resolver to check all four production write preconditions
    # Returns SandboxWriteResources (flag off) or production marker dict (all four met)
    # Raises PreconditionFailure with distinct reason if any precondition fails
    resources = await _load_listing_resources_for_tool(
        session,
        payload,
        tool_name="listing.create_hero_product",
    )
    # For sandbox path, resources is SandboxWriteResources; use it directly
    # For production path, resources is a dict marker; in current code, skip execution
    # (actual production flow will be implemented when ProductionWriteClientFactory exists)
    if isinstance(resources, dict) and resources.get("capability") == "production_write":
        # Production path - for now just return authorization marker
        # The actual tool execution would happen here with production resources
        return {
            "status": "production_authorized",
            "authorization_id": resources.get("authorization_id"),
        }
    # Sandbox path - execute the normal workflow
    return run_create_hero_product_chain(resources, payload)


async def optimize_product_handler(
    session: AsyncSession,
    payload: dict[str, Any],
) -> dict[str, Any]:
    # Call resolver to check all four production write preconditions
    resources = await _load_listing_resources_for_tool(
        session,
        payload,
        tool_name="listing.optimize_product",
    )
    if isinstance(resources, dict) and resources.get("capability") == "production_write":
        # Production path - authorization marker returned
        return {
            "status": "production_authorized",
            "authorization_id": resources.get("authorization_id"),
        }
    # Sandbox path - execute the normal workflow
    return run_optimize_product_chain(resources, payload)


register_async_tool("listing.create_hero_product", create_hero_product_handler)
register_async_tool("listing.optimize_product", optimize_product_handler)
