# Agent Workflow Execution — Implementation Plan

Status: **approved 2026-08-11**. Sequential, minimal-first implementation; one workflow end-to-end (Optimize Product, `optimize_product_2`) before rollout to the remaining 10. Update the progress tracker as phases complete.

## Locked decisions

- **D1 — Real LLM agent loop, production-grade.** Real provider calls, real user data, real external APIs. The 3 no-LLM contract tests (`tests/unit/test_rules_copy_layer_contract.py:45-51`, `tests/unit/test_recommendations.py:329-338`, `apps/dashboard/src/__tests__/test_listing_rules_engine.test.ts:159`) are lifted deliberately; ADR-012/021/055 amended via a new ADR.
- **D2 — SSE transport** with a typed event protocol (`workflow.started/status`, `assistant.text`, `tool.started/completed`, `workflow.approval_required`, `workflow.completed/failed`), event IDs + ordering.
- **D3 — Celery worker + event relay.** Loop runs in a Celery task; events appended to a sequence-numbered event store and published on Redis pub/sub; thin SSE endpoint subscribes + replays from `Last-Event-ID`. Loop emits through an **EventSink interface** (in-process sink for tests/dev). Preserves the "HTTP handlers never execute inline" invariant.
- **D4 — Sequential, minimal-first, one workflow end-to-end.** Each phase ships only the minimal specs needed to unblock the next; revisit when required. Remaining 10 workflows onboard via Phase 13 (edge cases).
- **D5 — Conversation storage.** Recent conversation (messages, tool calls, current workflow state) in **Redis**; permanent history (conversations, messages, tool calls, workflow runs) in **Supabase/Postgres**.
- **D6 — Demo UI polish** for Optimize Product is an explicit phase.

## Progress tracker (implementation order is top-to-bottom, sequential)

