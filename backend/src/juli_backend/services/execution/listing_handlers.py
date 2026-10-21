"""Listing workflow Celery tool handlers — P2-B6 (#379); production leg P61-B (D71.2).

Every call goes through `resolve_write_capability` (ADR-085). Its answer is one of:

- sandbox write resources -- the global flag is off, or this shop has no
  `production_write_shops` row. The chain runs on the sandbox merchant and the
  outcome says `write_mode: "simulated"`: nothing changed on the seller's shop.
- the production marker -- the flag is on, the shop is enabled, a matching
  authorization existed and was consumed, the RLS boot check passed, the
  release is attested and the kill switch is off.
  `production_write.load_production_write_resources` (the loader
  `composition.build_write_resources` delegates to) turns it into the shop's
  OWN guarded write resources, the chain runs there,
  its before/after listing values are recorded in `run_write_values`, and the
  outcome says `write_mode: "live"`.
- a `PreconditionFailure` naming the gate that refused (audited by the resolver).

Two refusals happen BEFORE the resolver, so no authorization is consumed for a
write that could never be performed, and only when the shop's writes would go to
its own shop: a price update and a product create (D13 -- v1 executes the listing
edit only; price is a recommendation, and Juli never reverts a price), and an
execution with no workflow run (the audit row and `run_write_values` both name
the run). The mutation kind the authorization is matched on is the tool's own
name, never a value from the payload.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.core.config import require_env
from juli_backend.models.models import WRITE_MODE_LIVE, WRITE_MODE_SIMULATED
from juli_backend.services.execution.listing import (
    run_create_hero_product_chain,
    run_optimize_product_chain,
)
from juli_backend.services.execution.production_write import (
    is_production_capability,
    load_production_write_resources,
    production_write_possible,
    record_listing_write_values,
)
from juli_backend.services.execution.production_write_resolver import (
    PreconditionFailure,
    PreconditionName,
    resolve_write_capability,
)
from juli_backend.services.execution.runner import register_async_tool

CREATE_HERO_PRODUCT_TOOL = "listing.create_hero_product"
OPTIMIZE_PRODUCT_TOOL = "listing.optimize_product"


def _uuid_field(payload: dict[str, Any], key: str) -> uuid.UUID | None:
    value = payload.get(key)
    return uuid.UUID(str(value)) if value else None


def _execution_shop_id(payload: dict[str, Any]) -> uuid.UUID:
    shop_id = _uuid_field(payload, "_execution_shop_id")
    if shop_id is None:
        raise ValueError("Payload missing _execution_shop_id; required for resolver")
    return shop_id


async def _load_listing_resources_for_tool(
    session: AsyncSession,
    payload: dict[str, Any],
    tool_name: str,
):
    """Resolve this call's write target through the ADR-085 resolver (see module docstring).

    Returns sandbox write resources or the production marker; raises
    `PreconditionFailure` with a distinct named reason when a gate refuses.
    """
    shop_id = _execution_shop_id(payload)
    run_id = _uuid_field(payload, "_execution_workflow_run_id")
    resolver_payload = {
        **payload,
        "tiktok_product_id": payload.get("tiktok_product_id") or payload.get("product_id"),
        # Server-held: the authorization is for THIS tool, whatever the payload says.
        "mutation_kind": tool_name,
    }
    return await resolve_write_capability(
        session,
        tool_name=tool_name,
        payload=resolver_payload,
        shop_id=shop_id,
        run_id=run_id,
    )


async def _refuse_before_production(
    session: AsyncSession, payload: dict[str, Any], *, refused_mutation: str | None
) -> None:
    """The pre-resolver refusals (module docstring), only when the write would go live."""
    shop_id = _execution_shop_id(payload)
    if not await production_write_possible(session, shop_id):
        return
    if refused_mutation is not None:
        raise PreconditionFailure(
            PreconditionName.MUTATION_NOT_ALLOWED_IN_PRODUCTION,
            f"{refused_mutation} is never executed on a seller's shop (D13)",
        )
    if _uuid_field(payload, "_execution_workflow_run_id") is None:
        raise PreconditionFailure(
            PreconditionName.NO_WORKFLOW_RUN,
            "A production write must belong to a workflow run (audit + write values)",
        )


async def create_hero_product_handler(
    session: AsyncSession,
    payload: dict[str, Any],
) -> dict[str, Any]:
    # D13: a product create is never a production mutation in v1.
    await _refuse_before_production(session, payload, refused_mutation="Product create")
    resources = await _load_listing_resources_for_tool(
        session,
        payload,
        tool_name=CREATE_HERO_PRODUCT_TOOL,
    )
    if is_production_capability(resources):
        # Unreachable: `_refuse_before_production` refused whenever the shop's
        # writes would go live. Kept fail-closed rather than executing.
        raise PreconditionFailure(
            PreconditionName.MUTATION_NOT_ALLOWED_IN_PRODUCTION,
            "Product create is never executed on a seller's shop (D13)",
        )
    return {**run_create_hero_product_chain(resources, payload), "write_mode": WRITE_MODE_SIMULATED}


async def optimize_product_handler(
    session: AsyncSession,
    payload: dict[str, Any],
) -> dict[str, Any]:
    await _refuse_before_production(
        session,
        payload,
        refused_mutation="A price update" if payload.get("price_update") else None,
    )
    resources = await _load_listing_resources_for_tool(
        session,
        payload,
        tool_name=OPTIMIZE_PRODUCT_TOOL,
    )
    if not is_production_capability(resources):
        # Sandbox merchant: the seller's shop is unchanged, and the outcome says so.
        result = run_optimize_product_chain(resources, payload)
        return {**result, "write_mode": WRITE_MODE_SIMULATED}
    return await _run_optimize_product_live(session, payload, capability=resources)


async def _run_optimize_product_live(
    session: AsyncSession, payload: dict[str, Any], *, capability: dict[str, Any]
) -> dict[str, Any]:
    """Every gate passed: the listing chain on the shop's own resources, values recorded."""
    shop_id = _execution_shop_id(payload)
    run_id = _uuid_field(payload, "_execution_workflow_run_id")
    if run_id is None:  # `_refuse_before_production` already refused; kept fail-closed
        raise PreconditionFailure(
            PreconditionName.NO_WORKFLOW_RUN,
            "A production write must belong to a workflow run (audit + write values)",
        )
    # The same loader `composition.build_write_resources` uses for a production
    # capability; called directly because `services/execution` must not import
    # `services/agent` (that edge would close a dependency cycle).
    resources = await load_production_write_resources(
        session,
        shop_id=shop_id,
        capability=capability,
        app_key=require_env("TIKTOK_APP_KEY"),
        app_secret=require_env("TIKTOK_APP_SECRET"),
    )
    result = run_optimize_product_chain(resources, payload)
    product_id = str(result["product_id"])
    if result.get("edit") is not None:
        after = resources.products.get_details(product_id)
        await record_listing_write_values(
            session,
            shop_id=shop_id,
            workflow_run_id=run_id,
            tool_call_id=str(payload.get("_execution_id") or capability["authorization_id"]),
            tiktok_product_id=product_id,
            before=result.get("current_product") or {},
            after=after,
            intended=result.get("edit_body") or {},
        )
    return {
        **result,
        "write_mode": WRITE_MODE_LIVE,
        "authorization_id": capability["authorization_id"],
    }


register_async_tool(CREATE_HERO_PRODUCT_TOOL, create_hero_product_handler)
register_async_tool(OPTIMIZE_PRODUCT_TOOL, optimize_product_handler)
