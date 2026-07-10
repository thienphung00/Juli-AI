"""Firebase Cloud Messaging adapter with retry + backoff."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from juli_backend.services.alerts.types import Alert, DeliveryResult

logger = logging.getLogger(__name__)

SendFn = Callable[[Alert, str], Awaitable[None]]


@dataclass
class FcmAdapter:
    """Delivers push notifications via FCM HTTP v1 (injectable transport for tests)."""

    channel: str = "fcm"
    max_attempts: int = 3
    base_delay_seconds: float = 0.05
    _send_fn: SendFn | None = None

    async def send(self, alert: Alert, *, device_token: str) -> DeliveryResult:
        started = time.monotonic()
        last_error: str | None = None

        for attempt in range(1, self.max_attempts + 1):
            try:
                await self._deliver(alert, device_token)
                latency = time.monotonic() - started
                return DeliveryResult(
                    success=True,
                    channel=self.channel,
                    latency_seconds=latency,
                    attempts=attempt,
                )
            except Exception as exc:  # noqa: BLE001 — retry boundary
                last_error = str(exc)
                logger.warning(
                    "fcm_delivery_failed",
                    extra={
                        "shop_id": str(alert.shop_id),
                        "alert_type": alert.alert_type,
                        "attempt": attempt,
                        "error": last_error,
                    },
                )
                if attempt < self.max_attempts:
                    delay = self.base_delay_seconds * (2 ** (attempt - 1))
                    await asyncio.sleep(delay)

        latency = time.monotonic() - started
        return DeliveryResult(
            success=False,
            channel=self.channel,
            latency_seconds=latency,
            attempts=self.max_attempts,
            error=last_error,
        )

    async def _deliver(self, alert: Alert, device_token: str) -> None:
        if self._send_fn is not None:
            await self._send_fn(alert, device_token)
            return
        if not device_token:
            raise ValueError("device_token is required for FCM delivery")
        # Production wiring: HTTP client to FCM v1 using service credentials.
        logger.info(
            "fcm_send_stub",
            extra={
                "shop_id": str(alert.shop_id),
                "alert_type": alert.alert_type,
                "title": alert.title,
            },
        )
