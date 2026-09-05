# Agent Workflow Execution — Implementation Plan

Status: **approved 2026-08-11**. Sequential, minimal-first implementation; one workflow end-to-end (Optimize Product, `optimize_product_2`) before rollout to the remaining 10. Update the progress tracker as phases complete.

## Locked decisions

- **D1 — Real LLM agent loop, production-grade.** Real provider calls, real user data, real external APIs. The 3 no-LLM contract tests (`tests/unit/test_rules_copy_layer_contract.py:45-51`, `tests/unit/test_recommendations.py:329-338`, `apps/dashboard/src/__tests__/test_listing_rules_engine.test.ts:159`) were originally to be lifted; **superseded by [ADR-068](../../adr/068-agent-workflow-execution-boundary.md) decision 6 — the three tests are KEPT UNCHANGED** as module-scoped determinism guarantees over the modules that retain recommendation authority, and three *new* boundary tests are added alongside them (provider-SDK import containment; agent tool handlers never import `TikTokClient`; agent-authored seller copy passes the server-side banned-pattern check). ADR-012/021/055 amended via a new ADR.
- **D2 — SSE transport** with a typed event protocol (`workflow.started/status`, `assistant.text`, `tool.started/completed`, `workflow.approval_required`, `workflow.completed/failed`), event IDs + ordering.
- **D3 — Celery worker + event relay.** Loop runs in a Celery task; events appended to a sequence-numbered event store and published on Redis pub/sub; thin SSE endpoint subscribes + replays from `Last-Event-ID`. Loop emits through an **EventSink interface** (in-process sink for tests/dev). Preserves the "HTTP handlers never execute inline" invariant.
- **D4 — Sequential, minimal-first, one workflow end-to-end.** Each phase ships only the minimal specs needed to unblock the next; revisit when required. Remaining 10 workflows onboard via Phase 13 (edge cases).
- **D5 — Conversation storage.** Recent conversation (messages, tool calls, current workflow state) in **Redis**; permanent history (conversations, messages, tool calls, workflow runs) in **Supabase/Postgres**.
- **D6 — Demo UI polish** for Optimize Product is an explicit phase.

## Progress tracker (implementation order is top-to-bottom, sequential)

