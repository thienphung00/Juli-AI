"""P16 Cloudflare Access JWT verification — fail closed (D25.1)."""

from __future__ import annotations

import json
import time

import httpx
import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from juli_backend.core.security import cf_access
from juli_backend.core.security.exceptions import Unauthorized
from juli_backend.core.security.jwks import JwksClient

TEAM = "https://juliteam.cloudflareaccess.com"
AUD = "aud-tag-123"


@pytest.fixture
def key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(autouse=True)
def access_env(monkeypatch, key):
    monkeypatch.delenv("OPS_CF_ACCESS_BYPASS", raising=False)
    monkeypatch.setenv("CF_ACCESS_TEAM_DOMAIN", "juliteam")
    monkeypatch.setenv("CF_ACCESS_AUD", AUD)
    jwk = json.loads(RSAAlgorithm.to_jwk(key.public_key()))
    jwk.update({"kid": "k1", "alg": "RS256", "use": "sig"})

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == TEAM + "/cdn-cgi/access/certs"
        return httpx.Response(200, json={"keys": [jwk]})

    cf_access._clients.clear()
    cf_access._clients[TEAM] = JwksClient(
        TEAM + "/cdn-cgi/access/certs", transport=httpx.MockTransport(handler)
    )
    yield
    cf_access._clients.clear()


def _token(key, **claims):
    now = int(time.time())
    body = {"aud": [AUD], "iss": TEAM, "iat": now, "exp": now + 600, "email": "an@app-juli.com"}
    body.update(claims)
    return pyjwt.encode(body, key, algorithm="RS256", headers={"kid": "k1"})


async def test_valid_token_returns_email(key):
    identity = await cf_access.verify_access_jwt(_token(key, email="An@App-Juli.com"))
    assert identity.email == "an@app-juli.com"
    assert identity.bypassed is False


@pytest.mark.parametrize(
    "claims",
    [
        {"aud": ["other"]},
        {"iss": "https://evil.cloudflareaccess.com"},
        {"exp": int(time.time()) - 10},
        {"email": "someone@gmail.com"},
        {"email": None},
    ],
)
async def test_bad_claims_are_refused(key, claims):
    with pytest.raises(Unauthorized):
        await cf_access.verify_access_jwt(_token(key, **claims))


async def test_missing_header_is_refused():
    with pytest.raises(Unauthorized):
        await cf_access.verify_access_jwt(None)


async def test_wrong_key_is_refused():
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(Unauthorized):
        await cf_access.verify_access_jwt(_token(other))


async def test_hs256_token_is_refused():
    token = pyjwt.encode({"aud": AUD}, "secret", algorithm="HS256", headers={"kid": "k1"})
    with pytest.raises(Unauthorized):
        await cf_access.verify_access_jwt(token)


async def test_unconfigured_fails_closed(monkeypatch, key):
    monkeypatch.delenv("CF_ACCESS_AUD")
    with pytest.raises(Unauthorized):
        await cf_access.verify_access_jwt(_token(key))


async def test_certs_unreachable_fails_closed(key):
    def boom(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    cf_access._clients[TEAM] = JwksClient(
        TEAM + "/cdn-cgi/access/certs", transport=httpx.MockTransport(boom)
    )
    with pytest.raises(Unauthorized):
        await cf_access.verify_access_jwt(_token(key))


async def test_bypass_only_outside_production(monkeypatch):
    monkeypatch.setenv("OPS_CF_ACCESS_BYPASS", "1")
    monkeypatch.setenv("ENVIRONMENT", "development")
    assert (await cf_access.verify_access_jwt(None)).bypassed is True
    monkeypatch.setenv("ENVIRONMENT", "production")
    with pytest.raises(Unauthorized):
        await cf_access.verify_access_jwt(None)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("juliteam", TEAM),
        ("juliteam.cloudflareaccess.com", TEAM),
        (TEAM + "/", TEAM),
    ],
)
def test_team_url(raw, expected):
    assert cf_access.team_url(raw) == expected


def test_team_url_rejects_paths():
    with pytest.raises(Unauthorized):
        cf_access.team_url("https://x.cloudflareaccess.com/cdn-cgi")
