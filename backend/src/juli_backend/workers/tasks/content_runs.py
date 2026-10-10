"""Hourly content-runs poll (fast track P14-E, contract ``p14-content-cards.md`` §2, §4).

``juli_backend.content_runs_poll`` (beat, minute 41): for every pollable shop
(the poll fan-out's own SECURITY DEFINER enumeration), under that shop's own
tenant scope, look at its content runs:

- waiting for the video / the LIVE → auto-detect it on TikTok, mark the run
  published and enqueue ``resume_lever_flow`` (the run confirms and starts
  measuring);
- measuring → take the day-7 / day-14 video readings, or the next-3-sessions
  LIVE readings, into the run's content state.

Read-only on TikTok, no model call. A shop without such runs costs one query
and no TikTok request. One shop's failure never stops the others.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field

from juli_backend.workers.celery_app import celery_app
from juli_backend.workers.tasks.database import get_async_database_url

logger = logging.getLogger(__name__)

CONTENT_RUNS_POLL_TASK = "juli_backend.content_runs_poll"


@dataclass
class ContentPollSummary:
    shops: int = 0
    detected: list[uuid.UUID] = field(default_factory=list)
    measured: int = 0
    failed_shops: int = 0


def _enqueue_resume(run_id: uuid.UUID) -> None:
    from juli_backend.workers.tasks import agent_workflow

    try:
        agent_workflow.resume_lever_flow.delay(str(run_id))
    except Exception:
        logger.error(
            "content_run_resume_enqueue_failed", extra={"run_id": str(run_id)}, exc_info=True
        )


async def _production_resources(session, shop_id):
    """The shop's guarded read resources (``composition.build_read_resources``)."""
    from juli_backend.services.agent import composition

    return await composition.build_read_resources(session, shop_id=shop_id)


async def run_content_runs_poll(
    session_factory, *, enqueue=_enqueue_resume, resources_for=_production_resources
) -> ContentPollSummary:
    """One poll over every pollable shop (module docstring)."""
    from juli_backend.database.tenant_context import with_sticky_shop_scope
    from juli_backend.services.content_cards import poll as content_poll
    from juli_backend.workers.services.polling.ingestion import enumerate_pollable_shops

    summary = ContentPollSummary()
    async with session_factory() as session:
        shops = await enumerate_pollable_shops(session)
    for shop in shops:
        async with session_factory() as session:
            try:
                async with with_sticky_shop_scope(session, shop.shop_id):
                    if not await content_poll.has_pollable_runs(session, shop.shop_id):
                        continue
                    summary.shops += 1
                    resources = await resources_for(session, shop.shop_id)
                    # TikTok reads are blocking calls; this task owns its event loop.
                    report = await content_poll.poll_shop(session, shop.shop_id, resources)
                    await session.commit()
            except Exception:
                summary.failed_shops += 1
                logger.warning(
                    "content_runs_poll_shop_failed",
                    extra={"shop_id": str(shop.shop_id)},
                    exc_info=True,
                )
                continue
        summary.detected += report.detected
        summary.measured += len(report.measured)
        for run_id in report.detected:
            enqueue(run_id)
    logger.info(
        "content_runs_poll_complete",
        extra={
            "shops": summary.shops,
            "detected": len(summary.detected),
            "measured": summary.measured,
            "failed_shops": summary.failed_shops,
        },
    )
    return summary


@celery_app.task(name=CONTENT_RUNS_POLL_TASK)
def content_runs_poll() -> None:
    """Celery beat entry: one hourly poll (see module docstring)."""
    from juli_backend.database.database import ensure_worker_session_factory

    factory = ensure_worker_session_factory(get_async_database_url())
    asyncio.run(run_content_runs_poll(factory))


__all__ = [
    "CONTENT_RUNS_POLL_TASK",
    "ContentPollSummary",
    "content_runs_poll",
    "run_content_runs_poll",
]
