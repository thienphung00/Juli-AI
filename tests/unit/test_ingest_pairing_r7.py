"""R7 (P1, P3): a re-pair from the same install supersedes; the minimum Connector version."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from juli_backend.models.ingest import IngestToken
from juli_backend.services import ingest as svc
from juli_backend.services.ingest import min_version
from juli_backend.services.ingest.rate_limit import InMemoryRateGate, set_ingest_rate_gate
from tests.support.api import authenticate, build_app, client_for
from tests.support.builders import make_tenant
from tests.support.consent import grant_service_consent

NOW = datetime(2026, 11, 18, 3, 0)
INSTALL_A = "inst_aaaaaaaaaaaa"
INSTALL_B = "inst_bbbbbbbbbbbb"


@pytest.fixture(autouse=True)
def generous_gate():
    set_ingest_rate_gate(InMemoryRateGate())
    yield
    set_ingest_rate_gate(None)


async def _shop(session):
    user, shop = await make_tenant(session, platform="shopee", tiktok_shop_id=None)
    await grant_service_consent(session, shop.id)
    return user, shop


async def _pair(session, shop, install_id, now):
    code = (await svc.create_pairing_code(session, shop=shop, user_id=shop.user_id, now=now)).code
    return await svc.redeem_pairing_code(
        session,
        code=code,
        platform="shopee",
        platform_shop_id=None,
        client_label=None,
        install_id=install_id,
        now=now,
    )


async def test_a_re_pair_of_the_same_install_supersedes_the_older_token(session):
    _, shop = await _shop(session)
    first = await _pair(session, shop, INSTALL_A, NOW)
    other = await _pair(session, shop, INSTALL_B, NOW)
    second = await _pair(session, shop, INSTALL_A, NOW + timedelta(days=1))
    rows = {t.id: t for t in (await session.execute(select(IngestToken))).scalars()}
    assert rows[first.token_id].superseded_at == NOW + timedelta(days=1)
    assert rows[first.token_id].install_id == INSTALL_A
    assert rows[second.token_id].superseded_at is None
    assert rows[other.token_id].superseded_at is None  # another computer is untouched
    later = NOW + timedelta(days=1, minutes=11)  # past the rotation grace
    assert await svc.resolve_token(session, first.token, later) is None
    assert await svc.resolve_token(session, second.token, later) is not None
    assert await svc.resolve_token(session, other.token, later) is not None


async def test_a_pairing_without_an_install_id_supersedes_nothing(session):
    _, shop = await _shop(session)
    first = await _pair(session, shop, None, NOW)
    await _pair(session, shop, None, NOW + timedelta(hours=1))
    row = await session.get(IngestToken, first.token_id)
    assert row is not None and row.superseded_at is None


def test_minimum_version_compares_numerically_and_lets_unnamed_versions_through(monkeypatch):
    monkeypatch.delenv(min_version.ENV_MIN_VERSION, raising=False)
    assert min_version.minimum() == "0.3.31"
    assert min_version.is_too_old("0.3.30")
    assert min_version.is_too_old("0.2.99")
    assert not min_version.is_too_old("0.3.31")
    assert not min_version.is_too_old("0.3.32")
    assert not min_version.is_too_old("0.3.100")
    assert not min_version.is_too_old("0.10.0")
    assert not min_version.is_too_old(None)
    assert not min_version.is_too_old("")
    monkeypatch.setenv(min_version.ENV_MIN_VERSION, "not a version")
    assert min_version.minimum() == "0.3.31"
    monkeypatch.setenv(min_version.ENV_MIN_VERSION, "0.4.0")
    assert min_version.is_too_old("0.3.31")


def test_an_unnamed_version_is_refused_only_for_a_connector_paired_token(monkeypatch):
    monkeypatch.delenv(min_version.ENV_MIN_VERSION, raising=False)
    assert min_version.made_by_connector("inst_x", None)
    assert min_version.made_by_connector(None, "Juli Connector 0.3.30")
    assert not min_version.made_by_connector(None, None)
    assert not min_version.made_by_connector(None, "loader")
    assert min_version.refuses(None, from_connector=True)
    assert min_version.refuses("seller-centre-xlsx-1", from_connector=True)
    assert not min_version.refuses(None, from_connector=False)
    assert not min_version.refuses("seller-centre-xlsx-1", from_connector=False)
    assert min_version.refuses("0.3.30", from_connector=False)
    assert not min_version.refuses("0.3.31", from_connector=True)


async def _token(session, shop, user):
    app = build_app(session)
    authenticate(app, user=user, shop=shop)
    async with client_for(app) as seller:
        code = (await seller.post("/v1/ingest/pairing-codes")).json()["code"]
    app.dependency_overrides.clear()
    app = build_app(session)
    async with client_for(app) as ext:
        paired = await ext.post("/v1/ingest/pair", json={"code": code, "install_id": INSTALL_A})
    assert paired.status_code == 200, paired.text
    return app, {"Authorization": f"Bearer {paired.json()['token']}"}


async def test_an_old_connector_gets_upgrade_required_and_nothing_is_written(session):
    user, shop = await _shop(session)
    app, auth = await _token(session, shop, user)
    async with client_for(app) as ext:
        old = await ext.get("/v1/ingest/status", headers={**auth, "X-Connector-Version": "0.3.30"})
        assert old.status_code == 426
        assert old.json()["detail"] == {
            "code": "connector_upgrade_required",
            "minimum": "0.3.31",
        }
        body = {
            "period_start": "2026-11-17",
            "period_end": "2026-11-17",
            "source_version": "0.3.20",
            "rows": [],
        }
        by_body = await ext.post("/v1/ingest/shopee/traffic_overview", headers=auth, json=body)
        assert by_body.status_code == 426
        assert by_body.json()["detail"]["code"] == "connector_upgrade_required"
        poll = await ext.get(
            "/v1/ingest/fill-jobs", headers={**auth, "X-Connector-Version": "0.3.1"}
        )
        assert poll.status_code == 426
        ok = await ext.get("/v1/ingest/status", headers={**auth, "X-Connector-Version": "0.3.31"})
        assert ok.status_code == 200
        # C5a: this token was paired by a Connector (install id), so a silent request is older.
        unnamed = await ext.get("/v1/ingest/status", headers=auth)
        assert unnamed.status_code == 426
        assert unnamed.json()["detail"]["code"] == "connector_upgrade_required"


async def test_a_loader_token_without_a_connector_version_still_posts(session, monkeypatch):
    """The export loader (scripts/load_shopee_exports.py) pairs with no install id and no
    Connector label and posts ``source_version`` "seller-centre-xlsx-1": still accepted."""
    monkeypatch.delenv(min_version.ENV_MIN_VERSION, raising=False)
    _, shop = await _shop(session)
    issued = await _pair(session, shop, None, NOW)
    await session.commit()
    auth = {"Authorization": f"Bearer {issued.token}"}
    app = build_app(session)
    async with client_for(app) as loader:
        status_ = await loader.get("/v1/ingest/status", headers=auth)
        assert status_.status_code == 200, status_.text
        body = {
            "source": "file",
            "source_version": "seller-centre-xlsx-1",
            "captured_at": "2026-11-17T03:00:00Z",
            "period": {"start": "2026-11-17", "end": "2026-11-17", "granularity": "day"},
            "rows": [],
        }
        posted = await loader.post("/v1/ingest/shopee/traffic_overview", headers=auth, json=body)
        assert posted.status_code != 426, posted.text


async def test_a_connector_label_token_without_a_version_is_refused(session):
    """A token from a Connector older than the install id (label "Juli Connector <v>" only)."""
    _, shop = await _shop(session)
    code = (await svc.create_pairing_code(session, shop=shop, user_id=shop.user_id, now=NOW)).code
    issued = await svc.redeem_pairing_code(
        session,
        code=code,
        platform="shopee",
        platform_shop_id=None,
        client_label="Juli Connector 0.3.22",
        install_id=None,
        now=NOW,
    )
    await session.commit()
    app = build_app(session)
    async with client_for(app) as ext:
        got = await ext.get(
            "/v1/ingest/status", headers={"Authorization": f"Bearer {issued.token}"}
        )
    assert got.status_code == 426
    assert got.json()["detail"] == {"code": "connector_upgrade_required", "minimum": "0.3.31"}


async def test_the_token_list_carries_each_computers_version_and_last_seen(session):
    from juli_backend.models.shopee_connector import ShopeeConnectorTokenState

    user, shop = await _shop(session)
    first = await _pair(session, shop, INSTALL_A, NOW)
    second = await _pair(session, shop, INSTALL_B, NOW)
    session.add(
        ShopeeConnectorTokenState(
            token_id=first.token_id,
            shop_id=shop.id,
            connector_version="0.3.25",
            heartbeat_at=NOW + timedelta(hours=2),
        )
    )
    await session.commit()
    app = build_app(session)
    authenticate(app, user=user, shop=shop)
    async with client_for(app) as seller:
        listed = (await seller.get("/v1/ingest/tokens")).json()["data"]
    by_id = {t["id"]: t for t in listed}
    assert by_id[str(first.token_id)]["connector_version"] == "0.3.25"
    assert by_id[str(first.token_id)]["last_seen_at"] == "2026-11-18T05:00:00Z"
    assert by_id[str(second.token_id)]["connector_version"] is None
    assert by_id[str(second.token_id)]["last_seen_at"] is None
    assert by_id[str(second.token_id)]["install_id"] == INSTALL_B


async def test_revoke_inactive_takes_only_this_shops_computers_not_seen_for_14_days(session):
    """F6.5: the bulk revoke is per shop and only for the old ones."""
    _, shop = await _shop(session)
    _, other_shop = await _shop(session)
    old = await _pair(session, shop, INSTALL_A, NOW - timedelta(days=30))
    recent = await _pair(session, shop, INSTALL_B, NOW - timedelta(days=2))
    foreign = await _pair(session, other_shop, INSTALL_A, NOW - timedelta(days=30))
    shop_id, other_id = shop.id, other_shop.id
    revoked = await svc.revoke_inactive(session, shop_id=shop_id, reason="seller_inactive", now=NOW)
    assert revoked == 1
    rows = {t.id: t for t in (await session.execute(select(IngestToken))).scalars()}
    assert rows[old.token_id].revoked_at == NOW
    assert rows[recent.token_id].revoked_at is None
    assert rows[foreign.token_id].revoked_at is None  # another shop's old token is untouched
    assert (
        await svc.revoke_inactive(session, shop_id=shop_id, reason="seller_inactive", now=NOW) == 0
    )
    assert other_id != shop_id


async def test_the_revoke_inactive_routes_answer_with_the_count(session):
    user, shop = await _shop(session)
    await _pair(session, shop, INSTALL_A, datetime(2020, 1, 1))
    app = build_app(session)
    authenticate(app, user=user, shop=shop)
    async with client_for(app) as client:
        r = await client.post("/v1/ingest/tokens/revoke-inactive")
        assert r.status_code == 200, r.text
        assert r.json() == {"revoked": 1}
    app.dependency_overrides.clear()


# -- batch-1124-a C2: rotation keeps the install; a re-pair retires the whole chain ---------------


async def _rotate(session, issued, now):
    principal = await svc.resolve_token(session, issued.token, now)
    assert principal is not None
    return await svc.rotate_token(session, principal, now=now)


async def test_rotation_keeps_the_install_id_and_the_client_label(session):
    _, shop = await _shop(session)
    code = (await svc.create_pairing_code(session, shop=shop, user_id=shop.user_id, now=NOW)).code
    first = await svc.redeem_pairing_code(
        session,
        code=code,
        platform="shopee",
        platform_shop_id=None,
        client_label="Juli Connector 0.3.35",
        install_id=INSTALL_A,
        now=NOW,
    )
    child = await _rotate(session, first, NOW + timedelta(days=30))
    row = await session.get(IngestToken, child.token_id)
    assert row is not None
    assert (row.install_id, row.client_label) == (INSTALL_A, "Juli Connector 0.3.35")
    assert row.rotated_from_id == first.token_id


async def test_a_re_pair_supersedes_the_rotated_child_too(session):
    _, shop = await _shop(session)
    first = await _pair(session, shop, INSTALL_A, NOW)
    child = await _rotate(session, first, NOW + timedelta(days=30))
    grandchild = await _rotate(session, child, NOW + timedelta(days=60))
    other = await _pair(session, shop, INSTALL_B, NOW)
    again = NOW + timedelta(days=61)
    fresh = await _pair(session, shop, INSTALL_A, again)
    later = again + timedelta(minutes=11)  # past the rotation grace
    assert await svc.resolve_token(session, grandchild.token, later) is None
    assert await svc.resolve_token(session, fresh.token, later) is not None
    assert await svc.resolve_token(session, other.token, later) is not None
    row = await session.get(IngestToken, grandchild.token_id)
    assert row is not None and row.superseded_at == again and row.install_id == INSTALL_A


async def test_a_legacy_child_rotated_without_an_install_id_is_found_through_its_chain(session):
    """Before 0.3.35's server a rotated child carried no install id; the re-pair still finds it
    through ``rotated_from_id`` and gives it its chain's install id."""
    _, shop = await _shop(session)
    first = await _pair(session, shop, INSTALL_A, NOW)
    child = await _rotate(session, first, NOW + timedelta(days=30))
    legacy = await session.get(IngestToken, child.token_id)
    assert legacy is not None
    legacy.install_id = None
    await session.flush()
    again = NOW + timedelta(days=31)
    await _pair(session, shop, INSTALL_A, again)
    await session.refresh(legacy)
    assert legacy.superseded_at == again and legacy.install_id == INSTALL_A
    assert await svc.resolve_token(session, child.token, again + timedelta(minutes=11)) is None
