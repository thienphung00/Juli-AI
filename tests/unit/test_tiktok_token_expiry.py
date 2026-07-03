"""Tests for TikTok token expiry parsing."""

from datetime import datetime, timezone

from backend.api.services.tiktok.token_expiry import access_token_expires_at


class TestAccessTokenExpiresAt:
    def test_parses_unix_timestamp_from_live_api(self):
        now = datetime(2026, 7, 3, 4, 40, tzinfo=timezone.utc).replace(tzinfo=None)
        expires_at = access_token_expires_at(1783658262, now=now)
        assert expires_at == datetime(2026, 7, 10, 4, 37, 42)

    def test_parses_ttl_seconds_from_test_fixtures(self):
        now = datetime(2026, 7, 3, 4, 40, tzinfo=timezone.utc).replace(tzinfo=None)
        expires_at = access_token_expires_at(604800, now=now)
        assert expires_at == datetime(2026, 7, 10, 4, 40)
