"""Tests for marketplace error translation at the sanitization boundary (ADR-070
decision 5).

Issue #993 — every marketplace failure a tool executor can raise (a coded
`TikTokAPIError`, a pre-signing `TransportGuardError`, or a bare network
transport failure below either) maps to
`{"error": {"category", "message", "retryable"}}`: `category` reuses the
existing `ExecutionErrorCategory` taxonomy (no new enum), `message` is
business-language English for the model, and `retryable` derives from the
curated allowlist of vendor codes (`{100005, 100006, 36009003}`) plus
transport-level errors. Raw vendor codes, endpoint paths, and vendor request
IDs must never appear in the translated envelope — only in server-side logs.
"""

from __future__ import annotations

import logging

import pytest
import requests

from juli_backend.integrations.tiktok import (
    AuthenticationError,
    PermissionDeniedError,
    RateLimitError,
    ResourceNotFoundError,
    TikTokAPIError,
    TikTokSystemError,
    TransportGuardError,
)
from juli_backend.services.agent.sanitize.errors import (
    _TIKTOK_API_MESSAGE,
    _TRANSIENT_VENDOR_MESSAGE,
    RETRYABLE_VENDOR_CODES,
    TranslatedError,
    to_error_envelope,
    translate_marketplace_error,
)
from juli_backend.services.execution.types import ExecutionErrorCategory

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _walk_strings(value: object) -> list[str]:
    """Recurse an arbitrarily nested structure and collect every string found.

    Used for the adversarial no-leak assertions: a flat top-level key check
    is not enough (a leaked identifier could hide inside a nested value), so
    every acceptance-criteria-5 test recurses the whole structure.
    """
    found: list[str] = []
    if isinstance(value, str):
        found.append(value)
    elif isinstance(value, dict):
        for key, val in value.items():
            found.append(str(key))
            found.extend(_walk_strings(val))
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            found.extend(_walk_strings(item))
    else:
        found.append(repr(value))
    return found


# ---------------------------------------------------------------------------
# The curated allowlist matches ADR-070 decision 5 exactly
# ---------------------------------------------------------------------------


def test_retryable_codes_match_adr_070_decision_5():
    assert RETRYABLE_VENDOR_CODES == frozenset({100005, 100006, 36009003})


# ---------------------------------------------------------------------------
# Acceptance criterion 1: each curated retryable vendor code -> retryable: true
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("exc", "expected_category"),
    [
        (RateLimitError(100005, "Request throttled"), ExecutionErrorCategory.TRANSIENT),
        (TikTokSystemError(100006, "Internal error"), ExecutionErrorCategory.TRANSIENT),
        (
            TikTokAPIError(36009003, "Internal error. Please try again."),
            ExecutionErrorCategory.TRANSIENT,
        ),
    ],
    ids=["100005_rate_limit", "100006_system_error", "36009003_vendor_internal"],
)
def test_curated_retryable_vendor_codes_map_to_retryable_true(exc, expected_category):
    result = translate_marketplace_error(exc)

    assert isinstance(result, TranslatedError)
    assert result.retryable is True
    assert result.category == expected_category


# ---------------------------------------------------------------------------
# Regression: message must never contradict retryable. Every curated code
# raised as a *bare* TikTokAPIError (not just the subclassed ones) must
# still produce a retryable-consistent message — this is the exact live
# production shape for 36009003, which has no dedicated subclass in
# integrations/tiktok/exceptions.py._CODE_MAP.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("code", sorted(RETRYABLE_VENDOR_CODES))
def test_bare_tiktok_api_error_for_every_curated_code_has_consistent_message(code):
    exc = TikTokAPIError(code, "boom", "req-123")

    result = translate_marketplace_error(exc)

    assert result.retryable is True
    assert result.category == ExecutionErrorCategory.TRANSIENT
    assert result.message == _TRANSIENT_VENDOR_MESSAGE
    assert "will not succeed" not in result.message


def test_bare_tiktok_api_error_for_an_uncatalogued_code_has_consistent_message():
    exc = TikTokAPIError(999999, "boom", "req-123")

    result = translate_marketplace_error(exc)

    assert result.retryable is False
    assert result.category == ExecutionErrorCategory.TIKTOK_API
    assert result.message == _TIKTOK_API_MESSAGE
    assert "will not succeed" in result.message


# ---------------------------------------------------------------------------
# Acceptance criterion 2: an uncatalogued vendor failure -> retryable: false.
# Its own behavior, since fail-open here would let the agent loop thrash.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "exc",
    [
        AuthenticationError(100002, "Token expired"),
        PermissionDeniedError(100003, "Missing scope"),
        ResourceNotFoundError(100004, "Order not found"),
        TikTokAPIError(999999, "Some uncatalogued vendor failure"),
    ],
    ids=["100002_auth", "100003_permission", "100004_not_found", "999999_uncatalogued"],
)
def test_uncatalogued_vendor_failure_maps_to_retryable_false(exc):
    result = translate_marketplace_error(exc)

    assert result.retryable is False
    assert result.category == ExecutionErrorCategory.TIKTOK_API


