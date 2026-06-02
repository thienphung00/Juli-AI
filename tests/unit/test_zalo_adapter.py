"""Tests for Zalo OA channel adapter — Issue #40.

Test mapping (from issue):
  AC1 → test_zalo_adapter_implements_channel_protocol
  AC2 → test_zalo_delivery_within_latency
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.catalog.domain.alerts import ZaloOaAdapter, deliver_alert
from src.modules.catalog.domain.alerts.types import Alert, ChannelAdapter
from src.shared.utils.data.models import AlertConfig, Shop, User


def _make_user(user_id: uuid.UUID) -> User:
    return User(id=user_id, phone="+84900000040")


def _make_shop(shop_id: uuid.UUID, user_id: uuid.UUID) -> Shop:
    return Shop(id=shop_id, user_id=user_id, shop_name="Zalo Shop")


async def _seed_shop(session: AsyncSession) -> uuid.UUID:
    uid = uuid.uuid4()
    sid = uuid.uuid4()
    session.add(_make_user(uid))
    session.add(_make_shop(sid, uid))
    await session.flush()
    return sid


async def _instant_zalo_send(alert: Alert, zalo_user_id: str) -> None:
    assert zalo_user_id
    assert alert.title
    assert alert.channel == "zalo"


@pytest.mark.asyncio
async def test_zalo_adapter_implements_channel_protocol(session: AsyncSession):
    """AC1: ZaloOaAdapter implements ChannelAdapter and delivers via Zalo OA API path."""
    shop_id = await _seed_shop(session)
    config = AlertConfig(
        id=uuid.uuid4(),
        shop_id=shop_id,
        alert_type="low_stock",
        channel="zalo",
        is_active=True,
    )
    session.add(config)
    await session.flush()

    alert = Alert(
        shop_id=shop_id,
        alert_type="low_stock",
        channel="zalo",
        title="Sắp hết hàng",
        body="SKU-1 còn 2 sản phẩm — nên nhập thêm.",
        config_id=config.id,
        payload={"sku_id": "SKU-1"},
    )

    adapter = ZaloOaAdapter(_send_fn=_instant_zalo_send)
    result = await deliver_alert(
        session,
        alert,
        adapter,
        device_token="zalo-user-40",
    )

    assert isinstance(adapter, ChannelAdapter)
    assert isinstance(adapter, ZaloOaAdapter)
    assert adapter.channel == "zalo"
    assert result.success is True
    assert result.channel == "zalo"


@pytest.mark.asyncio
async def test_zalo_delivery_within_latency(session: AsyncSession):
    """AC2: stock depletion warnings delivered via Zalo within 2 minutes (PRD AC-25)."""
    shop_id = await _seed_shop(session)
    config = AlertConfig(
        id=uuid.uuid4(),
        shop_id=shop_id,
        alert_type="low_stock",
        channel="zalo",
        is_active=True,
    )
    session.add(config)
    await session.flush()

    alert = Alert(
        shop_id=shop_id,
        alert_type="low_stock",
        channel="zalo",
        title="Sắp hết hàng",
        body="Test stock depletion warning",
        config_id=config.id,
    )

    adapter = ZaloOaAdapter(_send_fn=_instant_zalo_send)
    result = await adapter.send(alert, device_token="zalo-user-40")

    assert result.success is True
    assert result.channel == "zalo"
    assert result.latency_seconds < 120.0
