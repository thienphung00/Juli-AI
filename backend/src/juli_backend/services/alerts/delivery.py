"""Alert delivery orchestration across channel adapters."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.services.alerts.types import Alert, ChannelAdapter, DeliveryResult
from juli_backend.repositories.repos import AlertHistoryRepo


async def deliver_alert(
    session: AsyncSession,
    alert: Alert,
    adapter: ChannelAdapter,
    *,
    device_token: str,
) -> DeliveryResult:
    """Send via adapter and persist alert history."""
    result = await adapter.send(alert, device_token=device_token)

    history_repo = AlertHistoryRepo(session)
    await history_repo.create(
        shop_id=alert.shop_id,
        alert_config_id=alert.config_id,
        triggered_at=datetime.now(timezone.utc),
        payload=json.dumps(
            {
                "title": alert.title,
                "body": alert.body,
                "channel": adapter.channel,
                "latency_seconds": result.latency_seconds,
                "attempts": result.attempts,
            }
        ),
        status="sent" if result.success else "failed",
    )
    return result
