"""TikTok Shop Partner API exception hierarchy.

Maps TikTok API error codes to typed exceptions so callers can handle
specific failure modes (auth, rate-limit, permissions, etc.) without
inspecting raw codes.
"""

from __future__ import annotations

from typing import Optional


class TikTokAPIError(Exception):
    """Base exception for all TikTok Shop API errors."""

    def __init__(
        self,
        code: int,
        message: str,
        request_id: Optional[str] = None,
    ) -> None:
        self.code = code
        self.message = message
        self.request_id = request_id
        super().__init__(f"[{code}] {message}")


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


_CODE_MAP: dict[int, type[TikTokAPIError]] = {
    100002: AuthenticationError,
    100003: PermissionDeniedError,
    100004: ResourceNotFoundError,
    100005: RateLimitError,
    100006: TikTokSystemError,
}


def error_from_response(response: dict) -> Optional[TikTokAPIError]:
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
