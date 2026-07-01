# Repository Migration Plan

> **Tier 1 — path mapping & migration sequence.** Read [`EXECUTION.md`](../../EXECUTION.md) first.  
> **Owns:** current → target path mapping, migration PR sequence, naming collision notes.  
> **Does not own:** as-built module registry (`map.md`), deploy domain details (`phase-2.5-deployment.md`).

**Status:** Phase 2.5-a — docs + ownership scaffold complete; runtime code not moved.

---

## Current vs target layout

### Current (as-built)

```text
juli-ai-v2/
├── src/                  # Python backend modular monolith (runtime)
│   ├── apps/             # Backend entrypoints (NOT product apps)
│   ├── modules/
│   └── shared/
├── web/                  # Next.js seller dashboard (legacy pre-ecosystem)
├── ios/                  # SwiftUI mobile app (legacy)
├── apps/                 # Product deployables (scaffold only — Phase 2.5-a)
├── packages/             # Shared libraries (scaffold only)
├── backend/              # Backend target layout (scaffold only)
├── infra/                # CI/CD + deploy config (scaffold only)
├── docs/
├── scripts/
├── tests/
├── alembic/
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
| `web/` | `apps/dashboard/` (Phase 3.5) | Current seller dashboard |
| — | `apps/demo/` (Phase 3) | New mock storytelling app |
| — | `apps/landing/` (Phase 3) | New marketing site |
| `ios/` | `apps/mobile/` | Mobile app |
| `web/src/components/` | `packages/ui/` | Shared components (incremental) |
| `web/src/lib/` types | `packages/types/` | Shared TS types |
| `.github/workflows/` | `infra/ci/` | CI pipeline config |
| deploy configs (future) | `infra/deploy/` | Per-product deploy manifests |

---

## Naming collision: `src/apps` vs `apps/`

| Path | Meaning |
|------|---------|
| **`src/apps/`** | Backend composition layer — FastAPI entrypoints, cron workers. Python import path. |
| **`apps/`** (top-level) | Product deployables — landing, demo, dashboard, mobile. Frontend/mobile apps. |

Do **not** import from top-level `apps/` in Python backend code. Do **not** confuse
`src.apps.api_gateway` with `apps/demo`.

---

## Migration PR sequence (planned)

Each PR must pass the full test suite before and after. No opportunistic refactors.

| PR | Scope | Gate |
|----|-------|------|
| **2.5-a** (this PR) | Docs + scaffold READMEs | No runtime changes |
| **2.5-b** | Introduce `pnpm` workspace + Turborepo skeleton | `web/` still builds |
| **2.5-c** | Move `src/` → `backend/` with import rewrites | `pytest` green |
| **2.5-d** | Split deploy config into `infra/` | CI green |
| **3-a** | Scaffold `apps/landing` + `apps/demo` | New apps build independently |
| **3.5-a** | Extract `packages/ui`, `packages/theme` from `web/` | `web/` + new apps consume packages |
| **3.5-b** | Move `web/` → `apps/dashboard` | Dashboard deploys to `dashboard.app-juli.com` |

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
- Phase 2.5 scope: [`../phases/phase-2.5-deployment.md`](../phases/phase-2.5-deployment.md)
- Phase 3 demo IA: [`../phases/phase-3-landing-demo.md`](../phases/phase-3-landing-demo.md)
