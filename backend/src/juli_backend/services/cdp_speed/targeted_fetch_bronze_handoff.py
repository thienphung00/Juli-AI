"""Bronze append handoff for targeted Partner fetch rows (#627)."""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.services.etl import (
    append_targeted_ctor_payload,
    append_targeted_live_hours_payload,
    append_targeted_order_payload,
    append_targeted_return_payload,
)
from juli_backend.services.ingestion.handoff import HandoffFn

logger = logging.getLogger(__name__)


@dataclass
class BronzeAppendTracker:
    """Bronze rows appended during one Shared Compute bronze stage."""

    order_row_ids: list[uuid.UUID] = field(default_factory=list)
    return_row_ids: list[uuid.UUID] = field(default_factory=list)
    ctor_row_ids: list[uuid.UUID] = field(default_factory=list)
    live_hours_row_ids: list[uuid.UUID] = field(default_factory=list)

    @property
    def appended_count(self) -> int:
        return (
            len(self.order_row_ids)
            + len(self.return_row_ids)
            + len(self.ctor_row_ids)
            + len(self.live_hours_row_ids)
        )


def _order_source_event_id(job_token: str, payload: dict[str, Any]) -> str:
    order_id = str(payload.get("order_id") or payload.get("tiktok_order_id") or "")
    update_time = str(payload.get("update_time") or "")
    return f"{job_token}:orders:{order_id}:{update_time}"


def _return_source_event_id(job_token: str, payload: dict[str, Any]) -> str:
    return_id = str(payload.get("return_id") or payload.get("tiktok_return_id") or "")
    update_time = str(payload.get("update_time") or "")
    return f"{job_token}:returns:{return_id}:{update_time}"


def _ctor_source_event_id(job_token: str, payload: dict[str, Any]) -> str:
    product_id = str(payload.get("product_id") or "")
    snapshot_key = str(payload.get("snapshot_key") or "")
    return f"{job_token}:ctor:{product_id}:{snapshot_key}"


def _live_hours_source_event_id(job_token: str, payload: dict[str, Any]) -> str:
    live_id = str(payload.get("live_id") or "shop")
    snapshot_key = str(payload.get("snapshot_key") or "")
    return f"{job_token}:live_hours:{live_id}:{snapshot_key}"


def make_targeted_fetch_bronze_handoff(
    session: AsyncSession,
    *,
    shop_id: uuid.UUID,
    job_token: str,
    tracker: BronzeAppendTracker,
    clock: Callable[[], datetime] | None = None,
) -> HandoffFn:
    """Return a handoff that append-only writes Partner rows to bronze."""

    async def handoff(channel: str, shop_key: str, payload: bytes) -> None:
        # This used to read `del shop_key  # shop scope enforced by caller + shop_id`,
        # and that assumption is what broke. Every bronze table is RLS'd with
        # WITH CHECK (shop_id = app_current_shop_id()), so an append whose
        # connection has no `app.current_shop_id` is REFUSED, not merely
        # filtered:
        #
        #   InsufficientPrivilegeError: new row violates row-level security
        #   policy for table "order_raw_payloads"
        #
        # That is what mock_analytics_hourly_reconcile hit on every run after
        # the #1339 cutover moved the runtime off the table owner, which had
        # been RLS-exempt by virtue of ownership (#1627).
        #
        # The orchestrator DOES wrap its bronze stage in with_shop_scope, and
        # the scope is nonetheless absent by the time this flushes. The upstream
        # reason is not yet identified — ruled out so far: a commit inside the
        # fetch chain (there is none), a different session (it is the same one),
        # and nesting under NullPool (reproduces clean locally).
        #
        # So this asserts its own scope rather than trusting a caller several
        # frames up. `shop_id` is already bound here, so the boundary that
        # performs the write is also the one that establishes permission to.
        del shop_key  # the scope is asserted below from shop_id, not inferred
        try:
            data = json.loads(payload)
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
            logger.warning(
                "targeted_fetch_bronze_skip_unparseable",
                extra={"channel": channel, "correlation_id": job_token},
            )
            return
        if not isinstance(data, dict):
            return

        received_at = clock() if clock else datetime.now(tz=UTC)

        async with with_shop_scope(session, shop_id):
            await _append_for_channel(channel, data=data, received_at=received_at)

    async def _append_for_channel(
        channel: str,
        *,
        data: dict[str, Any],
        received_at: datetime,
    ) -> None:
        """The append itself. Split out so one scope covers every branch."""
        if channel == "tiktok.orders.raw":
            row_id = await append_targeted_order_payload(
                session,
                shop_id=shop_id,
                payload=data,
                received_at=received_at,
                source_event_id=_order_source_event_id(job_token, data),
            )
            if row_id is not None:
                tracker.order_row_ids.append(row_id)
            return

        if channel == "tiktok.returns.raw":
            row_id = await append_targeted_return_payload(
                session,
                shop_id=shop_id,
                payload=data,
                received_at=received_at,
                source_event_id=_return_source_event_id(job_token, data),
            )
            if row_id is not None:
                tracker.return_row_ids.append(row_id)
            return

        if channel == "tiktok.analytics.product.raw":
            row_id = await append_targeted_ctor_payload(
                session,
                shop_id=shop_id,
                payload=data,
                received_at=received_at,
                source_event_id=_ctor_source_event_id(job_token, data),
            )
            if row_id is not None:
                tracker.ctor_row_ids.append(row_id)
            return

        if channel == "tiktok.analytics.live.raw":
            row_id = await append_targeted_live_hours_payload(
                session,
                shop_id=shop_id,
                payload=data,
                received_at=received_at,
                source_event_id=_live_hours_source_event_id(job_token, data),
            )
            if row_id is not None:
                tracker.live_hours_row_ids.append(row_id)

    return handoff
