"""Celery tasks: product history, promotions, external changes, baselines (fast track P23).

All on the default queue (they read TikTok briefly and write a few rows).

``juli_backend.product_history_fanout`` (beat, daily 20:53 UTC = 03:53 UTC+7)
    One ``product_history_daily`` per connected shop past its fast phase.
``juli_backend.product_history_daily``
    ``reconcile_products`` then ``sweep_promotions`` for one shop
    (``services/product_history/job.py``). One per shop at a time (Redis lock
    ``ingest:product_history:{shop}``, skipped when held). The first run is the
    shop's full product baseline and its one-time promotion backfill.
``juli_backend.product_history_refresh_product`` / ``..._refresh_activity``
    Enqueued by webhooks 15 / 16 / 18 and 63 / 39 (``services/product_history/webhooks.py``):
    one Get Product / Get Activity and the change recording. ``rate_limit`` caps
    the worker's pace; each read also takes a token from the shared per-shop window.
``juli_backend.product_history_replay_webhooks``
    One-off: replays the stored raw deliveries of those types (``replay.py``).
``juli_backend.capture_run_baseline``
    Enqueued by the approve route after its commit: the run's ``approval`` baseline.

Every body logs and returns on failure instead of raising (tomorrow's run, or
the reconciliation, catches up).
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from juli_backend.workers.celery_app import celery_app
from juli_backend.workers.tasks.database import get_async_database_url

logger = logging.getLogger(__name__)

FANOUT_TASK = "juli_backend.product_history_fanout"
DAILY_TASK = "juli_backend.product_history_daily"
REFRESH_PRODUCT_TASK = "juli_backend.product_history_refresh_product"
REFRESH_ACTIVITY_TASK = "juli_backend.product_history_refresh_activity"
REPLAY_TASK = "juli_backend.product_history_replay_webhooks"
BASELINE_TASK = "juli_backend.capture_run_baseline"
LOCK_NAME = "product_history"
DAILY_BUDGET_SECONDS = 1500.0
REFRESH_BUDGET_SECONDS = 120.0
_LOCK_TTL_SECONDS = int(DAILY_BUDGET_SECONDS) + 300

SessionFactory = Callable[[], Any]


# -- bodies (collaborators injected; tests call these) ---------------------------------------


async def run_fanout(
    session: Any,
    *,
    enqueue: Callable[[str], Any],
    enumerate_fn: Callable[[Any], Awaitable[list[Any]]] | None = None,
) -> int:
    """One daily run per pollable shop past its fast phase. Returns the enqueued count."""
    from juli_backend.workers.services.polling.ingestion import enumerate_pollable_shops

    shops = await (enumerate_fn or enumerate_pollable_shops)(session)
    enqueued = 0
    for shop in shops:
        if not shop.fast_done:
            continue
        try:
            enqueue(str(shop.shop_id))
            enqueued += 1
        except Exception:
            logger.error(
                "product_history_fanout_enqueue_failed",
                extra={"shop_id": str(shop.shop_id)},
                exc_info=True,
            )
    logger.info("product_history_fanout", extra={"shops": len(shops), "enqueued": enqueued})
    return enqueued


async def _resources(
    session_factory: SessionFactory,
    shop_id: uuid.UUID,
    *,
    app_key: str,
    app_secret: str,
    resolve: Any = None,
    create_resources: Any = None,
    rate_limiter: Any = None,
) -> Any:
    from juli_backend.services.product_history.job import build_resources, plan_reads

    plan = await plan_reads(
        session_factory, shop_id, app_key=app_key, app_secret=app_secret, resolve=resolve
    )
    return build_resources(
        plan, app_key=app_key, create_resources=create_resources, rate_limiter=rate_limiter
    )


async def run_daily(
    shop_id: str,
    *,
    session_factory: SessionFactory,
    app_key: str,
    app_secret: str,
    lock: Any | None = None,
    resolve: Any = None,
    create_resources: Any = None,
    rate_limiter: Any = None,
    now: datetime | None = None,
    backoff_sleep: Callable[[float], Any] | None = None,
) -> dict[str, Any] | None:
    """Products then promotions for one shop; ``None`` when locked or failed."""
    from juli_backend.services.product_history.job import reconcile_products, sweep_promotions

    token: str | None = None
    if lock is not None:
        token = lock.try_acquire(shop_id, LOCK_NAME, ttl_seconds=_LOCK_TTL_SECONDS)
        if token is None:
            logger.info("product_history_skipped_locked", extra={"shop_id": shop_id})
            return None
    shop_uuid = uuid.UUID(shop_id)
    extra: dict[str, Any] = {} if backoff_sleep is None else {"backoff_sleep": backoff_sleep}
    out: dict[str, Any] = {}
    try:
        resources = await _resources(
            session_factory,
            shop_uuid,
            app_key=app_key,
            app_secret=app_secret,
            resolve=resolve,
            create_resources=create_resources,
            rate_limiter=rate_limiter,
        )
        try:
            out["products"] = (
                await reconcile_products(session_factory, shop_uuid, resources, now=now, **extra)
            ).__dict__
        except Exception as exc:
            _log_failure("product_history_products_failed", shop_id, exc)
        try:
            out["promotions"] = (
                await sweep_promotions(session_factory, shop_uuid, resources, now=now, **extra)
            ).__dict__
        except Exception as exc:
            _log_failure("product_history_promotions_failed", shop_id, exc)
        return out
    except Exception as exc:
        _log_failure("product_history_daily_failed", shop_id, exc)
        return None
    finally:
        if lock is not None and token is not None:
            lock.release(shop_id, LOCK_NAME, token)


async def run_refresh_product(
    shop_id: str,
    product_id: str,
    source: str,
    hint_kind: str | None,
    hint_fields: list[str] | None,
    *,
    session_factory: SessionFactory,
    app_key: str,
    app_secret: str,
    resolve: Any = None,
    create_resources: Any = None,
    rate_limiter: Any = None,
    now: datetime | None = None,
) -> int:
    from juli_backend.models.history import KIND_CONTENT
    from juli_backend.services.product_history.job import refresh_product

    try:
        shop_uuid = uuid.UUID(shop_id)
        resources = await _resources(
            session_factory,
            shop_uuid,
            app_key=app_key,
            app_secret=app_secret,
            resolve=resolve,
            create_resources=create_resources,
            rate_limiter=rate_limiter,
        )
        return await refresh_product(
            session_factory,
            shop_uuid,
            resources,
            product_id=product_id,
            source=source,
            hint_kind=hint_kind or KIND_CONTENT,
            hint_fields=hint_fields or [],
            now=now,
        )
    except Exception as exc:
        _log_failure("product_history_refresh_product_failed", shop_id, exc)
        return 0


async def run_refresh_activity(
    shop_id: str,
    change: dict[str, Any],
    source: str,
    *,
    session_factory: SessionFactory,
    app_key: str,
    app_secret: str,
    resolve: Any = None,
    create_resources: Any = None,
    rate_limiter: Any = None,
    now: datetime | None = None,
) -> int:
    from juli_backend.services.product_history.job import refresh_activity
    from juli_backend.services.product_history.promotions import ActivityChange

    try:
        shop_uuid = uuid.UUID(shop_id)
        resources = await _resources(
            session_factory,
            shop_uuid,
            app_key=app_key,
            app_secret=app_secret,
            resolve=resolve,
            create_resources=create_resources,
            rate_limiter=rate_limiter,
        )
        return await refresh_activity(
            session_factory,
            shop_uuid,
            resources,
            change=ActivityChange.from_json(change),
            source=source,
            now=now,
        )
    except Exception as exc:
        _log_failure("product_history_refresh_activity_failed", shop_id, exc)
        return 0


async def run_capture_baseline(
    shop_id: str,
    run_id: str,
    phase: str,
    captured_at: str | None,
    *,
    session_factory: SessionFactory,
) -> bool:
    """Capture one run baseline under the shop's scope; True when a row was stored."""
    from juli_backend.database.tenant_context import with_shop_scope
    from juli_backend.services.product_history.baselines import capture_for_run

    shop_uuid = uuid.UUID(shop_id)
    try:
        async with session_factory() as session:
            async with with_shop_scope(session, shop_uuid):
                row = await capture_for_run(
                    session,
                    shop_id=shop_uuid,
                    workflow_run_id=uuid.UUID(run_id),
                    phase=phase,
                    now=datetime.fromisoformat(captured_at) if captured_at else None,
                )
            await session.commit()
        return row is not None
    except Exception as exc:
        _log_failure("run_baseline_task_failed", shop_id, exc)
        return False


