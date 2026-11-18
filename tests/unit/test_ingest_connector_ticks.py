"""Connector 0.3.19: the scheduler's tick report (SQLite).

- ``POST /v1/ingest/connector-ticks``: a finished run or a skipped start lands in the Ops audit
  log (``system_connector_tick``), metadata only, behind the ingest token, and the shop's
  Connector state keeps the version
- the body is validated (no extra fields, short outcome notes) and scoped to the token's platform
- a small hourly cap

Synthetic values only.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from juli_backend.models.ops import OpsAuditLog
from juli_backend.models.shopee_connector import ShopeeConnectorState
from juli_backend.services.ingest.rate_limit import InMemoryRateGate, set_ingest_rate_gate
from tests.support.api import client_for
from tests.unit.test_ingest_gateway import _paired_client, _shopee_tenant


@pytest.fixture(autouse=True)
def generous_gate():
    set_ingest_rate_gate(InMemoryRateGate())
    yield
    set_ingest_rate_gate(None)


TICK = {
    "platform": "shopee",
    "kind": "run",
    "trigger": "daily",
    "result": "finished",
    "day": "2026-11-14",
    "occurred_at": "2026-11-14T03:00:00Z",
    "outcomes": {
        "products": "done:item_catalog=posted,item_snapshot=posted",
        "orders": "partial:page_cap",
    },
    "source_version": "0.3.19",
}


async def _token_headers(ext, code):
    paired = await ext.post("/v1/ingest/pair", json={"code": code, "platform": "shopee"})
    assert paired.status_code == 200, paired.text
    return {"Authorization": f"Bearer {paired.json()['token']}"}


async def test_a_tick_is_recorded_in_the_ops_audit_log_and_keeps_the_version(session):
    user, shop = await _shopee_tenant(session)
    app, code = await _paired_client(session, shop, user)
    async with client_for(app) as ext:
        assert (await ext.post("/v1/ingest/connector-ticks", json=TICK)).status_code == 401
        auth = await _token_headers(ext, code)
        done = await ext.post("/v1/ingest/connector-ticks", json=TICK, headers=auth)
        skip = await ext.post(
            "/v1/ingest/connector-ticks",
            json={
                **TICK,
                "kind": "skip",
                "trigger": "worker_start",
                "result": "backfill_busy",
                "outcomes": {},
            },
            headers=auth,
        )
    assert done.status_code == 202, done.text
    assert skip.status_code == 202, skip.text
    rows = (
        (
            await session.execute(
                select(OpsAuditLog).where(
                    OpsAuditLog.shop_id == shop.id, OpsAuditLog.action == "system_connector_tick"
                )
            )
        )
        .scalars()
        .all()
    )
    by_result = {row.after["result"]: row for row in rows}
    assert sorted(by_result) == ["backfill_busy", "finished"]
    assert by_result["finished"].actor_email == "system"
    assert by_result["finished"].after == {
        "platform": "shopee",
        "kind": "run",
        "trigger": "daily",
        "result": "finished",
        "day": "2026-11-14",
        "occurred_at": "2026-11-14T03:00:00+00:00",
        "outcomes": TICK["outcomes"],
        "source_version": "0.3.19",
    }
    state = await session.get(ShopeeConnectorState, shop.id)
    assert state is not None
    assert state.connector_version == "0.3.19"


async def test_a_tick_is_validated_and_scoped_to_the_token(session):
    user, shop = await _shopee_tenant(session)
    app, code = await _paired_client(session, shop, user)
    async with client_for(app) as ext:
        auth = await _token_headers(ext, code)
        bad = [
            {**TICK, "body": {"buyer": "x"}},
            {**TICK, "kind": "other"},
            {**TICK, "trigger": "Pair; DROP"},
            {**TICK, "outcomes": {"Orders!": "x"}},
            {**TICK, "outcomes": {"orders": "x" * 161}},
            {**TICK, "outcomes": {f"r_{'a' * (i % 20)}{chr(97 + i % 26)}": "x" for i in range(41)}},
        ]
        codes = [
            (await ext.post("/v1/ingest/connector-ticks", json=body, headers=auth)).status_code
            for body in bad
        ]
        other = await ext.post(
            "/v1/ingest/connector-ticks", json={**TICK, "platform": "tiktok"}, headers=auth
        )
    assert codes == [422] * len(bad)
    assert other.status_code == 403


async def test_a_stuck_client_cannot_flood_the_audit_log(session):
    user, shop = await _shopee_tenant(session)
    app, code = await _paired_client(session, shop, user)
    async with client_for(app) as ext:
        auth = await _token_headers(ext, code)
        codes = [
            (await ext.post("/v1/ingest/connector-ticks", json=TICK, headers=auth)).status_code
            for _ in range(32)
        ]
    assert codes[:30] == [202] * 30
    assert codes[30:] == [429, 429]


async def test_a_daily_run_writes_its_reader_blocks_stock_runs_and_skips_leave_them(session):
    """Connector 0.3.22 (migration 131): the state row keeps the last daily run's blocked pages."""
    user, shop = await _shopee_tenant(session)
    app, code = await _paired_client(session, shop, user)
    blocked = {"orders": "done", "shop_totals": "blocked:login", "traffic": "blocked:login"}
    async with client_for(app) as ext:
        auth = await _token_headers(ext, code)

        def post(body):
            return ext.post("/v1/ingest/connector-ticks", json=body, headers=auth)

        assert (await post({**TICK, "outcomes": blocked})).status_code == 202
        stock = {**TICK, "trigger": "stock", "outcomes": {"products": "done"}}
        assert (await post(stock)).status_code == 202
        skip = {**TICK, "kind": "skip", "trigger": "alarm", "result": "done_today", "outcomes": {}}
        assert (await post(skip)).status_code == 202
        row = await session.get(ShopeeConnectorState, shop.id)
        await session.refresh(row)
        assert row.reader_blocks == [
            {
                "section": "phan_tich_ban_hang",
                "reason": "login",
                "readers": ["shop_totals", "traffic"],
            }
        ]
        assert row.reader_blocks_at is not None
        # The next daily run with no block clears them.
        assert (await post(TICK)).status_code == 202
        await session.refresh(row)
        assert row.reader_blocks == []


