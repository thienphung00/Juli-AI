# apps/

Product deployables for the Juli AI ecosystem.

| App | Production domain | Dev port | Status |
|-----|-------------------|----------|--------|
| [`landing/`](landing/) | `app-juli.com` | **3007** | **Live** — public marketing site; owns the Login/Signup entry (`/login`, Phase 3.5-C) |
| [`demo/`](demo/) | `demo.app-juli.com` | **3100** | **Live** — public Demo in Mock mode, no signup |
| [`connector/`](connector/) | *(Chrome Web Store, manual)* | — | Juli Connector extension (fast track P24, D31.4); not deployed by CI |

`deploy.sh` has exactly three lanes — `api`, `demo`, `landing`.

The old `apps/dashboard` (npm package `juli-web`) was retired from production by
[#842](https://github.com/thienphung00/Juli-AI/issues/842)/#891 and **deleted from the
repo in fast-track P53 (C1, 2026-10-18)**; Demo and Landing replace it. Its source
is in git history before that commit.

**Not to be confused with `backend/src/juli_backend/api/`** — that path is the FastAPI
backend entrypoint.

## Local development

Both web apps run locally on fixed ports so you can view and polish them side by side:

```bash
pnpm setup     # pnpm install for the whole workspace
pnpm dev       # start both: demo :3100, landing :3007
```

Individually:

```bash
pnpm dev:demo        # http://localhost:3100
pnpm dev:landing     # http://localhost:3007
```

See [`docs/handoffs/repo-restructure-plan.md`](../docs/handoffs/repo-restructure-plan.md) Phase 3.
