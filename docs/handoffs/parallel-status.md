# Parallel status — Phase 3.5-A0 (#598 children)

**Status: IN PROGRESS** (2026-07-30)  
**Started:** 2026-07-30 · **Parent PRD:** [#598](https://github.com/thienphung00/Juli-AI/issues/598)  
**Mode:** Isolate for #603 (schemas first); #604/#605/#606 may parallel after #603 merges

## Locked decisions

| # | Decision |
|---|----------|
| 1 | `webhook_raw_events` = read-only audit shim; bronze = forward write path (#605) |
| 2 | Merge Queue unavailable → sync-before-merge fallback |
| 3 | One PR per child issue; data-platform domain |

## Issues

| Issue | Slice | Domain | Worktree / branch | Meta | Status |
|-------|-------|--------|-------------------|------|--------|
| [#603](https://github.com/thienphung00/Juli-AI/issues/603) | CDP-A0-1 | data-platform | `.worktrees/issue-603` / `feature/issue-603-cdp-a0-schemas` · [PR #609](https://github.com/thienphung00/Juli-AI/pull/609) | ready | **PR open — validate PASS** |
| [#604](https://github.com/thienphung00/Juli-AI/issues/604) | CDP-A0-2 | data-platform | — | blocked on #603 | queued |
| [#605](https://github.com/thienphung00/Juli-AI/issues/605) | CDP-A0-3 | data-platform | — | blocked on #603 | queued |
| [#606](https://github.com/thienphung00/Juli-AI/issues/606) | CDP-A0-5 | data-platform | — | blocked on #603 | queued |
| [#607](https://github.com/thienphung00/Juli-AI/issues/607) | CDP-A0-4 | data-platform | — | blocked on #605 | queued |
| [#608](https://github.com/thienphung00/Juli-AI/issues/608) | CDP-A0-6 | data-platform | — | blocked on #607+#606 | queued |

## Ops lock

**Holder:** #603 ops (`feature/issue-603-cdp-a0-schemas`)  
**Rule:** only ops holder may `git push` / `gh pr create|merge|checks`
