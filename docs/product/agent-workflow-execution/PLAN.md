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
|---|---|---|---|
| 1 | P0 — Execution model & lifecycle (0.1 + 0.2) | ✅ complete — [ADR-068](../../adr/068-agent-workflow-execution-boundary.md) merged (#962) | ✅ 2026-08-11 |
| 2 | P3+P4 — Tool registry + tool schemas (minimal) | ✅ implemented — [ADR-069](../../adr/069-agent-tool-registry-and-write-path.md); registry core + 6-tool Optimize Product set (#980–#984), registry×sanitizer integration (#996) | ✅ 2026-08-13 |
| 3 | P5 — TikTok sanitization (product surface only) | ✅ implemented — [ADR-070](../../adr/070-agent-safe-sanitization-contract.md); sanitize package (#990–#995), wired into the real READ handlers + golden re-pointed to the production path (#996) | ✅ 2026-08-13 |
| 4 | P11 — Model abstraction (minimal LLM service) | ✅ implemented — [ADR-071](../../adr/071-llm-service-openai-adapter.md); `LLMService`/adapter/fake (#985–#989), `FakeLLMService` proven downstream against the real registry + sanitizer (#996) | ✅ 2026-08-13 |
| 5 | P12 — Prompt architecture (system + Optimize Product) | ✅ implemented — [ADR-072](../../adr/072-agent-prompt-architecture.md); re-run wave merged to `main` (#1107, 2026-08-14) with all four status records after the [ADR-079](../../adr/079-w2-artifact-disposition.md) Option B refusal of the first attempt | ✅ 2026-08-14 (mechanical gates; human voice review #1071 open) |
| 6 | P1 — Agent execution loop (blocks + runner) | ✅ **implemented and live-verified** — [ADR-073](../../adr/073-agent-execution-loop-and-write-path-hardening.md); PRD #1115, slices #1117–#1124 merged via #1183. Read path, CONFIRM pause, resume, sandbox write, ledger and cancel all proven against the deployed host — see [Wave 3 live verification](#wave-3-live-verification-2026-08-19--2026-08-20) | ✅ 2026-08-20 |
| 7 | P-CS — Conversation & state storage (NEW) | ⏸ deferred (user, 2026-08-11) until real users exist — stand-in: `workflow_runs.state` JSONB blob behind the `ConversationStore` protocol (ADR-073 d.5) | ⬜ |
| 8 | P8 — Streaming (SSE + Celery relay) | ✅ **implemented and live-verified** — [ADR-074](../../adr/074-agent-event-streaming-and-relay.md); PRD #1116, slices #1125–#1133 merged via #1183. Live SSE, gapless duplicate-free `Last-Event-ID` reconnect, mid-run cancel, and the fail-closed `memory://` boot assertion all proven on the deployed host — see [Wave 3 live verification](#wave-3-live-verification-2026-08-19--2026-08-20) | ✅ 2026-08-20 |
| 9 | P7 — Structured output contract | ⏸ deferred (user, 2026-08-11) — scheduled **W9** with P15 (see the wave roadmap) — loop runs on ADR-072 prose output; wires in via `FinalResponse` block + prompt v2 bump (ADR-073 d.5) | ⬜ |
| 10 | P9+P14 — Approval, safety & security prerequisites | 🟨 **W5** — design grilled 2026-08-12 — [ADR-075](../../adr/075-agent-approval-gate-and-security-prerequisites.md) drafted; implementation pending | ⬜ |
| 11 | P-UI — Demo UI polish + wiring (Optimize Product) (NEW) | 🟨 **W6** — design grilled 2026-08-12 — [ADR-076](../../adr/076-agent-demo-execution-experience.md) + [PUI-DESIGN.md](PUI-DESIGN.md) drafted; implementation pending | ⬜ |
| 11b | P-IM — Incremental impact measurement (NEW) | ✅ implemented, gate reopened in **W4** — [ADR-077](../../adr/077-incremental-impact-measurement.md); re-run wave merged to `main` (#1113, 2026-08-14), #1040–#1045 + #1068 all with status records, after the [ADR-079](../../adr/079-w2-artifact-disposition.md) Option B refusal of the first attempt | 🟥 2026-08-20 — code gates green, but the one real end-to-end reading is **unreachable**, not merely un-run: the reader selects `tool_name IN {"listing.optimize_product"}` and the agent ledger writes `update_product_price` / `update_product_listing`, and the ledger records no `payload_json`, which classification and product binding both require. See [Wave 3 live verification](#wave-3-live-verification-2026-08-19--2026-08-20) |
| 11c | P-CRED — TikTok credential lifecycle / refresh-token rotation (NEW) | 🟨 **W4 — design settled; credentials lapse 2026-08-27 04:30 UTC** (manually refreshed 2026-08-20; each manual run buys 7 days from the moment it runs, not 7 added to what is left).** Grilled 2026-08-17 ([ADR-080](../../adr/080-tiktok-credential-lifecycle.md)), re-grilled 2026-08-18 against the code and **amended by [ADR-081](../../adr/081-refresh-token-rotation.md)**: three-layer refresh (beat + lazy + reactive), one guarded door with a session-level advisory lock, vendor-authoritative expiry, dedicated `credentials` queue, five additive columns; `CREDENTIALS_DATABASE_URL` descoped. Four slices — see [Wave 4](#wave-4--p-cred-refresh-token-rotation-2026-08-18); gate = full matrix + one real sandbox-token refresh | ⬜ |
| 11d | P-PROD — Production-write unlock (NEW) | ⬜ **W7** — RLS across 13 tables, manual red-team pass, the ADR-068 capability flip, and the ADR-050 C2 data dependencies. Gates P-IM's real reading and P10's business-impact metric | ⬜ |
| 12 | P10 — Observability baseline | ⬜ **W8** | ⬜ |
| 13 | P15 — E2E prototype complete (Optimize Product) | ⬜ **W9** (with P7) | ⬜ |
| 14 | P13 — Edge cases + rollout to remaining 10 workflows | ⬜ **W10** | ⬜ |
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
| **W4 — P-CRED + P-IM** | 11c, 11b gate | P-CRED slices W4-1…W4-5 (ADR-081) · measurement reconciliation #1215, #1216, #1219, #1220 | — |
| **W5 — P9+P14** | 10 | Approval gate #1214, #1221, #1222, #1224, #1225 · security prerequisites #1217, #1218, #1223 (ADR-075) · W3 leftovers #1139, #1140, #1142 | — |
| **W6 — P-UI** | 11 | ADR-076 + PUI-DESIGN.md in full — dual entry, recorded-replay + live flag, staged run view, consent-grade option picker, run ledger, `useRunStream`, localStorage mock deleted · #1077 (seller-copy TS half) | **W7** |
| **W7 — P-PROD** | 11d (NEW) | Production-write unlock: RLS across the 13 tables · manual red-team pass · the ADR-068 capability flip · the ADR-050 C2 data dependencies (per-shop analytics topup, OAuth→signals cold start, 7D bootstrap) | **W6** |
| **W8 — P10** | 12 | Logging baseline re-verification, per-run rollup, the five-link outcome chain, the four unconflated metrics · closes #1226's second half | — |
| **W9 — P15 + P7** | 13, 9 | Hardening pass over the whole Optimize Product path; extract the per-workflow config template (prompt + allowlist + **output schema**) · P7 structured output contract | — |
| **W10 — P13** | 14 | Edge-case matrix; register the 4 unregistered tool handlers; onboard the remaining ten workflows via the template | — |

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

## Wave 4 — P-CRED, refresh-token rotation (2026-08-18)

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

### 14. P13 — Edge cases + rollout to remaining 10 workflows
Minimal specs: work the edge-case matrix (API down/timeouts, malformed LLM output, unavailable tool, rate limits, cancellation, disconnects, duplicates, partial completion) against Optimize Product; then onboard each remaining workflow via the template, registering the 4 missing tool handlers as their workflows land.

Gate: edge-case matrix green; each workflow onboarded with its own prompt/allowlist/schema + tests.

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
