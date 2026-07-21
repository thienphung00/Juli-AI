# Parallel status — Phase 2.6 stretch + Demo deploy (#404–#406)

**Started:** 2026-07-21 · **Parent PRD:** [#395](https://github.com/thienphung00/Juli-AI/issues/395) · **AFK run** · Meta orchestrates only

## Locked decisions

| # | Decision |
|---|----------|
| 1 | Parallel with file-ownership partition |
| 2 | Open PRs + CI green; **do not merge** |
| 3 | Hard failure: retry ×2, then **stop that issue** (siblings continue) |
| 4 | **4A** — repo config + contract tests + CI only (no live VPS deploy) |
| 5 | Per-issue review agents may push/PR (stagger ≥30s) |
| 6 | **No** `packages/contracts` edits |

## Current run

| Issue | Title | Modules (exclusive) | Status | Branch | Worktree | GitHub ops |
|-------|-------|---------------------|--------|--------|----------|------------|
| #404 | Six-KPI Analytics | `apps/demo/src/app/analytics/**`, analytics lib/components/tests; `analytics*` keys in demo-state | Executing (wave1) | `feature/issue-404-analytics` | `.worktrees/issue-404` | per-issue (5B) |
| #405 | Editable Settings | `apps/demo/src/app/settings/**`, settings lib/components/tests; `settings*` keys in demo-state | PR open / CI green — [#461](https://github.com/thienphung00/Juli-AI/pull/461) | `feature/issue-405-settings` | `.worktrees/issue-405` | per-issue (5B) |
| #406 | Demo deploy automation | `infra/nginx\|systemd\|scripts` demo assets, runbooks, deploy contract tests/CI | Executing (wave1) | `feature/issue-406-demo-deploy` | `.worktrees/issue-406` | per-issue (5B) |

## Module disjointness (ownership)

| Path family | Owner |
|-------------|-------|
| `apps/demo/src/app/analytics/**`, analytics-only components/lib/tests | #404 |
| `apps/demo/src/app/settings/**`, settings-only components/lib/tests | #405 |
| `infra/**` demo nginx/systemd/scripts, deploy runbooks, deploy contract tests, CI deploy contracts | #406 |
| `demo-state.tsx` / `demo-shell.tsx` | Append-only: #404 may add `analytics*` keys / `/analytics` assistance; #405 may add `settings*` keys / `/settings` assistance; neither restructures the other’s keys |
| `packages/contracts`, root lockfile/CI unrelated to demo deploy contracts | **Forbidden** |

## GitHub ops

| Field | Value |
|-------|-------|
| **Owner** | Per-issue Review/ship agents (5B); stagger ≥30s |
| **Merge** | **Forbidden** this run (2B) |
| **Sync-before-merge** | N/A for merge; still rebase onto `origin/main` before final CI if siblings push |

### Remote op log

| Time (UTC) | Agent | Command | Issue |
|------------|-------|---------|-------|
| 2026-07-21T11:04Z | Review #405 | `git push -u origin feature/issue-405-settings`; `gh pr create` | #405 → PR [#461](https://github.com/thienphung00/Juli-AI/pull/461) |

## References

- Topology: [`worktree-branch-topology.md`](worktree-branch-topology.md)
- Isolate vs parallel: [`.cursor/rules/issue-workflow.mdc`](../../.cursor/rules/issue-workflow.mdc)
