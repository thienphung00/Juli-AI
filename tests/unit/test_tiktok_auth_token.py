"""Unit tests for TikTokAuth token exchange HTTP contract.

Issue #896 moved exchange_code / refresh_access_token to a POST body so live
OAuth credentials could not reach a query string — requests/urllib3 embed the
full request URL, query string included, in ConnectionError/HTTPError messages,
and a naive failure-path log would then write them to disk.

Issue #1187 corrected the shape: TikTok's Partner auth host answers **404** to
POST and **200** to GET-with-query-params (verified against the live host — GET
returns a real error envelope, `36004005 can not find related auth record`, for
a junk token). So neither call ever succeeded; tokens aged out with no way to
refresh them, and merchant onboarding through /v1/auth/tiktok/callback could not
complete. These tests previously mocked `requests.post` and therefore pinned the
broken shape in place indefinitely — the failure was only ever observable
against the real vendor.

#896's concern is real and is preserved by two properties asserted below, not by
the request method: the failure path logs only a safe classification, and it
raises `from None` so the URL-bearing chained exception never reaches a
traceback. Suppressing the chain is what actually closes that leak; the POST
body was only hiding it.
"""

import logging
from unittest.mock import MagicMock, patch

import pytest
import requests

from juli_backend.integrations.tiktok.auth import (
    DEFAULT_AUTH_BASE_URL,
    TikTokAuth,
)
from juli_backend.integrations.tiktok.exceptions import (
    AuthenticationError,
)

APP_KEY = "test_app_key"
APP_SECRET = "test_app_secret"

# Loopback port whose connection is refused immediately. Used to force a real
# requests.exceptions.ConnectionError so the test exercises urllib3's actual
# error-message construction (which embeds the full request URL, including
# any query string) rather than a mocked stand-in that would hide the bug.
UNREACHABLE_AUTH_BASE_URL = "https://127.0.0.1:1"


@pytest.fixture
def tiktok_auth():
    return TikTokAuth(app_key=APP_KEY, app_secret=APP_SECRET)


class TestTikTokAuthTokenRequest:
    def test_exchange_code_gets_with_query_params(self, tiktok_auth):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "code": 0,
            "data": {
                "access_token": "at",
                "refresh_token": "rt",
                "access_token_expire_in": 604800,
                "open_id": "seller_1",
            },
        }
        mock_resp.raise_for_status = MagicMock()

        with patch(
            "juli_backend.integrations.tiktok.auth.requests.get",
            return_value=mock_resp,
        ) as mock_get:
            result = tiktok_auth.exchange_code("auth_code_xyz")

        mock_get.assert_called_once()
        (called_url,) = mock_get.call_args[0]
        assert called_url == f"{DEFAULT_AUTH_BASE_URL}/api/v2/token/get"
        assert "json" not in mock_get.call_args.kwargs
        assert mock_get.call_args.kwargs["params"] == {
            "app_key": APP_KEY,
            "app_secret": APP_SECRET,
            "auth_code": "auth_code_xyz",
            "grant_type": "authorized_code",
        }
        assert result["open_id"] == "seller_1"

    def test_refresh_access_token_gets_with_query_params(self, tiktok_auth):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "code": 0,
            "data": {
                "access_token": "at2",
                "refresh_token": "rt2",
                "access_token_expire_in": 604800,
                "open_id": "seller_1",
            },
        }
        mock_resp.raise_for_status = MagicMock()

        with patch(
            "juli_backend.integrations.tiktok.auth.requests.get",
            return_value=mock_resp,
        ) as mock_get:
            result = tiktok_auth.refresh_access_token("refresh_token_xyz")

        mock_get.assert_called_once()
        (called_url,) = mock_get.call_args[0]
        assert called_url == f"{DEFAULT_AUTH_BASE_URL}/api/v2/token/refresh"
        assert "json" not in mock_get.call_args.kwargs
        assert mock_get.call_args.kwargs["params"] == {
            "app_key": APP_KEY,
            "app_secret": APP_SECRET,
            "refresh_token": "refresh_token_xyz",
            "grant_type": "refresh_token",
        }
        assert result["access_token"] == "at2"

    def test_exchange_code_maps_http_error_to_authentication_error(self, tiktok_auth):
        with patch(
            "juli_backend.integrations.tiktok.auth.requests.get",
            side_effect=requests.HTTPError("404 Client Error"),
        ):
            with pytest.raises(AuthenticationError, match="TikTok token request failed"):
                tiktok_auth.exchange_code("bad_code")

    def test_exchange_code_maps_tiktok_error_response(self, tiktok_auth):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "code": 36004004,
            "message": "invalid auth code",
            "request_id": "req-1",
        }
        mock_resp.raise_for_status = MagicMock()

        with patch(
            "juli_backend.integrations.tiktok.auth.requests.get",
            return_value=mock_resp,
        ):
            with pytest.raises(AuthenticationError) as exc_info:
                tiktok_auth.exchange_code("expired_code")

        assert exc_info.value.code == 36004004


