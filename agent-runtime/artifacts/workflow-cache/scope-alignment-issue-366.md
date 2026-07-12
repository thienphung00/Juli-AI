# Scope Alignment — Issue #366 (child of parent #278)

**Parent issue:** #278 (constant — `parent-cache-issue-278.json`)  
**Status:** valid  
**Cache block version:** 1  
**Last validated:** 2026-07-12  
**Companion artifact:** `agent-runtime/artifacts/workflow-cache/issue-context-cache-366.json`

## Authority chain (this run)

| Rank | Source | Applies because |
|------|--------|---------------|
| 1 | `EXECUTION.md` slice P2-A1 | Phase/slice law — TikTok Partner integration |
| 2 | `parent-cache-issue-278` | Epic constant for all children |
| 3 | GitHub issue #366 | **Child** acceptance criteria (unique) |
| 4 | `docs/handoffs/phase-2-tiktok-implementation.md` | Epic handoff (when not superseded) |

## In scope (this issue)

- Live (unmocked) TikTok Sandbox OAuth + webhook signature integration tests under `tests/integration/`
- Skip markers when `TIKTOK_APP_KEY` / `TIKTOK_APP_SECRET` are absent
- GitHub Actions secret wiring for CI runs on PRs
- Contract tests for file placement, CI wiring, and no hardcoded secrets

## Out of scope

- Fujiwa polling E2E (#367), Layer 2 sandbox writes (#301), webhook catalog (#354)
- Committing real Partner Center credentials to source control
- `web/`, `ios/`, `src/modules/ml/`

## Acceptance criteria (GitHub #366)

1. New tests live under `tests/integration/` (`test_tiktok_sandbox_oauth.py`, `test_tiktok_sandbox_webhook.py`)
2. Tests skip when `TIKTOK_APP_KEY` / `TIKTOK_APP_SECRET` are unset
3. CI secrets configured in GitHub Actions so tests run on PRs
4. One behavior per test (token exchange success, invalid signature rejection, etc.)
5. No secrets committed to source control
