# ADR-071: LLM service — neutral block interface over a stateless OpenAI Responses adapter

**Status:** Proposed
**Date:** 2026-08-11
**Deciders:** grill-with-docs (Architect) with user

**Builds on:** [ADR-068](068-agent-workflow-execution-boundary.md) (block vocabulary, SDK
containment test), [ADR-070](070-agent-safe-sanitization-contract.md) (what the model is
allowed to see). **Base model decision:** **OpenAI GPT-5.4 nano** (user, 2026-08-11) —
supersedes the Claude Haiku copy-layer provider assumption in ADR-012/phase-4 docs for
the agent path.
**Retires:** the dead `LlmGenerator = Callable[[str], Awaitable[str]]` seam
(`ai/recommendations/engine.py:49`, `livestream_script.py:29`) as the product's LLM
entry point — it cannot express tools, system prompts, or usage, and has no production
callers. Its injectable-fake test pattern remains valid for those rules modules.
**Scope:** Phase P11 (minimal model abstraction) of
[`docs/product/agent-workflow-execution/PLAN.md`](../product/agent-workflow-execution/PLAN.md).
One provider, one model; fallback chains and multi-provider registry are later hardening.

## Context

The agent loop needs a model client shaped for its own vocabulary — messages in, blocks
out, usage attached — without letting a vendor SDK become the schema of the durable
conversation store (P-CS) or of the event protocol (P8). Six decisions were grilled.

## Decision

1. **Neutral block interface.** `LLMService.complete(messages, system, tools, config) →
   AssistantTurn`, where `AssistantTurn` carries owned dataclasses —
   `TextBlock | ToolCallBlock | FinalResponse` blocks plus a `Usage` record. Provider
   wire types never leave the module (the `integrations/tiktok` wrapping pattern).
   Rejected: SDK types throughout (~2 days faster once; the SDK becomes the stored
   conversation schema, upgrades ripple stack-wide, and ADR-068's merged containment
   test would have to be repealed); LiteLLM (multi-provider weight before a second
   provider exists).

2. **OpenAI Responses API, stateless.** The adapter targets the Responses API (current
   primary surface for GPT-5-era models: strict structured outputs, best tool calling)
   and never uses server-side thread state (`previous_response_id`/stored threads) —
   every call rebuilds the message window from the P-CS store (D5). Keeps the provider
   swappable, replay fixtures deterministic, and one source of conversation truth.

