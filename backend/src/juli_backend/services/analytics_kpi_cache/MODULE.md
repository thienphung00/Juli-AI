# backend/src/juli_backend/services/analytics_kpi_cache

## Purpose

Required Redis read-through cache for Analytics KPI envelopes (ADR-038, P2.10-A5).
Postgres remains the system of record; Redis accelerates Demo reads and is refreshed
after successful precompute upserts.

## Public API

- ``envelope_cache_key(shop_id)`` → ``str`` — ``analytics:kpi_envelope:{shop_id}``
- ``get_analytics_kpi_envelope(session, shop_id, *, redis_client=None)``
  → ``AnalyticsKpiEnvelope | None`` — read Redis first; on miss or Redis error load
  Postgres and best-effort fill cache
- ``refresh_analytics_kpi_envelope_cache(shop_id, envelope, *, redis_client=None)``
  — overwrite cache with versioned envelope payload after Postgres upsert; fail-open
- ``create_redis_client(redis_url=None)`` → shared async Redis client or ``None``
  when ``REDIS_URL`` unset (compat alias for ``get_shared_redis_client``)
- ``get_shared_redis_client(redis_url=None)`` → per-event-loop shared client (#871: one per loop, so asyncio.run-per-task workers get a fresh client each run). Created with explicit ``socket_timeout``/``socket_connect_timeout`` (#927) so an unreachable Redis fails fast rather than blocking a caller for the OS TCP timeout — also relied on by ``services.action_cards.refresh_cooldown.bind_action_card_refresh_cooldown_gate()``, which reuses this same client instead of opening a second connection
- ``close_shared_redis_client()`` → awaitable shutdown close (API lifespan)

## Cache contract

- Key: ``analytics:kpi_envelope:{shop_id}``
- Value: JSON string of the envelope ``payload`` (includes ``envelope_version``)
- Redis errors (``RedisError``, including ``ConnectionError``) fall back to Postgres;
  never return empty when Postgres has rows

## Dependencies

- ``AnalyticsKpiEnvelopesRepo`` (#525) — Postgres SoT
- ``analytics_kpi_precompute`` — calls ``refresh_analytics_kpi_envelope_cache`` after upsert
- ``redis.asyncio`` — optional ``REDIS_URL`` client factory

## Must not

- Treat Redis as the only copy of truth
- Skip Postgres upsert on precompute
- Raise on Redis outage during reads (degraded path must still return Postgres rows)
