"""JWKS fetch/cache/single-flight behaviour (issue #1282, AGT-W5B).

`JwksClient` is the piece that makes ES256 verification viable in the auth
path: fetching JWKS per request would put a network call on every
authenticated request, so this covers caching, kid-rotation-without-
redeploy, and fail-closed behaviour on an unreachable endpoint -- including
that an unknown `kid` triggers at most one refetch, not a stampede.

`supabase_jwks_url` covers the SUPABASE_URL decision: the deployed host's
actual defect (SUPABASE_URL holding the Postgres db.*.supabase.co host, not
the project API URL) must fail closed with a named error rather than
silently building a URL that 404s.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from juli_backend.core.security.jwks import (
    JwksClient,
    JwksUnavailableError,
    supabase_jwks_url,
)
from tests.unit._es256_test_keys import generate_es256_keypair, jwks_document

# `asyncio_mode = auto` (pytest.ini) runs async defs directly -- no
# `pytestmark`/`@pytest.mark.asyncio` needed, and applying one at module
# scope would wrongly tag the synchronous `TestSupabaseJwksUrl` tests below.


# ---------------------------------------------------------------------------
# supabase_jwks_url -- structural validation, no network.
# ---------------------------------------------------------------------------


class TestSupabaseJwksUrl:
    def test_derives_jwks_endpoint_from_valid_api_url(self):
        assert (
            supabase_jwks_url("https://abcdefgh.supabase.co")
            == "https://abcdefgh.supabase.co/auth/v1/.well-known/jwks.json"
        )

    def test_strips_trailing_slash(self):
        assert supabase_jwks_url("https://abcdefgh.supabase.co/") == (
            "https://abcdefgh.supabase.co/auth/v1/.well-known/jwks.json"
        )

    def test_rejects_missing_scheme(self):
        with pytest.raises(JwksUnavailableError, match="SUPABASE_URL"):
            supabase_jwks_url("abcdefgh.supabase.co")

    def test_rejects_database_host_shape(self):
        """The exact defect on the deployed host: SUPABASE_URL held the
        Postgres connection host, not the project API URL."""
        with pytest.raises(JwksUnavailableError, match="database host"):
            supabase_jwks_url("db.abcdefgh.supabase.co")

    def test_rejects_empty_string(self):
        with pytest.raises(JwksUnavailableError):
            supabase_jwks_url("")

    def test_reads_env_var_when_no_argument_given(self, monkeypatch):
        monkeypatch.setenv("SUPABASE_URL", "https://envvar-project.supabase.co")
        assert supabase_jwks_url() == (
            "https://envvar-project.supabase.co/auth/v1/.well-known/jwks.json"
        )

    def test_raises_named_error_when_env_var_absent(self, monkeypatch):
        monkeypatch.delenv("SUPABASE_URL", raising=False)
        with pytest.raises(RuntimeError, match="SUPABASE_URL"):
            supabase_jwks_url()


# ---------------------------------------------------------------------------
# JwksClient -- fetch, cache, kid selection.
# ---------------------------------------------------------------------------


def _counting_transport(jwks_by_call: list[dict]) -> tuple[httpx.MockTransport, list[int]]:
    """A MockTransport that serves `jwks_by_call[call_count]` on each call
    (clamped to the last entry once exhausted) and records call count."""
    calls = {"count": 0}

    def _handle(request: httpx.Request) -> httpx.Response:
        idx = min(calls["count"], len(jwks_by_call) - 1)
        calls["count"] += 1
        return httpx.Response(200, json=jwks_by_call[idx])

    return httpx.MockTransport(_handle), calls


class TestJwksClientFetchAndCache:
    async def test_returns_signing_key_for_known_kid(self):
        _, kid, jwk = generate_es256_keypair()
        transport, calls = _counting_transport([jwks_document(jwk)])
        client = JwksClient(
            "https://x.supabase.co/auth/v1/.well-known/jwks.json", transport=transport
        )

        key = await client.get_signing_key(kid)

        assert key.key_id == kid
        assert calls["count"] == 1

    async def test_second_lookup_within_ttl_does_not_refetch(self):
        _, kid, jwk = generate_es256_keypair()
        transport, calls = _counting_transport([jwks_document(jwk)])
        client = JwksClient(
            "https://x.supabase.co/auth/v1/.well-known/jwks.json", transport=transport
        )

        await client.get_signing_key(kid)
        await client.get_signing_key(kid)

        assert calls["count"] == 1

    async def test_cache_expiry_after_ttl_triggers_refetch(self):
        _, kid, jwk = generate_es256_keypair()
        transport, calls = _counting_transport([jwks_document(jwk), jwks_document(jwk)])
        fake_time = {"t": 0.0}
        client = JwksClient(
            "https://x.supabase.co/auth/v1/.well-known/jwks.json",
            transport=transport,
            ttl_seconds=10.0,
            min_refetch_interval_seconds=0.0,
            clock=lambda: fake_time["t"],
        )

        await client.get_signing_key(kid)
        fake_time["t"] = 20.0  # past the 10s TTL
        await client.get_signing_key(kid)

        assert calls["count"] == 2

    async def test_unknown_kid_raises_jwks_unavailable_error(self):
        _, _kid, jwk = generate_es256_keypair()
        transport, _ = _counting_transport([jwks_document(jwk)])
        client = JwksClient(
            "https://x.supabase.co/auth/v1/.well-known/jwks.json", transport=transport
        )

        with pytest.raises(JwksUnavailableError, match="not present"):
            await client.get_signing_key("some-other-kid")


class TestJwksClientKidRotation:
    async def test_rotated_kid_is_picked_up_without_redeploy(self):
        """Simulates a real rotation: the server starts serving a JWKS with
        a NEW kid the client has never cached. No process restart -- just
        the client's own refetch-on-miss behaviour."""
        _, kid_a, jwk_a = generate_es256_keypair()
        _, kid_b, jwk_b = generate_es256_keypair()
        transport, calls = _counting_transport([jwks_document(jwk_a), jwks_document(jwk_b)])
        fake_time = {"t": 0.0}
        client = JwksClient(
            "https://x.supabase.co/auth/v1/.well-known/jwks.json",
            transport=transport,
            ttl_seconds=300.0,
            min_refetch_interval_seconds=0.0,
            clock=lambda: fake_time["t"],
        )

        key_a = await client.get_signing_key(kid_a)
        assert key_a.key_id == kid_a
        assert calls["count"] == 1

        # Advance the clock past the cooldown (set to 0 above, so any tick
        # suffices) and look up the freshly-rotated kid.
        fake_time["t"] = 1.0
        key_b = await client.get_signing_key(kid_b)
        assert key_b.key_id == kid_b
        assert calls["count"] == 2


