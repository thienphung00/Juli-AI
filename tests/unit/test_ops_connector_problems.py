"""F4.13 (C6): Juli Ops lists the Connector readers that did not finish well, from the stored tick
reports (``system_connector_tick``). Synthetic values only."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from juli_backend.models.ops import OpsAuditLog
from juli_backend.services.shopee_recommendations import reader_problems as rp
from tests.support.api import client_for
from tests.support.builders import make_shop, make_user
from tests.unit.test_ops_contract_shops import _ops_client

T0 = datetime(2026, 11, 19, 3, 0)


def _tick(at: datetime, outcomes: dict[str, str], kind: str = "run") -> OpsAuditLog:
    return OpsAuditLog(
        id=uuid.uuid4(),
        actor_email="system",
        action="system_connector_tick",
        at=at,
        after={"kind": kind, "occurred_at": at.isoformat() + "+00:00", "outcomes": outcomes},
    )


def test_only_non_ok_readers_are_listed_with_since_when_it_began():
    rows = [
        _tick(
            T0 - timedelta(days=2),
            {"ads": "done:ads_campaign_daily=posted", "traffic": "error:http_500"},
        ),
        _tick(T0 - timedelta(days=1), {"ads": "open_failed", "traffic": "blocked:login"}),
        _tick(
            T0,
            {
                "ads": "open_failed",
                "traffic": "blocked:login",
                "orders": "partial:first_page",
                "products": "done:item_catalog=posted",
                "health": "skipped:fresh",
            },
        ),
    ]
    out = {p["reader"]: p for p in rp.problems_of(rows)}
    assert set(out) == {"ads", "traffic", "orders"}
    assert out["ads"]["since"] == (T0 - timedelta(days=1)).isoformat() + "Z"  # open_failed twice
    assert out["traffic"]["since"] == (T0 - timedelta(days=1)).isoformat() + "Z"  # login, not 500
    assert out["orders"] == {
        "reader": "orders",
        "outcome": "partial:first_page",
        "since": T0.isoformat() + "Z",
    }


def test_a_reader_that_recovered_is_not_listed_and_skips_are_ignored():
    rows = [
        _tick(T0 - timedelta(hours=5), {"ads": "timeout"}),
        _tick(T0, {"ads": "done:ads_campaign_daily=posted"}),
        _tick(T0 + timedelta(hours=1), {"ads": "error:x"}, kind="skip"),
    ]
    assert rp.problems_of(rows) == []


async def test_the_ops_route_lists_the_shops_problems(session, monkeypatch):
    seller = await make_user(session, email="seller-f413@example.com")
    shop = await make_shop(session, seller, platform="shopee", tiktok_shop_id=None)
    now = datetime.now().replace(microsecond=0)
    for row in (
        _tick(now - timedelta(hours=2), {"traffic": "blocked:login", "ads": "done:x=posted"}),
    ):
        row.shop_id = shop.id
        session.add(row)
    await session.commit()
    app = await _ops_client(session, monkeypatch, "viewer")
    async with client_for(app) as client:
        res = await client.get(f"/v1/ops/shops/{shop.id}/connector-problems")
    app.dependency_overrides.clear()
    assert res.status_code == 200, res.text
    assert [(p["reader"], p["outcome"]) for p in res.json()["data"]] == [
        ("traffic", "blocked:login")
    ]
