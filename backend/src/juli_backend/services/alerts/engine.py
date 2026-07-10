"""Alert rule evaluation, configuration, and deduplication."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.services.alerts.rules import (
    build_alert_copy,
    cooldown_seconds,
    parse_threshold,
    rule_matches,
)
from juli_backend.services.alerts.types import Alert, AlertEvent, RuleConfigInput
from juli_backend.models.models import AlertConfig
from juli_backend.repositories.repos import AlertConfigsRepo, AlertHistoryRepo


async def configure_rules(
    session: AsyncSession,
    shop_id: uuid.UUID,
    rules: list[RuleConfigInput],
) -> list[AlertConfig]:
    """Upsert per-shop alert rules and thresholds."""
    repo = AlertConfigsRepo(session)
    saved: list[AlertConfig] = []

    for rule in rules:
        threshold = dict(rule.threshold or {})
        threshold.setdefault("cooldown_seconds", rule.cooldown_seconds)
        payload = json.dumps(threshold) if threshold else None

        existing = await repo.get_by_type(shop_id, rule.alert_type)
        if existing is None:
            saved.append(
                await repo.create(
                    shop_id=shop_id,
                    alert_type=rule.alert_type,
                    channel=rule.channel,
                    threshold_json=payload,
                    is_active=rule.is_active,
                )
            )
        else:
            existing.channel = rule.channel
            existing.is_active = rule.is_active
            existing.threshold_json = payload
            await session.flush()
            saved.append(existing)

    return saved


async def evaluate_rules(
    session: AsyncSession,
    shop_id: uuid.UUID,
    event: AlertEvent,
    *,
    now: datetime | None = None,
) -> list[Alert]:
    """Evaluate active rules; apply per-type cooldown deduplication."""
    configs_repo = AlertConfigsRepo(session)
    history_repo = AlertHistoryRepo(session)
    clock = now or datetime.now(timezone.utc)

    configs = await configs_repo.list_active(shop_id)
    alerts: list[Alert] = []

    for config in configs:
        if not rule_matches(config, event):
            continue

        since = clock - timedelta(seconds=cooldown_seconds(config))
        if await history_repo.has_recent_for_type(
            shop_id, config.alert_type, since=since
        ):
            continue

        title, body = build_alert_copy(config, event)
        threshold = parse_threshold(config)
        alerts.append(
            Alert(
                shop_id=shop_id,
                alert_type=config.alert_type,
                channel=config.channel,
                title=title,
                body=body,
                config_id=config.id,
                payload={
                    "event_type": event.event_type,
                    "metric": event.metric,
                    "value": event.value,
                    "threshold": threshold,
                },
            )
        )

    return alerts
