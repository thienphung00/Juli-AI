"""TDD tests for HMAC-SHA256 request signing.

Behaviors under test:
- Signature is computed from sorted params, path, and body
- sign and access_token params are excluded from signature input
- Empty body is handled correctly
- Produces a lowercase hex digest
- Deterministic: same inputs → same signature
"""
import hmac
import hashlib

import pytest

from src.modules.catalog.domain.integrations.tiktok.signing import sign_request


@pytest.fixture
def secret():
    return "my_app_secret"


class TestSignRequest:
    def test_produces_lowercase_hex_string(self, secret):
        sig = sign_request(
            app_secret=secret,
            path="/api/orders/search",
            params={"app_key": "key123", "timestamp": "1700000000"},
        )
        assert isinstance(sig, str)
        assert sig == sig.lower()
        assert all(c in "0123456789abcdef" for c in sig)
        assert len(sig) == 64  # SHA-256 hex = 64 chars

    def test_deterministic_same_inputs_same_output(self, secret):
        kwargs = dict(
            app_secret=secret,
            path="/api/products/search",
            params={"app_key": "k", "timestamp": "1"},
        )
        assert sign_request(**kwargs) == sign_request(**kwargs)

    def test_different_params_produce_different_signatures(self, secret):
        base = dict(app_secret=secret, path="/api/orders/search")
        sig_a = sign_request(**base, params={"app_key": "k", "timestamp": "1"})
        sig_b = sign_request(**base, params={"app_key": "k", "timestamp": "2"})
        assert sig_a != sig_b

    def test_params_sorted_alphabetically(self, secret):
        """Order of params dict should not affect the signature."""
        path = "/api/orders/search"
        params_ordered = {"app_key": "k", "foo": "bar", "timestamp": "1"}
        params_reversed = {"timestamp": "1", "foo": "bar", "app_key": "k"}

        sig_a = sign_request(app_secret=secret, path=path, params=params_ordered)
        sig_b = sign_request(app_secret=secret, path=path, params=params_reversed)
        assert sig_a == sig_b

    def test_excludes_sign_and_access_token_from_input(self, secret):
        path = "/api/orders/search"
        clean_params = {"app_key": "k", "timestamp": "1"}
        dirty_params = {
            "app_key": "k",
            "timestamp": "1",
            "sign": "should_be_ignored",
            "access_token": "should_be_ignored",
        }
        sig_clean = sign_request(app_secret=secret, path=path, params=clean_params)
        sig_dirty = sign_request(app_secret=secret, path=path, params=dirty_params)
        assert sig_clean == sig_dirty

    def test_includes_body_when_provided(self, secret):
        path = "/api/orders/search"
        params = {"app_key": "k", "timestamp": "1"}

        sig_no_body = sign_request(app_secret=secret, path=path, params=params)
        sig_with_body = sign_request(
            app_secret=secret,
            path=path,
            params=params,
            body='{"status": "COMPLETED"}',
        )
        assert sig_no_body != sig_with_body

    def test_empty_body_same_as_no_body(self, secret):
        path = "/api/orders/search"
        params = {"app_key": "k", "timestamp": "1"}

        sig_none = sign_request(app_secret=secret, path=path, params=params)
        sig_empty = sign_request(
            app_secret=secret, path=path, params=params, body=""
        )
        assert sig_none == sig_empty

    def test_matches_known_reference_value(self, secret):
        """Verify against a hand-computed HMAC to catch algorithm bugs.

        Algorithm per authentication.md:
        1. Filter out 'sign' and 'access_token'
        2. Sort remaining params by key
        3. Concatenate as key-value pairs (no separator)
        4. Build: {secret}{path}{canonical}{body}{secret}
        5. HMAC-SHA256 with secret as key
        """
        path = "/api/orders/search"
        params = {"app_key": "demo_key", "timestamp": "1700000000"}
        body = '{"status":"COMPLETED"}'

        sorted_params = sorted(params.items())
        canonical = "".join(f"{k}{v}" for k, v in sorted_params)
        sign_string = f"{secret}{path}{canonical}{body}{secret}"
        expected = hmac.new(
            secret.encode(), sign_string.encode(), hashlib.sha256
        ).hexdigest()

        actual = sign_request(
            app_secret=secret, path=path, params=params, body=body
        )
        assert actual == expected
