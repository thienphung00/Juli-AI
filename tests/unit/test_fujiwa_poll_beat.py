"""TDD tests for #1949 (ONB-DATA) -- the fleet's first *data* poll schedule.

Before this slice, `workers/services/polling/orchestrate.py::run_fujiwa_poll_cycle`
was never in `celery_app.py`'s `beat_schedule` (see
`workers/tasks/credential_refresh_beat.py`'s own docstring, which names the
same gap for the credential-refresh half of this orchestration function).
Only `services/action_cards/refresh.py::maybe_poll_tiktok_data`'s manual hook
ever called it, so `orders`, `products`, `inventory_items`, and `returns`
never ingested on a schedule.

Scope note: this module tests the *scheduling wrapper* this issue owns --
`workers/tasks/fujiwa_poll_beat.py`. It does not re-test
`run_fujiwa_poll_cycle`'s own internals (vendor sync, dedup, sync-state
cursors) -- those live in `workers/services/polling/`, owned by #1967/#1969,
not this slice. In particular the tenant-scope correctness of the credential
resolution `run_fujiwa_poll_cycle` performs internally (moving from
`reapply_shop_scope` to `with_sticky_shop_scope`) is #1967's fix; this
wrapper calls the cycle and lets that change govern scoping, exactly as
`workers/tasks/credential_refresh_beat.py`'s wrapper defers to
`run_credential_refresh_cycle`'s own per-row `with_shop_scope` rather than
wrapping it in anything at the task level.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from unittest.mock import patch

import pytest
from celery.schedules import crontab

from juli_backend.core.security.tiktok_oauth import TikTokOAuthService
from juli_backend.database.exceptions import NotFound
from juli_backend.integrations.tiktok import RateLimiter
from juli_backend.workers.services.polling import FujiwaPollConfig

# ---------------------------------------------------------------------------
# Beat schedule registration + collision guard
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def registered_task_names() -> set[str]:
    from juli_backend.workers.celery_app import celery_app

    # This is what a worker does at boot; without it autodiscovery stays lazy
    # and the registry looks empty -- the exact #791 trap
    # test_beat_schedule_registration.py's own docstring documents.
    celery_app.loader.import_default_modules()
    return set(celery_app.tasks)


class TestBeatScheduleEntry:
    def test_fujiwa_poll_cycle_entry_registered(self):
        from juli_backend.workers.celery_app import celery_app

        assert "fujiwa-poll-cycle" in celery_app.conf.beat_schedule

    def test_fujiwa_poll_cycle_entry_targets_correct_task_name(self):
        from juli_backend.workers.celery_app import celery_app

        entry = celery_app.conf.beat_schedule["fujiwa-poll-cycle"]
        assert entry["task"] == "juli_backend.fujiwa_poll_cycle"

    def test_fujiwa_poll_cycle_task_is_registered_on_the_worker(
        self, registered_task_names: set[str]
    ):
        """The #791 guard: a beat entry pointing at a task nothing imports
        dispatches into nothing, silently."""
        assert "juli_backend.fujiwa_poll_cycle" in registered_task_names


def _fire_slots(schedule: crontab) -> set[tuple[int, int]]:
    """Every (hour, minute) a crontab fires in a day.

    Mirrors `test_beat_schedule_registration.py::_fire_minutes` -- reads off
    the already-expanded `.hour`/`.minute` sets rather than comparing cron
    strings, which would miss `minute=0` colliding with `minute="*/30"`.
    """
    return {(h, m) for h in schedule.hour for m in schedule.minute}


class TestNoCrontabCollision:
    """#1659's lesson, applied to the new entry: no two beats may share a
    (hour, minute) fire slot. `cdp-batch-staggered-reconcile` is excluded --
    it fires every minute of every day by design (flag defaults OFF) and is
    excluded from this same check for every *existing* entry, not just this
    one (see `test_beat_schedule_registration.py::_daily_beats`, which drops
    it for firing 1440 times a day instead of once)."""

    def test_fujiwa_poll_cycle_shares_no_fire_slot_with_any_other_beat(self):
        from juli_backend.workers.celery_app import celery_app

        schedule = celery_app.conf.beat_schedule
        mine = _fire_slots(schedule["fujiwa-poll-cycle"]["schedule"])

        offenders: dict[str, set[tuple[int, int]]] = {}
        for name, entry in schedule.items():
            if name in ("fujiwa-poll-cycle", "cdp-batch-staggered-reconcile"):
                continue
            shared = mine & _fire_slots(entry["schedule"])
            if shared:
                offenders[name] = shared

        assert not offenders, (
            f"fujiwa-poll-cycle shares a fire slot with: {offenders}. "
            "That is the #1659 collision shape -- pick a minute untaken by "
            "every other entry's hour(s)."
        )


# ---------------------------------------------------------------------------
# Env-missing skip (mirrors credential_refresh_beat / maybe_poll_tiktok_data)
# ---------------------------------------------------------------------------


class TestEnvGuard:
    async def test_missing_env_skips_without_raising(self, monkeypatch, caplog):
        from juli_backend.workers.tasks.fujiwa_poll_beat import (
            _run_fujiwa_poll_beat_async,
        )

        for var in (
            "TIKTOK_APP_KEY",
            "TIKTOK_APP_SECRET",
            "TIKTOK_REDIRECT_URI",
            "REDIS_URL",
        ):
            monkeypatch.delenv(var, raising=False)

        with caplog.at_level(logging.INFO):
            await _run_fujiwa_poll_beat_async()

        skipped = [r for r in caplog.records if r.getMessage() == "fujiwa_poll_beat_skipped"]
        assert len(skipped) == 1
        assert skipped[0].reason == "missing_tiktok_or_redis_env"


# ---------------------------------------------------------------------------
# Cycle wiring -- bound to `run_fujiwa_poll_cycle`'s real keyword signature
# ---------------------------------------------------------------------------


class _RecordingPoll:
    """A test double bound to `run_fujiwa_poll_cycle`'s actual keyword-only
    signature -- never `**kwargs`, so a signature drift on the real function
    would break this double's call site, not silently pass it through."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def __call__(
        self,
        *,
        session,
        config: FujiwaPollConfig,
        oauth_service: TikTokOAuthService,
        rate_limiter: RateLimiter,
        handoff_fn,
    ) -> None:
        self.calls.append(
            {
                "session": session,
                "config": config,
                "oauth_service": oauth_service,
                "rate_limiter": rate_limiter,
                "handoff_fn": handoff_fn,
            }
        )


