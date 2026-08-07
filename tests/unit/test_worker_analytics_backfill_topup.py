"""Tests for analytics_backfill_topup Celery task (issue #791).

Verifies the scheduled task that keeps shop history current:
- Exception handling with structured logging and re-raise
- Timeout bounding to prevent indefinite hangs
- Beat schedule registration with A1 scope (single-shop only)
"""

import asyncio
from unittest.mock import patch

import pytest


class TestAnalyticsBackfillTopupTask:
    """Test the analytics_backfill_topup Celery Beat task."""

    def test_task_logs_structured_error_and_reraises_on_exception(self, monkeypatch):
        """Verify task logs structured error and re-raises on unhandled exception.

        Any exception from _run_analytics_backfill_topup_async should be logged
        with error type and message, then re-raised so Celery retry logic can
        kick in.
        """
        from juli_backend.workers.tasks.analytics_backfill_topup import (
            analytics_backfill_topup,
        )

        test_error = ValueError("Test error from async task")

        async def failing_async():
            raise test_error

        logged_errors = []

        def mock_logger_error(msg, extra=None, **kwargs):
            logged_errors.append({"msg": msg, "extra": extra, **kwargs})

        # Mock the async runner to raise
        monkeypatch.setattr(
            "juli_backend.workers.tasks.analytics_backfill_topup._run_analytics_backfill_topup_async",
            failing_async,
        )

        # Mock logger
        with patch("juli_backend.workers.tasks.analytics_backfill_topup.logger") as mock_logger:
            mock_logger.error = mock_logger_error

            # Task should raise (after logging)
            with pytest.raises(ValueError, match="Test error from async task"):
                analytics_backfill_topup()

        # Verify structured error was logged
        assert len(logged_errors) == 1
        error_log = logged_errors[0]
        assert error_log["msg"] == "analytics_backfill_topup_failed"
        assert error_log["extra"]["error_type"] == "ValueError"
        assert error_log["extra"]["error_message"] == "Test error from async task"
        assert error_log.get("exc_info") is True

    def test_task_handles_timeout_error_distinctly(self, monkeypatch):
        """Verify task logs TimeoutError separately and re-raises.

        asyncio.TimeoutError should be logged with its own message for better
        observability, then re-raised.
        """
        from juli_backend.workers.tasks.analytics_backfill_topup import (
            analytics_backfill_topup,
        )

        async def timing_out():
            raise TimeoutError("Operation took too long")

        logged_errors = []

        def mock_logger_error(msg, extra=None, **kwargs):
            logged_errors.append({"msg": msg, "extra": extra})

        # Mock the async runner to timeout
        monkeypatch.setattr(
            "juli_backend.workers.tasks.analytics_backfill_topup._run_analytics_backfill_topup_async",
            timing_out,
        )

        # Mock logger
        with patch("juli_backend.workers.tasks.analytics_backfill_topup.logger") as mock_logger:
            mock_logger.error = mock_logger_error

            # Task should raise TimeoutError
            with pytest.raises(asyncio.TimeoutError):
                analytics_backfill_topup()

        # Verify timeout was logged distinctly
        timeout_logs = [log for log in logged_errors if "timeout" in log["msg"].lower()]
        assert len(timeout_logs) > 0, "TimeoutError should be logged with 'timeout' in message"

    def test_task_bounds_runtime_with_asyncio_wait_for(self, monkeypatch):
        """Verify task uses asyncio.wait_for with timeout to prevent hangs.

        The task must call asyncio.wait_for with a timeout (e.g., 300 seconds)
        to prevent hung DB connections or slow Partner API calls from blocking
        a Celery worker indefinitely.
        """
        from juli_backend.workers.tasks.analytics_backfill_topup import (
            analytics_backfill_topup,
        )

        wait_for_calls = []

        original_wait_for = asyncio.wait_for

        async def tracked_wait_for(aw, timeout=None):
            wait_for_calls.append({"timeout": timeout})
            return await original_wait_for(aw, timeout=timeout)

        # Mock async runner to succeed quickly
        async def quick_success():
            pass

        monkeypatch.setattr(
            "juli_backend.workers.tasks.analytics_backfill_topup._run_analytics_backfill_topup_async",
            quick_success,
        )

        monkeypatch.setattr("asyncio.wait_for", tracked_wait_for)

        # Run the task
        analytics_backfill_topup()

        # Verify asyncio.wait_for was called with a timeout
        assert len(wait_for_calls) > 0, "asyncio.wait_for should be called"
        assert wait_for_calls[0]["timeout"] is not None, "timeout should be set"
        # Timeout should be reasonable (e.g., 300 seconds = 5 minutes)
        assert wait_for_calls[0]["timeout"] > 0, "timeout should be positive"


class TestAnalyticsBackfillBeatSchedule:
    """Test beat schedule registration for analytics backfill topup."""

    def test_beat_schedule_entry_registered_with_correct_name(self):
        """Verify 'analytics-backfill-topup' entry exists in beat schedule."""
        from juli_backend.workers.celery_app import celery_app

        assert "analytics-backfill-topup" in celery_app.conf.beat_schedule, (
            "analytics-backfill-topup must be registered in beat_schedule"
        )

    def test_beat_schedule_entry_targets_correct_task_name(self):
        """Verify beat schedule targets 'juli_backend.analytics_backfill_topup' task."""
        from juli_backend.workers.celery_app import celery_app

        schedule_entry = celery_app.conf.beat_schedule["analytics-backfill-topup"]
        assert schedule_entry["task"] == "juli_backend.analytics_backfill_topup", (
            "beat schedule should target the registered task name"
        )

    def test_beat_schedule_scope_is_single_shop_only_a1(self):
        """Verify beat schedule targets DEMO_REFERENCE_SHOP_ID only (A1 scope).

        The task comment explicitly states: 'A1 scope: single-shop only'.
        This test catches future attempts to widen it to fleet-wide loops,
        which belong in A2 (#601 US #30).

        Scope is enforced by: task reads DEMO_REFERENCE_SHOP_ID env var and
        returns early if unset. Beat schedule does not pass shop_id parameter
        (single shop is baked into the task logic).
        """
        from juli_backend.workers.celery_app import celery_app

        schedule_entry = celery_app.conf.beat_schedule["analytics-backfill-topup"]

        # Verify the entry doesn't pass multiple shop IDs (which would indicate fleet-wide)
        assert "args" not in schedule_entry or not schedule_entry.get("args"), (
            "A1 scope: beat schedule should NOT pass shop_id arguments (single shop only)"
        )
        assert "kwargs" not in schedule_entry or not schedule_entry.get("kwargs"), (
            "A1 scope: beat schedule should NOT pass shop_id kwargs (single shop only)"
        )

    def test_get_demo_reference_shop_id_reads_env_var(self, monkeypatch):
        """Verify task reads DEMO_REFERENCE_SHOP_ID from env and returns None if unset."""
        import uuid

        from juli_backend.workers.tasks.analytics_backfill_topup import (
            get_demo_reference_shop_id,
        )

        # When env var is set, should return UUID
        test_shop_id = str(uuid.uuid4())
        monkeypatch.setenv("DEMO_REFERENCE_SHOP_ID", test_shop_id)
        result = get_demo_reference_shop_id()
        assert str(result) == test_shop_id, "should parse env var to UUID"

        # When env var is unset, should return None
        monkeypatch.delenv("DEMO_REFERENCE_SHOP_ID", raising=False)
        result = get_demo_reference_shop_id()
        assert result is None, "should return None when env var unset (A1 scope guard)"
