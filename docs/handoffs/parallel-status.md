# Parallel status — Head Meta A1/A2 wave (rerun)

**Status: IN PROGRESS** (2026-07-31 rerun)  
**Head Meta:** this chat — owns `parallel-status*.md`, ops lock arbitration, exit-gate merge to `main`  
**Mode:** Wave branches under `main`; issue PRs merge into wave first; wave → `main` only after exit gate  
**Merge Queue:** unavailable (user-owned repo) → sync-before-merge fallback  
**Cache mandate:** try existing two-tier workflow caches first; Meta runs `meta_prepare_executor.py` before every Executor

## Tracks

| Track | Integration branch | Issues | Meta model | Path fence |
|-------|-------------------|--------|------------|------------|
| **A1** | `feature/a1-wave` | [#627](https://github.com/thienphung00/Juli-AI/issues/627) | GPT 5.6 | `cdp_speed` / webhook material path — **no** `cdp_batch/` |
| **A2** | `feature/a2-wave` | [#618](https://github.com/thienphung00/Juli-AI/issues/618) → [#620](https://github.com/thienphung00/Juli-AI/issues/620) → [#624](https://github.com/thienphung00/Juli-AI/issues/624) → [#619](https://github.com/thienphung00/Juli-AI/issues/619) | GPT 5.6 | `cdp_batch` / ops docs — **no** `webhook/` or `cdp_speed/` product edits |

## Locked decisions

| # | Decision |
|---|----------|
| 1 | Head Meta alone edits this file + track status handoffs; Executor/Review sub-agents do **not** touch process/parallel track files |
| 2 | Issue feature branches merge into their wave (`a1-wave` / `a2-wave`), not directly to `main` |
| 3 | A1 and A2 merge to `main` only after both tracks exit-gate PASS (Review + validate + CI green) |
| 4 | Ops: stagger remote ops ≥30s between tracks; one PR push/merge at a time per track |
| 5 | A2 merge order into `a2-wave`: #618 → #620 → #624 → #619 (sequential); A1 is single-issue |
| 6 | Blockers already on main: #625/#626 (#627); #608/#615/#604 as cited on A2 issues |

## Issue board

| Issue | Track | Slice | Worktree / branch | Status |
|-------|-------|-------|-------------------|--------|
| #627 | A1 | CDP-A1-3 | `.worktrees/issue-627` / `feature/issue-627-shared-compute-orchestrator` | **readyForExecutor** — Meta A1 running |
| #618 | A2 | CDP-A2-4 | `.worktrees/a2-wave/.worktrees/issue-618` / `feature/issue-618-shop-compute-mutex` | **readyForExecutor** — Meta A2 running |
| #620 | A2 | CDP-A2-5 | `.worktrees/issue-620` | in progress (Meta A2) |
| #624 | A2 | CDP-A2-6 | `.worktrees/issue-624` | **parallel** — cache valid, Executor launched |
| #619 | A2 | CDP-A2-7 | `.worktrees/issue-619` | **parallel** — cache valid, Executor launched |

## Ops lock

**Holder:** Head Meta (arbitrates); Meta A1 holds A1 remote ops; Meta A2 holds A2 remote ops  
**Rule:** never concurrent `git push` / `gh pr create|merge|checks` across tracks without ≥30s stagger

## Exit gate (wave → main)

- [ ] A1: #627 Review+validate PASS, PR into `a1-wave` green, `a1-wave` PR → `main` green
- [ ] A2: #618/#620/#624/#619 all merged to `a2-wave`, Review+validate PASS each, `a2-wave` PR → `main` green
- [ ] Path-disjoint re-check before final merges
