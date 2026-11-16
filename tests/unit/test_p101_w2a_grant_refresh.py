"""P101 W2a: the credentials of one TikTok grant refresh as one unit.

TikTok Shop rotates the refresh token on every refresh, so the sibling credentials one grant wrote
(one per authorised shop) must receive the new tokens in the same transaction, serialised by one
per-grant lock. SQLite twin: the sibling enumeration runs as a plain query here (migration 132's
``SECURITY DEFINER`` function on PostgreSQL), and the advisory lock always "acquires".
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from juli_backend.core.security import credential_refresh
from juli_backend.core.security.credential_refresh import RefreshStatus, refresh_credential
from juli_backend.core.security.tiktok_oauth import TikTokOAuthService
from juli_backend.database.token_crypto import decrypt_token
from juli_backend.integrations.tiktok import TikTokAuth, TikTokCapability
from juli_backend.models.models import TikTokCredential
from juli_backend.repositories.repos import TikTokCredentialRepo
from juli_backend.services.tiktok import credential_binding
from juli_backend.services.tiktok.credential_binding import make_binding_verifier
from tests.support.builders import make_shop, make_user

REPO = Path(__file__).resolve().parents[2]
MIGRATION = (
    REPO / "backend/src/juli_backend/database/migrations/versions/132_credential_grant_id.py"
)
MERCHANT = "merchant-w2a-grant"
CAP = TikTokCapability.SELLER_CONNECT.value


def _soon() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1)


def _auth() -> MagicMock:
    auth = MagicMock()
    auth.refresh_access_token = MagicMock(
        return_value={
            "access_token": "rotated-access",
            "refresh_token": "rotated-refresh",
            "access_token_expire_in": 604800,
        }
    )
    return auth


async def _cred(session, shop, *, grant_id, merchant=MERCHANT) -> TikTokCredential:
    return await TikTokCredentialRepo(session).create(
        shop.id,
        "old-access",
        "old-refresh",
        _soon(),
        merchant_authorization_id=merchant,
        capability=CAP,
        grant_id=grant_id,
    )


async def _tokens(session, credential_id) -> tuple[str, str]:
    row = await session.get(TikTokCredential, credential_id, populate_existing=True)
    return decrypt_token(row.access_token), decrypt_token(row.refresh_token)


@pytest.fixture
async def grant(session):
    """Shops A and B of one grant; C another account's, D another merchant's (same grant id)."""
    grant_id = uuid.uuid4()
    owner = await make_user(session)
    stranger = await make_user(session)
    shop_a = await make_shop(session, owner)
    shop_b = await make_shop(session, owner)
    shop_d = await make_shop(session, owner)
    shop_c = await make_shop(session, stranger)
    creds = {
        "a": await _cred(session, shop_a, grant_id=grant_id),
        "b": await _cred(session, shop_b, grant_id=grant_id),
        "c": await _cred(session, shop_c, grant_id=grant_id),
        "d": await _cred(session, shop_d, grant_id=grant_id, merchant="another-merchant"),
    }
    await session.commit()
    return creds


async def test_refreshing_shop_a_rotates_shop_b_in_the_same_transaction(session, grant):
    auth = _auth()

    outcome = await refresh_credential(session, grant["a"].id, auth=auth)

    assert outcome.status is RefreshStatus.REFRESHED
    assert await _tokens(session, grant["a"].id) == ("rotated-access", "rotated-refresh")
    assert await _tokens(session, grant["b"].id) == ("rotated-access", "rotated-refresh")
    b = await session.get(TikTokCredential, grant["b"].id, populate_existing=True)
    a = await session.get(TikTokCredential, grant["a"].id, populate_existing=True)
    assert b.token_expires_at == a.token_expires_at
    assert b.refresh_count == 1


async def test_a_sibling_on_another_account_or_merchant_is_never_touched(session, grant):
    await refresh_credential(session, grant["a"].id, auth=_auth())

    assert await _tokens(session, grant["c"].id) == ("old-access", "old-refresh")
    assert await _tokens(session, grant["d"].id) == ("old-access", "old-refresh")


async def test_the_sibling_refreshes_without_a_second_vendor_call(session, grant):
    auth = _auth()
    await refresh_credential(session, grant["a"].id, auth=auth)

    outcome = await refresh_credential(session, grant["b"].id, auth=auth)

    assert outcome.status is RefreshStatus.FRESH
    assert auth.refresh_access_token.call_count == 1


async def test_concurrent_refreshes_of_one_grant_share_one_lock_and_one_vendor_call(
    session, grant, monkeypatch
):
    """B arrives while A holds the grant lock; A finishes (writing B) while B polls."""
    auth = _auth()
    real_lock = credential_refresh._try_advisory_lock
    keys: list[str] = []

    async def lock(sess, key):
        keys.append(str(key))
        if len(keys) == 1:  # B's attempt: A holds the grant lock and completes meanwhile
            await refresh_credential(sess, grant["a"].id, auth=auth)
            return False, None
        return await real_lock(sess, key)

    monkeypatch.setattr(credential_refresh, "_try_advisory_lock", lock)

    outcome = await refresh_credential(session, grant["b"].id, auth=auth)

    assert outcome.status is RefreshStatus.REFRESHED
    assert auth.refresh_access_token.call_count == 1
    assert keys[0] == keys[1] == f"tiktok_grant:{grant['a'].grant_id}"
    assert await _tokens(session, grant["b"].id) == ("rotated-access", "rotated-refresh")


async def test_a_credential_without_a_grant_locks_on_itself_and_has_no_siblings(session):
    owner = await make_user(session)
    lone = await _cred(session, await make_shop(session, owner), grant_id=None)

    assert credential_refresh._lock_key(lone) == str(lone.id)
    assert await credential_refresh._grant_siblings(session, lone) == []


async def test_one_provision_stamps_one_grant_and_a_regrant_a_new_one(session, monkeypatch):
    grant_shops = [
        {"id": "7400000000000000011", "cipher": "ROW_g_a", "name": "A"},
        {"id": "7400000000000000012", "cipher": "ROW_g_b", "name": "B"},
    ]
    monkeypatch.setattr(credential_binding, "resolve_authorized_shops", lambda **_k: grant_shops)
    service = TikTokOAuthService(
        tiktok_auth=TikTokAuth(app_key="k", app_secret="s", base_url="https://example.test"),
        session=session,
        redirect_uri="https://example.test/cb",
        app_secret="s",
        binding_verifier=make_binding_verifier(app_key="k", app_secret="s"),
    )
    token = {
        "open_id": MERCHANT,
        "access_token": "t",
        "refresh_token": "r",
        "access_token_expire_in": 604800,
    }
    user = await make_user(session)

    async def grant_ids(shops):
        repo = TikTokCredentialRepo(session)
        return {(await repo.get_by_shop(shop.id)).grant_id for shop in shops}

    first = await grant_ids(await service.provision_shops_and_credentials(token, user_id=user.id))
    again = await grant_ids(await service.provision_shops_and_credentials(token, user_id=user.id))

    assert len(first) == 1 and None not in first
    assert len(again) == 1 and again != first


def test_migration_is_additive_literal_and_short_enough():
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location("m132", MIGRATION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.revision == "132_credential_grant_id" and len(mod.revision) <= 32
    assert mod.down_revision == "131_connector_reader_blocks"
    sys.path.insert(0, str(REPO / "infra/scripts"))
    from migration_additive_gate import evaluate_migration_paths

    result = evaluate_migration_paths([MIGRATION])
    assert [f.render() for f in result.findings] == [] and result.accepted
    text = MIGRATION.read_text("utf-8")
    up, down = text.split("def downgrade")
    assert "SECURITY DEFINER" in up and "SET search_path = pg_catalog, public" in up
    assert "c.shop_id = app_current_shop_id()" in up
    assert "os.user_id = cs.user_id" in up
    assert "FROM PUBLIC" in up and "TO juli_app" in up
    assert 'f"' not in text  # literal SQL only
    assert "DROP FUNCTION IF EXISTS public.enumerate_grant_sibling_credentials(uuid)" in down
    assert 'drop_column("tiktok_credentials", "grant_id")' in down
