"""TDD tests for #1232 (AGT-W4A-WIRE, ADR-081 decision 1 row 2) --
`core/security/credential_resolver.py`'s lazy refresh layer:
`resolve_production_read_credential`/`resolve_sandbox_write_credential` now
call `refresh_credential(force=False)` after resolving, so a worker that was
down when the beat should have run still gets a warm token on the next
hot-path resolve.

The load-bearing property under test: **no vendor call on every hot-path
resolve** -- only when the resolved credential is inside the 24h
`REFRESH_BUFFER` window.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from juli_backend.core.security import credential_resolver
from juli_backend.core.security.credential_resolver import (
    build_refresh_auth_from_env,
    resolve_production_read_credential,
    resolve_sandbox_write_credential,
)
from juli_backend.integrations.tiktok import PRODUCTION_AUTH_ID, SANDBOX_AUTH_ID, TikTokCapability
from juli_backend.integrations.tiktok.auth import TikTokAuth
from juli_backend.repositories.repos import ShopsRepo, TikTokCredentialRepo

_shop_counter = 0


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def _seed_merchant_credential(
    session,
    user_id,
    *,
    merchant_authorization_id: str,
    capability: TikTokCapability,
    token_expires_at: datetime,
    access_token: str = "old-access",
    refresh_token: str = "old-refresh",
):
    global _shop_counter
    _shop_counter += 1
    shop = await ShopsRepo(session).create(user_id, f"Lazy Resolver Test Shop {_shop_counter}")
    return await TikTokCredentialRepo(session).create(
        shop_id=shop.id,
        access_token=access_token,
        refresh_token=refresh_token,
        token_expires_at=token_expires_at,
        merchant_authorization_id=merchant_authorization_id,
        capability=capability.value,
    )


def _auth_returning() -> MagicMock:
    auth = MagicMock()
    auth.refresh_access_token = MagicMock(
        return_value={
            "access_token": "lazily-refreshed-access",
            "refresh_token": "lazily-refreshed-refresh",
            "access_token_expire_in": 604800,
        }
    )
    return auth


class TestBuildRefreshAuthFromEnv:
    def test_returns_none_when_app_key_missing(self, monkeypatch):
        monkeypatch.delenv("TIKTOK_APP_KEY", raising=False)
        monkeypatch.delenv("TIKTOK_APP_SECRET", raising=False)
        assert build_refresh_auth_from_env() is None

    def test_returns_auth_when_configured(self, monkeypatch):
        monkeypatch.setenv("TIKTOK_APP_KEY", "k")
        monkeypatch.setenv("TIKTOK_APP_SECRET", "s")
        auth = build_refresh_auth_from_env()
        assert isinstance(auth, TikTokAuth)


class TestLazyTriggerFiresInsideWindowOnly:
    @pytest.mark.asyncio
    async def test_fires_for_production_read_credential_inside_24h_window(
        self, session, user_id, monkeypatch
    ):
        credential = await _seed_merchant_credential(
            session,
            user_id,
            merchant_authorization_id=PRODUCTION_AUTH_ID,
            capability=TikTokCapability.PRODUCTION_READ,
            token_expires_at=_utc_now() + timedelta(hours=1),
        )
        auth = _auth_returning()
        monkeypatch.setattr(credential_resolver, "build_refresh_auth_from_env", lambda: auth)

        resolved = await resolve_production_read_credential(session)

        auth.refresh_access_token.assert_called_once()
        assert resolved.access_token == "lazily-refreshed-access"
        refreshed_row = await session.get(type(credential), credential.id)
        assert refreshed_row.refresh_count == 1

    @pytest.mark.asyncio
    async def test_does_not_fire_for_production_read_credential_outside_24h_window(
        self, session, user_id, monkeypatch
    ):
        credential = await _seed_merchant_credential(
            session,
            user_id,
            merchant_authorization_id=PRODUCTION_AUTH_ID,
            capability=TikTokCapability.PRODUCTION_READ,
            token_expires_at=_utc_now() + timedelta(days=7),
        )
        auth = _auth_returning()
        monkeypatch.setattr(credential_resolver, "build_refresh_auth_from_env", lambda: auth)

        resolved = await resolve_production_read_credential(session)

        auth.refresh_access_token.assert_not_called()
        assert resolved.access_token == "old-access"
        untouched_row = await session.get(type(credential), credential.id)
        assert untouched_row.refresh_count == 0

    @pytest.mark.asyncio
    async def test_fires_for_sandbox_write_credential_inside_24h_window(
        self, session, user_id, monkeypatch
    ):
        credential = await _seed_merchant_credential(
            session,
            user_id,
            merchant_authorization_id=SANDBOX_AUTH_ID,
            capability=TikTokCapability.SANDBOX_WRITE,
            token_expires_at=_utc_now() + timedelta(hours=1),
        )
        auth = _auth_returning()
        monkeypatch.setattr(credential_resolver, "build_refresh_auth_from_env", lambda: auth)

        resolved = await resolve_sandbox_write_credential(session)

        auth.refresh_access_token.assert_called_once()
        assert resolved.access_token == "lazily-refreshed-access"
        refreshed_row = await session.get(type(credential), credential.id)
        assert refreshed_row.refresh_count == 1

    @pytest.mark.asyncio
    async def test_does_not_fire_for_sandbox_write_credential_outside_24h_window(
        self, session, user_id, monkeypatch
    ):
        credential = await _seed_merchant_credential(
            session,
            user_id,
            merchant_authorization_id=SANDBOX_AUTH_ID,
            capability=TikTokCapability.SANDBOX_WRITE,
            token_expires_at=_utc_now() + timedelta(days=7),
        )
        auth = _auth_returning()
        monkeypatch.setattr(credential_resolver, "build_refresh_auth_from_env", lambda: auth)

        resolved = await resolve_sandbox_write_credential(session)

        auth.refresh_access_token.assert_not_called()
        assert resolved.access_token == "old-access"
        untouched_row = await session.get(type(credential), credential.id)
        assert untouched_row.refresh_count == 0


class TestLazyTriggerNoOpWithoutConfiguredAppCredentials:
    @pytest.mark.asyncio
    async def test_no_crash_and_no_vendor_call_when_env_unconfigured(
        self, session, user_id, monkeypatch
    ):
        """The default state of every unit test in this repo (TIKTOK_APP_KEY/
        SECRET unset): the lazy layer must not attempt a vendor call, and
        must not raise, even for a credential inside the refresh window."""
        monkeypatch.setattr(credential_resolver, "build_refresh_auth_from_env", lambda: None)
        credential = await _seed_merchant_credential(
            session,
            user_id,
            merchant_authorization_id=PRODUCTION_AUTH_ID,
            capability=TikTokCapability.PRODUCTION_READ,
            token_expires_at=_utc_now() + timedelta(hours=1),
        )

        resolved = await resolve_production_read_credential(session)

        assert resolved.access_token == "old-access"
        untouched_row = await session.get(type(credential), credential.id)
        assert untouched_row.refresh_count == 0


def test_resolve_functions_still_take_only_session():
    """Every existing caller (services/agent/composition.py,
    services/execution/sandbox_guard.py, orchestrate.py) invokes these with
    a single positional `session` argument -- the lazy layer must not grow a
    second required parameter."""
    import inspect

    prod_params = list(inspect.signature(resolve_production_read_credential).parameters)
    sandbox_params = list(inspect.signature(resolve_sandbox_write_credential).parameters)
    assert prod_params == ["session"]
    assert sandbox_params == ["session"]
