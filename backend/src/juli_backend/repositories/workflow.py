"""Webhook intake and the tool-execution audit trail.

Two concerns share a theme -- *what arrived* and *what we did about it*:

* :class:`WebhookRawEventsRepo` and :class:`WorkflowWebhookSignalsRepo` record
  inbound deliveries (redacted HTTP audit rows, and durable workflow intents).
* :class:`ToolExecutionsRepo` and :class:`WorkflowOutcomeRecordsRepo` record
  the approved tool call and its measured outcome (MMU-6/7).
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime

from sqlalchemy import select

from juli_backend.database.exceptions import NotFound
from juli_backend.models.models import (
    ToolExecution,
    WebhookRawEvent,
    WorkflowOutcomeRecord,
    WorkflowWebhookSignal,
)
from juli_backend.repositories._base import SessionRepo


class WorkflowWebhookSignalsRepo(SessionRepo):
    """Durable workflow-intent records for Phase 2 catalog webhooks (#354)."""

    async def list_for_shop(self, shop_id: uuid.UUID) -> list[WorkflowWebhookSignal]:
        stmt = (
            select(WorkflowWebhookSignal)
            .where(WorkflowWebhookSignal.shop_id == shop_id)
            .order_by(WorkflowWebhookSignal.created_at)
        )
        return await self._all(stmt)

    async def record_if_new(
        self,
        *,
        shop_id: uuid.UUID,
        tiktok_shop_id: str,
        catalog_id: int,
        event_type: str,
        workflow_keys: list[str],
        intent: str,
        event_id: str,
        payload_json: str,
    ) -> bool:
        """Store the signal unless ``event_id`` was already seen. Returns whether it was stored."""
        already_seen = await self._exists(
            select(WorkflowWebhookSignal.id).where(WorkflowWebhookSignal.event_id == event_id)
        )
        if already_seen:
            return False
        await self._add(
            WorkflowWebhookSignal(
                shop_id=shop_id,
                tiktok_shop_id=tiktok_shop_id,
                catalog_id=catalog_id,
                event_type=event_type,
                workflow_keys=json.dumps(workflow_keys),
                intent=intent,
                event_id=event_id,
                payload=payload_json,
            )
        )
        return True


class WebhookRawEventsRepo(SessionRepo):
    """Redacted audit log of TikTok HTTP deliveries (#392).

    Domain raw payloads go to the bronze repos; this table keeps only what is
    needed to explain a delivery after the fact.
    """

    async def insert(
        self,
        *,
        tiktok_shop_id: str | None,
        event_type: str | None,
        event_id: str | None,
        signature_header: str | None,
        headers: str | None,
        raw_body: str | None,
        http_status: int,
        processing_status: str,
        parse_version: int = 1,
    ) -> WebhookRawEvent:
        return await self._add(
            WebhookRawEvent(
                tiktok_shop_id=tiktok_shop_id,
                event_type=event_type,
                event_id=event_id,
                signature_header=signature_header,
                headers=headers,
                raw_body=raw_body,
                http_status=http_status,
                processing_status=processing_status,
                parse_version=parse_version,
            )
        )


class ToolExecutionsRepo(SessionRepo):
    async def create(
        self,
        *,
        shop_id: uuid.UUID,
        approval_id: str,
        tool_name: str,
        payload_json: str,
        status: str,
        celery_task_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> ToolExecution:
        return await self._add(
            ToolExecution(
                shop_id=shop_id,
                approval_id=approval_id,
                tool_name=tool_name,
                payload_json=payload_json,
                status=status,
                celery_task_id=celery_task_id,
                idempotency_key=idempotency_key,
            )
        )

    async def get(self, shop_id: uuid.UUID, execution_id: uuid.UUID) -> ToolExecution:
        """Tenant-checked read: a foreign shop's execution reads as missing."""
        record = await self._session.get(ToolExecution, execution_id)
        if record is None or record.shop_id != shop_id:
            raise NotFound(f"ToolExecution {execution_id} not found")
        return record

    async def get_by_id(self, execution_id: uuid.UUID) -> ToolExecution:
        """Worker-side read with no tenant in hand; the Celery task carries only the id."""
        record = await self._session.get(ToolExecution, execution_id)
        if record is None:
            raise NotFound(f"ToolExecution {execution_id} not found")
        return record

    async def set_celery_task_id(
        self, shop_id: uuid.UUID, execution_id: uuid.UUID, celery_task_id: str
    ) -> ToolExecution:
        record = await self.get(shop_id, execution_id)
        record.celery_task_id = celery_task_id
        await self._session.flush()
        return record

    async def update_status(
        self,
        shop_id: uuid.UUID,
        execution_id: uuid.UUID,
        *,
        status: str,
        outcome_json: str | None = None,
        error_message: str | None = None,
        error_category: str | None = None,
    ) -> ToolExecution:
        """Advance ``status``; the optional fields are only written when supplied."""
        record = await self.get(shop_id, execution_id)
        record.status = status
        if outcome_json is not None:
            record.outcome_json = outcome_json
        if error_message is not None:
            record.error_message = error_message
        if error_category is not None:
            record.error_category = error_category
        await self._session.flush()
        return record


class WorkflowOutcomeRecordsRepo(SessionRepo):
    async def create(
        self,
        *,
        shop_id: uuid.UUID,
        approval_id: str,
        execution_id: uuid.UUID,
        workflow_id: str,
        execution_status: str,
        metrics_json: str,
        executed_at: datetime,
    ) -> WorkflowOutcomeRecord:
        return await self._add(
            WorkflowOutcomeRecord(
                shop_id=shop_id,
                approval_id=approval_id,
                execution_id=execution_id,
                workflow_id=workflow_id,
                execution_status=execution_status,
                metrics_json=metrics_json,
                executed_at=executed_at,
            )
        )

    async def get_by_approval_id(
        self, shop_id: uuid.UUID, approval_id: str
    ) -> WorkflowOutcomeRecord:
        record = await self._one_or_none(
            select(WorkflowOutcomeRecord).where(
                WorkflowOutcomeRecord.shop_id == shop_id,
                WorkflowOutcomeRecord.approval_id == approval_id,
            )
        )
        if record is None:
            raise NotFound(f"WorkflowOutcomeRecord for approval {approval_id} not found")
        return record

    async def get_by_execution_id(
        self, shop_id: uuid.UUID, execution_id: uuid.UUID
    ) -> WorkflowOutcomeRecord | None:
        return await self._one_or_none(
            select(WorkflowOutcomeRecord).where(
                WorkflowOutcomeRecord.shop_id == shop_id,
                WorkflowOutcomeRecord.execution_id == execution_id,
            )
        )


__all__ = [
    "ToolExecutionsRepo",
    "WebhookRawEventsRepo",
    "WorkflowOutcomeRecordsRepo",
    "WorkflowWebhookSignalsRepo",
]
