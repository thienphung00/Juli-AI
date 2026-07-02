# App Review Deployment — Issues

> **Parent PRD:** [#249](https://github.com/thienphung00/Juli-AI/issues/249)  
> **Phase doc:** [`docs/phases/phase-2.5-deployment.md`](../../phases/phase-2.5-deployment.md)

Implementation slices for the TikTok App Review public deployment. Process in order;
HITL slices require manual VPS/DNS/provider steps.

| Slice | Issue | Title | Type | Blocked by |
|-------|-------|-------|------|------------|
| P2.5-d | [#253](https://github.com/thienphung00/Juli-AI/issues/253) | Deploy config (Nginx/systemd/env/smoke) | AFK | — |
| P2.5-AR-1 | [#256](https://github.com/thienphung00/Juli-AI/issues/256) | VPS + Nginx + HTTPS public domain routing | HITL | #253 |
| P2.5-AR-2a | [#257](https://github.com/thienphung00/Juli-AI/issues/257) | Deploy frontend on review VPS | AFK/HITL | #256 |
| P2.5-AR-2b | [#258](https://github.com/thienphung00/Juli-AI/issues/258) | Deploy backend on review VPS | AFK/HITL | #256 |
| P2.5-AR-3 | [#259](https://github.com/thienphung00/Juli-AI/issues/259) | TikTok OAuth callback route | AFK | #258 |
| P2.5-AR-4 | [#260](https://github.com/thienphung00/Juli-AI/issues/260) | Reviewer login path | AFK/HITL | #257, #258 |
| P2.5-e | [#254](https://github.com/thienphung00/Juli-AI/issues/254) | Wire App Review domains (E2E verification) | HITL | #253, #256–#260 |
| P2.5-AR-5 | [#261](https://github.com/thienphung00/Juli-AI/issues/261) | Smoke checklist / sign-off | HITL | #254 |

**#256 runbook:** [`infra/deploy/vps-wiring-runbook.md`](../../../infra/deploy/vps-wiring-runbook.md)
