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
