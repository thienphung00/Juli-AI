"""Tests for TikTok token expiry parsing."""

from datetime import UTC, datetime

import pytest

from juli_backend.services.tiktok.token_expiry import access_token_expires_at


class TestAccessTokenExpiresAt:
    def test_parses_unix_timestamp_from_live_api(self):
        now = datetime(2026, 7, 3, 4, 40, tzinfo=UTC).replace(tzinfo=None)
        expires_at = access_token_expires_at(1783658262, now=now)
        assert expires_at == datetime(2026, 7, 10, 4, 37, 42)

    def test_parses_ttl_seconds_from_test_fixtures(self):
        now = datetime(2026, 7, 3, 4, 40, tzinfo=UTC).replace(tzinfo=None)
        expires_at = access_token_expires_at(604800, now=now)
        assert expires_at == datetime(2026, 7, 10, 4, 40)

    def test_none_raises_instead_of_synthesizing(self):
        """ADR-081 decision 3: expiry is vendor-authoritative. A missing value
        used to synthesize ``now + 1h``; it must now raise instead, because a
        wrong expiry suppresses the refresh that would have corrected it."""
        with pytest.raises(ValueError, match="access_token_expire_in"):
            access_token_expires_at(None)

    def test_zero_raises_instead_of_synthesizing(self):
        """Zero is falsy exactly like ``None`` and must raise the same way."""
        with pytest.raises(ValueError, match="access_token_expire_in"):
            access_token_expires_at(0)
