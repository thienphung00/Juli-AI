"""Issue #619 — BatchFetchPlanner contract tests (CDP-A2-7).

AC1 → gap/fixture input returns bounded resource list (endpoint + params)
AC2 → no gap → gap_not_detected; not full 3.5-C cold-start fleet scope
AC3 → unit tests only; no live Partner
AC4 → MODULE documents planner vs A1 targeted fetch boundary
AC5 → Fake Refresh / public Demo does not invoke planner (guard)
"""

from __future__ import annotations

import importlib
from datetime import date
from pathlib import Path

import pytest

from juli_backend.integrations.tiktok import (
    ANALYTICS_BESTSELLING_VIDEOS_PATH,
    ANALYTICS_SHOP_PERFORMANCE_PATH,
    INVENTORY_SEARCH_PATH,
    ORDER_SEARCH_PATH,
    PRODUCT_SEARCH_PATH,
    RETURN_SEARCH_PATH,
)
from juli_backend.integrations.tiktok.constants import FINANCE_STATEMENTS_PATH
from juli_backend.services.cdp_batch.batch_fetch_planner import (
    DEFER_REASON,
    DOMAIN_GAP_KINDS,
    FORBIDDEN_TRIGGER_SOURCES,
    MAX_BATCH_RESOURCES,
    P1_DEFERRED_GAP_KINDS,
    BatchFetchPlanner,
    BatchFetchPlannerForbiddenTriggerError,
    is_batch_fetch_trigger_allowed,
    plan_batch_fetch,
)
from juli_backend.services.cdp_batch.stagger_scheduler import assign_window
from juli_backend.services.cdp_speed.targeted_fetch_planner import (
    FUJIWA_POLL_RESOURCE_NAMES,
    FULL_SYNC_ANALYTICS_RESOURCE_NAMES,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_MD = REPO_ROOT / "backend/src/juli_backend/services/cdp_batch/MODULE.md"
PLANNER_PATH = REPO_ROOT / "backend/src/juli_backend/services/cdp_batch/batch_fetch_planner.py"
DEMO_ANALYTICS_PATH = REPO_ROOT / "backend/src/juli_backend/api/routes/demo_analytics.py"


def test_ac1_gap_fixture_returns_bounded_resource_list_with_endpoint_and_params() -> None:
    window = assign_window("shop-619", date(2026, 7, 31))
    plan = plan_batch_fetch(
        shop_id="shop-619",
        detected_gaps=frozenset({"orders", "finance_statements"}),
        reconcile_window=window,
    )

    assert plan.should_fetch
    assert plan.defer_reason is None
    assert plan.shop_id == "shop-619"
    assert plan.reconcile_window == window
    assert plan.resources
    assert len(plan.resources) <= MAX_BATCH_RESOURCES
    assert all(r.name and r.endpoint_path and r.resource_attr for r in plan.resources)

    orders = next(r for r in plan.resources if r.name == "orders")
    assert orders.endpoint_path == ORDER_SEARCH_PATH
    assert orders.params is not None

    finance = next(r for r in plan.resources if r.name == "finance_statements")
    assert finance.endpoint_path == FINANCE_STATEMENTS_PATH
    assert finance.params is not None
    assert "reconcile_day" in finance.params


def test_ac2_no_gap_defers_with_gap_not_detected() -> None:
    plan = plan_batch_fetch(shop_id="shop-619", detected_gaps=frozenset())

    assert not plan.should_fetch
    assert plan.defer_reason == DEFER_REASON
    assert plan.resources == ()


def test_ac2_no_gap_does_not_emit_cold_start_fleet_resources() -> None:
    plan = plan_batch_fetch(shop_id="shop-619", detected_gaps=frozenset())

    names = {r.name for r in plan.resources}
    assert names.isdisjoint(FUJIWA_POLL_RESOURCE_NAMES)
    assert names.isdisjoint(FULL_SYNC_ANALYTICS_RESOURCE_NAMES)


@pytest.mark.parametrize("gap_kind", sorted(DOMAIN_GAP_KINDS))
def test_domain_gap_includes_matching_resource_not_full_quadruple(
    gap_kind: str,
) -> None:
    plan = plan_batch_fetch(shop_id="shop-619", detected_gaps=frozenset({gap_kind}))

    assert plan.should_fetch
    assert any(r.name == gap_kind for r in plan.resources)
    poll_attrs = frozenset(r.resource_attr for r in plan.resources if r.name in DOMAIN_GAP_KINDS)
    assert poll_attrs != FUJIWA_POLL_RESOURCE_NAMES


def test_p1_deferred_gaps_sequence_finance_and_video_analytics() -> None:
    plan = plan_batch_fetch(
        shop_id="shop-619",
        detected_gaps=frozenset({"finance_statements", "analytics_videos"}),
    )

    assert plan.should_fetch
    names = [r.name for r in plan.resources]
    assert "finance_statements" in names
    assert "analytics_videos" in names
    assert names.index("finance_statements") < names.index("analytics_videos")

    video = next(r for r in plan.resources if r.name == "analytics_videos")
    assert video.endpoint_path == ANALYTICS_BESTSELLING_VIDEOS_PATH


def test_plan_excludes_unbounded_sync_analytics_fanout() -> None:
    all_gaps = DOMAIN_GAP_KINDS | P1_DEFERRED_GAP_KINDS
    plan = plan_batch_fetch(shop_id="shop-619", detected_gaps=frozenset(all_gaps))

    analytics_names = frozenset(r.name for r in plan.resources if r.resource_attr == "analytics")
    assert analytics_names.isdisjoint(FULL_SYNC_ANALYTICS_RESOURCE_NAMES)


def test_plan_with_all_domain_gaps_is_bounded_not_cold_start_fanout() -> None:
    plan = plan_batch_fetch(shop_id="shop-619", detected_gaps=DOMAIN_GAP_KINDS)

    assert plan.should_fetch
    assert len(plan.resources) <= MAX_BATCH_RESOURCES
    analytics_names = frozenset(r.name for r in plan.resources if r.resource_attr == "analytics")
    assert analytics_names == frozenset({"analytics_shop"})
    assert analytics_names.isdisjoint(FULL_SYNC_ANALYTICS_RESOURCE_NAMES)


def test_planner_consumes_stagger_scheduler_window_context() -> None:
    window = assign_window("shop-window-619", date(2026, 7, 31))
    planner = BatchFetchPlanner()
    plan = planner.plan(
        shop_id="shop-window-619",
        detected_gaps=frozenset({"products"}),
        reconcile_window=window,
    )

    assert plan.reconcile_window == window
    shop_perf = next((r for r in plan.resources if r.name == "analytics_shop"), None)
    assert shop_perf is not None
    assert shop_perf.endpoint_path == ANALYTICS_SHOP_PERFORMANCE_PATH
    assert shop_perf.params is not None
    assert shop_perf.params.get("reconcile_day") == "2026-07-31"


@pytest.mark.parametrize("trigger", sorted(FORBIDDEN_TRIGGER_SOURCES))
def test_ac5_fake_refresh_public_demo_guard_rejects_planner_invocation(trigger: str) -> None:
    assert not is_batch_fetch_trigger_allowed(trigger)
    with pytest.raises(BatchFetchPlannerForbiddenTriggerError):
        plan_batch_fetch(
            shop_id="shop-619",
            detected_gaps=frozenset({"orders"}),
            trigger_source=trigger,
        )


def test_ac5_demo_analytics_route_does_not_import_batch_fetch_planner() -> None:
    source = DEMO_ANALYTICS_PATH.read_text(encoding="utf-8").lower()
    assert "batch_fetch_planner" not in source
    assert "plan_batch_fetch" not in source
    assert "cdp_batch" not in source


def test_ac3_pr_safe_no_live_partner_http() -> None:
    source = PLANNER_PATH.read_text(encoding="utf-8").lower()
    for forbidden in (
        "httpx",
        "aiohttp",
        "requests",
        "sqlalchemy",
        "asyncpg",
        "redis",
        "celery",
    ):
        assert forbidden not in source
    mod = importlib.import_module("juli_backend.services.cdp_batch.batch_fetch_planner")
    plan = mod.plan_batch_fetch(shop_id="shop-pr", detected_gaps=frozenset({"orders"}))
    assert plan.should_fetch


def test_ac4_module_documents_planner_vs_a1_targeted_fetch_boundary() -> None:
    text = MODULE_MD.read_text(encoding="utf-8")
    lowered = text.lower()
    assert "batchfetchplanner" in lowered.replace(" ", "")
    assert "targeted fetch" in lowered or "targetedfetch" in lowered.replace(" ", "")
    assert "a1" in lowered
    assert "gap_not_detected" in lowered
    assert "fake refresh" in lowered or "demo" in lowered


def test_domain_gap_resource_paths_match_partner_constants() -> None:
    expected = {
        "orders": ORDER_SEARCH_PATH,
        "products": PRODUCT_SEARCH_PATH,
        "returns": RETURN_SEARCH_PATH,
        "inventory": INVENTORY_SEARCH_PATH,
    }
    for gap_kind, path in expected.items():
        plan = plan_batch_fetch(shop_id="shop-619", detected_gaps=frozenset({gap_kind}))
        resource = next(r for r in plan.resources if r.name == gap_kind)
        assert resource.endpoint_path == path


def test_planner_module_has_no_a1_speed_webhook_wiring() -> None:
    source = PLANNER_PATH.read_text(encoding="utf-8")
    forbidden_imports = (
        "from juli_backend.services.cdp_speed",
        "material_handoff",
        "material_dispatch",
        "webhook_catalog",
        "precompute_shop_analytics",
    )
    for token in forbidden_imports:
        assert token not in source
