"""Terms acceptance grants consent, and the operator commands (ADR-116 §2, owner D10).

SQLite: proves which scopes are granted to which shops, idempotence, that a failed
consent write never breaks acceptance or connect, and the CLI's dry run / apply /
re-run. RLS under the real roles is ``tests/integration/test_data_use_consents_db.py``.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import UTC, date, datetime
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from juli_backend.integrations.tiktok.auth import TikTokAuth
from juli_backend.models.consent import DataUseConsent
from juli_backend.services import privacy
from juli_backend.services.consent import cli
from juli_backend.services.consent import terms as terms_module
from juli_backend.services.consent.terms import (
    TERMS_SCOPES,
    grant_terms_consents_if_accepted,
)
from juli_backend.services.privacy.terms import LEGAL_TERMS_DATE
from juli_backend.services.tiktok import oauth as oauth_module
from juli_backend.services.tiktok.oauth import (
    TikTokOAuthInfrastructureService,
    begin_tiktok_oauth,
    complete_tiktok_oauth_callback,
)
from tests.support.builders import make_shop, make_tenant, make_user

ACCEPTED = datetime(2026, 10, 20, 2, 30, tzinfo=UTC)
APP_SECRET = "test_app_secret"


async def _open_scopes(session, shop_id) -> dict[str, DataUseConsent]:
    rows = (
        await session.execute(
            select(DataUseConsent).where(
                DataUseConsent.shop_id == shop_id, DataUseConsent.revoked_at.is_(None)
            )
        )
    ).scalars()
    return {row.scope: row for row in rows}


async def _count(session) -> int:
    return (await session.execute(select(func.count()).select_from(DataUseConsent))).scalar_one()


async def _accept(session, user_id, now=ACCEPTED):
    return await privacy.record_consent(
        session, user_id, terms_date=LEGAL_TERMS_DATE, liability_clause=True, now=now
    )


# -- terms acceptance -----------------------------------------------------------------


async def test_accepting_the_terms_grants_the_four_scopes_to_every_owned_shop(session):
    user, shop = await make_tenant(session)
    second = await make_shop(session, user)
    _, stranger = await make_tenant(session)

    await _accept(session, user.id)

    for shop_id in (shop.id, second.id):
        grants = await _open_scopes(session, shop_id)
        assert set(grants) == set(TERMS_SCOPES)
        for grant in grants.values():
            assert grant.method == "in_app_click"
            assert grant.terms_version == LEGAL_TERMS_DATE.isoformat()
            assert grant.evidence_ref == f"users.terms_accepted_at:{user.id}"
            assert grant.granted_by == str(user.id)
            assert grant.granted_at == ACCEPTED.replace(tzinfo=None)
    assert await _open_scopes(session, stranger.id) == {}


async def test_accepting_again_is_idempotent(session):
    user, shop = await make_tenant(session)
    await _accept(session, user.id)
    first = {scope: grant.id for scope, grant in (await _open_scopes(session, shop.id)).items()}

    await _accept(session, user.id, now=datetime(2026, 10, 22, tzinfo=UTC))

    again = {scope: grant.id for scope, grant in (await _open_scopes(session, shop.id)).items()}
    assert again == first
    assert await _count(session) == len(TERMS_SCOPES)


async def test_terms_never_grant_pooled_training(session):
    user, shop = await make_tenant(session)
    await _accept(session, user.id)
    assert "pooled_training" not in TERMS_SCOPES
    assert "pooled_training" not in await _open_scopes(session, shop.id)


async def test_a_failed_consent_write_does_not_break_acceptance(session, monkeypatch, caplog):
    user, shop = await make_tenant(session)

    async def boom(*args, **kwargs):
        raise RuntimeError("consent store down")

    monkeypatch.setattr(terms_module, "grant_consent", boom)
    with caplog.at_level(logging.WARNING, logger=terms_module.__name__):
        state = await _accept(session, user.id)

    assert state.terms_date_accepted == LEGAL_TERMS_DATE
    assert state.needs_terms_acceptance is False
    assert (await privacy.get_privacy(session, user.id)).terms_accepted_at is not None
    assert await _open_scopes(session, shop.id) == {}
    failures = [r for r in caplog.records if r.getMessage() == "consent_terms_grant_failed"]
    assert len(failures) == 1
    assert failures[0].shop_id == str(shop.id) and failures[0].error_type == "RuntimeError"
    assert str(user.id) not in caplog.text


async def test_the_acceptance_route_grants_consent(session):
    from juli_backend.core.security import get_current_user
    from tests.support.api import build_app, client_for

    user, shop = await make_tenant(session)
    app = build_app(session)

    async def current():
        await session.refresh(user)
        return user

    app.dependency_overrides[get_current_user] = current
    async with client_for(app) as client:
        resp = await client.post(
            "/v1/me/consents", json={"terms_date": "2026-10-18", "liability_clause": True}
        )
    assert resp.status_code == 200
    assert set(await _open_scopes(session, shop.id)) == set(TERMS_SCOPES)


# -- a shop connected after acceptance ------------------------------------------------


async def test_without_terms_a_shop_gets_nothing(session):
    user, shop = await make_tenant(session)
    result = await grant_terms_consents_if_accepted(session, user.id, [shop.id])
    assert result.granted == 0
    assert await _count(session) == 0


def _connect_service():
    tiktok_auth = TikTokAuth(app_key="test_app_key", app_secret=APP_SECRET)
    service = TikTokOAuthInfrastructureService(app_secret=APP_SECRET, tiktok_auth=tiktok_auth)
    return service, tiktok_auth


async def _connect(session, user_id, open_id):
    service, tiktok_auth = _connect_service()
    tiktok_auth.exchange_code = MagicMock(
        return_value={
            "access_token": f"ROW_access_{open_id}",
            "refresh_token": f"ROW_refresh_{open_id}",
            "access_token_expire_in": 604800,
            "open_id": open_id,
            "seller_name": "Shop",
        }
    )
    started = begin_tiktok_oauth(user_id, oauth_service=service)
    state = parse_qs(urlparse(started.authorize_url).query)["state"][0]
    await complete_tiktok_oauth_callback(session, code="code", state=state, oauth_service=service)


async def _shop_of(session, open_id):
    from juli_backend.models.models import Shop

    return (await session.execute(select(Shop).where(Shop.tiktok_shop_id == open_id))).scalar_one()


async def test_a_shop_connected_after_acceptance_gets_the_four_scopes(session, monkeypatch):
    monkeypatch.setattr(oauth_module, "is_production", lambda: False)
    user = await make_user(session)
    await _accept(session, user.id)

    await _connect(session, user.id, "late_shop")

    grants = await _open_scopes(session, (await _shop_of(session, "late_shop")).id)
    assert set(grants) == set(TERMS_SCOPES)
    assert {g.terms_version for g in grants.values()} == {LEGAL_TERMS_DATE.isoformat()}


async def test_a_shop_connected_without_acceptance_gets_nothing(session, monkeypatch):
    monkeypatch.setattr(oauth_module, "is_production", lambda: False)
    user = await make_user(session)

    await _connect(session, user.id, "no_terms_shop")

    assert await _open_scopes(session, (await _shop_of(session, "no_terms_shop")).id) == {}


async def test_a_failed_consent_write_does_not_break_connect(session, monkeypatch):
    monkeypatch.setattr(oauth_module, "is_production", lambda: False)
    user = await make_user(session)
    await _accept(session, user.id)

    async def boom(*args, **kwargs):
        raise RuntimeError("consent store down")

    monkeypatch.setattr(terms_module, "grant_consent", boom)
    await _connect(session, user.id, "connect_survives")

    shop = await _shop_of(session, "connect_survives")
    assert shop.user_id == user.id
    assert await _open_scopes(session, shop.id) == {}


# -- operator CLI ---------------------------------------------------------------------


@pytest.fixture
def factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


async def _seed(factory):
    """Two accepting owners (one with two shops), one owner who never accepted."""
    async with factory() as session:
        accepted, shop_a = await make_tenant(session)
        shop_b = await make_shop(session, accepted)
        other, shop_c = await make_tenant(session)
        never, shop_d = await make_tenant(session)
        for user in (accepted, other):
            user.terms_date_accepted = LEGAL_TERMS_DATE
            user.terms_accepted_at = ACCEPTED
        await session.commit()
        return [shop_a.id, shop_b.id, shop_c.id], shop_d.id


async def _total(factory) -> int:
    async with factory() as session:
        return await _count(session)


async def _run(factory, *argv) -> tuple[int, str]:
    return await cli.run_command(cli.build_parser().parse_args(list(argv)), factory)


async def test_backfill_dry_run_writes_nothing_apply_writes_rerun_is_a_noop(factory):
    accepted_shops, never_shop = await _seed(factory)

    code, out = await _run(factory, "backfill-terms")
    assert code == 0
    assert "DRY RUN" in out and "owners=3" in out and "owners_accepted=2" in out
    assert "shops=3" in out and "to_grant=12" in out
    assert await _total(factory) == 0

    code, out = await _run(factory, "backfill-terms", "--apply")
    assert code == 0 and "granted=12" in out and "already_open=0" in out
    async with factory() as session:
        for shop_id in accepted_shops:
            assert set(await _open_scopes(session, shop_id)) == set(TERMS_SCOPES)
        assert await _open_scopes(session, never_shop) == {}

    code, out = await _run(factory, "backfill-terms", "--apply")
    assert code == 0 and "granted=0" in out and "already_open=12" in out
    assert await _total(factory) == 12


async def test_backfill_prints_counts_only(factory):
    await _seed(factory)
    _, out = await _run(factory, "backfill-terms")
    assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-", out)
    assert "@" not in out and "Shop-" not in out


FUJIWA_SCOPES = ("service", "llm_processing", "llm_images", "llm_media", "pooled_training")


def _grant_args(shop_id, *extra):
    args = ["grant", "--shop-id", str(shop_id)]
    for scope in FUJIWA_SCOPES:
        args += ["--scope", scope]
    args += [
        "--method",
        "contract_paper",
        "--terms-version",
        "fujiwa-hd-2026",
        "--evidence-ref",
        "contract/fujiwa.pdf",
        "--evidence-sha256",
        "ab" * 32,
        "--granted-by",
        "Fujiwa director",
        "--granted-at",
        "2026-10-24T09:00:00",
    ]
    return [*args, *extra]


async def test_grant_dry_run_then_apply_then_rerun(factory):
    async with factory() as session:
        _, shop = await make_tenant(session)
        await session.commit()

    code, out = await _run(factory, *_grant_args(shop.id))
    assert code == 0 and out.count("would_grant") == 5
    assert await _total(factory) == 0

    code, out = await _run(factory, *_grant_args(shop.id, "--apply"))
    assert code == 0 and out.count(": granted") == 5
    async with factory() as session:
        grants = await _open_scopes(session, shop.id)
    assert set(grants) == set(FUJIWA_SCOPES)
    assert grants["pooled_training"].evidence_sha256 == "ab" * 32
    assert grants["service"].granted_at == datetime(2026, 10, 24, 9, 0)

    code, out = await _run(factory, *_grant_args(shop.id, "--apply"))
    assert code == 0 and out.count("already_open") == 5
    assert await _total(factory) == 5


async def test_a_malformed_grant_writes_nothing(factory):
    async with factory() as session:
        _, shop = await make_tenant(session)
        await session.commit()
    args = _grant_args(shop.id, "--apply")
    args[args.index("--evidence-sha256") + 1] = "not-a-hash"
    code, out = await _run(factory, *args)
    assert code == 2 and "nothing written" in out
    assert await _total(factory) == 0


async def test_revoke_dry_run_then_apply(factory):
    async with factory() as session:
        _, shop = await make_tenant(session)
        await session.commit()
    await _run(factory, *_grant_args(shop.id, "--apply"))

    code, out = await _run(
        factory, "revoke", "--shop-id", str(shop.id), "--scope", "pooled_training"
    )
    assert code == 0 and "would_revoke" in out
    async with factory() as session:
        assert "pooled_training" in await _open_scopes(session, shop.id)

    code, out = await _run(
        factory, "revoke", "--shop-id", str(shop.id), "--scope", "pooled_training", "--apply"
    )
    assert code == 0 and "revoked" in out
    async with factory() as session:
        assert set(await _open_scopes(session, shop.id)) == set(TERMS_SCOPES)

    code, out = await _run(
        factory, "revoke", "--shop-id", str(shop.id), "--scope", "pooled_training", "--apply"
    )
    assert code == 0 and "no_open_grant" in out


def test_the_cli_refuses_an_unknown_scope_or_method():
    parser = cli.build_parser()
    shop = str(uuid.uuid4())
    with pytest.raises(SystemExit) as info:
        parser.parse_args(["revoke", "--shop-id", shop, "--scope", "everything"])
    assert info.value.code == 2
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "grant",
                "--shop-id",
                shop,
                "--scope",
                "service",
                "--method",
                "handshake",
                "--terms-version",
                "v",
                "--evidence-ref",
                "e",
                "--granted-by",
                "g",
            ]
        )


def test_terms_version_is_the_legal_text_date():
    assert terms_module.terms_version_of(date(2026, 10, 18)) == "2026-10-18"
