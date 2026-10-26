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

from sqlalchemy import func, select
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
        """The one ``production_write_audit`` row of this mutation, else ``None``.

        A refusal row for the same run, product and tool (``authorization_id`` NULL,
        P61-F: a run that was refused once and then allowed) must not make the link
        ambiguous, so the ALLOWED rows (they name the spent authorization) are
        looked at first; only when there is not exactly one of those do all rows of
        the mutation decide."""
        base = (
            ProductionWriteAudit.shop_id == self._shop_id,
            ProductionWriteAudit.run_id == self._workflow_run_id,
            # ADR-116 §6 (migration 106): the per-platform id first, the old column as
            # the fallback for a row written before it.
            func.coalesce(
                ProductionWriteAudit.platform_product_id, ProductionWriteAudit.tiktok_product_id
            )
            == tiktok_product_id,
            ProductionWriteAudit.mutation_kind == tool_name,
        )
        for extra in ((ProductionWriteAudit.authorization_id.is_not(None),), ()):
            ids = list(
                self._session.execute(
                    select(ProductionWriteAudit.id).where(*base, *extra).limit(2)
                ).scalars()
            )
            if len(ids) == 1:
                return ids[0]
        return None


class SqlReadBackRefusalAudit:
    """ADR-116 §6 (D76): the ``production_write_audit`` row of a live write the executor
    refused because the shop no longer shows the approved "before" (``read_back_changed``).

    Same synchronous session and shop scope as :class:`SqlWriteValueRecorder`. Append-only
    (an INSERT; ``authorization_id`` NULL as for every refusal). Never raises: the refusal
    has already happened and nothing was written, so a failed audit is logged instead.
    """

    def __init__(self, session: Session, *, shop_id: uuid.UUID, workflow_run_id: uuid.UUID):
        self._session = session
        self._shop_id = shop_id
        self._workflow_run_id = workflow_run_id

    def __call__(self, *, tool_name: str, tiktok_product_id: str, fields: Sequence[str]) -> None:
        from juli_backend.models.models import WRITE_PLATFORM_TIKTOK
        from juli_backend.services.execution.production_write_resolver import (
            PreconditionName,
            _get_deployed_release_sha,
        )

        context = {
            "shop_id": str(self._shop_id),
            "run_id": str(self._workflow_run_id),
            "tool_name": tool_name,
            "fields": list(fields),
            "reason": PreconditionName.READ_BACK_CHANGED.value,
        }
        try:
            self._session.add(
                ProductionWriteAudit(
                    id=uuid.uuid4(),
                    run_id=self._workflow_run_id,
                    shop_id=self._shop_id,
                    tiktok_product_id=tiktok_product_id,
                    platform=WRITE_PLATFORM_TIKTOK,
                    platform_product_id=tiktok_product_id,
                    mutation_kind=tool_name,
                    authorization_id=None,
                    precondition_name=PreconditionName.READ_BACK_CHANGED.value,
                    release_sha=_get_deployed_release_sha(),
                )
            )
            self._session.commit()
        except Exception:  # an audit failure must not turn the refusal into a crash
            self._session.rollback()
            logger.exception("read_back_refusal_audit_failed", extra=context)
            return
        logger.warning("agent_production_write_refused", extra=context)