def test_uncatalogued_vendor_code_is_not_in_the_curated_allowlist():
    """Sanity check the fixture itself is actually uncatalogued (guards the
    test above against a future allowlist edit silently making it a
    false-negative)."""
    assert 999999 not in RETRYABLE_VENDOR_CODES


# ---------------------------------------------------------------------------
# Acceptance criterion 3: transport-level errors -> retryable: true
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "exc",
    [
        requests.ConnectionError("connection reset"),
        requests.Timeout("read timeout"),
        requests.exceptions.ConnectTimeout("could not connect"),
        requests.exceptions.ReadTimeout("read timed out"),
    ],
    ids=["connection_error", "timeout", "connect_timeout", "read_timeout"],
)
def test_transport_level_errors_map_to_retryable_true(exc):
    result = translate_marketplace_error(exc)

    assert result.retryable is True
    assert result.category == ExecutionErrorCategory.TRANSIENT


# ---------------------------------------------------------------------------
# A pre-signing TransportGuardError is a deterministic policy rejection —
# never transport-level for retry purposes, so it is NOT retryable.
# ---------------------------------------------------------------------------


def test_transport_guard_rejection_is_validation_category_and_not_retryable():
    exc = TransportGuardError(
        capability="production_read",
        method="POST",
        path="/order/202309/orders/search",
        message="Production-read transport rejected request before signing.",
    )

    result = translate_marketplace_error(exc)

    assert result.category == ExecutionErrorCategory.VALIDATION
    assert result.retryable is False


# ---------------------------------------------------------------------------
# Acceptance criterion 4: category values come from ExecutionErrorCategory;
# no new enum introduced.
# ---------------------------------------------------------------------------


def test_category_is_a_member_of_the_existing_execution_error_taxonomy():
    for exc in (
        RateLimitError(100005, "throttled"),
        TikTokAPIError(100002, "auth failed"),
        TransportGuardError(capability="sandbox_write", method="PUT", path="/x", message="blocked"),
        requests.ConnectionError("reset"),
        ValueError("not a marketplace error at all"),
    ):
        result = translate_marketplace_error(exc)
        assert isinstance(result.category, ExecutionErrorCategory)
        assert result.category in set(ExecutionErrorCategory)


def test_no_parallel_taxonomy_is_introduced():
    """`TranslatedError.category`'s annotation is `ExecutionErrorCategory`
    itself, and the errors module defines no `Enum` subclass of its own —
    every `Enum` reachable from its namespace is `ExecutionErrorCategory`."""
    import enum

    import juli_backend.services.agent.sanitize.errors as errors_module

    field = TranslatedError.__dataclass_fields__["category"]
    assert field.type in ("ExecutionErrorCategory", ExecutionErrorCategory)

    enums_in_module = [
        obj
        for obj in vars(errors_module).values()
        if isinstance(obj, type) and issubclass(obj, enum.Enum)
    ]
    assert enums_in_module, "expected ExecutionErrorCategory to be reachable from the module"
    assert all(e is ExecutionErrorCategory for e in enums_in_module)


def test_unknown_exception_falls_back_to_unknown_category_and_is_not_retryable():
    result = translate_marketplace_error(ValueError("something unrelated"))

    assert result.category == ExecutionErrorCategory.UNKNOWN
    assert result.retryable is False


# ---------------------------------------------------------------------------
# Acceptance criterion 5: no raw vendor code, endpoint path, or vendor
# request id anywhere in the envelope — asserted directly and adversarially.
# ---------------------------------------------------------------------------

_DISTINCTIVE_CODE = 100006
_DISTINCTIVE_REQUEST_ID = "202608081300060C6F542C42A3ED1E4CE0-SENTINEL"
_DISTINCTIVE_PATH = "/order/202309/orders/search/SENTINEL-PATH"


def test_envelope_never_contains_raw_vendor_code_request_id_or_path_tiktok_api_error():
    exc = TikTokAPIError(
        _DISTINCTIVE_CODE,
        "Internal error",
        request_id=_DISTINCTIVE_REQUEST_ID,
    )

    result = translate_marketplace_error(exc)
    envelope = to_error_envelope(result)

    haystack = _walk_strings(envelope)
    joined = "\n".join(haystack)
    assert str(_DISTINCTIVE_CODE) not in joined
    assert _DISTINCTIVE_REQUEST_ID not in joined
    assert _DISTINCTIVE_PATH not in joined
    assert set(envelope) == {"error"}
    assert set(envelope["error"]) == {"category", "message", "retryable"}


