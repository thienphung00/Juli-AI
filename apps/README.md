# apps/

Product deployables for the Juli AI ecosystem.

| App | Production domain | Dev port | Status |
|-----|-------------------|----------|--------|
| [`landing/`](landing/) | `app-juli.com` | **3007** | **Live** — public marketing site; owns the Login/Signup entry (`/login`, Phase 3.5-C) |
| [`demo/`](demo/) | `demo.app-juli.com` | **3100** | **Live** — public Demo in Mock mode, no signup |
| [`dashboard/`](dashboard/) | *(none)* | **3000** | **Server-side only** — retired from production by [#842](https://github.com/thienphung00/Juli-AI/issues/842)/#891; still built and tested in CI, never deployed |

`deploy.sh` has exactly three lanes — `api`, `demo`, `landing`. `apps/dashboard` is
absent from `LANE_ORDER` and from `release.yml`'s app matrix on purpose: the main
domain serves Landing, and the dashboard is reachable only when someone runs it.

**Not to be confused with `backend/src/juli_backend/api/`** — that path is the FastAPI
backend entrypoint.

## Local development

All three apps run locally on fixed ports so you can view and polish them side by side:

```bash
pnpm setup     # install BOTH package managers' deps, in the required order
pnpm dev       # start all three: dashboard :3000, demo :3100, landing :3007
```

Individually:

```bash
pnpm dev:dashboard   # http://localhost:3000
pnpm dev:demo        # http://localhost:3100
pnpm dev:landing     # http://localhost:3007
```

### Two package managers — order matters

`apps/dashboard` is **npm-owned** and deliberately excluded from the pnpm workspace
(see the comment in [`pnpm-workspace.yaml`](../pnpm-workspace.yaml): matching it with
`apps/*` made every Dependabot npm bump desync `pnpm-lock.yaml`). Consequences:

- `pnpm --filter juli-web …` **matches nothing** — "No projects matched the filters".
  Drive the dashboard with `npm --prefix apps/dashboard`, never with pnpm.
- **A root `pnpm install` breaks the dashboard's node_modules.** It leaves
  `apps/dashboard/node_modules/next/dist/bin/next` missing and `npm run dev` fails with
  `Cannot find module`. Always re-run `npm --prefix apps/dashboard ci` afterwards —
  which is exactly what `pnpm setup` does, in that order.
- `turbo run dev` cannot reach the dashboard either, so the root `dev` script starts
  the three processes directly rather than through turbo.

### Turbopack root

`apps/dashboard/next.config.js` pins `turbopack.root` to the **repo root**, not the app
directory. With `root: __dirname` the dev server starts but every build fails with
`We couldn't find the Next.js package (next/package.json) from the project directory`,
even though `apps/dashboard/node_modules/next` exists. Verified on Next 16.2.11.

See [`docs/handoffs/repo-restructure-plan.md`](../docs/handoffs/repo-restructure-plan.md) Phase 3.
