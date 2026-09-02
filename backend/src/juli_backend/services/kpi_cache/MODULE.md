# backend/src/juli_backend/services/kpi_cache

## Purpose

The single copy of the Redis machinery both KPI envelope caches use
(`gold_kpi_cache`, `analytics_kpi_cache`). Before this package each cache
carried its own client lifecycle and read-through loop, and the copies drifted:
gold had the per-loop client (#871) but no socket timeouts, analytics had the
timeouts (#927) but a per-process client. Both fixes now live here, once.

## Public API

- `get_shared_redis_client(redis_url=None)` → `Redis | None` — one client per
  `(url, running event loop)`; `None` when `REDIS_URL` is unset. Created with
  explicit `socket_timeout` / `socket_connect_timeout` (2s).
- `close_shared_redis_client()` — awaitable, best-effort; API lifespan shutdown.
- `reset_shared_redis_client_for_tests()` — forget without closing; tests only.
- `resolve_redis_url(redis_url=None)` → `str` — explicit URL, else `REDIS_URL`, stripped.
- `EnvelopeCodec(key_prefix, payload_of, from_payload)` — how one envelope type
  crosses the Redis boundary.
- `EnvelopeCache(name, codec, load)` — fail-open read-through:
  `get(session, shop_id, redis_client=)`, `refresh(shop_id, envelope, redis_client=)`,
  `read_payload(shop_id, redis_client)`, `key(shop_id)`.

## Adding a cache

Name the key prefix, the repository read and the envelope constructor, build one
module-level `EnvelopeCache`, and export thin functions that call it. See
`analytics_kpi_cache/cache.py` for the minimal shape and `gold_kpi_cache/cache.py`
for one that adds behaviour (last-good fallback) on top.

## Must not

- Treat Redis as a source of truth — `load` is always Postgres.
- Raise on a Redis outage — every Redis call is caught and logged.
- Cache the client per process — worker tasks enter through `asyncio.run()`
  and a cross-loop client fails every call after the first run (#871).
