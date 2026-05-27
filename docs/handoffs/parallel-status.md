# Parallel Implementation Status

Live coordination doc for parallel agents implementing GitHub issues in
separate git worktrees. **Every in-flight worktree must have a row here.**

Protocol is defined in [`_bootstrap.md`](./_bootstrap.md). Brief recap:

- Claim a row **before** the first edit in your worktree.
- Only **one** in-flight row may list a given module under `Writer of`.
- Update `Phase` and `Last update` at every phase transition.
- After merge: mark `merged`, remove the worktree, move row to `## Archive`
  on the next sweep.

## Conventions

| Field          | Allowed values                                                     |
|----------------|--------------------------------------------------------------------|
| `Issue`        | `#<number>` (must exist on GitHub)                                 |
| `Worktree`     | Absolute or repo-relative path to the worktree                     |
| `Branch`       | `feat/issue-<n>-<slug>` or `fix/issue-<n>-<slug>`                  |
| `Writer of`    | Comma-separated module paths the agent will modify                 |
| `Reader of`    | Comma-separated module paths the agent only reads                  |
| `Phase`        | `focus` / `tdd-red` / `tdd-green` / `review` / `pr-open` / `merged` / `blocked` |
| `Owner`        | Human or agent identifier (e.g. `agent-window-1`, `sdk-cloud-3`)   |
| `Last update`  | ISO 8601 timestamp, UTC                                            |

## In-flight

| Issue | Worktree | Branch | Writer of | Reader of | Phase | Owner | Last update |
|-------|----------|--------|-----------|-----------|-------|-------|-------------|
| _(none)_ | | | | | | | |

## Recently released (keep one cycle)

| Issue | Modules released | Released at |
|-------|------------------|-------------|
| #45 | `web` | 2026-05-26 |
| #42 | `ios` | 2026-05-26 |
| #37 | `api` | 2026-05-26 |
| #34 | `intelligence/scoring` | 2026-05-26 |

## Archive

<!-- Move rows here after one cycle. Newest at top. -->
| Issue | Worktree | Branch | Writer of | Reader of | Phase | Owner | Last update |
|-------|----------|--------|-----------|-----------|-------|-------|-------------|
| #45 | `../juli-ai-issue-45` | `feat/issue-45-web-products-inventory-pages` | `web` | `api` | merged | agent-issue-45 | 2026-05-26T08:18:00Z |
| #42 | `../juli-ai-issue-42` | `feat/issue-42-ios-auth-daily-loop` | `ios` | `api`, `auth` | merged | agent-issue-42 | 2026-05-26T07:20:00Z |
| #37 | `../juli-ai-issue-37` | `feat/issue-37-api-orders-products-inventory` | `api` | `data` | merged | agent-issue-37 | 2026-05-26T08:15:00Z |
| #34 | `../juli-ai-issue-34` | `feat/issue-34-livestream-scoring-anomaly` | `intelligence/scoring` | `data` | merged | agent-issue-34 | 2026-05-26T08:20:00Z |
