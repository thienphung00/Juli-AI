# Parallel status — Issue #499 Demo static-asset bridge

**Ops lock:** parent Meta (this session)  
**Worktree:** `.worktrees/issue-499` · branch `feature/issue-499-demo-static-assets`  
**Parent:** #499 · **readyForExecutor:** true · **releaseEvidencePlanId:** `rep-499-demo-static-asset-bridge`

| Package | Agent | Write paths (exclusive) | Status |
|---------|-------|-------------------------|--------|
| DEMO-ASSET-1 runtime | Composer A | `apps/demo/next.config.ts`, `infra/systemd/juli-demo.service`, `infra/nginx/demo.app-juli.com.conf`, packaging lines in `infra/scripts/build-demo.sh` (+ optional `provision-demo.sh`), `tests/unit/test_demo_runtime_packaging.py` (new) | complete |
| DEMO-ASSET-2 assets | Composer B | `infra/scripts/verify-demo-static-assets.sh` (new), `infra/scripts/smoke-test-demo.sh`, `tests/unit/test_demo_static_asset_integrity.py` (new) | complete |
| DEMO-ASSET-3 e2e/rollback | Composer C | `apps/demo/e2e/exit-gate/static-asset-render.spec.ts` (new), `docs/runbooks/demo-deploy-runbook.md`, `tests/unit/test_demo_rollback_evidence.py` (new) | complete |

**Do not edit:** sibling caches; backend; TikTok docs; ECS (#498); redesign.

**Merge note:** single PR from this worktree after all three packages land; one implementation artifact for #499.
