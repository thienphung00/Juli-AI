"""Execution status and request types for P2-B4 Celery tool dispatch."""

from __future__ import annotations

from enum import StrEnum


class ExecutionStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ExecutionErrorCategory(StrEnum):
    """Coarse failure taxonomy for outcome tracking and retry policy (#305)."""

    VALIDATION = "validation"
    TIKTOK_API = "tiktok_api"
    TRANSIENT = "transient"
    UNKNOWN = "unknown"
