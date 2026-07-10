"""TikTok Shop webhook HMAC-SHA256 signature verification."""

from __future__ import annotations

import hashlib
import hmac


class TikTokWebhookSignatureVerifier:
    """Verifies the ``Authorization`` header on inbound webhook requests."""

    def __init__(self, *, app_key: str, app_secret: str, path: str) -> None:
        self._app_key = app_key
        self._app_secret = app_secret
        self._path = path

    def verify(self, body: bytes, received_sig: str) -> bool:
        """Return True when the received signature matches the expected HMAC."""
        sign_string = f"{self._app_key}{self._path}{body.decode()}"
        expected = hmac.new(
            self._app_secret.encode(),
            sign_string.encode(),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, received_sig)