class TestTikTokAuthNoCredentialLeakage:
    """Exit gate: a transport failure must never write live OAuth credentials
    into the log record — neither the app secret nor the refresh token."""

    SECRET_MARKER = "SECRET_MARKER_app_secret_12345"
    REFRESH_TOKEN_MARKER = "REFRESH_TOKEN_MARKER_67890"

    def _leaking_auth(self):
        return TikTokAuth(
            app_key=APP_KEY,
            app_secret=self.SECRET_MARKER,
            auth_base_url=UNREACHABLE_AUTH_BASE_URL,
        )

    @staticmethod
    def _all_captured_text(caplog) -> str:
        """Every string a structured/JSON log formatter could plausibly
        emit: the rendered message plus every `extra=` attribute recorded
        on each LogRecord, regardless of what formatter is (or is not)
        configured."""
        chunks = []
        for record in caplog.records:
            chunks.append(record.getMessage())
            chunks.append(str(record.__dict__))
        return "\n".join(chunks)

    def test_exchange_code_connection_failure_does_not_leak_app_secret(self, caplog):
        auth = self._leaking_auth()
        with caplog.at_level(logging.WARNING):
            with pytest.raises(AuthenticationError):
                auth.exchange_code("some_auth_code")

        captured = self._all_captured_text(caplog)
        assert self.SECRET_MARKER not in captured

    def test_refresh_access_token_connection_failure_does_not_leak_credentials(self, caplog):
        auth = self._leaking_auth()
        with caplog.at_level(logging.WARNING):
            with pytest.raises(AuthenticationError):
                auth.refresh_access_token(self.REFRESH_TOKEN_MARKER)

        captured = self._all_captured_text(caplog)
        assert self.SECRET_MARKER not in captured
        assert self.REFRESH_TOKEN_MARKER not in captured

    def test_refresh_access_token_connection_failure_still_raises_authentication_error(
        self, caplog
    ):
        auth = self._leaking_auth()
        with caplog.at_level(logging.WARNING):
            with pytest.raises(AuthenticationError, match="TikTok token request failed"):
                auth.refresh_access_token(self.REFRESH_TOKEN_MARKER)

    def test_transport_failure_suppresses_the_exception_chain(self):
        """#1187: with GET, the credentials ARE in the request URL, and
        requests/urllib3 put that URL into the exception message. `raise ...
        from None` is therefore load-bearing -- with `from exc`, anything that
        printed the cause (a traceback, an error reporter, `repr(exc.__cause__)`)
        would surface the app secret. Assert the chain is severed, and that no
        marker survives into a rendered traceback."""
        import traceback

        auth = self._leaking_auth()
        try:
            auth.refresh_access_token(self.REFRESH_TOKEN_MARKER)
        except AuthenticationError as exc:
            assert exc.__cause__ is None, (
                "the chained requests exception carries the full URL, query string "
                "included -- it must not be attached to the raised error"
            )
            rendered = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            assert self.SECRET_MARKER not in rendered
            assert self.REFRESH_TOKEN_MARKER not in rendered
        else:
            pytest.fail("expected AuthenticationError")

    def test_failure_message_names_the_status_without_leaking(self):
        """The generic `code=0` message hid an HTTP 404 for weeks and sent the
        diagnosis down the wrong path entirely (a 'dead refresh token' that was
        in fact perfectly valid). Surface the status code -- it is not
        sensitive -- while still never interpolating the exception text."""
        auth = self._leaking_auth()
        with pytest.raises(AuthenticationError) as exc_info:
            auth.exchange_code("some_auth_code")
        assert "HTTP" in str(exc_info.value)
        assert self.SECRET_MARKER not in str(exc_info.value)

    def test_connection_failure_still_emits_a_warning_record(self, caplog):
        """The fix must produce a SAFE record, not silence — a log record
        for the failure must still exist, just without the credentials."""
        auth = self._leaking_auth()
        with caplog.at_level(logging.WARNING):
            with pytest.raises(AuthenticationError):
                auth.exchange_code("some_auth_code")

        assert any(record.levelno == logging.WARNING for record in caplog.records)
