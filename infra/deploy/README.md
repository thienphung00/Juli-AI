# infra/deploy

Per-product deploy manifests and environment templates for the App Review deployment.

| Property | Value |
|----------|-------|
| **Phase** | 2.5-d |
| **Status** | App Review deploy config — VPS/Nginx/HTTPS, no production traffic |

**Start here:** [`app-review-runbook.md`](app-review-runbook.md) — VPS/Nginx/HTTPS
topology, env vars (no secrets in git), independent frontend/backend restart, and
validation.

**VPS layout:** single checkout at `~/Juli-AI-v2` — backend `.env` at repo root,
frontend `.env.production` in `web/`.

| Path | Purpose |
|------|---------|
| [`app-review-runbook.md`](app-review-runbook.md) | Deploy runbook + reviewer checklist |
| [`vps-wiring-runbook.md`](vps-wiring-runbook.md) | HITL VPS DNS + Nginx + HTTPS (#256) |
| [`frontend-deploy-runbook.md`](frontend-deploy-runbook.md) | Deploy Next.js frontend on VPS (#257) |
| [`backend-deploy-runbook.md`](backend-deploy-runbook.md) | Deploy FastAPI backend on VPS (#258) |
| [`reviewer-login-runbook.md`](reviewer-login-runbook.md) | Reviewer demo login + optional Supabase OTP (#260) |
| [`provision-nginx.sh`](provision-nginx.sh) | Install Nginx vhosts on the VPS (#256) |
| [`provision-frontend.sh`](provision-frontend.sh) | Install juli-web + build on the VPS (#257) |
| [`provision-backend.sh`](provision-backend.sh) | Install juli-api + pip deps on the VPS (#258) |
| [`build-frontend-review.sh`](build-frontend-review.sh) | `npm ci && npm run build` with UI-only login |
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
