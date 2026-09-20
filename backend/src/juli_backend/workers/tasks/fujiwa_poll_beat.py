"""Celery task entrypoint for the fleet's first *data* poll schedule (#1949,
ONB-DATA).

Before this slice, `workers/services/polling/orchestrate.py::run_fujiwa_poll_cycle`
was never in `celery_app.py`'s `beat_schedule` -- reachable only through
`services/action_cards/refresh.py::maybe_poll_tiktok_data`'s manual hook
(see `workers/tasks/credential_refresh_beat.py`'s docstring, which names the
same gap for the credential-refresh half of this orchestration function).
Only Analytics ingested on a schedule; `orders`, `products`,
`inventory_items`, and `returns` did not.

This overlaps #1811 (W10-A/P-CE-1), which independently found the same gap.
Two of that issue's premises are corrected here: the writer chain is not yet
complete (#1948 is fixing the inventory parameter elsewhere), and
`with_shop_scope` is not sufficient on its own (#1967 is moving
`run_fujiwa_poll_cycle`'s internal credential-resolution scope to
`with_sticky_shop_scope`, because the resolver's own `refresh_credential`
call can commit mid-cycle and discard a plain `SET LOCAL`). That fix lives in
`workers/services/polling/orchestrate.py`, which this slice does not own or
modify -- this thin wrapper calls the cycle and lets that change govern
scoping, exactly as `credential_refresh_beat.py`'s wrapper defers to
`run_credential_refresh_cycle`'s own per-row `with_shop_scope` rather than
adding a second, competing scope entry at the task level.

TENANT SCOPE (ADR-089). This task adds no `system_scope`/`with_shop_scope` call
of its own: `run_fujiwa_poll_cycle` resolves its own shop (the Fujiwa
production-read credential's `shop_id`) and re-establishes that scope
internally before any tenant read/write, immediately after resolving the
credential. Nothing in this file reads or writes a tenant-scoped row outside
that call.

MISSED-CADENCE TOLERANCE (S-NFR-6). This wrapper carries no state of its own
between fires: each cycle builds a fresh `TikTokOAuthService`, `RateLimiter`,
and ETL handoff from env and delegates entirely to `run_fujiwa_poll_cycle`,
which persists its own incremental cursors via `TikTokSyncStateRepo` (loaded
at the start of a cycle, saved at the end). A skipped tick needs no reset --
the next fire just re-reads the last saved cursor and covers the gap; a
re-run against an already-synced window re-derives the same normalized rows
ETL's own dedup (`ProcessedEventsRepo`) already treats as duplicates.

WHAT A FIRST SCHEDULED RUN DOES NOT RECOVER. The sync-state watermark this
task's cycle reads (`TikTokSyncStateRepo`) currently sits at roughly "now" --
nothing has ever advanced it from a scheduled run, only ad hoc manual
refreshes. Landing this beat entry alone means the *next* incremental window
starts getting polled; it does not back-fill the historical gap already
missed. Recovering that additionally needs the ledger epoch (#1968) and a
deliberate watermark reset, neither of which this task performs.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.workers.celery_app import celery_app
from juli_backend.workers.tasks.database import get_async_database_url

logger = logging.getLogger(__name__)

# The outer wrapper is a BACKSTOP on `_CycleDeadline`'s own wall-clock budget
# (`cycle_budget_seconds()`, `workers/services/polling/orchestrate.py`), not a
# competing ceiling (#2033). Before this fix `timeout_seconds` was a hardcoded
# 300 regardless of the configured budget, so raising the budget above 300
# changed nothing: production cut a real cold-start cycle off at 290s with
# 3 of 5 steps done, logging the undifferentiated `fujiwa_poll_beat_timeout`
# instead of the inner budget's own per-stage diagnosis
# (`poll_cycle_stage_timed_out`).
#
# `_OUTER_TIMEOUT_GRACE_SECONDS` covers only what happens AFTER the inner
# budget has already fired and is unwinding -- not more cycle work:
#   - one in-flight vendor request already past the deadline check, blocked
#     synchronously up to the client's socket timeout (15s by default --
#     `integrations/tiktok/client.py::TikTokClient.__init__`'s `timeout=15`,
#     the same number `_CycleDeadline`'s own docstring names as the residual
#     overrun `wait_for` cannot preempt)               -> 15s
#   - the rest of that page's ETL handoff loop finishing its writes, bounded
#     by one page, not the whole fetch                  -> 15s
#   - `_poll`'s except block saving the sync-state watermarks it already has
#     (`TikTokSyncStateRepo.save`, one flush) plus the
#     `poll_cycle_stage_timed_out` / `poll_step_outcome` logging -> 10s
# 15 + 15 + 10 = 40s of real unwind cost; doubled to 60s so this stays a
# comfortable backstop rather than a value tuned to the edge. On the 1800s
# default budget that is a 3.3% extension -- still small enough to catch a
# genuinely wedged process (one that never reaches its own save-before-raise
# at all) promptly rather than merely eventually.
_OUTER_TIMEOUT_GRACE_SECONDS = 60.0

#: Bound to `run_fujiwa_poll_cycle`'s real keyword-only signature (session,
#: config, oauth_service, rate_limiter, handoff_fn) -- the injection seam
#: `run_fujiwa_poll_beat_cycle` uses so a test can drive this wrapper without
#: a real vendor call or Redis instance.
PollCycleFn = Callable[..., Awaitable[None]]


def _poll_env_ready() -> dict[str, str] | None:
    """Return poll env vars, or `None` when Fujiwa poll prerequisites are
    unconfigured -- same shape as `services/action_cards/refresh.py::_poll_env_ready`,
    duplicated rather than imported since that module belongs to `services`,
    not `workers`, and this file's write-path lock does not extend there."""
    values = {
        "app_key": os.getenv("TIKTOK_APP_KEY", "").strip(),
        "app_secret": os.getenv("TIKTOK_APP_SECRET", "").strip(),
        "redirect_uri": os.getenv("TIKTOK_REDIRECT_URI", "").strip(),
        "redis_url": os.getenv("REDIS_URL", "").strip(),
    }
    if not all(values.values()):
        return None
    return values


