# Parallel status — MVP Phase 1 (#118–#120)

**Started:** 2026-06-05 · **Parent PRD:** [#113](https://github.com/thienphung00/Juli-AI/issues/113)

| Issue | Title | Modules | Status | Branch | Worktree | GitHub ops |
|-------|-------|---------|--------|--------|----------|------------|
| #118 | Seller home shell — routing + persona switcher | `web/seller-home` | **Done** (merged #129) | `feature/issue-118-ship-verify` | `.worktrees/issue-118` | **Owner** — verify + close issue |
| #119 | New Seller Copilot UI (mocked) | `web/workflows/new-seller` | Unblocked | `feature/issue-119-new-seller-copilot` | `.worktrees/issue-119` | Local commits; hand off push/PR to #118 window |
| #120 | Revenue Leakage Detection UI (mocked) | `web/workflows/leakage` | **Ready for PR** | `feature/issue-120-revenue-leakage-ui` | `.worktrees/issue-120` | Local commits; hand off push/PR to #118 window |

## Module disjointness

#119 and #120 touch **disjoint** workflow UI directories. They may run in parallel per `issue-workflow.mdc`. #118 is already on `main`; its window runs ship verification only.

## GitHub ops lock

| Field | Value |
|-------|-------|
| **Owner** | Window #118 (ship-verify) |
| **Last remote op** | — |
| **Stagger rule** | ≥ 30s between `git push`, `gh pr create`, `gh pr merge`, `gh issue close` |

### Remote op log

| Time (UTC) | Agent | Command | Issue |
|------------|-------|---------|-------|
| — | — | — | — |

## After each merge

1. Update Status column above (`Done` / `Blocked` / `Unblocked`).
2. Update `EXECUTION.md` slice checkbox (P1-2 for #119, P1-3 for #120).
3. Wait ≥ 30s before next remote GitHub op.
