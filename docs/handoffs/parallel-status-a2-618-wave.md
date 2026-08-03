# Parallel status — Meta A2 (#602 wave: #618 → #620 → #624 → #619)

**Status: IN PROGRESS** (2026-07-31)  
**Parent PRD:** [#602](https://github.com/thienphung00/Juli-AI/issues/602)  
**Integration branch:** `feature/a2-wave` (issue PRs merge here; A2→main only at exit gate)  
**Parallel with:** Meta A1 (#601 / #627 track) — path-disjoint (`cdp_batch` vs `webhook`/`cdp_speed`)  
**Cache mandate:** two-tier workflow prompt cache required before every Executor/Review

## Locked decisions

| # | Decision |
|---|----------|
| 1 | Sequential merges into `feature/a2-wave`: #618 → #620 → #624 → #619 |
| 2 | Do not touch A1 `services/webhook/` material handoff, `services/cdp_speed/`, or shared `status.md` / `CONTEXT.md` |
| 3 | Routing via `issue-prepare/{N}.yml` + `slices/CDP-A2-*` overlays; Meta owns `agent-runtime.config.yml` epic #602 |
| 4 | Executors must NOT edit `status.md`, `CONTEXT.md`, `slice-routing.yml`, `agent-runtime.config.yml` |

## Issues

| Issue | Slice | Domain | Worktree / branch | Meta | Status |
|-------|-------|--------|-------------------|------|--------|
| [#618](https://github.com/thienphung00/Juli-AI/issues/618) | CDP-A2-4 | backend | pending | preparing | ShopComputeMutex |
| [#620](https://github.com/thienphung00/Juli-AI/issues/620) | CDP-A2-5 | backend | — | queued | Partition checkpoints |
| [#624](https://github.com/thienphung00/Juli-AI/issues/624) | CDP-A2-6 | backend | — | queued | Replica isolation docs |
| [#619](https://github.com/thienphung00/Juli-AI/issues/619) | CDP-A2-7 | backend | — | queued | BatchFetchPlanner |

## Ops lock

**Holder:** Meta A2 (#618)  
**Rule:** stagger remote ops ≥30s vs Meta A1; one issue PR at a time on this track into `feature/a2-wave`
