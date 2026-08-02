# Parallel status — Meta A1 (#627 Shared Compute Orchestrator)

**Status: IN PROGRESS** (2026-07-31 rerun)  
**Parent PRD:** [#601](https://github.com/thienphung00/Juli-AI/issues/601)  
**Integration branch:** `feature/a1-wave` (`.worktrees/a1-wave`)  
**Parallel with:** Meta A2 (#618→#620→#624→#619) — path-disjoint (`cdp_speed` vs `cdp_batch`)  
**Cache:** `meta_prepare --issue 627` → **readyForExecutor: true** (cache-first)

## Locked decisions

| # | Decision |
|---|----------|
| 1 | PR base = `feature/a1-wave` (not `main`); wave → main only at Head Meta exit gate |
| 2 | Do not touch A2 `services/cdp_batch/` or shared Head `parallel-status.md` (Head Meta owns that) |
| 3 | Meta A1 owns this file + issue-627 routing commits |

## Issues

| Issue | Slice | Domain | Worktree / branch | Status |
|-------|-------|--------|-------------------|--------|
| [#627](https://github.com/thienphung00/Juli-AI/issues/627) | CDP-A1-3 | backend | `.worktrees/issue-627` / `feature/issue-627-shared-compute-orchestrator` | Meta running — Executor next |

## Ops lock

**Holder:** Meta A1 (#627)  
**Rule:** stagger remote ops ≥30s vs Meta A2
