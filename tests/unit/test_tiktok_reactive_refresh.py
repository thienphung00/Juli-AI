"""TDD tests for #1233 (AGT-W4A, ADR-081 decision 1 row 3) --
``integrations/tiktok/reactive_refresh.py``: the reactive layer that
self-heals a *lying* ``token_expires_at`` column on a vendor ``105002``
(unmapped -- surfaces as the bare ``TikTokAPIError`` base class, see
``exceptions.py::_CODE_MAP``) or transport-level HTTP ``401``
(``requests.HTTPError`` from ``TikTokClient._handle_response``) auth-expiry
signal.

``TikTokClient`` is synchronous, constructed per call with a static
``access_token``, and holds no credential context of its own -- it cannot
refresh itself. This module is the credential-aware layer that sits one
level above a single vendor call: it dispatches the call via
``asyncio.to_thread`` (mirroring every other async caller of a synchronous
TikTok primitive in this codebase), and on an auth-expiry signal, calls
``core/security/credential_refresh.py::refresh_credential(force=True)``,
swaps the refreshed token onto the ``TikTokClient`` instance, and retries
the originating call exactly once.

Concurrency (twenty simultaneous 105002s -> one vendor call, real Postgres)
lives in ``tests/integration/test_reactive_refresh_concurrency.py`` --
SQLite (this file's fixtures) cannot exercise cross-connection advisory-lock
contention.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
import requests

from juli_backend.integrations.tiktok.client import TikTokClient
from juli_backend.integrations.tiktok.exceptions import (
    PermissionDeniedError,
    ResourceNotFoundError,
    TikTokAPIError,
)
from juli_backend.integrations.tiktok.reactive_refresh import (
    ReactiveRefreshNeedsReauthError,
    call_with_reactive_refresh,
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
    access_token: str = "stale-access",
    refresh_token: str = "stale-refresh",
):
    """Seed a credential with ``token_expires_at`` far in the future --
    the literal sandbox scenario ADR-081 documents: the column claims
    fresh while the vendor answers ``105002 Expired``. Only the reactive
    path's ``force=True`` call can see past this lying column."""
    global _shop_counter
    _shop_counter += 1
    shop = await ShopsRepo(session).create(user_id, f"Reactive Refresh Shop {_shop_counter}")
    return await TikTokCredentialRepo(session).create(
        shop_id=shop.id,
        access_token=access_token,
        refresh_token=refresh_token,
        token_expires_at=_utc_now() + timedelta(days=7),
    )


def _auth_returning(
    access_token: str = "fresh-access", refresh_token: str = "fresh-refresh"
) -> MagicMock:
    auth = MagicMock()
    auth.refresh_access_token = MagicMock(
        return_value={
            "access_token": access_token,
            "refresh_token": refresh_token,
            "access_token_expire_in": 604800,
        }
    )
    return auth


def _auth_raising(exc: Exception) -> MagicMock:
    auth = MagicMock()
    auth.refresh_access_token = MagicMock(side_effect=exc)
    return auth


def _client(access_token: str = "stale-access") -> TikTokClient:
    return TikTokClient(app_key="key", app_secret="secret", access_token=access_token)


def _http_error(status_code: int) -> requests.HTTPError:
    resp = MagicMock()
    resp.status_code = status_code
    return requests.HTTPError(f"{status_code} error", response=resp)


class TestVendorCode105002TriggersRefreshAndRetry:
    async def test_105002_triggers_one_refresh_and_returns_retried_result(self, session, user_id):
        credential = await _seed_credential(session, user_id)
        client = _client()
        auth = _auth_returning(access_token="new-access")
        tokens_seen: list[str] = []

        def call():
            tokens_seen.append(client.access_token)
            if client.access_token == "stale-access":
                raise TikTokAPIError(code=105002, message="Expired")
            return {"ok": True}

        result = await call_with_reactive_refresh(
            session, credential.id, auth=auth, client=client, call=call
        )

        assert result == {"ok": True}
        auth.refresh_access_token.assert_called_once()
        assert tokens_seen == ["stale-access", "new-access"]
        assert client.access_token == "new-access"


class TestHttp401TriggersRefreshAndRetry:
    async def test_http_401_triggers_one_refresh_and_returns_retried_result(self, session, user_id):
        """Proves the transport-level shape is handled too, not just the
        JSON-envelope ``TikTokAPIError`` one."""
        credential = await _seed_credential(session, user_id)
        client = _client()
        auth = _auth_returning(access_token="new-access")
        attempts = {"n": 0}

        def call():
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise _http_error(401)
            return {"ok": True}

        result = await call_with_reactive_refresh(
            session, credential.id, auth=auth, client=client, call=call
        )

        assert result == {"ok": True}
        auth.refresh_access_token.assert_called_once()
        assert attempts["n"] == 2


