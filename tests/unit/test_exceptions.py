"""TDD tests for TikTok API exception hierarchy.

Behaviors under test:
- Base error carries code, message, and request_id
- Specific subclasses exist for each error domain
- Factory function maps API error codes to correct exception types
- Unknown error codes fall back to base TikTokAPIError
"""
import pytest

from src.integrations.tiktok.exceptions import (
    TikTokAPIError,
    AuthenticationError,
    PermissionDeniedError,
    RateLimitError,
    ResourceNotFoundError,
    TikTokSystemError,
    error_from_response,
)


class TestTikTokAPIError:
    def test_carries_code_message_and_request_id(self):
        err = TikTokAPIError(
            code=100001,
            message="Invalid parameter",
            request_id="req-abc-123",
        )
        assert err.code == 100001
        assert err.message == "Invalid parameter"
        assert err.request_id == "req-abc-123"

    def test_str_includes_code_and_message(self):
        err = TikTokAPIError(code=100001, message="Invalid parameter")
        text = str(err)
        assert "100001" in text
        assert "Invalid parameter" in text

    def test_request_id_defaults_to_none(self):
        err = TikTokAPIError(code=100001, message="Invalid parameter")
        assert err.request_id is None


class TestExceptionSubclasses:
    @pytest.mark.parametrize(
        "cls,base",
        [
            (AuthenticationError, TikTokAPIError),
            (PermissionDeniedError, TikTokAPIError),
            (RateLimitError, TikTokAPIError),
            (ResourceNotFoundError, TikTokAPIError),
            (TikTokSystemError, TikTokAPIError),
        ],
    )
    def test_subclass_inherits_from_base(self, cls, base):
        err = cls(code=0, message="test")
        assert isinstance(err, base)
        assert isinstance(err, Exception)


class TestErrorFromResponse:
    """Factory should map TikTok API error codes to the correct exception type."""

    @pytest.mark.parametrize(
        "code,expected_type",
        [
            (100002, AuthenticationError),
            (100003, PermissionDeniedError),
            (100004, ResourceNotFoundError),
            (100005, RateLimitError),
            (100006, TikTokSystemError),
        ],
    )
    def test_maps_known_error_codes(self, code, expected_type):
        response = {
            "code": code,
            "message": "Something went wrong",
            "request_id": "req-xyz-789",
        }
        err = error_from_response(response)
        assert isinstance(err, expected_type)
        assert err.code == code
        assert err.message == "Something went wrong"
        assert err.request_id == "req-xyz-789"

    def test_unknown_code_falls_back_to_base(self):
        response = {
            "code": 999999,
            "message": "Unknown error",
            "request_id": "req-000",
        }
        err = error_from_response(response)
        assert type(err) is TikTokAPIError
        assert err.code == 999999

    def test_success_code_returns_none(self):
        response = {"code": 0, "message": "Success", "request_id": "req-ok"}
        result = error_from_response(response)
        assert result is None

    def test_missing_request_id_defaults_to_none(self):
        response = {"code": 100001, "message": "Bad param"}
        err = error_from_response(response)
        assert err.request_id is None
