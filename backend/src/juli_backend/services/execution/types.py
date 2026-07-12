"""Execution status and request types for P2-B4 Celery tool dispatch."""

from __future__ import annotations

from enum import StrEnum


class ExecutionStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
