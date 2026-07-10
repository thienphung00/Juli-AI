# Runbooks

Step-by-step operator guides for App Review deployment (Phase 2.5-d).

| Runbook | Issue | Purpose |
|---------|-------|---------|
| [`app-review-runbook.md`](app-review-runbook.md) | #253 | Master deploy topology, env vars, validation |
| [`vps-wiring-runbook.md`](vps-wiring-runbook.md) | #256 | HITL VPS DNS + Nginx + HTTPS |
| [`frontend-deploy-runbook.md`](frontend-deploy-runbook.md) | #257 | Build and run Next.js on VPS |
| [`backend-deploy-runbook.md`](backend-deploy-runbook.md) | #258 | Build and run FastAPI on VPS |
| [`reviewer-login-runbook.md`](reviewer-login-runbook.md) | #260 | Reviewer demo login |
| [`smoke-checklist-runbook.md`](smoke-checklist-runbook.md) | #261 | App Review smoke sign-off + CORS |

Operational scripts, Nginx, and systemd units remain under [`infra/`](../infra/).

Phase context: [`docs/product/phases/phase-2.5-deployment.md`](../product/phases/phase-2.5-deployment.md).