class TestOtherSignalsDoNotTriggerRefresh:
    """This layer is scoped to auth-expiry signals only -- not a general
    retry-on-error policy."""

    @pytest.mark.parametrize(
        "exc",
        [
            PermissionDeniedError(code=100003, message="no scope"),
            ResourceNotFoundError(code=100004, message="not found"),
            TikTokAPIError(code=100002, message="different auth failure"),
        ],
        ids=["100003-permission-denied", "100004-not-found", "100002-not-105002"],
    )
    async def test_non_expiry_tiktok_api_error_propagates_without_refresh(
        self, session, user_id, exc
    ):
        credential = await _seed_credential(session, user_id)
        client = _client()
        auth = _auth_returning()

        def call():
            raise exc

        with pytest.raises(type(exc)):
            await call_with_reactive_refresh(
                session, credential.id, auth=auth, client=client, call=call
            )

        auth.refresh_access_token.assert_not_called()

    async def test_non_401_http_error_propagates_without_refresh(self, session, user_id):
        credential = await _seed_credential(session, user_id)
        client = _client()
        auth = _auth_returning()
        exc = _http_error(403)

        def call():
            raise exc

        with pytest.raises(requests.HTTPError):
            await call_with_reactive_refresh(
                session, credential.id, auth=auth, client=client, call=call
            )

        auth.refresh_access_token.assert_not_called()


class TestNeedsReauthDoesNotRetry:
    async def test_needs_reauth_raises_without_retry_and_without_second_vendor_call(
        self, session, user_id
    ):
        credential = await _seed_credential(session, user_id)
        client = _client()
        terminal_exc = TikTokAPIError(code=105002, message="Expired")
        auth = _auth_raising(terminal_exc)
        call_count = {"n": 0}

        def call():
            call_count["n"] += 1
            raise TikTokAPIError(code=105002, message="Expired")

        with pytest.raises(ReactiveRefreshNeedsReauthError) as excinfo:
            await call_with_reactive_refresh(
                session, credential.id, auth=auth, client=client, call=call
            )

        assert excinfo.value.credential_id == credential.id
        assert excinfo.value.cause.code == 105002
        # Only the original call happened -- no retry against the vendor's
        # originating endpoint once the credential is confirmed dead.
        assert call_count["n"] == 1
        auth.refresh_access_token.assert_called_once()


class TestBoundedToExactlyOneRetry:
    async def test_always_105002_raises_after_single_retry_not_loop(self, session, user_id):
        """A fixture that always returns 105002 -- even on the retried call,
        after a successful refresh -- must raise after the single bounded
        retry, not loop."""
        credential = await _seed_credential(session, user_id)
        client = _client()
        auth = _auth_returning(access_token="new-access")
        call_count = {"n": 0}

        def call():
            call_count["n"] += 1
            raise TikTokAPIError(code=105002, message="Still expired")

        with pytest.raises(TikTokAPIError) as excinfo:
            await call_with_reactive_refresh(
                session, credential.id, auth=auth, client=client, call=call
            )

        assert excinfo.value.code == 105002
        # Original call + exactly one retry, then the retry's own exception
        # propagates directly -- no second pass through the refresh branch.
        assert call_count["n"] == 2
        auth.refresh_access_token.assert_called_once()


class TestNoTokenMaterialInLogs:
    async def test_reactive_path_logs_no_token_material(self, session, user_id, caplog):
        credential = await _seed_credential(
            session,
            user_id,
            access_token="SECRET-STALE-ACCESS",
            refresh_token="SECRET-STALE-REFRESH",
        )
        client = _client(access_token="SECRET-STALE-ACCESS")
        auth = _auth_returning(access_token="SECRET-NEW-ACCESS", refresh_token="SECRET-NEW-REFRESH")

        def call():
            if client.access_token == "SECRET-STALE-ACCESS":
                raise TikTokAPIError(code=105002, message="Expired")
            return {"ok": True}

        with caplog.at_level(
            logging.WARNING, logger="juli_backend.integrations.tiktok.reactive_refresh"
        ):
            await call_with_reactive_refresh(
                session, credential.id, auth=auth, client=client, call=call
            )

        forbidden = {
            "SECRET-STALE-ACCESS",
            "SECRET-STALE-REFRESH",
            "SECRET-NEW-ACCESS",
            "SECRET-NEW-REFRESH",
        }
        assert caplog.records, "expected at least the reactive-refresh-triggered log line"
        for record in caplog.records:
            haystack = f"{record.getMessage()} {record.__dict__}"
            for token in forbidden:
                assert token not in haystack

    async def test_needs_reauth_path_logs_no_token_material(self, session, user_id, caplog):
        credential = await _seed_credential(
            session,
            user_id,
            access_token="SECRET-STALE-ACCESS",
            refresh_token="SECRET-STALE-REFRESH",
        )
        client = _client(access_token="SECRET-STALE-ACCESS")
        auth = _auth_raising(TikTokAPIError(code=105002, message="Expired"))

        def call():
            raise TikTokAPIError(code=105002, message="Expired")

        with caplog.at_level(
            logging.WARNING, logger="juli_backend.integrations.tiktok.reactive_refresh"
        ):
            with pytest.raises(ReactiveRefreshNeedsReauthError):
                await call_with_reactive_refresh(
                    session, credential.id, auth=auth, client=client, call=call
                )

        forbidden = {"SECRET-STALE-ACCESS", "SECRET-STALE-REFRESH"}
        assert caplog.records
        for record in caplog.records:
            haystack = f"{record.getMessage()} {record.__dict__}"
            for token in forbidden:
                assert token not in haystack


class TestUnknownCredentialPropagatesNotFound:
    async def test_unknown_credential_id_raises_not_found(self, session, user_id):
        from juli_backend.database.exceptions import NotFound

        client = _client()
        auth = _auth_returning()

        def call():
            raise TikTokAPIError(code=105002, message="Expired")

        with pytest.raises(NotFound):
            await call_with_reactive_refresh(
                session, uuid.uuid4(), auth=auth, client=client, call=call
            )
