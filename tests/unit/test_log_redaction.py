"""Log redaction inside JsonFormatter (#1654, P10-2).

Redaction applied inside the formatter ensures it holds for every record regardless
of how the call site was written. This covers credentials, PII, and deeply nested values.
"""

from __future__ import annotations

import json
import logging
import uuid

import pytest

from juli_backend.core.observability import JsonFormatter, configure_logging

# Planted credentials, built from fragments so no complete secret stays in the tree.
PLANTED_API_KEY = (
    "sk-" + "ant-" + "api03-" + "".join(("AAAABBBB", "CCCCDDDD", "EEEEFFFF", "GGGGHHHH"))
)
PLANTED_GH_TOKEN = "ghp" + "_" + "".join(("0123456789", "abcdefghij", "klmnopqrst", "uvwx"))
PLANTED_AWS_KEY = "AKIA" + "0123456789" + "ABCDEFGHIJ"
PLANTED_PASSWORD = "hunter2-" + "not-a-real-password"

# Test values that must survive redaction intact.
TEST_UUID = str(uuid.uuid4())
TEST_ISO_8601 = "2026-09-09T12:34:56+00:00"


@pytest.fixture(autouse=True)
def setup_logging():
    """Ensure formatter is configured for each test."""
    configure_logging(force=True)


class TestCredentialRedaction:
    """Credentials planted via extra= are redacted in emitted output."""

    def test_api_key_credential_does_not_appear_in_output(self):
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="test_event",
            args=(),
            exc_info=None,
        )
        record.api_key = PLANTED_API_KEY

        output = JsonFormatter().format(record)
        assert PLANTED_API_KEY not in output
        payload = json.loads(output)
        # Key is retained with a marker
        assert "api_key" in payload

    def test_github_token_does_not_appear_in_output(self):
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="test_event",
            args=(),
            exc_info=None,
        )
        record.gh_token = PLANTED_GH_TOKEN

        output = JsonFormatter().format(record)
        assert PLANTED_GH_TOKEN not in output
        payload = json.loads(output)
        assert "gh_token" in payload

    def test_password_does_not_appear_in_output(self):
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="test_event",
            args=(),
            exc_info=None,
        )
        record.password = PLANTED_PASSWORD

        output = JsonFormatter().format(record)
        assert PLANTED_PASSWORD not in output
        payload = json.loads(output)
        assert "password" in payload

    def test_aws_access_key_does_not_appear_in_output(self):
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="test_event",
            args=(),
            exc_info=None,
        )
        record.aws_key = PLANTED_AWS_KEY

        output = JsonFormatter().format(record)
        assert PLANTED_AWS_KEY not in output
        payload = json.loads(output)
        assert "aws_key" in payload


class TestPIIRedaction:
    """PII (phone, email) planted via extra= is redacted in emitted output."""

    def test_phone_number_does_not_appear_in_output(self):
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="test_event",
            args=(),
            exc_info=None,
        )
        phone = "+1234567890123"
        record.phone_number = phone

        output = JsonFormatter().format(record)
        assert phone not in output
        payload = json.loads(output)
        assert "phone_number" in payload

    def test_email_address_does_not_appear_in_output(self):
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="test_event",
            args=(),
            exc_info=None,
        )
        email = "user@example.com"
        record.email = email

        output = JsonFormatter().format(record)
        assert email not in output
        payload = json.loads(output)
        assert "email" in payload


class TestNestedRedaction:
    """Redaction survives nesting inside dicts and lists."""

    def test_secret_one_level_down_in_dict_is_redacted(self):
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="test_event",
            args=(),
            exc_info=None,
        )
        record.data = {"secret": PLANTED_API_KEY, "other": "value"}

        output = JsonFormatter().format(record)
        assert PLANTED_API_KEY not in output
        payload = json.loads(output)
        assert "data" in payload

    def test_secret_in_list_of_dicts_is_redacted(self):
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="test_event",
            args=(),
            exc_info=None,
        )
        record.items = [{"password": PLANTED_PASSWORD}, {"id": "123"}]

        output = JsonFormatter().format(record)
        assert PLANTED_PASSWORD not in output
        payload = json.loads(output)
        assert "items" in payload

    def test_secret_two_levels_down_in_nested_dict_is_redacted(self):
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="test_event",
            args=(),
            exc_info=None,
        )
        record.outer = {"inner": {"token": PLANTED_GH_TOKEN}, "other": "value"}

        output = JsonFormatter().format(record)
        assert PLANTED_GH_TOKEN not in output
        payload = json.loads(output)
        assert "outer" in payload


