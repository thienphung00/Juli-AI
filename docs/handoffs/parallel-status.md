# Implementation Status

In-flight worktrees. Protocol: [`_bootstrap.md`](./_bootstrap.md).

- Claim a row on `main` before the first edit.
- One in-flight writer per module path (`Writer of`).
- **One GitHub ops owner** for all remote `git`/`gh` commands (see below).
- Update `Phase` and `Last update` at each step.

| Field | Values |
|-------|--------|
| `Phase` | `focus` / `tdd-red` / `tdd-green` / `review` / `pr-open` / `merged` / `blocked` |
| `Writer of` | Modules from registry `Modules` column |
| `Reader of` | Optional read-only modules |

## GitHub ops lock

Single writer for remote GitHub operations. Implementation agents commit locally only.

| Owner | Last remote op (UTC) | Notes |
|-------|----------------------|-------|
| _(none)_ | | `push`, `gh pr create/merge/checks`, `parallel-status.md` updates on `main` |

Rules:

- Claim `Owner` before the first remote op; release when done or hand off explicitly.
- Wait **≥ 30s** after `Last remote op` before the next remote command.
- Non-ops agents: do not push or call `gh` — hand branch + PR draft to ops owner.

## In-flight

| Issue | Worktree | Branch | Writer of | Reader of | Phase | Owner | Last update |
|-------|----------|--------|-----------|-----------|-------|-------|-------------|

## Recently released

| Issue | Modules released | Released at |
|-------|------------------|-------------|
| #82 | `web/ai-chat` | 2026-05-29 |
| #81 | `web/operation` | 2026-05-29 |
| #80 | `web` | 2026-05-29 |
| #79 | `web` | 2026-05-29 |
| #43 | `api`, `alerts`, `recommendations` | 2026-05-27 |
| #35 | `intelligence/forecasting` | 2026-05-27 |
| #45 | `web` | 2026-05-26 |
| #42 | `ios` | 2026-05-26 |
| #37 | `api` | 2026-05-26 |
| #34 | `intelligence/scoring` | 2026-05-26 |

## Archive

| Issue | Worktree | Branch | Writer of | Phase | Owner | Last update |
|-------|----------|--------|-----------|-------|-------|-------------|
| #80 | `../juli-ai-issue-80` | `feat/issue-80-trends-discovery` | `web` | merged | agent-issue-80 | 2026-05-29T04:45:00Z |
| #40 | `../juli-ai-issue-40` | `feat/issue-40-alerts-zalo` | `alerts` | merged | agent-issue-40 | 2026-05-27T08:17:00Z |
| #43 | `../juli-ai-issue-43` | `feat/issue-43-api-alerts-recommendations` | `api`, `alerts`, `recommendations` | merged | agent-issue-43 | 2026-05-27T08:00:00Z |
| #35 | `../juli-ai-issue-35` | `feat/issue-35-forecasting` | `intelligence/forecasting`, `data` | merged | agent-issue-35 | 2026-05-27T13:00:00Z |
| #45 | `../juli-ai-issue-45` | `feat/issue-45-web-products-inventory-pages` | `web` | merged | agent-issue-45 | 2026-05-26T08:18:00Z |
| #42 | `../juli-ai-issue-42` | `feat/issue-42-ios-auth-daily-loop` | `ios` | merged | agent-issue-42 | 2026-05-26T07:20:00Z |
| #37 | `../juli-ai-issue-37` | `feat/issue-37-api-orders-products-inventory` | `api` | merged | agent-issue-37 | 2026-05-26T08:15:00Z |
| #34 | `../juli-ai-issue-34` | `feat/issue-34-livestream-scoring-anomaly` | `intelligence/scoring` | merged | agent-issue-34 | 2026-05-26T08:20:00Z |
| #76 | `../juli-ai-issue-76` | `feat/issue-76-mode-selection-gate` | `web` | merged | agent-issue-76 | 2026-05-29T03:30:00Z |
| #79 | `../juli-ai-issue-79` | `feat/issue-79-home-control-center-v2` | `web` | merged | agent-issue-79 | 2026-05-29T04:25:00Z |
