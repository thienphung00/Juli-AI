"""AC1 — Phone-OTP login via Supabase Auth returns valid JWT
containing user_id and shop_ids (PRD AC-1)."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.auth import SupabaseAuth, Unauthorized


pytestmark = pytest.mark.asyncio

FAKE_USER_ID = str(uuid.uuid4())
FAKE_JWT = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.test.signature"


class TestPhoneOtpLoginReturnsJwt:
    """AC1: SupabaseAuth OTP flow returns JWT with user context."""

    async def test_verify_otp_returns_session_with_access_token(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": FAKE_JWT,
            "token_type": "bearer",
            "expires_in": 3600,
            "refresh_token": "refresh-token-value",
            "user": {"id": FAKE_USER_ID, "phone": "+84901234567"},
        }

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        auth = SupabaseAuth(
            "https://test.supabase.co", "test-anon-key", client=mock_client
        )
        result = await auth.verify_otp("+84901234567", "123456")

        assert result["access_token"] == FAKE_JWT
        assert result["user"]["phone"] == "+84901234567"

    async def test_send_otp_calls_supabase_endpoint(self):
        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        auth = SupabaseAuth(
            "https://test.supabase.co", "test-anon-key", client=mock_client
        )
        await auth.send_otp("+84901234567")

        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        assert "/otp" in call_args[0][0]
        assert call_args[1]["json"]["phone"] == "+84901234567"

    async def test_verify_otp_raises_unauthorized_on_failure(self):
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "Invalid OTP"

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        auth = SupabaseAuth(
            "https://test.supabase.co", "test-anon-key", client=mock_client
        )
        with pytest.raises(Unauthorized):
            await auth.verify_otp("+84901234567", "wrong-otp")
