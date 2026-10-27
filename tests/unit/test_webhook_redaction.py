"""Unit tests for the stored-webhook field allowlist (#392; owner decision D16).

The archive used to apply a key DENYLIST; ``message``, ``note``, ``avatar``,
``buyer_id``, ``user_id``, ``comment`` and ``reason`` went through it. It is now
an allowlist per webhook kind (``services/privacy/payload_allowlist``,
``webhook.*``): anything not listed is dropped at any depth.
"""

from __future__ import annotations

import json

import pytest

from juli_backend.services.privacy.payload_allowlist import (
    WEBHOOK_ORDER,
    WEBHOOK_OTHER,
    WEBHOOK_RETURN,
    WEBHOOK_UNKNOWN,
)
from juli_backend.services.tiktok.webhook_redaction import (
    RAW_BODY_MAX_BYTES,
    drop_buyer_ids,
    has_buyer_id,
    redact_webhook_body,
    serialize_stored_body,
    webhook_endpoint,
)


class TestWebhookEndpoint:
    @pytest.mark.parametrize(
        ("event_type", "endpoint"),
        [
            ("ORDER_STATUS_CHANGE", WEBHOOK_ORDER),
            (1, WEBHOOK_ORDER),
            ("3", WEBHOOK_ORDER),
            ("PACKAGE_UPDATE", WEBHOOK_ORDER),
            ("CANCELLATION_STATUS_CHANGE", WEBHOOK_RETURN),
            (12, WEBHOOK_RETURN),
            ("REVERSE_STATUS_UPDATE", WEBHOOK_RETURN),
            ("PRODUCT_STATUS_CHANGE", WEBHOOK_OTHER),
            ("SELLER_DEAUTHORIZATION", WEBHOOK_OTHER),
            ("NEW_MESSAGE", WEBHOOK_UNKNOWN),
            ("TOTALLY_UNKNOWN", WEBHOOK_UNKNOWN),
            (None, WEBHOOK_UNKNOWN),
            ("", WEBHOOK_UNKNOWN),
        ],
    )
    def test_kind_of_each_delivered_type(self, event_type, endpoint) -> None:
        assert webhook_endpoint(event_type) == endpoint


class TestRedactWebhookBody:
    def test_keeps_the_envelope_and_listed_ids_and_drops_every_buyer_field(self) -> None:
        body = json.dumps(
            {
                "type": "ORDER_STATUS_CHANGE",
                "shop_id": "7000000000000001",
                "timestamp": 1761400000,
                "tts_notification_id": "n-1",
                "buyer_Name": "Alice",
                "data": {
                    "order_id": "5771",
                    "order_status": "AWAITING_SHIPMENT",
                    "update_time": 1761400000,
                    "buyer_id": "7494011223344556677",
                    "user_id": "7494011223344556677",
                    "buyer_message": "call me",
                    "buyer_email": "a@example.invalid",
                    "buyer_avatar": "https://example.invalid/a.png",
                    "note": "free text",
                    "reason": "free text",
                    "recipient_address": {"name": "Bob", "phone_number": "0900000000"},
                },
            }
        ).encode()

        redacted = redact_webhook_body(body)
        assert redacted is not None
        assert json.loads(redacted) == {
            "type": "ORDER_STATUS_CHANGE",
            "shop_id": "7000000000000001",
            "timestamp": 1761400000,
            "tts_notification_id": "n-1",
            "data": {
                "order_id": "5771",
                "order_status": "AWAITING_SHIPMENT",
                "update_time": 1761400000,
            },
        }

    def test_nested_lists_keep_only_listed_keys(self) -> None:
        body = json.dumps(
            {
                "type": "PACKAGE_UPDATE",
                "shop_id": "s",
                "data": {
                    "order_id": "o",
                    "package_list": [
                        {"package_id": "p1", "sku_list": [{"sku_id": "k", "comment": "x"}]},
                        {"package_id": "p2", "recipient": {"full_name": "Bob"}},
                    ],
                },
            }
        ).encode()

        parsed = json.loads(redact_webhook_body(body) or "{}")
        assert parsed["data"]["package_list"] == [
            {"package_id": "p1", "sku_list": [{"sku_id": "k"}]},
            {"package_id": "p2"},
        ]

    def test_an_unknown_type_keeps_the_envelope_only(self) -> None:
        body = json.dumps(
            {"type": "NEW_MESSAGE", "shop_id": "s", "data": {"content": "hello from a buyer"}}
        ).encode()

        assert json.loads(redact_webhook_body(body) or "{}") == {
            "type": "NEW_MESSAGE",
            "shop_id": "s",
        }

    def test_non_json_and_non_object_return_none(self) -> None:
        assert redact_webhook_body(b"not-json") is None
        assert redact_webhook_body(b"[1, 2]") is None

    def test_truncates_oversized_serialized_json(self) -> None:
        payload = {"type": "X", "shop_id": "x" * (RAW_BODY_MAX_BYTES + 2048)}

        stored = serialize_stored_body(payload)
        assert len(stored.encode("utf-8")) <= RAW_BODY_MAX_BYTES
        assert stored.endswith("…[TRUNCATED]")

    def test_empty_object_stays_empty(self) -> None:
        assert redact_webhook_body(b"{}") == "{}"


class TestBuyerIds:
    def test_found_and_dropped_at_any_depth(self) -> None:
        value = {"data": {"buyer_id": "1", "items": [{"buyer_id": "2", "sku_id": "k"}]}}

        assert has_buyer_id(value)
        assert drop_buyer_ids(value) == {"data": {"items": [{"sku_id": "k"}]}}
        assert not has_buyer_id(drop_buyer_ids(value))
        assert not has_buyer_id({"data": {"buyer_id": ""}})
