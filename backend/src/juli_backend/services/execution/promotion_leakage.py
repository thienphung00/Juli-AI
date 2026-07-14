"""Promotion leakage workflow chains — P2-B7 (#380)."""

from __future__ import annotations

from typing import Any

from juli_backend.integrations.tiktok.factories import SandboxWriteResources


def run_create_activity_chain(
    resources: SandboxWriteResources,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Workflow 7a: Create Activity → Update Activity Product."""
    activity_body = payload.get("activity") or payload.get("activity_body")
    if not activity_body:
        raise ValueError("create_activity requires activity body")

    created = resources.promotion.create_activity(body=activity_body)
    activity_id = str(created.get("activity_id") or "")
    if not activity_id:
        raise ValueError("create_activity response missing activity_id")

    products = payload.get("products")
    if products:
        resources.promotion.update_activity_products(
            activity_id=activity_id,
            body={"products": products},
        )

    return {
        "tool_name": "promotion.create_activity",
        "activity_id": activity_id,
    }


def run_update_activity_chain(
    resources: SandboxWriteResources,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Workflow 7c: Update Activity metadata and/or attached products."""
    activity_id = str(payload["activity_id"])
    update_body = payload.get("activity") or payload.get("update_body")
    if update_body:
        resources.promotion.update_activity(activity_id=activity_id, body=update_body)

    products = payload.get("products")
    if products:
        resources.promotion.update_activity_products(
            activity_id=activity_id,
            body={"products": products},
        )

    return {
        "tool_name": "promotion.update_activity",
        "activity_id": activity_id,
    }


def run_delete_activity_chain(
    resources: SandboxWriteResources,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Workflow 7b: Get Activity (optional) → Deactivate Activity."""
    activity_id = str(payload["activity_id"])

    if payload.get("verify_exists", True):
        resources.promotion.get_activity(activity_id)

    result = resources.promotion.deactivate(activity_id=activity_id)
    return {
        "tool_name": "promotion.delete_activity",
        "activity_id": activity_id,
        "status": result.get("status"),
    }
