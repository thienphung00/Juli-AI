# Parallel status — Phase 2.9 HITL wiring (#472)

**Started:** 2026-07-23 · **Parent PRD:** [#395](https://github.com/thienphung00/Juli-AI/issues/395) · Meta prepares; Executor → Review

## Locked decisions

| # | Decision |
|---|----------|
| 1 | **Isolate** — wire live `cli.py` backfill path so operator can run Fujiwa budgeted runs |
| 2 | Individual PR + CI green; sync-before-merge |
| 3 | Hard failure: retry ×2, then stop |
| 4 | Waves 1–4 (#463–#471) on `origin/main` — do not re-land partitions/coverage math |
| 5 | Review may push/PR |
| 6 | **No** migrations / `packages/contracts` / Demo UI |
| 7 | Section A reads only (ProductionReadClientFactory); no Section B writes |
| 8 | CI: mocked Partner only; live Fujiwa run is operator/HITL after merge |

## Current run

| Issue | Title | Modules (exclusive) | Status | Branch | Worktree | GitHub ops |
|-------|-------|---------------------|--------|--------|----------|------------|
| #472 | HITL — wire live backfill CLI + Fujiwa run path | `analytics_backfill/cli.py` (+ thin wiring helper if needed) + unit tests + MODULE.md | **PR open** | `feature/issue-472-hitl-backfill-cli` | `.worktrees/issue-472` | [PR #483](https://github.com/thienphung00/Juli-AI/pull/483) |

Base SHA: `origin/main` @ `71ee5ec2` (includes #471 merge).

Implementation SHA: `8a9bb220` · Review artifacts SHA: `d9c8254d`

## Module ownership

| Path family | Owner |
|-------------|-------|
| `services/analytics_backfill/cli.py` (+ optional `cli_wiring.py` / `live_runner.py`) | #472 |
| Tests for live CLI dispatcher (mocked Partner) | #472 |
| `MODULE.md` operator live-run command | #472 |
| Partition runners / orchestrator / coverage / budget / repos | **Read-only** |
| Demo/UI / pricing | **Forbidden** |

## GitHub ops

| Field | Value |
|-------|-------|
| **Owner** | Review Agent (PR open; await CI green + sync-before-merge) |
| **PR** | https://github.com/thienphung00/Juli-AI/pull/483 |
| **AFK code** | Yes — wire CLI with mocked unit tests |
| **HITL live** | Operator after merge; attach coverage to #462 |

## References

- Explore wiring recipe: Composer explore (mirror `run_fujiwa_poll_cycle`)
- PRD: `docs/product/phases/phase-2.9/PRD.md`
- ADR: `docs/adr/029-phase-2.9-analytics-historical-backfill.md`