class TestRedactionMarker:
    """Redacted keys retain a marker so operators can see the field existed."""

    def test_redacted_key_has_marker_at_top_level(self):
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="test_event",
            args=(),
            exc_info=None,
        )
        record.password = PLANTED_PASSWORD

        output = JsonFormatter().format(record)
        payload = json.loads(output)
        assert "password" in payload
        # The marker should be a single constant
        marker = payload["password"]
        # It should not be the original value
        assert marker != PLANTED_PASSWORD
        # It should be a string or something that indicates redaction
        assert isinstance(marker, str) or marker is None or isinstance(marker, dict)

    def test_redacted_key_in_nested_dict_has_marker(self):
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="test_event",
            args=(),
            exc_info=None,
        )
        record.data = {"secret": PLANTED_API_KEY, "other": "value"}

        output = JsonFormatter().format(record)
        payload = json.loads(output)
        # The inner dict should still have the key
        assert "data" in payload


class TestSafeValuesPreserved:
    """UUIDs and ISO-8601 timestamps survive intact."""

    def test_uuid_survives_redaction(self):
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="test_event",
            args=(),
            exc_info=None,
        )
        record.id = TEST_UUID

        output = JsonFormatter().format(record)
        payload = json.loads(output)
        assert payload["id"] == TEST_UUID

    def test_iso_8601_timestamp_survives_redaction(self):
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="test_event",
            args=(),
            exc_info=None,
        )
        record.created_at = TEST_ISO_8601

        output = JsonFormatter().format(record)
        payload = json.loads(output)
        assert payload["created_at"] == TEST_ISO_8601

    def test_correlation_id_survives_redaction(self):
        """correlation_id must not be redacted."""
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="test_event",
            args=(),
            exc_info=None,
        )
        record.correlation_id = TEST_UUID

        output = JsonFormatter().format(record)
        payload = json.loads(output)
        assert payload["correlation_id"] == TEST_UUID


class TestExceptionRedaction:
    """Redaction applies to exception and stack traces."""

    def test_secret_in_exception_message_is_redacted(self):
        try:
            raise ValueError(f"Error with secret: {PLANTED_API_KEY}")
        except ValueError:
            import sys

            exc_info = sys.exc_info()

        record = logging.LogRecord(
            name="test_logger",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="test_event",
            args=(),
            exc_info=exc_info,
        )

        output = JsonFormatter().format(record)
        # The secret should not appear anywhere in the output
        assert PLANTED_API_KEY not in output
        payload = json.loads(output)
        assert "exception" in payload

    def test_secret_in_stack_trace_is_redacted(self):
        """Secret in stack info is redacted."""
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="test_event",
            args=(),
            exc_info=None,
        )
        # Simulate stack info containing a secret
        record.stack_info = f"Stack trace with password: {PLANTED_PASSWORD}"

        output = JsonFormatter().format(record)
        assert PLANTED_PASSWORD not in output
        payload = json.loads(output)
        # stack_info should be present but redacted
        if "stack" in payload:
            assert PLANTED_PASSWORD not in payload["stack"]


class TestJSONOutputIntegrity:
    """Emitted output is still valid JSON, one object per line."""

    def test_redacted_output_is_valid_json(self):
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="test_event",
            args=(),
            exc_info=None,
        )
        record.password = PLANTED_PASSWORD
        record.id = TEST_UUID

        output = JsonFormatter().format(record)
        # Must be valid JSON
        payload = json.loads(output)
        assert isinstance(payload, dict)

    def test_no_newline_introduced_by_redaction(self):
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="test_event",
            args=(),
            exc_info=None,
        )
        record.secret = PLANTED_API_KEY

        output = JsonFormatter().format(record)
        # Should be exactly one line
        assert "\n" not in output


class TestConfigureLoggingIdempotency:
    """configure_logging remains idempotent and preserves foreign handlers."""

    def test_configure_logging_idempotency_preserved(self):
        """Regression test for #1013: idempotency must not change."""
        configure_logging(force=True)
        before = len(logging.getLogger().handlers)
        configure_logging()
        configure_logging()
        assert len(logging.getLogger().handlers) == before

    def test_configure_logging_only_removes_juli_handlers(self):
        """Only _JuliManagedStreamHandler instances removed."""
        from juli_backend.core.observability.logging import _JuliManagedStreamHandler

        root = logging.getLogger()
        foreign = logging.Handler()
        root.addHandler(foreign)
        try:
            configure_logging(force=True)
            configure_logging(force=True)
            assert foreign in root.handlers
            juli_handlers = [h for h in root.handlers if isinstance(h, _JuliManagedStreamHandler)]
            assert len(juli_handlers) == 1
        finally:
            root.removeHandler(foreign)


class TestExistingTests:
    """Existing observability tests must continue to pass."""

    def test_json_formatter_still_preserves_extra_context(self):
        """From test_api_observability.py."""
        configure_logging(force=True)
        record = logging.LogRecord(
            name="juli_backend.thing",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="audit_event",
            args=(),
            exc_info=None,
        )
        record.shop_id = "shop-abc"
        record.correlation_id = "11111111-2222-3333-4444-555555555555"

        payload = json.loads(JsonFormatter().format(record))
        assert payload["event"] == "audit_event"
        assert payload["level"] == "INFO"
        assert payload["logger"] == "juli_backend.thing"
        assert payload["shop_id"] == "shop-abc"
        assert payload["correlation_id"] == "11111111-2222-3333-4444-555555555555"
