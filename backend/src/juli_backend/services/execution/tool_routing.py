"""Workflow key → Celery tool name routing — mirrors webhook_catalog lookup shape (#305)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ToolRouteEntry:
    workflow_key: str
    tool_name: str


WORKFLOW_TOOL_CATALOG: dict[str, ToolRouteEntry] = {
    "create_hero_product_1": ToolRouteEntry(
        "create_hero_product_1", "listing.create_hero_product"
    ),
    "optimize_product_2": ToolRouteEntry("optimize_product_2", "listing.optimize_product"),
    "replenish_inventory_3": ToolRouteEntry(
        "replenish_inventory_3", "inventory.replenish"
    ),
    "clear_excess_4": ToolRouteEntry("clear_excess_4", "inventory.clear_excess"),
    "process_order_5": ToolRouteEntry("process_order_5", "fulfillment.process_order"),
    "create_activity_7a": ToolRouteEntry(
        "create_activity_7a", "promotion.create_activity"
    ),
    "update_activity_7c": ToolRouteEntry(
        "update_activity_7c", "promotion.update_activity"
    ),
    "delete_activity_7b": ToolRouteEntry(
        "delete_activity_7b", "promotion.delete_activity"
    ),
    "prevent_cancellation_8a": ToolRouteEntry(
        "prevent_cancellation_8a", "returns.prevent_cancellation"
    ),
    "prevent_return_8b": ToolRouteEntry(
        "prevent_return_8b", "returns.prevent_return"
    ),
    "prevent_refund_8c": ToolRouteEntry(
        "prevent_refund_8c", "returns.prevent_refund"
    ),
}


def resolve_tool_name(workflow_key: str) -> str | None:
    """Resolve an approved Action Card workflow_key to a registered tool name."""
    entry = WORKFLOW_TOOL_CATALOG.get(workflow_key)
    return entry.tool_name if entry is not None else None


def resolve_tool_name_for_workflow(workflow_key: str) -> str:
    """Resolve workflow_key to tool_name or raise ValueError when unknown."""
    tool_name = resolve_tool_name(workflow_key)
    if tool_name is None:
        raise ValueError(f"Unknown workflow_key: {workflow_key}")
    return tool_name
