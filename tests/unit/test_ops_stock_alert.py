"""Juli Ops: the shop's stock-alert switch (batch-1119-f5, F5.O1). Synthetic fixtures only."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from juli_backend.models.ops import OpsAuditLog, OpsStaff
from tests.support.api import build_app, client_for
from tests.support.builders import make_shop, make_user


async def _app(session, monkeypatch, role):
    from juli_backend.api.routes.ops import get_ops_user
    from juli_backend.core.security import get_current_user

    monkeypatch.setenv("OPS_CF_ACCESS_BYPASS", "1")
    monkeypatch.setenv("ENVIRONMENT", "development")
    email = f"{role}-{uuid.uuid4().hex[:6]}@app-juli.com"
    user = await make_user(session, email=email)
    session.add(OpsStaff(id=uuid.uuid4(), email=email, role=role, active=True))
    await session.flush()
    app = build_app(session)

    async def current():
        await session.refresh(user)
        return user

    app.dependency_overrides[get_current_user] = current
    app.dependency_overrides[get_ops_user] = current
    return app


async def _shop(session, **kw):
    seller = await make_user(session, email=f"seller-{uuid.uuid4().hex[:6]}@example.com")
    shop = await make_shop(session, seller, platform="shopee", **kw)
    await session.commit()
    return shop.id


async def test_get_defaults_to_off_and_seven_days(session, monkeypatch):
    shop_id = await _shop(session)
    app = await _app(session, monkeypatch, "viewer")
    async with client_for(app) as client:
        got = await client.get(f"/v1/ops/shops/{shop_id}/stock-alert")
    app.dependency_overrides.clear()
    assert got.status_code == 200 and got.json() == {"status": "off", "days": 7}


async def test_put_persists_status_and_days_and_audits(session, monkeypatch):
    shop_id = await _shop(session)
    app = await _app(session, monkeypatch, "operator")
    async with client_for(app) as client:
        put = await client.put(
            f"/v1/ops/shops/{shop_id}/stock-alert", json={"status": "preview", "days": 14}
        )
        only_days = await client.put(f"/v1/ops/shops/{shop_id}/stock-alert", json={"days": 10})
        got = await client.get(f"/v1/ops/shops/{shop_id}/stock-alert")
    app.dependency_overrides.clear()
    assert put.status_code == 200 and put.json() == {"status": "preview", "days": 14}
    assert only_days.json() == {"status": "preview", "days": 10}  # status kept
    assert got.json() == {"status": "preview", "days": 10}
    actions = (
        await session.execute(select(OpsAuditLog.action).where(OpsAuditLog.shop_id == shop_id))
    ).scalars()
    assert set(actions) == {"stock_alert_set"}


async def test_put_validates_status_and_days(session, monkeypatch):
    shop_id = await _shop(session)
    app = await _app(session, monkeypatch, "operator")
    url = f"/v1/ops/shops/{shop_id}/stock-alert"
    async with client_for(app) as client:
        bad_status = await client.put(url, json={"status": "maybe"})
        low = await client.put(url, json={"status": "on", "days": 0})
        high = await client.put(url, json={"status": "on", "days": 61})
        extra = await client.put(url, json={"status": "on", "who": "x"})
        got = await client.get(url)
    app.dependency_overrides.clear()
    assert [bad_status.status_code, low.status_code, high.status_code] == [422, 422, 422]
    assert extra.status_code == 422
    assert got.json() == {"status": "off", "days": 7}


async def test_a_viewer_cannot_write_and_an_unknown_shop_is_404(session, monkeypatch):
    shop_id = await _shop(session)
    app = await _app(session, monkeypatch, "viewer")
    async with client_for(app) as client:
        put = await client.put(f"/v1/ops/shops/{shop_id}/stock-alert", json={"status": "on"})
        unknown = await client.get(f"/v1/ops/shops/{uuid.uuid4()}/stock-alert")
    app.dependency_overrides.clear()
    assert put.status_code == 403
    assert unknown.status_code == 404


async def test_the_sample_shop_refuses_anything_but_off(session, monkeypatch):
    shop_id = await _shop(session, shopee_shop_id="990000000001")  # reserved sample range
    app = await _app(session, monkeypatch, "operator")
    url = f"/v1/ops/shops/{shop_id}/stock-alert"
    async with client_for(app) as client:
        refused = await client.put(url, json={"status": "on"})
        off = await client.put(url, json={"status": "off", "days": 5})
        got = await client.get(url)
    app.dependency_overrides.clear()
    assert refused.status_code == 422
    assert off.status_code == 200
    assert got.json() == {"status": "off", "days": 5}
