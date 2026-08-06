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
            ("ORDER_STATUS_CHANGE", "order_status_change"),
            ("PRODUCT_STATUS_CHANGE", "product_status_change"),
            ("AFFILIATE_COMMISSION_CHANGE", "deferred_out_of_scope"),
            ("MYSTERY_EVENT", "unknown_event"),
        ],
    )
    async def test_dispatches_to_expected_handler(self, event_type, expected_handler):
        dispatcher = TikTokWebhookDispatcher()
        event = TikTokWebhookPayload(type=event_type, shop_id="shop_1")

        handler_name = await dispatcher.dispatch(event)

        assert handler_name == expected_handler


class TestWebhookSignatureVerifier:
    def test_verify_with_correct_algorithm_app_key_plus_body_only(self):
        """Test that signature verification uses ONLY app_key + body (no path).

        Per TikTok's webhook documentation and diagnostic against 3 real captured events,
        the correct signing algorithm is: HMAC-SHA256(app_secret, app_key + raw_body) → hex.
        The path is NOT included in webhook signatures (unlike API request signing).
        """
        import hashlib
        import hmac

        app_key = "test_app_key"
        app_secret = "test_app_secret"
        body = b'{"type":"ORDER_STATUS_CHANGE","shop_id":"123456"}'

        # Compute the correct signature using app_key + body (no path)
        sign_string = f"{app_key}{body.decode()}"
        correct_sig = hmac.new(
            app_secret.encode(), sign_string.encode(), hashlib.sha256
        ).hexdigest()

        verifier = TikTokWebhookSignatureVerifier(app_key=app_key, app_secret=app_secret)
        assert verifier.verify(body, correct_sig) is True

    def test_verify_rejects_tampered_body(self):
        """Verify that a tampered body is rejected."""
        import hashlib
        import hmac

        app_key = "test_app_key"
        app_secret = "test_app_secret"
        body = b'{"type":"ORDER_STATUS_CHANGE","shop_id":"123456"}'

        # Compute signature for original body
        sign_string = f"{app_key}{body.decode()}"
        sig = hmac.new(app_secret.encode(), sign_string.encode(), hashlib.sha256).hexdigest()

        # Tamper with body
        tampered_body = b'{"type":"ORDER_STATUS_CHANGE","shop_id":"999999"}'

        verifier = TikTokWebhookSignatureVerifier(app_key=app_key, app_secret=app_secret)
        # Signature should NOT match tampered body
        assert verifier.verify(tampered_body, sig) is False

    def test_verify_rejects_wrong_signature(self):
        """Verify that wrong/absent signatures are rejected."""
        app_key = "test_app_key"
        app_secret = "test_app_secret"
        body = b'{"type":"ORDER_STATUS_CHANGE","shop_id":"123456"}'

        verifier = TikTokWebhookSignatureVerifier(app_key=app_key, app_secret=app_secret)
        assert verifier.verify(body, "completely_invalid_sig") is False
        assert verifier.verify(body, "") is False

    def test_algorithm_pins_app_key_plus_body_no_path(self):
        """Explicit pin that the algorithm is app_key + body (no path).

        This test will fail if anyone reintroduces the path into the signing string.
        """
        import hashlib
        import hmac

        app_key = "key123"
        app_secret = "secret456"
        path = "/webhooks/tiktok"
        body = b'{"data":"test"}'

        # Correct algorithm: app_key + body ONLY
        sign_string_correct = f"{app_key}{body.decode()}"
        correct_sig = hmac.new(
            app_secret.encode(), sign_string_correct.encode(), hashlib.sha256
        ).hexdigest()

        # Wrong algorithm (with path) - should NOT match
        sign_string_wrong = f"{app_key}{path}{body.decode()}"
        wrong_sig = hmac.new(
            app_secret.encode(), sign_string_wrong.encode(), hashlib.sha256
        ).hexdigest()

        verifier = TikTokWebhookSignatureVerifier(app_key=app_key, app_secret=app_secret)

        # Correct signature should verify
        assert verifier.verify(body, correct_sig) is True
        # Wrong signature (with path) should NOT verify
        assert verifier.verify(body, wrong_sig) is False
