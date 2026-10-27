"""Writers of ``llm_call_log`` rows for the OpenAI gate (ADR-116 §5, migration 105).

One row per call attempt, metadata only (:class:`CallLogEntry` has no field that could
hold a prompt or an output). A writer **never raises**: the log must not break the call
path it records, so a failure is logged as ``llm_call_log_write_failed`` and dropped --
inside a SAVEPOINT on Postgres, so the caller's transaction survives it (the pattern of
``services/card_events/writer.py``).

- :class:`SessionCallLog` -- the caller's ``AsyncSession`` (agent run, content drafting,
  content analysis); the row commits with the caller's transaction. The caller holds
  the shop's scope, so RLS accepts the row.
- :class:`SyncSessionCallLog` -- a sync ``Session`` (the agent's ledger session, for the
  synchronous image-inspection call); a SAVEPOINT, then committed at once, like the
  run's write-value recorder on the same session.
- :class:`MemoryCallLog` -- keeps entries in a list (tests, and nowhere else).
"""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass, field
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from juli_backend.models.llm_call_log import LLMCallLog

logger = logging.getLogger(__name__)

PROJECT_ENV = "OPENAI_PROJECT_LABEL"
#: The one OpenAI project the backend key belongs to (ADR-116 §5, D6 revised).
DEFAULT_PROJECT = "juli-client-data"


def project_label() -> str:
    """The ``project`` written on every row (``OPENAI_PROJECT_LABEL``, else the default)."""
    return (os.environ.get(PROJECT_ENV) or "").strip()[:64] or DEFAULT_PROJECT


@dataclass(frozen=True)
class CallLogEntry:
    """One call attempt. No prompt, no output -- by construction."""

    shop_id: uuid.UUID
    purpose: str
    model: str
    endpoint: str
    status: str
    project: str = field(default_factory=project_label)
    input_tokens: int = 0
    output_tokens: int = 0
    request_id: str | None = None
    refusal_reason: str | None = None

    def to_row(self) -> LLMCallLog:
        return LLMCallLog(
            shop_id=self.shop_id,
            purpose=self.purpose[:64],
            model=(self.model or "unknown")[:64],
            endpoint=self.endpoint[:64],
            project=self.project[:64],
            input_tokens=max(0, int(self.input_tokens)),
            output_tokens=max(0, int(self.output_tokens)),
            request_id=self.request_id[:128] if self.request_id else None,
            status=self.status,
            refusal_reason=self.refusal_reason[:64] if self.refusal_reason else None,
        )


class CallLogSink(Protocol):
    async def write(self, entry: CallLogEntry) -> None: ...


class SyncCallLogSink(Protocol):
    def write_sync(self, entry: CallLogEntry) -> None: ...


def _failed(entry: CallLogEntry, exc: BaseException) -> None:
    logger.warning(
        "llm_call_log_write_failed",
        extra={
            "shop_id": str(entry.shop_id),
            "purpose": entry.purpose,
            "status": entry.status,
            "error_type": type(exc).__name__,
        },
    )


class SessionCallLog:
    """Writes on the caller's async session, in its transaction (see module docstring)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def write(self, entry: CallLogEntry) -> None:
        try:
            if self._session.bind.dialect.name == "postgresql":
                async with self._session.begin_nested():
                    self._session.add(entry.to_row())
            else:
                self._session.add(entry.to_row())
                await self._session.flush()
        except Exception as exc:  # the log never breaks the call path
            _failed(entry, exc)


class SyncSessionCallLog:
    """Writes on a sync session and commits at once (see module docstring)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def write_sync(self, entry: CallLogEntry) -> None:
        # In a SAVEPOINT: a failed insert must not roll back whatever the ledger has
        # pending on this same session.
        try:
            if self._session.get_bind().dialect.name == "postgresql":
                with self._session.begin_nested():
                    self._session.add(entry.to_row())
            else:
                self._session.add(entry.to_row())
            self._session.commit()
        except Exception as exc:  # the log never breaks the call path
            _failed(entry, exc)


@dataclass
class MemoryCallLog:
    """Keeps entries in memory (tests)."""

    entries: list[CallLogEntry] = field(default_factory=list)

    async def write(self, entry: CallLogEntry) -> None:
        self.entries.append(entry)

    def write_sync(self, entry: CallLogEntry) -> None:
        self.entries.append(entry)


__all__ = [
    "DEFAULT_PROJECT",
    "PROJECT_ENV",
    "CallLogEntry",
    "CallLogSink",
    "MemoryCallLog",
    "SessionCallLog",
    "SyncCallLogSink",
    "SyncSessionCallLog",
    "project_label",
]