def enqueue_run_baseline(
    shop_id: uuid.UUID, run_id: uuid.UUID, phase: str, captured_at: datetime
) -> str | None:
    """Enqueue one baseline capture; never raises (the approval already committed)."""
    try:
        return capture_run_baseline_task.delay(
            str(shop_id), str(run_id), phase, captured_at.isoformat()
        ).id
    except Exception:
        logger.error(
            "run_baseline_enqueue_failed",
            extra={"shop_id": str(shop_id), "run_id": str(run_id), "phase": phase},
            exc_info=True,
        )
        return None


def _log_failure(event: str, shop_id: str, exc: BaseException) -> None:
    logger.error(
        event,
        extra={
            "shop_id": shop_id,
            "error_type": type(exc).__name__,
            "error_message": str(exc)[:200],
        },
        exc_info=True,
    )


# -- Celery wrappers -------------------------------------------------------------------------


def _env() -> tuple[str, str, str] | None:
    app_key = os.getenv("TIKTOK_APP_KEY", "").strip()
    app_secret = os.getenv("TIKTOK_APP_SECRET", "").strip()
    redis_url = os.getenv("REDIS_URL", "").strip()
    if not (app_key and app_secret and redis_url):
        return None
    return app_key, app_secret, redis_url


def _factory() -> SessionFactory:
    from juli_backend.database.database import ensure_worker_session_factory

    return ensure_worker_session_factory(get_async_database_url())


