# infra/

Infrastructure, CI/CD, and deployment configuration.

| Path | Purpose | Status |
|------|---------|--------|
| [`ci/`](ci/) | CI pipeline config split from `.github/workflows/` | Scaffold only |
| [`deploy/`](deploy/) | App Review deploy runbooks and reviewer checklists | **Live** (sign-off 2026-07-03) |
| [`scripts/`](scripts/) | VPS provision, deploy, rollback, secrets, smoke-test scripts | **Live** |
| [`nginx/`](nginx/) | Nginx vhosts for App Review domains | **Live** |
| [`systemd/`](systemd/) | `juli-web` / `juli-api` systemd units | **Live** |

**Current CI:** [`.github/workflows/`](../.github/workflows/)

**Domains (App Review — live):**

| Domain | Product |
|--------|---------|
| `app-juli.com` | App Review frontend (`web/`) |
| `api.app-juli.com` | Backend API (`backend/`) |

See [`docs/phases/phase-2.5-deployment.md`](../docs/phases/phase-2.5-deployment.md).
