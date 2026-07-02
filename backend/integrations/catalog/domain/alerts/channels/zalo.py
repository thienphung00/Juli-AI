"""Zalo Official Account adapter with retry + backoff."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx

from backend.integrations.catalog.domain.alerts.types import Alert, DeliveryResult

logger = logging.getLogger(__name__)

SendFn = Callable[[Alert, str], Awaitable[None]]

ZALO_OA_MESSAGE_URL = "https://openapi.zalo.me/v3.0/oa/message/cs"


@dataclass
class ZaloOaAdapter:
    """Delivers seller alerts via Zalo OA messaging API.

    ``device_token`` is the recipient Zalo user id (OA follower id), matching
  the ``ChannelAdapter`` parameter name used by ``deliver_alert``.
    """

    channel: str = "zalo"
    max_attempts: int = 3
    base_delay_seconds: float = 0.05
    _send_fn: SendFn | None = None
    _access_token: str | None = None
    _http_client: httpx.AsyncClient | None = None

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
                    "zalo_delivery_failed",
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

    async def _deliver(self, alert: Alert, zalo_user_id: str) -> None:
        if self._send_fn is not None:
            await self._send_fn(alert, zalo_user_id)
            return
        if not zalo_user_id:
            raise ValueError("device_token (Zalo user id) is required for Zalo delivery")

        token = self._access_token or os.environ.get("ZALO_OA_ACCESS_TOKEN", "")
        if not token:
            logger.info(
                "zalo_send_stub",
                extra={
                    "shop_id": str(alert.shop_id),
                    "alert_type": alert.alert_type,
                    "title": alert.title,
                },
            )
            return

        payload = _build_message_payload(zalo_user_id, alert)
        client = self._http_client or httpx.AsyncClient(timeout=30.0)
        owns_client = self._http_client is None
        try:
            response = await client.post(
                ZALO_OA_MESSAGE_URL,
                params={"access_token": token},
                json=payload,
            )
            response.raise_for_status()
            body = response.json()
            if body.get("error") not in (0, None):
                raise RuntimeError(
                    f"Zalo API error {body.get('error')}: {body.get('message', body)}"
                )
        finally:
            if owns_client:
                await client.aclose()


def _build_message_payload(zalo_user_id: str, alert: Alert) -> dict[str, Any]:
    text = f"{alert.title}\n{alert.body}".strip()
    return {
        "recipient": {"user_id": zalo_user_id},
        "message": {"text": text},
    }
