# ADR-002: Use Supabase as Backend-as-a-Service

**Status:** Accepted  
**Date:** 2026-05-26  
**Deciders:** Product owner

## Context

The product requires:

- PostgreSQL for multi-shop commerce and analytics data
- Phone-OTP authentication (Vietnamese sellers)
- Realtime updates for dashboard / cockpit UX
- File storage (product images, exports — as needed)
- Strong tenant isolation per shop

Building auth, realtime, and managed Postgres operations from scratch would add
roughly 6–10 weeks of infrastructure work before TikTok integration could ship.

## Decision

**Use Supabase as the managed backend-as-a-service layer** for Postgres, Auth,
Realtime, and Storage.

- **Database:** Supabase-hosted Postgres; application access via SQLAlchemy async
  + asyncpg in `src/shared/utils/data` (Alembic migrations).
- **Auth:** Supabase Auth for phone-OTP; `src/modules/identity/infrastructure/auth`
  verifies JWTs on every protected FastAPI request (`verify_supabase_jwt`, `get_current_user`).
- **TikTok OAuth:** Application-owned in `src/modules/identity/infrastructure/auth`
  (`TikTokOAuthService`) with tokens stored in `TikTokCredential` — not delegated to Supabase.
- **Redis (v2.0) is unchanged** — Supabase does not replace caching, rate
  limits, Celery, or the event bus.

## Rationale

| Factor | Supabase |
|--------|----------|
| Time to market | Auth + managed Postgres without custom infra sprint |
| Phone-OTP | Native flow — matches Vietnam mobile-first ICP |
| Portability | Standard Postgres; schemas owned by the app via Alembic |
| Realtime | Postgres Changes for live dashboard updates (reduces custom WebSocket code) |
| Multi-tenancy | RLS available; app also enforces `shop_id` scoping in repos |
| Cost | Predictable free/low tier for MVP |

## Architecture Integration

```
┌─────────────┐     ┌──────────────────┐     ┌──────────────────┐
│  iOS App    │     │  Next.js (web/)  │     │  Actions (v1.5)  │
│  (SwiftUI)  │     │  Matching UI     │     │  (Zalo/FCM)      │
└──────┬──────┘     └────────┬─────────┘     └──────┬───────────┘
       │    Supabase OTP      │    Supabase OTP       │
       │    + FastAPI JWT     │    + FastAPI JWT      │
       └─────────────────────┼───────────────────────┘
                             │
                    ┌────────▼─────────────┐
                    │  api_gateway/api     │
                    │  (FastAPI REST /v1)  │
                    └────────┬─────────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
     ┌────────▼──────┐ ┌────▼────┐ ┌───────▼───────┐
     │   Supabase    │ │ Redis   │ │  (v2.0 only)  │
     │ ┌───────────┐ │ │ cache,  │ │ event bus     │
     │ │ Postgres  │ │ │ Celery, │ │ (webhooks)    │
     │ │ Auth      │ │ │ rate    │ └───────────────┘
     │ │ Realtime  │ │ │ limits  │
     │ │ Storage   │ │ └─────────┘
     │ └───────────┘ │
     └───────────────┘
```

## Implementation (as built)

| Concern | Location | Notes |
|---------|----------|-------|
| Phone OTP | `src/modules/identity/infrastructure/auth` (`SupabaseAuth`) | Direct Supabase Auth REST via httpx |
| JWT validation | `src/modules/identity/infrastructure/auth` (`verify_supabase_jwt`, dependencies) | `pyjwt`; FastAPI `get_current_user` |
| TikTok tokens | `src/shared/utils/data` (`TikTokCredential`) | Encrypted per shop; refresh in `TikTokOAuthService` |
| Persistence | `src/shared/utils/data` | Models + `ShopScopedRepo`; see MODULE.md |
| Migrations | Alembic under `src/shared/utils/data` | App-owned schema evolution |

Clients (`web/`, `ios/`) may call Supabase Auth directly for OTP; business APIs
go through FastAPI with the issued JWT.

## Consequences

- FastAPI is the **authorization boundary** for shop-scoped commerce APIs.
- Realtime dashboard features should prefer Supabase Realtime where possible.
- Redis remains for TikTok rate limiting, Celery broker, and hot caches.
- Ingest uses in-process handoff to `src/modules/ordering/use_cases/etl` (see ADR-004 and [`EXECUTION.md`](../../EXECUTION.md)).
- [`docs/architecture/data-sources.md`](../architecture/data-sources.md) row #2
  marks Supabase Postgres as the sole MVP OLTP store.

## Alternatives Considered

| Alternative | Why rejected |
|-------------|--------------|
| Self-managed Postgres only | Still requires building OTP auth, realtime, and ops |
| Firebase | Not Postgres-first; weaker fit for analytics SQL |
| AWS Cognito + RDS | Higher setup and ops burden at MVP stage |

## References

- [`src/modules/identity/infrastructure/auth/MODULE.md`](../../src/modules/identity/infrastructure/auth/MODULE.md)
- [`src/shared/utils/data/MODULE.md`](../../src/shared/utils/data/MODULE.md)
- [`docs/architecture/map.md`](../architecture/map.md)
- [`EXECUTION.md`](../../EXECUTION.md) — phased execution plan (single source of truth)