async def test_a_reread_tick_merges_into_the_blocks_and_a_daily_run_still_replaces(session):
    """B2/B4: trigger ``reread`` is accepted; done readers leave their block, blocked ones join."""
    user, shop = await _shopee_tenant(session)
    app, code = await _paired_client(session, shop, user)
    first = {
        **TICK,
        "outcomes": {
            "shop_totals": "blocked:password_recheck",
            "product_period": "blocked:password_recheck",
        },
    }
    async with client_for(app) as ext:
        auth = await _token_headers(ext, code)

        def post(body):
            return ext.post("/v1/ingest/connector-ticks", json=body, headers=auth)

        assert (await post(first)).status_code == 202
        reread = {
            **TICK,
            "trigger": "reread",
            "outcomes": {"shop_totals": "done:shop_overview=posted"},
        }
        assert (await post(reread)).status_code == 202
        row = await session.get(ShopeeConnectorState, shop.id)
        await session.refresh(row)
        assert row.reader_blocks == [
            {
                "section": "phan_tich_ban_hang",
                "reason": "password_recheck",
                "readers": ["product_period"],
            }
        ]
        again = {**reread, "outcomes": {"product_period": "done:product_period=posted"}}
        assert (await post(again)).status_code == 202
        await session.refresh(row)
        assert row.reader_blocks == []
        assert (await post({**TICK, "outcomes": {"traffic": "blocked:login"}})).status_code == 202
        await session.refresh(row)
        assert [b["readers"] for b in row.reader_blocks] == [["traffic"]]
