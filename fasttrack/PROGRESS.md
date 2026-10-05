# Progress

Status: `todo` / `doing` / `done` / `blocked`. Owner = who's on it.

## P0 — setup

| Task | ACs | Status | Owner |
|---|---|---|---|
| Cut branch + worktree | 0.1 | done | orchestrator |
| Write fasttrack/ docs | 0.2 | done | orchestrator |
| Disable edit hooks + executor-cache pre-commit gate | 0.3 | done | owner |
| `check.sh` + manual deploy workflow | 0.4, 0.5 | done (dispatch caveat) | P0 agent (Opus) |
| Close Dependabot PRs | 0.6 | done | orchestrator |

## P1 — data layer

| Task | ACs | Status | Owner |
|---|---|---|---|
| P1-A Mapper fixes (analytics breakdowns, CVR, price, category) + migration | 1.8, 1.9 | done | P1-A agent (Sonnet) |
| P1-B Bootstrap on connect, per-shop schedule, cadence split, date-range backfill, parallel calls, latency events | 1.1–1.7, 1.10, 1.12 | done | P1-B agent (Opus) |
| P1 integration: merge A + B, full test pass, check.sh | 1.11 | done | orchestrator |

## P2–P6

Not started. See SPEC §4. P2 is blocked on the FastMoss API trial (owner).

## Owner actions (not for agents)

- FastMoss REST API trial + 1,000-request minimum (blocks P2).
- Confirm Fujiwa's TikTok authorisation allows product writes (blocks P5).
- Consent screen #2061 (launch, not this branch).
- Deploy trigger: land `fasttrack-deploy.yml` on `main` once, or add a tag-push trigger (`fasttrack-deploy-*`). Blocks the first fast-track deploy.
- Dependabot keeps reopening PRs because its config is read from `main`
  (frozen). Either accept periodic closes, or allow a one-line change on `main`
  setting `open-pull-requests-limit: 0`.
