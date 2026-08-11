"""Structured logging and request correlation (#902, ADR-061).

There was no logging configuration in this application at all, and the consequences were
worse than "logs are unstructured":

* The root logger had no handler, so Python's last-resort handler took over. It emits at
  WARNING and above only — every ``logger.info`` audit call site in the codebase was
  computed and then **discarded before it was written**. The intended audit trail
  produced nothing.
* Warnings and errors *were* emitted, but through that same fallback, which prints only
  ``record.getMessage()``. Every ``extra={...}`` payload — user, shop, error detail — was
  built and thrown away.
* Nothing carried a correlation identifier, so a customer report could not be tied to a
  server-side event.

This module is the floor: configure once, emit JSON to stdout so the host journal
captures it, and carry a correlation id on every record without changing a single
existing call site.

Vendor-free by design — the planned observability platform consumes this same stream,
so nothing here is throwaway.
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
import sys
import uuid
from typing import Any

CORRELATION_ID_HEADER = "X-Request-ID"

# contextvars, not threading.local: the request lifecycle is async, and a ContextVar is
# the only thing that survives an await without leaking between concurrent requests.
_correlation_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "juli_correlation_id", default=None
)

# The caller's address, bound per request alongside the correlation id (#905). Carried
# the same way and for the same reason: a security event is worthless if it cannot be
# attributed to a source, and plumbing an address parameter down through the webhook
# service, verifier and dispatcher would touch every signature on the path.
_client_address: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "juli_client_address", default=None
)

# Everything the stdlib puts on a LogRecord. Anything else came from `extra=` and is the
# structured context we exist to preserve. Derived from logging.LogRecord.__init__ plus
# the attributes Formatter adds; kept explicit so a new stdlib attribute shows up as an
# unexpected field rather than being silently swallowed.
_STANDARD_RECORD_ATTRS = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "message",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    }
)


def set_correlation_id(value: str | None) -> contextvars.Token[str | None]:
    return _correlation_id.set(value)


def reset_correlation_id(token: contextvars.Token[str | None]) -> None:
    _correlation_id.reset(token)


def get_correlation_id() -> str | None:
    return _correlation_id.get()


def set_client_address(value: str | None) -> contextvars.Token[str | None]:
    return _client_address.set(value)


def reset_client_address(token: contextvars.Token[str | None]) -> None:
    _client_address.reset(token)


def get_client_address() -> str | None:
    return _client_address.get()


def new_correlation_id() -> str:
    return str(uuid.uuid4())


def coerce_correlation_id(raw: str | None) -> str:
    """Honour a well-formed inbound identifier, otherwise mint one.

    "Well-formed" is deliberately strict — a UUID. An inbound header is attacker-supplied
    and lands in every log line for the request; accepting arbitrary text would let a
    caller inject newlines or forge another request's id into our own audit trail.
    """
    if raw:
        candidate = raw.strip()
        try:
            return str(uuid.UUID(candidate))
        except ValueError:
            pass
    return new_correlation_id()


class JsonFormatter(logging.Formatter):
    """Render records as one JSON object per line.

    Anything passed via ``extra=`` is merged in at the top level, which is what makes
    the existing call sites start producing useful output with no edits to them.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }

        correlation_id = getattr(record, "correlation_id", None) or get_correlation_id()
        if correlation_id:
            payload["correlation_id"] = correlation_id

        client_address = getattr(record, "client_address", None) or get_client_address()
        if client_address:
            payload["client_address"] = client_address

        for key, value in record.__dict__.items():
            if key in _STANDARD_RECORD_ATTRS or key.startswith("_"):
                continue
            if key in ("correlation_id", "client_address"):
                continue
            payload[key] = value if _json_safe(value) else repr(value)

        if record.exc_info:
            # Kept for the server-side record only. The HTTP response never carries this
            # — see the catch-all handler in juli_backend.api.middleware.
            payload["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)

        return json.dumps(payload, default=str, ensure_ascii=False)


def _json_safe(value: Any) -> bool:
    return isinstance(value, str | int | float | bool | type(None) | list | dict)


class _CorrelationFilter(logging.Filter):
    """Stamp the current correlation id and client address onto every record.

    A filter rather than formatter-only lookup so the id is attached at emit time, which
    keeps it correct even if a handler formats later or a different formatter is swapped
    in by an operator.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "correlation_id"):
            correlation_id = get_correlation_id()
            if correlation_id:
                record.correlation_id = correlation_id
        if not hasattr(record, "client_address"):
            client_address = get_client_address()
            if client_address:
                record.client_address = client_address
        return True


_DEFAULT_LEVEL = "INFO"
_configured = False


def configure_logging(*, level: str | None = None, force: bool = False) -> None:
    """Configure the root logger once, idempotently.

    Idempotent because uvicorn ``--reload``, the Celery workers and the test suite all
    import the app repeatedly; re-running this would stack duplicate handlers and print
    every line N times.
    """
    global _configured
    if _configured and not force:
        return

    resolved = (level or os.environ.get("LOG_LEVEL") or _DEFAULT_LEVEL).upper()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(_CorrelationFilter())

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(resolved)

    # uvicorn installs its own handlers; let its records flow to ours instead of being
    # printed twice in two different formats.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True

    _configured = True
