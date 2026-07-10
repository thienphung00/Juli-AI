# App Review Deployment — Issues

> **Parent PRD:** [#249](https://github.com/thienphung00/Juli-AI/issues/249)  
> **Phase doc:** [`docs/product/phases/phase-2.5-deployment.md`](../../product/phases/phase-2.5-deployment.md)  
> **Status:** Complete — smoke sign-off 2026-07-03 ([#261](https://github.com/thienphung00/Juli-AI/issues/261))

Implementation slices for the TikTok App Review public deployment. All slices below are
**complete** unless noted.

| Slice | Issue | Title | Status |
|-------|-------|-------|--------|
| P2.5-d | [#253](https://github.com/thienphung00/Juli-AI/issues/253) | Deploy config (Nginx/systemd/env/smoke) | Done |
| P2.5-AR-1 | [#256](https://github.com/thienphung00/Juli-AI/issues/256) | VPS + Nginx + HTTPS public domain routing | Done |
| P2.5-AR-2a | [#257](https://github.com/thienphung00/Juli-AI/issues/257) | Deploy frontend on review VPS | Done |
| P2.5-AR-2b | [#258](https://github.com/thienphung00/Juli-AI/issues/258) | Deploy backend on review VPS | Done |
| P2.5-AR-3 | [#259](https://github.com/thienphung00/Juli-AI/issues/259) | TikTok OAuth callback route | Done |
| P2.5-AR-4 | [#260](https://github.com/thienphung00/Juli-AI/issues/260) | Reviewer login path | Done |
| P2.5-e | [#254](https://github.com/thienphung00/Juli-AI/issues/254) | Wire App Review domains (E2E verification) | Done |
| P2.5-AR-5 | [#261](https://github.com/thienphung00/Juli-AI/issues/261) | Smoke checklist / sign-off | Done |

**#256 runbook:** [`docs/runbooks/vps-wiring-runbook.md`](../../../docs/runbooks/vps-wiring-runbook.md)

**#257 runbook:** [`docs/runbooks/frontend-deploy-runbook.md`](../../../docs/runbooks/frontend-deploy-runbook.md)

**#258 runbook:** [`docs/runbooks/backend-deploy-runbook.md`](../../../docs/runbooks/backend-deploy-runbook.md)

**#260 runbook:** [`docs/runbooks/reviewer-login-runbook.md`](../../../docs/runbooks/reviewer-login-runbook.md)

**#261 runbook:** [`docs/runbooks/smoke-checklist-runbook.md`](../../../docs/runbooks/smoke-checklist-runbook.md)
