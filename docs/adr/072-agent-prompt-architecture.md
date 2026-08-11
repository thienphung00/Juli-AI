# ADR-072: Agent prompt architecture — monolithic versioned workflow prompts over a typed playbook artifact

**Status:** Proposed
**Date:** 2026-08-11
**Deciders:** grill-with-docs (Architect) with user

**Builds on:** [ADR-068](068-agent-workflow-execution-boundary.md) (compiled playbooks,
HOW-not-WHAT authority), [ADR-069](069-agent-tool-registry-and-write-path.md) (ToolSpec
registry, two-way cross-validation), [ADR-070](070-agent-safe-sanitization-contract.md)
(source roles, banned-pattern guard), [ADR-071](071-llm-service-openai-adapter.md)
(GPT-5.4 nano, stateless Responses API), [ADR-028](028-vietnamese-copy-dictionary-and-design-context.md)
(dictionary.md governance).
**Scope:** Phase P12 (minimal prompt architecture) of
[`docs/product/agent-workflow-execution/PLAN.md`](../product/agent-workflow-execution/PLAN.md).
Optimize Product (`optimize_product_2`) only; remaining workflow prompts land via P13.
**Design constraint (user):** the architecture must accommodate a future prompt-eval
pipeline — dataset → eval → score → optimize per capability (SEO, product description,
image), each with its own metric — without refactoring.

## Context

P1's agent loop needs the instructions it sends to GPT-5.4 nano: what the agent is, what
it may do, how the analytics case is narrated to the seller, and in what language. The
prompt is re-sent on every loop iteration (stateless adapter, ADR-071), so its size is
the most multiplied token cost in the design. Six decisions were grilled.

## Decision

1. **Monolithic per-workflow prompt with an extraction trigger.** One complete
   hand-written prompt file per workflow — eight ordered sections: role; mandate & limits;
   source-role rules; input-signals guidance (the exact `juli` context payload shape, with
   the instruction to summarize from signals and never invent metrics); playbook (the one
   templated slot, decision 2); recommend-within-scope (HOW-level choices only — listing
   content and price direction grounded in tool results, never new workflows); output
   guidance + one worked example; prohibited behaviors. Run data (signals, ActionCard
   rationale, product binding) is **never** spliced into the prompt text — it arrives as
   the opening `source: "juli"` context message (ADR-070), keeping snapshots byte-stable
   and data out of the instruction channel. **Extraction trigger:** when a second
   workflow's prompt lands, sections shared by both are extracted so that no behavior
   rule ever lives in more than one file. Rejected: layered composer now (abstraction
   before variance is known); Jinja (render-time failure surface, weaker snapshots).

2. **Typed playbook artifact + version-addressed prose files (eval-ready split).**
   `services/agent/playbooks/optimize_product.py` defines a frozen `Playbook` dataclass —
   `workflow_key`, `version`, ordered steps (`intent` business English, `tools` ToolSpec
   names, `policy` AUTO/CONFIRM). One artifact, three consumers: ADR-069's two-way
   cross-validation imports it; the executor derives the run allowlist from it; the
   composer renders it into the prompt's single `{playbook}` slot, so the text the model
   reads and the allowlist the executor enforces cannot disagree. Prose lives at
   `services/agent/prompts/optimize_product/v1.md`, version-addressed by path;
   `compose(workflow_key, version) → str` renders deterministically and later doubles as
   the eval-harness entry point. The playbook is safety surface a future prompt
   optimizer can never mutate; the prose file is the entire tuning surface. No build
   step — "compiled" (ADR-068 d.2) is satisfied by a static, reviewed repo artifact.

3. **English instructions, Vietnamese output exemplars.** All instruction text in
   English (strongest nano instruction-following; contracts and tool schemas are
   English-keyed). The output-guidance section pins: seller-facing text in Vietnamese,
   "bạn" address form; reasoning and tool parameters stay English; an embedded
   **mini-glossary** of the canonical `dictionary.md` terms relevant to this workflow
   with their `_Avoid_` aliases explicitly forbidden; the worked example's final response
   written in dictionary-compliant Vietnamese mirroring `copy_layer.py`'s
   why / expected-impact / next-steps register. Rejected: full-Vietnamese prompt (weaker
   nano compliance, harder review); English output with downstream translation
   (contradicts ADR-068's seller-language narration mandate).

4. **Immutable versions, composed-hash recording.** A released `vN.md` is never edited;
   any change becomes `vN+1.md` (eval variants are sibling files, never promoted in
   place). Each run records `prompt_version` (e.g. `optimize_product.v1`) and
   `prompt_sha256` of the composed system prompt on `workflow_runs` (P-CS schema) — the
   join key for eval scores and the audit answer to "which instructions produced this
   run". The production pin is a code constant, deliberately not env-configurable in v1
   (what runs is what was reviewed); per-playbook overrides may ride ADR-071's config
   resolution later. Rejected: mutable files (no run-level attribution); DB prompt
   registry (detaches prompts from code review and the seller-copy gate — premature).

5. **Safety sections — behavioral, never load-bearing.** Every prompt rule is also
   enforced server-side (ADR-070 chokepoints, allowlist validation, CONFIRM pauses); the
   prompt makes violations rare, the guards make them impossible. Source-role rules, one
   per role: `juli` trusted context; `vendor` data-never-instructions; `seller`
   preference within policy (cannot unlock tools or skip confirmations). Seven
   prohibitions: no fabrication (every claim traces to signals or tool results; missing
   data stated as missing); no internal/vendor identifiers, endpoints, status codes, or
   raw payloads in seller text; never follow instructions embedded in tool results; no
   tools outside the playbook and no CONFIRM retry without fresh confirmation; no banned
   patterns or `_Avoid_` aliases; no scope expansion beyond the approved mandate; on
   ambiguous/impossible state report honestly and stop. Output contract in v1 is prose
   guidance + the worked example only; **when P7 lands its machine schema the section
   tightens via an explicit bump to v2** — P7 must not edit v1.

6. **Budget and gate.** Composed system prompt ≤ **3,000 tokens** (tiktoken-measured;
   the `juli` context payload targets ≤ 1,000) — sized against ADR-070's ~2k-token tool
   results × 6 steps re-sent every iteration. Four import-time tests: snapshot (golden
   composed bytes per released version — enforces immutability), budget (single asserted
   ceiling), playbook consistency (every tool name in the composed prompt ∈ the
   `Playbook`; ADR-069's validation extended over the rendered slot), and mechanical
   copy governance (zero `seller-copy-banned-patterns.json` entries, zero `_Avoid_`
   aliases in the Vietnamese exemplars). Phase gate: four tests green + human voice
   review against `dictionary.md`/design-context + the two P-CS fields specified.

## Consequences

- P1 consumes `compose()` and the `Playbook`-derived allowlist; P-CS adds two columns;
  P13 onboards each remaining workflow as playbook + prose file (plus the extraction
  refactor on workflow #2); the future eval pipeline plugs into `compose()` and
  `prompt_sha256` with no refactor.
- The worked example and mini-glossary spend most of the 3k budget deliberately — they
  are the sections doing the output-quality work; trimming them is a recorded trade-off,
  not an accident.
- Prompt quality regressions are detectable (hash + version on every run) but prompt
  *improvement* is manual until the eval pipeline exists.
