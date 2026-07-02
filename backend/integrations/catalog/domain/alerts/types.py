"""Shared types for the alerts module."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class AlertEvent:
    """Incoming signal evaluated against configured shop rules."""

    event_type: str
    metric: str
    value: float
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Alert:
    """A triggered alert ready for channel delivery."""

    shop_id: uuid.UUID
    alert_type: str
    channel: str
    title: str
    body: str
    config_id: uuid.UUID
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RuleConfigInput:
    """Per-shop rule definition for ``configure_rules``."""

    alert_type: str
    channel: str = "fcm"
    is_active: bool = True
    threshold: dict[str, Any] | None = None
    cooldown_seconds: int = 3600


@dataclass(frozen=True)
class DeliveryResult:
    success: bool
    channel: str
    latency_seconds: float
    attempts: int
    error: str | None = None


@runtime_checkable
class ChannelAdapter(Protocol):
    """Pluggable delivery channel (FCM, Zalo OA, etc.)."""

    channel: str

    async def send(
        self,
        alert: Alert,
        *,
        device_token: str,
    ) -> DeliveryResult: ...
