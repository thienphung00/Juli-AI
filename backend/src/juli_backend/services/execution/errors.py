"""Execution error taxonomy for ToolExecution outcomes (#305)."""

from __future__ import annotations

from juli_backend.integrations.tiktok.exceptions import (
    RateLimitError,
    TikTokAPIError,
    TikTokSystemError,
    TransportGuardError,
)
from juli_backend.services.execution.types import ExecutionErrorCategory


def classify_execution_error(exc: BaseException) -> tuple[ExecutionErrorCategory, str]:
    """Map a worker-side exception to a coarse retry/terminal taxonomy."""
    if isinstance(exc, ValueError):
        return ExecutionErrorCategory.VALIDATION, str(exc)
    if isinstance(exc, TransportGuardError):
        return ExecutionErrorCategory.VALIDATION, str(exc)
    if isinstance(exc, (RateLimitError, TikTokSystemError)):
        return ExecutionErrorCategory.TRANSIENT, str(exc)
    if isinstance(exc, TikTokAPIError):
        return ExecutionErrorCategory.TIKTOK_API, str(exc)
    return ExecutionErrorCategory.UNKNOWN, str(exc)
