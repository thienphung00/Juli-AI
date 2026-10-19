"""TikTok Shop Partner API exception hierarchy.

Maps TikTok API error codes to typed exceptions so callers can handle
specific failure modes (auth, rate-limit, permissions, etc.) without
inspecting raw codes.
"""

from __future__ import annotations

from typing import Any


def rebuild_keyword_exception(cls: type[BaseException], kwargs: dict[str, Any]) -> BaseException:
    """Unpickle an exception whose ``__init__`` takes keyword-only arguments.

    ``BaseException.__reduce__`` replays ``cls(*self.args)``, and ``self.args``
    holds only the formatted message. A class whose constructor wants
    ``(code, message, ...)`` or keyword-only fields therefore cannot be rebuilt,
    which is what Celery's result backend logged in production as
    ``UnpickleableExceptionWrapper('...exceptions', 'TikTokAPIError', ...)``
    (P59) -- the task's real failure reached the result store as a wrapper.
    """
    return cls(**kwargs)


class TikTokAPIError(Exception):
    """Base exception for all TikTok Shop API errors."""

    def __init__(
        self,
        code: int,
        message: str,
        request_id: str | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.request_id = request_id
        super().__init__(f"[{code}] {message}")

    def __reduce__(self) -> tuple[Any, ...]:
        # P59: rebuild from the constructor's own arguments (see
        # `rebuild_keyword_exception`); `__dict__` carries any attribute set
        # after construction. Subclasses that keep this `__init__` inherit it.
        return (
            rebuild_keyword_exception,
            (
                type(self),
                {"code": self.code, "message": self.message, "request_id": self.request_id},
            ),
            self.__dict__,
        )


class AuthenticationError(TikTokAPIError):
    """Token expired, invalid signature, or other auth failure (100002)."""


class PermissionDeniedError(TikTokAPIError):
    """Missing API scope or insufficient permissions (100003)."""


class RateLimitError(TikTokAPIError):
    """Request throttled — retry after backoff (100005)."""


class ResourceNotFoundError(TikTokAPIError):
    """Requested entity does not exist (100004)."""


class TikTokSystemError(TikTokAPIError):
    """Transient server-side failure — safe to retry (100006)."""


class TransportGuardError(Exception):
    """Raised when a capability transport guard rejects a request before signing."""

    def __init__(
        self,
        *,
        capability: str,
        method: str,
        path: str,
        message: str,
    ) -> None:
        self.capability = capability
        self.method = method
        self.path = path
        super().__init__(message)

    def __reduce__(self) -> tuple[Any, ...]:
        # Keyword-only constructor: the default reduce cannot rebuild it (P59).
        return (
            rebuild_keyword_exception,
            (
                type(self),
                {
                    "capability": self.capability,
                    "method": self.method,
                    "path": self.path,
                    "message": str(self),
                },
            ),
            self.__dict__,
        )


_CODE_MAP: dict[int, type[TikTokAPIError]] = {
    100002: AuthenticationError,
    100003: PermissionDeniedError,
    100004: ResourceNotFoundError,
    100005: RateLimitError,
    100006: TikTokSystemError,
}


def error_from_response(response: dict) -> TikTokAPIError | None:
    """Build the correct exception from a TikTok API response dict.

    Returns None when the response indicates success (code == 0).
    """
    code = response.get("code", 0)
    if code == 0:
        return None

    message = response.get("message", "Unknown error")
    request_id = response.get("request_id")
    exc_cls = _CODE_MAP.get(code, TikTokAPIError)
    return exc_cls(code=code, message=message, request_id=request_id)