| # | Phase (draft-checklist numbering kept) | Status | Gate passed |
|---|---|---|---|---|
| 1 | P0 — Execution model & lifecycle (0.1 + 0.2) | ✅ complete — [ADR-068](../../adr/068-agent-workflow-execution-boundary.md) merged (#962) | ✅ 2026-08-11 |
| 2 | P3+P4 — Tool registry + tool schemas (minimal) | ✅ implemented — [ADR-069](../../adr/069-agent-tool-registry-and-write-path.md); registry core + 6-tool Optimize Product set (#980–#984), registry×sanitizer integration (#996) | ✅ 2026-08-13 |
| 3 | P5 — TikTok sanitization (product surface only) | ✅ implemented — [ADR-070](../../adr/070-agent-safe-sanitization-contract.md); sanitize package (#990–#995), wired into the real READ handlers + golden re-pointed to the production path (#996) | ✅ 2026-08-13 |
| 4 | P11 — Model abstraction (minimal LLM service) | ✅ implemented — [ADR-071](../../adr/071-llm-service-openai-adapter.md); `LLMService`/adapter/fake (#985–#989), `FakeLLMService` proven downstream against the real registry + sanitizer (#996) | ✅ 2026-08-13 |
| 5 | P12 — Prompt architecture (system + Optimize Product) | ✅ implemented — [ADR-072](../../adr/072-agent-prompt-architecture.md); re-run wave merged to `main` (#1107, 2026-08-14) with all four status records after the [ADR-079](../../adr/079-w2-artifact-disposition.md) Option B refusal of the first attempt | ✅ 2026-08-14 (mechanical gates; human voice review #1071 open) |
| 6 | P1 — Agent execution loop (blocks + runner) | ✅ **implemented and live-verified** — [ADR-073](../../adr/073-agent-execution-loop-and-write-path-hardening.md); PRD #1115, slices #1117–#1124 merged via #1183. Read path, CONFIRM pause, resume, sandbox write, ledger and cancel all proven against the deployed host — see [Wave 3 live verification](#wave-3-live-verification-2026-08-19--2026-08-20) | ✅ 2026-08-20 |
| 7 | P-CS — Conversation & state storage (NEW) | ⏸ deferred (user, 2026-08-11) until real users exist — stand-in: `workflow_runs.state` JSONB blob behind the `ConversationStore` protocol (ADR-073 d.5) | ⬜ |
| 8 | P8 — Streaming (SSE + Celery relay) | ✅ **implemented and live-verified** — [ADR-074](../../adr/074-agent-event-streaming-and-relay.md); PRD #1116, slices #1125–#1133 merged via #1183. Live SSE, gapless duplicate-free `Last-Event-ID` reconnect, mid-run cancel, and the fail-closed `memory://` boot assertion all proven on the deployed host — see [Wave 3 live verification](#wave-3-live-verification-2026-08-19--2026-08-20) | ✅ 2026-08-20 |
| 9 | P7 — Structured output contract | ⏸ deferred (user, 2026-08-11) — scheduled **W9-B** with P15 (see the wave roadmap) — loop runs on ADR-072 prose output; wires in via `FinalResponse` block + prompt v2 bump (ADR-073 d.5) | ⬜ |
| 10 | P9+P14 — Approval, safety & security prerequisites | ✅ **implemented, W5 merged 2026-08-24** — [ADR-075](../../adr/075-agent-approval-gate-and-security-prerequisites.md) + [ADR-082](../../adr/082-agent-run-product-binding.md); eleven slices deployed on release `4cce75a7`. The confirmation endpoint no longer returns 501; approve-is-run-creation is the only path to a run; `POST /v1/demo/runs` is removed | 🟨 **2026-08-25 — observation 1 at six of seven steps; observation 2 blocked by owner decision.** Ten defects were found and fixed by walking it (#1287, #1289–#1293, #1299–#1301, #1302, #1304, #1305). Auth (ES256/JWKS), fast refresh + sandbox catalog sync, card surfacing, approve→run creation, SSE with replay and heartbeats, all three read tools via shop-aware credential routing, copy-guard-clean completion, and crash/clean-failure card recovery are all proven live. The final step — confirm → sandbox write lands — waits on **realistic sandbox product data (owner action)**, not on code. Observation 2 is recorded BLOCKED: no production write authorized; unblock chain is functional RLS → manual red-team pass → explicit owner authorization for a single production mutation → T+7 → a real `impact_readings` row. See [W5 live verification](#w5-live-verification-2026-08-24) and #1226's 2026-08-25 comments |
| 11 | P-UI — Demo UI polish + wiring (Optimize Product) (NEW) | 🟨 **W6 — a third landed, 2026-09-05.** Design grilled 2026-08-12 ([ADR-076](../../adr/076-agent-demo-execution-experience.md) + [PUI-DESIGN.md](PUI-DESIGN.md)), amended by [ADR-084](../../adr/084-agent-demo-surface-tenancy-and-replay.md). PRD [#1308](https://github.com/thienphung00/Juli-AI/issues/1308). **On `main`:** #1272 seller-facing reason codes, #1314 visual identity + motion, #1318 the run ledger, #1423 golden-scenario capture/replay (which is #1311's deliverable — that issue is stale, not open work), #1309 the executability discriminator. The wave was reconciled with `main` (#1451 → #1640) and landed (#1645). **Still unbuilt:** #1315 (in review, PR #1650), #1316, #1317, #1320, #1313, and #1321's replay journey; gate #1322 untouched. Scoped in [the remaining-slices handoff](../../handoffs/2026-09-05-w6-remaining-slices.md) | 🟨 2026-09-05 — **four of ten slices; the seller-facing surface is the part still missing.** #1320 is blocked on #1313: the demo's recommendations panel calls `/v1/demo/recommendations`, which 404s, and the real route `/v1/demo/decisions` is authenticated, so there is no session to call it with. It renders fixture content and reports success today. Note #1308 is CLOSED while nine children are open |
| 11b | P-IM — Incremental impact measurement (NEW) | ✅ implemented, gate reopened in **W4** — [ADR-077](../../adr/077-incremental-impact-measurement.md); re-run wave merged to `main` (#1113, 2026-08-14), #1040–#1045 + #1068 all with status records, after the [ADR-079](../../adr/079-w2-artifact-disposition.md) Option B refusal of the first attempt | 🟨 2026-08-21 — **reachable, still un-run.** W4 fixed all three broken reads (#1215 payload, #1216 duration, #1219 measurable set). The reading itself needs a production-shop write, because the sandbox shop has no analytics series — that is W5's gate, not a code gap |
| 11c | P-CRED — TikTok credential lifecycle / refresh-token rotation (NEW) | ✅ **W4 closed 2026-08-21** — deployed on release `14807670` and verified against the vendor: sandbox credential refreshed through the real `refresh_credential` path, `refresh_count` 0→1, expiry moved 2026-08-27→2026-08-28. Beat and lazy layers live; **reactive layer built but wired to nothing** (#1233), so a token that dies before its recorded expiry is not self-healed. `/root/refresh_credentials.py` retired. [ADR-081](../../adr/081-refresh-token-rotation.md) | ✅ 2026-08-21 — full matrix green + one real sandbox-token refresh |
| 11d | P-PROD — Production-write unlock (NEW) | ✅ **W7 slices landed; W7-bis (#1469) closed 2026-09-05.** Design [ADR-085](../../adr/085-production-write-preconditions.md). PRD [#1325](https://github.com/thienphung00/Juli-AI/issues/1325); gate [#1339](https://github.com/thienphung00/Juli-AI/issues/1339). The cutover to the non-owner RLS-bound role `juli_app` is **done and deployed** — and exposed six defects, all fixed: #1548, #1575 (alembic ran as the runtime role), #1576/#1599 (`SET LOCAL` discarded by commit), #1613 (the public demo read emptied by RLS), #1627 and #1631 (bronze append and sync-state write unscoped; #1631 also found a missing UPDATE grant → migration 055) | 🟨 2026-09-05 — **Observation 1 partially evidenced.** Bullets 2 and 3 pass: `juli_app`, `bypassrls=false`, owns 0 tables, cross-tenant reads return 0. Bullet 4 is 3 of 5 beats with **zero scoping errors** — `analytics_backfill_topup` (02:00 UTC) and `daily_impact_reader` (03:00 UTC) had not yet fired. Bullet 1's authenticated half needs an operator token. Bullet 4's wording was **amended 2026-09-05**: it named `system_scope()`, which writes no database GUC and has zero callers, making the condition unfalsifiable; the beats pass via `with_shop_scope`. Checks committed at `infra/scripts/obs1/`. **Root cause still open: [#1630](https://github.com/thienphung00/Juli-AI/issues/1630)** — a tenant scope set before a multi-minute vendor fetch does not survive it, so every per-statement scope added is a workaround until it lands |
| 12 | P10 — Observability baseline | ⬜ **W8** | ⬜ |
| 13 | P15 — E2E prototype complete (Optimize Product) | ⬜ **W9-B** (with P7), over the path W9-A realigns | ⬜ |
| 14 | P13 — Family charter, seller journeys + rollout of the remaining workflows | 🟨 **charter recorded 2026-09-03** — four families (Product, Inventory, Campaign & Promotion, Customer Service), Livestream removed, **Process Order (5) + Handle Split Package (6) promoted to design-order item 3** with sustained mega-sale volume as its non-functional requirement, and a new **Mega Sale Readiness** workflow at item 5 as its preparation companion (owner, 2026-09-03), six seller-journey reports and eight corrections, automation/monitoring NFR grades — see [P13](#14-p13--family-charter-seller-journeys-and-rollout-of-the-remaining-workflows-charter-grilled-2026-09-03-supersedes-rollout-to-remaining-10-workflows); grill in progress. Design-order items 0–1 (template hardening + the Optimize Product pricing realignment) land in **W9-A** — see [where it lands](#where-the-optimize-product-pricing-realignment-lands-2026-09-03); items 2–9 roll out in **W10** | ⬜ |
| 15 | P6 — Documentation retrieval tool (deferred, optional) | ⬜ | ⬜ |

## Wave 2 status — re-run inside the harness contract (2026-08-14)

Wave 2 was **completed twice**. The first attempt is not what merges.

### First attempt — refused, retained as reference only

`feature/agent-w2-p12-wave` and `feature/agent-w2-pim-wave` carry reviewed, working code that
never reached `main`. `meta_prepare_executor.py` was never run for any slice, and the executor
worktrees were torn down before Review, destroying the implementation artifacts. A fourth artifact
waiver was **refused** under [ADR-079](../../adr/079-w2-artifact-disposition.md) Option B, honouring
[ADR-078](../../adr/078-agent-w1-wave-artifact-waiver.md) item 6. PRs #1060 and #1061 are closed
unmerged.

**Those two branches are the reference implementation. Do not build on them and do not merge them.**

### The re-run — this is the path to `main`

| Wave | Branch | Slices | State |
| --- | --- | --- | --- |
| W2-A (P12) | `feature/agent-w2a-wave` | #1036, #1037, #1038, #1039 | **merged to `main`** — #1107, 2026-08-14; `wave_artifact_gate: PASS`, all four status records committed |
| W2-B (P-IM) | `feature/agent-w2b-wave` | #1040–#1045, #1068 | **merged to `main`** — #1113, 2026-08-14; all slices landed with records |

**Both re-run waves are on `main`. Wave 2 is closed; W3-A is unblocked.** The first-attempt
branches (`feature/agent-w2-p12-wave`, `feature/agent-w2-pim-wave`) remain as ADR-079 reference
evidence only; all other W2 slice/wave branches are content-identical to `main` and prunable.

Every landed slice went through the full contract: Meta gate returning `readyForExecutor: true`,
an executor whose worktree survived until Review had read its artifacts, an adversarial Review that
proved each test by breaking what it guards, a committed status record, and
`artifact-retention-guard` (#1064) flipping from red to green in CI. That guard is the control the
first attempt lacked — it fails a slice PR whose status record is missing or not `PASS`.

**What the re-run fixed that the first attempt shipped:**

- The GMV monoculture. Every gate family in the old #1045 suite drove one metric family, which is
  how a HIGH-severity control-pool defect survived five green gates — a count-calibrated volume
  floor compared against a rate metric, silently disabling K-nearest sibling selection for `ctr`
  and `conversion_rate`. The re-run covers all three families and pins the defect by mutation.
- `classify.py` had **no dedicated tests at all**, and its `IMAGE` and `SEO_KEYWORDS_TITLE`
  branches — the two feeding `impressions_ctr` — were never exercised. Now #1068.
- ADR-069 decision 4's **reverse** cross-validation direction did not exist: nothing checked that
  every registered tool appears in a playbook. Built in #1039, proven by registering a seventh tool.
- A proxy token ceiling that reserved less headroom than the real render cost, admitting an
  over-budget composition. Retired in #1039 in favour of measuring the composed prompt directly:
  **2,967 against the 3,000 ceiling, 33 tokens of headroom.**

### Still open after the re-run

- **#1071 — human voice review** of the Vietnamese prompt against `dictionary.md`. The one P12
  gate clause no agent can close; the mechanical gates cannot judge register.
- **#1091, #1100** — two holes in the artifact guard itself: it does not run on slice PRs targeting
  `main`, and a stale `PASS` record satisfies it on later commits.
- ADR-077's **one real end-to-end reading** from a backdated sandbox run needs W3-A's
  `workflow_runs` table and runner, which do not exist yet.

**W3-A** depends on W2-A reaching `main` for playbook↔registry cross-validation. That dependency is
**satisfied as of #1107 (2026-08-14) — W3-A is unblocked** and is the next implementation phase,
in parallel with W3-B per the [2026-08-12 handoff](../../handoffs/2026-08-12-agent-execution-implementation-handoff.md).

## Wave 3 status — kickoff (2026-08-14)

Wave 3 implements the two phases that converge everything Waves 1 and 2 built: the agent loop
that consumes blocks, prompts, tools and sanitized results (**W3-A / P1 / ADR-073**), and the
event log that makes a run watchable (**W3-B / P8 / ADR-074**).

### One wave branch, both phases — a deliberate deviation from the handoff

The [2026-08-12 handoff](../../handoffs/2026-08-12-agent-execution-implementation-handoff.md) §6
gives W3-A and W3-B separate worktrees and implies a wave branch each. They run on **one** branch,
`feature/agent-w3-wave` (manifest `wave-agent-w3`), because the two phases are not disjoint:

- both add tables to `models/models.py` with migrations chained on `033_impact_readings_table`,
  and the wave must end with exactly one Alembic head;
- W3-A's runner emits through the `EventSink` protocol **W3-B/P8-1 defines**, so on two wave
  branches the runner slice would be based on a sibling wave's branch — the shape that receives
  zero CI checks and reads as green;
- the §8 wave-close gate is a *single* observed event (ActionCard → runner → tools → sandbox
  write → `final_response`, streamed live with reconnect replay). Splitting the waves splits a
  gate that has to be watched once.

This follows the W1 precedent (#1034 landed three phases in one wave). W2's split was correct
only because P12 and P-IM genuinely shared nothing. Context isolation is preserved where it
matters: two epics with `doNotLoad` lists that exclude each other's ADR, so no executor ever
dual-loads both.

### Landing order

`#1117` (P1-1, `workflow_runs` + revision `034`) and `#1125` (P8-1, `workflow_run_events` +
the `EventSink` seam) land **sequentially, in that order** — P8-1's FK targets `workflow_runs.id`,
so it chains onto P1-1. Every other slice opens in parallel once both are in. These are the only
two slices in the wave with a fixed sequence.

| Slice | Issue | Depends on |
| --- | --- | --- |
| W3-A/P1-1 workflow_runs, ledger columns, total stop_reason mapping | #1117 | — |
| W3-B/P8-1 workflow_run_events, 8-event union, EventSink protocol | #1125 | #1117 |
| W3-A/P1-2 run-state object, ConversationStore, JSONB round-trip | #1118 | #1117 |
| W3-B/P8-2 TS event mirror + dual-language golden fixtures | #1126 | #1125 |
| W3-B/P8-3 PersistingEventSink — insert, commit, then publish | #1127 | #1125 |
| W3-B/P8-5 Celery agent_runs queue + fail-closed broker assertion | #1129 | #1125 |
| W3-A/P1-3 WorkflowRunner core loop, block dispatch, tool executor seam | #1119 | #1118, #1125 |
| W3-B/P8-4 SSE endpoint, cancel, reserved confirmations shape | #1128 | #1127 |
| W3-A/P1-4 termination policy, paused clock, checkpoint cancellation | #1120 | #1119 |
| W3-A/P1-5 idempotent mutation execution on the ToolExecution ledger | #1121 | #1119 |
| W3-B/P8-6 the five-minute reaper — worker_lost, confirmation_expired | #1130 | #1129, #1117 |
| W3-B/P8-7 integration suite against a scripted fake runner | #1131 | #1128 |
| W3-B/P8-8 fetch-streaming client helper (ui-ux, public-release) | #1132 | #1126 |
| W3-A/P1-6 basis-hash concurrency + one bounded revalidation | #1122 | #1121 |
| W3-A/P1-7 pause and resume across worker processes | #1123 | #1120 |
| W3-A/P1-8 **HITL** two live GPT-5.4 nano smokes | #1124 | all W3-A |
| W3-B/P8-9 **HITL** live gate — real Redis, browser run with reconnect | #1133 | #1131, #1124 |

### Harness registration

Both epics are registered before any executor is assigned — the control ADR-079 records as
missing from the first Wave 2 attempt. `AGT-W3A` and `AGT-W3B` route to `backend`; `AGT-W3B-UI`
splits #1132 out to `ui-ux` because it writes into `apps/demo/`, which also makes it genuinely
public-release and gives it a committed release evidence plan. `meta_prepare_executor.py`
returns `readyForExecutor: true` for #1117, #1125, #1132 and #1133.

### Conflicts found during issue authoring — recorded, not reconciled

Two live documents disagree with the merged ADRs. Both are logged in
[the authority map](../../handoffs/agent-execution-authority-map.md) and neither was silently
adapted around:

1. **Runner module shape.** ADR-073 d.1 and PLAN.md §6 both say `services/agent/runner.py` — a
   single file. The handoff §6 says `services/agent/runner/` — a package. The package form is
   what W3-A builds, because seven of its eight slices touch runner-owned logic and need disjoint
   write paths for Review to grade independently. Flagged for the Architect to ratify.
2. **P8's phase gate shape.** ADR-074 d.6 states one flat gate list; the handoff §6 splits it into
   a contracts stage and a live stage. W3-B follows the handoff's two-stage split, because the
   parallelism contract (build against pinned I5/I6 while W3-A is in flight, live gate after)
   only makes sense under it — but the ADR does not name the split, so it is recorded as a
   divergence rather than treated as settled.

## Wave 3 progress — 13 of 17 slices reviewed and recorded (2026-08-15)

Every slice below lives on its own `feature/issue-11xx-*` branch, stacked in dependency
order. **Nothing has merged to `main`** — PR #1137 (#1117) is green and open; the whole
stack waits behind it.

### Reviewed PASS with a committed status record

| Slice | Issue | Notes |
| --- | --- | --- |
| P1-1 schema + total `stop_reason` mapping | #1117 | 12 mutations; value-level mapping proven, not key-presence |
| P1-2 run-state + `ConversationStore` | #1118 | real-Postgres JSONB round-trip; 10 of 11 divergence cases identical |
| P1-3 `WorkflowRunner` core loop | #1119 | 16 mutations, 14 caught; 2 gaps closed in follow-up |
| P1-4 termination policy | #1120 | AST literal guard + a hard cap of 7 (neither 6 nor 8) |
| P1-5 idempotency ledger | #1121 | genuine two-thread race test; bounded lock wait |
| P1-6 basis-hash concurrency | #1122 | LLM-invisibility asserted at two layers, not incidental |
| P1-7 pause/resume across processes | #1123 | weakref proof that the resuming runner shares no state |
| P8-1 events table + `EventSink` | #1125 | `sequence_number` pinned non-defaultable |
| P8-2 TS mirror + dual-language goldens | #1126 | FAIL→PASS; interfaces now guarded, not just the field table |
| P8-3 `PersistingEventSink` | #1127 | cross-session visibility proof of insert-commit-then-publish |
| P8-5 Celery `agent_runs` + boot assertion | #1129 | all four broker directions mutation-tested |
| P8-6 five-minute reaper | #1130 | approval expiry proven liveness-independent |
| P8-7 integration matrix | #1131 | FAIL→PASS; CI-breaking fixture isolation caught and fixed |

### Blocked on the human owner, not on code

**#1128** (SSE endpoint) and **#1132** (fetch-streaming client) are reviewed with every
warning **fixed** and reviewer signoff given. Both sit at exactly two red gates —
`findings_acknowledged` and `owner_signoff_present` — because `ownerAck` and
`ownerSignoff` are human attestations. Every agent asked declined to forge them, including
when it was the only thing between them and a clean gate. That is the control working.

### Not started — require credentials no agent holds *(cleared 2026-08-20)*

**#1124** (two live GPT-5.4 nano smokes: `OPENAI_API_KEY`, sandbox shop) and **#1133**
(live gate: real Redis broker, VPS worker, observed browser reconnect) were written but had
never run anywhere. Both have now run against the deployed host with real credentials — see
[Wave 3 live verification](#wave-3-live-verification-2026-08-19--2026-08-20). Running them
took sixteen defect fixes; none of the sixteen was visible to the 4,028-test suite.

#1133 also inherited a requirement from #1129's review: `AGENT_WORKFLOWS_ENABLED` was wired
into no systemd unit and no `api.env.example`, so the fail-closed broker assertion could not
fire on a real deployment. A guard that cannot fire reads as protection without being any.
**Now armed and verified**: the live worker process carries `AGENT_WORKFLOWS_ENABLED=1` and
`CELERY_BROKER_URL=redis://…/1`, and importing `celery_app` in the deployed venv with the
broker unset raises the `RuntimeError` rather than booting.

### Defects found outside the wave's own scope

| Issue | What |
| --- | --- |
| #1136 | `services/agent/` unmapped in `MODULES.md` across seven merged ADRs |
| #1138 | `OrdersRepo.confirm_shipment` writes an aware datetime into a naive column — asyncpg `DataError` in production |
| #1139 | `events`↔`runner` import cycle and no depth-2 public surface; three consumers, three different workarounds |
| #1140 | `workflow.status.phase_narration` ships English where ADR-074 d.2 specifies Vietnamese |
| #1141 | `PASS_WITH_WARNINGS` is a valid ship state for validate but impossible to land past `artifact-retention-guard` |
| #1142 | Unguarded `int(last_event_id)` — a non-numeric `Last-Event-ID` returns HTTP 500 instead of degrading |
| #1143 | `phase_run_correlation` reads the previous generation's validation artifact — a read-before-write off-by-one |

### Two limitations recorded deliberately *(resolved 2026-08-20)*

The **idempotency ledger (#1121)** and **basis-hash concurrency (#1122)** were both
implemented, unit-proven, and **structurally inert on the live path**: no non-test call site
constructed `ProductToolExecutor`, and `core.py` passed no `tool_call_id`, `ledger` or
`concurrency_guard`. Fail-closed made that safe and it was the correct build order — but
"we have an idempotency ledger" and "our writes are idempotent" are different claims, as
are "we have concurrency control" and "our writes are version-checked in production".

#1145 and #1173 wired both, and the live write-path run on 2026-08-20 is what turns the
first claim into the second: a real sandbox write left one `tool_executions` row
(`status=succeeded`, `operation=update_product_price`, `outcome_json` carrying the applied
SKU price) written through the real ledger, with the real `ConcurrencyGuard` holding a
basis snapshot captured before the write. Both are now load-bearing on a path that has
actually executed. One gap the same run exposed: that ledger row records **no
`payload_json`**, which is what makes the P-IM reading unreachable (below).

### Prompt-injection attempts during the wave

Reviewers and executors encountered roughly twenty injected fake `system-reminder` blocks,
concentrated immediately after `git checkout --` reverts, falsely claiming a reverted file
had been modified "by the user or a linter" and instructing the agent to conceal it. A
variant impersonated a harness directive urging raw Bash over the Read/Edit/Write tools,
which carry read-before-write and match-ambiguity protections that `sed` does not. Every
instance was disproven with `git status --short` and `git hash-object` against
`git rev-parse HEAD:<path>`, and none were acted on. No mutation was left in any tree.

## Wave 3 live verification (2026-08-19 → 2026-08-20)

Wave 3 merged with every slice reviewed and every unit gate green. Nothing in it had ever
run. This section records what was proven on the deployed host (release `6ce2ec89`), against
the real TikTok Partner API, the real GPT-5.4 nano endpoint, the real Redis broker and the
real database — and what is still not proven.

### Proven

| Claim | Evidence |
| --- | --- |
| A read-path run executes end to end | run `16b0364c`, `completed` / `final_response`, three real tool calls (`get_product_information`, `get_seo_keywords`, `inspect_product_image`) |
| Events stream live over SSE, sequence-numbered from 1 | 8 events, `[1,2,3]` before a deliberate disconnect |
| `Last-Event-ID` reconnect is gapless and duplicate-free | reconnect at 3, `[4,5,6,7,8]` after — **GAPLESS PASS**, **DUPLICATE-FREE PASS** |
| A CONFIRM-policy write pauses for approval | `workflow.approval_required` carrying `proposed_change` and `expires_at` |
| An approved write reaches the vendor, exactly once, through the ledger | run `379d8dd5`; one `tool_executions` row, `succeeded`, `outcome_json` = the applied SKU price |
| The full write path reaches `final_response` | same run, `workflow.completed` / `final_response`; reproduced on a second consecutive run |
| Mid-run cancel stops the loop | `202` mid-flight, in-flight tool call allowed to finish (cooperative by design), terminal `status=cancelled` / `stop_reason=cancelled_by_seller` |
| The `memory://` boot assertion crashes, and is armed | `RuntimeError` on importing `celery_app` in the deployed venv with the broker unset; the live worker carries `AGENT_WORKFLOWS_ENABLED=1` and a real Redis broker |
| P-UI has its first golden scenario | `tests/fixtures/agent_live_write_smoke_event_log.json`, sanitized, written by the live smoke |

### What running it cost

Sixteen defects, every one surfaced by real credentials meeting real APIs and **none** by the
4,028-test suite. The recurring shape, named across #1195 / #1201 / #1205 / #1207 / #1212:
**two internally-consistent halves that nothing reconciled, disagreeing only in production.**
Each fix shipped the missing reconciliation — a contract test that makes the two halves meet —
not just the correction.

The clearest instance is #1212. `WorkflowRunner._tool_definitions` renders each tool as
`{name, description, input_schema}`; `openai_adapter._translate_tool` read `parameters` and
substituted an empty schema when it found nothing. **Every tool reached the model declared as
taking no arguments.** The read tools take none, so they worked; every write attempt arrived as
`{}`, and the model's own (correct) explanation that it had been given nothing to send read as
the model being too small for the job. `ToolDefinition` was `Mapping[str, Any]`, so nothing
could reconcile the two ends — and all three tests covering the translation, including the
recorded round-trip, hand-built definitions using the consumer's key. It is now a `TypedDict`.
This was the third bug of that exact shape on that seam (#1177 was `call_id` vs `tool_call_id`).

### Not proven — the remaining gaps

1. **The approval decision is not authorized by anything.** `POST /v1/demo/runs/{id}/confirmations/{tool_call_id}` returns `501` by design (ADR-074 d.5 reserves it for W4-A). The live pause/resume above was driven through `WorkflowRunner.resume` directly, so it proves the **loop's** write path, not the **product's** approval gate. No seller can approve a write today.
2. **P-IM cannot read an agent run.** Entry point: `run_daily_impact_reader(session, reference_date)` (`workers/impact_reader/pipeline.py`), scheduled as the beat task `juli_backend.daily_impact_reader`. It scans `tool_executions` where `status='succeeded'` and `tool_name IN MEASURABLE_TOOL_NAMES` — which is `frozenset({"listing.optimize_product"})`, the *old* execution layer's name. The agent ledger writes `update_product_price` / `update_product_listing`, so **no agent run is ever selected**. Even if it were, the ledger records no `payload_json`, and both `classify_mutation_kinds` and the product binding read it. Two changes are needed before ADR-077's "one real end-to-end reading" is reachable at all; a third (the sandbox shop has no analytics series) means the first honest reading will have to come from a production-shop write, not a sandbox one.
3. **The "did the job" outcome fact is never recorded.** `OPTIMIZE_PRODUCT_TERMINATION_POLICY` declares `required_steps = ("update_product_listing", "update_product_price")`, and every reference to it outside that declaration is in a test. **This is not a missing termination rule** — ADR-073 decision 2 is explicit that it must not be one: "whether it *did the job* (`required_steps` completed) is an outcome fact on the run record feeding the execution-quality metric — a `final_response` without the required mutation is honest data, not a synthetic failure." Terminating differently would contradict the design. What is missing is the *record*: `workflow_runs` has no column for the fact, and nothing computes it, so the execution-quality metric has no input. Its only consumer is the measurement layer, which is gap 2 — same seam, one slice.
4. **`workflow_runs.running_seconds_elapsed` records 0** on runs that took real wall-clock time — #1117's denormalized mirror is not being written.

### Exit-gate verdict

**W3's own gates pass.** P1's gate ("real-provider smoke run completes for Optimize Product")
and P8's gate ("browser sees live events for a real run; reconnect mid-run replays without
gaps/duplicates; cancellation stops the loop") are both met with recorded evidence, and the
`memory://` assertion that #1133 inherited is armed and fires.

**W3 is closed. It does not close P15.** None of the four gaps is W3's own contract:

- **Gap 1** is the approval gate by explicit design — ADR-074 d.5 reserves the confirmation
  decision, and the route returns `501` deliberately. No seller-initiated write can happen
  until it lands (W5 below).
- **Gaps 2, 3 and 4 are one slice, not three.** All three are the same defect: the agent's
  run and ledger records do not carry what the measurement layer needs. The reader selects a
  tool name the ledger never writes; the ledger records no `payload_json` to classify; the
  run record has nowhere to put the "did the job" fact; and `running_seconds_elapsed` is
  never written. One measurement-reconciliation slice covers all four symptoms and is the
  honest prerequisite for any of the four metrics (W4 below).

P15 ("E2E prototype complete") is not tickable until both land — see the wave roadmap.

## W5 live verification (2026-08-24)

W5's eleven slices merged to `main` as #1281 and deployed on release `4cce75a7`. **The code is live. The
gate is not passed.**

### What the deployed host proves

The Celery worker's startup banner is the evidence unit tests cannot give:

- **It booted at all** — so `assert_agent_runtime_config()`'s six checks (#1217) passed against the real
  host: `OPENAI_API_KEY`, a non-`memory://` broker, banned patterns compiling, sandbox-write guard config
  resolvable for every registered WRITE tool, `SUPABASE_JWT_SECRET` present, and the structural
  route-group backstop.
- **`transport: redis://127.0.0.1:6379/1`** — a real broker. The `memory://` assertion would have killed
  the boot.
- **`agent_runs` queue consumed**, with `run_agent_workflow` and `resume_agent_workflow` both registered.
- The reaper beat task runs clean on a 5-minute cadence.

`juli-api` reads `inactive`, which is correct: `deploy.sh` stops the durable unit after every cutover
(#1069) and traffic is served by a transient `juli-api-candidate-<port>` unit.

### Why #1226 is blocked — two causes, neither anticipated

**1. Every authenticated route returns 401.** ([#1282](https://github.com/thienphung00/Juli-AI/issues/1282))

The Supabase project issues **ES256** tokens signed with asymmetric keys
(`{"alg":"ES256","kid":"70a78d90-…"}`). `verify_supabase_jwt` calls
`pyjwt.decode(token, secret, algorithms=["HS256"], …)`, which raises `InvalidAlgorithmError` **before the
secret is consulted** — so the configured `SUPABASE_JWT_SECRET` is irrelevant and even a correct legacy
secret would fail. Confirmed live: a freshly minted, structurally valid token (`sub` matching a real
`users` row, `aud: authenticated`, ~1h remaining) is rejected by `POST /v1/action-cards/refresh`.

This blocks the seller path at **step one**, before card provisioning and before any write question.

**Two mechanisms failed to catch it, and both failed for the same reason.** #1217's check 5 asserts the
secret is *present*, not that it can verify a token the identity provider actually issues — so the process
boots green and 401s at runtime. The test suite mints its own HS256 tokens with a test secret, verifying
the code against its own assumption rather than against the identity provider's behaviour. A green suite
and a green boot are both fully compatible with a total auth outage.

The unauthenticated demo routes still return 200 throughout, which makes the outage easy to mistake for a
working system: the surface a browser hits first looks healthy while everything requiring identity is dead.

**2. The sandbox shop has nothing to approve, and the demo surface points at production.**
([#1283](https://github.com/thienphung00/Juli-AI/issues/1283))

`GET /v1/demo/decisions` is unauthenticated and resolves a **server-bound reference shop**, which on this
host is **Fujiwa Vietnam Store** — a real merchant's production shop. All four `active` cards belong to it,
including an `optimize_product_2` card. The sandbox shop `1862f13b-…` has **zero** action cards, though it
does have one product (*Authentic Stainless Steel Water Bottle 750ml*), so ADR-082's binding would resolve
unambiguously if a card existed.

Because `/decisions` ignores `X-Shop-Id` while `/approve` honours it, **the cards a caller can see are not
the cards that caller can approve.** The only walkable approval on this host targets the production shop,
which the owner's sandbox-only decision (2026-08-21) rules out.

### Observation 2 — unchanged, and still blocked

No production write was authorized. The sandbox shop has no analytics series, so a genuine DiD reading is
impossible there; RLS across the 13 tables and the manual red-team pass both remain outstanding (W7).
ADR-077's gate stays open. **No `suppressed` reading was produced and called a reading** — #1226 forbids
that by name.

### What this changes about W6 and W7

W7 has been framed as "production-write unlock: RLS, a red-team pass, the ADR-068 capability flip." The
gate shows something larger and earlier: **the seller path has never been walkable end to end on anything
but production data**, and as of this deployment it is not walkable at all. #1282 is a prerequisite for any
authenticated flow, and #1283 has to be settled before W6 builds its option picker against a surface bound
to a live merchant's rows.

### Honest summary

W5 built the approval gate and it is deployed. Whether a seller can use it is **unproven**, and the two
reasons are recorded rather than worked around. That is the outcome #1226 explicitly permits, and it is
the finding the HITL gate existed to produce — the fourth time in this wave a check passed for a reason
unrelated to its claim, and the first to reach production.

## W7 cutover and W6 landing — progress (2026-09-05)

### The W7 cutover is done, and it found six defects by being done

Moving the runtime off the table owner to `juli_app` was the whole point of W7's RLS
work, and it behaved exactly as a real cutover does: everything that had been passing on
**owner exemption rather than on permission** failed at once, one execution path at a time.

| # | What broke | Why it was invisible before |
|---|---|---|
| #1548 | — | — |
| #1575 | `alembic upgrade` ran as the runtime role | `env.py` read `DATABASE_URL`; every *other* step used `DATABASE_DIRECT_URL`, so backup and migration ran as two different roles |
| #1576/#1599 | `SET LOCAL` discarded by a mid-stage commit | the scope was set once per job, not per stage |
| #1613 | the public demo read returned zero rows | an unauthenticated route sets no tenant GUC; the owner had been exempt |
| #1627 | the bronze append was refused | the handoff assumed "shop scope enforced by caller" |
| #1631 | the sync-state write was refused, **and** `juli_app` lacked UPDATE | a cursor could advance exactly once, then fail |

**The pattern, not the list, is the finding.** These were not six unrelated bugs. Fleet-wide
work was authorised by table ownership rather than by any grant or policy, so it all lost its
authority at the same instant and surfaced one path at a time. `system_scope()` — the
mechanism the design named for this — sets a Python module global, writes **no database
GUC**, and has **zero callers**.

**#1630 is the root cause and is still open.** A tenant scope set before a multi-minute vendor
fetch does not survive it; both database URLs resolve to the Supavisor pooler and the task
held a transaction open for 23 minutes. Until it lands, every per-statement scope added by
#1627 and #1631 is a workaround, and they should be reviewed for removal afterwards rather
than left as sediment.

### A measurement worth keeping

CI runs the whole suite as `postgres` — superuser *and* table owner, which Postgres exempts
from RLS. Only 4 of 49 integration modules exercise RLS as `juli_app`. Making application
sessions run as `juli_app` was measured: it costs **one** additional failing test, not the
large churn assumed. But it would not have caught these six, because the suite does not
exercise the paths that broke. It is a **coverage** gap, not only an exemption gap.

### W6 landed a third of itself

The wave was reconciled with `main` (#1451 → #1640) and merged (#1645). Reconciling it
surfaced three semantic conflicts — one of which produced **no conflict marker at all**:
`credential_refresh_beat.py` auto-merged into main's `with_shop_scope` *plus* a `system_scope`
wrapper main had deliberately deleted, caught only by `test_system_scope_call_sites_enumerated`.

Also worth recording: squash-merging a **wave reconciliation** discards the ancestry that made
the next merge clean, so the same files re-conflict. Squash is right for issue PRs and wrong
for this.

What landed is the infrastructure — the event protocol, the replay source, the design tokens.
What is missing is the surface a seller uses: the stream hook (#1315, in review), the staged
view (#1316), and the consent picker (#1317).

## Wave 6 — sellers can watch Juli work and choose what it does (2026-08-25)

Phase 11 / P-UI. **PRD [#1308](https://github.com/thienphung00/Juli-AI/issues/1308)**;
design authority [ADR-076](../../adr/076-agent-demo-execution-experience.md) +
[`PUI-DESIGN.md`](PUI-DESIGN.md), amended by
[ADR-084](../../adr/084-agent-demo-surface-tenancy-and-replay.md).

### Why this wave and not the blockers

W7's contents — functional RLS, a manual red-team pass, the ADR-068 capability flip — are on
record as **hard blockers whose clearance is an owner decision**, and the first production
mutation additionally requires explicit per-mutation owner authorization after both clear
(#1226's 2026-08-25 observation-2 record). A wave scoped to them would be a wave whose
deliverable is somebody else's signature. W6 is the largest wholly-AFK body of remaining work,
it is write-path-disjoint from W7 (`apps/demo` + `packages/contracts` + a read-only server
surface, against security/infra/data-platform), and the roadmap already names W6 ∥ W7 as the
one real parallelism gain.

There is also a product argument. Six of seven steps of a seller-path approval are now proven
live — every one of them a `curl` typed over SSH. `apps/demo` still runs on a localStorage
mock whose recommendations fetcher points at a route that does not exist and silently falls
back to fixtures. **The event stream that took two waves to build has no consumer.**

### What the W5 gate walk changed about the plan

ADR-076 was settled 2026-08-12, before any of it had run. Four of its premises were
contradicted by reality and are corrected in ADR-084:

| ADR-076 said | Reality | ADR-084 |
| --- | --- | --- |
| Anonymous session's active shop is "structurally pinned to the reference shop" | That setting resolves to **Fujiwa Vietnam Store** — a live merchant. It is how #1283 served a real seller's recommendations unauthenticated | d.1 — a **seeded demo tenant**, idempotent, no write credential, loud failure when unset |
| Golden scenarios "replayed through the identical SSE endpoint" | No replay mechanism, no scenario format; the gate's event logs are raw files on a host | d.2 — a **capture tool** + a schema validated against the shared event union + **server-side** replay through the real handler |
| The option picker renders each option's rationale | `rationale` is `ToolSpec.description` — English tool-schema prose written for a model (#1272) | d.5 — seller-facing reason codes, Vietnamese copy, nothing internal in `workflow_run_events.payload` |
| — | `approval.py` runs Optimize Product for **every** card regardless of `workflow_key`, and the Decisions envelope hides `workflow_key`, so the client cannot tell | d.3 — a non-leaking executability discriminator + approve **refusing** unregistered playbooks |

#1283 is settled (ADR-076 carries its amendment), so the earlier note that it "must be settled
before W6 builds its option picker" is discharged.

### Two lanes, disjoint write paths

| Lane | Slices | Domain | Write paths |
| --- | --- | --- | --- |
| **W6-B — the server contract** | #1309 #1310 #1272 #1311 #1312 #1313 | backend, except #1312 (**data-platform**, the wave's only seed/schema slice) | `api/routes/demo_decisions.py` · new `api/routes` run list · `services/agent/approval.py` · `services/agent/runner/core.py` · a scenario capture/replay module · the demo seed |
| **W6-A — the interface** | #1314 #1315 #1316 #1317 #1318 #1319 #1320 #1321 | ui-ux | `apps/demo/**`, `packages/theme` (scoped layer), `packages/contracts` TS mirrors |

Five of W6-B's six slices are unblocked and open in parallel. W6-A's #1314 lands first so no
view slice invents its own tokens; the rest is a real dependency chain through the reducer.

| Slice | Issue | Depends on |
| --- | --- | --- |
| W6-B/P-UI-1 executability discriminator + approve refuses unregistered playbooks | #1309 | — |
| W6-B/P-UI-2 `GET /v1/demo/runs` polled read model | #1310 | — |
| W6-B/P-UI-3 nothing internal on the seller's stream *(adopted, filed 2026-08-21)* | #1272 | — |
| W6-B/P-UI-4 scenario capture tool + server-side replay | #1311 | — |
| W6-B/P-UI-5 the seeded demo tenant | #1312 | — |
| W6-B/P-UI-6 anonymous session scoped to that tenant | #1313 | #1312 |
| W6-A/P-UI-1 scoped tokens + motion primitives | #1314 | — |
| W6-A/P-UI-2 `useRunStream` + the pure reducer | #1315 | #1311 |
| W6-A/P-UI-3 the staged run view | #1316 | #1314, #1315 |
| W6-A/P-UI-4 the consent-grade option picker | #1317 | #1316, #1272 |
| W6-A/P-UI-5 In-Progress becomes the run ledger | #1318 | #1310, #1314 |
| W6-A/P-UI-6 dual entry + connect-shop screen | #1319 | #1313 |
| W6-A/P-UI-7 the mock layer is deleted | #1320 | #1309, #1318 |
| W6-A/P-UI-8 replay journey in CI, dictionary, MODULE.md | #1321 | #1317, #1319, #1320 |
| **W6 gate** **HITL** — a seller steers a run in a browser | #1322 | #1317, #1319, #1321 |

### Public release

`apps/demo` is a deployed lane (`demo.app-juli.com`, `infra/scripts/deploy.sh` lane order
`api → demo → landing`) with its own Playwright suite in `release.yml`. **Every W6-A slice and
several W6-B slices are public-release work and carry a release-evidence plan** (ADR-035) in
their issue body. Meta halts any Executor whose slice lacks one.

### The gate, and the one thing it inherits

#1322 mirrors #1226's two-observation shape. Observation 1 — a visitor steers a replayed run
to completion in a browser, twice, once confirming and once declining, with a forced mid-run
reconnect and **no `curl`, no SSH, no database access**. Observation 2 — one observed live-mode
run reaching a real sandbox write.

Observation 2 inherits #1226's remaining blocker verbatim: the sandbox-write seller's product
(merchant `7658096633384781588`) carries placeholder data — title "Hinh ảnh Juli Mới Nhất trên
thị trường", description `23432432`, an infographic banner for a photo — so two consecutive
clean live runs on 2026-08-25 correctly ended with a report rather than a write proposal. Until
an owner edits that listing in the sandbox Seller Center, neither #1226's step 7 nor #1322's
observation 2 can be walked. **Nothing else in W6 is blocked**, because every artifact the wave
builds — the scenario schema, the capture tool, the replay path, the reducer, the picker, the
browser suite — is exercised by a scenario the same tool captures from the real runner driven
through the scripted-fake integration path.

**Writes stay sandbox-bound for the whole wave.** The owner's sandbox-only decision of
2026-08-21 holds; no approval or write against Fujiwa Vietnam Store (`2b1da87b`).

### Explicitly not in W6

Functional RLS and the red-team pass (W7) · any production write or the first real impact
reading (W7/W8, and per-mutation owner authorization) · onboarding the remaining ten workflows
(W10) · **product-scoped action cards** — ADR-082 named them "a real W6 item"; they reach
scoring, the emission budget, the dashboard and the fixtures, so W6 *discloses* the bound
product at the product-snapshot stage instead and the change stays scheduled-but-unscheduled ·
structured output (W9) · the live merchant OAuth exchange for arbitrary shops · a multiplexed
per-shop event stream (deferred behind ADR-083 T4's own trigger) · the dashboard and iOS.

### One numbering correction landed with this wave

`082-agent-concurrency-target-nfrs.md` and `082-agent-run-product-binding.md` were both filed
as ADR-082, four days apart. The product-binding number is cited from code, migrations and the
W5 parent cache; the concurrency one from two documents. The concurrency ADR is renumbered to
**[ADR-083](../../adr/083-agent-concurrency-target-nfrs.md)**. An issue body saying "ADR-082"
was otherwise ambiguous to an executor with no way to ask.

## Wave 7 — the owner can authorize one real change, and prove it was safe (2026-08-25)

Phase 11d / P-PROD. **PRD [#1325](https://github.com/thienphung00/Juli-AI/issues/1325)**;
design authority [ADR-085](../../adr/085-production-write-preconditions.md), which amends
[ADR-061](../../adr/061-first-user-security-baseline.md) decision 1 — the RLS deferral's
own trigger has fired. **Planned in parallel with W6 and started at the same time**; W7 is
not blocked by W6's gate.

### The objection, and the answer

W6's design record states it plainly: *"A wave scoped to blockers whose clearance is an owner
decision is a wave whose deliverable is somebody else's signature."* That was correct about the
framing, and this wave is scoped the other way. **All thirteen implementation slices are AFK
engineering that stands on its own** — tenant isolation is worth having whether or not a
production write ever happens, and so is a threat model, an adversarial behaviour suite, a
cross-tenant probe, and a single-use authorization primitive. The three owner acts appear
**only** as gate observations, each with an explicit legitimate-result clause, exactly as #1226
and #1322 handle theirs.

### What the codebase actually says about the two blockers

Both are larger and differently shaped than "RLS across the 13 tables" implies. The findings,
all verified against the tree rather than inferred:

| Claim on record | What the code says |
| --- | --- |
| RLS is *deferred* | It is **absent in a way that looks present.** Ten policies across migrations 001/002/017/019/020/022/024 compare against `current_setting('app.current_user_id')`. There is **no `set_config` and no `SET LOCAL app.current_user_id` anywhere in `backend/src`** — the only `SET LOCAL`s in the tree are `lock_timeout`/`statement_timeout` in `runner/ledger.py`. The GUC has never been set |
| Adding policies would fix it | It would not. Migration `032`'s own docstring: *"it authenticates as the Supabase pooler `postgres` role"* — **the table owner**, which Postgres exempts from row policies. A correct policy would still be bypassed by the only connection that matters |
| "13 tables" | `models.py` declares **37** across five schemas; migrations 033–041 added six after ADR-061's audit. A scope expressed as a number rots exactly the way the convention did |
| RLS is expressible per table | **Five tables have no tenant column.** `workflow_run_events`, `run_confirmations`, `impact_readings`, `action_card_approvals` reach a shop only through a parent; `webhook_raw_events` has no shop lineage at all |
| The flip is "a capability grant" | There is **no artifact** representing *"the owner authorized this mutation, on this listing, once."* A path allow-list and an env var cannot express it, and an authorization living in a GitHub comment is not something a program can fail closed on |
| The impact reader is missing something | It is not. It is scheduled, computes both kinds, and maps `below_floor` → `suppressed` honestly. What is missing is knowing **before** a write whether a listing can yield a non-suppressed reading, and a read-side rule that never counts one as a reading |

### The shape of the fix

A **`juli_app` runtime role that owns nothing** becomes the role the API and workers connect
as. Policies apply because it is not the owner — no `FORCE ROW LEVEL SECURITY`, no broken
migrations, no owner exemptions to keep right forever. Tenant identity travels as `SET LOCAL
app.current_shop_id` / `app.current_user_id` applied at the unit-of-work seam, denying twice:
`missing_ok = true` so an unset GUC returns no rows, **and** a named Python error raised before
the query is issued — because SQL-side denial alone makes a missing tenant context read as
"this seller has no data." Coverage is enumerated from `pg_catalog` at test time, so a table
that lands unprotected lands failing.

Isolation becomes real at one moment: when `DATABASE_URL` names `juli_app`. That is deliberate —
the one step CI cannot derisk is also the cheapest to undo, and everything before it is AFK.
To stop the two changes being made in the wrong order, `assert_agent_runtime_config()` gains a
**seventh check**: with the production-write capability enabled, the process verifies at boot
that its own connection is not a table owner and that RLS is on for every catalog-classified
tenant table — or it refuses to start, naming the check.

### Four lanes, and where they touch W6

| Lane | Slices | Domain | Write paths |
| --- | --- | --- | --- |
| **W7-A — isolation** | #1326 #1327 #1328 #1329 #1330 | data-platform (#1327, #1330 backend) | new migrations · `database/database.py` · `workers/agent_runtime_boot.py` · `pr.yml` (appended jobs) · runbooks |
| **W7-B — the red-team harness** | #1331 #1332 #1333 #1334 | backend | `docs/security/**` · new test trees · `infra/nginx/**` |
| **W7-C — production-write machinery** | #1335 #1336 #1337 | backend | new migrations · `services/execution/**` · `integrations/tiktok/capabilities.py`, `guards.py` |
| **W7-D — measurement honesty** | #1338 | backend | impact read path · `services/impact` reuse (no reader changes) |

**Six slices are unblocked on day one** — #1326, #1331, #1332, #1334, #1335, #1338.

| Slice | Issue | Depends on |
| --- | --- | --- |
| W7-A/P-PROD-1 the `juli_app` runtime role and its grants | #1326 | — |
| W7-A/P-PROD-2 tenant identity set on every transaction, fail-closed | #1327 | #1326 |
| W7-A/P-PROD-3 RLS that denies — the ten dead policies rewritten | #1328 | #1327 |
| W7-A/P-PROD-4 the two-tenant proof, enumerated from the catalog | #1329 | #1328 |
| W7-A/P-PROD-5 the boot check that outranks the capability flip | #1330 | #1329 |
| W7-B/P-PROD-6 threat model + an inventory CI keeps honest | #1331 | — |
| W7-B/P-PROD-7 adversarial corpus asserts loop behaviour | #1332 | — |
| W7-B/P-PROD-8 generated cross-tenant probe — 404, never 403 | #1333 | #1331 |
| W7-B/P-PROD-9 abuse limits verified, including cancel's exemption | #1334 | — |
| W7-C/P-PROD-10 owner authorization becomes a single-use row | #1335 | — |
| W7-C/P-PROD-11 four preconditions with four names, default off | #1336 | #1335, #1330 |
| W7-C/P-PROD-12 no-deploy kill switch + audit of every attempt | #1337 | #1336 |
| W7-D/P-PROD-13 measurable before the write, unfabricated after | #1338 | — |
| **W7 gate** **HITL** — isolation real, surface red-teamed, one change measured | #1339 | #1330, #1332, #1333, #1334, #1336, #1337, #1338 |

### Disjointness with W6, and three declared serialization points

W6 owns `apps/demo/**`, `packages/theme`, `packages/contracts`, `api/routes/demo_decisions.py`,
the new run-list route, `services/agent/approval.py`, `services/agent/runner/core.py`, the
scenario capture/replay module, and the demo-tenant seed. W7 touches **none** of them. Three
places need coordination rather than a claim of disjointness, and each is declared on the issue
that touches it:

1. **Alembic's linear head.** W6's #1312 may add at most one migration; W7 adds several.
   Numbers are **reserved, not read from head — #1312 takes 042 if it needs one; W7 starts at
   043 and never reuses.** An unissued 042 is a gap; two waves computing `down_revision` from
   head is a branched head and an outage.
2. **`core/security/`.** W6's #1313 owns `dependencies.py` and the anonymous-session path. W7
   reads the already-resolved active shop at the unit-of-work seam and **does not edit that
   module** — declared as a lock on #1327 and #1330.
3. **CI workflow files.** Both waves add jobs. W7 **appends** jobs and never string-replaces
   into an existing `needs:` block without running the validator; duplicate `- <job>` entries
   make a replace hit the wrong job, and an empty `needs.X.result` is the silent symptom.

One more coordination note that is not a conflict: #1333's cross-tenant probe is generated from
the live route table, so it covers W6's new routes automatically when they land. W6's parent
scope already requires 404-not-403 for cross-tenant and nonexistent, so the waves agree by
construction. **If a W6 route fails the probe, that is a real defect and gets reported against
the owning W6 issue — not silenced with an exclusion.**

Likewise #1332 adds fixtures and tests only. If a case reveals a defect needing a change in
`runner/core.py` or the sanitizer, it is reported and coordinated with #1272, never fixed
across the wave boundary.

### The gate, and what it supersedes

#1339 carries four observations, each with a legitimate result that is not "success":
the role cutover on the deployed host (revert cleanly and diagnose is a pass); the manual
red-team pass (open findings is the pass working); an explicit owner authorization for a
single production mutation (declining is the default, and the standing 2026-08-21 decision
holds); and the first real impact reading at T+7.

**#1339 supersedes #1226's observation 2**, which #1226's 2026-08-25 comment recorded as
blocked by owner decision. #1226 stays open for observation 1 only — the confirm→write step,
pending realistic sandbox product data, an owner action in the sandbox Seller Center as
merchant `7658096633384781588`.

Neither this gate nor any slice may close by disabling a control, waiving a precondition, or
recording a `suppressed` reading as a reading.

### Explicitly not in W7

- **The manual red-team pass itself** and any finding it produces — gate observation 2; findings become new issues.
- **The production mutation**, and the `DATABASE_URL` cutover — gate observations 3 and 1, owner acts.
- **[ADR-050](../../adr/050-cdp-slice-3-5-c-two-gated-exits.md) C2** — the cold-start fleet engine (fleet-wide analytics top-up, OAuth→signals cold start, 7D bootstrap) is **removed from W7**: it is a many-shop onboarding engine, it is nowhere on #1226's chain, and it roughly doubles the wave. The one C2-adjacent fact that *is* on the chain — the production shop's analytics depth — is already served by the existing single-shop `analytics-backfill-topup` beat and is verified empirically by #1338. *Trigger:* a second live merchant connects, or W8's business-impact metric needs readings from more than one shop.
- **The GA per-shop credential model.** ADR-081 shipped lazy + beat refresh and #1290's binding verifier landed; per-shop scoping of `seller_connect` is an architecture, not a hardening pass. *Trigger:* the first non-owner merchant completes OAuth, or the first write credential is minted from a `seller_connect` capability.
- **Generalizing production writes beyond one allow-listed listing.** *Trigger:* observation 3 completes and a second authorization is requested.
- **A tenant column on `webhook_raw_events`** (it gets `INSERT` only). *Trigger:* a tenant-scoped surface needs to read it.
- **`gold` RLS keyed to `auth.uid()`** for client-direct reads — ADR-061's 3.5-C deferral is untouched; migration 032 revoked `anon`/`authenticated` from `public` entirely and this wave does not re-open the Data API.
- **Automated or continuous red-teaming.** *Trigger:* the manual pass finds a class the fixture suite could not have caught.
- W8's observability rollups · the remaining ten workflows (P13/W10) · `apps/demo` and everything else W6 owns.

## Wave roadmap — W4 to W10 (2026-08-20)

Every remaining phase, assigned to a wave, in the order the constraints allow. Waves are
named for the phases they implement.

### Three constraints that fix the order

1. **2026-08-27 04:30 UTC.** All three TikTok credentials expire together, and **nothing
   automatically refreshes them**: the only production refresh call site sits inside `run_fujiwa_poll_cycle`,
   which is not in the Celery beat schedule, and `sandbox_write` has no refresh call site at
   all. Everything that touches TikTok dies with them. **Verified live 2026-08-20**, not inferred:
   a dry run of the bridge script reported all three within five days of expiry with no scheduled
   refresher. P-CRED cannot move.
2. **A real impact reading requires a production write.** The sandbox shop has no analytics
   series, so ADR-077's outstanding reading cannot come from a sandbox mutation. Production
   writes have two preconditions already on record — functional RLS and a manual red-team
   pass — so P-IM's gate and P10's business-impact metric are gated on a *security* wave,
   not an engineering one.
3. **The four metrics have four different sources.** Approval rate comes from
   `run_confirmations` (W5), execution quality from the run record (W4), business impact from
   `impact_readings` (needs W7), recommendation quality from scoring signals vs observed
   outcomes. P10 cannot precede all of them.

### The waves

| Wave | Phases | Contents | Parallel with |
| --- | --- | --- | --- |
| **W4 — P-CRED + P-IM** | 11c, 11b gate | ✅ **CLOSED 2026-08-21**, deployed `14807670` · #1215 #1216 #1219 #1230 #1231 #1232 #1233 #1234 #1246 | ✅ |
| **W5 — P9+P14** | 10 | ✅ **CODE MERGED 2026-08-24**, deployed `4cce75a7` · #1214 #1217 #1218 #1221 #1222 #1224 #1225 #1181 #1223 #1269 #1274 #1140 · **gate #1226 blocked** — see [W5 live verification](#w5-live-verification-2026-08-24) | — |
| **W6 — P-UI** | 11 | 🟨 **PLANNED AND FILED 2026-08-25** · PRD #1308, ADR-084 · W6-B contract lane #1309 #1310 #1272 #1311 #1312 #1313 · W6-A interface lane #1314–#1321 · gate #1322 · rider #1077 (seller-copy TS half) — see [Wave 6](#wave-6--sellers-can-watch-juli-work-and-choose-what-it-does-2026-08-25) | **W7** |
| **W7 — P-PROD** | 11d (NEW) | 🟨 **PLANNED AND FILED 2026-08-25** · PRD #1325, ADR-085 · W7-A isolation #1326–#1330 · W7-B red-team harness #1331–#1334 · W7-C write machinery #1335–#1337 · W7-D measurement #1338 · gate #1339 — see [Wave 7](#wave-7--the-owner-can-authorize-one-real-change-and-prove-it-was-safe-2026-08-25). **ADR-050 C2 removed from this wave** and deferred with its own trigger | **W6** |
| **W8 — P10** | 12 | Logging baseline re-verification, per-run rollup, the five-link outcome chain, the four unconflated metrics · closes #1226's second half | — |
| **W9-A — template hardening + Optimize Product pricing realignment** | 14 (design-order items 0–1) | The part of P13 step 0 the realignment needs (`workflow_key`, bound subject, tool dispatcher, shared prompt sections) · seller-journey finding 1's correction: reprice through a Product Discount instead of `prices/update`, diagnostics first, title-length and listing-bundle guards, prompt v4 · HITL sandbox re-proof — see [Where the Optimize Product pricing realignment lands](#where-the-optimize-product-pricing-realignment-lands-2026-09-03) | — |
| **W9-B — P15 + P7** | 13, 9 | Hardening pass over the whole — now realigned — Optimize Product path; extract the per-workflow config template (prompt + allowlist + **output schema**) · P7 structured output contract | — |
| **W10 — P13** | 14 (design-order items 2–9) | Edge-case matrix; register the 4 unregistered tool handlers; onboard the remaining workflows via the template **in the P13 design order** (Clear Excess → **Process Order + Split Package** → Replenish FBS → **Mega Sale Readiness** → Create Hero Product → Promotion family → 8a–8c → CS responses). Item 1, the Optimize Product pricing realignment, has moved to **W9-A** | — |

### Filed work — W4 and W5

Slice titles follow the Wave 3 convention (`W<wave>-<sub-wave>/P<phase>-<n>`). A `HITL:` prefix
means the slice needs the repo owner to run something, observe something live, or make a call a
coding agent cannot; those issues carry a numbered "What you need to do" section.

| Wave | Parent PRD | Slices |
| --- | --- | --- |
| **W4-A — P-CRED** | #1228 | `W4-A/P-CRED-1..5` (ADR-081 decisions 1–9) |
| **W4-B — P-IM** | #1228 | #1215 ledger payload · #1216 running seconds · #1219 reader vocabulary · #1220 did-the-job fact |
| **W5-A — P9 approval** | #1213 | #1214 schema · #1221 decision requests · #1222 approve-is-run-creation · #1224 confirmation endpoint · #1225 decline |
| **W5-B — P14 security** | #1213 | #1217 auth + boot assertion · #1218 sanitizer + adversarial fixtures · #1223 abuse limits |
| **W5 gate** | #1213 | #1226 (HITL) — seller-path approval end to end |

**W4-B's own gate — the first real impact reading — is deliberately not in W4.** The sandbox shop
has no analytics series, so a genuine DiD reading requires a production-shop write, which is W7's
unlock. W4 makes the reading *reachable*; W7 is what makes it *possible*. Recording a `suppressed`
reading and calling the gate met would be dishonest, and the issue says so explicitly.

**W6 ∥ W7 is the one real parallelism gain.** P-UI is `apps/demo/**` and `packages/contracts`;
the production unlock is security, infra and data-platform. Zero write-path overlap, and it
saves a wave of wall-clock on the two heaviest remaining items.

### Why this order

- **P-CRED cannot move** — it is the only wave with an external clock. The measurement slices
  ride with it because they are small, backend-only, write-path-disjoint from it, and they are
  what makes execution quality measurable at all.
- **W5 before W6**: P-UI's option picker renders the decision-request structure W5 defines.
  Building the UI first means building against a guess.
- **W7 before W8**: business impact needs real readings, which need production writes. P10
  earlier produces a dashboard with one populated column.
- **P15 and P13 last**, by their own definitions — one hardens the finished path, the other
  generalises it.

### Where P7 lands, and why not W10

P7 (structured output) goes in **W9, with P15** — not W10:

- W9's deliverable *is* the per-workflow template, and P15's own minimal spec defines that
  template as "prompt + allowlist + **output schema**". Extracting it before P7 exists means
  extracting a template with an empty slot, and W10 then multiplies that hole by ten workflows.
- W10's edge-case matrix lists **"malformed LLM output"** as a case to work. Without P7 there
  is no validation, so there is nothing to be malformed against and no repair path to test.
  P7 is a prerequisite for one of W10's own matrix rows, not a peer of them.

**A stronger case exists for W6.** P7's own gate is "frontend can type against the schema",
and W6 *is* the frontend. If P-UI's completion stage renders prose now and typed output later,
that view gets built twice. Recorded here so the move is a one-line decision.

**P7 carries one correction when it is picked up.** Its deferral note says it "adds no new
vocabulary" because `output_validation_failed` was already reserved. That is no longer true:
#1210 gave that stop_reason its first real producer (the outbound banned-pattern guard), so a
`failed` run carrying it will be ambiguous between a guard hit and a validation failure. P7
must split the reason or carry a discriminator.

### Where the Optimize Product pricing realignment lands (2026-09-03)

**Decision: W9-A** — a new first sub-wave of W9, ahead of P15 and P7. It carries P13 design-order
item 1 and the part of item 0 that item 1 depends on.

**The realignment's design is [ADR-090](../../adr/090-optimize-product-realignment.md)** — seven
decisions covering the discount-only price lever, diagnosis-first step order, one lever per run,
the single-option decision request, no Repeat consent with a lapse revision, and the honest
no-change end states. Read it before `to-prd` on any W9-A slice below.

Three of this plan's own constraints pick the wave:

- **It must precede template extraction.** W9's deliverable *is* the per-workflow config template.
  Seller-journey finding 1 says `optimize_product_2` reprices through `prices/update`, which is not
  how TikTok reprices. Extracting the template from that path and then handing it to ten workflows
  in W10 multiplies one misalignment by ten — the same argument that already put P7 in W9, not W10.
- **It is not write-path-disjoint from what is in flight.** The realignment writes
  `services/agent/{playbooks,tools,prompts,runner}`; W6-B writes `services/agent/approval.py` and
  `services/agent/runner/core.py`, and W8's per-run rollup shares the `workflow_runs` migration
  chain with hardening slice T-1. One writer per tree is the rule this plan does not break.
- **Its proof is live, and live means deployed.** #1226 observation 1 is still the only end-to-end
  instrument, so a Product Discount write is only believed once it lands on the sandbox shop —
  which W6's gate (#1322) also needs deployed. Sequencing after both gates buys one sandbox walk
  instead of two.

**Alternative considered:** a new **W8.5** run in parallel with W6/W8 — rejected on the write-path
overlap above; it would have needed three declared serialization points to buy one wave of clock.

**Slices — W9-A.** Template hardening first, then the realignment, then the proof.

| # | Slice | Domain |
| --- | --- | --- |
| W9-A/T-1 | `workflow_key` on `workflow_runs`, polymorphic bound subject (nullable `product_id`), active-run index on `(shop_id, workflow_key, subject_ref)` | data-platform |
| W9-A/T-2 | domain-registered tool dispatcher replacing `ProductToolExecutor`'s literal handler dicts | backend |
| W9-A/T-3 | shared prompt sections extracted per [ADR-072](../../adr/072-agent-prompt-architecture.md) d.1; the two gate tests de-pinned from `optimize_product_2` | backend |
| W9-A/R-1 | diagnostics-first read tool — TikTok's own listing diagnostics fetched *before* `get_seo_keywords` | integrations |
| W9-A/R-2 | `create_product_discount` write tool + its sanitizer adapter under the [ADR-070](../../adr/070-agent-safe-sanitization-contract.md) contract | integrations |
| W9-A/R-3 | campaign / Flash-Deal precheck — refuse a discount that collides with an active activity or a fixed-price promo | integrations |
| W9-A/R-4 | title-length gate — ≥ 25 characters, enforced on the next edit (finding 8) | backend |
| W9-A/R-5 | listing-edit bundle guard — title, category, images and description never in one write (finding 8) | backend |
| W9-A/R-6 | prompt v4 — diagnostics-first ordering, discount vocabulary, both guards | backend |
| W9-A/R-7 | [`execution_layer.md`](../execution_layer.md) step 6 corrected from `prices/update` to the discount path | docs (fast-track lane) |
| **W9-A gate** | **HITL** — one live sandbox run reprices a real listing through a Product Discount, watched from the browser, no `curl` and no SSH | owner |

**The gate inherits #1226's blocker and adds one.** The sandbox listing still carries placeholder
data, and it now must also be **Product-Discount-capable**: a SKU whose base price a discount can
sit under, with no active campaign or flash sale on it. Owner action in the sandbox Seller Center,
not code.

**What stays out of W9-A.** The rest of design-order item 0 — step input contracts, the deadline
clock, the `waiting_external` run state and the autonomy ladder — rides with the first W10 workflow
that needs it (Inventory, then Customer Service). The realignment needs none of the four, and
pulling them forward would make W9-A a wave. W9-B is otherwise unchanged: P15's hardening pass and
P7, over the realigned path.

### Still deferred, with the trigger for picking each up

| Phase | Pick up when |
| --- | --- |
| **P-CS** (7) — conversation storage | Real users exist, or a run must survive worker restart mid-conversation. |
| **P6** (15) — documentation retrieval | Only if agent answers actually need it. No trigger yet. |

### Debt that rides along rather than getting its own wave

The harness/CI issues (#1090, #1091, #1093, #1100, #1101, #1111, #1112, #1143) touch only
`.github/` and `agent-runtime/`, so they are write-path-disjoint from every wave and can ride
with any of them. #1136 (`services/agent` unmapped in MODULES.md) and #1071 (prompt voice
review) are single-PR items.

**Backlog hygiene, outside any wave:** roughly 25 W3 issues (#1117–#1133, #1145, #1160, #1164,
#1171–#1181) are merged but still open, which makes the issue list unreadable at a glance.

## W4 orchestration contract (2026-08-20)

Derived from what W3 actually cost, not from general practice. Two failure classes were
measured across W3's issues, PRs, and every worktree's git state; each gets a mechanism here.

### What W3 cost, in numbers

**Four re-implementations.** Four worktrees hold finished work that was redone on a
differently-named branch: `feature/issue-1127-persisting-sink` (8 commits, PR #1154 closed
unmerged) → `feature/issue-1171-persisting-sink`; `feature/issue-1142-last-event-id` →
`feature/issue-1142-sse-last-event-id`; `fix/issue-1138-aware-datetime` →
`fix/issue-1138-confirm-shipment-tz`; `feature/issue-1173-runner-composition` → the same
branch with `-v2`. Twenty worktrees are still alive, seven dirty, the oldest untouched since
2026-07-21.

The cause is recorded in the [W3 meta handoff](../../handoffs/2026-08-17-w3-meta-handoff.md)
§2.2: the wave was squash-merged repeatedly while a 12-deep stack sat on top of it, so every
squash re-diverged everything behind it. Two commits were lost outright. **No sub-agent went
stale on its own — the base moved under it**, and the cheapest recovery from a base that no
longer exists is to redo the work on a fresh branch. Briefing agents harder would have
prevented none of the four.

**Sixteen post-merge fixes, six of them one defect.** The wave merged 2026-08-18 with every
slice reviewed PASS; sixteen fix PRs landed 08-18 → 08-20. Six are the same shape — two
slices agreeing on a name in prose and disagreeing in code, with both sides' unit tests green
because each tested against its own fixture:

| PR | Producer wrote | Consumer read |
| --- | --- | --- |
| #1182 (#1177) | `tool_call_id` | `call_id` |
| #1212 | `input_schema` | `parameters` — *every tool reached the model declared as taking no arguments* |
| #1190 (#1188) | `state={}` | a complete state blob |
| #1196 (#1195) | sequences from 0 | 0 means "no cursor" |
| #1194 (#1191) | no `function_call` | a `function_call` |
| #1179 (#1173) | a new constructor | the old signature |

\#1145 — the decomposition gap Meta filed against itself — is the seventh instance. The rest
were environment-only (#1205/#1207 unconsumed queue and unregistered task, #1201 the wrong
systemd unit, #1187 the vendor requiring GET) and were invisible to any test at any tier.

So most of what looked like scope creep was **deferred discovery**: gaps that could not be
found until something ran end to end, surfacing all at once on day six. Genuine silent scope
expansion happened once (handoff §2.7), and the fault was telling the owner after rather than
before.

### The wave branch stays — it was never the problem

Direct-to-`main` per slice was considered and rejected on measurement:

- The `Protect main` ruleset sets `strict_required_status_checks_policy: true`, so every merge
  to `main` forces every other open PR to update and re-run.
- `pr.yml`'s `classify-tier` keys the tier off `base_ref`: `feature/*-wave` → **issue** tier
  (path-filtered unit, lint, policy); `main` → **main** tier (full regression, E2E, security,
  deploy readiness). Nine slices PR'd to `main` is nine full main-tier regressions.

[ADR-052](../../adr/052-wave-free-merge-deferred-artifact-gate.md) removed up-to-date-with-base
on `feature/*-wave` specifically to kill this thrash. Abandoning the wave would undo the
decision that solves the problem.

**GitHub's stacked pull requests (public preview, 2026-07-30) do not help here.** The docs
state CI checks triggered by pull requests on the default branch run for all PRs in the
stack — so a stacked slice would either hit `classify-tier`'s `else` and fail as
`Unsupported CI flow`, or run full main tier. Neither path reaches the cheap issue tier,
because this repo's cost model is keyed to `base_ref`, not to rebase ergonomics. What stacks
*would* fix — automatic rebasing and auto-retarget on merge — is the recovery automation for
W3's damage, not its cause. Adopting them means rewriting `pr.yml`'s trigger and classifier
and re-deriving the artifact gate's timing: an ADR-052 amendment, its own wave, not a
mid-W4 change.

### The eight rules

1. **`feature/agent-w4-wave` is the base.** Slices PR into it at issue tier; one wave→`main`
   PR at the end.
2. **Maximum stack depth 2, against W3's 12.** Slices inside a gate are path-disjoint siblings
   cut straight from the wave, so squash-merging one re-diverges nothing — and with
   up-to-date-with-base off the wave, the others do not even rebuild. Real depth exists only
   where a dependency is real (#1219 on #1215; the P-CRED chain on #1231), and each is one
   `rebase --onto` at one known moment.
3. **The wave squash-merges to `main` exactly once, at the end.** No mid-wave wave→`main`
   merge while anything is stacked. This is the single change that prevents all four W3
   re-implementations.
4. **Contract slices land alone, before any fan-out, and the contract is a typed object.**
   W4's seams are known: P-IM's ledger `payload_json` → `classify_mutation_kinds` →
   `MEASURABLE_TOOL_NAMES` (#1215 producing, #1219 consuming); P-CRED's new
   `tiktok_credentials` columns → `credential_refresh.py` → the three deleted call sites
   (#1230 → #1231 → #1232). A shape crossing a module boundary is a TypedDict/Pydantic model,
   the fix #1212 forced on `ToolDefinition`, applied before a live run instead of after one.
5. **Cross-boundary DoD: the producer's tests call the real consumer.** Any slice changing a
   shape that crosses a module boundary adds one test exercising the actual consumer, never a
   fixture. This kills the six-defect class above at its root and is already written into
   #1215's acceptance criteria as the deliverable.
6. **Migration numbers are assigned by Meta up front, never read from head by an executor.**
   `037_required_steps_completed` is on `main` as of 2026-08-20, so **#1230 takes `038`**.
   Revision ids stay ≤32 characters — a longer id fails at upgrade time with
   `StringDataRightTruncation`, not at write time.
7. **Meta owns worktrees and branch names; redo happens in place.** One branch per issue,
   **`feature/issue-<N>-<slug>` — the `feature/` prefix is mandatory, not a convention.**
   `pr.yml`'s `policy-checks` fails an issue-tier PR outright with *"Issue-tier PRs must use
   feature/\* branches"* on any other prefix; a `fix/`-named branch cost W4 one
   closed-and-reopened PR before this was written down. Force-push if work must be redone.
   An executor never
   creates a worktree, never picks a branch name, never renames. No `-v2` branch can exist,
   which makes stale work visible instead of invisible. Teardown stays with Meta and stays
   *after* Review — removing a worktree early destroys the run's telemetry permanently.
8. **Scope protocol: file, don't widen.** When an executor finds something outside its spec:
   if its own acceptance criterion is false without the fix, fix it and say so in the PR (the
   #1235 reaper case, which was right); otherwise report it and touch nothing. **No new issue
   is filed without the owner's approval.** Anything that changes an already-reviewed slice's
   scope goes to the owner *before* the change, not after — handoff §2.7's lesson.

9. **The executor emits its own implementation artifact, before it reports done.**
   ```
   python agent-runtime/scripts/ci/generate_implementation_artifact.py \
     --issue <N> --executor-domain <domain> --phase-run-id <id assigned by Meta>
   ```
   Gate 1 ran with generic sub-agents rather than the harness's `executor-<domain>`
   phase, so this was never invoked and no telemetry existed for any slice. One missing
   file failed five validate gates each, and `artifact-retention-guard` held all three
   PRs. Meta assigns the `phaseRunId` up front — review and validation must carry the
   *same* id or `phase_run_correlation` fails, and a slice with a release evidence plan
   must also carry its `releaseEvidencePlanId`.

   **A field is populated only if the run actually observed it — and empty must itself
   be true.** `skillsLoaded`, `rulesLoaded` and `mcpsUsed` are empty when no skill, rule
   or MCP was loaded: that is the true value, not a blank to be helpfully filled. One
   reviewer filled them from `issue-context-cache`'s `harnessUtility` block, which
   records what Meta *would* route, and briefly turned the guard green on two false
   observations. The harness optimizer learns from these fields, so a plausible guess is
   worse than an honest gap.

   **But do not over-apply that.** `contextFilesLoaded` is a *blocking* gate
   (`check_implementation_artifact.py` requires a non-empty list) and empty is a FALSE
   statement — an executor that edits three files and writes a 415-line test read more
   than zero files. Both gate-2 executors read the rule above and emptied this field
   too, blocking both PRs. The test is not "am I certain?" but "did this happen?":
   nothing was loaded → empty is true; files were read → name them.

   **Validate the artifact against its schema before reporting done:**
   ```
   python agent-runtime/scripts/validate/check_implementation_schema_valid.py --issue <N>
   python agent-runtime/scripts/validate/check_implementation_artifact.py --issue <N>
   ```
   `implementation-artifact.schema.json` sets `additionalProperties: false`, so an
   invented field name fails the gate even when the content behind it is excellent.
   #1231 recorded the best evidence of the wave — the `NullPool` lock-release finding —
   under `redCommand`/`redResult`/`greenCommand`/`greenResult` with `cycle` as a
   descriptive string, and blocked its own PR. The schema wants `cycle` as an integer
   plus `failingTestEvidence` / `passingTestEvidence` / `commands[{command, exitCode,
   outputSummary}]`.

   Known trap: `phase_run_correlation` reads the *previous* generation's validation
   artifact (#1143), so `generate_validation_artifact.py` must be run twice before its
   verdict is current.

Retained from W3 because each caught a real defect: the duplicate-replay check
(`git log --oneline <wave>..<branch>`) before every merge; the tree-identity check before
rebasing; re-running an executor's tests in its own worktree with `PYTHONPATH` pinned rather
than reading its report.

### Concrete assignment — gates and lanes

Dependencies confirmed from the issue bodies, not from the roadmap: P-CRED is a genuine chain,
P-IM is not.

| Gate | Concurrency | Slices | Domain | Write paths |
| --- | --- | --- | --- | --- |
| 0 | Meta | #1235 merged; migration `038` pinned to #1230 | — | — |
| 1 | 3 | **#1215** ledger payload *(contract)* · **#1230** credential columns *(contract)* · **#1216** running seconds | backend · data-platform · backend | `runner/ledger.py`+`tool_executor.py` · `migrations/`+`models.py`+`repos.py` · `runner/core.py` |
| 2 | 2 | **#1219** impact reader (needs #1215) · **#1231** the guarded door (needs #1230) | backend · integrations | `workers/impact_reader/` · `core/security/credential_refresh.py` |
| 3 | 2 | **#1232** beat + delete call sites · **#1233** reactive auth-retry — both need #1231 only | integrations · integrations | `workers/tasks/` · `integrations/tiktok/` |
| 4 | 1 | **#1234** merchant identity from the vendor | integrations | `services/tiktok/` |

Three concurrent executors maximum, never two in one file. Gates 1→2 and 2→3 are real barriers
because they are the contract seams; inside a gate no coordination is needed at all.

**HITL checkpoints — Meta pauses and does not proceed past:** any PR ready to merge (the owner
merges every PR); any gap that would require a new issue; #1234, which lands last to keep the
credential surface still. **P-CRED-2 (#1231) carries a live credential refresh against the
vendor as its acceptance criterion** — that slice is what deletes the manual refresh bridge
script, so proving it against a real credential *is* the criterion. Meta runs it against the
sandbox credential; the production credentials stay the owner's.

## Wave 4 — CLOSED 2026-08-21, deployed and verified against the vendor

Nine slices, merged to `main` as #1248, deployed to the VPS on release `14807670`.

### What is now true that was not

**Juli refreshes its own TikTok credentials on a schedule — for the first time.**
`run_fujiwa_poll_cycle` had never appeared in `beat_schedule`; the only refresh path was the
manual action-card hook, which is why operator scripts were load-bearing.

**An agent run leaves a measurable trace.** Three independent reads were broken at once: the
ledger wrote `payload_json = '{}'`, `running_seconds_elapsed` recorded `0`, and
`MEASURABLE_TOOL_NAMES` held the *old dispatcher's* name — so the reader selected zero agent
rows, forever, silently. ADR-077's "one real end-to-end reading" was **unreachable**, not
merely un-run. It is now reachable; it still needs a production-shop write, which is W5's gate.

### The three refresh layers, and which are live

| Layer | Trigger | State |
| --- | --- | --- |
| **Beat** | `credential-refresh-beat`, `crontab(minute="*/30")`, scans `list_expiring_within(24h)` excluding `needs_reauth`, calls `refresh_credential(force=False)` | **live** |
| **Lazy** | shared helper in `credential_resolver.py`, both resolvers, `force=False`; no vendor call on a hot-path resolve because the 24h guard returns `fresh` | **live** |
| **Reactive** | `call_with_reactive_refresh` on `105002`/`401` with `force=True` | **built, wired to nothing** |

**The reactive gap is the one that matters.** It is the only layer that can self-heal a
`token_expires_at` that is *lying* — the 2026-08-18 sandbox case, where the column said
`now + 7d` and the vendor said `105002 Expired`. Beat and lazy both trust that column and would
skip a lying row identically. So today, a token that dies before its recorded expiry is not
recovered automatically. #1233 delivers and tests the wrapper (twenty concurrent callers collapse
to one vendor call); wiring it into a live request path lives in `workers`/`services`, outside
that slice's write-path lock. This is the [#1145](https://github.com/thienphung00/Juli-AI/issues/1145)
shape — component complete, wiring absent — caught during the wave rather than at the gate.

### Live verification, 2026-08-21

Sandbox credential refreshed through the real `refresh_credential` path on the deployed release:

```
outcome: refreshed
expires: 2026-08-27 04:30:03 -> 2026-08-28 02:05:02
count  : 0 -> 1     last_refreshed: 2026-08-21 02:05:02
status : active     last_error: None
```

`force=True` as a typed argument did what `FORCE_EXPIRED=1` used to do by backdating a column.
The credential was six days from expiry — outside the 24h buffer — and refreshed because the
caller asked, not because the guard was lied to. `/root/refresh_credentials.py` is retired.

`production_read` and `seller_connect` were deliberately **not** refreshed: rotating live
credentials has an inherent crash window between the vendor's response and our write, and the
beat picks them up automatically on 2026-08-26.

### The deploy gap this wave exposed

After #1248 deployed, the host ran `-Q celery,agent_runs` while the release carried
`-Q celery,agent_runs,credentials` — the beat was active and enqueueing into a queue nobody
consumed, with `NeedDaemonReload=no` so systemd reported itself current about the file it had.
Fixed manually by the owner; verified by the worker's own startup banner listing `credentials`
under `[queues]` and `juli_backend.credential_refresh_beat` under `[tasks]` — the `ExecStart`
flag alone proves only what systemd loaded, not what the process subscribed to.

**Filed as [#1250](https://github.com/thienphung00/Juli-AI/issues/1250) after reading the
script.** The cause is narrower than first recorded here, and the first wording was wrong:
`deploy.sh` **does** install unit files (`deploy.sh:225-227`, `install -m 0644` +
`daemon-reload`) — but only for **lanes**, which are exactly `api`, `demo`, `landing`. That is
the only `install -m` in the 593-line script. The Celery worker and beat are handled separately
(`deploy.sh:383-389`): `systemctl cat` checks the unit *exists*, then `systemctl restart` runs
it — from whatever is already on the host. So the API unit was never affected; only the Celery
units are, and they are restarted with stale config while the deploy reports success.

Two aggravating details found in the same read. `lane_path_filters api` covers `backend/`,
`requirements.txt` and `infra/systemd/juli-api.service`, so **the API unit is a deploy trigger
for its own lane while the Celery unit files trigger nothing** — a commit changing only
`juli-celery-worker.service` marks every lane unchanged and deploys nothing. And the API lane
ends with a real `public_check` against a live URL, whereas the Celery branch records
`record_step api celery "restarted"`, which asserts that `systemctl restart` was *called*, not
that the worker came up consuming the intended queues.

[#1205](https://github.com/thienphung00/Juli-AI/issues/1205) was diagnosed as a one-off missing
`-Q` flag and fixed by editing the unit. It is the same defect as this one, and it will recur on
every future Celery unit change until #1250 lands.
`deploy.sh` does **not** copy systemd unit files out of the release into `/etc/systemd/system/`.
After #1248 deployed, the host ran `-Q celery,agent_runs` while the release carried
`-Q celery,agent_runs,credentials` — the beat was active and enqueueing into a queue nobody
consumed, with `NeedDaemonReload=no` so systemd reported itself current. This is exactly
[#1205](https://github.com/thienphung00/Juli-AI/issues/1205)'s failure, and #1205 was treated as
a one-off `-Q` bug when it is the symptom of a missing deploy step. Fixed manually by the owner;
verified by the worker's own startup banner listing `credentials` under `[queues]` and
`juli_backend.credential_refresh_beat` under `[tasks]` — the `ExecStart` flag alone proves only
what systemd loaded, not what the process subscribed to.

**Not yet filed as an issue.** `deploy.sh` should either sync unit files or fail loudly when a
release's unit differs from the installed one; today it does neither. Whether every systemd
change in this repo shares the gap is *unverified* — it is consistent with what was observed,
but `deploy.sh` has not been read.

### Slices

| # | Lane | What |
| --- | --- | --- |
| [#1215](https://github.com/thienphung00/Juli-AI/issues/1215) | P-IM | Ledger records the mutation — `ToolExecutionRequestPayload`, fields derived from what the consumers read, not from `ToolSpec.input_model` |
| [#1216](https://github.com/thienphung00/Juli-AI/issues/1216) | P-IM | `running_seconds_elapsed` at all 8 persist sites; pause excluded structurally |
| [#1219](https://github.com/thienphung00/Juli-AI/issues/1219) | P-IM | Measurable set derived from the real WRITE registry via `composition.py` |
| [#1230](https://github.com/thienphung00/Juli-AI/issues/1230) | P-CRED | Five columns, migration `038` (number assigned, not read from head) |
| [#1231](https://github.com/thienphung00/Juli-AI/issues/1231) | P-CRED | The one guarded door; returns an outcome, never raises |
| [#1232](https://github.com/thienphung00/Juli-AI/issues/1232) | P-CRED | Beat, `credentials` queue, lazy layer, three call sites deleted |
| [#1233](https://github.com/thienphung00/Juli-AI/issues/1233) | P-CRED | Reactive retry — built, not wired |
| [#1234](https://github.com/thienphung00/Juli-AI/issues/1234) | P-CRED | Merchant IDs become configuration |
| [#1246](https://github.com/thienphung00/Juli-AI/issues/1246) | P-CRED | …and that configuration reaches the transport guards |

### Two defects only real infrastructure could find

**#1231 — `NullPool` released the advisory lock.** The first implementation took the lock through
the caller's session. Under `NullPool`, `AsyncSession.commit()` returns the connection and
`NullPool` *closes* it, so a session-level advisory lock died before the vendor call. Verified
with `pg_backend_pid()`; caught as 2 vendor calls for 2 callers. SQLite could not have surfaced
it. Review then ran the suite 8× — one vendor call across twenty concurrent callers every time,
zero leaked locks.

**#1246 — a silent cross-merchant acceptance, correcting the record.** #1245's PR body and its
review both called the `capabilities.py` gap *"fail-closed, not a silent misroute."* Half right.
Pre-fix, a client carrying Juli's **old** merchant ID was silently *accepted* by a deployment
configured for different merchants. Both directions were broken; only the loud one was
documented.

---

## Wave 4 design record — P-CRED, refresh-token rotation (2026-08-18)

Wave 4 implements phase 11c. Design settled in [ADR-081](../../adr/081-refresh-token-rotation.md),
which amends [ADR-080](../../adr/080-tiktok-credential-lifecycle.md) after re-grilling it against
the code. Read ADR-081 for the full rationale; this section is the wave's shape and landing order.

### Why the design changed between ADR-080 and ADR-081

ADR-080 was never implemented. Re-reading it against the code found six gaps; ADR-080 removes
two, is partial on two, silent on one, and **specifies a beat that would refresh nothing** — its
24h scan window feeds a function that returns early unless expiry is within `REFRESH_BUFFER`,
which is 30 minutes (`core/security/tiktok_oauth.py:34`). ADR-081 keeps ADR-080's intent and
corrects the mechanism.

The load-bearing change is the third refresh layer. `token_expires_at` is a *cache of the
vendor's opinion* and can be wrong — the sandbox row's expiry was invented by a seeding script,
so the column claimed fresh while the API answered `105002 Expired`, and the operator script had
to grow a `FORCE_EXPIRED=1` backdate to work at all. Beat and lazy both read that column and
would have skipped the row identically. Only the API response observes the truth, so the reactive
layer is not optional polish — it is the only part of the design that can self-heal.

### What this wave does not do

Refreshing 100 credentials and polling 100 shops are different problems. Production reads stay
pinned to one hardcoded merchant (`PRODUCTION_AUTH_ID`); ingest fan-out is P13's, not this wave's.
`CREDENTIALS_DATABASE_URL` (ADR-080 decision 2) is descoped — see ADR-081 decision 8.

### Slices — one executor domain each, landing in order

Slice 1 gates the rest (columns before the code that writes them). Slices 3 and 4 both consume
slice 2's `refresh_credential`, so they open in parallel once it lands.

| Slice | Domain | Content | Depends on |
| --- | --- | --- | --- |
| W4-1 migration + model + repo writes | data-platform | Alembic `037` on `036_cancel_requested_column`: `status`, `last_refreshed_at`, `last_refresh_error`, `refresh_count`, `refresh_token_expires_at`. Additive, nullable-or-defaulted, no backfill | — |
| W4-2 the one guarded door | backend | `core/security/credential_refresh.py::refresh_credential` — `RefreshOutcome` instead of raising, `force`, session-level advisory lock, re-read after acquire. `REFRESH_BUFFER` → 24h. `access_token_expires_at(None)` raises instead of synthesizing `now + 1h` | W4-1 |
| W4-3 beat + queue + lazy layer | backend | 30-min fleet scan, `credentials` queue route + worker, lazy refresh at `resolve_*_credential`, and **deleting the three direct refresh call sites** (`orchestrate.py:174`, `orchestrate.py:244`, `targeted_fetch_executor.py:253`) | W4-2 |
| W4-4 reactive auth-retry | integrations | Outbound client catches `105002`/401 → `refresh_credential(force=True)` → retry the originating call once → `needs_reauth` on refresh failure | W4-2 |
| W4-5 derive merchant identity from the vendor, delete the hardcoded table | integrations | `integrations/tiktok/merchant.py` hardcodes `PRODUCTION_AUTH_ID`/`SANDBOX_AUTH_ID` and `_KNOWN_MERCHANTS`, and `resolve_merchant_context()` maps an `open_id` to a capability off that literal table. A deployable application should establish this itself from `GET /authorization/{v}/shops` rather than shipping the operator's merchant ids in source. #1200 removed the need for hardcoded *shop* ids (its invariants are relational: distinctness + trust-on-first-use); this slice removes the remaining hardcoded *auth-id → capability* table, so a new deployment needs no code edit to onboard its merchants. Owner decision 2026-08-19: "I don't want hardcoded functionality" | #1200 |

Never dual-load `backend` + `data-platform` on one issue: W4-1 is the only schema slice, and
W4-2/W4-3 never touch the migration.

### Wave gate

The full ADR-081 decision-9 matrix, **plus one real end-to-end refresh of the live sandbox
credential** (`sandbox_write`, expiring **2026-08-27**) showing a new expiry, incremented
`refresh_count`, populated `last_refreshed_at`, and the log line present. That single observation
is the only step that proves the vendor contract rather than our belief about it, and it also
settles whether `refresh_token_expire_in` exists at all — it appears nowhere in the codebase,
fixtures, or `docs/integrations/tiktok_api/authentication.md` today, which is why
`refresh_token_expires_at` is nullable and the health signal rides on `last_refreshed_at` instead.

**The sandbox credential expires 2026-08-27 04:30 UTC.** A manual refresh (`/root/refresh_
credentials.py --dry-run` then without the flag, on the deployment host) buys 7 days from the
moment it runs — it is the bridge, not the fix, and it is what the owner ran on 2026-08-20 to
move the deadline off 2026-08-25. If the wave has not reached its gate by the current date, run
the bridge again rather than letting the credential lapse; a lapsed credential must be re-seeded
through the Partner Center sandbox OAuth exchange before the gate can run at all.

### Exit condition

`refresh_cloud_credentials.py` and its `FORCE_EXPIRED=1` flag are deleted, not archived. While
that script still exists, the wave is not done.

## Phases — minimal specs + gate to proceed

### 1. P0 — Execution model & lifecycle *(grill-with-docs target — first)*
Minimal specs:
- New ADR: agent workflow execution boundary (Client → Juli Server → LLM; LLM never touches TikTok/internal services), read/recommend/mutate classification, which operations require confirmation.
- Unified `WorkflowRunStatus` enum + documented mapping to the 4 existing vocabularies (`ExecutionStatus`, `ActionCard.status`, `DemoExecutionState`, frontend `ExecutionLifecycleStatus`). Includes failure/cancelled/timeout/waiting_approval.
- Decision recorded: lift the 3 no-LLM contract tests; replacement boundary tests specified.

Gate: ADR merged; enum + mapping reviewed; every later phase can name its states without inventing new ones.

### 2. P3+P4 — Tool registry + schemas (minimal) — *design settled in [ADR-069](../../adr/069-agent-tool-registry-and-write-path.md)*
Minimal specs (per ADR-069):
- New `services/agent/tools/` module: `ToolSpec` dataclass (name, description, Pydantic input/output models → `model_json_schema()`, read|write, auto|confirm, timeout), explicit registration, domain-grouped handlers. Legacy `runner.py` untouched.
- **Decision-point granularity** — 6 Optimize Product tools: `get_product_information`, `get_seo_keywords` (steps 2+3 bundled), `upload_product_image`, `update_product_listing` (CONFIRM), `update_product_price` (CONFIRM), `check_product_status` (webhook #5 closes post-run via `WorkflowOutcomeRecord`).
- Writes execute in-run with a `ToolExecution` row per write (shared persistence helper with the legacy dispatcher); outbound `RateLimiter` attaches at the tool executor. Revisit trigger documented for nested-enqueue upgrade at heavier write volume.
- Allowlists live in playbooks; import-time contract tests cross-validate playbook↔registry both directions. Also flag (don't yet fix) the 4 unregistered legacy tools (`fulfillment.process_order`, `returns.prevent_*`).

Gate: LLM-consumable JSON schemas render for the 6-tool Optimize Product set; playbook↔registry contract test green.

**Implemented (#980–#984, W1-A; integration #996, W1 close).** `ToolSpec`/`ToolRegistry`
(#980) and the 6 Optimize Product tools across `product.py` (READ, #981) and
`product_write.py` (WRITE, #982) shipped exactly as specced — no collapsing, no
splitting. Playbook↔registry cross-validation is **not yet implemented**: P12 (the
playbook) is a later wave (W2-A) and does not exist yet, so there is nothing to
cross-validate against yet — this is not a gap, it is sequencing (P12 depends on W1-A
per the implementation handoff's parallel order). The 4 unregistered legacy tools
(`fulfillment.process_order`, `returns.prevent_*`) remain flagged, not fixed, per
ADR-069's explicit scope. #996 (W1 close) proved the registry composes with the
sanitizer (I2×I3) and with `FakeLLMService` (I1×I2×I3) via two new integration test
suites (`tests/integration/test_agent_registry_sanitizer_integration.py`,
`tests/integration/test_agent_llm_registry_sanitizer_composition.py`), both dispatching
against the real `ToolRegistry`/handlers, not fixtures.

### 3. P5 — Sanitization (product surface only) — *design settled in [ADR-070](../../adr/070-agent-safe-sanitization-contract.md)*
Minimal specs (per ADR-070):
- Context-bound IDs: executor injects `product_id` from run context; no ID params in Optimize Product schemas; opaque-ref extension reserved for future mid-run selection steps.
- Hard caps + signaled truncation (~2k tokens/result, top-20 lists, ~1.5k-char free text, `{truncated, omitted_count}`); deterministic server-side shaping only (GPT-5.4 nano context).
- Source-role provenance envelopes: `juli` (implicit), `vendor` (data never instructions), `seller` (preference within policy); no buyer role; one rule per source in the system prompt.
- Machine values: ISO-8601 UTC dates, numeric + `currency` field, numeric rates, English keys; display formatting stays in the copy layer.
- Errors: `{category, message, retryable}` reusing `ExecutionErrorCategory` + curated retryable allowlist; one in-loop retry then honest `failed`.
- Fail-closed banned-pattern guard at two chokepoints; pattern list extracted to `packages/contracts/seller-copy-banned-patterns.json` (TS + Python consumers, dual-dialect compile contract test).
- Flagged for the ActionCard layer (not P5): multi-product Optimize Product — stacked top-3 card vs N-card cap; `action_cards` unique `(shop_id, workflow_key)` blocks the cap option without a migration.

Gate: golden-file test — raw sandbox product response in, agent-safe result out, zero banned identifiers via the shared JSON pattern source.

**Implemented (#990–#995, W1-C; wired into production + golden re-pointed, #996 W1
close).** The sanitize package (provenance envelopes, machine values, caps, error
translation, the two fail-closed banned-pattern chokepoints) shipped against recorded
fixtures in W1-C, but as flagged by Meta during W1 verification (issue #996's comment
thread — a genuine integration gap, not a design defect): `product.py`'s READ handlers
still returned raw vendor-shaped output (epoch ints, bare strings) after W1-C landed,
and the golden gate (#995) exercised a **test-local** transform rather than the shipped
tool path. #996 closed that gap:
- All three READ handlers (`get_product_information`, `get_seo_keywords`,
  `check_product_status`) now build their `output_model`s through the sanitize
  package — `VendorText`/`to_json_safe` for free text, `iso_utc_timestamp` for
  `create_time`/`update_time`, `Money` for SKU prices, `cap_list`/`cap_text`/
  `sanitize_images` for every list/text/image field. `get_product_information`'s
  output model grew `description`, `sku_count`, `total_inventory_quantity`,
  `sku_prices`, and `images` — the shape the golden gate always intended, now real.
  `check_product_status`'s single `status` field needed no internal shaping (it is a
  plain machine value, not free text/timestamp/list) — decided in-slice, not deferred.
- **Design decision:** the inbound chokepoint (`guard_inbound_tool_result`, decision
  6(a)) is applied at the **dispatch boundary**, not inside each handler — a handler
  produces ADR-070-shaped `output_model`s (decisions 1–4); the chokepoint brackets
  *any* tool's result once, regardless of how much shaping that tool's own handler
  did, exactly as it will when `WorkflowRunner` (W3-A) becomes the real dispatcher.
  `tests/integration/agent_tool_dispatch.py` is a test-only stand-in for that
  boundary — not a preview of the runner's design.
- `tests/unit/test_agent_sanitize_golden.py` now calls the real
  `handle_get_product_information` handler (via a stub `ProductionReadResources`
  standing in for the marketplace transport only) instead of its own
  `sanitize_product_detail_response` reimplementation; both golden `.golden.json`
  expectation files were regenerated — the only diff is field order (now the
  `output_model`'s declared order) and the addition of `create_time` (which the
  recorded fixture has no raw value for, so it serializes as `null`). Both fixture
  provenance blocks (`recorded/`, `synthetic/`) are unchanged and unmoved.
- `product_write.py` was reviewed and left unchanged: its outputs already satisfy
  ADR-070 decision 1 structurally (no identifier field, no raw vendor SKU id/asset
  URI — enforced since #982), and carry no vendor-sourced free text, timestamp, or
  money value to shape (they echo agent-authored input, not marketplace data).
  **Flagged, not silently worked around:** `ProductSkuPrice.amount: str` (shared by
  `update_product_price`'s input *and* output) is a formatted-looking string, not
  `Money`'s numeric-amount-plus-currency shape — decision 4 read literally would
  reach this field too. Changing it touches the WRITE input schema the LLM populates
  (a bigger, CONFIRM-write-adjacent design question), which is out of #996's
  explicit acceptance criteria; reported here for the Architect rather than changed
  in-slice.

Gate now demonstrably met on the production path, not just the sanitize package in
isolation: `tests/unit/test_agent_sanitize_golden.py` (recorded + synthetic, both
re-pointed), `tests/integration/test_agent_registry_sanitizer_integration.py` (all
three READ capabilities from the real registry), and
`tests/integration/test_agent_llm_registry_sanitizer_composition.py` (I1×I2×I3) are
all green.

### 4. P11 — Model abstraction (minimal)
Minimal specs:
- `LLMService` (messages, system, tools, usage) with one provider — **OpenAI, base model GPT-5.4 nano** (decided 2026-08-11) — + config surface (model, max_tokens, temperature, API key via ADR-030 pattern). No fallback chains yet.
- Replace/retire the dead `LlmGenerator` seam (`ai/recommendations/engine.py:49`); lift no-LLM tests per P0 decision.

Gate: one real tool-calling round-trip against the provider passes an integration test (recorded-replay for CI).

**Implemented (#985–#989, W1-B; downstream composition proven, #996 W1 close).** The
block vocabulary + `LLMService` protocol (#985), the stateless `OpenAIResponsesAdapter`
over `httpx` — no `openai` package import anywhere, since it is not a declared
dependency (#986) — `FakeLLMService` (#987), the AST containment test guarding no
provider SDK import outside the adapter (#988), and the recorded-replay harness plus
one real GPT-5.4 nano round-trip fixture (#989) all shipped as specced. The dead
`LlmGenerator` seam retirement and the no-LLM test lift were superseded by ADR-068
decision 6 (recorded in PLAN.md D1 above) before this phase started — not this phase's
job. #996 (W1 close) added the acceptance-criterion-2 gate the implementation handoff
§8 named: `FakeLLMService` scripted to propose a tool call, dispatched against the real
ADR-069 registry, with the result run through the real ADR-070 sanitizer
(`tests/integration/test_agent_llm_registry_sanitizer_composition.py`) — proving I1×I2×I3
compose before `WorkflowRunner` (W3-A) depends on all three simultaneously.

### 5. P12 — Prompt architecture (minimal) — *design grilled 2026-08-11, [ADR-072](../../adr/072-agent-prompt-architecture.md)*
Settled specs (Optimize Product only; eval-pipeline-ready by design):
- **Monolithic workflow prompt** `services/agent/prompts/optimize_product/v1.md` — eight sections: role, mandate & limits, source-role rules, input-signals guidance (summarize from the `juli` context payload, never invent metrics), playbook slot, recommend-within-scope (HOW-level only), output guidance + one worked example, prohibited behaviors. Run data arrives as the `juli`-source context message, never spliced into prompt text. Extraction trigger recorded: shared sections extracted when workflow #2's prompt lands.
- **Typed `Playbook` artifact** `services/agent/playbooks/optimize_product.py` (frozen dataclass: steps → intent, tools, policy) feeding ADR-069 cross-validation, the run allowlist, and the prompt's single `{playbook}` slot via deterministic `compose(workflow_key, version)` — later the eval-harness entry point. Playbook = safety surface (never eval-mutated); prose file = entire tuning surface.
- **Language:** English instructions; Vietnamese seller-facing output ("bạn" form) with an embedded mini-glossary of canonical `dictionary.md` terms (`_Avoid_` aliases forbidden); worked example in dictionary-compliant Vietnamese mirroring `copy_layer.py`'s register.
- **Versioning:** immutable released versions (edits → `vN+1`); runs record `prompt_version` + `prompt_sha256` (P-CS columns); production pin is a code constant. Output-contract section tightens to P7's schema via an explicit v2 bump.
- **Safety sections:** 3 source-role rules + 7 prohibitions (behavioral; ADR-070 guards remain load-bearing).
- **Budget:** composed prompt ≤ 3,000 tokens (tiktoken-asserted); `juli` payload targets ≤ 1,000.

Gate: four import-time tests green (snapshot, budget, playbook consistency, mechanical banned-pattern/`_Avoid_` check) + human voice review against `dictionary.md`/design-context + P-CS fields specified.


**Implemented and merged to `main`** (re-run wave `feature/agent-w2a-wave`, #1036–#1039, landed
via #1107 on 2026-08-14; the first attempt on `feature/agent-w2-p12-wave` was refused under
[ADR-079](../../adr/079-w2-artifact-disposition.md) and is retained as reference evidence only).
The monolithic prompt, typed `Playbook`, deterministic `compose()`, direct composed-prompt token
measurement (2,967 against the 3,000 ceiling) and `optimize_product_2` criteria key all shipped
as specced, plus the reverse registry→playbook cross-validation (#1039). Open: human voice review
of the Vietnamese prompt (#1071) — the one gate clause no agent can close. **W3-A is unblocked.**

### 6. P1 — Agent execution loop (minimal) — *design grilled 2026-08-11, [ADR-073](../../adr/073-agent-execution-loop-and-write-path-hardening.md)*
Settled specs (includes the 2026-08-11 write-path hardening fixes — idempotency, concurrency, termination policy — as production-write-unlock prerequisites):
- **`WorkflowRunner`** class (`services/agent/runner.py`) owning status transitions, conversation append, block dispatch, and termination-policy evaluation; injected protocols: `LLMService`, `ToolExecutor`, `EventSink`, `ConversationStore`. Run state serialized to a `workflow_runs.state` JSONB blob per iteration and on pause — CONFIRM resume works across worker processes. Celery task (P8) is a thin shell.
- **`TerminationPolicy` on the `Playbook`** (Optimize Product v1: `max_iterations=6`, `max_extensions=1` (+2 → hard cap 8, model-proposed `continue` auto-granted with a visible event), `wall_clock_timeout_s=300` running-time-only (clock pauses during `waiting_approval`), `approval_timeout_h=4` → `cancelled`/`confirmation_expired`, `required_steps`). Every exit records one **`stop_reason`** with a total, test-asserted mapping to `WorkflowRunStatus`. Cancellation is checkpoint-based, never interrupting an in-flight write.
- **Idempotency (fix 4):** `ToolExecution` promoted to mutation ledger — unique `(workflow_run_id, tool_call_id, operation)`, claim-then-execute, stored sanitized result replayed on retry, verify-then-decide crash-window reconciliation; non-verifiable ops fail closed.
- **Concurrency (fix 5):** basis snapshot (SHA of mutable fields at read time) + compare-before-write (fail-closed, pre-signing) + one bounded revalidation (conflict fed back to the LLM with fresh values; second conflict → `concurrency_conflict`) + partial unique index: one active run per `(shop_id, product_id)`.
- **Deferral seams:** P-CS → run-state blob behind `ConversationStore`; P7 → prose output now, machine schema attaches at `FinalResponse` + prompt v2 bump.

Gate: fake-`LLMService` scenario per `stop_reason` + total-mapping test + idempotency/race tests + pause/resume round-trip + self-correction all green; two `live` smokes complete — (a) read-only run reaching `final_response`, (b) full write-path run (CONFIRM, ledger, compare-before-write) against the sandbox shop; `stop_reason` + `state` columns on `workflow_runs`.

### 7. P-CS — Conversation & state storage — *⏸ deferred (user, 2026-08-11)*
Deferred until real users exist: chat storage (conversations/messages tables, Redis hot window) is only needed when there are users whose history must persist. **Deferral principle:** the loop must function without P-CS and wire to it cleanly later. Stand-in (owned by P1, ADR-073 d.5): a `workflow_runs.state` JSONB blob behind the `ConversationStore` protocol — written per iteration and on pause, reloaded on resume; P-CS later swaps the store implementation (Redis hot + Postgres permanent as originally specced below), not the runner.

Original minimal specs (unchanged, for when the phase is picked up):
- **Redis (hot)**: recent conversation window (messages, tool calls) + current workflow run state, keyed by run/conversation ID, with TTL; the loop reads/writes this — process-restart-safe.
- **Supabase/Postgres (permanent)**: migrations for `conversations`, `messages`, `tool_calls`, `workflow_runs`; append-on-event writes from the loop; JSON/JSONB payloads.
- Clear write path: Redis is the working set, Postgres is the durable record (write-through on each loop step).

Gate: kill-and-resume test — restart mid-run, state reconstructed from Redis; full history queryable from Postgres after completion. (P1's pause/resume round-trip test covers the blob stand-in.)

### 8. P8 — Streaming (minimal) — *design grilled 2026-08-12, [ADR-074](../../adr/074-agent-event-streaming-and-relay.md)*
Settled specs (event record per user fix 2, 2026-08-11):
- **Canonical event record** `{workflow_run_id, sequence_number, event_type, timestamp, payload, v: 1}` in `workflow_run_events`; **Postgres = replay authority, Redis pub/sub = best-effort delivery**. Sequence numbers minted by the `WorkflowRunner` (counter in the run-state blob; single writer per run); unique `(run_id, seq)` index makes crash-replays no-ops.
- **8-event union** (D2 names; `workflow.failed` covers `failed`/`cancelled`/`timed_out` with `stop_reason` precision; `assistant.text.delta` reserved) — Pydantic source + mirrored TS discriminated union in `packages/contracts`, kept honest by golden fixtures tested in both languages.
- **`PersistingEventSink`**: INSERT + commit, then publish to `run_events:{run_id}` (publish failure logged + swallowed). **SSE endpoint**: subscribe-before-replay, server-side seq dedupe (clients never dedupe), 15s heartbeats, terminal-close, late-joiner replay, 2s Postgres-polling fallback if Redis is down.
- **Celery**: real Redis broker in agent deployments (fail-closed boot assertion; `memory://` stays the test default); dedicated `agent_runs` queue; `run_agent_workflow` + `resume_agent_workflow` tasks with `acks_late` + one blob-resume retry; **5-min reaper** closes stale runs (`worker_lost`, additive ADR-073 member) and expired approvals (`confirmation_expired`, enforcing the 4h policy).
- **Endpoints**: `GET /v1/demo/runs/{id}/events`, `POST /v1/demo/runs/{id}/cancel` (202, idempotent), reserved `POST …/confirmations/{tool_call_id}` for P9; tenant scoping via `get_active_shop`, cross-tenant 404. Client consumes SSE via **fetch + ReadableStream** (bearer auth in headers, owned reconnect, inspectable errors) — provider-agnostic by construction (the stream is Juli's protocol, not the LLM's).

Gate: sink-ordering + reaper units, dual-language fixtures, exact-replay / handoff-overlap / Redis-loss / lifecycle / crash-resume integration tests all green; one observed browser E2E (live run + offline-toggle reconnect); boot assertion verified.

### 9. P7 — Structured output contract — *⏸ deferred (user, 2026-08-11)*
Deferred under the same principle: the workflow functions without it and wires to it later. Stand-in: ADR-072's prose output guidance (final response = Vietnamese seller summary + actions list, shaped by the worked example). Wiring seam (ADR-073 d.5): the machine schema attaches at the `FinalResponse` block, the prompt's output section tightens via an explicit v2 bump (ADR-072 d.5), and `stop_reason: output_validation_failed` is already reserved in the enum.

Original minimal specs (unchanged, for when the phase is picked up):
- Optimize Product output schema (summary/findings/recommendations/actions/requires_confirmation) in `packages/contracts` + Pydantic; validate final LLM output; one repair retry; rules-template fallback (extend `CopySource` literal at `services/scoring/types.py:132`).

Gate: malformed-output test falls back cleanly; frontend can type against the schema.

### 10. P9+P14 — Approval, safety & security prerequisites — *design grilled 2026-08-12, [ADR-075](../../adr/075-agent-approval-gate-and-security-prerequisites.md)*
Settled specs (baseline re-verified: JWT already fail-closed via `require_env` #902; `/docs` production-gated — both now verification tests):
- **Approval gate:** approve *is* run creation — one atomic transaction (verify card `active` + tenant → flip → insert run + audit row → one-run-per-product check → enqueue); no `approval_id` parameter on the agent path; raced double-approve yields exactly one run. Legacy `/v1/executions` hardened separately with server-side verification.
- **Decision requests (user directive):** CONFIRM generalized to 1..N reasoned options (e.g. three price moves with rationale) — plan-mode style; additive `options[]` on `workflow.approval_required`; endpoint takes `{decision: approve, option_id}` or `decline`; per-option `params_sha` consent binding (only the shown, selected option may execute); single-use row; decline → model wraps up honestly → `completed`/`confirmation_declined`. `run_confirmations` is the consent audit + approval-rate metric source. Free-form mid-run Q&A deferred with P-CS.
- **Authenticated demo (user choice):** all agent run routes require Supabase JWT (`get_current_user` + `get_active_shop`); the demo is a real account whose active shop is the reference shop — one router, one resolution. **P-UI inherits a Supabase sign-in requirement + option-picker confirmation UI.**
- **Boot assertion** `assert_agent_runtime_config()`: OPENAI_API_KEY; real broker; banned-patterns compiles; sandbox guard config per WRITE tool; SUPABASE_JWT_SECRET (unconditional); production-write capability ⇒ zero unauthenticated route groups.
- **Inbound limits** (Redis token bucket inward, per shop, config-driven, 429 + security event): runs 5/hr burst 2; confirmations 30/hr; 10 concurrent SSE streams; **cancel never throttled**.
- **Injection posture:** six layers assembled (structural / provenance / content shape / output / consent / blast radius) + invisible-Unicode & bidi stripping in the sanitizer + an adversarial fixture suite as the permanent regression net. **RLS deferred** as a hard precondition on the production-write-unlock list (no multi-tenant production with real seller data before functional RLS).

Gate: approval-gate suite (incl. raced double-approve + atomicity fault injection), full confirmation ladder + hash-mismatch hard-fail, 401s on every route incl. SSE, six-check boot matrix, 429 + security events with cancel unthrottled, adversarial fixtures green; manual red-team pass — "run without approval" and "unshown mutation" both demonstrably impossible.

### 11. P-UI — Demo UI polish + wiring, Optimize Product only — *design grilled 2026-08-12, [ADR-076](../../adr/076-agent-demo-execution-experience.md) + [PUI-DESIGN.md](PUI-DESIGN.md)*
Settled specs (redesign mandate: structure + theme tokens lifted for these surfaces; motion first-class; dictionary copy, other workflows, a11y binding):
- **Dual entry:** "Dùng thử Demo" → Supabase anonymous session (real JWT — ADR-075 intact; per-session rate buckets; shop pinned to reference shop) vs "Đăng nhập với Google" → Supabase Auth → TikTok OAuth connect-shop screen (live merchant exchange = flagged follow-up).
- **Recorded-replay demo + live flag:** golden scenarios (real sandbox runs, one continuation per decision option) replayed through the identical SSE endpoint — recorded-delta pacing, rebased timestamps, typewriter, interactive decision request; live mode behind config.
- **Staged run view:** dedicated page, six playbook-derived stages, top stepper + full canvas, back-to-frozen / forward-to-live-edge / future-locked; finished runs reopen frozen (replay-powered history).
- **Consent-grade option picker** (Đề xuất stage): side-by-side cards with before→after diffs on real listing elements, two-step select-then-confirm, quiet first-class decline, 4h expiry, staggered arrival motion.
- **In-Progress = run ledger:** Đang chờ bạn (pinned, countdown) / Đang chạy (breathing cards) / Hoàn tất (honest distinct terminal states); no retry-in-place.
- **Client:** `useRunStream` + pure event→stage reducer on golden fixtures (replay ≡ live by construction); localStorage mock deleted, `fetchRecommendations` path bug fixed, silent fallback removed; stream-error ≠ run-error reconnect UX.

Gate: replay-based Playwright E2E green in CI (Try Demo → approve → stages → pick option → completion) + one observed live-mode run end-to-end + `dictionary.md` entries landed + `apps/demo/MODULE.md` invariant updated + PUI-DESIGN.md published + zero regressions on the other 10 workflows.

### 11b. P-IM — Incremental impact measurement (NEW) — *design grilled 2026-08-12, [ADR-077](../../adr/077-incremental-impact-measurement.md)*
Settled specs (adopted from research — DiD/CausalImpact-lite lineage, no invented statistics):
- **Funnel-first metric mapping:** SEO/title→`impressions`+`ctr`, description→`conversion_rate`, image→`ctr`, price→`gmv`/orders; per-mutation readings + run-level rollup on `expected_impact.metric` (SEO and description separately quantifiable).
- **Formula:** ratio-form DiD — `expected = pre(14d) × control_growth`; `incremental = post − expected`; preliminary reading at T+7, final at T+14; day T excluded; `confounded` marking for second runs in-window; zero-guards.
- **Controls:** top-5 correlation-ranked sibling products (equal weights, min 3, mean r ≥ 0.2), Juli-touched products disqualified; fallback plain pre/post capped Thấp; control provenance stored per reading.
- **Confidence:** per-metric volume floors with a designed suppressed state; Cao/Trung bình/Thấp from volume + pre-period noise band (labeled heuristic; `tfcausalimpact` = upgrade path); "ước tính" hedging, negative impact shown honestly.
- **Compute/storage:** daily impact-reader beat task (post-backfill) → `impact_readings` table (queryable source of truth, idempotent) → fills the legacy outcome envelope (preliminary→weekly, final→monthly); `WORKFLOW_OUTCOME_SUCCESS_CRITERIA` gains `optimize_product_2`; UI shows "Đang theo dõi" → reading + tier.
- **A/B seam (user requirement):** future LLM-output experiments reuse `prompt_sha256` as treatment label + `impact_readings` grouped by version as the dependent variable + `run_confirmations` selections as early quality signal; new work = randomized assignment at `compose()` + proper two-sample inference.

Gate: synthetic-uplift recovery + shock-cancellation + placebo battery + suppression matrix + reader idempotency green on real-shaped fixtures; one real end-to-end reading (backdated sandbox run); criteria entry present; reading visible in the demo UI; business-impact metric computable from `impact_readings`.

Flagged data-dependency gaps (verified against code + live DB, 2026-08-12 — address now or before multi-shop rollout):
- **Per-shop analytics topup.** The daily `analytics-backfill-topup` beat task is hardcoded to `DEMO_REFERENCE_SHOP_ID`; every other shop's `analytics_performance_intervals` only refreshes on manual `POST /action-cards/refresh`. The impact reader needs complete daily rows for T−14…T+14 for the treated product **and** ≥3 sibling controls — without per-connected-shop daily topup, real-merchant readings land `suppressed` (missing data), not computed. Prototype (reference shop) is unaffected.
- **Cold start: OAuth → signals never fires today.** The TikTok OAuth callback only provisions `shops` + `tiktok_credentials`; no sync is triggered, and both `run_fujiwa_poll_cycle` and the backfill auto-topup are capability-gated to the single Fujiwa `PRODUCTION_READ` credential (new self-serve shops get `SELLER_CONNECT` and are rejected/skipped). ADR-050 explicitly deferred this as the C2 cold-start engine.
- **Adopted quick path — 7D bootstrap, not full-shop ETL (user directive 2026-08-12):** on connect, run (a) a 7-day `analytics_backfill` window — 4 buckets × 7 days = 28 partitions ≈ 42 Partner calls, avoiding `sync_analytics`' per-product/per-SKU N+1 fan-out (~106 calls/day); (b) entity polls bounded to `update_time_from = now−7d` (the resource layer already accepts it; `sync.py` just never passes it — unbounded cold pulls fetch all-time history); then (c) scoring, which is pure in-process Python over ≤10k-row queries (seconds). **Measured estimate** from the production backfill ledger (`ops.analytics_backfill_partitions`, July 2026 run: catalog ≈3.7s, live ≈11s, product ≈32s, revenue ≈0s per day-partition; ~12s mean): analytics ≈5–6 min + entities ≈1 min + scoring seconds ⇒ **OAuth → first signals/ActionCards in ≈6–8 minutes**, ~55 total calls, far inside ADR-029's 400-call soft budget and never binding the 10 req/min/endpoint bucket (≤7 calls per endpoint). Speed over completeness by design.
- **Impact-eligibility corollary:** a 7D bootstrap yields signals fast but not ADR-077's 14-day pre-window; extend the backfill asynchronously (7d → 14d ≈ +5 min, → 30d progressive per ADR-050 C2) in the background so runs executed soon after connect still get counterfactuals.


**Implemented and merged to `main`** (re-run wave `feature/agent-w2b-wave`, #1040–#1045 + #1068,
landed via #1113 on 2026-08-14; the first attempt on `feature/agent-w2-pim-wave` was refused under
[ADR-079](../../adr/079-w2-artifact-disposition.md) and is retained as reference evidence only).
The DiD reader, control-pool selection, confidence tiering, `impact_readings` storage, daily beat
task and gate suite all shipped as specced. The re-run fixed what the first attempt carried: the
HIGH-severity control-pool screen that compared a count-calibrated volume floor against rate
metrics (silently disabling K-nearest sibling selection for `ctr`/`conversion_rate`, #1062), the
GMV-only gate-suite monoculture (now all three metric families, defect pinned by mutation), and
untested `classify.py` branches (#1068). Outstanding: `ProductSkuPrice.amount` stored as a string;
the **one real end-to-end reading** (backdated sandbox run) waits for W3-A's `workflow_runs` +
runner and lands at the W3 checkpoint.

### 12. P10 — Observability baseline
Minimal specs:
- dictConfig JSON logging + request-ID middleware; per-run rollup (tokens, cost, latency, tool calls); log redaction (no tokens/PII). (Re-verify baseline: request-ID middleware + dictConfig partially landed on main via #963+.)
- **Outcome chain (user directive 2026-08-11 — fix 3):** every run's post-hoc record follows Recommendation → Action → TikTok state change → Observed outcome → Incremental impact. Links: ActionCard (recommendation) → `ToolExecution` rows (actions) → webhook #5 / read-back state (`WorkflowOutcomeRecord`, TikTok state change) → KPI window after the change (observed outcome) → before/after delta on the recommendation's target metric (incremental impact).
- **Four unconflated metrics (user directive 2026-08-11 — fix 7)**, each with its own source and denominator, never blended into one score:
  | Metric | Question | Source |
  |---|---|---|
  | Recommendation quality | Was Juli right? | Scoring signals vs subsequent observed outcomes |
  | Approval rate | Did sellers agree with Juli? | ActionCard approve/reject/expire counts |
  | Execution quality | Did Juli successfully perform the task? | `stop_reason` distribution + `required_steps` completion |
  | Business impact | Did the action actually improve the metric? | Outcome-chain incremental impact |

Gate: one run produces a complete, queryable run tree with all five outcome-chain links populated; the four metrics computable from separate sources; logs actually emit.

### 13. P15 — E2E prototype complete
Minimal specs: hardening pass over the full Optimize Product path (frontend + backend); extract reusable per-workflow config template (prompt + allowlist + output schema).

Gate: demo-able, repeatable, documented run; template extraction reviewed.

### 14. P13 — Family charter, seller journeys, and rollout of the remaining workflows *(charter grilled 2026-09-03; supersedes "rollout to remaining 10 workflows")*

**Status: charter recorded, design order proposed, grill in progress.** This section is the
reference for every workflow designed after Optimize Product: the family purpose below is the
context for each workflow's **functional** requirements, and the automation/monitoring grades
are the reference for its **non-functional** requirements. Read this before `to-prd` on any
workflow issue.

#### Positioning — four families, two removals

Juli is an AI assistant that automates and monitors a TikTok Shop through analytics and
approval-gated end-to-end execution, in this priority order: **Product** (create, optimize),
**Inventory** (replenish, clear excess), **Campaign & Promotion** (create, end, optimize), and
**Customer Service** (returns/refunds/cancellations, then responses) last.

- **Livestream is not an automation target.** The Partner API has no livestream write endpoint;
  every live-related call is an analytics read, and ADR-067 already fixed livestream as
  recommendation-only. Do not design a livestream execution workflow.
- **Process Order (5) and Handle Split Package (6) are an Operations item, not a fifth family.**
  Owner decision 2026-09-03: they are **design-order item 3 (Operations)**, ahead of Replenish,
  Mega Sale Readiness, Create Hero Product and the Promotion family, on the evidence in
  [`seller-journeys/order-shipping.md`](seller-journeys/order-shipping.md) and the family-by-phase
  scoring in [`seller-journeys/mega-sale-prep.md`](seller-journeys/mega-sale-prep.md).
  A shop that misses TikTok's shipping clock loses its licence to operate before any listing
  optimisation matters, and a mega sale multiplies the order volume without moving the clock.
- **FBS before FBT.** FBT appears once in 839 Vietnamese academy pages, needs the
  `seller.fbt.inbound` OAuth scope Juli does not hold, an FBT-onboarded merchant and a goods-binding
  step, and no FBT call has ever been captured. FBT branches stay deferred until all three exist.

#### What each family is for — functional-requirement context

The seller is not short of information: Seller Center already grades every listing, tiers every
price, forecasts every SKU and clocks every chat. The seller is short of time, and one wrong
automated write costs more than a missed opportunity. Each family exists to make one class of
judgment call once, with consent, and carry it through.

| Family | Seller's purpose | Main KPI | What TikTok already gives the seller | Where Juli adds value |
|---|---|---|---|---|
| **Product** | Get found and get chosen — the product page is the only surface a buyer sees before paying | CTOR | Product Optimizer diagnostic tags, title optimizer with search-volume scores, Price Diagnostics tiers, 14 card-diagnostic recommendations | Decide *which* suggestion to accept and *whether* a price move is safe, then execute it as one consented change. Reprice through a Product Discount, never the base price |
| **Inventory** | Never sell what you do not have; never hold what will not sell | GMV (replenish), AOV (clear excess) | 30-day forecast, recommended replenishment quantity, days of supply, four alert channels, the Sản phẩm thanh lý clearance label | Reconcile to TikTok's numbers instead of competing with them; guard the stock write against auto-restock, the Luôn sẵn hàng lock and multi-warehouse; relay the supplier as a seller-attested fact; clear through the label, not zero stock |
| **Campaign & Promotion** | Spend margin only where it buys sales — every promo is seller-funded and price-remembered | CTOR | Discount bands, duration bounds, the 14-day floor, stacking priority, a pricing simulator — all enforced for a human in the UI, only rejected for an API caller | Pre-submit validation, lever chosen by eligibility (VP < 36 ∧ balance > −100 USD ∧ official account — the VN rating cell is malformed in the crawl, see [`seller-journeys/promotion.md`](seller-journeys/promotion.md) §A.2), safe monotonic edits (extend, raise limits/budget, deactivate expired); vouchers and campaigns as guided checklists since they have no API |
| **Customer Service** | Protect the licence to operate — rating, Account Health, campaign and CRM access | Cancellation rate, AHT, 12HRR | Its own clocks (48h / 1d / 2d / 12h), platform pre-approval, Fast Refund, a chatbot, FAQ auto-send, proactive shipping messages and the Trợ lý Nhà Bán Hàng copilot | Triage by time-to-breach, two-decision return model, evidenced rejections and one-shot negotiation/appeal drafted for confirmation, evidence packs for the sanctioned repair paths. Never auto-send, never auto-reject |

**Process Order sits beside these four as an Operations workflow**, not inside them: Main KPI
**cancellation rate**, seller purpose "ship on time inside TikTok's clock", per
[`seller-journeys/order-shipping.md`](seller-journeys/order-shipping.md). It borrows Customer
Service's clock mechanics without sharing its licence-protection framing. **Mega Sale Readiness**
(design-order item 5) sits in the same Operations slot and reaches across into Promotion: it
prepares the campaign event that Process Order then has to survive.

#### Seller-journey evidence

Five Opus scouts read ~120 bodies from the TikTok Academy VN corpus (ADR-051 protocol) and
aligned each journey to `execution_layer.md` step by step. A sixth scout (mega-sale preparation,
2026-09-03) swept the campaign/mega filter across both the academy and partner corpora. The reports
are committed beside this plan and are the source of truth for the corrections below:

| Journey | Report | Juli workflows aligned |
|---|---|---|
| Product — create, optimize, stock | [`seller-journeys/product.md`](seller-journeys/product.md) | 1, 2, 3, 4 |
| Campaign & Promotion | [`seller-journeys/promotion.md`](seller-journeys/promotion.md) | 4, 7a–7c |
| Order & Shipping, warehouses, capacity | [`seller-journeys/order-shipping.md`](seller-journeys/order-shipping.md) | 5, 6, 3 (warehouse touchpoints) |
| Returns, refunds, cancellation | [`seller-journeys/returns-refunds.md`](seller-journeys/returns-refunds.md) | 8a, 8b, 8c |
| Customers & customer service | [`seller-journeys/customers.md`](seller-journeys/customers.md) | Resolve Recurring Complaints (deferred), future responses |
| Mega Sale preparation and peak-day operations | [`seller-journeys/mega-sale-prep.md`](seller-journeys/mega-sale-prep.md) | 5, 3, 7a–7c, 8; platform-campaign registration has NO Partner API |
| Process Order actors per fulfilment path (Partner API + Academy) | [`seller-journeys/process-order-actors.md`](seller-journeys/process-order-actors.md) | 5, 6, 5B; Vietnam is on the SEA "schedule shipping" flow — Create Packages and Confirm Package Shipment are not seller steps, Ship Package is the pivotal write, FBT is monitor-only |

Eight findings change workflows rather than annotate them:

1. **TikTok reprices through discounts and vouchers, not the base price.** Optimize Product step 6
   and Clear Excess step 3 both call `prices/update`; Price Diagnostics applies a Product Discount
   (SKU) or Seller Voucher (product), 30-day default, held ≥ 1 day. This affects the working
   `optimize_product_2` playbook.
2. **Clear Excess's "baseline markdown before every promotion" is harmful** — it compounds with
   percentage promos, is blocked under fixed-price promos, raises the 14-day flash-sale floor and
   tightens 30–180-day campaign thresholds permanently.
3. **TikTok already computes the replenishment number** (forecast × period − available) and days
   of supply; T1/T10 must reconcile to it.
4. **Clearance has a native end state** — the Sản phẩm thanh lý label; a 0-stock SKU cannot be
   labelled and adding stock strips it. Clear Excess step 6a is the wrong end state.
5. **After-sales is a race against TikTok's clocks** — 48h cancellation auto-cancel, 1-day
   intake auto-approve, 2-day inspection auto-approve that also forfeits the appeal; VN window is
   15 days (6 for several categories), not 30; returns carry two seller decisions, not one.
6. **The enforced service metric is a 12-hour response rate ≥ 85 %** graded every Monday
   (−10/−20 AHR). Juli's curated `account-health.md:67` still records a legacy 24h figure.
7. **Promotion has three lanes** — API-automatable (product discount, shop flash sale, shipping
   discount, BMSM), Seller-Center-only (all vouchers), human-only (campaigns). Ongoing edits are
   monotonic only. Analytics are D-1. 7c is `PUT`, not `POST`.
8. **Never edit title, category, images and description together** — that is the fingerprint of
   the listing-repurposing violation. Title ≥ 25 characters is enforced on the next edit.

#### Workflow design order

Reordered from the 2026-09-02 proposal because Optimize Product — the template every later
workflow copies — is misaligned on the one mechanism (pricing) that the Inventory and Promotion
families share. Amended 2026-09-03 by owner decision: items 0 and 1 move into **W9-A**, ahead of
P15's template extraction, and Process Order + Handle Split Package enter the order as an
Operations item (their position superseded by the 2026-09-03 reorder below).

**Reordered again 2026-09-03 (owner), on the mega-sale scout's family-by-phase scoring.** Scoring the
four families plus Operations separately for the two phases of a mega sale splits the answer. *During*
the sale, Order Processing is the highest-scoring family on every axis (impact 5, pain 5, repetition 5,
API reach 5) and Inventory is second (held back only by reach 3). *Preparation* pain is real but
mostly **unreachable**: platform-campaign registration has no Partner API, and TikTok already ships
one-click registration, recommended campaign price and stock, and a 30-day forecast. So Process Order
becomes item 3 with mega-sale volume as its non-functional requirement, Mega Sale Readiness enters at
item 5 as its preparation companion, and the Campaign & Promotion family moves back to item 7.

*Preparation (T-30 → T-1)*

| Family | Impact | Pain | Repetition | Reach | Composite |
|---|---|---|---|---|---|
| Promotion | 5 | 5 | 5 | 1 | 125 |
| Inventory | 5 | 4 | 5 | 3 | 300 |
| Product | 4 | 3 | 4 | 4 | 192 |
| Order Processing | 3 | 2 | 3 | 1 | 18 |
| Customer Service | 3 | 2 | 2 | 1 | 12 |

*During the sale (T-day → T+3)*

| Family | Impact | Pain | Repetition | Reach | Composite |
|---|---|---|---|---|---|
| Order Processing | 5 | 5 | 5 | 5 | 625 |
| Inventory | 5 | 5 | 5 | 3 | 375 |
| Customer Service | 4 | 4 | 5 | 2 | 160 |
| Promotion | 3 | 2 | 3 | 4 | 72 |
| Product | 2 | 1 | 1 | 2 | 4 |

Composite is the product of the four columns — a ranking device only, not a unit of anything.

| # | Item | Family | Wave | Scope |
|---|---|---|---|---|
| 0 | Template hardening | shared | **W9-A** (T-1..T-3); the rest with the first W10 workflow that needs it | `workflow_key` on `workflow_runs`; polymorphic bound subject (nullable `product_id`, active-run index on `(shop_id, workflow_key, subject_ref)`); domain-registered tool dispatcher replacing `ProductToolExecutor`'s literal handler dicts; shared prompt sections extracted per ADR-072 d.1; the two gate tests de-pinned from `optimize_product_2`; step input contracts (deferred-design half 1). **Also the deadline clock, the `waiting_external` run state and the autonomy ladder** (see NFR reference) — Inventory and Customer Service cannot ship without them |
| 1 | Optimize Product pricing realignment | Product | **W9-A** — see [where it lands](#where-the-optimize-product-pricing-realignment-lands-2026-09-03) | Read TikTok's diagnostics first (before `get_seo_keywords`); reprice via Product Discount with the campaign/Flash-Deal precheck; title-length gate; never bundle the four listing fields. Introduces the first Promotion write tool. **design: [ADR-090](../../adr/090-optimize-product-realignment.md)** |
| 2 | Clear Excess Inventory (4) | Inventory | W10 | Drop the markdown; pre-submit validator (bands, duration, floor, stacking); end with the Thanh lý label. First workflow to need `waiting_external`. **design: [ADR-091](../../adr/091-clear-excess-inventory-design.md)** |
| 3 | Process Order (5) + Handle Split Package (6) | Operations | W10 | An everyday operations workflow whose **non-functional requirement is sustained high-volume processing during a mega sale**: order volume multiplies while the 14:00 cutoff, the 2–3-working-day auto-cancel, the 48 h cancellation window and LDR/FDR do not move. The deadline clock is the run's spine; `waiting_external` and its intervention guard are reused from ADR-091; inventory webhooks (#27/#68) drive an **oversell guard** that pauses dispatch proposals for a SKU whose available stock has reached zero; packing and handover are presented as a timed human checklist. Combine/split is decided at Create Packages, not downstream; an Update Delivery Status step for Ship-by-Seller; a failed-delivery terminal branch; OHC capacity and Holiday Mode as capacity levers; multi-warehouse modelled — [`seller-journeys/order-shipping.md`](seller-journeys/order-shipping.md) and [`seller-journeys/mega-sale-prep.md`](seller-journeys/mega-sale-prep.md) §B/§E. **design: [ADR-092](../../adr/092-process-order-dispatch-design.md)** — v1 scoped minimal (FBS + platform shipping, two runs a day, one batch confirmation, notification-only exceptions, Batch Ship as the only write); the v2 column is the mega-sale NFR; the standing approval (option 2) is planned and deferred |
| 4 | Replenish Inventory (3), FBS | Inventory | W10 | An **inventory-risk forecaster** (owner framing 2026-09-04): Stage A monitors three signals — stockout-by date under the event uplift, stranded committed stock (cancelled, not returned, auto-restock OFF), post-event excess (→ Clear Excess). Two labelled numbers (TikTok's baseline + Juli's event uplift) summed into one agent-proposed order; one run suspended twice on seller-attested reports ("ordered", "received") with the report form as the consent moment; in-event reconciliation of stranded stock in batches; the auto-restock toggle recommended before the event, never flipped unasked; three write guards (auto-restock state, Luôn sẵn hàng lock, multi-warehouse allocation); impact reading = **stock health**, no revenue. Stock locks at **order placement** (`committed_quantity`), not add-to-cart. **design: [ADR-093](../../adr/093-replenish-inventory-design.md)** |
| 5 | Mega Sale Readiness | Operations/Promotion | **v2 — deferred (owner, 2026-09-05)** | **Not designed.** The T-10 preparation companion to item 3: one card per campaign event (the subject is the campaign, not a product), carrying a **read-only briefing** — eligibility pre-flight, a per-SKU max-safe campaign price computed from the seller's own margin floor and 30–180-day price memory, a stock reservation plan, and the registration deadline on the deadline clock — that ends in a Seller Center checklist. The single write is post-approval **promo-stacking cleanup**: deactivate the seller promotions the campaign price silences. **Platform-campaign registration has no Partner API**, so nothing about registration is ever a write Juli performs — [`seller-journeys/mega-sale-prep.md`](seller-journeys/mega-sale-prep.md) §E |
| 6 | Create Hero Product (1) | Product | W10 | Image → title → suggested category → attributes; draft vs submit; rejection loop distinguishing *Không thành công* (resubmit) from *Đóng băng* (terminal); 2026-03-20 licence attributes |
| 7 | Campaign & Promotion family (7a–7c) | Promotion | W10 | Create / end / optimize across the four API lanes; monotonic edits as level-1 autonomy candidates; vouchers and campaigns as human checklists. *Proposed, not yet grilled:* the family's first workflow is **Optimize Promotion** over existing seller-created activities, whose subject already exists under ADR-087; standalone creation is deferred behind it |
| 8 | Returns, Refunds, Cancellation (8a–8c) | Customer Service | W10 | Two-decision return model; TikTok timers as run state; every reject and negotiation offer prepared with evidence and paused for CONFIRM; AHT as the optimisation target |
| 9 | Customer Service responses | Customer Service | W10 | Subscribe webhooks #13/#14; ingest 12HRR/CSAT/NRR; draft-only replies over the unanswered queue ranked by time-to-breach; evidence packs for report-invalid-review and report-abusive-buyer |
| — | Deferred | — | — | FBT replenishment (scope + onboarded shop); Livestream (no write API) |

**v1 specification (owner directive, 2026-09-05).** Every workflow designed so far ships as v1 with
limited functionality — minimal, viable and safe. The single v1 spec, functional and non-functional
requirements per workflow plus the shared requirements, is
[`v1-workflow-spec.md`](v1-workflow-spec.md); it is the input to `to-prd`. Where it trims an ADR
decision for v1 the trim is marked in the spec, and the ADR remains the design of record.

**Delivery rules for the v1 build (owner, 2026-09-05).** (1) Shared code (design-order item 0,
restricted to the P0 ladder in [`v1-workflow-spec.md`](v1-workflow-spec.md) §8.1) lands first and
serially; the four workflow lanes then run in parallel with disjoint write paths. (2) **The first
~10 % of slices in landing order — the P0 shared code and the first Optimize Product slices — are
executed by Fable**, overriding the Haiku executor row of the agent phase model for those slices,
to establish the code standard (`docs/architecture/code-standard.md`) that every later Haiku
executor is held to; the Haiku review agent reviews them unchanged. (3) v1 is done only when a
workflow works end-to-end for a real connected seller, so the production-write unlock (#1339) and
W7-bis (#1469) are on the v1 critical path. (4) One active run per subject across all workflows,
with endpoint-family write locks (spec S-FR-11). (5) One deadline view is the single surface added
to the identical-UX set, shared by every workflow.

#### Common workflow structure — identical UX, per-case internals

Owner directive, 2026-09-04: every agent workflow follows the **same five-stage structure** and
the seller-facing UX is **identical** across workflows. What differs per workflow is the
predicate, the tools, the guards and the measure — never the surfaces the seller learns once.

- **Stage A — Monitoring.** Scheduled scoring or a webhook-driven basis change emits a
  subject-scoped card through the ADR-087 no-duplicate path, or suppresses with a named reason.
- **Stage B — Decision plan review and approval.** One card anatomy: situation, evidence, the
  Main KPI with its real trend and a directional goal, an agent-proposed value for every field,
  and human checklist items wherever TikTok has no API. Approve is run creation (ADR-075).
- **Stage C — Run.** Reads → a **deterministic rule** computes every price- or quantity-bearing
  parameter (the model never picks a number) → validator at dispatch → **one CONFIRM pause with
  a single proposal** (one lever per run, N = 1) whose proposed change states the consequences →
  **re-verify immediately before the write** → **exactly one write** (single or batch) → vendor
  confirmation via webhook → completion digest.
- **Stage D — Suspended close-out**, only where the workflow waits on the world:
  `waiting_external` with its own reaper policy and the intervention guard — the seller changes
  the thing, the run closes, Juli reverts nothing.
- **Stage E — Measure.** A did-the-job fact per run plus the hedged impact reading; no reading
  for a run that wrote nothing.

Honest end states everywhere: `completed` with a named cause, never `failed` for "nothing to do".
The identical surfaces: the card, the plan review, the confirmation sheet, the notification and
digest, the completion message, the exception list. **A workflow that needs a new surface is a
signal the design is wrong**, and every later workflow ADR must carry the instantiation row below.

| | ADR-090 Optimize Product | ADR-091 Clear Excess | ADR-092 Process Order (v1) | ADR-093 Replenish |
|---|---|---|---|
| Subject | Product | Product (SKU evidence) | Dispatch window (Order for v2 exceptions) | Product (SKU evidence) |
| Trigger | Nightly scoring: CTOR drift, price tier, TikTok diagnosis codes | Nightly scoring: days of supply > 90 and low sell-through | Scheduled read of orders due before the next run | Risk monitor: stockout-by date, stranded committed stock, post-event excess |
| Deterministic rule | Discount depth from T9 margin floor; diagnosis code selects the field | Depth envelope + recommended depth per SKU; stock goal | Clean predicate; sort by `rts_sla` | TikTok baseline + Juli event uplift; needed-by date; reconciliation tally |
| Single write | Product Discount create, or one listing-field edit | Product Discount create (then deactivate on goal) | Batch Ship for the confirmed subset | Update Inventory (toggle on its own card) |
| Suspended? | No (lapse emits a card revision) | Yes — until goal or expiry | No in v1; v2 exceptions only | Yes — twice, on attested reports |
| Guards | Diagnosis-first, title gate, never bundle four fields, lock via vendor rejection | Eight-rule validator, disclosure check, intervention guard | Re-verify before write, subset only, per-package read, cancellation and address guards | Re-verify, auto-restock state, Luôn sẵn hàng lock, warehouse allocation, intervention guard |
| Measure | Impact reading on the tied KPI | Goal progress; days of supply before/after | Shipped before deadline ÷ due | Stock-health series; forecast vs actual into the event outcome store; no revenue |

#### Automation vs monitoring — non-functional-requirement reference

Scale: **A** — the family's value depends on it; **B** — matters but is bounded by TikTok's rules
or data cadence; **C** — deliberately weak.

| Family | Monitoring | Automation | Why the balance sits there |
|---|---|---|---|
| Product | B | A | Listings change slowly; daily cadence suffices. Value is executing a judged change well, once, with consent. No write is ever pre-approved |
| Inventory | A | B | Stock is the fastest-moving state after orders and depletes at night. Juli cannot execute the supplier step, so watching and prompting is most of the value. Clear Excess is the exception and automates fully behind one CONFIRM |
| Campaign & Promotion | B | A | Analytics are D-1, so no intraday optimizer. TikTok's ongoing-edit matrix (extend window, raise limits/budget, deactivate expired/exhausted) defines the highest pre-approval ceiling of any family |
| Customer Service | A | C | The family is clocks graded automatically; 24/7 monitoring *is* the product. Sending, rejecting, negotiating and appealing are one-shot, policy-exposed acts that stay human |

What "24/7" means on TikTok Shop: at night and on weekends the shop still receives orders, chats,
cancellation and return requests, stock depletion from a creator's video, and promos that expire
or exhaust their limit. Listing edits, campaign registrations and reorders happen in business
hours. The always-on layer is therefore an **event and deadline layer**, and automation is a
**consent ladder** on top of it. Four shared mechanisms carry all four families:

1. **Event spine.** The webhook-first spine (ADR-048) already ingests 16 event types; add #13
   New conversation and #14 New message. Each event revises the subject-scoped action card
   (ADR-087) rather than minting a new one.
2. **Deadline clock.** One beat task computes time-to-breach for every open request and order
   from TikTok's real timers (48h / 1d / 2d / 12h / 14:00 cutoff / 2–3 working days) and escalates
   by push, then email. Depends on the W7-bis fix (#1469) so beat tasks can read tenant rows.
3. **Autonomy ladder tied to Repeat consent (ADR-055 d.19).** Level 0 notifies. Level 1 is
   pre-approval with notification, granted once per workflow kind after a `completed` run, and
   only for reversible or monotonic writes. There is no level 2. Price setting, stock writes,
   rejections and anything one-shot never leave level 0. No-auto-act copy still bars the ask.
4. **`waiting_external` run state.** A run that must wait days (supplier delivery, campaign
   review, return ship-back) suspends with its own reaper policy and resumes on a seller-attested
   report or a webhook — never by reusing `waiting_approval`, whose 4h reaper and paused
   wall-clock are load-bearing for consent expiry. The **intervention guard** — snapshot what the
   run created, compare on every external change event, and close the run when the seller has
   changed it — is part of `waiting_external`, not a per-workflow rule
   ([ADR-091](../../adr/091-clear-excess-inventory-design.md) d.5). **Clear Excess is the first
   workflow that needs `waiting_external`**, so it lands with design-order item 0, ahead of item 2.

Per-family plan:

- **Product.** Monitoring: nightly scoring over CTOR drift, price tier and TikTok's own listing
  diagnostics; product status (#5) and audit (#37) webhooks. Automation: card → approve → run →
  CONFIRM per write → impact reading. Success metric: approval rate on well-reasoned single changes.
- **Inventory.** Monitoring: inventory webhooks #27/#68 plus days-of-supply, reconciled against
  TikTok's recommended reorder number; night-time depletion triggers a push, not a run.
  Automation: Replenish auto-safe steps are exporting the replenishment list and drafting the
  purchase request; the quantity write only after the seller attests receipt and passes the three
  guards. Clear Excess automates fully behind one CONFIRM.
- **Campaign & Promotion.** Monitoring: activity webhooks #39/#63, daily eligibility signals,
  stock-limit exhaustion, expiry, and the campaign calendar surfaced 14 days ahead. Automation:
  creation and any price-bearing change CONFIRM-only; extend/raise/deactivate as level-1
  candidates; optimisation on a daily loop.
- **Customer Service.** Monitoring: a live queue ordered by time-to-breach across cancellations,
  returns, refunds and chats, with 12h and Monday grading modelled explicitly and rolling AHT.
  Automation: level 1 only for acts TikTok already performs (intake-stage approvals inside the
  seller's configured envelope). Rejections, partial-refund offers, appeals and any reply beyond a
  status restatement are drafted with evidence and paused for CONFIRM. Nothing is auto-sent.

#### Documentation conflicts to resolve before implementation

| Conflict | Sources | Safe bound |
|---|---|---|
| Fulfilment cutoff 14:00 (academy, crawled 2026-07) vs 18:00 "effective Dec 1, 2025" | academy fulfilment-timeframe policy vs `tiktok_platform/seller/operational-limits.md:97-99` | Resolve before T5 Deadline Rule ships |
| Return appeal window 7 vs 15 calendar days | dispute rules vs refund FAQ | 7 days |
| Platform refund-only appeal 7 calendar days vs 3 business days | feature guide vs agreement §4.2.1 | 3 business days |
| Flash sale "API không được hỗ trợ" vs verified sandbox `FLASHSALE` create | VN flash-sale page vs `contract-collection.md` §B-5 | Verify on the sandbox before relying on it |
| Product video ≤ 5 MB (policy) vs ≤ 20 MB (guide) | listing policy vs feature guide | 5 MB |
| Response rate 24h (Store Rating, analytics tile) vs 12h (enforcement) | chat feature page vs communication policy | Model both; enforce on 12h |
| 7c Update Activity `POST` vs `PUT` | `execution_layer.md:301-306` vs `contract-collection.md:1201` | `PUT` |
| Flash-sale price-floor lookback 14 days vs 30 days | newer product flash-sale page vs older LIVE flash-sale page | **30 days** (conservative) |
| `Search Activities` "does not exist" vs documented in the Partner API | `execution_layer.md:290-293` vs `partner-catalog.json` `POST /promotion/202309/activities/search` | Capture it on the sandbox before relying on it either way |
| §5A step 4 Create Packages vs Partner docs "region specific to the US and JP" | `execution_layer.md` §5A vs `create-packages-202512.md:17`; VN production orders already carry `packages[]` | Read `package_id`; no create in SEA |
| §5A step 7 Confirm Package Shipment vs "only warehouse service providers certified by the platform" | `execution_layer.md` §5A vs `supply-chain/confirm-package-shipment-202309.md:17` | Delete the step |
| Ship-by-Seller auto-cancel 15 calendar days vs day 13 from payment | `seller-journeys/order-shipping.md` vs the SOF feature page | **13 days** |
| Stock "locked at add-to-cart" (owner assumption) vs locked at order placement | inventory dashboard buckets (*Đã khóa vì đã chốt đơn*) and `inventory-search-202309.md` `committed_quantity` | Order placement; the manual restore step is the auto-restock toggle (`Tự động về lại hàng`), API-configurable via `POST /product/202604/inventory/operation/settings` (uncaptured) |

#### Edge-case matrix — unchanged

Work the matrix (API down/timeouts, malformed LLM output, unavailable tool, rate limits,
cancellation, disconnects, duplicates, partial completion) against Optimize Product first, then
carry it into each onboarded workflow; register the 4 missing tool handlers as their workflows land.

**Gate (revised):** edge-case matrix green; `execution_layer.md` corrected for the eight findings;
each workflow designed against its family charter and its seller-journey report, with its NFR
grades stated in the PRD; the four shared mechanisms landed in step 0 before any workflow that
needs them.

### 15. P6 — Documentation retrieval (deferred)
Optional `search_juli_documentation` tool over curated docs (ADR-051 catalog pattern, not embeddings). Only if agent answers need it.

## Target architecture — swimlane sequence diagram

Four lanes; the LLM never touches TikTok or internal services — every tool call crosses the Juli Server execution boundary. `═══>` arrows = streamed SSE events; `───>` = request/response.

```
┌─────────────┐   ┌──────────────────────────────┐   ┌─────────────┐   ┌───────────────────────────┐
│   Client    │   │         Juli Server          │   │ LLM Server  │   │ External/Internal Tools   │
│  apps/demo  │   │  FastAPI + workflow engine   │   │ (provider)  │   │ TikTok API · Analytics ·  │
│  Demo page  │   │  (orchestrator & boundary)   │   │             │   │ Scoring/Decision Layer    │
└──────┬──────┘   └──────────────┬───────────────┘   └──────┬──────┘   └─────────────┬─────────────┘
       │                         │                          │                        │
       │ Approve workflow        │                          │                        │
       │ POST /v1/demo/decisions/{id}/approve               │                        │
       │────────────────────────>│                          │                        │
       │                         │ verify ActionCard        │                        │
       │                         │ status + tenant scope    │                        │
       │                         │ (approval gate)          │                        │
       │   SSE: workflow.started │                          │                        │
       │<════════════════════════│                          │                        │
       │                         │ system + workflow prompt │                        │
       │                         │ + tool schemas (registry)│                        │
       │                         │─────────────────────────>│                        │
       │                         │<─────────────────────────│                        │
       │                         │ AssistantMessage:        │                        │
       │                         │  TextBlock               │                        │
       │                         │  ToolCallBlock           │                        │
       │  SSE: assistant.text    │                          │                        │
       │  SSE: tool.started      │                          │                        │
       │<════════════════════════│                          │                        │
       │                         │ validate tool + params   │                        │
       │                         │ (allowlist, guards,      │                        │
       │                         │  read/write policy)      │                        │
       │                         │ run_tool_async(name, payload)                     │
       │                         │──────────────────────────────────────────────────>│
       │                         │              execute via guarded client           │
       │                         │              (sandbox write / prod read)          │
       │                         │<──────────────────────────────────────────────────│
       │                         │ raw result → normalize   │                        │
       │                         │ → agent-safe sanitize    │                        │
       │                         │ = ToolCallResult         │                        │
       │  SSE: tool.completed    │                          │                        │
       │<════════════════════════│                          │                        │
       │                         │ ToolCallResult appended  │                        │
       │                         │ to conversation          │                        │
       │                         │─────────────────────────>│                        │
       │                         │<─────────────────────────│                        │
       │                         │  ╭─ loop until FinalResponse or iteration cap ─╮  │
       │                         │                          │                        │
       │                         │ Final TextBlock +        │                        │
       │                         │ structured output,       │                        │
       │                         │ validated vs workflow    │                        │
       │                         │ output schema            │                        │
       │  SSE: workflow.completed│                          │                        │
       │<════════════════════════│                          │                        │
       │ render summary,         │                          │                        │
       │ recommendations,        │                          │                        │
       │ next actions            │                          │                        │
```

Boundary rules:
- `LLM → ToolCallBlock → Juli Server → validate → execute → sanitize → ToolCallResult → LLM` — the LLM only ever sees business semantics; TikTok endpoints, credentials, and raw responses stay server-side.
- Approval gate sits before the loop; CONFIRM-class write tools pause the loop with `workflow.approval_required` inside it.

## End-to-end data flow and triggers (2026-08-11)

Three planes; the LLM enters late and narrow — steps ①–⑥ are entirely deterministic,
and the agent loop is never a trigger source (it only runs inside a run a human
approval created). Triggers are of three kinds: time (① ③), vendor push (② ⑪), and
human intent (⑥ and mid-run CONFIRM).

```
════════════════════════════════════════════════════════════════════════
 DATA PLANE — how the server gets data (no agent, no LLM involved)
════════════════════════════════════════════════════════════════════════

   TikTok Shop Partner API  (production merchant, READ-ONLY guard)
        │
        │  ① scheduled sync (Celery)      ② webhooks (orders, product status)
        ▼
   Ingestion → bronze / silver tables (Postgres)
        │        raw vendor payloads → normalized DTOs (mapping.py)
        │
        │  ③ trigger: sync completion / scoring batch
        ▼
   Analytics & scoring layer                     ◄── owns WHAT
        KPI computation → AdvisorySignals → WorkflowRecommendation
        │
        │  ④ recommendation materialized
        ▼
   ActionCard  (shop_id, workflow_key, product binding, rules copy)
        status: active — sits waiting for the seller

════════════════════════════════════════════════════════════════════════
 DECISION PLANE — the seller in the Demo page
════════════════════════════════════════════════════════════════════════

   Client (apps/demo, Decisions page)
        │  ⑤ GET /v1/demo/decisions          seller opens the page
        ▼
   renders ActionCard (Đề xuất: why / expected impact / next steps)
        │
        │  ⑥ seller clicks Approve (Phê duyệt)
        ▼
   POST /v1/demo/decisions/{id}/approve  ───►  Juli Server

════════════════════════════════════════════════════════════════════════
 EXECUTION PLANE — Juli Server orchestrates; the LLM never touches
                   TikTok, the DB, or credentials
════════════════════════════════════════════════════════════════════════

   Juli Server (FastAPI)
        ⑦ approval gate: ActionCard really approved? tenant scope ok?
           one-active-run-per-product index checked (ADR-073)
        ⑧ create workflow_run  (created → queued)
             records prompt_version + prompt_sha256
        ⑨ enqueue Celery task
        ▼
   Worker builds the run context — the ONLY things the LLM ever sees:
        • composed prompt  compose(optimize_product, v1)   ≤3k tokens
        • juli-source signals payload (from ActionCard/scoring)  ≤1k
        • tool schemas + allowlist derived from the Playbook artifact
        ▼
   ┌────────────── WorkflowRunner agent loop (running) ─────────────┐
   │                                                                │
   │   LLMService.complete(...)  ───►  OpenAI GPT-5.4 nano          │
   │        ◄───  TextBlock / ToolCallBlock      ◄── owns HOW only  │
   │                     │                                          │
   │        validate vs allowlist + AUTO/CONFIRM policy             │
   │          ├─ AUTO read   → TikTok PRODUCTION (read guard)       │
   │          │      basis snapshot captured on product reads       │
   │          ├─ CONFIRM write → pause: waiting_approval            │
   │          │      seller confirms diff in client → resume        │
   │          │    → idempotency ledger claim → compare-before-write│
   │          │    → TikTok write (sandbox now; production when     │
   │          │      the mutation capability unlocks — ADR-068 amd) │
   │          └─ raw result → sanitize (ADR-070: caps, source       │
   │                          roles, banned-pattern guard)          │
   │                     │                                          │
   │        sanitized ToolCallResult appended → next LLM call       │
   │        (stateless: window rebuilt from run-state blob)         │
   │                                                                │
   └── until stop_reason: final_response │ caps │ timeout │ cancel ─┘
        ▼
   ⑩ every step emits events → workflow_run_events (Postgres,
        {run_id, sequence_number, event_type, timestamp, payload})
        + Redis pub/sub (best-effort delivery; Postgres replays)
        ▼
   SSE endpoint  ═══►  Client renders live; reconnect sends
        Last-Event-ID: <sequence_number> → replay from Postgres

════════════════════════════════════════════════════════════════════════
 POST-RUN
════════════════════════════════════════════════════════════════════════
   ⑪ TikTok webhook (#5 product-status) → WorkflowOutcomeRecord
   Outcome chain: Recommendation → Action → TikTok state change
                  → Observed outcome → Incremental impact
   Storage:  workflow_runs.state JSONB = run working set (P-CS deferred)
             Postgres = durable record (runs, tool executions, events)
```

## Codebase verification findings (2026-08-11 baseline)

Condensed from four exploration reports; full evidence lives in the session plan.

| Draft-checklist phase | Verdict | Key evidence |
|---|---|---|
| 0.1 Execution model | PARTIAL | Read/write boundary is strong (`integrations/tiktok/capabilities.py`, `guards.py`, `factories.py`, `services/execution/sandbox_guard.py`); no per-tool confirmation classification. |
| 0.2 Lifecycle | MISSING | Four disjoint vocabularies (`ExecutionStatus`, `ActionCard.status`, `DemoExecutionState`, frontend lifecycle); no retry/timeout/cancellation anywhere. |
| 1 Engine | PARTIAL | Celery dispatch + tool registry exist (`services/execution/`); orchestration hard-coded per tool handler; no agent loop. |
| 2 The 11 workflows | EXISTS (catalog) | `WORKFLOW_TOOL_CATALOG` (`tool_routing.py:14-42`) + `WORKFLOW_DISPLAY_NAMES` (`kpi_catalog.py:82-94`) + `docs/product/execution_layer.md`; 4 keys route to unregistered tools. |
| 3/4 Tool registry & schemas | PARTIAL/MISSING | name→callable only; no metadata/schemas; handlers take `dict[str, Any]`. |
| 5 Sanitization | PARTIAL | `mapping.py` normalizers + Pydantic DTOs + `SELLER_COPY_BANNED_PATTERNS`; no agent-safe serializer. |
| 6 Docs retrieval | PARTIAL | ADR-051 catalog+grep for dev agents; embedding RAG rejected; nothing product-runtime. |
| 7 Structured output | MISSING (LLM) | No block types/validation/repair; `CopySource = Literal["rules"]` is the designed switch. |
| 8 Streaming | MISSING | No SSE/WS/polling anywhere; demo approve returns full narrative synchronously. |
| 9 Safety | PARTIAL | Transport guards excellent; `POST /v1/executions` trusts caller-supplied `approval_id` unverified. |
| 10 Observability | MISSING | No logging config, request IDs, metrics; ADR-039/061 designed, unimplemented. |
| 11 Model abstraction | MISSING | No LLM SDK; dead `LlmGenerator` seam. |
| 12 Prompts | MISSING | 3 inline f-strings; deterministic `copy_layer.py` templates are the stand-in. |
| 13 Errors | PARTIAL | Good TikTok client retry taxonomy; no Celery retry/timeout/cancellation/global handler. |
| 14 Security | PARTIAL + 2 live vulns | JWT fails open (`core/security/dependencies.py:27`); RLS non-functional; prompt-injection defense required once LLM lands. |
| 15 E2E (SEO) | PARTIAL | `optimize_product_2` chain exists using TikTok's own SEO endpoints; no agent loop. |

Demo page baseline: all-11 plan/review/execution modules exist client-side but execution is a localStorage mock; `fetchRecommendations()` targets nonexistent `/v1/demo/recommendations` and silently falls back to fixtures; the backend demo surface is unconsumed.

## Verification strategy

- Unit: loop runner with fake `LLMService` (scripted tool-call sequences) — iteration cap, timeout, cancellation, malformed-output repair, unauthorized-tool rejection.
- Contract: registry↔catalog cross-validation; event-schema snapshot tests in `packages/contracts`; new LLM-boundary tests replacing the lifted no-LLM tests.
- Integration: sandbox-write guarded run of `optimize_product_2` (`tests/integration/tiktok_sandbox.py` helpers); SSE reconnect/replay test.
- E2E: Demo page approve → live stream → rendered structured output against the real provider (manual, then recorded-replay fixture).

---

## Deferred design — explicit step state contracts + agent-requested data (2026-08-27)

**Status: DEFERRED. Revisit at the W6 exit gate, and before any further workflow
implementation.** Consistent with D4 (sequential, minimal-first): get the whole
pipeline working end-to-end first, then deepen. Nothing here blocks gate #1226.

### The problem

The playbook fixes the *sequence* of steps, but each step's **data requirements
are implicit**. A tool reaches into whatever the run happens to have and hopes
the fields it needs are present. Nothing declares what a step consumes, nothing
verifies it before dispatch, and the agent has no way to ask for data the run
never gathered.

Two consequences, both observed in production during the gate #1226 walk:

**Producers silently missing.** Four defects in one lane where a value's
consumer shipped and its producer did not — the failure only appeared on a live
run, because every unit test supplied the missing value itself:

| Issue | Consumer built | Producer missing |
|---|---|---|
| #1379 | terminal tool declared in the playbook | never registered in the production tool registry |
| #1382 | resume seeded a guard from `RunState.basis_snapshots` | nothing ever wrote that key |
| #1389 | handler read `context.product_detail` | never assigned at context construction |
| #1389 | `_sync_product_detail` read the guard | `set_product_detail` never called in production |

**Vendor requirements discovered one rejection at a time.** The
`update_product_listing` body was built from an allowlist copied out of
contract-collection B-4's sample cURL. That sample is a working example, not a
required-field specification, so production surfaced the gaps serially:

- run `b354d2d6` → `400 CategoryId is a required field`
- run `f6f2695e` → `400 MainImages is a required field`

Each cost a fix, a review, a deploy and a walk. The current mitigation — pass
every unedited field through at its current value — stops the bleeding, but the
tool is still deciding what it needs invisibly, from a bag it never asked for.

### The two halves

**1. Workflow half — steps declare their inputs.** A `PlaybookStep` states what
it consumes, and the runner verifies availability *before* dispatch, failing
with "step 5 needs `main_images`, which no prior step produced" instead of
letting the vendor reject it. This is the half that would have caught all four
producer gaps above at once, and it is the higher-value half.

**2. Agent half — the agent can request data.** A capability the model can call
when a step needs something the run has not gathered, rather than the tool
silently reaching for it. Narrow and explicit, not open-ended: the point is
adaptability *within* the fixed structure, not letting the agent improvise the
workflow. ADR-068's capability boundary and ADR-072 d.2's playbook allowlist
both constrain what this may look like.

### Open questions to answer at revisit

- Where does the declared-input contract live — `PlaybookStep`, the `ToolSpec`,
  or both? A tool's requirements are arguably a property of the tool, not of the
  step that calls it.
- Does verification happen at import time (like `validate_playbook_tools`), at
  run start, or immediately before each dispatch? Each catches a different class
  of failure at a different cost.
- How does a declared input survive the CONFIRM pause? The write leg runs in a
  fresh process, so this interacts directly with `RunState` persistence
  (#1382, #1389).
- What is the vendor-contract source of truth? B-4's sample proved insufficient.
  Either the required-field list is documented properly per endpoint, or the
  body is derived wholesale from the current entity — the second is what the
  current fix does, and may simply be the right long-term answer.
- Does the agent-requested-data capability need its own CONFIRM policy, or is
  read-only by construction sufficient?

### Why not now

The pipeline is one field away from its first end-to-end success. The gate #1226
walk is currently the *only* end-to-end test of this path (see ADR-088 decision
4 on the live smoke that has never run), so redesigning mid-walk would remove
the one instrument that has found every one of these defects. Close the gate,
then design this properly as an ADR.
