"""Issue #1282, AGT-W5B -- `verify_supabase_jwt` ES256/JWKS verification.

The deployed Supabase project issues ES256 tokens; the previous HS256-only
decode path rejected every one of them with `InvalidAlgorithmError` before
the secret was ever consulted, taking down every authenticated route. This
covers the fix at the `verify_supabase_jwt` level (below `get_current_user`,
which `test_get_current_user_es256.py` exercises end to end through a
shop-scoped route):

- a real-shaped ES256 token (a generated EC P-256 keypair, signed with
  PyJWT, verified against a JWKS fixture -- not a self-minted HS256 token)
  verifies successfully
- a token signed with the wrong key is rejected
- an unexpected `alg` -- including `none` -- is rejected before either
  verifier runs
- a wrong-audience token is rejected
- an unreachable JWKS fails closed, logged under a name distinguishable
  from a bad token
- HS256 keeps working unmodified (the owner may re-enable Supabase's legacy
  shared secret as a stopgap; that path must not regress)
"""

from __future__ import annotations

import base64
import json

import httpx
import pytest

import juli_backend.core.security.jwt as jwt_module
from juli_backend.core.security.exceptions import Unauthorized
from juli_backend.core.security.jwks import JwksClient
from juli_backend.core.security.jwt import verify_supabase_jwt
from tests.unit._es256_test_keys import generate_es256_keypair, jwks_document, sign_es256_token

HS256_SECRET = "test-jwt-secret-for-es256-suite"


@pytest.fixture(autouse=True)
def _reset_jwks_singleton():
    """Isolate every test from the module-level JWKS client singleton."""
    jwt_module._default_jwks_client = None
    yield
    jwt_module._default_jwks_client = None


def _install_jwks_client(*jwk_dicts: dict) -> None:
    def _handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=jwks_document(*jwk_dicts))

    jwt_module._default_jwks_client = JwksClient(
        "https://test-project.supabase.co/auth/v1/.well-known/jwks.json",
        transport=httpx.MockTransport(_handle),
    )


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unsigned_alg_none_token(sub: str = "00000000-0000-0000-0000-000000000000") -> str:
    """Craft a raw `alg: none` token -- no signature, no key involved at
    all. Must be rejected purely by the algorithm allowlist."""
    header = {"alg": "none", "typ": "JWT"}
    payload = {"sub": sub, "aud": "authenticated", "role": "authenticated"}
    header_b64 = _b64url(json.dumps(header, separators=(",", ":")).encode())
    payload_b64 = _b64url(json.dumps(payload, separators=(",", ":")).encode())
    return f"{header_b64}.{payload_b64}."


class TestEs256HappyPath:
    async def test_real_shaped_es256_token_verifies(self):
        """AC: at least one test exercises a real-shaped ES256 token --
        generated EC keypair, signed, verified against a JWKS fixture."""
        private_key, kid, jwk = generate_es256_keypair()
        _install_jwks_client(jwk)
        token = sign_es256_token(private_key, kid, sub="11111111-1111-1111-1111-111111111111")

        payload = await verify_supabase_jwt(token, HS256_SECRET)

        assert payload["sub"] == "11111111-1111-1111-1111-111111111111"
        assert payload["aud"] == "authenticated"


class TestWrongKeyRejected:
    async def test_token_signed_by_wrong_key_is_rejected(self):
        """The JWKS advertises the legitimate key under `kid`; the token
        presented was signed by a *different* private key but claims that
        same `kid` -- the classic forged-signature case."""
        _legit_private_key, kid, legit_jwk = generate_es256_keypair(kid="shared-kid")
        attacker_private_key, _attacker_kid, _attacker_jwk = generate_es256_keypair()
        _install_jwks_client(legit_jwk)

        forged_token = sign_es256_token(attacker_private_key, kid)

        with pytest.raises(Unauthorized):
            await verify_supabase_jwt(forged_token, HS256_SECRET)

    async def test_kid_absent_from_jwks_is_rejected(self):
        private_key, _real_kid, jwk = generate_es256_keypair()
        _install_jwks_client(jwk)
        token = sign_es256_token(private_key, "a-kid-not-in-the-jwks")

        with pytest.raises(Unauthorized):
            await verify_supabase_jwt(token, HS256_SECRET)


