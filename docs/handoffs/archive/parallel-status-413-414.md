# Parallel status — Phase 2.6 packages/ui compositions (#413–#414)

**Started:** 2026-07-16 · **Parent PRD:** [#395](https://github.com/thienphung00/Juli-AI/issues/395) · **Blocker cleared:** #412 merged (PR #415)

| Issue | Title | Modules (exclusive files) | Status | Branch | Worktree | GitHub ops |
|-------|-------|---------------------------|--------|--------|----------|------------|
| #413 | Surface compositions (cards, dialogs, forms, tables, popovers) | `packages/ui` cards/dialogs/forms/tables/popovers | **Unblocked** | `feature/issue-413-ui-surface-compositions` | `.worktrees/issue-413` | — |
| #414 | Feedback + navigation (toasts, loaders, nav, charts) | `packages/ui` toasts/loaders/nav/charts | **Unblocked** | `feature/issue-414-ui-feedback-nav` | `.worktrees/issue-414` | — |

## Module disjointness

Both issues touch `packages/ui` (would be **Isolate** under naive module overlap). Meta partitioned **file ownership** so they may run in parallel:

| Path family | Owner |
|-------------|-------|
| `card*`, `dialog*`, `form*`, `table*`, `popover*` | #413 |
| `toast*`, `loading-indicator*`, `chart*`, nav composition extensions | #414 |
| `index.ts` / `styles.css` / `MODULE.md` | Append-only per-issue marked sections; merge carefully at PR time |

Shared base from #412 (Button, Badge, Chip, ProgressBar, HealthBar, DestinationCard, RecommendationCard, PrimaryNavigation) is **read-only** unless a composition must compose them.

## GitHub ops lock

| Field | Value |
|-------|-------|
| **Owner** | Meta / #413 window (first to open PR) |
| **Last remote op** | — |
| **Stagger rule** | ≥ 30s between `git push`, `gh pr create`, `gh pr merge`, `gh issue close` |

### Remote op log

| Time (UTC) | Agent | Command | Issue |
|------------|-------|---------|-------|
| — | — | — | — |

## After each merge

1. Update Status column above (`Done` / `Blocked` / `Unblocked`).
2. Prefer merge #413 before #414 if both ready (surface before feedback is optional; either order OK if ownership respected).
3. Wait ≥ 30s before next remote GitHub op.
