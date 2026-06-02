"""Tests for alerts module — Issue #36.

Test mapping (from issue):
  AC1 → test_evaluate_rules_produces_alerts
  AC2 → test_fcm_delivery_within_latency
  AC3 → test_deduplication_within_cooldown
  AC4 → test_per_shop_rule_configuration
  AC5 → test_channel_adapter_protocol_pluggable
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.catalog.domain.alerts import (
    AlertEvent,
    FcmAdapter,
    RuleConfigInput,
    configure_rules,
    deliver_alert,
    evaluate_rules,
)
from src.modules.catalog.domain.alerts.types import Alert, ChannelAdapter, DeliveryResult
from src.shared.utils.data.models import AlertConfig, Shop, User
from src.shared.utils.data.repos import AlertHistoryRepo


def _make_user(user_id: uuid.UUID) -> User:
    return User(id=user_id, phone="+84900000036")


def _make_shop(shop_id: uuid.UUID, user_id: uuid.UUID) -> Shop:
    return Shop(id=shop_id, user_id=user_id, shop_name="Alert Shop")


async def _seed_shop(session: AsyncSession) -> uuid.UUID:
    uid = uuid.uuid4()
    sid = uuid.uuid4()
    session.add(_make_user(uid))
    session.add(_make_shop(sid, uid))
    await session.flush()
    return sid


async def _instant_send(alert: Alert, device_token: str) -> None:
    assert device_token
    assert alert.title


@pytest.mark.asyncio
async def test_evaluate_rules_produces_alerts(session: AsyncSession):
    """AC1: configured rules produce Alert objects for matching events."""
    shop_id = await _seed_shop(session)
    await configure_rules(
        session,
        shop_id,
        [
            RuleConfigInput(
                alert_type="revenue_milestone",
                threshold={"min_revenue": 1_000_000},
            )
        ],
    )

    event = AlertEvent(
        event_type="metric",
        metric="revenue",
        value=1_500_000.0,
    )
    alerts = await evaluate_rules(session, shop_id, event)

    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.shop_id == shop_id
    assert alert.alert_type == "revenue_milestone"
    assert alert.channel == "fcm"
    assert "doanh thu" in alert.body.lower()


@pytest.mark.asyncio
async def test_fcm_delivery_within_latency(session: AsyncSession):
    """AC2: FCM adapter completes delivery within 30 seconds (PRD AC-26)."""
    shop_id = await _seed_shop(session)
    configs = await configure_rules(
        session,
        shop_id,
        [RuleConfigInput(alert_type="low_stock", threshold={"max_quantity": 5})],
    )
    alert = Alert(
        shop_id=shop_id,
        alert_type="low_stock",
        channel="fcm",
        title="Sắp hết hàng",
        body="Test body",
        config_id=configs[0].id,
    )

    adapter = FcmAdapter(_send_fn=_instant_send)
    result = await deliver_alert(
        session,
        alert,
        adapter,
        device_token="device-token-36",
    )

    assert result.success is True
    assert result.channel == "fcm"
    assert result.latency_seconds < 30.0


@pytest.mark.asyncio
async def test_deduplication_within_cooldown(session: AsyncSession):
    """AC3: no duplicate alerts within cooldown window (default 1 hour)."""
    shop_id = await _seed_shop(session)
    await configure_rules(
        session,
        shop_id,
        [
            RuleConfigInput(
                alert_type="revenue_milestone",
                threshold={"min_revenue": 100, "cooldown_seconds": 3600},
            )
        ],
    )
    event = AlertEvent(event_type="metric", metric="revenue", value=500.0)
    now = datetime(2026, 5, 27, 12, 0, tzinfo=timezone.utc)

    first = await evaluate_rules(session, shop_id, event, now=now)
    assert len(first) == 1

    history_repo = AlertHistoryRepo(session)
    await history_repo.create(
        shop_id=shop_id,
        alert_config_id=first[0].config_id,
        triggered_at=now,
        status="sent",
    )

    second = await evaluate_rules(
        session,
        shop_id,
        event,
        now=now + timedelta(minutes=30),
    )
    assert second == []


@pytest.mark.asyncio
async def test_per_shop_rule_configuration(session: AsyncSession):
    """AC4: configure_rules stores per-shop thresholds."""
    shop_id = await _seed_shop(session)
    saved = await configure_rules(
        session,
        shop_id,
        [
            RuleConfigInput(
                alert_type="anomaly",
                threshold={"min_severity": "high"},
                cooldown_seconds=1800,
            ),
            RuleConfigInput(
                alert_type="low_stock",
                threshold={"max_quantity": 3},
            ),
        ],
    )

    assert len(saved) == 2
    by_type = {c.alert_type: c for c in saved}
    assert by_type["anomaly"].is_active is True
    assert '"min_severity": "high"' in (by_type["anomaly"].threshold_json or "")
    assert '"max_quantity": 3' in (by_type["low_stock"].threshold_json or "")

    updated = await configure_rules(
        session,
        shop_id,
        [
            RuleConfigInput(
                alert_type="anomaly",
                threshold={"min_severity": "medium"},
                is_active=False,
            )
        ],
    )
    assert len(updated) == 1
    assert updated[0].is_active is False


class _RecordingAdapter:
    channel = "test_channel"
    sent = False

    async def send(self, alert: Alert, *, device_token: str) -> DeliveryResult:
        self.sent = True
        return DeliveryResult(
            success=True,
            channel=self.channel,
            latency_seconds=0.01,
            attempts=1,
        )


@pytest.mark.asyncio
async def test_channel_adapter_protocol_pluggable(session: AsyncSession):
    """AC5: core delivery accepts any ChannelAdapter without FCM coupling."""
    shop_id = await _seed_shop(session)
    config = AlertConfig(
        id=uuid.uuid4(),
        shop_id=shop_id,
        alert_type="violation_risk",
        channel="test_channel",
        is_active=True,
    )
    session.add(config)
    await session.flush()

    alert = Alert(
        shop_id=shop_id,
        alert_type="violation_risk",
        channel="test_channel",
        title="Test",
        body="Body",
        config_id=config.id,
    )

    adapter = _RecordingAdapter()
    result = await deliver_alert(
        session,
        alert,
        adapter,
        device_token="tok",
    )

    assert isinstance(adapter, ChannelAdapter)
    assert result.success is True
    assert result.channel == "test_channel"
    assert adapter.sent is True
