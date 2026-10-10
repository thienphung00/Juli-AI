"""Celery tasks for per-shop ingestion (fast track P1-B, SPEC §3.1–3.2).

Four tasks, replacing the single-merchant ``fujiwa-poll-cycle`` beat entry:

``juli_backend.shop_poll_fanout``       (beat, every 15 min at :07/:22/:37/:52)
    Enumerates every active shop with a usable read credential -- the
    production merchant and ``SELLER_CONNECT`` shops alike -- and enqueues one
    task per shop: ``poll_shop`` when its fast phase is done, ``bootstrap_shop``
    otherwise. A shop whose cycle lock is held is skipped for this tick.

``juli_backend.bootstrap_shop``         (queue ``ingest_priority``)
    The fast phase. Enqueued by the OAuth callback after its commit, or by the
    fan-out. Enqueues the history phase when it finishes.

``juli_backend.shop_history_backfill``  (queue ``ingest_backfill``)
    Some history chunks per run, then re-enqueues itself until 60 days exist
    (fast track P17, D25.12; ``SHOP_HISTORY_CONNECT_DAYS``). Beyond that,
    ``nightly=True`` runs from the ``shop-history-extend`` beat read a few
    small chunks a night up to the look-back (180 days).

``juli_backend.shop_history_extend``    (beat, nightly 19:43 UTC = 02:43 UTC+7)
    Enqueues one nightly history run per shop whose walk is not done.

``juli_backend.shop_quick_scan``        (queue ``ingest_priority``, P17 / D26)
    Enqueued by ``bootstrap_shop`` as it starts; 1-3 quick cards in parallel
    with the fast phase (``workers/tasks/shop_quick_scan.py``).

``juli_backend.poll_shop``              (default queue)
    One scheduled cycle for one shop (commerce every time, analytics at most
    once a day).

PER-SHOP MUTEX. ``bootstrap_shop`` and ``poll_shop`` take the shop's ``cycle``
lock (Redis ``SET NX EX``, owner-token release) and skip -- never wait -- when
another holder has it, so two cycles for one shop never overlap and a long cold
start is never stacked under. History takes its own ``history`` lock. The lock
TTL is the task's outer timeout plus grace, so a killed worker frees the shop.

ENQUEUE DE-DUPLICATION. ``bootstrap_queued`` / ``history_queued`` markers
(same lock store, TTL-bounded) stop a backed-up queue from accumulating one
copy per tick; the task releases its marker when it starts.

TENANT SCOPE. These wrappers read nothing tenant-scoped themselves: the fan-out
enumerates through migration 074's definer function, and each per-shop run
enters ``with_sticky_shop_scope`` for its own shop inside
``workers/services/polling/ingestion.py``.

TIMEOUTS. Each task's outer ``asyncio.wait_for`` is a backstop on the inner
wall-clock budget (``_CycleDeadline``) plus ``_OUTER_TIMEOUT_GRACE_SECONDS``,
the shape ``fujiwa_poll_beat`` uses (#2033).
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.workers.celery_app import celery_app
from juli_backend.workers.tasks.database import get_async_database_url
from juli_backend.workers.tasks.shop_diagnosis import enqueue_shop_diagnosis
from juli_backend.workers.tasks.shop_quick_scan import enqueue_quick_scan

logger = logging.getLogger(__name__)

QUEUE_PRIORITY = "ingest_priority"
QUEUE_BACKFILL = "ingest_backfill"

BOOTSTRAP_TASK = "juli_backend.bootstrap_shop"
HISTORY_TASK = "juli_backend.shop_history_backfill"
POLL_SHOP_TASK = "juli_backend.poll_shop"
FANOUT_TASK = "juli_backend.shop_poll_fanout"
HISTORY_EXTEND_TASK = "juli_backend.shop_history_extend"

#: History runs whose stop is deliberate: no immediate re-enqueue (P17).
_HISTORY_PARKED_REASONS = frozenset({"fast_not_done", "connect_window_done", "already_extended"})

_OUTER_TIMEOUT_GRACE_SECONDS = 60.0
_LOCK_GRACE_SECONDS = 60
#: How long an enqueue marker survives a lost message.
_MARKER_TTL_SECONDS = 2 * 3600
#: Delay before retrying a history chunk that was rate-limited or whose list
#: call failed transiently.
_HISTORY_RETRY_COUNTDOWN_SECONDS = 300

Collaborators = Callable[[AsyncSession], Awaitable[dict[str, Any]]]
SessionFactory = Callable[[], Any]


def _env_ready() -> dict[str, str] | None:
    values = {
        "app_key": os.getenv("TIKTOK_APP_KEY", "").strip(),
        "app_secret": os.getenv("TIKTOK_APP_SECRET", "").strip(),
        "redirect_uri": os.getenv("TIKTOK_REDIRECT_URI", "").strip(),
        "redis_url": os.getenv("REDIS_URL", "").strip(),
    }
    if not all(values.values()):
        return None
    return values


def _session_factory() -> SessionFactory:
    from juli_backend.database.database import ensure_worker_session_factory

    return ensure_worker_session_factory(get_async_database_url())


def _redis_lock(env: dict[str, str]) -> Any:
    import redis

    from juli_backend.workers.services.polling.shop_lock import RedisShopIngestLock

    return RedisShopIngestLock(redis.from_url(env["redis_url"]))


def _production_collaborators(env: dict[str, str]) -> Collaborators:
    """Fresh ETL handoff + rate limiter + config per run, as `fujiwa_poll_beat` builds them."""

    async def build(session: AsyncSession) -> dict[str, Any]:
        from juli_backend.services.etl import EtlConsumer
        from juli_backend.services.ingestion import make_etl_handoff
        from juli_backend.services.tiktok import build_fujiwa_poll_vendor_resources
        from juli_backend.workers.services.polling import FujiwaPollConfig

        async def _dlq_handoff(channel: str, shop_key: str, payload: bytes) -> None:
            logger.error(
                "shop_ingestion_etl_dlq",
                extra={"channel": channel, "shop_key": shop_key, "payload_bytes": len(payload)},
            )

        consumer = EtlConsumer(session=session, dlq_handoff=_dlq_handoff)
        _oauth_service, rate_limiter = build_fujiwa_poll_vendor_resources(
            session,
            app_key=env["app_key"],
            app_secret=env["app_secret"],
            redirect_uri=env["redirect_uri"],
            redis_url=env["redis_url"],
        )
        return {
            "config": FujiwaPollConfig(app_key=env["app_key"], app_secret=env["app_secret"]),
            "rate_limiter": rate_limiter,
            "handoff_fn": make_etl_handoff(consumer),
        }

    return build


async def score_and_persist_cards(session: AsyncSession, shop_id: uuid.UUID) -> list[Any]:
    """The existing scoring + card persistence for one shop, with no poll (SPEC §3.1).

    `run_action_card_refresh(poll=False)`: score -> persist -> commit ->
    emission budget, exactly as the manual refresh runs it after its poll.
    """
    from juli_backend.services.action_cards import run_action_card_refresh

    return await run_action_card_refresh(session, shop_id, poll=False)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).replace(tzinfo=None)
    except ValueError:
        return None


# -- enqueue helpers ----------------------------------------------------------


def enqueue_bootstrap(
    shop_id: str,
    *,
    connect_committed_at: str | None = None,
    enqueued_at: str | None = None,
    marker_token: str | None = None,
) -> str:
    async_result = bootstrap_shop.apply_async(
        args=[shop_id],
        kwargs={
            "connect_committed_at": connect_committed_at,
            "enqueued_at": enqueued_at,
            "marker_token": marker_token,
        },
        queue=QUEUE_PRIORITY,
    )
    return async_result.id


def enqueue_history(
    shop_id: str, *, marker_token: str | None, countdown: int = 0, nightly: bool = False
) -> str:
    async_result = shop_history_backfill.apply_async(
        args=[shop_id],
        kwargs={"marker_token": marker_token, "nightly": nightly},
        queue=QUEUE_BACKFILL,
        countdown=countdown or None,
    )
    return async_result.id


def enqueue_poll_shop(shop_id: str) -> str:
    return poll_shop.delay(shop_id).id


@dataclass
class Enqueuers:
    """The enqueue calls, injectable so tests never touch a broker."""

    bootstrap: Callable[..., str] = enqueue_bootstrap
    history: Callable[..., str] = enqueue_history
    poll: Callable[[str], str] = enqueue_poll_shop
    #: P7-A: the ADR-108 shop diagnosis report (``workers/tasks/shop_diagnosis.py``).
    diagnosis: Callable[[str], str | None] = enqueue_shop_diagnosis
    #: P17 (D26): the quick scan (``workers/tasks/shop_quick_scan.py``).
    quick_scan: Callable[[str], str | None] = enqueue_quick_scan


def _now_iso() -> str:
    from juli_backend.repositories import utc_now_naive

    return utc_now_naive().isoformat()


def _marked_enqueue(
    lock: Any,
    shop_id: str,
    marker: str,
    enqueue: Callable[[str | None], str | None],
) -> str | None:
    """Enqueue once per marker lifetime. Returns the task id, or None if skipped/failed."""
    token = lock.try_acquire(shop_id, marker, ttl_seconds=_MARKER_TTL_SECONDS)
    if token is None:
        logger.info(
            "shop_ingestion_enqueue_deduplicated", extra={"shop_id": shop_id, "marker": marker}
        )
        return None
    try:
        return enqueue(token)
    except Exception:
        lock.release(shop_id, marker, token)
        logger.error(
            "shop_ingestion_enqueue_failed",
            extra={"shop_id": shop_id, "marker": marker},
            exc_info=True,
        )
        return None


def maybe_enqueue_history(
    lock: Any, shop_id: str, enqueuers: Enqueuers, *, countdown: int = 0, nightly: bool = False
) -> str | None:
    if nightly:
        return _marked_enqueue(
            lock,
            shop_id,
            "history_queued",
            lambda token: enqueuers.history(
                shop_id, marker_token=token, countdown=countdown, nightly=True
            ),
        )
    return _marked_enqueue(
        lock,
        shop_id,
        "history_queued",
        lambda token: enqueuers.history(shop_id, marker_token=token, countdown=countdown),
    )


def maybe_enqueue_quick_scan(lock: Any, shop_id: str, enqueuers: Enqueuers) -> str | None:
    """P17 (D26): the quick scan, once per marker lifetime; the scan itself runs once."""
    from juli_backend.services.onboarding.quick_scan import enabled

    if not enabled():
        return None
    task_id = _marked_enqueue(
        lock, shop_id, "quick_scan_queued", lambda _token: enqueuers.quick_scan(shop_id)
    )
    if task_id is not None:
        logger.info("shop_quick_scan_enqueued", extra={"shop_id": shop_id, "task_id": task_id})
    return task_id


def maybe_enqueue_diagnosis(shop_id: str, enqueuers: Enqueuers, *, after: str) -> str | None:
    """Fast track P7-A: rebuild the shop's diagnosis report. Never raises.

    The build is its own task (idempotent per shop and report end date), so a
    failure there -- or here -- never touches the poll cycle.
    """
    try:
        task_id = enqueuers.diagnosis(shop_id)
    except Exception:
        logger.error(
            "shop_diagnosis_enqueue_failed",
            extra={"shop_id": shop_id, "after": after},
            exc_info=True,
        )
        return None
    logger.info(
        "shop_diagnosis_enqueued", extra={"shop_id": shop_id, "after": after, "task_id": task_id}
    )
    return task_id


def maybe_enqueue_bootstrap(lock: Any, shop_id: str, enqueuers: Enqueuers) -> str | None:
    enqueued_at = _now_iso()
    task_id = _marked_enqueue(
        lock,
        shop_id,
        "bootstrap_queued",
        lambda token: enqueuers.bootstrap(shop_id, enqueued_at=enqueued_at, marker_token=token),
    )
    if task_id is not None:
        logger.info(
            "shop_bootstrap_enqueued",
            extra={"shop_id": shop_id, "task_id": task_id, "at": enqueued_at, "by": "fanout"},
        )
    return task_id


# -- the four task bodies -----------------------------------------------------


@dataclass
class FanoutSummary:
    shops: int = 0
    cycles: int = 0
    bootstraps: int = 0
    skipped_locked: int = 0
    deduplicated: int = 0
    shop_ids: list[str] = field(default_factory=list)


async def run_fanout(
    session: AsyncSession,
    *,
    lock: Any,
    enqueuers: Enqueuers,
    enumerate_fn: Callable[[AsyncSession], Awaitable[list[Any]]] | None = None,
) -> FanoutSummary:
    """One beat tick: one enqueue per pollable shop (AC-1.5)."""
    from juli_backend.workers.services.polling.ingestion import enumerate_pollable_shops

    enumerate_shops = enumerate_fn or enumerate_pollable_shops
    shops = await enumerate_shops(session)
    summary = FanoutSummary(shops=len(shops))
    for shop in shops:
        shop_id = str(shop.shop_id)
        summary.shop_ids.append(shop_id)
        if lock.is_held(shop_id, "cycle"):
            summary.skipped_locked += 1
            logger.info("shop_poll_fanout_skipped_locked", extra={"shop_id": shop_id})
            continue
        try:
            if shop.fast_done:
                enqueuers.poll(shop_id)
                summary.cycles += 1
            elif maybe_enqueue_bootstrap(lock, shop_id, enqueuers) is not None:
                summary.bootstraps += 1
            else:
                summary.deduplicated += 1
        except Exception:
            # One shop's broker hiccup must not starve the rest of the fleet.
            logger.error(
                "shop_poll_fanout_enqueue_failed", extra={"shop_id": shop_id}, exc_info=True
            )
    logger.info(
        "shop_poll_fanout_summary",
        extra={
            "shops": summary.shops,
            "cycles": summary.cycles,
            "bootstraps": summary.bootstraps,
            "skipped_locked": summary.skipped_locked,
            "deduplicated": summary.deduplicated,
        },
    )
    return summary


async def _with_cycle_lock(
    lock: Any,
    shop_id: str,
    name: str,
    ttl_seconds: int,
    body: Callable[[], Awaitable[Any]],
) -> tuple[bool, Any]:
    token = lock.try_acquire(shop_id, name, ttl_seconds=ttl_seconds)
    if token is None:
        logger.info("shop_ingestion_skipped_locked", extra={"shop_id": shop_id, "lock": name})
        return False, None
    try:
        return True, await body()
    finally:
        lock.release(shop_id, name, token)


async def run_bootstrap_task(
    shop_id: str,
    *,
    session_factory: SessionFactory,
    lock: Any,
    collaborators: Collaborators,
    enqueuers: Enqueuers,
    connect_committed_at: str | None = None,
    enqueued_at: str | None = None,
    marker_token: str | None = None,
    fast_fn: Callable[..., Awaitable[Any]] | None = None,
    run_kwargs: dict[str, Any] | None = None,
) -> Any:
    from juli_backend.workers.services.polling.ingestion import (
        bootstrap_budget_seconds,
        run_bootstrap_fast_phase,
    )

    if marker_token:
        lock.release(shop_id, "bootstrap_queued", marker_token)
    # P17 (D26): the quick scan runs beside the fast phase, in another worker.
    maybe_enqueue_quick_scan(lock, shop_id, enqueuers)
    fast = fast_fn or run_bootstrap_fast_phase
    ttl = int(bootstrap_budget_seconds() + _OUTER_TIMEOUT_GRACE_SECONDS) + _LOCK_GRACE_SECONDS

    async def body() -> Any:
        async with session_factory() as session:
            kwargs = {"score_fn": score_and_persist_cards, **await collaborators(session)}
            kwargs.update(run_kwargs or {})
            result = await fast(
                session=session,
                shop_id=uuid.UUID(shop_id),
                connect_committed_at=_parse_dt(connect_committed_at),
                enqueued_at=_parse_dt(enqueued_at),
                **kwargs,
            )
            await session.commit()
            return result

    ran, result = await _with_cycle_lock(lock, shop_id, "cycle", ttl, body)
    if ran and result is not None:
        # Fast phase finished now, or had already: either way the history
        # phase is next. De-duplicated, so a re-run never stacks a second one.
        maybe_enqueue_history(lock, shop_id, enqueuers)
        if not getattr(result, "skipped", False):
            maybe_enqueue_diagnosis(shop_id, enqueuers, after="bootstrap_fast")
    return result


async def run_history_task(
    shop_id: str,
    *,
    session_factory: SessionFactory,
    lock: Any,
    collaborators: Collaborators,
    enqueuers: Enqueuers,
    marker_token: str | None = None,
    history_fn: Callable[..., Awaitable[Any]] | None = None,
    run_kwargs: dict[str, Any] | None = None,
    nightly: bool = False,
    now: datetime | None = None,
) -> Any:
    """History chunks for one shop.

    P17 (D25.12): after connect, stop at ``SHOP_HISTORY_CONNECT_DAYS`` (60) and
    re-enqueue until then; ``nightly`` reads ``SHOP_HISTORY_NIGHTLY_CHUNKS`` ×
    ``SHOP_HISTORY_NIGHTLY_CHUNK_DAYS`` once per local day and never
    re-enqueues (the next night continues).
    """
    from juli_backend.services.onboarding.history import (
        connect_days,
        nightly_chunk_days,
        nightly_chunks,
    )
    from juli_backend.workers.services.polling.ingestion import (
        history_budget_seconds,
        run_history_chunks,
    )

    if nightly:
        from juli_backend.services.action_cards.emission_budget import shop_day

        moment = now or datetime.now(UTC)
        mode: dict[str, Any] = {
            "chunk_days": nightly_chunk_days(),
            "max_chunks": nightly_chunks(),
            "once_on": shop_day(moment),
        }
    else:
        mode = {"stop_at_days": connect_days()}

    if marker_token:
        lock.release(shop_id, "history_queued", marker_token)
    history = history_fn or run_history_chunks
    ttl = int(history_budget_seconds() + _OUTER_TIMEOUT_GRACE_SECONDS) + _LOCK_GRACE_SECONDS

    async def body() -> Any:
        async with session_factory() as session:
            kwargs = await collaborators(session)
            result = await history(
                session=session,
                shop_id=uuid.UUID(shop_id),
                **kwargs,
                **{**mode, **(run_kwargs or {})},
            )
            await session.commit()
            return result

    ran, result = await _with_cycle_lock(lock, shop_id, "history", ttl, body)
    if (
        ran
        and result is not None
        and not nightly
        and not result.done
        and result.reason not in _HISTORY_PARKED_REASONS
    ):
        countdown = _HISTORY_RETRY_COUNTDOWN_SECONDS if result.reason == "incomplete_chunk" else 0
        maybe_enqueue_history(lock, shop_id, enqueuers, countdown=countdown)
    return result


async def run_poll_shop_task(
    shop_id: str,
    *,
    session_factory: SessionFactory,
    lock: Any,
    collaborators: Collaborators,
    enqueuers: Enqueuers,
    cycle_fn: Callable[..., Awaitable[Any]] | None = None,
    run_kwargs: dict[str, Any] | None = None,
) -> Any:
    from juli_backend.workers.services.polling.ingestion import run_shop_cycle
    from juli_backend.workers.services.polling.orchestrate import cycle_budget_seconds

    cycle = cycle_fn or run_shop_cycle
    ttl = int(cycle_budget_seconds() + _OUTER_TIMEOUT_GRACE_SECONDS) + _LOCK_GRACE_SECONDS

    async def body() -> Any:
        async with session_factory() as session:
            kwargs = {"score_fn": score_and_persist_cards, **await collaborators(session)}
            kwargs.update(run_kwargs or {})
            result = await cycle(session=session, shop_id=uuid.UUID(shop_id), **kwargs)
            await session.commit()
            return result

    ran, result = await _with_cycle_lock(lock, shop_id, "cycle", ttl, body)
    if not ran or result is None:
        return result
    if getattr(result, "analytics_ran", False):
        maybe_enqueue_diagnosis(shop_id, enqueuers, after="daily_analytics")
    if result.needs_bootstrap:
        maybe_enqueue_bootstrap(lock, shop_id, enqueuers)
    elif (
        not result.history_done
        and getattr(result, "history_connect_pending", False)
        and not lock.is_held(shop_id, "history")
    ):
        # Keeps the post-connect history chain alive across a lost message or a
        # worker restart, until its 60 days exist (P17: beyond that, only the
        # nightly beat extends it); the marker makes this a no-op while queued.
        maybe_enqueue_history(lock, shop_id, enqueuers)
    return result


async def run_history_extend_fanout(
    session: AsyncSession,
    *,
    lock: Any,
    enqueuers: Enqueuers,
    enumerate_fn: Callable[[AsyncSession], Awaitable[list[Any]]] | None = None,
) -> int:
    """Nightly beat (P17, D25.12): one ``nightly`` history run per shop past its fast phase.

    The run itself skips a shop whose walk is done or that already ran today;
    the ``history_queued`` marker skips one whose history run is queued.
    """
    from juli_backend.workers.services.polling.ingestion import enumerate_pollable_shops

    enumerate_shops = enumerate_fn or enumerate_pollable_shops
    shops = await enumerate_shops(session)
    enqueued = 0
    for shop in shops:
        if not shop.fast_done:
            continue
        shop_id = str(shop.shop_id)
        if lock.is_held(shop_id, "history"):
            continue
        try:
            if maybe_enqueue_history(lock, shop_id, enqueuers, nightly=True) is not None:
                enqueued += 1
        except Exception:
            logger.error(
                "shop_history_extend_enqueue_failed", extra={"shop_id": shop_id}, exc_info=True
            )
    logger.info("shop_history_extend_fanout", extra={"shops": len(shops), "enqueued": enqueued})
    return enqueued


# -- Celery wrappers ----------------------------------------------------------


def _run(coro_factory: Callable[[], Awaitable[Any]], *, timeout: float, event: str, **extra: Any):
    try:
        return asyncio.run(asyncio.wait_for(coro_factory(), timeout=timeout))
    except TimeoutError:
        logger.error(f"{event}_timeout", extra={"timeout_seconds": timeout, **extra})
        raise
    except Exception as exc:
        logger.error(
            f"{event}_failed",
            extra={"error_type": type(exc).__name__, "error_message": str(exc)[:200], **extra},
            exc_info=True,
        )
        raise


def _skip_if_unconfigured(event: str, **extra: Any) -> dict[str, str] | None:
    env = _env_ready()
    if env is None:
        logger.info(f"{event}_skipped", extra={"reason": "missing_tiktok_or_redis_env", **extra})
    return env


@celery_app.task(name=FANOUT_TASK)
def shop_poll_fanout() -> None:
    """Beat: enqueue one poll (or bootstrap) per connected shop."""
    env = _skip_if_unconfigured("shop_poll_fanout")
    if env is None:
        return

    async def go() -> None:
        factory = _session_factory()
        async with factory() as session:
            await run_fanout(session, lock=_redis_lock(env), enqueuers=Enqueuers())

    _run(go, timeout=300.0, event="shop_poll_fanout")


@celery_app.task(name=BOOTSTRAP_TASK)
def bootstrap_shop(
    shop_id: str,
    connect_committed_at: str | None = None,
    enqueued_at: str | None = None,
    marker_token: str | None = None,
) -> None:
    """Fast phase for one shop (high-priority queue)."""
    from juli_backend.workers.services.polling.ingestion import bootstrap_budget_seconds

    env = _skip_if_unconfigured("bootstrap_shop", shop_id=shop_id)
    if env is None:
        return

    async def go() -> None:
        await run_bootstrap_task(
            shop_id,
            session_factory=_session_factory(),
            lock=_redis_lock(env),
            collaborators=_production_collaborators(env),
            enqueuers=Enqueuers(),
            connect_committed_at=connect_committed_at,
            enqueued_at=enqueued_at,
            marker_token=marker_token,
        )

    _run(
        go,
        timeout=bootstrap_budget_seconds() + _OUTER_TIMEOUT_GRACE_SECONDS,
        event="bootstrap_shop",
        shop_id=shop_id,
    )


@celery_app.task(name=HISTORY_EXTEND_TASK)
def shop_history_extend() -> None:
    """Beat: the nightly history extension to 180 days (P17, D25.12)."""
    env = _skip_if_unconfigured("shop_history_extend")
    if env is None:
        return

    async def go() -> None:
        factory = _session_factory()
        async with factory() as session:
            await run_history_extend_fanout(session, lock=_redis_lock(env), enqueuers=Enqueuers())

    _run(go, timeout=300.0, event="shop_history_extend")


@celery_app.task(name=HISTORY_TASK)
def shop_history_backfill(
    shop_id: str, marker_token: str | None = None, nightly: bool = False
) -> None:
    """History phase chunks for one shop (low-priority queue)."""
    from juli_backend.workers.services.polling.ingestion import history_budget_seconds

    env = _skip_if_unconfigured("shop_history_backfill", shop_id=shop_id)
    if env is None:
        return

    async def go() -> None:
        await run_history_task(
            shop_id,
            session_factory=_session_factory(),
            lock=_redis_lock(env),
            collaborators=_production_collaborators(env),
            enqueuers=Enqueuers(),
            marker_token=marker_token,
            nightly=nightly,
        )

    _run(
        go,
        timeout=history_budget_seconds() + _OUTER_TIMEOUT_GRACE_SECONDS,
        event="shop_history_backfill",
        shop_id=shop_id,
    )


@celery_app.task(name=POLL_SHOP_TASK)
def poll_shop(shop_id: str) -> None:
    """One scheduled cycle for one shop."""
    from juli_backend.workers.services.polling.orchestrate import cycle_budget_seconds

    env = _skip_if_unconfigured("poll_shop", shop_id=shop_id)
    if env is None:
        return

    async def go() -> None:
        await run_poll_shop_task(
            shop_id,
            session_factory=_session_factory(),
            lock=_redis_lock(env),
            collaborators=_production_collaborators(env),
            enqueuers=Enqueuers(),
        )

    _run(
        go,
        timeout=cycle_budget_seconds() + _OUTER_TIMEOUT_GRACE_SECONDS,
        event="poll_shop",
        shop_id=shop_id,
    )


__all__ = [
    "BOOTSTRAP_TASK",
    "FANOUT_TASK",
    "HISTORY_EXTEND_TASK",
    "HISTORY_TASK",
    "POLL_SHOP_TASK",
    "QUEUE_BACKFILL",
    "QUEUE_PRIORITY",
    "Enqueuers",
    "FanoutSummary",
    "bootstrap_shop",
    "enqueue_bootstrap",
    "maybe_enqueue_bootstrap",
    "maybe_enqueue_diagnosis",
    "maybe_enqueue_history",
    "maybe_enqueue_quick_scan",
    "poll_shop",
    "run_bootstrap_task",
    "run_fanout",
    "run_history_extend_fanout",
    "run_history_task",
    "run_poll_shop_task",
    "score_and_persist_cards",
    "shop_history_backfill",
    "shop_history_extend",
    "shop_poll_fanout",
]
