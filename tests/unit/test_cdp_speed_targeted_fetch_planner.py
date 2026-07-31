"""Issue #626 — Targeted Fetch Planner contract tests (CDP-A1-2).

AC1 → each material catalog id returns a non-empty bounded plan with named resources
AC2 → material-path plan ≠ full Fujiwa poll step list
AC3 → non-material events return empty plan
AC4 → documented in MODULE.md (manual review)
AC5 → no A2 Postgres I/O governors wired through planner
"""

from __future__ import annotations

import pytest

from juli_backend.services.cdp_speed.targeted_fetch_planner import (
    FUJIWA_POLL_RESOURCE_NAMES,
    FULL_SYNC_ANALYTICS_RESOURCE_NAMES,
    plan_targeted_fetch,
)
from juli_backend.services.tiktok.webhook_catalog import (
    MATERIAL_CATALOG_IDS,
    catalog_id_for_event,
    is_material_catalog_id,
)
from juli_backend.workers.services.polling.orchestrate import _FUJIWA_POLL_STEPS

MATERIAL_EVENT_BY_CATALOG_ID: dict[int, str] = {
    1: "ORDER_STATUS_CHANGE",
    2: "REVERSE_STATUS_UPDATE",
    5: "PRODUCT_STATUS_CHANGE",
    12: "RETURN_STATUS_CHANGE",
    27: "INVENTORY_STATUS_CHANGE",
    39: "ACTIVITY_STATUS_CHANGE",
    67: "REFUND_SUCCESS",
    68: "INVENTORY_CHANGED",
}

NON_MATERIAL_EVENTS = (
    "RECIPIENT_ADDRESS_UPDATE",  # 3
    "PACKAGE_UPDATE",  # 4
    "CANCELLATION_STATUS_CHANGE",  # 11
    "FBT_INVENTORY_UPDATE",  # 24
    "PRODUCT_AUDIT_STATUS_CHANGE",  # 37
)


@pytest.mark.parametrize("catalog_id", sorted(MATERIAL_CATALOG_IDS))
def test_material_catalog_id_returns_non_empty_bounded_plan(catalog_id: int) -> None:
    plan = plan_targeted_fetch(
        catalog_id=catalog_id,
        shop_id="shop_626",
        payload_hints={"activity_id": "act-626"} if catalog_id == 39 else None,
    )
    assert not plan.is_empty
    assert plan.catalog_id == catalog_id
    assert plan.shop_id == "shop_626"
    assert plan.resources
    assert all(step.name and step.endpoint_path and step.resource_attr for step in plan.resources)
    assert len(plan.resources) <= 4, "material plans must stay bounded (≤4 resources)"


@pytest.mark.parametrize("catalog_id", sorted(MATERIAL_CATALOG_IDS))
def test_material_plan_by_event_type(catalog_id: int) -> None:
    event_type = MATERIAL_EVENT_BY_CATALOG_ID[catalog_id]
    plan = plan_targeted_fetch(
        event_type=event_type,
        shop_id="shop_626",
        payload_hints={"activity_id": "act-626"} if catalog_id == 39 else None,
    )
    assert plan.catalog_id == catalog_id
    assert not plan.is_empty


def test_fujiwa_poll_resource_names_match_orchestrate_steps() -> None:
    expected = frozenset(step.resource_attr for step in _FUJIWA_POLL_STEPS)
    assert FUJIWA_POLL_RESOURCE_NAMES == expected


@pytest.mark.parametrize("catalog_id", sorted(MATERIAL_CATALOG_IDS))
def test_material_plan_is_not_full_fujiwa_poll_stack(catalog_id: int) -> None:
    plan = plan_targeted_fetch(
        catalog_id=catalog_id,
        shop_id="shop_626",
        payload_hints={"activity_id": "act-626"} if catalog_id == 39 else None,
    )
    plan_names = frozenset(
        step.resource_attr for step in plan.resources if step.name in FUJIWA_POLL_RESOURCE_NAMES
    )
    assert plan_names != FUJIWA_POLL_RESOURCE_NAMES
    poll_step_paths = frozenset(step.endpoint_path for step in _FUJIWA_POLL_STEPS)
    plan_poll_paths = frozenset(
        step.endpoint_path
        for step in plan.resources
        if step.resource_attr in FUJIWA_POLL_RESOURCE_NAMES
    )
    assert plan_poll_paths != poll_step_paths


@pytest.mark.parametrize("catalog_id", sorted(MATERIAL_CATALOG_IDS))
def test_material_plan_excludes_unbounded_sync_analytics_fanout(
    catalog_id: int,
) -> None:
    plan = plan_targeted_fetch(
        catalog_id=catalog_id,
        shop_id="shop_626",
        payload_hints={"activity_id": "act-626"} if catalog_id == 39 else None,
    )
    analytics_names = frozenset(
        step.name for step in plan.resources if step.resource_attr == "analytics"
    )
    assert analytics_names.isdisjoint(FULL_SYNC_ANALYTICS_RESOURCE_NAMES)


@pytest.mark.parametrize("event_type", NON_MATERIAL_EVENTS)
def test_non_material_event_returns_empty_plan(event_type: str) -> None:
    catalog_id = catalog_id_for_event(event_type)
    assert catalog_id is not None
    assert not is_material_catalog_id(catalog_id)

    plan = plan_targeted_fetch(event_type=event_type, shop_id="shop_626")
    assert plan.is_empty
    assert plan.resources == ()
    assert plan.catalog_id == catalog_id


def test_unknown_event_returns_empty_plan() -> None:
    plan = plan_targeted_fetch(event_type="AFFILIATE_CREATOR_UPDATE", shop_id="shop_626")
    assert plan.is_empty
    assert plan.catalog_id is None


def test_non_material_catalog_id_returns_empty_plan() -> None:
    plan = plan_targeted_fetch(catalog_id=24, shop_id="shop_626")
    assert plan.is_empty


def test_planner_module_has_no_a2_governors() -> None:
    import juli_backend.services.cdp_speed.targeted_fetch_planner as module

    source = open(module.__file__, encoding="utf-8").read()
    forbidden = (
        "PostgresIoBudget",
        "FleetDefer",
        "postgres_io_budget",
        "fleet_defer",
        "cdp_batch",
    )
    for token in forbidden:
        assert token not in source
