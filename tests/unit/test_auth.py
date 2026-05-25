"""Unit tests for the KiotViet authentication / TokenManager."""

from __future__ import annotations

import time
from unittest.mock import patch, MagicMock

import pytest
import requests
import responses

from src.integrations.kiotviet.auth import TokenManager, RENEWAL_BUFFER_SECONDS, TOKEN_URL
from src.integrations.kiotviet.exceptions import AuthenticationError
from tests.mocks.kiotviet_responses import TOKEN_RESPONSE


class TestTokenManager:

    @responses.activate
    def test_authenticate_success(self, token_manager: TokenManager) -> None:
        responses.add(
            responses.POST,
            TOKEN_URL,
            json=TOKEN_RESPONSE,
            status=200,
        )

        token = token_manager.access_token
        assert token == TOKEN_RESPONSE["access_token"]

    @responses.activate
    def test_token_is_cached(self, token_manager: TokenManager) -> None:
        responses.add(responses.POST, TOKEN_URL, json=TOKEN_RESPONSE, status=200)

        first = token_manager.access_token
        second = token_manager.access_token

        assert first == second
        assert len(responses.calls) == 1

    @responses.activate
    def test_token_refreshes_after_expiry(self, token_manager: TokenManager) -> None:
        responses.add(responses.POST, TOKEN_URL, json=TOKEN_RESPONSE, status=200)
        responses.add(
            responses.POST,
            TOKEN_URL,
            json={**TOKEN_RESPONSE, "access_token": "refreshed-token"},
            status=200,
        )

        _ = token_manager.access_token
        # Simulate expiry by setting _expires_at in the past
        token_manager._expires_at = 0.0

        refreshed = token_manager.access_token
        assert refreshed == "refreshed-token"
        assert len(responses.calls) == 2

    @responses.activate
    def test_authenticate_failure_raises(self, token_manager: TokenManager) -> None:
        responses.add(responses.POST, TOKEN_URL, json={"error": "invalid_client"}, status=400)

        with pytest.raises(AuthenticationError, match="HTTP 400"):
            _ = token_manager.access_token

    @responses.activate
    def test_authenticate_network_error(self, token_manager: TokenManager) -> None:
        responses.add(
            responses.POST,
            TOKEN_URL,
            body=requests.ConnectionError("DNS failure"),
        )

        with pytest.raises(AuthenticationError, match="Token request failed"):
            _ = token_manager.access_token

    @responses.activate
    def test_invalidate_forces_reauthentication(self, token_manager: TokenManager) -> None:
        responses.add(responses.POST, TOKEN_URL, json=TOKEN_RESPONSE, status=200)
        responses.add(
            responses.POST,
            TOKEN_URL,
            json={**TOKEN_RESPONSE, "access_token": "new-after-invalidate"},
            status=200,
        )

        first = token_manager.access_token
        token_manager.invalidate()
        second = token_manager.access_token

        assert first != second
        assert second == "new-after-invalidate"
        assert len(responses.calls) == 2

    @responses.activate
    def test_proactive_renewal_before_expiry(self, token_manager: TokenManager) -> None:
        short_lived = {**TOKEN_RESPONSE, "expires_in": RENEWAL_BUFFER_SECONDS}
        responses.add(responses.POST, TOKEN_URL, json=short_lived, status=200)
        responses.add(
            responses.POST,
            TOKEN_URL,
            json={**TOKEN_RESPONSE, "access_token": "renewed"},
            status=200,
        )

        _ = token_manager.access_token
        # With expires_in == RENEWAL_BUFFER_SECONDS, _expires_at is essentially now
        # so the next call should trigger re-auth
        second = token_manager.access_token
        assert second == "renewed"