def _run(coro: Awaitable[Any], *, timeout: float, event: str, **extra: Any) -> Any:
    async def bounded() -> Any:
        return await asyncio.wait_for(coro, timeout=timeout)

    try:
        return asyncio.run(bounded())
    except TimeoutError:
        logger.error(event, extra={"timeout_seconds": timeout, **extra})
        return None


@celery_app.task(name=FANOUT_TASK)
def product_history_fanout() -> int:
    async def go() -> int:
        async with _factory()() as session:
            return await run_fanout(session, enqueue=lambda sid: product_history_daily.delay(sid))

    return int(_run(go(), timeout=120.0, event="product_history_fanout_timeout") or 0)


@celery_app.task(name=DAILY_TASK)
def product_history_daily(shop_id: str) -> None:
    env = _env()
    if env is None:
        logger.info("product_history_skipped", extra={"shop_id": shop_id, "reason": "env"})
        return
    app_key, app_secret, redis_url = env

    async def go() -> Any:
        import redis

        from juli_backend.services.shop_diagnosis_daily import shared_rate_limiter
        from juli_backend.workers.services.polling.shop_lock import RedisShopIngestLock

        client = redis.from_url(redis_url)
        return await run_daily(
            shop_id,
            session_factory=_factory(),
            app_key=app_key,
            app_secret=app_secret,
            lock=RedisShopIngestLock(client),
            rate_limiter=shared_rate_limiter(client),
        )

    _run(go(), timeout=DAILY_BUDGET_SECONDS, event="product_history_timeout", shop_id=shop_id)


@celery_app.task(name=REFRESH_PRODUCT_TASK, rate_limit="30/m")
def product_history_refresh_product(
    shop_id: str,
    product_id: str,
    source: str,
    hint_kind: str | None = None,
    hint_fields: list[str] | None = None,
) -> None:
    env = _env()
    if env is None:
        return
    app_key, app_secret, redis_url = env

    async def go() -> Any:
        import redis

        from juli_backend.services.shop_diagnosis_daily import shared_rate_limiter

        return await run_refresh_product(
            shop_id,
            product_id,
            source,
            hint_kind,
            hint_fields,
            session_factory=_factory(),
            app_key=app_key,
            app_secret=app_secret,
            rate_limiter=shared_rate_limiter(redis.from_url(redis_url)),
        )

    _run(go(), timeout=REFRESH_BUDGET_SECONDS, event="product_history_timeout", shop_id=shop_id)


@celery_app.task(name=REFRESH_ACTIVITY_TASK, rate_limit="30/m")
def product_history_refresh_activity(shop_id: str, change: dict[str, Any], source: str) -> None:
    env = _env()
    if env is None:
        return
    app_key, app_secret, redis_url = env

    async def go() -> Any:
        import redis

        from juli_backend.services.shop_diagnosis_daily import shared_rate_limiter

        return await run_refresh_activity(
            shop_id,
            change,
            source,
            session_factory=_factory(),
            app_key=app_key,
            app_secret=app_secret,
            rate_limiter=shared_rate_limiter(redis.from_url(redis_url)),
        )

    _run(go(), timeout=REFRESH_BUDGET_SECONDS, event="product_history_timeout", shop_id=shop_id)


@celery_app.task(name=REPLAY_TASK)
def product_history_replay_webhooks(since: str | None = None, limit: int = 5000) -> dict:
    """One-off: ``celery call juli_backend.product_history_replay_webhooks``."""
    from juli_backend.services.product_history.replay import replay_raw_events

    async def go() -> dict:
        async with _factory()() as session:
            result = await replay_raw_events(
                session,
                since=datetime.fromisoformat(since) if since else None,
                limit=limit,
            )
            await session.commit()
            return dict(result.__dict__)

    return _run(go(), timeout=600.0, event="product_history_replay_timeout") or {}


@celery_app.task(name=BASELINE_TASK)
def capture_run_baseline_task(
    shop_id: str, run_id: str, phase: str, captured_at: str | None = None
) -> bool:
    return bool(
        _run(
            run_capture_baseline(shop_id, run_id, phase, captured_at, session_factory=_factory()),
            timeout=60.0,
            event="run_baseline_timeout",
            shop_id=shop_id,
        )
    )


__all__ = [
    "BASELINE_TASK",
    "DAILY_TASK",
    "FANOUT_TASK",
    "REFRESH_ACTIVITY_TASK",
    "REFRESH_PRODUCT_TASK",
    "REPLAY_TASK",
    "capture_run_baseline_task",
    "enqueue_run_baseline",
    "product_history_daily",
    "product_history_fanout",
    "product_history_refresh_activity",
    "product_history_refresh_product",
    "product_history_replay_webhooks",
    "run_capture_baseline",
    "run_daily",
    "run_fanout",
    "run_refresh_activity",
    "run_refresh_product",
]
