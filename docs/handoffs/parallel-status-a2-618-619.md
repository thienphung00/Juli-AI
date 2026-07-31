# Parallel status — Meta A2 (#602 children wave)

**Status: IN PROGRESS** (2026-07-31)  
**Parent PRD:** [#602](https://github.com/thienphung00/Juli-AI/issues/602)  
**Integration branch:** `feature/a2-wave`  
**Parallel with:** Meta A1 (#601 / #627 track) — path-disjoint (`cdp_batch` vs `webhook`/`cdp_speed`)  
**Cache mandate:** two-tier workflow prompt cache required before every Executor/Review

## Locked decisions

| # | Decision |
|---|----------|
| 1 | Sequential PRs into `feature/a2-wave`: #618 → #620 → #624 → #619 |
| 2 | Do not touch A1 `services/webhook/`, `services/cdp_speed/`, or shared `status.md` / `CONTEXT.md` |
| 3 | Process routing via issue-prepare + `slices/CDP-A2-*` overlays; Meta serializes epicRegistry on A2 branch |
| 4 | Do not merge A2 → main until exit gate (all four green + Review/validate PASS) |

## Issues

| Issue | Slice | Domain | Worktree / branch | Meta | Status |
|-------|-------|--------|-------------------|------|--------|
| [#618](https://github.com/thienphung00/Juli-AI/issues/618) | CDP-A2-4 | backend | `.worktrees/issue-618` / `feature/issue-618-shop-compute-mutex` | pending | queued |
| [#620](https://github.com/thienphung00/Juli-AI/issues/620) | CDP-A2-5 | data-platform | TBD | pending | blocked on #618 merge to A2 |
| [#624](https://github.com/thienphung00/Juli-AI/issues/624) | CDP-A2-6 | docs | TBD | pending | blocked on #620 merge to A2 |
| [#619](https://github.com/thienphung00/Juli-AI/issues/619) | CDP-A2-7 | backend | TBD | pending | blocked on #624 merge to A2 |

## Ops lock

**Holder:** Meta A2 (#618)  
**Rule:** stagger remote ops ≥30s vs Meta A1; one issue PR at a time on this track
