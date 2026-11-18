"""``POST /v1/ingest/connector-ticks`` -- the Juli Connector's scheduler tick (Connector 0.3.19).

What woke the Connector's reader schedule (pairing, a Chrome start, the daily alarm, the 06:30
stock read, a retry), how that tick ended (a run started, a run finished, or why nothing started)
and, for a finished run, how each Seller Centre report page went. Ops reads it from the audit log
(``system_connector_tick``, kind ``system``, 90-day retention) like the stop events next door
(``POST /v1/ingest/connector-events``), and the shop's Connector state keeps the version and,
for a daily run, its blocked pages (migration 131, read by the Thực hiện bar).

Metadata only: reader ids, short outcome notes (an endpoint and an HTTP status, never a body, an
order or a buyer). Ingest-token auth: the token names exactly one shop. A small hourly cap keeps a
stuck client from flooding the log (the Connector sends a finished run, and each distinct skip
once a day).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.api.routes.ingest import get_ingest_principal
from juli_backend.database import get_session
from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.repositories import utc_now_naive
from juli_backend.services import ingest as ingest_service
from juli_backend.services.ops import audit
from juli_backend.services.shopee_recommendations import connector_state

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ingest", tags=["ingest"])

#: The audit action of a Connector tick (``system_`` prefix: kind ``system``, 90-day retention).
ACTION_CONNECTOR_TICK = connector_state.ACTION_CONNECTOR_TICK
#: The Celery task that generates the shop's new cards (``workers/tasks/shopee_daily_cards``).
DAILY_CARDS_TASK = "juli_backend.shopee_daily_cards"
#: Ticks per shop per hour (a day has one run, one stock read and a few distinct skips).
TICKS_PER_HOUR = 30

_OUTCOME_KEY = re.compile(r"^[a-z_]{1,48}$")
_MAX_OUTCOMES = 40
_MAX_OUTCOME_LEN = 160


class ConnectorTick(BaseModel):
    """One scheduler tick: a finished run (``run``) or a start that did not happen (``skip``)."""

    model_config = ConfigDict(extra="forbid")

    platform: Literal["shopee", "tiktok"]
    kind: Literal["run", "skip"]
    trigger: Annotated[str, StringConstraints(pattern=r"^[a-z_]{1,32}$")]
    result: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.:\-]{1,80}$")]
    day: Annotated[str, StringConstraints(pattern=r"^\d{4}-\d{2}-\d{2}$")]
    occurred_at: datetime | None = None
    outcomes: dict[str, str] = Field(default_factory=dict)
    source_version: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9._+\-]{1,64}$")]

    @field_validator("outcomes")
    @classmethod
    def _outcomes_are_short_metadata(cls, value: dict[str, str]) -> dict[str, str]:
        if len(value) > _MAX_OUTCOMES:
            raise ValueError("too_many_outcomes")
        for key, outcome in value.items():
            if not _OUTCOME_KEY.match(key):
                raise ValueError("bad_outcome_key")
            if len(outcome) > _MAX_OUTCOME_LEN:
                raise ValueError("outcome_too_long")
        return value


def _enqueue_daily_cards(shop_id: Any) -> None:
    """The daily run reported in: new cards for that shop, in a worker (never in the request).
    A broker failure is logged and never fails the tick; the 02:03 UTC beat is the fallback."""
    try:
        from juli_backend.workers import celery_app

        celery_app.celery_app.send_task(DAILY_CARDS_TASK, args=[str(shop_id)])
    except Exception as exc:
        logger.error(
            "shopee_daily_cards_enqueue_failed",
            extra={"shop_id": str(shop_id), "error_type": type(exc).__name__},
        )


@router.post("/connector-ticks", status_code=status.HTTP_202_ACCEPTED)
async def post_connector_tick(
    tick: ConnectorTick,
    principal: ingest_service.IngestPrincipal = Depends(get_ingest_principal),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """The Connector's last tick: metadata for Ops (audit log), its version on the shop state."""
    if tick.platform != principal.platform:
        raise HTTPException(status_code=403, detail={"code": "platform_not_allowed"})
    decision = await ingest_service.get_ingest_rate_gate().hit(
        f"connector-tick:{principal.shop_id}", TICKS_PER_HOUR, 3600
    )
    if not decision.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"code": "rate_limited", "retry_after_seconds": decision.retry_after_seconds},
            headers={"Retry-After": str(decision.retry_after_seconds)},
        )
    now = utc_now_naive()
    async with with_shop_scope(session, principal.shop_id):
        await audit.record(
            session,
            audit.SYSTEM_ACTOR,
            ACTION_CONNECTOR_TICK,
            shop_id=principal.shop_id,
            after={
                "platform": tick.platform,
                "kind": tick.kind,
                "trigger": tick.trigger,
                "result": tick.result,
                "day": tick.day,
                "occurred_at": (tick.occurred_at or now).isoformat(),
                "outcomes": tick.outcomes,
                "source_version": tick.source_version,
            },
            at=now,
        )
        if tick.platform == "shopee" and tick.kind == "run":
            # Connector 0.3.22: the daily run's blocked pages replace the last ones; any other
            # run (a re-read, a stock run) merges into them. Skips leave them.
            await connector_state.record_reader_blocks(
                session,
                principal.shop_id,
                tick.outcomes,
                now=now,
                daily=tick.trigger == "daily",
                token_id=principal.token_id,
            )
        if tick.platform == "shopee":
            await connector_state.record_heartbeat(
                session,
                principal.shop_id,
                seller_centre_open=None,
                ack=None,
                now=now,
                version=tick.source_version,
                token_id=principal.token_id,
            )
    await session.commit()
    if tick.platform == "shopee" and tick.kind == "run" and tick.trigger == "daily":
        _enqueue_daily_cards(principal.shop_id)
    logger.info(
        "connector_tick",
        extra={
            "shop_id": str(principal.shop_id),
            "kind": tick.kind,
            "trigger": tick.trigger,
            "result": tick.result,
            "source_version": tick.source_version,
        },
    )
    return {"recorded": True}
