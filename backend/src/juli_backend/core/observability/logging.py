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
import re
import sys
import uuid
from typing import Any

CORRELATION_ID_HEADER = "X-Request-ID"
REDACTION_MARKER = "[REDACTED]"

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

    Redaction is applied to the entire payload to remove credentials and PII.
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

        # Apply redaction to the entire payload
        payload = self._redact_payload(payload)

        return json.dumps(payload, default=str, ensure_ascii=False)

    def _redact_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Redact sensitive values in the payload.

        Applies redaction to:
        - Top-level extra fields
        - Nested dicts and lists
        - Exception and stack traces (string redaction)

        Preserves non-sensitive fields like correlation_id, client_address, timestamp, etc.
        """
        redacted = {}
        for key, value in payload.items():
            # Never redact these fields
            if key in ("timestamp", "level", "logger", "event", "correlation_id", "client_address"):
                redacted[key] = value
            elif _is_redactable_key(key):
                # Key itself indicates redactable content
                redacted[key] = REDACTION_MARKER
            elif isinstance(value, dict):
                redacted[key] = _redact_dict(value)
            elif isinstance(value, list):
                redacted[key] = _redact_list(value)
            elif isinstance(value, str):
                # For exception and stack traces, use string-level redaction
                if key in ("exception", "stack"):
                    redacted[key] = _redact_string(value)
                else:
                    redacted[key] = _redact_value(value)
            else:
                redacted[key] = value

        return redacted


def _json_safe(value: Any) -> bool:
    return isinstance(value, str | int | float | bool | type(None) | list | dict)


def _is_redactable_key(key: str) -> bool:
    """Check if a key name indicates a value that should be redacted.

    Redactable keys: password, secret, token, authorization, api_key, access_token,
    refresh_token, cookie, set-cookie, phone, email (case-insensitive).
    """
    lower_key = key.lower()
    redactable_keywords = {
        "password",
        "secret",
        "token",
        "authorization",
        "api_key",
        "access_token",
        "refresh_token",
        "cookie",
        "set-cookie",
        "phone",
        "email",
        "gh_token",
        "aws_key",
    }
    return any(keyword in lower_key for keyword in redactable_keywords)


def _is_redactable_value(value: Any) -> bool:
    """Check if a value matches credential or PII patterns.

    Patterns:
    - API keys: sk_*, bearer *, AKIA*
    - Email: contains @ with domain-like structure
    - Phone: starts with + followed by digits and dashes, min 10 digits
    """
    if not isinstance(value, str):
        return False

    # Skip UUIDs and ISO-8601 timestamps
    if _is_uuid(value) or _is_iso_8601(value):
        return False

    stripped = value.strip()

    # API key patterns
    if stripped.startswith("sk-") or stripped.startswith("sk_"):
        return True
    if stripped.startswith("ghp_") or stripped.startswith("ghp-"):
        return True
    if stripped.startswith("AKIA"):
        return True
    if stripped.lower().startswith("bearer "):
        return True

    # Email pattern: contains @ with dots
    if "@" in stripped and "." in stripped:
        if re.match(r"[^@]+@[^@]+\.[a-zA-Z]{2,}", stripped):
            return True

    # Phone pattern: starts with +, contains digits and dashes/spaces
    if stripped.startswith("+"):
        # Extract digits only to count them
        digits_only = re.sub(r"[^\d]", "", stripped)
        if len(digits_only) >= 10:
            # Check if it has the right structure: +digits or +digits-digits
            if re.match(r"\+\d+[- ]?\d+", stripped):
                return True

    return False


def _is_uuid(value: str) -> bool:
    """Check if value is a UUID."""
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError):
        return False


def _is_iso_8601(value: str) -> bool:
    """Check if value is an ISO-8601 timestamp."""
    # Simplified check for common ISO-8601 formats
    iso_pattern = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
    return bool(re.match(iso_pattern, value))


def _redact_value(value: Any) -> Any:
    """Redact a single value if it matches redaction criteria."""
    if _is_redactable_value(value):
        return REDACTION_MARKER
    return value


def _redact_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Recursively redact sensitive values in a dictionary.

    Redacts based on:
    - Key names (password, secret, token, etc.)
    - Value patterns (API keys, emails, phone numbers)

    Preserves structure and keys for operator visibility.
    """
    redacted = {}
    for key, value in data.items():
        if _is_redactable_key(key):
            redacted[key] = REDACTION_MARKER
        elif isinstance(value, dict):
            redacted[key] = _redact_dict(value)
        elif isinstance(value, list):
            redacted[key] = _redact_list(value)
        elif isinstance(value, str):
            redacted[key] = _redact_value(value)
        else:
            redacted[key] = value
    return redacted


