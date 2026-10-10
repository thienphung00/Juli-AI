"""Celery tasks of the content analysis (fast track P15), queue ``content_analysis``.

``juli_backend.analyze_content_upload(analysis_id, shop_id)``
    Enqueued by the upload route when the last byte arrives. Runs
    ``services.content_analysis.pipeline.analyze`` under the shop's sticky
    tenant scope.

    - IDEMPOTENT: a row already ``done`` / ``failed`` / ``refused`` /
      ``expired`` is left alone; only ``queued`` (or a ``processing`` row whose
      worker died) is run.
    - ONE PER SHOP AT A TIME: the per-shop Redis lock
      ``ingest:content_analysis:{shop_id}`` (``shop_lock.py``); a second upload of
      the same shop waits (task retry in 60 s), it never runs beside the first.
    - COST: every paid step checks the shop's monthly OpenAI cap first; over it
      the row ends ``refused`` with a Vietnamese message. The cost of every step
      is stored on the row as it is spent.
    - FILES: deleted when the analysis ends; a provider error keeps the file for
      the retry (at most ``MAX_ATTEMPTS`` runs), and ``content_analysis_sweep``
      removes anything older than 24 h.

``juli_backend.content_analysis_sweep`` (beat, hourly at minute 47)
    Deletes uploads and work directories older than 24 h from the upload
    directory -- filesystem only, no database, so it needs no shop scope.

Both run on the dedicated ``content_analysis`` queue (CPU-heavy ffmpeg work must
not hold the agent-run or ingest workers); ``infra/systemd/
juli-celery-worker.service`` consumes it.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from juli_backend.workers.celery_app import celery_app
from juli_backend.workers.tasks.database import get_async_database_url

logger = logging.getLogger(__name__)

ANALYZE_TASK = "juli_backend.analyze_content_upload"
SWEEP_TASK = "juli_backend.content_analysis_sweep"
QUEUE = "content_analysis"
LOCK_NAME = "content_analysis"
#: A LIVE (3 h, ≤ 60 min scanned) stays well under; a dead worker frees the shop then.
LOCK_TTL_SECONDS = 2 * 3600
MAX_ATTEMPTS = 3
LOCKED_RETRY_S = 60
PROVIDER_RETRY_S = 120

OUTCOME_DONE = "done"
OUTCOME_FAILED = "failed"
OUTCOME_REFUSED = "refused"
OUTCOME_RETRY = "retry"
OUTCOME_LOCKED = "locked"
OUTCOME_SKIPPED = "skipped"


def production_collaborators() -> Any:
    from juli_backend.services import content_analysis as ca

    conf = ca.settings()
    return ca.Collaborators(
        transcriber=ca.OpenAITranscriber(conf.asr_model),
        vision=ca.OpenAIVision(conf.vision_model),
        scorer=ca.OpenAIScorer(conf.scoring_model),
        product_reader=ca.TikTokProductReader(),
    )


def enqueue_analysis(analysis_id: uuid.UUID, shop_id: uuid.UUID) -> str | None:
    """Enqueue one analysis; never raises (the row stays ``queued``, see DEBT)."""
    try:
        return analyze_content_upload.delay(str(analysis_id), str(shop_id)).id
    except Exception:
        logger.error(
            "content_analysis_enqueue_failed",
            extra={"analysis_id": str(analysis_id), "shop_id": str(shop_id)},
            exc_info=True,
        )
        return None


async def run_analysis(
    analysis_id: str,
    shop_id: str,
    *,
    session_factory: Any,
    lock: Any,
    collaborators: Callable[[], Any] = production_collaborators,
    conf: Any | None = None,
) -> str:
    """Task body (module docstring). Returns the outcome."""
    from juli_backend.database.tenant_context import with_sticky_shop_scope
    from juli_backend.models.content_analysis import ContentAnalysis
    from juli_backend.services import content_analysis as ca

    costs, pipeline, ProviderError = ca.costs, ca.pipeline, ca.ProviderError
    conf = conf or ca.settings()
    token = lock.try_acquire(shop_id, LOCK_NAME, ttl_seconds=LOCK_TTL_SECONDS)
    if token is None:
        logger.info("content_analysis_locked", extra={"shop_id": shop_id})
        return OUTCOME_LOCKED
    shop_uuid = uuid.UUID(shop_id)
    outcome = OUTCOME_SKIPPED
    try:
        async with session_factory() as session:
            async with with_sticky_shop_scope(session, shop_uuid):
                row = await session.get(ContentAnalysis, uuid.UUID(analysis_id))
                if row is None or row.shop_id != shop_uuid:
                    return OUTCOME_SKIPPED
                if row.status not in (pipeline.STATUS_QUEUED, pipeline.STATUS_PROCESSING):
                    return OUTCOME_SKIPPED
                row.status = pipeline.STATUS_PROCESSING
                row.attempts = int(row.attempts or 0) + 1
                row.started_at = datetime.now(UTC).replace(tzinfo=None)
                row.error_code = None
                row.error_message = None
                await session.commit()
                rules = await ca.seller_rules(session, shop_uuid)
                try:
                    await pipeline.analyze(
                        session, row, collab=collaborators(), conf=conf, rules=rules
                    )
                    outcome = OUTCOME_DONE
                except costs.CostCapExceeded as exc:
                    pipeline.refuse(row, conf, exc)
                    outcome = OUTCOME_REFUSED
                except pipeline.AnalysisFailed as exc:
                    pipeline.fail(row, conf, exc.code)
                    outcome = OUTCOME_FAILED
                except Exception as exc:
                    transient = isinstance(exc, ProviderError)
                    logger.warning(
                        "content_analysis_error",
                        extra={
                            "analysis_id": analysis_id,
                            "shop_id": shop_id,
                            "error": type(exc).__name__,
                            "attempt": row.attempts,
                        },
                        exc_info=not transient,
                    )
                    if row.attempts >= MAX_ATTEMPTS:
                        pipeline.fail(row, conf, "provider_final")
                        outcome = OUTCOME_FAILED
                    else:
                        row.status = pipeline.STATUS_QUEUED
                        row.error_code = "provider"
                        row.error_message = pipeline.ERROR_VI["provider"]
                        outcome = OUTCOME_RETRY
                await session.commit()
                logger.info(
                    "content_analysis_finished",
                    extra={
                        "analysis_id": analysis_id,
                        "shop_id": shop_id,
                        "kind": row.kind,
                        "outcome": outcome,
                        "cost_usd": float(row.cost_usd or 0),
                        "duration_s": row.duration_s,
                        "usage": row.usage,
                    },
                )
    finally:
        lock.release(shop_id, LOCK_NAME, token)
    return outcome


def _redis_lock() -> Any:
    from juli_backend.workers.services.polling.shop_lock import (
        InMemoryShopIngestLock,
        RedisShopIngestLock,
    )

    redis_url = os.getenv("REDIS_URL", "").strip()
    if not redis_url:
        # Single-process dev only: the worker unit always has REDIS_URL.
        return InMemoryShopIngestLock()
    import redis

    return RedisShopIngestLock(redis.from_url(redis_url))


@celery_app.task(
    name=ANALYZE_TASK, bind=True, max_retries=60, acks_late=True, reject_on_worker_lost=False
)
def analyze_content_upload(self: Any, analysis_id: str, shop_id: str) -> str:
    from juli_backend.database.database import ensure_worker_session_factory

    factory = ensure_worker_session_factory(get_async_database_url())
    outcome = asyncio.run(
        run_analysis(analysis_id, shop_id, session_factory=factory, lock=_redis_lock())
    )
    if outcome == OUTCOME_LOCKED:
        raise self.retry(countdown=LOCKED_RETRY_S)
    if outcome == OUTCOME_RETRY:
        raise self.retry(countdown=PROVIDER_RETRY_S)
    return outcome


@celery_app.task(name=SWEEP_TASK)
def content_analysis_sweep() -> int:
    from juli_backend.services import content_analysis as ca

    removed = ca.storage.sweep(ca.settings())
    logger.info("content_analysis_sweep", extra={"removed": removed})
    return removed


__all__ = [
    "ANALYZE_TASK",
    "LOCK_NAME",
    "MAX_ATTEMPTS",
    "QUEUE",
    "SWEEP_TASK",
    "analyze_content_upload",
    "content_analysis_sweep",
    "enqueue_analysis",
    "production_collaborators",
    "run_analysis",
]
