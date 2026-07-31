"""Gap-gated bounded Partner fetch plans for CDP batch reconcile (#619 / CDP-A2-7).

Broader than A1 ``plan_targeted_fetch`` (webhook-first targeted plans) but still
capped — no full Fujiwa poll stacks or unbounded ``sync_analytics`` fan-out.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from juli_backend.integrations.tiktok import (
    ANALYTICS_BESTSELLING_VIDEOS_PATH,
    ANALYTICS_SHOP_PERFORMANCE_PATH,
    FINANCE_STATEMENTS_PATH,
    INVENTORY_SEARCH_PATH,
    ORDER_SEARCH_PATH,
    PRODUCT_SEARCH_PATH,
    RETURN_SEARCH_PATH,
)
from juli_backend.services.cdp_batch.stagger_scheduler import ReconcileWindow

DEFER_REASON = "gap_not_detected"

FORBIDDEN_TRIGGER_SOURCES: frozenset[str] = frozenset(
    {
        "fake_refresh",
        "demo_public",
        "visitor_refresh",
        "public_demo",
    }
)

DOMAIN_GAP_KINDS: frozenset[str] = frozenset({"orders", "products", "returns", "inventory"})
P1_DEFERRED_GAP_KINDS: frozenset[str] = frozenset({"finance_statements", "analytics_videos"})

MAX_BATCH_RESOURCES = 8

# Stable sequencing: domain gaps → shop analytics → speed-deferred P1 batch fetches.
_RESOURCE_SEQUENCE: tuple[str, ...] = (
    "orders",
    "products",
    "returns",
    "inventory",
    "analytics_shop",
    "finance_statements",
    "analytics_videos",
)


class BatchFetchPlannerForbiddenTriggerError(ValueError):
    """Raised when public Demo / Fake Refresh attempts to invoke batch fetch planning."""


@dataclass(frozen=True, slots=True)
class BatchFetchResource:
    """Named Partner resource entry in a batch reconcile fetch plan."""

    name: str
    endpoint_path: str
    resource_attr: str
    params: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class BatchFetchPlan:
    """Bounded fetch plan for one batch reconcile window."""

    shop_id: str
    resources: tuple[BatchFetchResource, ...]
    defer_reason: str | None = None
    reconcile_window: ReconcileWindow | None = None

    @property
    def should_fetch(self) -> bool:
        return self.defer_reason is None and bool(self.resources)


def is_batch_fetch_trigger_allowed(trigger_source: str | None) -> bool:
    """Return False for Fake Refresh / public Demo trigger sources (PRD US #25)."""
    if trigger_source is None:
        return True
    return trigger_source.strip().lower() not in FORBIDDEN_TRIGGER_SOURCES


def _normalize_gaps(detected_gaps: frozenset[str] | set[str] | tuple[str, ...]) -> frozenset[str]:
    return frozenset(gap.strip().lower() for gap in detected_gaps if gap.strip())


def _reconcile_day_params(reconcile_window: ReconcileWindow | None) -> dict[str, str]:
    if reconcile_window is None:
        return {}
    return {"reconcile_day": reconcile_window.day.isoformat()}


def _build_resource(
    name: str,
    *,
    reconcile_window: ReconcileWindow | None,
) -> BatchFetchResource:
    day_params = _reconcile_day_params(reconcile_window)
    match name:
        case "orders":
            return BatchFetchResource(
                "orders",
                ORDER_SEARCH_PATH,
                "orders",
                {"page_size": "50", **day_params},
            )
        case "products":
            return BatchFetchResource(
                "products",
                PRODUCT_SEARCH_PATH,
                "products",
                {"page_size": "50", **day_params},
            )
        case "returns":
            return BatchFetchResource(
                "returns",
                RETURN_SEARCH_PATH,
                "returns",
                {"page_size": "50", **day_params},
            )
        case "inventory":
            return BatchFetchResource(
                "inventory",
                INVENTORY_SEARCH_PATH,
                "inventory",
                {"page_size": "50", **day_params},
            )
        case "analytics_shop":
            return BatchFetchResource(
                "analytics_shop",
                ANALYTICS_SHOP_PERFORMANCE_PATH,
                "analytics",
                {"granularity": "1D", **day_params},
            )
        case "finance_statements":
            return BatchFetchResource(
                "finance_statements",
                FINANCE_STATEMENTS_PATH,
                "settlements",
                {"sort_field": "statement_time", **day_params},
            )
        case "analytics_videos":
            return BatchFetchResource(
                "analytics_videos",
                ANALYTICS_BESTSELLING_VIDEOS_PATH,
                "analytics",
                {"page_size": "20", **day_params},
            )
        case _:
            raise KeyError(f"unknown batch fetch resource: {name}")


def _resource_keys_for_gaps(gaps: frozenset[str]) -> tuple[str, ...]:
    if not gaps:
        return ()

    keys: list[str] = []
    for gap in DOMAIN_GAP_KINDS:
        if gap in gaps:
            keys.append(gap)

    needs_shop_analytics = bool(keys) or bool(gaps & P1_DEFERRED_GAP_KINDS)
    if needs_shop_analytics and "analytics_shop" not in keys:
        keys.append("analytics_shop")

    for gap in P1_DEFERRED_GAP_KINDS:
        if gap in gaps:
            keys.append(gap)

    ordered = [name for name in _RESOURCE_SEQUENCE if name in keys]
    return tuple(ordered[:MAX_BATCH_RESOURCES])


def plan_batch_fetch(
    *,
    shop_id: str,
    detected_gaps: frozenset[str] | set[str] | tuple[str, ...] = (),
    reconcile_window: ReconcileWindow | None = None,
    trigger_source: str | None = "batch_reconcile",
) -> BatchFetchPlan:
    """Return a bounded batch reconcile fetch plan, or defer when no gap is detected."""
    if not is_batch_fetch_trigger_allowed(trigger_source):
        raise BatchFetchPlannerForbiddenTriggerError(trigger_source)

    gaps = _normalize_gaps(detected_gaps)
    if not gaps:
        return BatchFetchPlan(
            shop_id=shop_id,
            resources=(),
            defer_reason=DEFER_REASON,
            reconcile_window=reconcile_window,
        )

    resource_keys = _resource_keys_for_gaps(gaps)
    resources = tuple(
        _build_resource(name, reconcile_window=reconcile_window) for name in resource_keys
    )
    return BatchFetchPlan(
        shop_id=shop_id,
        resources=resources,
        reconcile_window=reconcile_window,
    )


class BatchFetchPlanner:
    """Gap-gated batch fetch planner for orchestrator injection."""

    def plan(
        self,
        *,
        shop_id: str,
        detected_gaps: frozenset[str] | set[str] | tuple[str, ...] = (),
        reconcile_window: ReconcileWindow | None = None,
        trigger_source: str | None = "batch_reconcile",
    ) -> BatchFetchPlan:
        return plan_batch_fetch(
            shop_id=shop_id,
            detected_gaps=detected_gaps,
            reconcile_window=reconcile_window,
            trigger_source=trigger_source,
        )
