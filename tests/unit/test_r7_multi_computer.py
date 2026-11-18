"""batch-1118e R7: the Connector on more than one computer (SQLite; the claim race is Postgres).

- L1: a poll leases the open fill jobs to its token; another live token is not served them and its
  report is refused (409 ``fill_job_leased``); the holder's poll extends the lease; an expired
  lease, or one held by a revoked token, is free
- L2: heartbeat / version / tab / reader blocks are kept per token and the shop row is their
  aggregate (``connector_state.aggregate``); the clear-on-ingest clears every token
- L3: ``read()`` keeps its keys and adds ``computers``

Synthetic values only.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

from juli_backend.models.ingest import IngestToken
from juli_backend.models.shopee_connector import ShopeeConnectorState, ShopeeConnectorTokenState
from juli_backend.models.shopee_fill import ShopeeFillJob
from juli_backend.services.ingest.rate_limit import InMemoryRateGate, set_ingest_rate_gate
from juli_backend.services.shopee_recommendations import connector_state as cs
from juli_backend.services.shopee_recommendations import fill_queue
from tests.support.api import build_app, client_for
from tests.unit import test_p97_fill_queue as p97

_approve, _token = p97._approve, p97._token
shop = p97.shop  # the seeded reco shop fixture

JOBS = "/v1/ingest/fill-jobs"
TICKS = "/v1/ingest/connector-ticks"
NOW = datetime(2026, 11, 18, 3, 0)
BLOCK_A = {"section": "phan_tich_ban_hang", "reason": "password_recheck", "readers": ["traffic"]}
BLOCK_B = {
    "section": "phan_tich_ban_hang",
    "reason": "password_recheck",
    "readers": ["shop_totals"],
}
LOGIN = {"section": "seller_centre", "reason": "login", "readers": ["orders"]}


@pytest.fixture(autouse=True)
def no_minimum_version(monkeypatch):
    """These tests post made-up older versions; the minimum-version gate has its own tests."""
    monkeypatch.setenv("CONNECTOR_MIN_VERSION", "0.0.0")


@pytest.fixture(autouse=True)
def _flag_on(monkeypatch):
    monkeypatch.setenv("CONNECTOR_FILL_LISTING", "1")
    set_ingest_rate_gate(InMemoryRateGate())
    yield
    set_ingest_rate_gate(None)


def _wall() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _row(**kw) -> ShopeeConnectorTokenState:
    base = {
        "token_id": uuid.uuid4(),
        "shop_id": uuid.uuid4(),
        "heartbeat_at": None,
        "connector_version": None,
        "seller_centre_open": None,
        "reader_blocks": [],
        "reader_blocks_at": None,
    }
    return ShopeeConnectorTokenState(**{**base, **kw})


# ----------------------------------------------------------------------------- L2 (pure)


def test_the_window_constants_live_in_one_place():
    assert cs.FILL_LEASE == timedelta(minutes=10)
    assert cs.HEARTBEAT_FRESH == timedelta(minutes=10)
    assert cs.VERSION_WINDOW == timedelta(days=7)
    assert cs.BLOCKS_WINDOW == timedelta(hours=36)
    assert fill_queue.FILL_LEASE is cs.FILL_LEASE


def test_alive_if_any_computer_is_fresh_and_the_tab_open_if_any_fresh_one_says_so():
    stale = _row(heartbeat_at=NOW - timedelta(hours=2), seller_centre_open=True)
    closed = _row(heartbeat_at=NOW - timedelta(minutes=1), seller_centre_open=False)
    agg = cs.aggregate([stale, closed], now=NOW)
    assert agg["alive"] is True and agg["seller_centre_open"] is False
    assert agg["heartbeat_at"] == NOW - timedelta(minutes=1)
    opened = _row(heartbeat_at=NOW, seller_centre_open=True)
    assert cs.aggregate([stale, closed, opened], now=NOW)["seller_centre_open"] is True
    gone = cs.aggregate([stale], now=NOW)
    assert gone["alive"] is False and gone["seller_centre_open"] is None


def test_the_version_is_the_newest_semver_seen_in_seven_days():
    rows = [
        _row(heartbeat_at=NOW - timedelta(days=1), connector_version="0.3.9"),
        _row(heartbeat_at=NOW - timedelta(hours=1), connector_version="0.3.25"),
        _row(heartbeat_at=NOW - timedelta(days=8), connector_version="0.4.0"),
        _row(heartbeat_at=NOW, connector_version="0.3.24"),
    ]
    assert cs.aggregate(rows, now=NOW)["connector_version"] == "0.3.25"


def test_reader_blocks_are_the_union_of_recent_computers_each_reader_once():
    a = _row(reader_blocks=[BLOCK_A, LOGIN], reader_blocks_at=NOW - timedelta(hours=1))
    b = _row(reader_blocks=[BLOCK_B, BLOCK_A], reader_blocks_at=NOW - timedelta(hours=2))
    old = _row(
        reader_blocks=[{**LOGIN, "readers": ["vouchers"]}],
        reader_blocks_at=NOW - timedelta(hours=37),
    )
    clean = _row(reader_blocks=[], reader_blocks_at=NOW)
    agg = cs.aggregate([b, old, clean, a], now=NOW)
    assert agg["reader_blocks"] == [
        {"section": "phan_tich_ban_hang", "reason": "password_recheck",
         "readers": ["traffic", "shop_totals"]},
        {"section": "seller_centre", "reason": "login", "readers": ["orders"]},
    ]  # fmt: skip
    assert agg["reader_blocks_at"] == NOW


# ----------------------------------------------------------------------------- L1 (routes)


async def _two_computers(session, seeded):
    first = await _token(session, seeded)
    second = await _token(session, seeded)
    return first, second


async def _token_id(session, headers) -> uuid.UUID:
    rows = (await session.scalars(select(IngestToken).order_by(IngestToken.created_at))).all()
    from juli_backend.services.ingest import pairing

    digest = pairing.token_hash(headers["Authorization"].split(" ", 1)[1])
    return next(r.id for r in rows if r.token_hash == digest)


async def _job(session, job_id) -> ShopeeFillJob:
    return (
        await session.scalars(
            select(ShopeeFillJob)
            .where(ShopeeFillJob.id == uuid.UUID(job_id))
            .execution_options(populate_existing=True)
        )
    ).one()


async def test_a_job_leased_to_one_computer_is_not_served_to_another(session, shop):
    seeded, ids = shop
    await _approve(session, seeded, ids[0])
    first, second = await _two_computers(session, seeded)
    app = build_app(session)
    async with client_for(app) as a, client_for(app) as b:
        a.headers.update(first)
        b.headers.update(second)
        got = (await a.get(JOBS, params={"sc_open": "true"})).json()["jobs"]
        assert len(got) == 1
        job_id = got[0]["id"]
        row = await _job(session, job_id)
        assert row.claimed_by_token_id == await _token_id(session, first)
        lease = row.lease_until
        assert lease is not None and lease - _wall() <= cs.FILL_LEASE
        assert (await b.get(JOBS, params={"sc_open": "true"})).json()["jobs"] == []
        refused = await b.post(f"{JOBS}/{job_id}", json={"status": "opened"})
        assert refused.status_code == 409 and refused.json()["detail"]["code"] == "fill_job_leased"
        assert (await _job(session, job_id)).status == "queued"
        # the holder's poll and report extend the lease
        assert [j["id"] for j in (await a.get(JOBS)).json()["jobs"]] == [job_id]
        assert (await a.post(f"{JOBS}/{job_id}", json={"status": "opened"})).status_code == 200
        held = await _job(session, job_id)
        assert held.status == "opened" and held.lease_until >= lease
    app.dependency_overrides.clear()


async def test_an_expired_lease_or_a_revoked_holder_frees_the_job(session, shop):
    seeded, ids = shop
    await _approve(session, seeded, ids[0])
    first, second = await _two_computers(session, seeded)
    app = build_app(session)
    async with client_for(app) as a, client_for(app) as b:
        a.headers.update(first)
        b.headers.update(second)
        (job,) = (await a.get(JOBS)).json()["jobs"]
        await session.execute(
            update(ShopeeFillJob)
            .where(ShopeeFillJob.id == uuid.UUID(job["id"]))
            .values(lease_until=_wall() - timedelta(seconds=1))
        )
        await session.commit()
        assert [j["id"] for j in (await b.get(JOBS)).json()["jobs"]] == [job["id"]]
        second_id = await _token_id(session, second)
        assert (await _job(session, job["id"])).claimed_by_token_id == second_id
        assert (await a.get(JOBS)).json()["jobs"] == []  # now B's
        await session.execute(
            update(IngestToken).where(IngestToken.id == second_id).values(revoked_at=_wall())
        )
        await session.commit()
        assert [j["id"] for j in (await a.get(JOBS)).json()["jobs"]] == [job["id"]]
        assert (await a.post(f"{JOBS}/{job['id']}", json={"status": "opened"})).status_code == 200
    app.dependency_overrides.clear()


async def test_a_report_of_an_unclaimed_job_takes_the_lease(session, shop):
    """A job served before the claim existed (no holder) is accepted from the first reporter."""
    seeded, ids = shop
    await _approve(session, seeded, ids[0])
    (row,) = (await session.scalars(select(ShopeeFillJob))).all()
    token_id = uuid.uuid4()
    out = await fill_queue.report(
        session, seeded.shop_id, row.id, status="opened", now=NOW, token_id=token_id
    )
    assert out["status"] == "opened"
    held = await _job(session, str(row.id))
    assert held.claimed_by_token_id == token_id and held.lease_until == NOW + cs.FILL_LEASE


# ----------------------------------------------------------------------------- L2 / L3 (routes)

TICK = {
    "platform": "shopee",
    "kind": "run",
    "trigger": "daily",
    "result": "finished",
    "day": "2026-11-18",
    "occurred_at": "2026-11-18T03:00:00Z",
    "outcomes": {},
}


async def test_each_computer_keeps_its_own_state_and_the_shop_row_is_the_aggregate(session, shop):
    seeded, _ = shop
    first, second = await _two_computers(session, seeded)
    app = build_app(session)
    async with client_for(app) as a, client_for(app) as b:
        a.headers.update(first)
        b.headers.update(second)
        blocked = {**TICK, "source_version": "0.3.25", "outcomes": {"traffic": "blocked:login"}}
        clean = {
            **TICK,
            "source_version": "0.3.24",
            "outcomes": {"traffic": "done:traffic_overview=posted"},
        }
        assert (await a.post(TICKS, json=blocked)).status_code == 202
        assert (await b.post(TICKS, json=clean)).status_code == 202  # last writer, no block
        assert (await b.get(JOBS, params={"sc_open": "false"})).status_code == 200
        assert (await a.get(JOBS, params={"sc_open": "true"})).status_code == 200
    app.dependency_overrides.clear()
    states = (
        await session.scalars(
            select(ShopeeConnectorTokenState).where(
                ShopeeConnectorTokenState.shop_id == seeded.shop_id
            )
        )
    ).all()
    assert len(states) == 2
    shop_row = await session.get(ShopeeConnectorState, seeded.shop_id)
    await session.refresh(shop_row)
    assert shop_row.connector_version == "0.3.25"  # newest, not the last writer's
    assert shop_row.seller_centre_open is True
    assert shop_row.reader_blocks == [
        {"section": "phan_tich_ban_hang", "reason": "login", "readers": ["traffic"]}
    ]
    out = await cs.read(session, seeded.shop_id, now=_wall())
    assert set(out) == {
        "heartbeat_at", "alive", "seller_centre_open", "connector_version",
        "reconcile_pending", "reader_blocks", "computers",
    }  # fmt: skip
    assert out["alive"] is True and out["seller_centre_open"] is True
    assert out["reader_blocks"] == shop_row.reader_blocks
    assert sorted(c["version"] for c in out["computers"]) == ["0.3.24", "0.3.25"]
    assert all(c["alive"] and c["label"] == "Juli Connector test" for c in out["computers"])


async def test_the_clear_on_ingest_clears_the_block_for_every_computer(session, shop):
    seeded, _ = shop
    before = _wall() - timedelta(hours=1)
    for _ in range(2):
        session.add(
            ShopeeConnectorTokenState(
                token_id=uuid.uuid4(), shop_id=seeded.shop_id, heartbeat_at=before,
                reader_blocks=[BLOCK_A, LOGIN], reader_blocks_at=before,
            )
        )  # fmt: skip
    session.add(
        ShopeeConnectorState(
            shop_id=seeded.shop_id, reader_blocks=[BLOCK_A, LOGIN], reader_blocks_at=before
        )
    )
    await session.flush()
    await cs.clear_blocks_for_dataset(
        session, seeded.shop_id, "traffic_overview", captured_at=_wall()
    )
    rows = (await session.scalars(select(ShopeeConnectorTokenState))).all()
    assert [r.reader_blocks for r in rows] == [[LOGIN], [LOGIN]]
    shop_row = await session.get(ShopeeConnectorState, seeded.shop_id)
    assert shop_row.reader_blocks == [LOGIN]
    assert (await cs.read(session, seeded.shop_id, now=_wall()))["reader_blocks"] == [LOGIN]


async def test_without_a_token_the_shop_row_is_written_as_before(session, shop):
    seeded, _ = shop
    await cs.record_heartbeat(
        session, seeded.shop_id, seller_centre_open=True, ack=None, now=NOW, version="0.3.20"
    )
    out = await cs.read(session, seeded.shop_id, now=NOW)
    assert out["alive"] is True and out["connector_version"] == "0.3.20"
    assert out["computers"] == [] and out["reader_blocks"] == []