def _database_url() -> str:
    return get_async_database_url()


def _ensure_session_factory():
    from juli_backend.database.database import ensure_worker_session_factory

    return ensure_worker_session_factory(_database_url())


async def run_fujiwa_poll_beat_cycle(
    session: AsyncSession,
    *,
    env: dict[str, str],
    poll_cycle_fn: PollCycleFn | None = None,
) -> None:
    """Build one cycle's production-read poll resources from `env` and run it.

    Fresh `TikTokOAuthService` / `RateLimiter` / ETL handoff every call --
    nothing here is cached across cycles, so a missed fire needs no reset
    (S-NFR-6) and no stale token or rate-limit-window state can leak from one
    cycle into the next.

    `poll_cycle_fn` defaults to the real
    `workers.services.polling.run_fujiwa_poll_cycle`; injectable so a test can
    substitute a recording double bound to that function's actual keyword
    signature instead of exercising the vendor-facing internals it owns.
    """
    from juli_backend.services.etl import EtlConsumer
    from juli_backend.services.ingestion import make_etl_handoff
    from juli_backend.services.tiktok import build_fujiwa_poll_vendor_resources
    from juli_backend.workers.services.polling import FujiwaPollConfig, run_fujiwa_poll_cycle

    poll = poll_cycle_fn if poll_cycle_fn is not None else run_fujiwa_poll_cycle

    async def _dlq_handoff(channel: str, shop_key: str, payload: bytes) -> None:
        logger.error(
            "fujiwa_poll_beat_etl_dlq",
            extra={"channel": channel, "shop_key": shop_key, "payload_bytes": len(payload)},
        )

    consumer = EtlConsumer(session=session, dlq_handoff=_dlq_handoff)
    handoff = make_etl_handoff(consumer)

    # `TikTokOAuthService`/`RateLimiter` construction lives in
    # `services.tiktok.poll_resources` -- `workers -> integrations` is a
    # forbidden edge (`.importlinter.toml`), not just depth-capped, so this
    # task file may not build `TikTokAuth`/`RateLimiter` itself. See that
    # module's docstring.
    oauth_service, rate_limiter = build_fujiwa_poll_vendor_resources(
        session,
        app_key=env["app_key"],
        app_secret=env["app_secret"],
        redirect_uri=env["redirect_uri"],
        redis_url=env["redis_url"],
    )

    await poll(
        session=session,
        config=FujiwaPollConfig(app_key=env["app_key"], app_secret=env["app_secret"]),
        oauth_service=oauth_service,
        rate_limiter=rate_limiter,
        handoff_fn=handoff,
    )


async def _run_fujiwa_poll_beat_async(poll_cycle_fn: PollCycleFn | None = None) -> None:
    env = _poll_env_ready()
    if env is None:
        logger.info(
            "fujiwa_poll_beat_skipped",
            extra={"reason": "missing_tiktok_or_redis_env"},
        )
        return

    factory = _ensure_session_factory()
    async with factory() as session:
        await run_fujiwa_poll_beat_cycle(session, env=env, poll_cycle_fn=poll_cycle_fn)
        await session.commit()


@celery_app.task(name="juli_backend.fujiwa_poll_cycle")
def fujiwa_poll_cycle() -> None:
    """Celery Beat periodic task -- the fleet's first scheduled data poll.

    Thin wrapper only, mirroring `workers/tasks/analytics_backfill_topup.py`
    and `workers/tasks/impact_reader.py`: builds vendor/Redis resources from
    env, opens a session, delegates to `run_fujiwa_poll_beat_cycle` with
    production defaults (the real `run_fujiwa_poll_cycle`), commits. No-op
    when TikTok/Redis env is not configured -- same as
    `maybe_poll_tiktok_data` today.

    Exception handling mirrors `analytics_backfill_topup`/`daily_impact_reader`:
    any unhandled exception is logged with structured context and re-raised
    so Celery retry logic can kick in.

    `timeout_seconds` is derived from the cycle's own configured budget
    (`cycle_budget_seconds()`), not a hardcoded ceiling that competes with it
    (#2033) -- see `_OUTER_TIMEOUT_GRACE_SECONDS` above for why the grace is
    60s. This bound only ever fires on a genuinely wedged process; a cycle
    that respects its own budget always raises the inner, per-stage
    `PollCycleTimeoutError` first, which the `except Exception` branch below
    logs and re-raises undisturbed.
    """
    from juli_backend.workers.services.polling.orchestrate import cycle_budget_seconds

    timeout_seconds = cycle_budget_seconds() + _OUTER_TIMEOUT_GRACE_SECONDS
    try:
        asyncio.run(asyncio.wait_for(_run_fujiwa_poll_beat_async(), timeout=timeout_seconds))
    except TimeoutError:
        logger.error(
            "fujiwa_poll_beat_timeout",
            extra={"timeout_seconds": timeout_seconds},
        )
        raise
    except Exception as exc:
        logger.error(
            "fujiwa_poll_beat_failed",
            extra={
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
            exc_info=True,
        )
        raise