_ENV = {
    "app_key": "test_app_key",
    "app_secret": "test_app_secret",
    "redirect_uri": "https://example.com/callback",
    "redis_url": "redis://localhost:6399/0",
}


class TestCycleWiring:
    async def test_builds_real_collaborators_and_calls_the_injected_cycle_fn(self, session):
        from juli_backend.workers.tasks.fujiwa_poll_beat import (
            run_fujiwa_poll_beat_cycle,
        )

        poll = _RecordingPoll()

        await run_fujiwa_poll_beat_cycle(session, env=_ENV, poll_cycle_fn=poll)

        assert len(poll.calls) == 1
        call = poll.calls[0]
        assert call["session"] is session
        assert call["config"] == FujiwaPollConfig(
            app_key="test_app_key", app_secret="test_app_secret"
        )
        assert isinstance(call["oauth_service"], TikTokOAuthService)
        assert isinstance(call["rate_limiter"], RateLimiter)
        assert callable(call["handoff_fn"])

    async def test_a_missed_cadence_is_tolerated_by_two_independent_cycles(self, session):
        """S-NFR-6: the wrapper carries no cross-cycle state of its own, so a
        skipped fire (worker down, missed tick) does not need any reset --
        the next fire is just another independent call. Modeled here as two
        back-to-back cycles against the same session, each producing its own
        fresh collaborators, neither erroring from the other having run."""
        from juli_backend.workers.tasks.fujiwa_poll_beat import (
            run_fujiwa_poll_beat_cycle,
        )

        poll = _RecordingPoll()

        await run_fujiwa_poll_beat_cycle(session, env=_ENV, poll_cycle_fn=poll)
        await run_fujiwa_poll_beat_cycle(session, env=_ENV, poll_cycle_fn=poll)

        assert len(poll.calls) == 2
        first, second = poll.calls
        # Fresh collaborators each cycle -- no shared mutable rate-limiter/
        # oauth-service instance that could carry state (e.g. a stale token)
        # from one cycle into the next.
        assert first["oauth_service"] is not second["oauth_service"]
        assert first["rate_limiter"] is not second["rate_limiter"]


