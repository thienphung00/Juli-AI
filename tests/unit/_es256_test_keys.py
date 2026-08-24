"""Shared ES256 keypair + JWKS fixture helpers (issue #1282, AGT-W5B).

Generates a real EC P-256 keypair per call, exports the public half as a
JWK, and signs tokens with the private half via PyJWT -- the "real-shaped
ES256 token" the issue requires at least one test to exercise, as opposed
to a self-minted HS256 token with a test secret.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt as pyjwt
from cryptography.hazmat.primitives.asymmetric import ec
from jwt.algorithms import ECAlgorithm


def generate_es256_keypair(kid: str | None = None) -> tuple[ec.EllipticCurvePrivateKey, str, dict]:
    """Return `(private_key, kid, jwk_dict)` for a fresh EC P-256 keypair.

    `jwk_dict` is the public half, shaped exactly as Supabase's JWKS
    endpoint would publish it (kty=EC, crv=P-256, x, y, kid, alg, use).
    """
    resolved_kid = kid or str(uuid.uuid4())
    private_key = ec.generate_private_key(ec.SECP256R1())
    algorithm = ECAlgorithm(ECAlgorithm.SHA256)
    jwk_dict = algorithm.to_jwk(private_key.public_key(), as_dict=True)
    jwk_dict["kid"] = resolved_kid
    jwk_dict["use"] = "sig"
    jwk_dict["alg"] = "ES256"
    return private_key, resolved_kid, jwk_dict


def jwks_document(*jwk_dicts: dict) -> dict:
    return {"keys": list(jwk_dicts)}


def sign_es256_token(
    private_key: ec.EllipticCurvePrivateKey,
    kid: str,
    *,
    sub: str | None = None,
    aud: str = "authenticated",
    expired: bool = False,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """Sign a Supabase-shaped ES256 token with a real EC private key."""
    now = datetime.now(UTC)
    exp = now - timedelta(hours=1) if expired else now + timedelta(hours=1)
    claims: dict[str, Any] = {
        "sub": sub or str(uuid.uuid4()),
        "aud": aud,
        "role": "authenticated",
        "exp": exp,
    }
    if extra_claims:
        claims.update(extra_claims)
    return pyjwt.encode(
        claims,
        private_key,
        algorithm="ES256",
        headers={"kid": kid},
    )