def _redact_list(data: list[Any]) -> list[Any]:
    """Recursively redact sensitive values in a list."""
    redacted = []
    for item in data:
        if isinstance(item, dict):
            redacted.append(_redact_dict(item))
        elif isinstance(item, list):
            redacted.append(_redact_list(item))
        elif isinstance(item, str):
            redacted.append(_redact_value(item))
        else:
            redacted.append(item)
    return redacted


def _redact_string(text: str) -> str:
    """Redact sensitive values in a string (for exception/stack traces)."""
    # This is tricky because we're redacting inside free text. We use value patterns.
    result = text

    # API key patterns
    result = re.sub(r"sk[-_][a-zA-Z0-9-_]+", REDACTION_MARKER, result)
    result = re.sub(r"ghp[-_][a-zA-Z0-9-_]+", REDACTION_MARKER, result)
    result = re.sub(r"AKIA[0-9A-Z]{16}", REDACTION_MARKER, result)
    result = re.sub(
        r"bearer\s+[a-zA-Z0-9\-._~+/]+=*",
        REDACTION_MARKER,
        result,
        flags=re.IGNORECASE,
    )

    # Email pattern
    result = re.sub(
        r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
        REDACTION_MARKER,
        result,
    )

    # Phone pattern: +digits with optional dashes/spaces
    result = re.sub(r"\+\d{1,3}[- ]?\d{1,14}(?:[- ]?\d{1,4})*", REDACTION_MARKER, result)

    # Password pattern: word after "password:" or "password =" with various separators
    result = re.sub(
        (
            r"(?:password|passwd|pwd)\s*[:=\s]\s*"
            r"[\w\-._~+/!@#$%^&*()+=\[\]{}|;:',<>?/\\`]+"
        ),
        REDACTION_MARKER,
        result,
        flags=re.IGNORECASE,
    )

    return result


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


class _JuliManagedStreamHandler(logging.StreamHandler):
    """Marks a handler as installed by ``configure_logging``, so re-configuration
    clears only our own handlers and never a foreign one (e.g. pytest's
    ``LogCaptureHandler``, which backs ``caplog``) — see #1013.
    """


def configure_logging(*, level: str | None = None, force: bool = False) -> None:
    """Configure the root logger once, idempotently.

    Idempotent because uvicorn ``--reload``, the Celery workers and the test suite all
    import the app repeatedly; re-running this would stack duplicate handlers and print
    every line N times.

    The clearing loop below only removes handlers *this module* previously installed
    (identified by the ``_JuliManagedStreamHandler`` marker type). It must never touch
    foreign handlers — notably pytest's ``LogCaptureHandler``, which backs the ``caplog``
    fixture. Wiping every root handler unconditionally used to strip that handler off
    mid-suite whenever a forced re-configuration happened after collection started
    (#1013).
    """
    global _configured
    if _configured and not force:
        return

    resolved = (level or os.environ.get("LOG_LEVEL") or _DEFAULT_LEVEL).upper()

    handler = _JuliManagedStreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(_CorrelationFilter())

    root = logging.getLogger()
    for existing in list(root.handlers):
        if isinstance(existing, _JuliManagedStreamHandler):
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
