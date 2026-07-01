# apps/

Product deployables for the Juli AI ecosystem. Each subdirectory is an independently deployable app.

| App | Domain | Phase | Status |
|-----|--------|-------|--------|
| [`landing/`](landing/) | `app-juli.com` | 3 | Scaffold only |
| [`demo/`](demo/) | `demo.app-juli.com` | 3 | Scaffold only |
| [`dashboard/`](dashboard/) | `dashboard.app-juli.com` | 3.5 | Scaffold only |
| [`mobile/`](mobile/) | App stores | 4 | Scaffold only |

**Not to be confused with `src/apps/`** — that path is backend entrypoint composition in the legacy layout.

Runtime code currently lives in legacy paths:

| Legacy | Future |
|--------|--------|
| `web/` | `apps/dashboard` |
| `ios/` | `apps/mobile` |

See [`docs/architecture/migration-plan.md`](../docs/architecture/migration-plan.md).
