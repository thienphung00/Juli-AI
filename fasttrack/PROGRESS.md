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

## P7 — Quyết định + Phân tích on the demo (D21)

| Task | ACs | Status | Owner |
|---|---|---|---|
| Sync main (ADR-106/108 code) into the branch | — | done (7c31a0a4) | orchestrator |
| P7-A Phân tích backend: daily shop diagnosis report per shop + `/v1/demo/analysis` | 7.1, 7.2 | doing | P7-A agent (Opus) |
| P7-B Quyết định backend: ADR-106 Optimize Product cards per shop | 7.3, 7.4 | doing | P7-B agent (Opus) |
| P7-C UI restyle to index.html + Quyết định / Phân tích screens | 7.5–7.8 | doing | P7-C agent (Opus) |
| P7-D Deploy builds the demo lane | 7.9 | doing | P7-D agent (Sonnet) |
| P7 integration: merge A–D, full test pass, check.sh | — | todo | orchestrator |

## P2–P6

Not started. See SPEC §4. P3 no longer waits on FastMoss (D22): next after P7. P2 (FastMoss) is optional and still waits on the API trial (owner).

## Owner actions (not for agents)

- FastMoss REST API trial + 1,000-request minimum (P2, optional since D22).
- Confirm Fujiwa's TikTok authorisation allows product writes (blocks P5).
- Consent screen #2061 (launch, not this branch).
- Dependabot keeps reopening PRs because its config is read from `main`
  (frozen). Either accept periodic closes, or allow a one-line change on `main`
  setting `open-pull-requests-limit: 0`.
