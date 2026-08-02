# Parallel status — Meta A1 (#601 children wave 1)

**Status: IN PROGRESS** (2026-07-31)  
**Parent PRD:** [#601](https://github.com/thienphung00/Juli-AI/issues/601)  
**Parallel with:** Meta A2 (#615–#617) — path-disjoint (`cdp_speed`/`webhook` vs `cdp_batch`)  
**Cache mandate:** two-tier workflow prompt cache required before every Executor/Review

## Locked decisions

| # | Decision |
|---|----------|
| 1 | Sequential PRs: #625 → PR open → then #626 |
| 2 | Do not touch A2 `services/cdp_batch/` or shared `status.md` / `CONTEXT.md` |
| 3 | Epic registry CDP-A1-* prepared in Meta primary checkout (local, alongside A2 CDP-A2-*) |

## Issues

| Issue | Slice | Domain | Worktree / branch | Meta | Status |
|-------|-------|--------|-------------------|------|--------|
| [#625](https://github.com/thienphung00/Juli-AI/issues/625) | CDP-A1-1 | backend | `.worktrees/issue-625` / `feature/issue-625-material-deployed-handoff` | ready | **CI green · MERGEABLE** [#636](https://github.com/thienphung00/Juli-AI/pull/636) |
| [#626](https://github.com/thienphung00/Juli-AI/issues/626) | CDP-A1-2 | backend | `.worktrees/issue-626` / `feature/issue-626-targeted-fetch-planner` | ready | **CI green · MERGEABLE** [#637](https://github.com/thienphung00/Juli-AI/pull/637) |

## Ops lock

**Holder:** Meta A1 (#625)  
**Rule:** stagger remote ops ≥30s vs Meta A2; one issue PR at a time on this track
