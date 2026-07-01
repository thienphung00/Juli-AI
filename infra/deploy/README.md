# infra/deploy

Per-product deploy manifests and environment templates for the App Review deployment.

| Property | Value |
|----------|-------|
| **Phase** | 2.5-d |
| **Status** | App Review deploy config — VPS/Nginx/HTTPS, no production traffic |

**Start here:** [`app-review-runbook.md`](app-review-runbook.md) — VPS/Nginx/HTTPS
topology, env vars (no secrets in git), independent frontend/backend restart, and
validation.

| Path | Purpose |
|------|---------|
| [`app-review-runbook.md`](app-review-runbook.md) | Deploy runbook + reviewer checklist |
| [`nginx/`](nginx/) | Frontend/backend Nginx vhosts |
| [`systemd/`](systemd/) | `juli-web` / `juli-api` service units |
| [`env/`](env/) | Env templates (placeholders only) |
| [`smoke-test.sh`](smoke-test.sh) | DNS/TLS/frontend/health/OAuth checklist |

CI: `python -m pytest tests/unit/test_phase_2_5_deploy_config.py`.

**Target domains:**

| Domain | Product |
|--------|---------|
| `app-juli.com` | App Review frontend (legacy `web/`) |
| `demo.app-juli.com` | Demo |
| `dashboard.app-juli.com` | Dashboard |
| `api.app-juli.com` | Backend API |

See [`docs/phases/phase-2.5-deployment.md`](../../docs/phases/phase-2.5-deployment.md).
