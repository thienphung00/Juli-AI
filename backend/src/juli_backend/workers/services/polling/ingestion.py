"""Per-shop ingestion: bootstrap fast phase, history phase, scheduled cycle (fast track P1-B).

SPEC §3.1–3.3 and §3.7. Three entrypoints, one per Celery task in
``workers/tasks/shop_ingestion.py``:

``run_bootstrap_fast_phase``
    Right after a shop connects (high-priority queue). Commerce cold start
    (the same four search steps as every cycle -- with no watermark they run
    under the 400-page backfill budget) plus the last ``SHOP_BOOTSTRAP_FAST_DAYS``
    (30) days of analytics as ONE date-range pass, then the existing scoring +
    card persistence for that shop, with no second poll. Its only job is the
    first card.

``run_history_chunks``
    Low-priority queue, after the fast phase. Walks analytics backwards in
    ``SHOP_HISTORY_CHUNK_DAYS`` chunks from the earliest date already stored,
    until TikTok returns no data (``SHOP_HISTORY_EMPTY_CHUNKS_TO_STOP``
    consecutive empty chunks), refuses the range as out of bounds, or
    ``SHOP_HISTORY_MAX_LOOKBACK_DAYS`` is reached. The earliest date reached is
    persisted after every chunk, so a re-run resumes where the last one stopped
    and never refetches a completed chunk. A chunk whose calls were
    rate-limited is not recorded and is retried.

``run_shop_cycle``
    The scheduled cycle, once per shop per fan-out. Commerce steps every
    fifteen minutes exactly as before (watermarks, page caps, verdicts).
    Analytics at most once a day: from the last fully-fetched day + 1 up to
    TikTok's ``latest_available_date``, read from a single A-36 probe; when
    nothing is new the cycle makes zero analytics detail calls. A day pass that
    fetched new days re-runs scoring (D11). After the commerce steps, a bounded
    number of orders' cost data (price detail, finance transactions; P14-C) is
    read by ``services.order_costs.sync_order_costs``, which never fails the cycle.

TENANT SCOPE. Every entrypoint resolves the shop's own credential with
``resolve_read_credential_for_shop``, refuses it unless it is read-capable and
owned by that shop (``_assert_pollable_read_credential``), and only then enters
``with_sticky_shop_scope(shop_id)`` for the whole unit of work -- the #1967
order (resolve -> assert -> scope). The scope is sticky because the ETL handoff,
the scoring step and this module's own state writes all commit mid-cycle.

LATENCY (SPEC §3.7, AC-1.10). Each transition is written to
``shop_ingestion_state`` (first occurrence only) and emitted as a structured
log event carrying ``seconds_since_connect``:

    shop_connect_committed      (logged by the OAuth callback)
    shop_bootstrap_enqueued     (logged by the dispatcher; stamped here)
    shop_bootstrap_fast_started
    shop_bootstrap_fast_done
    shop_first_card_persisted
    shop_history_started
    shop_history_chunk_done
    shop_history_done
    shop_bootstrap_failed
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.database.tenant_context import with_shop_scope, with_sticky_shop_scope
from juli_backend.integrations.tiktok import (
    READ_CAPABILITIES,
    SANDBOX_AUTH_ID,
    ProductionReadClientFactory,
    ProductionReadResources,
    RateLimiter,
)
from juli_backend.models.ingestion import (
    BOOTSTRAP_FAILED,
    BOOTSTRAP_FAST_DONE,
    BOOTSTRAP_FAST_RUNNING,
    BOOTSTRAP_HISTORY_DONE,
    BOOTSTRAP_HISTORY_RUNNING,
    ShopIngestionState,
)
from juli_backend.models.models import (
    AnalyticsPerformanceInterval,
    Shop,
    TikTokCredential,
)
from juli_backend.repositories import ShopIngestionStateRepo, TikTokSyncStateRepo, utc_now_naive
from juli_backend.services.ingestion import HandoffFn
from juli_backend.services.order_costs import OrderCostsResult, sync_order_costs
from juli_backend.workers.services.polling.analytics_range import (
    AnalyticsRangeResult,
    probe_latest_available_date,
    sync_analytics_range,
    utc_today,
)
from juli_backend.workers.services.polling.orchestrate import (
    _FUJIWA_POLL_STEPS,
    CreateResourcesFn,
    FujiwaPollConfig,
    ResolveCredentialFn,
    SleepFn,
    _assert_cycle_succeeded,
    _assert_pollable_read_credential,
    _CycleDeadline,
    _default_resolve_credential,
    _factory_config,
    _record_cycle,
    _run_poll_step,
    _synced_product_ids_fn,
    _within_cycle_budget,
)
from juli_backend.workers.services.polling.sync import PollStepDroppedRowsError, SyncOutcome

logger = logging.getLogger(__name__)

# -- configuration ----------------------------------------------------------

FAST_DAYS_ENV = "SHOP_BOOTSTRAP_FAST_DAYS"
HISTORY_CHUNK_DAYS_ENV = "SHOP_HISTORY_CHUNK_DAYS"
HISTORY_MAX_LOOKBACK_DAYS_ENV = "SHOP_HISTORY_MAX_LOOKBACK_DAYS"
HISTORY_EMPTY_CHUNKS_TO_STOP_ENV = "SHOP_HISTORY_EMPTY_CHUNKS_TO_STOP"
HISTORY_CHUNKS_PER_TASK_ENV = "SHOP_HISTORY_CHUNKS_PER_TASK"
BOOTSTRAP_BUDGET_SECONDS_ENV = "SHOP_BOOTSTRAP_BUDGET_SECONDS"
HISTORY_BUDGET_SECONDS_ENV = "SHOP_HISTORY_BUDGET_SECONDS"


def _env_int(name: str, default: int, *, minimum: int = 1) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, value)


def _env_float(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return max(1.0, value)


def fast_days() -> int:
    return _env_int(FAST_DAYS_ENV, 30)


def history_chunk_days() -> int:
    return _env_int(HISTORY_CHUNK_DAYS_ENV, 30)


def history_max_lookback_days() -> int:
    return _env_int(HISTORY_MAX_LOOKBACK_DAYS_ENV, 1095)


def history_empty_chunks_to_stop() -> int:
    return _env_int(HISTORY_EMPTY_CHUNKS_TO_STOP_ENV, 2)


def history_chunks_per_task() -> int:
    return _env_int(HISTORY_CHUNKS_PER_TASK_ENV, 12)


#: Don't start a history chunk with less than this much task budget left.
_HISTORY_CHUNK_MIN_SECONDS = 120.0


def bootstrap_budget_seconds() -> float:
    return _env_float(BOOTSTRAP_BUDGET_SECONDS_ENV, 3600.0)


def history_budget_seconds() -> float:
    return _env_float(HISTORY_BUDGET_SECONDS_ENV, 1800.0)


ScoreFn = Callable[[AsyncSession, uuid.UUID], Awaitable[list[Any]]]


# Scoring is INJECTED, never imported here: `services/action_cards` already
# imports this package (`maybe_poll_tiktok_data` -> `run_fujiwa_poll_cycle`),
# so importing it back would make the two modules a cycle. The Celery wrappers
# in `workers/tasks/shop_ingestion.py` pass `score_and_persist_cards`.


# -- latency events ---------------------------------------------------------


def _seconds_since(start: datetime | None, at: datetime | None) -> float | None:
    if start is None or at is None:
        return None
    return round((at - start).total_seconds(), 3)


def log_transition(
    event: str, state: ShopIngestionState | None, *, shop_id: uuid.UUID, **extra: Any
):
    """One structured event per bootstrap transition (AC-1.10)."""
    at = utc_now_naive()
    connect = state.connect_committed_at if state is not None else None
    logger.info(
        event,
        extra={
            "shop_id": str(shop_id),
            "event": event,
            "at": at.isoformat(),
            "status": state.status if state is not None else None,
            "seconds_since_connect": _seconds_since(connect, at),
            **extra,
        },
    )


# -- shared plumbing --------------------------------------------------------


@dataclass
class _ShopRun:
    """A resolved, verified, scoped shop and the collaborators a run needs."""

    session: AsyncSession
    shop_id: uuid.UUID
    credential: TikTokCredential
    resources: ProductionReadResources
    shop_key: str
    app_id: str
    sync_state: dict[str, Any]
    sync_state_repo: TikTokSyncStateRepo
    state_repo: ShopIngestionStateRepo


@asynccontextmanager
async def _scoped_shop_run(
    *,
    session: AsyncSession,
    config: FujiwaPollConfig,
    shop_id: uuid.UUID,
    resolve_credential: ResolveCredentialFn | None,
    factory: ProductionReadClientFactory | None,
    create_resources: CreateResourcesFn | None,
    sync_state_repo: TikTokSyncStateRepo | None,
):
    """resolve -> assert -> sticky scope, then build the run's collaborators.

    The order is the safety property (#1967 / #1995): the scope grants the
    shop's authority, so it is entered only after the credential has been
    proved to be a read credential OWNED BY ``shop_id``.
    """
    resolve = resolve_credential or _default_resolve_credential
    # The resolve reads `tiktok_credentials`, whose RLS policy is keyed on the
    # shop GUC, and these tasks start with no scope at all (the fan-out names
    # the shop, nothing has entered it). So the read runs under a plain
    # `with_shop_scope` for the NAMED shop: it can only ever see rows that shop
    # owns, which is the resolver's own contract restated by the database. The
    # sticky cycle scope -- the authority to write -- is still granted only
    # after the assert below.
    async with with_shop_scope(session, shop_id):
        credential = await resolve(session, shop_id)
    _assert_pollable_read_credential(credential, shop_id=shop_id)
    async with with_sticky_shop_scope(session, shop_id):
        client_factory = factory or ProductionReadClientFactory()
        build = create_resources or client_factory.create_resources
        resources = build(_factory_config(config, credential))
        shop = await session.get(Shop, shop_id)
        if shop is None or not shop.tiktok_shop_id:
            raise ValueError(
                f"shop ingestion requires a shop with tiktok_shop_id; shop_id={shop_id}"
            )
        repo = sync_state_repo or TikTokSyncStateRepo(session)
        yield _ShopRun(
            session=session,
            shop_id=shop_id,
            credential=credential,
            resources=resources,
            shop_key=shop.tiktok_shop_id,
            app_id=config.app_key,
            sync_state=await repo.load(shop_id),
            sync_state_repo=repo,
            state_repo=ShopIngestionStateRepo(session),
        )


async def _run_commerce_steps(
    run: _ShopRun,
    *,
    rate_limiter: RateLimiter,
    handoff_fn: HandoffFn,
    sleep: SleepFn,
    deadline: _CycleDeadline,
    outcomes: list[SyncOutcome],
) -> None:
    """Orders, products, returns, inventory -- unchanged semantics (SPEC §3.3)."""
    list_product_ids = _synced_product_ids_fn(run.session, run.shop_id)
    for step in _FUJIWA_POLL_STEPS:
        outcomes.append(
            await _run_poll_step(
                step,
                resources=run.resources,
                rate_limiter=rate_limiter,
                handoff_fn=handoff_fn,
                app_id=run.app_id,
                shop_key=run.shop_key,
                sync_state=run.sync_state,
                sleep=sleep,
                deadline=deadline,
                list_product_ids=list_product_ids,
            )
        )


async def _analytics_range(
    run: _ShopRun,
    *,
    rate_limiter: RateLimiter,
    handoff_fn: HandoffFn,
    sleep: SleepFn,
    deadline: _CycleDeadline,
    start: date,
    end_exclusive: date,
    concurrency: int | None,
    include_per_day_extras: bool = False,
    out_of_range_is_end: bool = False,
    stage: str = "analytics",
) -> AnalyticsRangeResult:
    return await _within_cycle_budget(
        lambda: sync_analytics_range(
            resource=run.resources.analytics,
            rate_limiter=rate_limiter,
            handoff_fn=handoff_fn,
            app_id=run.app_id,
            shop_id=run.shop_key,
            start=start,
            end_exclusive=end_exclusive,
            sleep=sleep,
            deadline=deadline,
            concurrency=concurrency,
            include_per_day_extras=include_per_day_extras,
            out_of_range_is_end=out_of_range_is_end,
        ),
        deadline=deadline,
        stage=stage,
    )


async def _probe_latest(
    run: _ShopRun,
    *,
    rate_limiter: RateLimiter,
    sleep: SleepFn,
    deadline: _CycleDeadline,
    today: date,
) -> date | None:
    return await _within_cycle_budget(
        lambda: probe_latest_available_date(
            run.resources.analytics,
            rate_limiter=rate_limiter,
            app_id=run.app_id,
            shop_id=run.shop_key,
            today=today,
            sleep=sleep,
            deadline=deadline,
        ),
        deadline=deadline,
        stage="analytics_probe",
    )


async def max_stored_analytics_day(session: AsyncSession, shop_id: uuid.UUID) -> date | None:
    """The newest day of daily shop/product analytics already stored for the shop."""
    stmt = select(func.max(AnalyticsPerformanceInterval.start_date)).where(
        AnalyticsPerformanceInterval.shop_id == shop_id,
        AnalyticsPerformanceInterval.grain.in_(("shop", "product")),
        AnalyticsPerformanceInterval.hour_index.is_(None),
    )
    value = (await session.execute(stmt)).scalar_one_or_none()
    if isinstance(value, datetime):
        return value.date()
    return value


async def _score(
    run: _ShopRun,
    score_fn: ScoreFn | None,
    *,
    phase: str,
) -> int | None:
    """Run scoring + card persistence; stamp the first card. Never raises.

    A scoring failure must not undo the data the phase just landed, nor send
    the shop back through bootstrap: the next daily pass scores again (D11).
    Returns the number of cards persisted, or ``None`` on failure.
    """
    if score_fn is None:
        logger.warning("shop_scoring_skipped", extra={"shop_id": str(run.shop_id), "phase": phase})
        return None
    try:
        cards = await score_fn(run.session, run.shop_id)
    except Exception as exc:
        logger.error(
            "shop_scoring_failed",
            extra={"shop_id": str(run.shop_id), "phase": phase, "error": repr(exc)[:200]},
            exc_info=True,
        )
        try:
            await run.session.rollback()
            await run.state_repo.update(run.shop_id, last_error=f"scoring: {exc!r}")
            await run.session.commit()
        except Exception:
            logger.error("shop_ingestion_state_write_failed", exc_info=True)
        return None
    count = len(cards or [])
    if count:
        state, written = await run.state_repo.stamp_once(run.shop_id, "first_card_at")
        await run.session.commit()
        if written:
            log_transition(
                "shop_first_card_persisted",
                state,
                shop_id=run.shop_id,
                phase=phase,
                cards=count,
                seconds_since_fast_done=_seconds_since(state.fast_done_at, state.first_card_at),
            )
    return count


async def _save_partial(run: _ShopRun, outcomes: list[SyncOutcome]) -> None:
    """Persist the watermarks and verdicts of the steps that did finish.

    The failing-path twin of the success-path save, committed so it survives
    the exception (``_record_cycle`` itself never raises; the commit is guarded
    for the same reason -- it must not replace the original failure).
    """
    await _record_cycle(
        run.sync_state_repo, run.shop_id, sync_state=run.sync_state, outcomes=outcomes
    )
    try:
        await run.session.commit()
    except Exception:
        logger.error(
            "poll_cycle_partial_state_commit_failed",
            extra={"shop_id": str(run.shop_id)},
            exc_info=True,
        )


async def _mark_failed(run: _ShopRun, *, phase: str, error: BaseException) -> None:
    """Record a failed phase. Guarded: it runs on the failing path."""
    try:
        await run.session.rollback()
        state = await run.state_repo.update(
            run.shop_id,
            status=BOOTSTRAP_FAILED,
            failed_phase=phase,
            failed_at=utc_now_naive(),
            last_error=repr(error),
        )
        await run.session.commit()
        log_transition(
            "shop_bootstrap_failed",
            state,
            shop_id=run.shop_id,
            phase=phase,
            error=repr(error)[:200],
        )
    except Exception:
        logger.error(
            "shop_ingestion_state_write_failed",
            extra={"shop_id": str(run.shop_id), "phase": phase},
            exc_info=True,
        )


# -- fast phase -------------------------------------------------------------


@dataclass
class FastPhaseResult:
    shop_id: uuid.UUID
    skipped: bool = False
    reason: str | None = None
    analytics: AnalyticsRangeResult | None = None
    window_start: date | None = None
    window_end_exclusive: date | None = None
    cards: int | None = None
    outcomes: list[SyncOutcome] = field(default_factory=list)


async def run_bootstrap_fast_phase(
    *,
    session: AsyncSession,
    config: FujiwaPollConfig,
    shop_id: uuid.UUID,
    rate_limiter: RateLimiter,
    handoff_fn: HandoffFn,
    resolve_credential: ResolveCredentialFn | None = None,
    factory: ProductionReadClientFactory | None = None,
    create_resources: CreateResourcesFn | None = None,
    sync_state_repo: TikTokSyncStateRepo | None = None,
    sleep: SleepFn = asyncio.sleep,
    score_fn: ScoreFn | None = None,
    now: datetime | None = None,
    window_days: int | None = None,
    concurrency: int | None = None,
    budget_seconds: float | None = None,
    connect_committed_at: datetime | None = None,
    enqueued_at: datetime | None = None,
    force: bool = False,
) -> FastPhaseResult:
    """Bootstrap fast phase for one shop. See the module docstring."""
    deadline = _CycleDeadline(budget_seconds=budget_seconds or bootstrap_budget_seconds())
    days = window_days or fast_days()
    today = utc_today(now)

    async with _scoped_shop_run(
        session=session,
        config=config,
        shop_id=shop_id,
        resolve_credential=resolve_credential,
        factory=factory,
        create_resources=create_resources,
        sync_state_repo=sync_state_repo,
    ) as run:
        repo = run.state_repo
        existing = await repo.find(shop_id)
        if existing is not None and existing.fast_done_at is not None and not force:
            logger.info(
                "shop_bootstrap_skipped", extra={"shop_id": str(shop_id), "reason": "fast_done"}
            )
            return FastPhaseResult(shop_id=shop_id, skipped=True, reason="fast_done")

        if connect_committed_at is not None:
            await repo.stamp_once(shop_id, "connect_committed_at", connect_committed_at)
        if enqueued_at is not None:
            await repo.stamp_once(shop_id, "bootstrap_enqueued_at", enqueued_at)
        state, _ = await repo.stamp_once(
            shop_id,
            "fast_started_at",
            status=BOOTSTRAP_FAST_RUNNING,
            failed_phase=None,
        )
        await session.commit()
        log_transition("shop_bootstrap_fast_started", state, shop_id=shop_id, window_days=days)

        outcomes: list[SyncOutcome] = []
        result = FastPhaseResult(shop_id=shop_id, outcomes=outcomes)
        try:
            await _run_commerce_steps(
                run,
                rate_limiter=rate_limiter,
                handoff_fn=handoff_fn,
                sleep=sleep,
                deadline=deadline,
                outcomes=outcomes,
            )
            latest = await _probe_latest(
                run, rate_limiter=rate_limiter, sleep=sleep, deadline=deadline, today=today
            )
            last_day = latest or (today - timedelta(days=1))
            window_end = last_day + timedelta(days=1)
            window_start = window_end - timedelta(days=days)
            result.window_start, result.window_end_exclusive = window_start, window_end
            analytics = await _analytics_range(
                run,
                rate_limiter=rate_limiter,
                handoff_fn=handoff_fn,
                sleep=sleep,
                deadline=deadline,
                start=window_start,
                end_exclusive=window_end,
                concurrency=concurrency,
            )
            result.analytics = analytics
            outcomes.append(analytics.outcome)
        except PollStepDroppedRowsError as exc:
            outcomes.append(exc.outcome)
            await _save_partial(run, outcomes)
            await _mark_failed(run, phase="fast", error=exc)
            raise
        except Exception as exc:
            await _save_partial(run, outcomes)
            await _mark_failed(run, phase="fast", error=exc)
            raise

        await _record_cycle(
            run.sync_state_repo, shop_id, sync_state=run.sync_state, outcomes=outcomes
        )
        await session.commit()
        try:
            _assert_cycle_succeeded(outcomes, shop_id=shop_id)
        except Exception as exc:
            await _mark_failed(run, phase="fast", error=exc)
            raise

        # A window some of whose calls were refused (rate limit) is not "fetched
        # through" any day: the cursor is left before the window so the first
        # daily pass fetches it again rather than skipping its holes forever.
        through = (
            max((date.fromisoformat(d) for d in analytics.days_with_rows), default=None)
            if analytics.complete
            else window_start - timedelta(days=1)
        )
        state = await repo.update(
            shop_id,
            status=BOOTSTRAP_FAST_DONE,
            failed_phase=None,
            last_error=None,
            history_earliest_date=window_start,
            analytics_through_date=through,
            analytics_last_run_on=today if analytics.complete else None,
            latest_available_date=latest,
        )
        state, _ = await repo.stamp_once(shop_id, "fast_done_at")
        await session.commit()
        log_transition(
            "shop_bootstrap_fast_done",
            state,
            shop_id=shop_id,
            window_start=window_start.isoformat(),
            window_end_exclusive=window_end.isoformat(),
            analytics_days=len(analytics.days_with_rows),
            detail_calls=analytics.detail_calls,
            analytics_complete=analytics.complete,
        )

        result.cards = await _score(run, score_fn, phase="fast")
        return result


# -- history phase ----------------------------------------------------------


@dataclass
class HistoryResult:
    shop_id: uuid.UUID
    done: bool = False
    reason: str | None = None
    chunks: list[tuple[date, date]] = field(default_factory=list)
    earliest_date: date | None = None
    detail_calls: int = 0


async def run_history_chunks(
    *,
    session: AsyncSession,
    config: FujiwaPollConfig,
    shop_id: uuid.UUID,
    rate_limiter: RateLimiter,
    handoff_fn: HandoffFn,
    resolve_credential: ResolveCredentialFn | None = None,
    factory: ProductionReadClientFactory | None = None,
    create_resources: CreateResourcesFn | None = None,
    sync_state_repo: TikTokSyncStateRepo | None = None,
    sleep: SleepFn = asyncio.sleep,
    now: datetime | None = None,
    max_chunks: int | None = None,
    chunk_days: int | None = None,
    max_lookback_days: int | None = None,
    empty_chunks_to_stop: int | None = None,
    concurrency: int | None = None,
    budget_seconds: float | None = None,
) -> HistoryResult:
    """Walk analytics backwards from the earliest stored day. See the module docstring."""
    deadline = _CycleDeadline(budget_seconds=budget_seconds or history_budget_seconds())
    span = chunk_days or history_chunk_days()
    lookback = max_lookback_days or history_max_lookback_days()
    stop_after_empty = empty_chunks_to_stop or history_empty_chunks_to_stop()
    budget_chunks = max_chunks or history_chunks_per_task()
    today = utc_today(now)
    floor = today - timedelta(days=lookback)

    async with _scoped_shop_run(
        session=session,
        config=config,
        shop_id=shop_id,
        resolve_credential=resolve_credential,
        factory=factory,
        create_resources=create_resources,
        sync_state_repo=sync_state_repo,
    ) as run:
        repo = run.state_repo
        state = await repo.find(shop_id)
        result = HistoryResult(shop_id=shop_id)
        if state is None or state.fast_done_at is None:
            result.reason = "fast_not_done"
            logger.info(
                "shop_history_skipped", extra={"shop_id": str(shop_id), "reason": "fast_not_done"}
            )
            return result
        if state.history_done_at is not None:
            result.done, result.reason = True, "already_done"
            result.earliest_date = state.history_earliest_date
            return result

        state, first = await repo.stamp_once(
            shop_id, "history_started_at", status=BOOTSTRAP_HISTORY_RUNNING, failed_phase=None
        )
        await session.commit()
        if first:
            log_transition("shop_history_started", state, shop_id=shop_id, chunk_days=span)

        try:
            chunks_left = budget_chunks
            # The window length for the next attempt. Halved when TikTok refuses
            # a window as out of range, so the walk ends AT TikTok's limit rather
            # than up to a whole chunk short of it; reset after every chunk.
            window = span
            while chunks_left > 0:
                if deadline.remaining() < _HISTORY_CHUNK_MIN_SECONDS:
                    # Stop between chunks, not inside one: a chunk cut by the
                    # budget raises, while one never started costs nothing.
                    result.reason = "budget"
                    break
                state = await repo.ensure(shop_id)
                end = state.history_earliest_date or (today - timedelta(days=fast_days()))
                if end <= floor:
                    await _finish_history(run, reason="max_lookback")
                    result.done, result.reason = True, "max_lookback"
                    break
                start = max(end - timedelta(days=window), floor)
                analytics = await _analytics_range(
                    run,
                    rate_limiter=rate_limiter,
                    handoff_fn=handoff_fn,
                    sleep=sleep,
                    deadline=deadline,
                    start=start,
                    end_exclusive=end,
                    concurrency=concurrency,
                    out_of_range_is_end=True,
                    stage="history",
                )
                result.detail_calls += analytics.detail_calls
                if analytics.out_of_range:
                    if (end - start).days > 1:
                        window = max(1, (end - start).days // 2)
                        continue
                    await _finish_history(run, reason="out_of_range")
                    result.done, result.reason = True, "out_of_range"
                    break
                if not analytics.complete:
                    # Not recorded: a chunk whose calls were refused must be
                    # fetched again, not skipped over.
                    result.reason = "incomplete_chunk"
                    logger.warning(
                        "shop_history_chunk_incomplete",
                        extra={
                            "shop_id": str(shop_id),
                            "start_date_ge": start.isoformat(),
                            "end_date_lt": end.isoformat(),
                            "rate_limited": analytics.rate_limited,
                            "list_failed": analytics.list_failed,
                        },
                    )
                    break
                state = await repo.record_history_chunk(
                    shop_id, earliest_date=start, had_data=analytics.has_data
                )
                await session.commit()
                chunks_left -= 1
                window = span
                result.chunks.append((start, end))
                log_transition(
                    "shop_history_chunk_done",
                    state,
                    shop_id=shop_id,
                    start_date_ge=start.isoformat(),
                    end_date_lt=end.isoformat(),
                    had_data=analytics.has_data,
                    detail_calls=analytics.detail_calls,
                    chunks_done=state.history_chunks_done,
                )
                if state.history_empty_chunks >= stop_after_empty:
                    await _finish_history(run, reason="no_data")
                    result.done, result.reason = True, "no_data"
                    break
                if start <= floor:
                    await _finish_history(run, reason="max_lookback")
                    result.done, result.reason = True, "max_lookback"
                    break
        except Exception as exc:
            await _mark_failed(run, phase="history", error=exc)
            raise

        state = await repo.ensure(shop_id)
        result.earliest_date = state.history_earliest_date
        return result


async def _finish_history(run: _ShopRun, *, reason: str) -> None:
    state, written = await run.state_repo.stamp_once(
        run.shop_id, "history_done_at", status=BOOTSTRAP_HISTORY_DONE
    )
    await run.session.commit()
    if written:
        log_transition(
            "shop_history_done",
            state,
            shop_id=run.shop_id,
            reason=reason,
            earliest_date=(
                state.history_earliest_date.isoformat() if state.history_earliest_date else None
            ),
            chunks_done=state.history_chunks_done,
        )


# -- scheduled cycle --------------------------------------------------------


@dataclass
class ShopCycleResult:
    shop_id: uuid.UUID
    needs_bootstrap: bool = False
    history_done: bool = False
    analytics_ran: bool = False
    analytics_skip_reason: str | None = None
    analytics: AnalyticsRangeResult | None = None
    cards: int | None = None
    outcomes: list[SyncOutcome] = field(default_factory=list)
    #: P14-C cost data read this cycle (never fails the cycle).
    order_costs: OrderCostsResult | None = None


async def run_shop_cycle(
    *,
    session: AsyncSession,
    config: FujiwaPollConfig,
    shop_id: uuid.UUID,
    rate_limiter: RateLimiter,
    handoff_fn: HandoffFn,
    resolve_credential: ResolveCredentialFn | None = None,
    factory: ProductionReadClientFactory | None = None,
    create_resources: CreateResourcesFn | None = None,
    sync_state_repo: TikTokSyncStateRepo | None = None,
    sleep: SleepFn = asyncio.sleep,
    score_fn: ScoreFn | None = None,
    now: datetime | None = None,
    concurrency: int | None = None,
) -> ShopCycleResult:
    """One scheduled cycle for one shop. See the module docstring."""
    # Before resolve, as in `_resolve_and_poll`: the resolve is cycle work.
    deadline = _CycleDeadline()
    today = utc_today(now)

    async with _scoped_shop_run(
        session=session,
        config=config,
        shop_id=shop_id,
        resolve_credential=resolve_credential,
        factory=factory,
        create_resources=create_resources,
        sync_state_repo=sync_state_repo,
    ) as run:
        result = ShopCycleResult(shop_id=shop_id)
        state = await run.state_repo.find(shop_id)
        if state is None or state.fast_done_at is None:
            result.needs_bootstrap = True
            return result
        result.history_done = state.history_done_at is not None

        outcomes = result.outcomes
        new_days = False
        try:
            await _run_commerce_steps(
                run,
                rate_limiter=rate_limiter,
                handoff_fn=handoff_fn,
                sleep=sleep,
                deadline=deadline,
                outcomes=outcomes,
            )
            new_days = await _daily_analytics(
                run,
                state=state,
                result=result,
                rate_limiter=rate_limiter,
                handoff_fn=handoff_fn,
                sleep=sleep,
                deadline=deadline,
                today=today,
                concurrency=concurrency,
            )
        except PollStepDroppedRowsError as exc:
            outcomes.append(exc.outcome)
            await _save_partial(run, outcomes)
            raise
        except Exception:
            await _save_partial(run, outcomes)
            raise

        await _record_cycle(
            run.sync_state_repo, shop_id, sync_state=run.sync_state, outcomes=outcomes
        )
        await session.commit()
        _assert_cycle_succeeded(outcomes, shop_id=shop_id)
        # P14-C (D24.13): a few orders' price detail / finance transactions,
        # read-only, after the orders were just synced. Never fails the cycle.
        result.order_costs = await sync_order_costs(
            session=session,
            shop_id=shop_id,
            resources=run.resources,
            rate_limiter=rate_limiter,
            app_id=run.app_id,
            shop_key=run.shop_key,
            deadline=deadline,
            now=now,
            sleep=sleep,
        )
        if new_days:
            # D11: scoring once a day, after the analytics pass.
            result.cards = await _score(run, score_fn, phase="daily")
        return result


async def _daily_analytics(
    run: _ShopRun,
    *,
    state: ShopIngestionState,
    result: ShopCycleResult,
    rate_limiter: RateLimiter,
    handoff_fn: HandoffFn,
    sleep: SleepFn,
    deadline: _CycleDeadline,
    today: date,
    concurrency: int | None,
) -> bool:
    """At most one analytics fetch per shop per UTC day (SPEC §3.3).

    Returns True when new days landed (so the caller re-scores).
    """
    shop_id = run.shop_id
    if state.analytics_last_run_on is not None and state.analytics_last_run_on >= today:
        result.analytics_skip_reason = "already_ran_today"
        logger.info(
            "shop_analytics_daily_skipped",
            extra={"shop_id": str(shop_id), "reason": "already_ran_today"},
        )
        return False

    latest = await _probe_latest(
        run, rate_limiter=rate_limiter, sleep=sleep, deadline=deadline, today=today
    )
    target = latest or (today - timedelta(days=1))
    last = state.analytics_through_date or await max_stored_analytics_day(run.session, shop_id)
    if last is None:
        last = target - timedelta(days=fast_days())
    if target <= last:
        # Nothing new: zero detail calls. The gate is NOT closed for the day --
        # TikTok publishes yesterday at an unknown hour, and the next cycle's
        # probe is one call, not a detail fan-out.
        result.analytics_skip_reason = "nothing_new"
        await run.state_repo.update(shop_id, latest_available_date=latest)
        logger.info(
            "shop_analytics_daily_skipped",
            extra={
                "shop_id": str(shop_id),
                "reason": "nothing_new",
                "latest_available_date": latest.isoformat() if latest else None,
                "through_date": last.isoformat(),
            },
        )
        return False

    start = last + timedelta(days=1)
    end = target + timedelta(days=1)
    analytics = await _analytics_range(
        run,
        rate_limiter=rate_limiter,
        handoff_fn=handoff_fn,
        sleep=sleep,
        deadline=deadline,
        start=start,
        end_exclusive=end,
        concurrency=concurrency,
        include_per_day_extras=True,
    )
    result.analytics = analytics
    result.analytics_ran = True
    result.outcomes.append(analytics.outcome)

    landed = [date.fromisoformat(d) for d in analytics.days_with_rows]
    new_through = max([last, *landed]) if analytics.complete else last
    closed = analytics.complete and new_through >= target
    await run.state_repo.update(
        shop_id,
        analytics_through_date=new_through,
        latest_available_date=latest,
        analytics_last_run_on=today if closed else state.analytics_last_run_on,
    )
    logger.info(
        "shop_analytics_daily_synced",
        extra={
            "shop_id": str(shop_id),
            "start_date_ge": start.isoformat(),
            "end_date_lt": end.isoformat(),
            "through_date": new_through.isoformat(),
            "detail_calls": analytics.detail_calls,
            "complete": analytics.complete,
        },
    )
    return new_through > last


# -- fan-out enumeration ----------------------------------------------------


@dataclass(frozen=True)
class PollableShop:
    shop_id: uuid.UUID
    fast_done: bool


async def enumerate_pollable_shops(session: AsyncSession) -> list[PollableShop]:
    """Every active shop holding a usable read credential, and its bootstrap verdict.

    The one cross-tenant read on this path, through migration 074's SECURITY
    DEFINER function on Postgres (ADR-089 decision 3). It returns identifiers
    and one boolean only; each per-shop task re-reads its own credential under
    its own shop scope. SQLite (unit tests) has neither the function nor RLS,
    so it runs the same predicate as a plain query.
    """
    capabilities = [capability.value for capability in READ_CAPABILITIES]
    if session.get_bind().dialect.name == "postgresql":
        from sqlalchemy import text

        rows = await session.execute(
            text(
                "SELECT out_shop_id, out_fast_done "
                "FROM public.enumerate_pollable_shops(:capabilities, :excluded)"
            ).bindparams(capabilities=capabilities, excluded=SANDBOX_AUTH_ID or "")
        )
        return [PollableShop(shop_id=row[0], fast_done=bool(row[1])) for row in rows.all()]

    credential_exists = (
        select(TikTokCredential.id)
        .where(
            TikTokCredential.shop_id == Shop.id,
            TikTokCredential.capability.in_(capabilities),
            TikTokCredential.status != "needs_reauth",
            TikTokCredential.merchant_authorization_id.is_not(None),
            TikTokCredential.merchant_authorization_id != (SANDBOX_AUTH_ID or ""),
        )
        .exists()
    )
    stmt = (
        select(Shop.id, ShopIngestionState.fast_done_at)
        .outerjoin(ShopIngestionState, ShopIngestionState.shop_id == Shop.id)
        .where(Shop.is_active.is_not(False), credential_exists)
        .order_by(Shop.id)
    )
    listed = (await session.execute(stmt)).all()
    return [PollableShop(shop_id=row[0], fast_done=row[1] is not None) for row in listed]


__all__ = [
    "FastPhaseResult",
    "HistoryResult",
    "PollableShop",
    "ShopCycleResult",
    "bootstrap_budget_seconds",
    "enumerate_pollable_shops",
    "fast_days",
    "history_budget_seconds",
    "history_chunk_days",
    "history_max_lookback_days",
    "log_transition",
    "max_stored_analytics_day",
    "run_bootstrap_fast_phase",
    "run_history_chunks",
    "run_shop_cycle",
]
