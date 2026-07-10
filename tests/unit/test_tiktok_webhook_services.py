"""Unit tests for TikTok webhook dispatcher and signature verifier."""

from __future__ import annotations

import pytest

from juli_backend.services.tiktok.dispatcher import TikTokWebhookDispatcher
from juli_backend.services.tiktok.schemas import TikTokWebhookPayload
from juli_backend.services.tiktok.signature import TikTokWebhookSignatureVerifier


class TestWebhookDispatcher:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("event_type", "expected_handler"),
        [
            ("ORDER_CREATED", "order_created"),
            ("ORDER_PAID", "order_paid"),
            ("ORDER_CANCELLED", "order_cancelled"),
            ("REFUND_CREATED", "refund_created"),
            ("PRODUCT_STATUS_CHANGE", "unknown_event"),
        ],
    )
    async def test_dispatches_to_expected_handler(self, event_type, expected_handler):
        dispatcher = TikTokWebhookDispatcher()
        event = TikTokWebhookPayload(type=event_type, shop_id="shop_1")

        handler_name = await dispatcher.dispatch(event)

        assert handler_name == expected_handler


class TestWebhookSignatureVerifier:
    def test_verify_matches_hmac_helper(self):
        import hashlib
        import hmac

        app_key = "key"
        app_secret = "secret"
        path = "/webhooks/tiktok"
        body = b'{"type":"ORDER_CREATED","shop_id":"s1"}'
        sign_string = f"{app_key}{path}{body.decode()}"
        sig = hmac.new(
            app_secret.encode(), sign_string.encode(), hashlib.sha256
        ).hexdigest()

        verifier = TikTokWebhookSignatureVerifier(
            app_key=app_key, app_secret=app_secret, path=path
        )
        assert verifier.verify(body, sig) is True
        assert verifier.verify(body, "bad") is False