def test_envelope_never_contains_endpoint_path_from_transport_guard_error():
    exc = TransportGuardError(
        capability="production_read",
        method="POST",
        path=_DISTINCTIVE_PATH,
        message=f"Production-read transport rejected before signing: POST {_DISTINCTIVE_PATH}",
    )

    result = translate_marketplace_error(exc)
    envelope = to_error_envelope(result)

    joined = "\n".join(_walk_strings(envelope))
    assert _DISTINCTIVE_PATH not in joined
    assert "production_read" not in joined
    assert set(envelope["error"]) == {"category", "message", "retryable"}


def test_translated_error_to_dict_wire_shape():
    result = TranslatedError(
        category=ExecutionErrorCategory.TRANSIENT,
        message="TikTok Shop is temporarily unavailable.",
        retryable=True,
    )

    assert result.to_dict() == {
        "category": "transient",
        "message": "TikTok Shop is temporarily unavailable.",
        "retryable": True,
    }


def test_error_envelope_wraps_translated_error_under_error_key():
    translated = TranslatedError(
        category=ExecutionErrorCategory.TIKTOK_API,
        message="TikTok Shop rejected the request.",
        retryable=False,
    )

    assert to_error_envelope(translated) == {
        "error": {
            "category": "tiktok_api",
            "message": "TikTok Shop rejected the request.",
            "retryable": False,
        }
    }


# ---------------------------------------------------------------------------
# Acceptance criterion 6: the raw detail is still emitted to server-side logs
# ---------------------------------------------------------------------------


def test_raw_vendor_detail_is_logged_server_side(caplog):
    exc = TikTokAPIError(
        _DISTINCTIVE_CODE,
        "Internal error",
        request_id=_DISTINCTIVE_REQUEST_ID,
    )

    with caplog.at_level(logging.WARNING, logger="juli_backend.services.agent.sanitize.errors"):
        translate_marketplace_error(exc)

    records = [r for r in caplog.records if r.name == "juli_backend.services.agent.sanitize.errors"]
    assert records, "expected the raw marketplace error detail to be logged"
    record = records[0]
    assert record.vendor_code == _DISTINCTIVE_CODE
    assert record.vendor_request_id == _DISTINCTIVE_REQUEST_ID


def test_raw_endpoint_path_is_logged_server_side_for_transport_guard_error(caplog):
    exc = TransportGuardError(
        capability="production_read",
        method="POST",
        path=_DISTINCTIVE_PATH,
        message="blocked",
    )

    with caplog.at_level(logging.WARNING, logger="juli_backend.services.agent.sanitize.errors"):
        translate_marketplace_error(exc)

    records = [r for r in caplog.records if r.name == "juli_backend.services.agent.sanitize.errors"]
    assert records, "expected the raw endpoint path to be logged"
    record = records[0]
    assert record.endpoint_path == _DISTINCTIVE_PATH
    assert record.guard_capability == "production_read"
    assert record.guard_method == "POST"


# ---------------------------------------------------------------------------
# Acceptance criterion 7: message is business-language English, short and
# information-dense for a nano-class model — never the vendor's raw text.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "exc",
    [
        RateLimitError(100005, "Request throttled"),
        TikTokSystemError(100006, "Internal error"),
        TikTokAPIError(36009003, "Internal error. Please try again."),
        AuthenticationError(100002, "Token expired"),
        TikTokAPIError(999999, "Some uncatalogued vendor failure"),
        requests.ConnectionError("connection reset"),
        TransportGuardError(capability="x", method="GET", path="/y", message="blocked"),
        ValueError("boom"),
    ],
)
def test_message_is_short_business_english_and_never_the_raw_vendor_text(exc):
    result = translate_marketplace_error(exc)

    assert result.message
    assert result.message.isascii()
    # Nano-class context budget: keep every curated message well under the
    # ~1,500-char free-text cap this package enforces elsewhere — in practice
    # each of these fixed sentences is well under 200 characters.
    assert len(result.message) < 200
    # Never the vendor's raw code-prefixed text, e.g. "[100006] Internal error".
    assert "[" not in result.message
    raw_vendor_text = getattr(exc, "message", None)
    if raw_vendor_text:
        assert raw_vendor_text not in result.message


def test_message_does_not_vary_with_vendor_free_text_content():
    """Two different raw vendor messages for the same code produce the exact
    same curated message — the translator never interpolates vendor text."""
    exc_a = TikTokSystemError(100006, "Internal error A")
    exc_b = TikTokSystemError(100006, "A completely different internal error B")

    assert translate_marketplace_error(exc_a).message == translate_marketplace_error(exc_b).message
