# backend/src/juli_backend/services/gold_kpi_cache

## Purpose

Required Redis read-through cache for Gold KPI envelopes (ADR-038, A1-#631).
Postgres remains the system of record; Redis accelerates Demo reads and is refreshed
after successful Demo KPI envelope upserts. On compute failure, Demo falls back to
last-good cached envelope (degraded path, never fabricates stale values).

## Public API

- ``envelope_cache_key(shop_id)`` → ``str`` — ``gold:kpi_envelope:{shop_id}``
- ``get_gold_kpi_envelope(session, shop_id, *, redis_client=None)``
  → ``GoldKpiEnvelope | None`` — read Redis first; on miss or Redis error load
  Postgres and best-effort fill cache
- ``get_gold_kpi_envelope_with_last_good_fallback(session, shop_id, *, redis_client=None)``
  → ``GoldKpiEnvelope | None`` — read-through with last-good fallback on compute failure;
  never overwrites Postgres SoT with fabricated values
- ``refresh_gold_kpi_envelope_cache(shop_id, envelope, *, redis_client=None)``
  — overwrite cache with versioned envelope payload after Postgres upsert; fail-open
- ``create_redis_client(redis_url=None)`` → shared async Redis client or ``None``
  when ``REDIS_URL`` unset (compat alias for ``get_shared_redis_client``)
- ``get_shared_redis_client(redis_url=None)`` → per-event-loop shared client (#871: one per loop, so asyncio.run-per-task workers get a fresh client each run)
- ``close_shared_redis_client()`` → awaitable shutdown close (API lifespan)

## Cache contract

- Key: ``gold:kpi_envelope:{shop_id}``
- Value: JSON string of the envelope ``payload`` (includes ``envelope_version``)
- Redis errors (``RedisError``, including ``ConnectionError``) fall back to Postgres;
  never return empty when Postgres has rows
- Last-good cache (in-memory): stores envelope payloads on successful write; used only
  when compute/read fails and Postgres is unavailable (graceful degradation)

## Dependencies

- ``GoldKpiEnvelopesRepo`` (#606) — Postgres SoT (gold.kpi_envelopes table)
- ``write_demo_main_kpis_envelope`` — calls ``refresh_gold_kpi_envelope_cache`` after upsert
- ``redis.asyncio`` — optional ``REDIS_URL`` client factory

## Must not

- Treat Redis as the only copy of truth — Postgres always SoT
- Skip Postgres upsert on Demo precompute
- Raise on Redis outage during reads (degraded path must still return Postgres rows)
- Overwrite Postgres with stale/fabricated values on compute failure
  (last-good fallback is read-only, never writes to DB)
