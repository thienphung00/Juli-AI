# infra/

Infrastructure, CI/CD, and deployment configuration.

| Path | Purpose | Status |
|------|---------|--------|
| [`ci/`](ci/) | CI pipeline config split from `.github/workflows/` | Scaffold only |
| [`deploy/`](deploy/) | App Review deploy runbooks, Nginx, systemd, smoke tests | **Live** (sign-off 2026-07-03) |

**Current CI:** [`.github/workflows/`](../.github/workflows/)

**Domains (App Review — live):**

| Domain | Product (current) | Product (Phase 3+ target) |
|--------|-------------------|---------------------------|
| `app-juli.com` | Legacy `web/` dashboard (App Review) | `apps/landing` |
| `api.app-juli.com` | Backend API (`backend/`) | Backend API |
| `demo.app-juli.com` | — | `apps/demo` |
| `dashboard.app-juli.com` | — | `apps/dashboard` |

See [`docs/phases/phase-2.5-deployment.md`](../docs/phases/phase-2.5-deployment.md).
