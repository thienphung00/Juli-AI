"""KiotViet API exception hierarchy.

Maps HTTP status codes and KiotViet error payloads into typed exceptions
so callers can handle failures precisely without inspecting raw responses.
"""

from __future__ import annotations

from typing import Any


class KiotVietError(Exception):
    """Base exception for all KiotViet API errors."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        error_code: str | None = None,
        errors: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.errors = errors or []


class AuthenticationError(KiotVietError):
    """401 — invalid or expired token."""


class ForbiddenError(KiotVietError):
    """403 — insufficient permissions."""


class NotFoundError(KiotVietError):
    """404 — requested resource does not exist."""


class ValidationError(KiotVietError):
    """400 — bad request / business-logic validation failure."""


class RateLimitError(KiotVietError):
    """429 — rate limit exceeded."""


class ServerError(KiotVietError):
    """5xx — KiotViet server-side failure."""


_STATUS_TO_EXCEPTION: dict[int, type[KiotVietError]] = {
    400: ValidationError,
    401: AuthenticationError,
    403: ForbiddenError,
    404: NotFoundError,
    429: RateLimitError,
}


def raise_for_status(status_code: int, body: dict[str, Any] | None = None) -> None:
    """Raise a typed exception when the API returns a non-200 status."""
    if status_code == 200:
        return

    error_code: str | None = None
    message = f"HTTP {status_code}"
    field_errors: list[dict[str, Any]] = []

    if body and "responseStatus" in body:
        rs = body["responseStatus"]
        error_code = rs.get("errorCode")
        message = rs.get("message", message)
        field_errors = rs.get("errors", [])

    exc_cls = _STATUS_TO_EXCEPTION.get(status_code)
    if exc_cls is None:
        exc_cls = ServerError if status_code >= 500 else KiotVietError

    raise exc_cls(
        message=message,
        status_code=status_code,
        error_code=error_code,
        errors=field_errors,
    )
