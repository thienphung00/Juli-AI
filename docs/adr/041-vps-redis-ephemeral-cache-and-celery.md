# ADR-041: VPS Redis — ephemeral cache + Celery DB split

**Status:** Accepted  
**Date:** 2026-07-28  
**Deciders:** grill-with-docs (Architect) — Phase 2.10 A11 / #535

**Builds on:** [ADR-038](038-phase-2.10-dual-layer-pipeline.md), [ADR-020](020-vps-ssh-continuous-delivery-and-secrets-manager.md).  
**Does not change:** Postgres remains system of record; Redis never SoT (ADR-038).

## Context

Phase 2.10 requires Redis on the product VPS for Analytics envelope read-through,
TikTok rate-limit counters, material webhook coalesce, and (for workers) a shared
Celery broker. Operators installed Redis co-located on the Hetzner product host
with only `bind 127.0.0.1 -::1` uncommented (package defaults otherwise). Without
an explicit stance, Debian defaults enable RDB snapshots and unbounded memory —
misleading for a cache that must never be treated as durable product state.

## Decision

1. **Co-locate Redis on the product VPS**; keep loopback bind only. App URL:
   `REDIS_URL=redis://127.0.0.1:6379/0`. Do not expose `6379` publicly.
2. **No Redis persistence** for this instance: `save ""` and `appendonly no`.
   Restart may drop hot cache, rate-limit windows, coalesce gates, and in-flight
   Celery messages; product rows remain in Postgres; webhooks/reconciler re-drive work.
3. **Cap memory:** `maxmemory 256mb` and `maxmemory-policy allkeys-lru` so cache
   growth cannot OOM the host; Demo/API fall back to Postgres on eviction/miss.
4. **No `requirepass` for A11** while bind is loopback-only. Revisit if Redis is
   ever bound beyond localhost or the host gains untrusted local tenants.
5. **Celery shares the same Redis server** with separate logical DBs:
   broker `/1`, result backend `/2` — keep envelope/rate-limit keys on `/0`.
6. **API process uses one shared async Redis client** (create once, close on
   lifespan shutdown). `/health` must **not** require Redis (fail-open cache).

## Consequences

- Operators configure Redis via `redis.conf` + env (`REDIS_URL`, `CELERY_*`,
  `DEMO_REFERENCE_SHOP_ID`) rather than a managed Redis product for 2.10.
- Losing Redis is a performance/degradation event, not data loss.
- If Celery durability becomes required later, revisit persistence or a dedicated
  broker — do not silently enable RDB “just in case.”

## Options considered

| Option | Outcome |
|--------|---------|
| Keep package RDB defaults | Rejected — implies durability Redis does not provide for Juli |
| Managed Redis (Upstash/ElastiCache) | Deferred — co-located loopback is enough for single-VPS 2.10 |
| Password on localhost | Deferred for A11 operational simplicity |
| Single Redis DB for app + Celery | Rejected — key-space collision risk |
| Fail `/health` when Redis down | Rejected — contradicts ADR-038 fail-open reads |
