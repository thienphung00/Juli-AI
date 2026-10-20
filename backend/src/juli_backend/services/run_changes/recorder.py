"""The database-backed ``WriteValueRecorder`` (fast track P8-C).

Runs inside the worker, on the same synchronous session ``ToolExecutionLedger``
uses -- the one the task shell binds under the run's sticky shop scope, which is
what ``run_write_values``' INSERT policy checks. Called after the vendor write
succeeded, so it never raises: a failure is logged and the run goes on (see
``WriteValueRecorder``).

Idempotent per (run, tool call, field): a redelivered task replays the ledger's
stored result and calls the recorder again; the existing row wins.

P60-1b (ADR-107 amendment §6): each row also carries ``before_hash`` /
``after_hash`` (``product_history.normalize.field_value_hash``, the form
``product_snapshots`` hashes), ``before_read_at`` (the executor's before read)
and ``production_write_audit_id`` -- the audit row of this mutation when exactly
one matches (``run_id``, ``tiktok_product_id``, ``mutation_kind`` = tool name),
else NULL.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from juli_backend.models.models import ProductionWriteAudit
from juli_backend.models.run_changes import RunWriteValue
from juli_backend.services.agent.runner.write_capture import FieldWrite
from juli_backend.services.product_history.normalize import field_value_hash

logger = logging.getLogger(__name__)


class SqlWriteValueRecorder:
    """Writes one ``run_write_values`` row per changed field of one WRITE."""

    def __init__(self, session: Session, *, shop_id: uuid.UUID, workflow_run_id: uuid.UUID):
        self._session = session
        self._shop_id = shop_id
        self._workflow_run_id = workflow_run_id

    def record(
        self,
        *,
        tool_name: str,
        tool_call_id: str,
        tiktok_product_id: str,
        writes: Sequence[FieldWrite],
    ) -> None:
        context = {
            "shop_id": str(self._shop_id),
            "run_id": str(self._workflow_run_id),
            "tool_name": tool_name,
            "fields": [write.field for write in writes],
        }
        try:
            existing = set(
                self._session.execute(
                    select(RunWriteValue.field).where(
                        RunWriteValue.workflow_run_id == self._workflow_run_id,
                        RunWriteValue.tool_call_id == tool_call_id,
                    )
                ).scalars()
            )
            audit_id = self._audit_id(tool_name, tiktok_product_id)
            for write in writes:
                if write.field in existing:
                    continue
                self._session.add(
                    RunWriteValue(
                        shop_id=self._shop_id,
                        workflow_run_id=self._workflow_run_id,
                        tool_call_id=tool_call_id,
                        tool_name=tool_name,
                        tiktok_product_id=tiktok_product_id,
                        field=write.field,
                        before_value=write.before,
                        after_value=write.after,
                        after_source=write.after_source,
                        before_hash=field_value_hash(write.field, write.before),
                        after_hash=field_value_hash(write.field, write.after),
                        before_read_at=write.before_read_at,
                        production_write_audit_id=audit_id,
                    )
                )
            self._session.commit()
        except SQLAlchemyError:
            self._session.rollback()
            logger.exception("run_write_values_record_failed", extra=context)
            return
        logger.info("run_write_values_recorded", extra=context)

    def _audit_id(self, tool_name: str, tiktok_product_id: str) -> uuid.UUID | None:
        """The one ``production_write_audit`` row of this mutation, else ``None``."""
        ids = list(
            self._session.execute(
                select(ProductionWriteAudit.id)
                .where(
                    ProductionWriteAudit.shop_id == self._shop_id,
                    ProductionWriteAudit.run_id == self._workflow_run_id,
                    ProductionWriteAudit.tiktok_product_id == tiktok_product_id,
                    ProductionWriteAudit.mutation_kind == tool_name,
                )
                .limit(2)
            ).scalars()
        )
        return ids[0] if len(ids) == 1 else None
