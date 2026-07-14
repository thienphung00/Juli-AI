"""Unit tests for TikTok webhook PII redaction (#392)."""

from __future__ import annotations

import json

from juli_backend.services.tiktok.webhook_redaction import (
    RAW_BODY_MAX_BYTES,
    redact_webhook_body,
)


class TestRedactWebhookBody:
    def test_redacts_denylist_keys_case_insensitive(self) -> None:
        body = json.dumps(
            {
                "type": "ORDER_STATUS_CHANGE",
                "buyer_Name": "Alice",
                "Phone": "+84900000000",
                "order_id": "5771",
            }
        ).encode()

        redacted = redact_webhook_body(body)
        assert redacted is not None
        parsed = json.loads(redacted)
        assert parsed["buyer_Name"] == "[REDACTED]"
        assert parsed["Phone"] == "[REDACTED]"
        assert parsed["order_id"] == "5771"
        assert parsed["type"] == "ORDER_STATUS_CHANGE"

    def test_redacts_nested_dicts_and_list_of_dicts(self) -> None:
        body = json.dumps(
            {
                "data": {
                    "recipient": {
                        "full_name": "Bob",
                        "street_address": "1 Main St",
                        "city": "Hanoi",
                    },
                    "items": [
                        {"sku": "A", "email": "a@example.com"},
                        {"sku": "B", "mobile": "090"},
                    ],
                }
            }
        ).encode()

        redacted = redact_webhook_body(body)
        assert redacted is not None
        parsed = json.loads(redacted)
        recipient = parsed["data"]["recipient"]
        assert recipient["full_name"] == "[REDACTED]"
        assert recipient["street_address"] == "[REDACTED]"
        assert recipient["city"] == "[REDACTED]"
        assert parsed["data"]["items"][0]["email"] == "[REDACTED]"
        assert parsed["data"]["items"][0]["sku"] == "A"
        assert parsed["data"]["items"][1]["mobile"] == "[REDACTED]"

    def test_non_json_returns_none(self) -> None:
        assert redact_webhook_body(b"not-json") is None

    def test_truncates_oversized_redacted_json(self) -> None:
        # Large non-PII payload that exceeds the size cap after serialize.
        payload = {"type": "X", "blob": "x" * (RAW_BODY_MAX_BYTES + 2048)}
        body = json.dumps(payload).encode()

        redacted = redact_webhook_body(body)
        assert redacted is not None
        assert len(redacted.encode("utf-8")) <= RAW_BODY_MAX_BYTES
        assert redacted.endswith("…[TRUNCATED]")

    def test_preserves_structure_for_empty_object(self) -> None:
        redacted = redact_webhook_body(b"{}")
        assert redacted == "{}"
