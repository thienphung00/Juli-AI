# Repository Migration Plan

> **Tier 1 — path mapping & migration sequence.** Read [`EXECUTION.md`](../../EXECUTION.md) first.  
> **Owns:** current → target path mapping, migration PR sequence, naming collision notes.  
> **Does not own:** as-built module registry (`map.md`), deploy domain details (`phase-2.5-deployment.md`).

**Status:** Phase 2.5 complete (App Review sign-off 2026-07-03). Runtime code lives under
`backend/`; deploy entrypoint is `backend.api.api.main:app`. `web/` has already been
renamed to `apps/dashboard/` (see `apps/README.md`) and serves the legacy App Review
placeholder at `app-juli.com` until Phase 3 repoints that domain to `apps/landing`.
`ios/` remains legacy until its Phase 4+ `apps/mobile` migration.

---

## Current vs target layout

### Current (as-built)

```text
juli-ai-v2/
├── backend/              # Python backend modular monolith (runtime)
│   ├── api/              # FastAPI REST + app factory
│   ├── workers/          # Polling / scheduled jobs
│   ├── integrations/     # Domain modules
│   ├── ai/               # ML trainers, features, artifacts
│   └── database/         # SQLAlchemy, repos, Alembic migrations
├── ios/                  # SwiftUI mobile app (legacy)
├── apps/
│   └── dashboard/        # Next.js seller dashboard (legacy ADR-014 IA; live at app-juli.com for App Review)
├── packages/             # Shared libraries (scaffold — Phase 2.5-b)
├── infra/                # CI/CD + deploy config (live App Review runbooks)
├── docs/
├── scripts/
├── tests/
└── requirements.txt
```

### Target (product-oriented monorepo)

```text
juli-ai-v2/
├── apps/
│   ├── landing/
│   ├── demo/
│   ├── dashboard/
│   └── mobile/
├── packages/
│   ├── ui/
│   ├── theme/
│   ├── icons/
│   ├── illustrations/
│   ├── api-client/
│   ├── types/
│   └── utils/
├── backend/
│   ├── api/
│   ├── workers/
│   ├── ai/
│   ├── integrations/
│   └── database/
├── docs/
└── infra/
```

---

## Path mapping

| Current | Target | Notes |
|---------|--------|-------|
| `src/apps/api_gateway/` | `backend/api/` | FastAPI REST + app factory |
| `src/apps/api_gateway/services/webhook/` | `backend/api/` or `backend/workers/` | Webhook receiver |
| `src/apps/cron_jobs/` | `backend/workers/` | Polling / scheduled jobs |
| `src/modules/` | `backend/integrations/`, `backend/ai/` | Domain modules split by concern |
| `src/shared/utils/data/` | `backend/database/` | SQLAlchemy, repos, Alembic |
| `alembic/` | `backend/database/migrations/` | DB migrations |
| `requirements.txt` | `backend/requirements.txt` or `pyproject.toml` | Python deps |
| `tests/` | `backend/tests/` | Python unit/integration tests |
| `web/` (renamed) | `apps/dashboard/` (done; ADR-023 IA rebuild is Phase 3.5) | Legacy seller dashboard, App Review placeholder |
| — | `apps/demo/` (Phase 2.6) | New ADR-023 IA demo app, mock data |
| — | `apps/landing/` (Phase 2.7) | New marketing site |
| `ios/` | `apps/mobile/` | Mobile app |
| `web/src/components/` | `packages/ui/` | Shared components (incremental) |
| `web/src/lib/` types | `packages/types/` | Shared TS types |
| `.github/workflows/` | `infra/ci/` | CI pipeline config |
| deploy configs (future) | `infra/deploy/` | Per-product deploy manifests |

---

## Naming collision: `backend/api` vs top-level `apps/`

| Path | Meaning |
|------|---------|
| **`backend/api/`**, **`backend/workers/`** | Backend composition layer — FastAPI entrypoints, cron workers. Python import path. |
| **`apps/`** (top-level) | Product deployables — landing, demo, dashboard, mobile. Frontend/mobile apps. |

Do **not** import from top-level `apps/` in Python backend code. Do **not** confuse
`backend.api` with `apps/demo`.

---

## Migration PR sequence (planned)

Each PR must pass the full test suite before and after. No opportunistic refactors.

| PR | Scope | Gate |
|----|-------|------|
| **2.5-a** | Docs + scaffold READMEs | No runtime changes |
| **2.5-b** | Introduce `pnpm` workspace + Turborepo skeleton | `web/` still builds; `pnpm run workspace:baseline` |
| **2.5-review** | VPS/Nginx/HTTPS deploy of legacy frontend/API for TikTok App Review | **Complete** — sign-off 2026-07-03 |
| **2.5-c** | Move `src/` → `backend/` with import rewrites | `pytest` green |
| **2.5-d** | Split deploy config into `infra/` | CI green; review runbook retained |
| **2.6** | Scaffold `apps/demo` (ADR-023 IA, mock data); extract `packages/ui`, `packages/theme` | `apps/demo` builds independently on mock data |
| **2.7** | Scaffold `apps/landing` (mock/static content); consumes `packages/ui`/`packages/theme` | `apps/landing` builds independently on mock data |
| **3** | Wire `apps/demo` + `apps/landing` to real backend; enable Demo Sign-in mode; deploy both | Both apps deployed on real data end-to-end |
| **3.5** | Rebuild `apps/dashboard` to the ADR-023 IA with multi-tenant auth | Dashboard deploys to `dashboard.app-juli.com` |

> **Superseded (2026-07-15, [ADR-024](../adr/024-phase-2.6-2.7-frontend-resequencing.md)):**
> the previous `3-a` (scaffold apps/landing+demo together) and `3.5-a` (extract
> packages/ui after both apps exist) rows are replaced by the `2.6`/`2.7`/`3` rows above —
> `apps/demo` and `apps/landing` now scaffold separately, in that order, with package
> extraction starting at `2.6` instead of `3.5-a`. `web/` was already renamed to
> `apps/dashboard/` ahead of this plan (see `apps/README.md`); `3.5-b` now means
> "rebuild its IA," not "move the directory."

`2.5-review` is allowed to deploy from legacy paths because TikTok review only needs public access,
not the final monorepo runtime layout. It must not introduce production-only dependencies such as
Redis, cron, background workers, ML batch jobs, polling services, webhooks, or HA scaling unless the
review login/OAuth path cannot start without them.

---

## Import boundary rules (future)

```
apps/*     → may import packages/*
apps/*     → must NOT import other apps/*
packages/* → may import packages/* (acyclic)
packages/* → must NOT import apps/*
backend/*  → must NOT import apps/* or packages/*
apps/*     → backend only via packages/api-client (HTTP)
```

---

## Related docs

- As-built registry: [`map.md`](map.md)
- Phase 2.5 scope: [`../product/phases/phase-2.5-deployment.md`](../product/phases/phase-2.5-deployment.md)
- Phase 3 demo IA: [`../product/phases/phase-3-landing-demo.md`](../product/phases/phase-3-landing-demo.md)
