"""Unit tests for the exception hierarchy and raise_for_status."""

from __future__ import annotations

import pytest

from src.integrations.kiotviet.exceptions import (
    AuthenticationError,
    ForbiddenError,
    KiotVietError,
    NotFoundError,
    RateLimitError,
    ServerError,
    ValidationError,
    raise_for_status,
)
from tests.mocks.kiotviet_responses import (
    ERROR_400_RESPONSE,
    ERROR_401_RESPONSE,
    ERROR_404_RESPONSE,
    ERROR_429_RESPONSE,
    ERROR_500_RESPONSE,
)


class TestRaiseForStatus:

    def test_200_does_not_raise(self) -> None:
        raise_for_status(200, None)

    @pytest.mark.parametrize(
        "status, body, expected_cls, expected_msg",
        [
            (400, ERROR_400_RESPONSE, ValidationError, "Invalid request"),
            (401, ERROR_401_RESPONSE, AuthenticationError, "Invalid or expired token"),
            (404, ERROR_404_RESPONSE, NotFoundError, "Resource not found"),
            (429, ERROR_429_RESPONSE, RateLimitError, "Rate limit exceeded"),
            (500, ERROR_500_RESPONSE, ServerError, "Internal server error"),
        ],
    )
    def test_maps_status_to_exception(
        self,
        status: int,
        body: dict,
        expected_cls: type[KiotVietError],
        expected_msg: str,
    ) -> None:
        with pytest.raises(expected_cls, match=expected_msg) as exc_info:
            raise_for_status(status, body)
        assert exc_info.value.status_code == status

    def test_unknown_4xx_raises_base(self) -> None:
        with pytest.raises(KiotVietError, match="HTTP 418"):
            raise_for_status(418, None)

    def test_unknown_5xx_raises_server_error(self) -> None:
        with pytest.raises(ServerError, match="HTTP 502"):
            raise_for_status(502, None)

    def test_field_errors_propagated(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            raise_for_status(400, ERROR_400_RESPONSE)
        assert len(exc_info.value.errors) == 1
        assert exc_info.value.errors[0]["fieldName"] == "name"

    def test_error_code_propagated(self) -> None:
        with pytest.raises(AuthenticationError) as exc_info:
            raise_for_status(401, ERROR_401_RESPONSE)
        assert exc_info.value.error_code == "Unauthorized"
