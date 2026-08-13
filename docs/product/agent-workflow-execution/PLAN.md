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
| 5 | P12 — Prompt architecture (system + Optimize Product) | 🟧 **implemented on `feature/agent-w2-p12-wave`, not on `main`** — [ADR-072](../../adr/072-agent-prompt-architecture.md); #1036–#1039 merged into the wave, green on every check except `artifact-gate`. Wave→main refused under [ADR-079](../../adr/079-w2-artifact-disposition.md) Option B; must be re-run inside the harness contract | ⬜ |
| 6 | P1 — Agent execution loop (blocks + runner) | 🟨 design grilled 2026-08-11 — [ADR-073](../../adr/073-agent-execution-loop-and-write-path-hardening.md) drafted; implementation pending | ⬜ |
| 7 | P-CS — Conversation & state storage (NEW) | ⏸ deferred (user, 2026-08-11) until real users exist — stand-in: `workflow_runs.state` JSONB blob behind the `ConversationStore` protocol (ADR-073 d.5) | ⬜ |
| 8 | P8 — Streaming (SSE + Celery relay) | 🟨 design grilled 2026-08-12 — [ADR-074](../../adr/074-agent-event-streaming-and-relay.md) drafted; implementation pending | ⬜ |
| 9 | P7 — Structured output contract | ⏸ deferred (user, 2026-08-11) — loop runs on ADR-072 prose output; wires in via `FinalResponse` block + prompt v2 bump (ADR-073 d.5) | ⬜ |
| 10 | P9+P14 — Approval, safety & security prerequisites | 🟨 design grilled 2026-08-12 — [ADR-075](../../adr/075-agent-approval-gate-and-security-prerequisites.md) drafted; implementation pending | ⬜ |
| 11 | P-UI — Demo UI polish + wiring (Optimize Product) (NEW) | 🟨 design grilled 2026-08-12 — [ADR-076](../../adr/076-agent-demo-execution-experience.md) + [PUI-DESIGN.md](PUI-DESIGN.md) drafted; implementation pending | ⬜ |
| 11b | P-IM — Incremental impact measurement (NEW) | 🟧 **implemented on `feature/agent-w2-pim-wave`, not on `main`** — [ADR-077](../../adr/077-incremental-impact-measurement.md); #1040–#1045 merged into the wave, green on every check except `artifact-gate`. Wave→main refused under [ADR-079](../../adr/079-w2-artifact-disposition.md) Option B; must be re-run inside the harness contract | ⬜ |
| 12 | P10 — Observability baseline | ⬜ | ⬜ |
| 13 | P15 — E2E prototype complete (Optimize Product) | ⬜ | ⬜ |
| 14 | P13 — Edge cases + rollout to remaining 10 workflows | ⬜ | ⬜ |
| 15 | P6 — Documentation retrieval tool (deferred, optional) | ⬜ | ⬜ |

## Wave 2 status — code on wave branches, **not on `main`** (2026-08-13)

Both W2 waves are complete and merged into their wave branches. **Neither reached `main`**, and
this is deliberate, not in-flight work:

| Wave | Branch | Issues | State |
| --- | --- | --- | --- |
| W2-A (P12) | `feature/agent-w2-p12-wave` | #1036–#1039 | merged into the wave; every check green except `artifact-gate` |
| W2-B (P-IM) | `feature/agent-w2-pim-wave` | #1040–#1045 | merged into the wave; every check green except `artifact-gate` |

`artifact-gate` cannot pass: `meta_prepare_executor.py` was never run for any W2 slice, and the
executor worktrees were torn down before Review, destroying the implementation artifacts for
#1036–#1043. Even the two surviving artifacts (#1044, #1045) cannot reach PASS —
`phase_run_correlation` requires the workflow cache and the executor run to be contemporaneous.
A fourth waiver was **refused** under [ADR-079](../../adr/079-w2-artifact-disposition.md),
Option B, honouring [ADR-078](../../adr/078-agent-w1-wave-artifact-waiver.md) item 6. The
wave→main PRs (#1060, #1061) are closed, not merged.

**What this means for agents picking up work here:**

- Do **not** treat P12 or P-IM as landed. `main` does not contain them; anything importing
  `services/agent/playbooks/` or `services/impact/` must branch from the relevant wave branch or
  wait for the re-run.
- **W3-A is blocked** on W2-A reaching `main` (playbook↔registry cross-validation needs the
  playbook). That cost was accepted knowingly.
- The path to `main` is a **re-run inside the harness contract**, now unblocked: #1057/#1058 gave
  the W2 issues real PRD parents and #1059 registered the epics and slice-routing rules, which
  demonstrably moves #1044 from `readyForExecutor: false` to `true`. Meta must run
  `meta_prepare_executor.py` per slice and halt unless it prints `readyForExecutor: true`, and
  **worktrees must survive until Review has read their artifacts.** The CI guard that would have
  caught all four occurrences of this failure is filed as **#1064** and should land first.
- The W2 code is not suspect. A full retrospective Review pass verified both waves by execution
  and found and fixed a HIGH-severity defect (#1062) plus three lesser ones. ADR-079 is about
  evidence of process, not about whether the work is sound.

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


**Implemented on `feature/agent-w2-p12-wave` (#1036–#1039, W2-A) — not on `main`.** The
monolithic prompt, typed `Playbook`, deterministic `compose()`, token budget assertion and
`optimize_product_2` criteria key all shipped as specced; the composed prompt measures 2,967
tokens against the 3,000 ceiling. The wave→main PR (#1060) was closed unmerged because
`artifact-gate` cannot pass — see **Wave 2 status** above and
[ADR-079](../../adr/079-w2-artifact-disposition.md). Playbook↔registry cross-validation therefore
still cannot run on `main`, and **W3-A remains blocked** until this wave is re-run inside the
harness contract.

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


**Implemented on `feature/agent-w2-pim-wave` (#1040–#1045, W2-B) — not on `main`.** The DiD
reader, control-pool selection, confidence tiering, `impact_readings` storage, daily beat task and
gate suite all shipped as specced. A retrospective Review pass found and fixed a HIGH-severity
defect: control-pool candidate screening compared a count-calibrated volume floor against the
candidate's own metric, so rate metrics (`ctr`, `conversion_rate` — half of ADR-077 decision 1's
map) could never clear it, silently disabling K-nearest-correlated-sibling selection (#1062). The
wave→main PR (#1061) was closed unmerged because `artifact-gate` cannot pass — see **Wave 2
status** above and [ADR-079](../../adr/079-w2-artifact-disposition.md). Known follow-ups carried
into the re-run: the #1045 gate suite exercises GMV only (metric monoculture), and
`ProductSkuPrice.amount` is still stored as a string.

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
