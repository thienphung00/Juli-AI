"""TDD tests for #1231 (AGT-W4A-BE, ADR-081 decision 4) --
``core/security/credential_refresh.py::refresh_credential``: window
selection, force override, transient-vs-terminal classification, log
hygiene, and the no-open-transaction-across-HTTP-call invariant.

Concurrency (real Postgres: two refreshers, twenty simultaneous forced
refreshes) lives in
``tests/integration/test_credential_refresh_concurrency.py`` -- SQLite (this
file's fixtures) cannot exercise cross-connection lock contention.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from juli_backend.core.security import credential_refresh
from juli_backend.core.security.credential_refresh import (
    RefreshOutcome,
    RefreshStatus,
    refresh_credential,
)
from juli_backend.database.exceptions import NotFound
from juli_backend.integrations.tiktok.exceptions import (
    AuthenticationError,
    RateLimitError,
    TikTokAPIError,
    TikTokSystemError,
)
from juli_backend.repositories.repos import ShopsRepo, TikTokCredentialRepo

pytestmark = pytest.mark.asyncio


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


_shop_counter = 0


async def _seed_credential(
    session,
    user_id,
    *,
    token_expires_at: datetime,
    access_token: str = "old-access-token",
    refresh_token: str = "old-refresh-token",
):
    global _shop_counter
    _shop_counter += 1
    shop = await ShopsRepo(session).create(user_id, f"Refresh Test Shop {_shop_counter}")
    return await TikTokCredentialRepo(session).create(
        shop_id=shop.id,
        access_token=access_token,
        refresh_token=refresh_token,
        token_expires_at=token_expires_at,
    )


def _auth_returning(
    access_token: str = "new-access-token",
    refresh_token: str = "new-refresh-token",
    access_token_expire_in: int = 604800,
) -> MagicMock:
    auth = MagicMock()
    auth.refresh_access_token = MagicMock(
        return_value={
            "access_token": access_token,
            "refresh_token": refresh_token,
            "access_token_expire_in": access_token_expire_in,
        }
    )
    return auth


def _auth_raising(exc: Exception) -> MagicMock:
    auth = MagicMock()
    auth.refresh_access_token = MagicMock(side_effect=exc)
    return auth


class TestRefreshOutcomeShape:
    async def test_outcome_carries_credential_status_and_no_error_on_success(
        self, session, user_id
    ):
        credential = await _seed_credential(
            session, user_id, token_expires_at=_utc_now() + timedelta(hours=1)
        )
        outcome = await refresh_credential(session, credential.id, auth=_auth_returning())

        assert isinstance(outcome, RefreshOutcome)
        assert outcome.status is RefreshStatus.REFRESHED
        assert outcome.credential.id == credential.id
        assert outcome.error is None


class TestWindowSelection:
    async def test_far_from_expiry_is_fresh_no_vendor_call(self, session, user_id):
        credential = await _seed_credential(
            session, user_id, token_expires_at=_utc_now() + timedelta(days=7)
        )
        auth = _auth_returning()

        outcome = await refresh_credential(session, credential.id, auth=auth)

        assert outcome.status is RefreshStatus.FRESH
        auth.refresh_access_token.assert_not_called()
        assert outcome.credential.access_token == "old-access-token"

    async def test_just_over_24h_is_fresh(self, session, user_id):
        credential = await _seed_credential(
            session, user_id, token_expires_at=_utc_now() + timedelta(hours=24, minutes=1)
        )
        auth = _auth_returning()

        outcome = await refresh_credential(session, credential.id, auth=auth)

        assert outcome.status is RefreshStatus.FRESH
        auth.refresh_access_token.assert_not_called()

    async def test_exactly_24h_boundary_is_not_fresh_and_refreshes(self, session, user_id):
        """The guard is strictly-greater-than: a row exactly REFRESH_BUFFER
        from expiry is on the refresh side of the boundary, not the fresh
        side."""
        credential = await _seed_credential(
            session, user_id, token_expires_at=_utc_now() + timedelta(hours=24)
        )
        auth = _auth_returning()

        outcome = await refresh_credential(session, credential.id, auth=auth)

        assert outcome.status is RefreshStatus.REFRESHED
        auth.refresh_access_token.assert_called_once()

    async def test_just_under_24h_refreshes(self, session, user_id):
        credential = await _seed_credential(
            session, user_id, token_expires_at=_utc_now() + timedelta(hours=23, minutes=59)
        )
        auth = _auth_returning()

        outcome = await refresh_credential(session, credential.id, auth=auth)

        assert outcome.status is RefreshStatus.REFRESHED
        auth.refresh_access_token.assert_called_once()


class TestGap6Regression:
    async def test_20h_from_expiry_is_refreshed_not_fresh(self, session, user_id):
        """ADR-081 gap 6: a beat scanning a 24h window must not be a no-op
        against a row 20h from expiry. See the module docstring for the
        red-proof procedure against the old ``timedelta(minutes=30)``
        buffer (run separately, not encoded as a permanent test, since
        pinning the historical bug value here would just be dead weight
        once the fix has landed)."""
        credential = await _seed_credential(
            session, user_id, token_expires_at=_utc_now() + timedelta(hours=20)
        )
        auth = _auth_returning()

        outcome = await refresh_credential(session, credential.id, auth=auth)

        assert outcome.status is RefreshStatus.REFRESHED
        auth.refresh_access_token.assert_called_once()


class TestForceOverride:
    async def test_force_true_ignores_fresh_column_and_calls_vendor(self, session, user_id):
        """The literal 2026-08-18 sandbox scenario: the column claims fresh
        (``now + 7d``) but ``force=True`` still issues the vendor call and
        rotates the tokens."""
        credential = await _seed_credential(
            session, user_id, token_expires_at=_utc_now() + timedelta(days=7)
        )
        auth = _auth_returning(access_token="forced-access", refresh_token="forced-refresh")

        outcome = await refresh_credential(session, credential.id, auth=auth, force=True)

        assert outcome.status is RefreshStatus.REFRESHED
        auth.refresh_access_token.assert_called_once()
        assert outcome.credential.access_token == "forced-access"
        assert outcome.credential.refresh_token == "forced-refresh"


class TestTransientFailure:
    @pytest.mark.parametrize(
        "exc",
        [
            AuthenticationError(code=0, message="TikTok token request failed (HTTP 503)"),
            RateLimitError(code=100005, message="Too many requests"),
            TikTokSystemError(code=100006, message="Internal error"),
        ],
        ids=["network-5xx-wrapper", "rate-limit", "system-error"],
    )
    async def test_transient_vendor_failure_leaves_credential_valid_and_unmarked(
        self, session, user_id, exc
    ):
        credential = await _seed_credential(
            session, user_id, token_expires_at=_utc_now() + timedelta(hours=1)
        )
        auth = _auth_raising(exc)

        outcome = await refresh_credential(session, credential.id, auth=auth)

        assert outcome.status is RefreshStatus.TRANSIENT
        assert outcome.error is exc
        assert outcome.credential.status == "active"
        assert outcome.credential.access_token == "old-access-token"
        assert outcome.credential.refresh_token == "old-refresh-token"
        assert outcome.credential.token_expires_at == credential.token_expires_at


class TestNeedsReauthFailure:
    async def test_terminal_vendor_failure_marks_needs_reauth_with_runbook_message(
        self, session, user_id
    ):
        """105002 "Expired" is not in the vendor's mapped code table
        (``integrations/tiktok/exceptions.py::_CODE_MAP``), so it surfaces as
        the generic ``TikTokAPIError`` base class -- the exact sandbox
        scenario ADR-081 documents."""
        credential = await _seed_credential(
            session, user_id, token_expires_at=_utc_now() + timedelta(hours=1)
        )
        exc = TikTokAPIError(code=105002, message="Expired")
        auth = _auth_raising(exc)

        outcome = await refresh_credential(session, credential.id, auth=auth)

        assert outcome.status is RefreshStatus.NEEDS_REAUTH
        assert outcome.error is exc
        assert outcome.credential.status == "needs_reauth"
        assert "initiate_oauth" in outcome.credential.last_refresh_error
        assert "re-OAuth" in outcome.credential.last_refresh_error

    async def test_needs_reauth_does_not_touch_token_triad(self, session, user_id):
        credential = await _seed_credential(
            session, user_id, token_expires_at=_utc_now() + timedelta(hours=1)
        )
        auth = _auth_raising(AuthenticationError(code=100002, message="invalid token"))

        outcome = await refresh_credential(session, credential.id, auth=auth)

        assert outcome.status is RefreshStatus.NEEDS_REAUTH
        assert outcome.credential.access_token == "old-access-token"
        assert outcome.credential.refresh_token == "old-refresh-token"


class TestLockedOutcome:
    async def test_lock_not_acquired_and_row_never_updates_returns_locked(
        self, session, user_id, monkeypatch
    ):
        """Deterministic, dialect-agnostic exercise of the lock-loser branch
        itself. Real cross-connection contention (the actual N-callers-one-
        vendor-call proof) needs real Postgres and lives in the integration
        suite."""
        credential = await _seed_credential(
            session, user_id, token_expires_at=_utc_now() + timedelta(hours=1)
        )

        async def _never_acquires(session, credential_id):
            return False, None

        monkeypatch.setattr(credential_refresh, "_try_advisory_lock", _never_acquires)
        monkeypatch.setattr(credential_refresh, "_LOCK_POLL_TIMEOUT_SECONDS", 0.05)
        monkeypatch.setattr(credential_refresh, "_LOCK_POLL_INTERVAL_SECONDS", 0.01)
        auth = _auth_returning()

        outcome = await refresh_credential(session, credential.id, auth=auth)

        assert outcome.status is RefreshStatus.LOCKED
        auth.refresh_access_token.assert_not_called()


class TestUnknownCredential:
    async def test_unknown_credential_id_raises_not_found(self, session, user_id):
        import uuid

        with pytest.raises(NotFound):
            await refresh_credential(session, uuid.uuid4(), auth=_auth_returning())


class TestNoTokenMaterialInLogs:
    async def test_refreshed_path_logs_no_token_material(self, session, user_id, caplog):
        credential = await _seed_credential(
            session,
            user_id,
            token_expires_at=_utc_now() + timedelta(hours=1),
            access_token="SECRET-OLD-ACCESS",
            refresh_token="SECRET-OLD-REFRESH",
        )
        auth = _auth_returning(access_token="SECRET-NEW-ACCESS", refresh_token="SECRET-NEW-REFRESH")

        with caplog.at_level(logging.INFO, logger="juli_backend.core.security.credential_refresh"):
            await refresh_credential(session, credential.id, auth=auth)

        forbidden = {
            "SECRET-OLD-ACCESS",
            "SECRET-OLD-REFRESH",
            "SECRET-NEW-ACCESS",
            "SECRET-NEW-REFRESH",
        }
        assert caplog.records, "expected at least the tiktok_token_refreshed log line"
        for record in caplog.records:
            haystack = f"{record.getMessage()} {record.__dict__}"
            for token in forbidden:
                assert token not in haystack

    async def test_needs_reauth_path_logs_no_token_material(self, session, user_id, caplog):
        credential = await _seed_credential(
            session,
            user_id,
            token_expires_at=_utc_now() + timedelta(hours=1),
            access_token="SECRET-OLD-ACCESS",
            refresh_token="SECRET-OLD-REFRESH",
        )
        auth = _auth_raising(TikTokAPIError(code=105002, message="Expired"))

        with caplog.at_level(logging.INFO, logger="juli_backend.core.security.credential_refresh"):
            await refresh_credential(session, credential.id, auth=auth)

        forbidden = {"SECRET-OLD-ACCESS", "SECRET-OLD-REFRESH"}
        assert caplog.records
        for record in caplog.records:
            haystack = f"{record.getMessage()} {record.__dict__}"
            for token in forbidden:
                assert token not in haystack


class TestNoOpenTransactionAcrossHttpCall:
    async def test_http_call_observes_no_open_transaction_on_the_session(self, session, user_id):
        """Test-double assertion (not source inspection), per ADR-081
        decision 5: the vendor call must never happen while this session
        holds an open transaction, because worker sessions use NullPool
        (#871) and an open transaction there is a live Supabase pooler
        client slot (#813)."""
        credential = await _seed_credential(
            session, user_id, token_expires_at=_utc_now() + timedelta(hours=1)
        )
        observed: dict[str, bool] = {}

        class _SpyAuth:
            def refresh_access_token(self, refresh_token: str) -> dict:
                observed["in_transaction"] = session.in_transaction()
                return {
                    "access_token": "spied-access",
                    "refresh_token": "spied-refresh",
                    "access_token_expire_in": 604800,
                }

        outcome = await refresh_credential(session, credential.id, auth=_SpyAuth())

        assert observed == {"in_transaction": False}
        assert outcome.status is RefreshStatus.REFRESHED
