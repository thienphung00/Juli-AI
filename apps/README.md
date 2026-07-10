# apps/

Product deployables for the Juli AI ecosystem.

| App | Domain | Status |
|-----|--------|--------|
| [`dashboard/`](dashboard/) | `app-juli.com` (App Review) | **Live** — Next.js seller dashboard (Home / Decisions / Juli Chat per ADR-014) |

**Not to be confused with `backend/src/juli_backend/api/`** — that path is the FastAPI backend entrypoint.

| Legacy | Current |
|--------|---------|
| `web/` (removed) | `apps/dashboard/` |
| `ios/` | native iOS app (unchanged) |

Frontend uses **npm** in `apps/dashboard/` (`npm ci`, `npm run build`, `npm run dev`).

See [`docs/handoffs/repo-restructure-plan.md`](../docs/handoffs/repo-restructure-plan.md) Phase 3.
