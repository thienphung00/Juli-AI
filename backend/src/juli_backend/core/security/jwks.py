"""Supabase JWKS fetch + cache for ES256 JWT verification (issue #1282).

## Why this module exists

The deployed Supabase project issues **ES256** (asymmetric) tokens. Verifying
them requires the project's public signing keys, published at
``{api_url}/auth/v1/.well-known/jwks.json`` and selected by the token's
``kid`` header -- there is no shared secret to verify against, unlike the
legacy HS256 flow ``core/security/jwt.py`` already implements.

## The `SUPABASE_URL` decision

`SUPABASE_URL` is documented (`infra/scripts/env/api.env.example:22`,
`docs/runbooks/app-review-runbook.md:347`) as *"Supabase project URL"* --
i.e. the API base URL, ``https://<project-ref>.supabase.co``. Nothing in
``backend/src`` read it before this module. On the deployed host it in fact
holds the **Postgres connection host**, ``db.<project-ref>.supabase.co``
(no scheme) -- the value `DATABASE_URL`'s own host uses, and the exact shape
`core/config/runtime.py::_is_direct_supabase_host` already recognises for a
*different* purpose (choosing an IPv4 hostaddr for the DB connection).

Rather than guess a transform from the wrong value (deriving `https://<ref>.
supabase.co` from `db.<ref>.supabase.co` would silently paper over a
misconfigured deployment and is fragile against self-hosted / custom-domain
Supabase projects), or invent a second, undocumented env var, this module
**requires `SUPABASE_URL` to already be a correct, corrected API URL** and
validates that deliberately in `supabase_jwks_url()`:

- missing scheme/host -> `JwksUnavailableError`, named
- shaped like the database host (`db.*`) -> `JwksUnavailableError`, named,
  explicitly telling the operator DATABASE_URL already owns that hostname

This is intentionally a **structural** check only -- it never makes a
network call. It cannot prove the URL is *reachable*, only that it is not
obviously the wrong value. See `assert_agent_runtime_config`'s check 5 for
where this is wired into boot, and its own docstring for what that proves
and does not.

## Caching and `kid` rotation

`JwksClient` caches the fetched key set for `ttl_seconds` (default 300s) so
the JWKS endpoint is not hit on every request in the auth path. An unknown
`kid` (freshly rotated key, or a forged one) triggers **at most one**
refetch per `min_refetch_interval_seconds` (default 10s) cooldown window,
enforced by an `asyncio.Lock` plus a timestamped cooldown gate -- not just
the lock alone:

- The lock alone stops a burst of *concurrent* callers from each firing
  their own fetch (they serialize on the lock, and every caller but the
  first finds the cache already warm when it is finally its turn).
- The lock alone does **not** stop a burst of *sequential* callers -- if
  the looked-up `kid` genuinely does not exist (a forged token, or an
  attacker probing with random `kid`s), each one still finds the cache
  fresh-but-missing-the-key and would refetch again, one at a time, on
  every single call. The cooldown timestamp closes that gap: once a
  refetch attempt has run (successfully or not), no further attempt is
  made until the cooldown elapses, regardless of how many more lookups
  arrive for that same missing `kid` in the meantime.

## Fail-closed

Any failure to fetch or parse the key set -- network error, non-2xx
response, invalid JSON, no signing keys in the response -- raises
`JwksUnavailableError` rather than returning something that could be
mistaken for "no matching key" and rather than silently falling back to a
previously-cached (and now possibly stale) key set on request paths that
never had one. `core/security/jwt.py` logs this under its own event name
(`jwt_jwks_unavailable`), distinct from `jwt_invalid` / `jwt_expired`, so an
outage is distinguishable from a bad token in the logs.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from urllib.parse import urlparse

import httpx
from jwt import PyJWK, PyJWKSet

from juli_backend.core.config.runtime import require_env

_JWKS_PATH = "/auth/v1/.well-known/jwks.json"
DEFAULT_JWKS_CACHE_TTL_SECONDS = 300.0
DEFAULT_MIN_REFETCH_INTERVAL_SECONDS = 10.0
_DEFAULT_FETCH_TIMEOUT_SECONDS = 5.0


class JwksUnavailableError(RuntimeError):
    """The JWKS key set could not be obtained or used.

    Raised for a structurally-unusable `SUPABASE_URL`, a network failure
    reaching the JWKS endpoint, a malformed response, or a `kid` absent
    after a refetch. Distinct from "the token is bad" (`Unauthorized`) --
    this means verification could not be *attempted*, not that it failed.
    Callers still fail closed (401) on it, but must log it under a name
    that lets an outage be told apart from an attack.
    """


def supabase_jwks_url(supabase_url: str | None = None) -> str:
    """Derive the JWKS endpoint from `SUPABASE_URL`, failing closed if unusable.

    Pure string validation -- makes no network call. See the module
    docstring's "The SUPABASE_URL decision" section for why this requires a
    corrected value rather than deriving one from the (wrong, on the
    deployed host) database hostname.
    """
    raw = (supabase_url if supabase_url is not None else require_env("SUPABASE_URL")).strip()
    # Parse hostname even when the scheme is missing (the deployed host's
    # actual defect: DATABASE_URL-style values carry no scheme at all) by
    # forcing a scheme-relative parse -- `urlparse` only populates `netloc`
    # /`hostname` from a leading `//`. This lets the more specific
    # database-host check below fire even on a schemeless value, instead of
    # being masked by the generic "missing scheme" branch.
    candidate = raw if "://" in raw else f"//{raw}"
    parsed = urlparse(candidate)
    hostname = parsed.hostname or ""
    if hostname.startswith("db."):
        raise JwksUnavailableError(
            f"SUPABASE_URL ({raw!r}) looks like the Postgres database host "
            "(db.<project-ref>.supabase.co), not the project API URL. DATABASE_URL "
            "already owns that hostname -- set SUPABASE_URL to "
            "https://<project-ref>.supabase.co instead."
        )
    if parsed.scheme not in ("http", "https") or not hostname:
        raise JwksUnavailableError(
            f"SUPABASE_URL is not a usable Supabase API URL ({raw!r}): expected an "
            "http(s) URL such as https://<project-ref>.supabase.co."
        )
    return raw.rstrip("/") + _JWKS_PATH


class JwksClient:
    """Fetches and caches one Supabase project's JWKS, single-flighted.

    `transport` mirrors the injectable-`httpx.AsyncBaseTransport` pattern
    `services/agent/llm/openai_adapter.py` already uses: production leaves
    it unset (real network); tests inject `httpx.MockTransport`. `clock`
    defaults to `time.monotonic` and is overridable so tests can exercise
    TTL expiry / cooldown elapsing without sleeping.
    """

    def __init__(
        self,
        jwks_url: str,
        *,
        ttl_seconds: float = DEFAULT_JWKS_CACHE_TTL_SECONDS,
        min_refetch_interval_seconds: float = DEFAULT_MIN_REFETCH_INTERVAL_SECONDS,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_seconds: float = _DEFAULT_FETCH_TIMEOUT_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._jwks_url = jwks_url
        self._ttl_seconds = ttl_seconds
        self._min_refetch_interval_seconds = min_refetch_interval_seconds
        self._transport = transport
        self._timeout_seconds = timeout_seconds
        self._clock = clock
        self._lock = asyncio.Lock()
        self._keys: dict[str, PyJWK] = {}
        self._fetched_at: float | None = None
        self._last_refetch_attempt: float | None = None

    def _cache_fresh(self) -> bool:
        return self._fetched_at is not None and (
            self._clock() - self._fetched_at < self._ttl_seconds
        )

    def _cooldown_elapsed(self) -> bool:
        if self._last_refetch_attempt is None:
            return True
        return (self._clock() - self._last_refetch_attempt) >= self._min_refetch_interval_seconds

    async def get_signing_key(self, kid: str) -> PyJWK:
        """Return the signing key for `kid`, refreshing at most once per
        cooldown window when it is missing from a fresh cache.

        Raises `JwksUnavailableError` when the key set cannot be fetched at
        all, or when `kid` is still absent after a refetch was attempted.
        """
        key = self._keys.get(kid) if self._cache_fresh() else None
        if key is not None:
            return key

        async with self._lock:
            # Re-check: a concurrent caller may have already refreshed
            # while this one waited for the lock (this is the single-flight
            # behaviour -- see the module docstring's caching section).
            key = self._keys.get(kid) if self._cache_fresh() else None
            if key is None and self._cooldown_elapsed():
                await self._refresh()
                key = self._keys.get(kid)

        if key is None:
            raise JwksUnavailableError(f"kid {kid!r} not present in JWKS ({self._jwks_url})")
        return key

    async def _refresh(self) -> None:
        # Recorded before the network call so a failed attempt also starts
        # the cooldown -- an unreachable JWKS endpoint must not be retried
        # on every single request either.
        self._last_refetch_attempt = self._clock()
        try:
            async with httpx.AsyncClient(
                transport=self._transport, timeout=self._timeout_seconds
            ) as client:
                response = await client.get(self._jwks_url)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            raise JwksUnavailableError(f"JWKS fetch failed ({self._jwks_url}): {exc}") from exc
        except ValueError as exc:
            raise JwksUnavailableError(
                f"JWKS response was not valid JSON ({self._jwks_url}): {exc}"
            ) from exc

        try:
            jwk_set = PyJWKSet.from_dict(data)
        except Exception as exc:
            raise JwksUnavailableError(
                f"JWKS response malformed ({self._jwks_url}): {exc}"
            ) from exc

        keys = {key.key_id: key for key in jwk_set.keys if key.key_id}
        if not keys:
            raise JwksUnavailableError(f"JWKS response had no usable keys ({self._jwks_url})")

        # Only replace the cache on a fully successful fetch + parse -- a
        # transient outage must not wipe previously-good keys and turn into
        # an outage for kids that were already cached and valid (mirrors
        # PyJWT's own PyJWKClient.fetch_data comment).
        self._keys = keys
        self._fetched_at = self._clock()