class TestJwksClientStampedePrevention:
    async def test_concurrent_lookups_of_same_unknown_kid_fetch_once(self):
        """AC: an unknown kid does not cause a fetch stampede. 25 concurrent
        callers ask for a kid that is genuinely absent from the JWKS; only
        one network fetch must happen, and every caller must still see the
        same failure."""
        _, _present_kid, jwk = generate_es256_keypair()
        transport, calls = _counting_transport([jwks_document(jwk)])
        client = JwksClient(
            "https://x.supabase.co/auth/v1/.well-known/jwks.json",
            transport=transport,
            min_refetch_interval_seconds=60.0,
        )

        results = await asyncio.gather(
            *(client.get_signing_key("kid-that-does-not-exist") for _ in range(25)),
            return_exceptions=True,
        )

        assert calls["count"] == 1
        assert all(isinstance(r, JwksUnavailableError) for r in results)

    async def test_concurrent_lookups_of_same_known_kid_fetch_once(self):
        _, kid, jwk = generate_es256_keypair()
        transport, calls = _counting_transport([jwks_document(jwk)])
        client = JwksClient(
            "https://x.supabase.co/auth/v1/.well-known/jwks.json", transport=transport
        )

        results = await asyncio.gather(*(client.get_signing_key(kid) for _ in range(25)))

        assert calls["count"] == 1
        assert all(key.key_id == kid for key in results)


class TestJwksClientFailClosed:
    async def test_network_error_raises_jwks_unavailable_error(self):
        def _raise(_: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused")

        client = JwksClient(
            "https://x.supabase.co/auth/v1/.well-known/jwks.json",
            transport=httpx.MockTransport(_raise),
        )

        with pytest.raises(JwksUnavailableError, match="JWKS fetch failed"):
            await client.get_signing_key("any-kid")

    async def test_non_2xx_response_raises_jwks_unavailable_error(self):
        def _handle(_: httpx.Request) -> httpx.Response:
            return httpx.Response(503, text="service unavailable")

        client = JwksClient(
            "https://x.supabase.co/auth/v1/.well-known/jwks.json",
            transport=httpx.MockTransport(_handle),
        )

        with pytest.raises(JwksUnavailableError, match="JWKS fetch failed"):
            await client.get_signing_key("any-kid")

    async def test_malformed_json_raises_jwks_unavailable_error(self):
        def _handle(_: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="not json")

        client = JwksClient(
            "https://x.supabase.co/auth/v1/.well-known/jwks.json",
            transport=httpx.MockTransport(_handle),
        )

        with pytest.raises(JwksUnavailableError, match="not valid JSON"):
            await client.get_signing_key("any-kid")

    async def test_empty_key_set_raises_jwks_unavailable_error(self):
        def _handle(_: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"keys": []})

        client = JwksClient(
            "https://x.supabase.co/auth/v1/.well-known/jwks.json",
            transport=httpx.MockTransport(_handle),
        )

        # PyJWKSet.from_dict itself rejects an empty key list before this
        # module's own `if not keys` check (reserved for the narrower case
        # of a non-empty response where every entry lacks a `kid`) ever
        # runs -- both are folded into the same fail-closed outcome.
        with pytest.raises(JwksUnavailableError, match="malformed"):
            await client.get_signing_key("any-kid")

    async def test_outage_does_not_wipe_previously_cached_keys(self):
        """A transient JWKS outage must not turn into an outage for a kid
        that was already cached and valid before the network broke."""
        _, kid, jwk = generate_es256_keypair()
        state = {"broken": False}

        def _handle(request: httpx.Request) -> httpx.Response:
            if state["broken"]:
                return httpx.Response(503, text="service unavailable")
            return httpx.Response(200, json=jwks_document(jwk))

        client = JwksClient(
            "https://x.supabase.co/auth/v1/.well-known/jwks.json",
            transport=httpx.MockTransport(_handle),
            ttl_seconds=300.0,
            min_refetch_interval_seconds=0.0,
        )

        key = await client.get_signing_key(kid)
        assert key.key_id == kid

        # Break the network and look up a *different*, unknown kid -- this
        # is within the still-fresh TTL, so the only reason it refetches at
        # all is the cache miss for that kid. The refetch fails.
        state["broken"] = True
        with pytest.raises(JwksUnavailableError, match="JWKS fetch failed"):
            await client.get_signing_key("some-unknown-kid")

        # The original kid's cache entry (from the successful fetch) must
        # be untouched by that failed refresh -- still fresh, still served
        # with zero network I/O.
        key_again = await client.get_signing_key(kid)
        assert key_again.key_id == kid
