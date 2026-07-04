# apps/

Product deployables for the Juli AI ecosystem. Each subdirectory is an independently deployable app.

| App | Domain | Phase | Status |
|-----|--------|-------|--------|
| [`landing/`](landing/) | `app-juli.com` (Phase 3 target) | 3 | Scaffold only |
| [`demo/`](demo/) | `demo.app-juli.com` | 3 | Scaffold only |
| [`dashboard/`](dashboard/) | `dashboard.app-juli.com` | 3.5 | Scaffold only |
| [`mobile/`](mobile/) | App stores | 4 | Scaffold only |

**Not to be confused with `backend/api/`** — that path is the FastAPI backend entrypoint.

Runtime code currently lives in legacy paths:

| Legacy | Future | Current live use |
|--------|--------|------------------|
| `web/` | `apps/dashboard` | **`app-juli.com`** (App Review until Phase 3 landing) |
| `ios/` | `apps/mobile` | — |

**Status:** Phase 2.5 complete (2026-07-03). Workspace tooling (`pnpm` + Turborepo) in place;
scaffold members are private placeholders.

See [`docs/phases/phase-2.5-deployment.md`](../docs/phases/phase-2.5-deployment.md).
