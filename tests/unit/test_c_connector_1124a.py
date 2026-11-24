"""batch-1124-a C3 (server half): a dead token's fill-job leases are released at once.

A revoked or superseded token's leases are freed in the same transaction (not when they expire),
and a rotation moves them to the same browser's new token. Synthetic values only.
"""

from __future__ import annotations

import uuid

import pytest

from juli_backend.services import ingest as svc
from juli_backend.services.ingest.rate_limit import InMemoryRateGate, set_ingest_rate_gate
from tests.support.api import build_app, client_for
from tests.unit import test_r7_multi_computer as r7

shop = r7.shop  # the seeded reco shop fixture
JOBS = r7.JOBS


@pytest.fixture(autouse=True)
def _flag_on(monkeypatch):
    monkeypatch.setenv("CONNECTOR_MIN_VERSION", "0.0.0")
    monkeypatch.setenv("CONNECTOR_FILL_LISTING", "1")
    set_ingest_rate_gate(InMemoryRateGate())
    yield
    set_ingest_rate_gate(None)


async def _leased(session, seeded, ids):
    await r7._approve(session, seeded, ids[0])
    headers = await r7._token(session, seeded)
    app = build_app(session)
    async with client_for(app) as a:
        a.headers.update(headers)
        (job,) = (await a.get(JOBS)).json()["jobs"]
    app.dependency_overrides.clear()
    token_id = await r7._token_id(session, headers)
    assert (await r7._job(session, job["id"])).claimed_by_token_id == token_id
    return headers, token_id, job["id"]


async def test_revoking_a_token_releases_its_fill_job_lease_at_once(session, shop):
    seeded, ids = shop
    _, token_id, job_id = await _leased(session, seeded, ids)
    assert await svc.revoke_token(
        session, shop_id=seeded.shop_id, token_id=token_id, reason="test", now=r7._wall()
    )
    row = await r7._job(session, job_id)
    assert (row.claimed_by_token_id, row.lease_until) == (None, None)


async def test_a_re_pair_of_the_same_install_releases_the_old_tokens_lease(session, shop):
    seeded, ids = shop
    await r7._approve(session, seeded, ids[0])
    install = "inst_cccccccccccc"
    old = await _pair(session, seeded, install)
    app = build_app(session)
    async with client_for(app) as a:
        a.headers.update({"Authorization": f"Bearer {old.token}", "X-Connector-Version": "0.3.35"})
        (job,) = (await a.get(JOBS)).json()["jobs"]
    app.dependency_overrides.clear()
    assert (await r7._job(session, job["id"])).claimed_by_token_id == old.token_id
    await _pair(session, seeded, install)
    row = await r7._job(session, job["id"])
    assert (row.claimed_by_token_id, row.lease_until) == (None, None)


async def test_a_rotation_moves_the_lease_to_the_new_token(session, shop):
    seeded, ids = shop
    headers, token_id, job_id = await _leased(session, seeded, ids)
    before = (await r7._job(session, job_id)).lease_until
    principal = await svc.resolve_token(
        session, headers["Authorization"].split(" ", 1)[1], r7._wall()
    )
    assert principal is not None and principal.token_id == token_id
    issued = await svc.rotate_token(session, principal, now=r7._wall())
    row = await r7._job(session, job_id)
    assert row.claimed_by_token_id == issued.token_id and row.lease_until == before


async def _pair(session, seeded, install_id):
    created = await svc.create_pairing_code(
        session, shop=seeded.shop, user_id=seeded.user.id, now=r7._wall()
    )
    issued = await svc.redeem_pairing_code(
        session,
        code=created.code,
        platform="shopee",
        platform_shop_id="998877",
        client_label="Juli Connector test",
        install_id=install_id,
        now=r7._wall(),
    )
    await session.commit()
    assert isinstance(issued.token_id, uuid.UUID)
    return issued
