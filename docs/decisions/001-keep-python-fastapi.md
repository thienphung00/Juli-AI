# ADR-001: Keep Python / FastAPI as Backend Runtime

**Status:** Accepted  
**Date:** 2026-05-26  
**Deciders:** Product owner

## Context

Early TikTok integration planning listed Node.js / NestJS and BullMQ as options
(see `docs/tiktok_api/tech-stack.md`). By the time the MVP was scoped, the
repository already shipped a working Python backend:

| Module (current path) | Role |
|--------|------|
| `src/modules/catalog/domain/integrations/tiktok` | TikTok Partner API client — OAuth, HMAC signing, rate limiting, resources |
| `src/apps/api_gateway/services/webhook` | FastAPI webhook receiver → ETL handoff |
| `src/apps/cron_jobs/services/polling` | Background sync (`sync_creators`, `sync_products`, `sync_livestreams`, …) |
| `src/shared/utils/data` | SQLAlchemy async models, shop-scoped repos, Alembic migrations |
| `src/modules/identity/infrastructure/auth` | JWT verification, TikTok OAuth lifecycle |
| `src/apps/api_gateway/api` | Versioned FastAPI REST API, shop-scoped routes |
| `src/modules/catalog/domain/intelligence/scoring` | Post-stream scoring, Vietnamese sentiment (legacy signal; superseded creator-matching scope) |

Rewriting to NestJS would discard tested integration code and delay the
execution plan ([`EXECUTION.md`](../../EXECUTION.md)).

## Decision

**Keep Python / FastAPI.** Extend the modular monolith under `src/` (apps,
modules, shared). Do not introduce a parallel Node.js backend for MVP.

## Rationale

| Factor | Python / FastAPI |
|--------|------------------|
| Delivery | No rewrite — build on modules already in production paths |
| AI / analytics | Planned forecasting and recommendations fit the Python ML stack |
| Consistency | One backend language for API, workers, webhooks, and intelligence |
| Interfaces | `web/` (Next.js) and `ios/` (SwiftUI) both call FastAPI REST — no BFF split required at MVP |

## Consequences

- **API & services:** FastAPI for `src/apps/api_gateway/api`, `src/apps/api_gateway/services/webhook`, and future workers.
- **Task queue:** Celery + Redis — not BullMQ.
- **HTTP client:** httpx for TikTok and Supabase Auth API calls — not axios.
- **ORM:** SQLAlchemy async + asyncpg — not Prisma/TypeORM.
- **Frontends:** Next.js (`web/`) and SwiftUI (`ios/`) are thin clients; business logic stays in Python services.
- **Docs:** `docs/tiktok_api/tech-stack.md` “or Node.js” options are **historical**; new work follows this ADR and [`docs/architecture/map.md`](../architecture/map.md). The original 45-day execution plan has been superseded by [`EXECUTION.md`](../../EXECUTION.md) (seller-money rescope).

## Alternatives Considered

| Alternative | Why rejected |
|-------------|--------------|
| Node.js / NestJS | Discards working TikTok client and sync pipeline; no MVP time budget |
| Hybrid (Python workers + Node API) | Two runtimes to deploy and debug without MVP-scale benefit |
| Next.js API Routes as primary backend | Splits auth/data logic away from integrations; duplicates TikTok signing in TypeScript |

## References

- [`docs/architecture/map.md`](../architecture/map.md) — module list and dependency graph
- [`EXECUTION.md`](../../EXECUTION.md) — phased execution plan (single source of truth)
- [`src/modules/catalog/domain/integrations/tiktok/MODULE.md`](../../src/modules/catalog/domain/integrations/tiktok/MODULE.md)
