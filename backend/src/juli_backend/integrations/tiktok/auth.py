"""TikTok Shop OAuth 2.0 authentication service.

Handles authorization URL generation, auth-code-to-token exchange,
and token refresh.  Does NOT handle encrypted storage — that is the
responsibility of the persistence layer.
"""

from __future__ import annotations

import logging
from urllib.parse import urlencode

import requests

from juli_backend.integrations.tiktok.exceptions import AuthenticationError, error_from_response

logger = logging.getLogger(__name__)

PARTNER_AUTH_URL = "https://services.tiktokshop.com/open/authorize"
DEFAULT_OPEN_API_BASE_URL = "https://open-api.tiktokglobalshop.com"
DEFAULT_AUTH_BASE_URL = "https://auth.tiktok-shops.com"


class TikTokAuth:
    """Manages the OAuth 2.0 lifecycle for a TikTok Shop Partner app."""

    def __init__(
        self,
        app_key: str,
        app_secret: str,
        base_url: str | None = None,
        *,
        auth_base_url: str | None = None,
    ) -> None:
        self._app_key = app_key
        self._app_secret = app_secret
        self._base_url = (base_url or DEFAULT_OPEN_API_BASE_URL).rstrip("/")
        self._auth_base_url = (auth_base_url or DEFAULT_AUTH_BASE_URL).rstrip("/")

    @property
    def app_key(self) -> str:
        """The OAuth *client id*, not a secret (the `client_id` analogue).

        Read-only accessor so callers that must build a signed client of their
        own -- `core/security/credential_binding.py`'s vendor identity check
        (#1200) -- do not reach into `_app_key`. Deliberately no `app_secret`
        counterpart: that one IS a secret, and callers already receive it
        explicitly where they legitimately need it.
        """
        return self._app_key

    def generate_auth_url(self, redirect_uri: str, state: str) -> str:
        """Build the URL a seller is redirected to for OAuth consent."""
        params = urlencode(
            {
                "app_key": self._app_key,
                "redirect_uri": redirect_uri,
                "state": state,
            }
        )
        return f"{PARTNER_AUTH_URL}?{params}"

    def exchange_code(self, auth_code: str) -> dict:
        """Exchange an authorization code for access + refresh tokens.

        Raises AuthenticationError when TikTok returns a non-zero code.
        """
        payload = {
            "app_key": self._app_key,
            "app_secret": self._app_secret,
            "auth_code": auth_code,
            "grant_type": "authorized_code",
        }
        return self._token_request("/api/v2/token/get", payload)

    def refresh_access_token(self, refresh_token: str) -> dict:
        """Use a refresh token to obtain a new access + refresh token pair.

        Raises AuthenticationError when the refresh token is expired or invalid.
        """
        payload = {
            "app_key": self._app_key,
            "app_secret": self._app_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
        return self._token_request("/api/v2/token/refresh", payload)

    def _token_request(self, path: str, payload: dict) -> dict:
        """Call a TikTok Partner auth endpoint (`/api/v2/token/get`,
        `/api/v2/token/refresh`).

        **GET with query parameters, because that is what the vendor accepts**
        (issue #1187). Verified directly against the live host: GET returns 200
        with a real error envelope (`36004005 can not find related auth record`
        for a junk token), POST with a JSON body returns `404 page not found`.

        Issue #896 moved these calls to POST on purpose, to keep credentials out
        of a query string that requests/urllib3 embed in `ConnectionError`/
        `HTTPError` messages. The reasoning was sound but the endpoint does not
        support POST, so `refresh_access_token` and `exchange_code` never once
        succeeded: tokens silently aged out and merchant onboarding through
        `/v1/auth/tiktok/callback` could not complete. The unit tests mocked
        `requests.post` and so pinned the broken shape indefinitely, while the
        live tests that would have caught it (`tests/integration/
        test_tiktok_sandbox_oauth.py`) run only on `merge_group`.

        #896's guarantee is preserved here rather than abandoned, in two ways:

        1. Nothing derived from the exception is logged or raised — only a safe
           classification (`path`, `error_type`, `status_code`). `str(exc)` is
           never interpolated.
        2. `raise ... from None` **suppresses the exception chain**. The chained
           `requests` exception's own message contains the full URL, query string
           included; with `from exc` it would surface in any traceback that
           printed the cause. Suppressing it is what actually closes the leak
           #896 was worried about — the POST body was only ever hiding it.
        """
        url = f"{self._auth_base_url}{path}"
        try:
            # creds-url-guard: allow -- TikTok's Partner auth host requires GET
            # with query params here (POST answers 404), so `app_secret` and
            # `refresh_token` unavoidably travel in the URL for these two
            # endpoints. This is the deliberate exception issue #1187 records;
            # the leak it creates is closed at the two places the URL could
            # actually escape -- the log record (safe classification only) and
            # the traceback (`from None`, chain suppressed). Recorded explicitly
            # rather than relying on the checker's blind spot: it inspects dict
            # literals and same-function locals, and `payload` is a parameter,
            # so this call site would otherwise pass unexamined.
            resp = requests.get(url, params=payload, timeout=10)
            resp.raise_for_status()
        except requests.RequestException as exc:
            status_code = getattr(exc.response, "status_code", None)
            logger.warning(
                "tiktok_token_request_failed",
                extra={
                    "path": path,
                    "error_type": type(exc).__name__,
                    "status_code": status_code,
                },
            )
            # `from None`, not `from exc` -- see docstring point 2.
            raise AuthenticationError(
                code=0, message=f"TikTok token request failed (HTTP {status_code})"
            ) from None

        data = resp.json()
        err = error_from_response(data)
        if err is not None:
            if not isinstance(err, AuthenticationError):
                raise AuthenticationError(
                    code=err.code,
                    message=err.message,
                    request_id=err.request_id,
                )
            raise err

        return data.get("data", {})