| # | Phase (draft-checklist numbering kept) | Status | Gate passed |
|---|---|---|---|
| 1 | P0 — Execution model & lifecycle (0.1 + 0.2) | ✅ complete — [ADR-068](../../adr/068-agent-workflow-execution-boundary.md) merged (#962) | ✅ 2026-08-11 |
| 2 | P3+P4 — Tool registry + tool schemas (minimal) | 🟨 design grilled 2026-08-11 — [ADR-069](../../adr/069-agent-tool-registry-and-write-path.md) drafted; implementation pending | ⬜ |
| 3 | P5 — TikTok sanitization (product surface only) | 🟨 design grilled 2026-08-11 — [ADR-070](../../adr/070-agent-safe-sanitization-contract.md) drafted; implementation pending | ⬜ |
| 4 | P11 — Model abstraction (minimal LLM service) | 🟨 design grilled 2026-08-11 — [ADR-071](../../adr/071-llm-service-openai-adapter.md) drafted; implementation pending | ⬜ |
| 5 | P12 — Prompt architecture (system + Optimize Product) | 🟨 design grilled 2026-08-11 — [ADR-072](../../adr/072-agent-prompt-architecture.md) drafted; implementation pending | ⬜ |
| 6 | P1 — Agent execution loop (blocks + runner) | 🟨 design grilled 2026-08-11 — [ADR-073](../../adr/073-agent-execution-loop-and-write-path-hardening.md) drafted; implementation pending | ⬜ |
| 7 | P-CS — Conversation & state storage (NEW) | ⏸ deferred (user, 2026-08-11) until real users exist — stand-in: `workflow_runs.state` JSONB blob behind the `ConversationStore` protocol (ADR-073 d.5) | ⬜ |
| 8 | P8 — Streaming (SSE + Celery relay) | ⬜ | ⬜ |
| 9 | P7 — Structured output contract | ⏸ deferred (user, 2026-08-11) — loop runs on ADR-072 prose output; wires in via `FinalResponse` block + prompt v2 bump (ADR-073 d.5) | ⬜ |
| 10 | P9+P14 — Approval, safety & security prerequisites | ⬜ | ⬜ |
| 11 | P-UI — Demo UI polish + wiring (Optimize Product) (NEW) | ⬜ | ⬜ |
| 12 | P10 — Observability baseline | ⬜ | ⬜ |
| 13 | P15 — E2E prototype complete (Optimize Product) | ⬜ | ⬜ |
| 14 | P13 — Edge cases + rollout to remaining 10 workflows | ⬜ | ⬜ |
| 15 | P6 — Documentation retrieval tool (deferred, optional) | ⬜ | ⬜ |

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

### 4. P11 — Model abstraction (minimal)
Minimal specs:
- `LLMService` (messages, system, tools, usage) with one provider — **OpenAI, base model GPT-5.4 nano** (decided 2026-08-11) — + config surface (model, max_tokens, temperature, API key via ADR-030 pattern). No fallback chains yet.
- Replace/retire the dead `LlmGenerator` seam (`ai/recommendations/engine.py:49`); lift no-LLM tests per P0 decision.

Gate: one real tool-calling round-trip against the provider passes an integration test (recorded-replay for CI).

### 5. P12 — Prompt architecture (minimal) — *design grilled 2026-08-11, [ADR-072](../../adr/072-agent-prompt-architecture.md)*
Settled specs (Optimize Product only; eval-pipeline-ready by design):
- **Monolithic workflow prompt** `services/agent/prompts/optimize_product/v1.md` — eight sections: role, mandate & limits, source-role rules, input-signals guidance (summarize from the `juli` context payload, never invent metrics), playbook slot, recommend-within-scope (HOW-level only), output guidance + one worked example, prohibited behaviors. Run data arrives as the `juli`-source context message, never spliced into prompt text. Extraction trigger recorded: shared sections extracted when workflow #2's prompt lands.
- **Typed `Playbook` artifact** `services/agent/playbooks/optimize_product.py` (frozen dataclass: steps → intent, tools, policy) feeding ADR-069 cross-validation, the run allowlist, and the prompt's single `{playbook}` slot via deterministic `compose(workflow_key, version)` — later the eval-harness entry point. Playbook = safety surface (never eval-mutated); prose file = entire tuning surface.
- **Language:** English instructions; Vietnamese seller-facing output ("bạn" form) with an embedded mini-glossary of canonical `dictionary.md` terms (`_Avoid_` aliases forbidden); worked example in dictionary-compliant Vietnamese mirroring `copy_layer.py`'s register.
- **Versioning:** immutable released versions (edits → `vN+1`); runs record `prompt_version` + `prompt_sha256` (P-CS columns); production pin is a code constant. Output-contract section tightens to P7's schema via an explicit v2 bump.
- **Safety sections:** 3 source-role rules + 7 prohibitions (behavioral; ADR-070 guards remain load-bearing).
- **Budget:** composed prompt ≤ 3,000 tokens (tiktoken-asserted); `juli` payload targets ≤ 1,000.

Gate: four import-time tests green (snapshot, budget, playbook consistency, mechanical banned-pattern/`_Avoid_` check) + human voice review against `dictionary.md`/design-context + P-CS fields specified.

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

### 8. P8 — Streaming (minimal)
Minimal specs (event schema fixed by user directive, 2026-08-11 — fix 2):
- **Canonical event record** — every event persisted to `workflow_run_events` as `{workflow_run_id, sequence_number, event_type, timestamp, payload}`, sequence-numbered per run. **Postgres is the replay authority; Redis pub/sub is best-effort delivery only** — a lost Redis message is never a lost event. Reconnect contract: client sends `Last-Event-ID: <sequence_number>` ("give me events after sequence 47"); the SSE endpoint replays from Postgres, then re-attaches to live pub/sub.
- Typed SSE event protocol with event IDs/ordering, shared via `packages/contracts`.
- Celery task `run_agent_workflow` (dedicated queue; real Redis broker — currently `memory://` in `workers/celery_app.py`); Redis pub/sub `EventSink`; SSE endpoint with Last-Event-ID replay + heartbeats; cancel endpoint (sets `cancel_requested`, honored at ADR-073 checkpoints).

Gate: browser sees live events for a real run; kill Redis mid-run — reconnect replays from Postgres without gaps/duplicates; cancellation stops the loop.

### 9. P7 — Structured output contract — *⏸ deferred (user, 2026-08-11)*
Deferred under the same principle: the workflow functions without it and wires to it later. Stand-in: ADR-072's prose output guidance (final response = Vietnamese seller summary + actions list, shaped by the worked example). Wiring seam (ADR-073 d.5): the machine schema attaches at the `FinalResponse` block, the prompt's output section tightens via an explicit v2 bump (ADR-072 d.5), and `stop_reason: output_validation_failed` is already reserved in the enum.

Original minimal specs (unchanged, for when the phase is picked up):
- Optimize Product output schema (summary/findings/recommendations/actions/requires_confirmation) in `packages/contracts` + Pydantic; validate final LLM output; one repair retry; rules-template fallback (extend `CopySource` literal at `services/scoring/types.py:132`).

Gate: malformed-output test falls back cleanly; frontend can type against the schema.

### 10. P9+P14 — Approval, safety & security prerequisites
Minimal specs:
- Server-side approval gate: run created only from an `ActionCard` the user approved (closes the unverified `approval_id` gap in `api/routes/executions.py`); CONFIRM-class write tools pause with `workflow.approval_required` + resume endpoint.
- Fail-closed JWT startup assertion (empty `SUPABASE_JWT_SECRET` must crash, not bypass — `core/security/dependencies.py:27`) — **required before real user data flows**.
- Prompt-injection posture: product content tagged untrusted; server-side output guard on.

Gate: unauthorized/unapproved run attempts rejected in tests; write tool blocked without confirmation; auth assertion verified.

### 11. P-UI — Demo UI polish + wiring, Optimize Product only
Minimal specs:
- Fix `fetchRecommendations()` path bug (`/v1/demo/recommendations` → `/v1/demo/decisions` in `apps/demo/src/lib/recommendations.ts`); surface failures instead of silent fixture fallback.
- Approve → create run → `EventSource` consumption; execution view rendered from the event protocol (agent text, tool progress, approval pause, final structured output); replace localStorage `startExecution` (`apps/demo/src/lib/executions.ts:163-196`) for this workflow; polish per `ui-ux-design` skill; update `apps/demo/MODULE.md` invariant.

Gate: a user can run Optimize Product end-to-end in the Demo page against the real backend and watch it stream.

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
