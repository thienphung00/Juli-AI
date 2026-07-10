# infra/deploy

Deploy configuration index for App Review (Phase 2.5-d).

> **Runbooks moved to [`docs/runbooks/`](../../docs/runbooks/).** This folder keeps the
> deploy index; step-by-step operator docs live under `docs/runbooks/`.

| Property | Value |
|----------|-------|
| **Phase** | 2.5-d |
| **Status** | App Review deploy config — VPS/Nginx/HTTPS, no production traffic |

**Start here:** [`docs/runbooks/app-review-runbook.md`](../../docs/runbooks/app-review-runbook.md) —
VPS/Nginx/HTTPS topology, env vars (no secrets in git), independent frontend/backend restart,
and validation.

**VPS layout:** single checkout at `~/Juli-AI-v2` — backend `.env` at repo root,
frontend `.env.production` in `apps/dashboard/`.

| Runbook | Purpose |
|---------|---------|
| [`app-review-runbook.md`](../../docs/runbooks/app-review-runbook.md) | Deploy runbook + reviewer checklist |
| [`vps-wiring-runbook.md`](../../docs/runbooks/vps-wiring-runbook.md) | HITL VPS DNS + Nginx + HTTPS (#256) |
| [`frontend-deploy-runbook.md`](../../docs/runbooks/frontend-deploy-runbook.md) | Deploy Next.js frontend on VPS (#257) |
| [`backend-deploy-runbook.md`](../../docs/runbooks/backend-deploy-runbook.md) | Deploy FastAPI backend on VPS (#258) |
| [`reviewer-login-runbook.md`](../../docs/runbooks/reviewer-login-runbook.md) | Reviewer demo login + optional Supabase OTP (#260) |
| [`smoke-checklist-runbook.md`](../../docs/runbooks/smoke-checklist-runbook.md) | App Review smoke sign-off + CORS (#261) |

**Operational assets** (scripts, Nginx, systemd, env templates) live alongside this folder:

| Path | Purpose |
|------|---------|
| [`../scripts/`](../scripts/) | Provision, build, deploy, rollback, secrets, smoke-test scripts |
| [`../nginx/`](../nginx/) | Frontend/backend Nginx vhosts |
| [`../systemd/`](../systemd/) | `juli-web` / `juli-api` service units (run from `~/releases/current`) |
| [`../scripts/env/`](../scripts/env/) | Env templates (placeholders — real values in AWS Secrets Manager) |
| [`../scripts/aws/`](../scripts/aws/) | IAM policy for the `juli-vps-secrets-reader` user |

CI: `python -m pytest tests/unit/test_phase_2_5_deploy_config.py`. Continuous
delivery, rollback, secrets, and monitoring are documented in
[`app-review-runbook.md`](../../docs/runbooks/app-review-runbook.md) (see "Continuous Delivery",
"Rollback", "Secrets", and "Minimal Monitoring").

**Target domains:**

| Domain | Product |
|--------|---------|
| `app-juli.com` | App Review frontend (`apps/dashboard/`) |
| `demo.app-juli.com` | Demo |
| `dashboard.app-juli.com` | Dashboard |
| `api.app-juli.com` | Backend API |

See [`docs/product/phases/phase-2.5-deployment.md`](../../docs/product/phases/phase-2.5-deployment.md).

**Local artifact hygiene:** after aggressive branch switches or parallel worktrees, run
`./scripts/clean-local.sh` from the repo root to remove `node_modules/`, `.next/`,
`__pycache__/`, `.pytest_cache/`, and `.worktrees/` (all gitignored).
