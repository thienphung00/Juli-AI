"""TikTok Sandbox OAuth integration tests — Issue #366.

Live (unmocked) calls to TikTok token endpoints using Partner Center sandbox
credentials from environment variables. Skips when secrets are absent.
"""

from __future__ import annotations

import pytest

from juli_backend.integrations.tiktok.exceptions import AuthenticationError

from tests.integration.tiktok_sandbox import (
    requires_sandbox_auth_code,
    requires_sandbox_credentials,
    requires_sandbox_refresh_token,
    sandbox_auth_code,
    sandbox_refresh_token,
)

INVALID_AUTH_CODE = "juli_integration_invalid_auth_code_366"


@requires_sandbox_credentials
def test_invalid_auth_code_returns_authentication_error_from_live_api(
    tiktok_auth_client,
):
    """Live token/get rejects an invalid auth code with a TikTok error envelope."""
    with pytest.raises(AuthenticationError) as exc_info:
        tiktok_auth_client.exchange_code(INVALID_AUTH_CODE)

    assert exc_info.value.code != 0
    assert exc_info.value.message


@requires_sandbox_auth_code
def test_exchange_code_returns_token_pair_with_sandbox_auth_code(tiktok_auth_client):
    """Live token/get succeeds with a fresh sandbox auth code from CI secrets.

    TIKTOK_SANDBOX_AUTH_CODE is single-use — rotate the GitHub secret after each
    successful OAuth consent flow in Partner Center.
    """
    result = tiktok_auth_client.exchange_code(sandbox_auth_code())

    assert result["access_token"]
    assert result["refresh_token"]
    assert int(result["access_token_expire_in"]) > 0


@requires_sandbox_refresh_token
def test_refresh_access_token_returns_token_pair_with_sandbox_refresh_token(
    tiktok_auth_client,
):
    """Live token/refresh succeeds with a sandbox refresh token from CI secrets."""
    result = tiktok_auth_client.refresh_access_token(sandbox_refresh_token())

    assert result["access_token"]
    assert result["refresh_token"]
    assert int(result["access_token_expire_in"]) > 0
