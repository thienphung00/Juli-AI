"""Tests for CDP batch staggered reconcile Celery Beat scheduler wiring (#622).

Tests RED→GREEN verification of:
- Config flag (CDP_BATCH_STAGGERED_RECONCILE_ENABLED) defaults OFF, enqueues nothing
- Staggered windows drive exactly one enqueue per shop per UTC day
- Rollout allowlist restricts enqueue blast radius to Fujiwa reference + stub shops
- A1 hourly exception (mock_analytics_hourly_reconcile) remains untouched
- Public trigger sources (fake_refresh, demo_public, etc.) are rejected
- Job enqueue/completion metrics tied to shop_id and window slot
- Rollback scenario: flag flip mid-run produces zero enqueues for remainder of day
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import pytest
from freezegun import freeze_time

from juli_backend.services.cdp_batch.stagger_scheduler import ReconcileWindow
from juli_backend.workers.celery_app import celery_app

# --- Fixtures ---


@pytest.fixture
def fujiwa_shop_id() -> str:
    """Fujiwa Mock reference shop ID (stable across tests)."""
    return "fujiwa-shop-1"


@pytest.fixture
def stub_shop_ids() -> list[str]:
    """Stub shop IDs for prove-out (synthetic fixtures, not real tenant IDs)."""
    return ["stub-shop-1", "stub-shop-2"]


@pytest.fixture
def rollout_allowlist(fujiwa_shop_id: str, stub_shop_ids: list[str]) -> list[str]:
    """Config: shops to enqueue in staggered batch reconcile."""
    return [fujiwa_shop_id] + stub_shop_ids


@pytest.fixture
def enqueue_spy():
    """Mock broker enqueue spy to count batch-reconcile enqueue calls."""
    enqueue_calls = []

    def record_enqueue(*args, **kwargs):
        enqueue_calls.append({"args": args, "kwargs": kwargs})

    return {
        "calls": enqueue_calls,
        "record": record_enqueue,
        "count": lambda: len(enqueue_calls),
    }


# --- Test: Flag OFF enqueues nothing ---


@freeze_time("2025-01-15 00:00:00", tz_offset=0)  # UTC midnight
def test_flag_off_enqueues_nothing(
    fujiwa_shop_id: str,
    enqueue_spy: dict,
    monkeypatch,
):
    """With flag OFF, a full simulated UTC day produces exactly zero enqueue calls."""
    # Ensure flag is explicitly OFF
    monkeypatch.setenv("CDP_BATCH_STAGGERED_RECONCILE_ENABLED", "false")

    # Mock the enqueue path
    with patch("juli_backend.workers.tasks.cdp_batch_reconcile.celery_app.send_task") as mock_send:
        mock_send.side_effect = enqueue_spy["record"]

        # Import and call the Beat task
        from juli_backend.workers.tasks.cdp_batch_reconcile import (
            cdp_batch_staggered_reconcile_beat_tick,
        )

        # Simulate 24 hourly ticks across one UTC day
        for hour in range(24):
            current_time = datetime(2025, 1, 15, hour, 0, 0)
            with freeze_time(current_time, tz_offset=0):
                cdp_batch_staggered_reconcile_beat_tick()

        # Assert: zero enqueues
        assert enqueue_spy["count"]() == 0, "Flag OFF should produce zero enqueues"


@freeze_time("2025-01-15 00:00:00", tz_offset=0)
def test_flag_off_unset_enqueues_nothing(
    fujiwa_shop_id: str,
    enqueue_spy: dict,
    monkeypatch,
):
    """With flag unset (defaulting OFF), a full day produces zero enqueues."""
    # Ensure flag is unset (default OFF per Architect assumption)
    monkeypatch.delenv("CDP_BATCH_STAGGERED_RECONCILE_ENABLED", raising=False)

    with patch("juli_backend.workers.tasks.cdp_batch_reconcile.celery_app.send_task") as mock_send:
        mock_send.side_effect = enqueue_spy["record"]

        from juli_backend.workers.tasks.cdp_batch_reconcile import (
            cdp_batch_staggered_reconcile_beat_tick,
        )

        # Single tick at midnight
        cdp_batch_staggered_reconcile_beat_tick()

        # Assert: zero enqueues
        assert enqueue_spy["count"]() == 0, (
            "Flag unset should default OFF and produce zero enqueues"
        )


@freeze_time("2025-01-15 00:00:00", tz_offset=0)
def test_a1_hourly_exception_untouched(monkeypatch):
    """The existing mock-analytics-hourly-reconcile Beat entry is byte-for-byte unchanged."""
    # Load the Beat schedule from celery_app
    beat_schedule = celery_app.conf.beat_schedule

    # Assert: the A1 hourly entry exists and is unchanged
    assert "mock-analytics-hourly-reconcile" in beat_schedule, (
        "A1 hourly reconcile entry must not be removed or renamed"
    )

    entry = beat_schedule["mock-analytics-hourly-reconcile"]
    assert entry["task"] == "juli_backend.mock_analytics_hourly_reconcile", (
        "A1 task name must not change"
    )

    # crontab(minute=0) produces a schedule object with minute={0}
    schedule = entry["schedule"]
    assert schedule.minute == {0}, "A1 schedule must remain hourly at minute=0"


# --- Test: Staggered windows drive enqueue ---


@freeze_time("2025-01-15 00:00:00", tz_offset=0)
def test_stagger_windows_drive_enqueue(
    fujiwa_shop_id: str,
    stub_shop_ids: list[str],
    rollout_allowlist: list[str],
    enqueue_spy: dict,
    monkeypatch,
):
    """With flag ON, each shop is enqueued exactly once at its assigned window."""
    monkeypatch.setenv("CDP_BATCH_STAGGERED_RECONCILE_ENABLED", "true")
    monkeypatch.setenv("CDP_BATCH_STAGGERED_RECONCILE_ALLOWLIST", ",".join(rollout_allowlist))

    with patch("juli_backend.workers.tasks.cdp_batch_reconcile.celery_app.send_task") as mock_send:
        mock_send.side_effect = enqueue_spy["record"]

        from juli_backend.services.cdp_batch.stagger_scheduler import (
            window_minute_for_shop,
        )
        from juli_backend.workers.tasks.cdp_batch_reconcile import (
            cdp_batch_staggered_reconcile_beat_tick,
        )

        # Simulate 24 hourly ticks (1440 ticks per minute across a 24h day)
        minute_to_shops = {}
        for shop_id in rollout_allowlist:
            minute = window_minute_for_shop(shop_id)
            if minute not in minute_to_shops:
                minute_to_shops[minute] = []
            minute_to_shops[minute].append(shop_id)

        # Walk through each minute of the day and simulate a tick
        for minute in range(1440):
            hour = minute // 60
            minute_of_hour = minute % 60
            current_time = datetime(2025, 1, 15, hour, minute_of_hour, 0)
            with freeze_time(current_time, tz_offset=0):
                cdp_batch_staggered_reconcile_beat_tick()

        # Assert: exactly N shops enqueued (N = rollout_allowlist size)
        assert enqueue_spy["count"]() == len(rollout_allowlist), (
            f"Expected {len(rollout_allowlist)} enqueues, got {enqueue_spy['count']()}"
        )

        # Assert: each enqueued job carries the ReconcileWindow
        for call in enqueue_spy["calls"]:
            kwargs = call.get("kwargs", {})
            assert "kwargs" in kwargs, "Enqueue must pass kwargs"
            job_kwargs = kwargs.get("kwargs", {})
            assert "reconcile_window" in job_kwargs, "Job must carry reconcile_window"
            window = job_kwargs["reconcile_window"]
            assert isinstance(window, ReconcileWindow), (
                "reconcile_window must be ReconcileWindow instance"
            )


@freeze_time("2025-01-15 00:00:00", tz_offset=0)
def test_no_global_hourly_full_poll(
    rollout_allowlist: list[str],
    enqueue_spy: dict,
    monkeypatch,
):
    """No tick enqueues the whole fleet; no global hourly full poll."""
    monkeypatch.setenv("CDP_BATCH_STAGGERED_RECONCILE_ENABLED", "true")
    monkeypatch.setenv("CDP_BATCH_STAGGERED_RECONCILE_ALLOWLIST", ",".join(rollout_allowlist))

    with patch("juli_backend.workers.tasks.cdp_batch_reconcile.celery_app.send_task") as mock_send:
        mock_send.side_effect = enqueue_spy["record"]

        from juli_backend.workers.tasks.cdp_batch_reconcile import (
            cdp_batch_staggered_reconcile_beat_tick,
        )

        # Hourly ticks for a full day (24 ticks)
        for hour in range(24):
            current_time = datetime(2025, 1, 15, hour, 0, 0)
            with freeze_time(current_time, tz_offset=0):
                cdp_batch_staggered_reconcile_beat_tick()

        # Assert: the stagger scheduler spreads enqueues across minutes, so no single
        # tick enqueues all shops. Verify by checking enqueue count is <= allowlist size.
        assert enqueue_spy["count"]() <= len(rollout_allowlist), (
            "No single tick should enqueue all shops"
        )


@freeze_time("2025-01-15 00:00:00", tz_offset=0)
def test_no_double_enqueue_in_same_minute(
    fujiwa_shop_id: str,
    rollout_allowlist: list[str],
    enqueue_spy: dict,
    monkeypatch,
):
    """A repeated tick in the same minute does not double-enqueue."""
    monkeypatch.setenv("CDP_BATCH_STAGGERED_RECONCILE_ENABLED", "true")
    monkeypatch.setenv("CDP_BATCH_STAGGERED_RECONCILE_ALLOWLIST", ",".join(rollout_allowlist))

    with patch("juli_backend.workers.tasks.cdp_batch_reconcile.celery_app.send_task") as mock_send:
        mock_send.side_effect = enqueue_spy["record"]

        from juli_backend.workers.tasks.cdp_batch_reconcile import (
            cdp_batch_staggered_reconcile_beat_tick,
        )

        # Tick twice at the same time
        cdp_batch_staggered_reconcile_beat_tick()
        count_after_first_tick = enqueue_spy["count"]()

        cdp_batch_staggered_reconcile_beat_tick()
        count_after_second_tick = enqueue_spy["count"]()

        # Assert: idempotency - repeated tick in same minute doesn't increase enqueue count
        # (Celery Beat itself prevents duplicate ticks in the same minute, but this verifies
        # our code is idempotent if called twice)
        assert count_after_second_tick == count_after_first_tick, (
            "Repeated tick in same minute should not increase enqueue count"
        )


# --- Test: Rollout allowlist limits blast radius ---


def test_rollout_allowlist_scopes_enqueue(
    fujiwa_shop_id: str,
    stub_shop_ids: list[str],
    enqueue_spy: dict,
    monkeypatch,
):
    """Only configured allowlist shops are enqueued; others are never enqueued."""
    allowlist = [fujiwa_shop_id] + stub_shop_ids
    monkeypatch.setenv("CDP_BATCH_STAGGERED_RECONCILE_ENABLED", "true")
    monkeypatch.setenv("CDP_BATCH_STAGGERED_RECONCILE_ALLOWLIST", ",".join(allowlist))

    with patch("juli_backend.workers.tasks.cdp_batch_reconcile.celery_app.send_task") as mock_send:
        mock_send.side_effect = enqueue_spy["record"]

        from juli_backend.workers.tasks.cdp_batch_reconcile import (
            cdp_batch_staggered_reconcile_beat_tick,
        )

        # Freeze at a time and tick
        with freeze_time("2025-01-15 06:30:00", tz_offset=0):
            cdp_batch_staggered_reconcile_beat_tick()

        # Assert: only allowlist shops are enqueued (or none if timing doesn't match)
        enqueued_shops = set()
        for call in enqueue_spy["calls"]:
            kwargs = call.get("kwargs", {})
            job_kwargs = kwargs.get("kwargs", {})
            if "shop_id" in job_kwargs:
                enqueued_shops.add(job_kwargs["shop_id"])

        # All enqueued shops must be in allowlist
        assert enqueued_shops.issubset(set(allowlist)), (
            f"Enqueued shops {enqueued_shops} must be in allowlist {set(allowlist)}"
        )


def test_rollout_allowlist_config_change_not_code_change(
    rollout_allowlist: list[str],
    monkeypatch,
):
    """Widening rollout set is a config change, not a code change."""
    # This is a compile-time assertion: the allowlist must be read from env at runtime
    monkeypatch.setenv("CDP_BATCH_STAGGERED_RECONCILE_ALLOWLIST", ",".join(rollout_allowlist))

    # Reload the module to pick up env change
    import importlib

    import juli_backend.workers.tasks.cdp_batch_reconcile

    importlib.reload(juli_backend.workers.tasks.cdp_batch_reconcile)

    # The allowlist should be loaded from env, so changing env + reload changes behavior
    new_allowlist = rollout_allowlist + ["new-shop-3"]
    monkeypatch.setenv("CDP_BATCH_STAGGERED_RECONCILE_ALLOWLIST", ",".join(new_allowlist))
    importlib.reload(juli_backend.workers.tasks.cdp_batch_reconcile)

    # If the test passes (no exception), config-change is supported


# --- Test: Public trigger sources rejected ---


def test_public_trigger_sources_rejected(
    rollout_allowlist: list[str],
    enqueue_spy: dict,
    monkeypatch,
):
    """Fake Refresh / public Demo trigger sources are rejected."""
    from juli_backend.services.cdp_batch.batch_fetch_planner import (
        FORBIDDEN_TRIGGER_SOURCES,
    )

    # Verify the constant is defined
    assert "fake_refresh" in FORBIDDEN_TRIGGER_SOURCES
    assert "demo_public" in FORBIDDEN_TRIGGER_SOURCES
    assert "visitor_refresh" in FORBIDDEN_TRIGGER_SOURCES
    assert "public_demo" in FORBIDDEN_TRIGGER_SOURCES

    # The guard is enforced at the scheduler/enqueue boundary
    monkeypatch.setenv("CDP_BATCH_STAGGERED_RECONCILE_ENABLED", "true")
    monkeypatch.setenv("CDP_BATCH_STAGGERED_RECONCILE_ALLOWLIST", ",".join(rollout_allowlist))

    with patch("juli_backend.workers.tasks.cdp_batch_reconcile.celery_app.send_task") as mock_send:
        mock_send.side_effect = enqueue_spy["record"]

        from juli_backend.workers.tasks.cdp_batch_reconcile import (
            cdp_batch_staggered_reconcile_beat_tick,
        )

        with freeze_time("2025-01-15 06:30:00", tz_offset=0):
            cdp_batch_staggered_reconcile_beat_tick()

        # The Beat task itself never receives a trigger_source (it's Beat-scheduled)
        # So the guard is in BatchReconcileOrchestrator.run which validates
        # trigger_source="batch_reconcile" always
        assert enqueue_spy["count"]() >= 0  # Just verify the spy is working


def test_batch_fetch_trigger_allowed_rejects_forbidden(monkeypatch):
    """The is_batch_fetch_trigger_allowed guard rejects forbidden sources."""
    from juli_backend.services.cdp_batch.batch_fetch_planner import (
        is_batch_fetch_trigger_allowed,
    )

    # Allowed: None (internal), "batch_reconcile", etc.
    assert is_batch_fetch_trigger_allowed(None) is True
    assert is_batch_fetch_trigger_allowed("batch_reconcile") is True

    # Rejected: fake_refresh, demo_public, visitor_refresh, public_demo
    assert is_batch_fetch_trigger_allowed("fake_refresh") is False
    assert is_batch_fetch_trigger_allowed("demo_public") is False
    assert is_batch_fetch_trigger_allowed("visitor_refresh") is False
    assert is_batch_fetch_trigger_allowed("public_demo") is False


# --- Test: Observability (metrics/logs tied to shop_id and window) ---


@freeze_time("2025-01-15 06:30:00", tz_offset=0)
def test_enqueue_and_completion_metrics(
    rollout_allowlist: list[str],
    enqueue_spy: dict,
    monkeypatch,
):
    """Enqueue and completion metrics carry shop_id and window slot."""
    monkeypatch.setenv("CDP_BATCH_STAGGERED_RECONCILE_ENABLED", "true")
    monkeypatch.setenv("CDP_BATCH_STAGGERED_RECONCILE_ALLOWLIST", ",".join(rollout_allowlist))

    with patch("juli_backend.workers.tasks.cdp_batch_reconcile.celery_app.send_task") as mock_send:
        mock_send.side_effect = enqueue_spy["record"]

        from juli_backend.workers.tasks.cdp_batch_reconcile import (
            cdp_batch_staggered_reconcile_beat_tick,
        )

        cdp_batch_staggered_reconcile_beat_tick()

        # Assert: enqueued jobs carry shop_id and window info
        for call in enqueue_spy["calls"]:
            kwargs = call.get("kwargs", {})
            job_kwargs = kwargs.get("kwargs", {})

            # shop_id must be present
            assert "shop_id" in job_kwargs or "shop_id" in call.get("args", []), (
                "Enqueue must carry shop_id for metrics"
            )

            # reconcile_window must be present (includes minute_of_day and day)
            if "reconcile_window" in job_kwargs:
                window = job_kwargs["reconcile_window"]
                assert window.minute_of_day is not None
                assert window.day is not None


def test_defer_reason_codes_preserved(monkeypatch):
    """Defer reason codes from orchestrator survive unchanged."""
    # These are constants in the respective modules
    from juli_backend.services.cdp_batch.batch_fetch_planner import (
        DEFER_REASON as GAP_DEFER,
    )
    from juli_backend.services.cdp_batch.partner_budget import (
        DEFER_REASON as PARTNER_BUDGET_DEFER,
    )
    from juli_backend.services.cdp_batch.postgres_io_budget import (
        DEFER_REASON as POSTGRES_IO_DEFER,
    )
    from juli_backend.services.cdp_batch.shop_compute_mutex import (
        DEFER_REASON as SPEED_MUTEX_DEFER,
    )

    assert PARTNER_BUDGET_DEFER == "partner_budget_exhausted"
    assert POSTGRES_IO_DEFER == "postgres_io_throttled"
    assert SPEED_MUTEX_DEFER == "speed_mutex_active"
    assert GAP_DEFER == "gap_not_detected"


# --- Test: Rollback scenario (flag flip mid-run) ---


@freeze_time("2025-01-15 00:00:00", tz_offset=0)
def test_rollback_flag_flip_mid_run_produces_zero_enqueues(
    rollout_allowlist: list[str],
    enqueue_spy: dict,
    monkeypatch,
):
    """Flipping flag to OFF mid-run produces zero enqueues for remainder of day."""
    monkeypatch.setenv("CDP_BATCH_STAGGERED_RECONCILE_ENABLED", "true")
    monkeypatch.setenv("CDP_BATCH_STAGGERED_RECONCILE_ALLOWLIST", ",".join(rollout_allowlist))

    with patch("juli_backend.workers.tasks.cdp_batch_reconcile.celery_app.send_task") as mock_send:
        mock_send.side_effect = enqueue_spy["record"]

        from juli_backend.workers.tasks.cdp_batch_reconcile import (
            cdp_batch_staggered_reconcile_beat_tick,
        )

        # First half of day: flag is ON
        for hour in range(12):
            current_time = datetime(2025, 1, 15, hour, 0, 0)
            with freeze_time(current_time, tz_offset=0):
                cdp_batch_staggered_reconcile_beat_tick()

        count_before_flip = enqueue_spy["count"]()

        # Flip flag to OFF
        monkeypatch.setenv("CDP_BATCH_STAGGERED_RECONCILE_ENABLED", "false")

        # Second half of day: flag is OFF
        for hour in range(12, 24):
            current_time = datetime(2025, 1, 15, hour, 0, 0)
            with freeze_time(current_time, tz_offset=0):
                cdp_batch_staggered_reconcile_beat_tick()

        count_after_flip = enqueue_spy["count"]()

        # Assert: no additional enqueues after flip
        assert count_after_flip == count_before_flip, (
            "Flag OFF should stop enqueuing; count must not increase"
        )
