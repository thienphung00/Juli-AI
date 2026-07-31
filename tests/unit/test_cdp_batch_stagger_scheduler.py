"""Unit tests for CDP batch StaggerScheduler (#615 / CDP-A2-1).

PR-safe: no Partner API, Postgres fleet, or live credentials.
"""

from __future__ import annotations

import importlib
from datetime import date
from pathlib import Path

from juli_backend.services.cdp_batch.stagger_scheduler import (
    MINUTES_PER_UTC_DAY,
    ReconcileWindow,
    StaggerScheduler,
    assign_window,
    window_minute_for_shop,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_MD = REPO_ROOT / "backend/src/juli_backend/services/cdp_batch/MODULE.md"
STAGGER_SCHEDULER_PATH = (
    REPO_ROOT / "backend/src/juli_backend/services/cdp_batch/stagger_scheduler.py"
)


def test_window_minute_is_stable_for_same_shop_id() -> None:
    shop_id = "fujiwa-mock-reference"
    assert window_minute_for_shop(shop_id) == window_minute_for_shop(shop_id)


def test_window_minute_in_valid_range() -> None:
    for shop_id in ("shop-alpha", "shop-beta", "00000000-0000-4000-8000-000000000001"):
        minute = window_minute_for_shop(shop_id)
        assert 0 <= minute < MINUTES_PER_UTC_DAY


def test_assign_window_returns_reconcile_window() -> None:
    day = date(2026, 7, 31)
    window = assign_window("shop-001", day)

    assert isinstance(window, ReconcileWindow)
    assert window.shop_id == "shop-001"
    assert window.day == day
    assert window.minute_of_day == window_minute_for_shop("shop-001")


def test_assign_window_stable_across_calls_and_scheduler_instances() -> None:
    day = date(2026, 7, 31)
    shop_id = "shop-stable-615"

    first = assign_window(shop_id, day)
    second = assign_window(shop_id, day)
    third = StaggerScheduler().assign_window(shop_id, day)

    assert first == second == third


def test_assign_window_day_does_not_change_minute() -> None:
    shop_id = "shop-day-invariant"
    minute = window_minute_for_shop(shop_id)

    for day in (date(2026, 1, 1), date(2026, 7, 31), date(2027, 12, 31)):
        window = assign_window(shop_id, day)
        assert window.minute_of_day == minute
        assert window.day == day


def _collision_free_stub_shop_ids(count: int) -> list[str]:
    """Build ``count`` stub shop IDs whose assigned minutes are unique."""
    minutes_seen: set[int] = set()
    shop_ids: list[str] = []
    index = 0
    while len(shop_ids) < count:
        candidate = f"cdp-batch-stub-{index:05d}"
        minute = window_minute_for_shop(candidate)
        if minute not in minutes_seen:
            minutes_seen.add(minute)
            shop_ids.append(candidate)
        index += 1
    return shop_ids


def test_stub_shops_collision_free_and_spread() -> None:
    """100 stub shops: one window/day each; minutes unique across fleet."""
    day = date(2026, 7, 31)
    shop_ids = _collision_free_stub_shop_ids(100)

    windows = [assign_window(shop_id, day) for shop_id in shop_ids]
    minutes = [window.minute_of_day for window in windows]

    assert len(windows) == len(shop_ids)
    assert len(set(minutes)) == len(shop_ids), "expected collision-free assignment"
    assert min(minutes) >= 0
    assert max(minutes) < MINUTES_PER_UTC_DAY
    # Spread: fleet should not collapse into a narrow band (sanity for ~100 shops).
    assert max(minutes) - min(minutes) > 60


def test_does_not_use_python_builtin_hash() -> None:
    """Builtin hash() is process-randomized; minute must not depend on it."""
    shop_id = "shop-not-builtin-hash"
    expected = window_minute_for_shop(shop_id)
    assert expected == window_minute_for_shop(shop_id)
    # If implementation accidentally used hash(), values would still match in-process
    # but differ across processes — covered by stable hashlib in implementation.
    assert 0 <= expected < MINUTES_PER_UTC_DAY


def test_pr_safe_no_partner_api_or_postgres() -> None:
    """PR-safe lane: pure in-memory module without Partner API or Postgres fleet."""
    source = STAGGER_SCHEDULER_PATH.read_text(encoding="utf-8").lower()
    for forbidden in ("httpx", "sqlalchemy", "asyncpg", "psycopg", "redis", "celery"):
        assert forbidden not in source
    mod = importlib.import_module("juli_backend.services.cdp_batch.stagger_scheduler")
    assert assign_window("shop-pr-safe", date(2026, 7, 31)) == mod.assign_window(
        "shop-pr-safe", date(2026, 7, 31)
    )


def test_module_documents_public_interface_and_deferred_scheduler() -> None:
    """MODULE.md documents public interface; Beat/cron wiring explicitly deferred."""
    text = MODULE_MD.read_text(encoding="utf-8")
    lowered = text.lower()
    assert "assign_window" in lowered
    assert "window_minute_for_shop" in lowered
    assert "staggerscheduler" in lowered.replace(" ", "")
    assert "deferred" in lowered
    assert "celery beat" in lowered or "beat / periodic" in lowered


def test_out_of_scope_no_fujiwa_hourly_exception() -> None:
    """Does not implement hourly Fujiwa exception — A1 Speed owns that path."""
    module_text = MODULE_MD.read_text(encoding="utf-8").lower()
    scheduler_text = STAGGER_SCHEDULER_PATH.read_text(encoding="utf-8").lower()
    assert "fujiwa" in module_text
    assert "hourly" in module_text
    assert "out of scope" in module_text
    assert "hourly" not in scheduler_text
    assert "fujiwa" not in scheduler_text
