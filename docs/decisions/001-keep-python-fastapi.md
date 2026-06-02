# ADR-001: Keep Python / FastAPI as Backend Runtime

**Status:** Accepted  
**Date:** 2026-05-26  
**Deciders:** Product owner

## Context

Early TikTok integration planning listed Node.js / NestJS and BullMQ as options
(see `docs/tiktok_api/tech-stack.md`). By the time the MVP was scoped, the
repository already shipped a working Python backend:

| Module | Role |
|--------|------|
| `src/integrations/tiktok` | TikTok Partner API client — OAuth, HMAC signing, rate limiting, resources |
| `src/services/webhook` | FastAPI webhook receiver → ETL handoff |
| `src/services/polling` | Background sync (`sync_orders`, `sync_products`, `sync_inventory`) |
| `src/data` | SQLAlchemy async models, shop-scoped repos, Alembic migrations |
| `src/auth` | Supabase phone-OTP, JWT verification, TikTok OAuth lifecycle |
| `src/api` | Versioned FastAPI REST API, shop-scoped routes |
| `src/intelligence/scoring` | Post-stream scoring, anomalies, Vietnamese sentiment |

Rewriting to NestJS would discard tested integration code and delay the 45-day
execution plan ([`docs/tiktok-shop-execution-plan.md`](../tiktok-shop-execution-plan.md)).

## Decision

**Keep Python / FastAPI.** Extend `src/integrations/`, `src/services/`,
`src/data`, `src/auth`, `src/api`, and `src/intelligence/`. Do not introduce a
parallel Node.js backend for MVP.

## Rationale

| Factor | Python / FastAPI |
|--------|------------------|
| Delivery | No rewrite — build on modules already in production paths |
| AI / analytics | Planned forecasting and recommendations fit the Python ML stack |
| Consistency | One backend language for API, workers, webhooks, and intelligence |
| Interfaces | `web/` (Next.js) and `ios/` (SwiftUI) both call FastAPI REST — no BFF split required at MVP |

## Consequences

- **API & services:** FastAPI for `src/api`, `src/services/webhook`, and future workers.
- **Task queue:** Celery + Redis — not BullMQ.
- **HTTP client:** httpx for TikTok and Supabase Auth API calls — not axios.
- **ORM:** SQLAlchemy async + asyncpg — not Prisma/TypeORM.
- **Frontends:** Next.js (`web/`) and SwiftUI (`ios/`) are thin clients; business logic stays in Python services.
- **Docs:** `docs/tiktok_api/tech-stack.md` “or Node.js” options are **historical**; new work follows this ADR and [`docs/architecture/map.md`](../architecture/map.md).

## Alternatives Considered

| Alternative | Why rejected |
|-------------|--------------|
| Node.js / NestJS | Discards working TikTok client and sync pipeline; no MVP time budget |
| Hybrid (Python workers + Node API) | Two runtimes to deploy and debug without MVP-scale benefit |
| Next.js API Routes as primary backend | Splits auth/data logic away from integrations; duplicates TikTok signing in TypeScript |

## References

- [`docs/architecture/map.md`](../architecture/map.md) — module list and dependency graph
- [`docs/tiktok-shop-execution-plan.md`](../tiktok-shop-execution-plan.md) — finalized stack table
- [`src/integrations/tiktok/MODULE.md`](../../src/integrations/tiktok/MODULE.md)