3. **Turn-level blocks, no token deltas.** Provider calls are non-streamed; the loop
   emits complete `assistant.text` / tool events per block. Rationale: a run's liveness
   comes from event cadence (status + tool events every few seconds, nano turns are
   1–3s); token deltas would fork the protocol into relay-only vs persisted events
   (breaking D3's event-log-is-the-stream symmetry and Last-Event-ID replay), force
   partial tool-call JSON assembly into the adapter, and make fixtures chunk-order
   sensitive. The event name `assistant.text.delta` is **reserved** as the additive
   upgrade for a future chat-like surface; the client may typewriter-animate blocks.

4. **Config surface.** One `LLMConfig` owned by the module: `model` (default
   `gpt-5.4-nano`), `max_output_tokens`, `temperature`, request timeout. Resolution
   order: **playbook override → environment → defaults** (per-workflow model selection
   realized without a registry). `OPENAI_API_KEY` arrives via the ADR-030 secrets
   pattern; agent-enabled deployments **fail closed at startup** when it is missing
   (ADR-061 startup-assertion vocabulary — never an empty-string default).

5. **Usage and cost capture.** The adapter returns input/output tokens per call;
   persisted on message rows (P-CS) and rolled up on `workflow_runs` (total tokens +
   cost estimate from a static price table in config). Enforcement is not this phase's
   job: per-run iteration caps live in P1; per-shop daily budgets are flagged to P9.

6. **Test strategy.** Recorded-replay HTTP fixtures for the adapter (mirroring
   `tests/integration/tiktok_recorded_replay.py`; the OpenAI SDK rides httpx like the
   TikTok client); real-key tests behind the existing `live` marker; the backend-wide
   AST containment test (`openai` importable only inside the LLM module) fulfilling
   ADR-068 decision 6(a); and a fake `LLMService` returning scripted `AssistantTurn`s
   as the standard double for loop tests.

## Consequences

- P8's `assistant.text` event carries complete blocks; P-CS stores our block shapes, so
  SDK/API-version migrations never touch stored rows — they touch one adapter file.
- The phase gate: one real tool-calling round-trip passes an integration test via
  recorded replay in CI; containment test green; usage visible on a run.
- The price table is a maintained artifact; stale prices skew cost estimates (accepted —
  estimates, not billing).
- A second provider or fallback chain later means a second adapter behind the same
  interface; nothing upstream changes.

## Amendment — token streaming in the run surface (D71.3, P61-C, 2026-10-20)

**Status:** Accepted (owner, D71.3). Supersedes decision 3's "provider calls are
non-streamed" for the agent run loop; turn-level blocks remain the contract.

1. **The adapter streams when asked.** `OpenAIResponsesAdapter.complete(...,
   on_text_delta=cb)` sends `stream: true` to the Responses API, awaits `cb` with
   each `response.output_text.delta`, and still returns one complete
   `AssistantTurn` — the same blocks and usage a non-streamed call returns. Tool-call
   arguments are assembled from `response.function_call_arguments.delta` / `.done`
   and `response.output_item.done`; the `response.completed` body's `output` is
   authoritative when present. `response.failed`, `error`, a stream without a
   terminal event, a transport error mid-stream or a malformed frame raise
   `LLMProviderError` — the turn fails as a whole (`stop_reason=llm_error`), never
   half-returned. Calls without a callback (card drafts, structured analysis,
   content scoring) stay non-streamed. `LLM_STREAMING` (default on) turns
   streaming off everywhere without a deploy of code. `on_text_delta` is not on
   the `LLMService` protocol; the runner passes it only when constructed with
   `stream_text=True` (the worker does so for the real adapter only).
2. **Deltas are persisted, coalesced.** The reservation in decision 3 worried that
   relay-only deltas would fork the protocol and break Last-Event-ID replay. So
   deltas are ordinary `workflow_run_events` rows — `assistant.text.delta`
   `{block_id, chunk_index, text}` with a run sequence number — written and
   published by the same `PersistingEventSink`: one event log, one stream, replay
   unchanged (D3 symmetry kept). Write volume stays sane by coalescing in the runner
   (`runner/text_stream.py`): emit when ≥ 48 characters are ready
   (`STREAM_DELTA_FLUSH_MIN_CHARS`) or 100 ms have passed since the last emit
   (`STREAM_DELTA_FLUSH_INTERVAL_SECONDS`) — roughly 5–40 rows for a nano turn
   instead of hundreds. No migration: `event_type` is a free `String(64)`.
3. **`assistant.text` stays the source of truth.** Deltas are previews. Every block
   that streamed is followed by its authoritative `assistant.text` (a `TextBlock`
   always was emitted; a streamed `FinalResponse` is now also committed by one,
   after the outbound guard, before `workflow.completed`), or by some other event
   and never committed (guard refusal, `llm_error`, `required_steps_unfulfilled`).
   Clients render the open block with a typing caret, replace it with the
   `assistant.text`, and drop a block that was never committed. Replay re-sends the
   same rows with the same sequence numbers, so dedupe-by-sequence (already the
   reducers' contract) prevents doubled text. The tail of a turn's text held back
   at the end of the stream is never sent as a delta — the commit carries it.
4. **The outbound guard runs before a delta leaves (ADR-070 d.6(b)).** Before each
   emit the relay scans the whole text received so far and releases only text that
   ends 64 characters short of it (`STREAM_GUARD_HOLDBACK_CHARS`), so a banned
   match up to that length is complete — and caught — before any of it could be
   sent. On a hit the turn's stream stops; the final block then meets the existing
   guard exactly as before. Cost: a turn's last ≤ 64 characters appear with the
   commit rather than typed.
5. **Contract.** `assistant.text.delta` joins the event union on both sides
   (`events/payloads.py` / `envelope.py`, `packages/contracts/src/agent-events.ts`,
   golden fixture `assistant-text-delta.json`); the old "reserved, rejected by name"
   fixture became a malformed-delta fixture rejected by both languages. A streamed
   run captured from the real runner is committed as
   `tests/fixtures/golden_scenarios/optimize_product_streamed.json` and drives the
   run-surface reducer tests.

Consequences: fixtures for a streamed turn are chunk-order sensitive only in the
delta rows; every assertion about outcomes reads the committed `assistant.text`. A
crash-redelivered task that replays a turn can now collide on more sequence numbers
(the sink's unique-index no-op drops the replayed rows, as for every event) — see
fasttrack DEBT P61-C.
