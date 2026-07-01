# infra/

Infrastructure, CI/CD, and deployment configuration.

| Path | Purpose | Status |
|------|---------|--------|
| [`ci/`](ci/) | CI pipeline config split from `.github/workflows/` | Scaffold only |
| [`deploy/`](deploy/) | Per-product deploy manifests (Vercel, Railway) | Scaffold only |

**Current CI:** [`.github/workflows/`](../.github/workflows/)

**Target domains:**

| Domain | Product |
|--------|---------|
| `app-juli.com` | Landing |
| `demo.app-juli.com` | Demo |
| `dashboard.app-juli.com` | Dashboard |
| `api.app-juli.com` | Backend API |

See [`docs/phases/phase-2.5-deployment.md`](../docs/phases/phase-2.5-deployment.md).
