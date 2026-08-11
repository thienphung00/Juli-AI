# ADR-070: Agent-safe sanitization contract — bound IDs, source roles, caps, error translation

**Status:** Proposed
**Date:** 2026-08-11
**Deciders:** grill-with-docs (Architect) with user

**Builds on:** [ADR-068](068-agent-workflow-execution-boundary.md) (boundary + injection
posture), [ADR-069](069-agent-tool-registry-and-write-path.md) (ToolSpec output models are
the sanitized shapes).
**Context constraint:** the base model is **GPT-5.4 nano** — small context, nano-class
instruction-following. Sanitized results must be compact and structurally
injection-resistant, not merely clean.
**Scope:** Phase P5 of
[`docs/product/agent-workflow-execution/PLAN.md`](../product/agent-workflow-execution/PLAN.md)
— the Optimize Product tool surface (6 tools, ADR-069); the contract generalizes to later
workflows.

## Context

Tool results are the only content the LLM sees besides prompts. The existing
vendor→domain layer (`integrations/tiktok/schemas.py`, `mapping.py`) normalizes for ETL
correctness, not LLM exposure: raw IDs, vendor payload residue, unbounded free text, and
technical errors all pass through. Six decisions define the agent-safe layer.

## Decision

1. **Context-bound IDs.** The run context (created from the approved ActionCard) holds
   entity bindings; the tool executor injects real IDs server-side. Optimize Product tool
   schemas carry **no ID parameters** — the LLM never sees nor supplies a raw vendor ID,
   eliminating the hallucinated/injected-ID class structurally and avoiding nano-model ID
   copy corruption. **Per-step extension (reserved):** playbook steps that genuinely need
   mid-run agent selection use server-minted opaque refs (`"item_ref": "I1"`) resolved
   against a closed per-run map. Raw IDs through the LLM are rejected for agent runs.

2. **Hard caps + signaled truncation.** The sanitizer enforces ~2,000 tokens per tool
   result (design target ≤800): lists capped (SEO words top 20 by vendor relevance
   ordering), free text capped (~1,500 chars, verbatim otherwise), every truncation
   emits `{"truncated": true, "omitted_count": n}` — never silent. No raw nested vendor
   payloads; images surface as `{count, dimensions}` with server-held references. No
   LLM-side summarization — compaction is deterministic server code so goldens stay
   reproducible.

3. **Source-role provenance tagging.** Free text in tool results lives in envelopes by
   server-assigned **source** (named `source`, not `role`, to avoid chat-role collision):
   `juli` (implicit trusted default — structured fields, computed values), `vendor`
   (TikTok/marketplace text — data, never instructions), `seller` (client-supplied
   inputs — preference, honored within playbook + policy). **No buyer role.** Assignment
   derives from field provenance server-side — attacker text cannot re-assign its own
   source. One handling rule per source in the system prompt. Defense-in-depth stack
   behind it: tool allowlist, bound IDs (decision 1), CONFIRM diffs (ADR-068), output
   guards (decision 6).

4. **Machine values, no display formatting.** ISO-8601 UTC dates (no relative dates);
   money as numeric value + `"currency": "VND"`; rates as numbers with self-describing
   keys (`conversion_rate_pct`, matching `gold.kpi_envelopes` pre-divided convention);
   keys English, values verbatim. Display formatting (₫, dd/mm) is the copy layer's job.

5. **Error translation.** Every `TikTokAPIError` maps at the sanitization boundary to
   `{"error": {"category", "message", "retryable"}}` — `category` reuses
   `ExecutionErrorCategory` (validation | tiktok_api | transient | unknown); `message` is
   business-language English for the model; `retryable` derives from the curated
   allowlist (`{100005, 100006, 36009003}` + transport errors). Loop policy: one in-loop
   re-call on `retryable: true`, then the step fails and the run reports `failed`
   honestly. Raw codes, endpoint paths, and vendor request IDs go only to server-side
   audit/logs.

6. **Fail-closed banned-pattern guard at two chokepoints.** (a) Every tool output before
   it enters the conversation — a hit replaces the result with an internal tool error
   (logged); the model never sees the leaked token. (b) All agent-authored output before
   it streams or persists — a hit triggers the single repair retry, then rules-template
   fallback (P7). The pattern list moves to one language-neutral source:
   `packages/contracts/seller-copy-banned-patterns.json`, imported by the existing TS
   guard (`seller-copy.ts`, no behavior change) and loaded by Python; a contract test
   compiles every pattern in both regex dialects, constraining patterns to the
   JS/Python-common subset.

## Consequences

- ADR-069's tool `output_model`s implement this contract; the golden-file gate (raw
  sandbox response in → agent-safe result out → zero banned identifiers) tests decisions
  1–4 and 6 together.
- Optimize Product schemas shrink (no ID params) — a direct token saving per turn on a
  nano-class model.
- **Flagged open question (ActionCard layer, not P5):** multi-product Optimize Product.
  Options raised: (1) one stacked card recommending the top-3 products via a
  product-level priority algorithm (needs design); (2) a cap of N cards per workflow for
  N products. Hard fact for that decision: `action_cards` is unique on
  `(shop_id, workflow_key)` — option 2 requires a schema migration, not just policy.
  Context-bound IDs (decision 1) work unchanged under either option; multi-entity
  selection *within* one run would use the reserved ref extension.
- New pattern additions must compile in both regex dialects — a deliberate authoring
  constraint in exchange for structurally impossible drift.
