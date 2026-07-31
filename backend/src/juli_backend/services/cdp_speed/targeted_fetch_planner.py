"""Targeted Fetch Planner — material webhook catalog id → bounded Partner resources (#626)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from juli_backend.integrations.tiktok import (
    ANALYTICS_SHOP_PERFORMANCE_PATH,
    ANALYTICS_SHOP_PRODUCTS_PERFORMANCE_PATH,
    INVENTORY_SEARCH_PATH,
    ORDER_SEARCH_PATH,
    PRODUCT_SEARCH_PATH,
    RETURN_SEARCH_PATH,
    promotion_activity_path,
)
from juli_backend.services.tiktok.webhook_catalog import (
    catalog_id_for_event,
    is_material_catalog_id,
)

FUJIWA_POLL_RESOURCE_NAMES: frozenset[str] = frozenset(
    {"orders", "products", "returns", "inventory"}
)

# Resources invoked by ``sync_analytics`` A-31–A-39 fan-out — forbidden on material path.
FULL_SYNC_ANALYTICS_RESOURCE_NAMES: frozenset[str] = frozenset(
    {
        "analytics_skus",
        "analytics_sku_details",
        "analytics_products",
        "analytics_product_details",
        "analytics_live",
        "analytics_live_overview",
        "analytics_bestselling_products",
        "analytics_bestselling_videos",
        "analytics_shop_per_hour",
        "promotion_activity_list",
    }
)


@dataclass(frozen=True, slots=True)
class FetchResource:
    """Named Partner resource entry in a targeted fetch plan."""

    name: str
    endpoint_path: str
    resource_attr: str


@dataclass(frozen=True, slots=True)
class TargetedFetchPlan:
    """Bounded fetch plan for a single material trigger."""

    catalog_id: int | None
    shop_id: str
    resources: tuple[FetchResource, ...]

    @property
    def is_empty(self) -> bool:
        return not self.resources


_STATIC_RESOURCES: dict[str, FetchResource] = {
    "orders": FetchResource("orders", ORDER_SEARCH_PATH, "orders"),
    "products": FetchResource("products", PRODUCT_SEARCH_PATH, "products"),
    "returns": FetchResource("returns", RETURN_SEARCH_PATH, "returns"),
    "inventory": FetchResource("inventory", INVENTORY_SEARCH_PATH, "inventory"),
    "analytics_shop": FetchResource(
        "analytics_shop",
        ANALYTICS_SHOP_PERFORMANCE_PATH,
        "analytics",
    ),
    "analytics_products_list": FetchResource(
        "analytics_products_list",
        ANALYTICS_SHOP_PRODUCTS_PERFORMANCE_PATH,
        "analytics",
    ),
}

# Material catalog id → named resource keys (see MODULE.md for rationale).
_MATERIAL_FETCH_MATRIX: dict[int, tuple[str, ...]] = {
    1: ("orders", "analytics_shop"),
    2: ("returns", "orders", "analytics_shop"),
    5: ("products", "analytics_shop", "analytics_products_list"),
    12: ("returns", "analytics_shop"),
    27: ("inventory", "products", "analytics_shop"),
    39: ("promotion_activity", "analytics_shop"),
    67: ("returns", "orders", "analytics_shop"),
    68: ("inventory", "analytics_shop"),
}


def _resolve_promotion_activity(payload_hints: Mapping[str, Any] | None) -> FetchResource:
    activity_id = None
    if payload_hints:
        activity_id = payload_hints.get("activity_id") or payload_hints.get("promotion_activity_id")
    endpoint = (
        promotion_activity_path(str(activity_id))
        if activity_id
        else "/promotion/202309/activities/{activity_id}"
    )
    return FetchResource("promotion_activity", endpoint, "promotion")


def _resolve_resource(name: str, payload_hints: Mapping[str, Any] | None) -> FetchResource:
    if name == "promotion_activity":
        return _resolve_promotion_activity(payload_hints)
    try:
        return _STATIC_RESOURCES[name]
    except KeyError as exc:
        raise KeyError(f"unknown fetch resource: {name}") from exc


def _resolve_catalog_id(
    *,
    catalog_id: int | None,
    event_type: str | None,
) -> int | None:
    if catalog_id is not None:
        return catalog_id
    if event_type is None:
        return None
    return catalog_id_for_event(event_type)


def plan_targeted_fetch(
    *,
    shop_id: str,
    catalog_id: int | None = None,
    event_type: str | None = None,
    payload_hints: Mapping[str, Any] | None = None,
) -> TargetedFetchPlan:
    """Return a bounded Partner fetch plan for a material trigger, or empty when non-material."""
    resolved_id = _resolve_catalog_id(catalog_id=catalog_id, event_type=event_type)
    if resolved_id is None or not is_material_catalog_id(resolved_id):
        return TargetedFetchPlan(catalog_id=resolved_id, shop_id=shop_id, resources=())

    resource_keys = _MATERIAL_FETCH_MATRIX.get(resolved_id)
    if not resource_keys:
        return TargetedFetchPlan(catalog_id=resolved_id, shop_id=shop_id, resources=())

    resources = tuple(_resolve_resource(name, payload_hints) for name in resource_keys)
    return TargetedFetchPlan(catalog_id=resolved_id, shop_id=shop_id, resources=resources)
