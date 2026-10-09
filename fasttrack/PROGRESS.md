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
| P7-A Phân tích backend: daily shop diagnosis report per shop + `/v1/demo/analysis` | 7.1, 7.2 | done (6a8e2324) | P7-A agent (Opus) |
| P7-B Quyết định backend: ADR-106 Optimize Product cards per shop | 7.3, 7.4 | done (df673ced) | P7-B agent (Opus) |
| P7-C UI restyle to index.html + Quyết định / Phân tích screens | 7.5–7.8 | done (8a857b04) | P7-C agent (Opus) |
| P7-D Deploy builds the demo lane | 7.9 | done (d76e11bf) | P7-D agent (Sonnet) |
| P7 integration: merge A–D, align UI to P7-B, funnel layout, repay P7-A lock + rate-limit debt, full test pass, check.sh | — | done (c446bb2d..HEAD; e2e: 8 restyle failures open in DEBT) | P7 integration agent (Opus) |

## P8 — the app follows the sales demo video (ADR-109)

| Task | ACs | Status | Owner |
|---|---|---|---|
| P8-A Rankings job, DB only, read on demand | 8.1 | done (merged d7e0e19f) | P8-A agent (Opus) |
| P8-B Per-video 30/30 data | 8.2 | done (merged 2abcd168) | P8-B agent (Opus) |
| P8-C Before/after + Hoàn tác, rule store, day-7 guardrail | 8.3 | done (merged 06a95d38, 078 re-chained onto 077) | P8-C agent (Opus) |
| P8-G `get_product_diagnoses` playbook tool | 8.4 | done (merged f4740ceb) | P8-G agent (Sonnet) |
| P8-D App shell + Home | 8.5 | done (merged 41584c55) | P8-D agent (Opus) |
| P8-E Phân tích UI | 8.6 | done (merged) | P8-E agent (Opus) |
| P8-F Quyết định UI | 8.7 | doing | P8-F agent (Opus) |
| P8 integration + deploy | — | todo | orchestrator |

## P2–P6

Not started. See SPEC §4. P3 no longer waits on FastMoss (D22): next after P7. P2 (FastMoss) is optional and still waits on the API trial (owner).

## Owner actions (not for agents)

- FastMoss REST API trial + 1,000-request minimum (P2, optional since D22).
- Confirm Fujiwa's TikTok authorisation allows product writes (blocks P5).
- Consent screen #2061 (launch, not this branch).
- Dependabot keeps reopening PRs because its config is read from `main`
  (frozen). Either accept periodic closes, or allow a one-line change on `main`
  setting `open-pull-requests-limit: 0`.