class TestUnexpectedAlgorithmRejected:
    async def test_alg_none_is_rejected(self):
        """AC: `alg: none` must be impossible -- rejected by the allowlist
        before any verifier (HS256 or ES256) ever runs."""
        with pytest.raises(Unauthorized, match="Unsupported algorithm"):
            await verify_supabase_jwt(_unsigned_alg_none_token(), HS256_SECRET)

    async def test_rs256_is_rejected(self):
        """Not in `_SUPPORTED_ALGORITHMS` -- rejected even though PyJWT
        itself supports RS256 verification in the abstract."""
        # A syntactically well-formed but unverifiable RS256-header token is
        # enough: the allowlist rejects it purely from the header, before
        # any key material is ever looked up.
        header = {"alg": "RS256", "kid": "whatever", "typ": "JWT"}
        payload = {"sub": "x", "aud": "authenticated"}
        token = (
            f"{_b64url(json.dumps(header).encode())}.{_b64url(json.dumps(payload).encode())}.sig"
        )

        with pytest.raises(Unauthorized, match="Unsupported algorithm"):
            await verify_supabase_jwt(token, HS256_SECRET)


class TestWrongAudienceRejected:
    async def test_es256_wrong_audience_is_rejected(self):
        private_key, kid, jwk = generate_es256_keypair()
        _install_jwks_client(jwk)
        token = sign_es256_token(private_key, kid, aud="some-other-audience")

        with pytest.raises(Unauthorized):
            await verify_supabase_jwt(token, HS256_SECRET)

    async def test_hs256_wrong_audience_is_rejected(self):
        from datetime import UTC, datetime, timedelta

        import jwt as pyjwt

        token = pyjwt.encode(
            {
                "sub": "x",
                "aud": "some-other-audience",
                "exp": datetime.now(UTC) + timedelta(hours=1),
            },
            HS256_SECRET,
            algorithm="HS256",
        )

        with pytest.raises(Unauthorized):
            await verify_supabase_jwt(token, HS256_SECRET)


class TestJwksUnreachableFailsClosed:
    async def test_unreachable_jwks_fails_closed_and_logs_distinguishably(self, caplog):
        private_key, kid, _jwk = generate_es256_keypair()

        def _raise(_: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused")

        jwt_module._default_jwks_client = JwksClient(
            "https://test-project.supabase.co/auth/v1/.well-known/jwks.json",
            transport=httpx.MockTransport(_raise),
        )
        token = sign_es256_token(private_key, kid)

        with caplog.at_level("WARNING"):
            with pytest.raises(Unauthorized):
                await verify_supabase_jwt(token, HS256_SECRET)

        events = [record.message for record in caplog.records]
        assert "jwt_jwks_unavailable" in events
        # Distinguishable from a bad-token rejection -- must not be logged
        # under the same event name a forged/expired token would use.
        assert "jwt_invalid" not in events
        assert "jwt_expired" not in events


class TestHs256StillWorksUnmodified:
    async def test_valid_hs256_token_still_verifies(self):
        from datetime import UTC, datetime, timedelta

        import jwt as pyjwt

        token = pyjwt.encode(
            {
                "sub": "22222222-2222-2222-2222-222222222222",
                "aud": "authenticated",
                "exp": datetime.now(UTC) + timedelta(hours=1),
            },
            HS256_SECRET,
            algorithm="HS256",
        )

        payload = await verify_supabase_jwt(token, HS256_SECRET)

        assert payload["sub"] == "22222222-2222-2222-2222-222222222222"

    async def test_hs256_token_signed_with_wrong_secret_is_rejected(self):
        from datetime import UTC, datetime, timedelta

        import jwt as pyjwt

        token = pyjwt.encode(
            {"sub": "x", "aud": "authenticated", "exp": datetime.now(UTC) + timedelta(hours=1)},
            "a-different-secret",
            algorithm="HS256",
        )

        with pytest.raises(Unauthorized):
            await verify_supabase_jwt(token, HS256_SECRET)