# ---------------------------------------------------------------------------
# At least one real cycle: the genuine, non-doubled `run_fujiwa_poll_cycle`
# ---------------------------------------------------------------------------


class TestRealCycle:
    async def test_real_orchestration_is_reached_and_fails_closed_on_no_credential(self, session):
        """No `poll_cycle_fn` override: this drives the actual
        `workers.services.polling.run_fujiwa_poll_cycle`, not a double.

        With no `TikTokCredential` row seeded, the real
        `resolve_production_read_credential` -> `TikTokCredentialRepo.get_by_merchant`
        raises `NotFound` -- proof the call reached genuine production code
        (env parsing, `FujiwaPollConfig`, `TikTokOAuthService`,
        `RateLimiter`, `EtlConsumer`/`make_etl_handoff` all built and handed
        through correctly), not a stub standing in for it. This is also
        exactly the "recovers nothing yet" state described in the issue: a
        first scheduled run has no credential-holding shop configured any
        differently than today, so it surfaces the same failure a manual
        `maybe_poll_tiktok_data` call would.
        """
        from juli_backend.workers.tasks.fujiwa_poll_beat import (
            run_fujiwa_poll_beat_cycle,
        )

        with pytest.raises(NotFound):
            await run_fujiwa_poll_beat_cycle(session, env=_ENV)


# ---------------------------------------------------------------------------
# Task-level exception handling + timeout bound (mirrors
# analytics_backfill_topup / daily_impact_reader)
# ---------------------------------------------------------------------------


class TestTaskExceptionHandling:
    def test_task_logs_structured_error_and_reraises(self, monkeypatch):
        from juli_backend.workers.tasks.fujiwa_poll_beat import fujiwa_poll_cycle

        test_error = ValueError("boom")

        async def failing_async(poll_cycle_fn=None):
            raise test_error

        monkeypatch.setattr(
            "juli_backend.workers.tasks.fujiwa_poll_beat._run_fujiwa_poll_beat_async",
            failing_async,
        )

        logged: list[dict[str, Any]] = []

        def mock_logger_error(msg, extra=None, **kwargs):
            logged.append({"msg": msg, "extra": extra, **kwargs})

        with patch("juli_backend.workers.tasks.fujiwa_poll_beat.logger") as mock_logger:
            mock_logger.error = mock_logger_error
            with pytest.raises(ValueError, match="boom"):
                fujiwa_poll_cycle()

        assert len(logged) == 1
        assert logged[0]["msg"] == "fujiwa_poll_beat_failed"
        assert logged[0]["extra"]["error_type"] == "ValueError"
        assert logged[0].get("exc_info") is True

    def test_task_bounds_runtime_with_asyncio_wait_for(self, monkeypatch):
        from juli_backend.workers.tasks.fujiwa_poll_beat import fujiwa_poll_cycle

        wait_for_calls: list[dict[str, Any]] = []
        original_wait_for = asyncio.wait_for

        async def tracked_wait_for(aw, timeout=None):
            wait_for_calls.append({"timeout": timeout})
            return await original_wait_for(aw, timeout=timeout)

        async def quick_success(poll_cycle_fn=None):
            return None

        monkeypatch.setattr(
            "juli_backend.workers.tasks.fujiwa_poll_beat._run_fujiwa_poll_beat_async",
            quick_success,
        )
        monkeypatch.setattr("asyncio.wait_for", tracked_wait_for)

        fujiwa_poll_cycle()

        assert len(wait_for_calls) == 1
        assert wait_for_calls[0]["timeout"] is not None
        assert wait_for_calls[0]["timeout"] > 0
