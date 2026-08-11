# ADR-068: Agent workflow execution — boundary, authority, and lifecycle

**Status:** Proposed
**Date:** 2026-08-11
**Deciders:** grill-with-docs (Architect) with user

**Amends:** [ADR-012](012-architecture-reconciliation-mvp-vs-target.md) and
[`phase-4-beta-launch.md`](../product/phases/phase-4-beta-launch.md) — the rule "LLM never
decides what to recommend — only formats copy" is narrowed, not discarded: the LLM still
never decides *what* to recommend; it gains bounded authority over *how* an approved
workflow executes.
**Amends:** [ADR-055](055-decision-plan-review.md) in two scoped points: the Demo execution
path for agent runs is a **real agent run** (production reads + sandbox writes), no longer
the mock dry-run narrative; and the frontend lifecycle gains a terminal `failed` state for
agent runs (ADR-055 noted deriveLifecycleFromTimeline has no terminal failure).
**Does not change:** the deterministic scoring pipeline as the sole recommendation source;
Decisions' exclusive ownership of the approval gate; ADR-028 seller-copy authority;
ADR-037 unauthenticated reference-shop Demo; the P2-A1 capability guards
(`PRODUCTION_READ` / `SANDBOX_WRITE` hard-bound merchant IDs).
**Scope:** Phase 0 (execution model) of
[`docs/product/agent-workflow-execution/PLAN.md`](../product/agent-workflow-execution/PLAN.md).
First workflow: `optimize_product_2`.

## Context

The agent-workflow-execution plan introduces an LLM-driven tool-calling loop behind the
Demo page. The standing architecture (ADR-012/021/055, three no-LLM contract tests) was
written for a deterministic rules product with an LLM at most formatting copy. An agent
loop needs decisions on: what the LLM may decide, what its write tools may mutate, how it
learns each workflow's correct endpoint sequence, when a human must confirm, what the run
lifecycle is, and what happens to the no-LLM tests.

## Decision

1. **Playbook-guided bounded authority.** Three authorities, none overlapping:
   - Juli's deterministic scoring pipeline owns *what* is recommended (unchanged).
   - The seller owns approval — of the workflow, and again for CONFIRM-class writes.
   - The LLM owns *how* an approved workflow executes, inside that workflow's
     **playbook**: it selects allowlisted tool calls, proposes parameters, interprets
     sanitized results into seller language, and emits structured output. It never selects
     workflows, never calls tools outside the allowlist, never invents thresholds.

2. **Compiled playbooks, not runtime doc retrieval.** Each workflow's documented Partner
   API sequence in `execution_layer.md` is compiled at build time into a versioned
   playbook artifact (ordered steps → intent + permitted tools) embedded in the workflow
   prompt/config. The agent gets no runtime documentation-search tool: compiled artifacts
   are deterministic, reviewable, and are not a prompt-injection surface (consistent with
   the ADR-051 "curated artifacts for executors" pattern).

3. **Production reads, sandbox writes.** Agent runs are real end-to-end: READ tools
   receive `ProductionReadResources`; WRITE tools receive `SandboxWriteResources` obtained
   exclusively via `load_sandbox_write_resources()` (fail-closed transport guards,
   merchant-ID pinning). The LLM never sees a client, credential, or endpoint — the
   executor binds guarded resources server-side by `ToolSpec` classification. Writes
   target the sandbox counterpart product; production writes unlock at 3.5-C as a
   guard-configuration change, not an architecture change.

4. **Tool execution policy — AUTO / CONFIRM / NEVER** on every `ToolSpec`:
   - AUTO: READ + internal tools.
   - CONFIRM: every WRITE tool in this phase. The run pauses
     (`workflow.approval_required`) showing the agent-composed mutation as a field diff —
     LLM-authored content did not exist at plan-approval time, so plan approval cannot
     cover it. Repeat consent (ADR-055 item 19) is the only CONFIRM→AUTO downgrade path,
     valid solely for the five eligible workflow kinds.
   - NEVER: operations absent from every playbook (product deletion, order cancellation
     initiation, out-of-workflow refunds) are not registered as tools at all — structural,
     not runtime.

5. **`WorkflowRunStatus` — 8 states + status events.**
   `created → queued → running ⇄ waiting_approval → completed | failed | cancelled |
   timed_out`. Phase narration travels as SSE `workflow.status` events, never stored
   states. Mapping (documented, nothing rewritten): `ExecutionStatus` covers each spawned
   write-tool execution; `ActionCard.status` maps card-side (`approved` at run creation,
   `executing` while live); `DemoExecutionState` is superseded on the agent path; the
   frontend lifecycle derives `needs_input` ≈ `waiting_approval` and gains terminal
   `failed`.

6. **No-LLM tests stay; containment tests are added.** The three existing tests
   (`test_rules_copy_layer_contract.py`, `test_recommendations.py`
   `TestRuleBasedNoLlmDependency`, dashboard `test_listing_rules_engine.test.ts`) are
   module-scoped determinism guarantees over exactly the modules that keep recommendation
   authority — they are kept unchanged. New boundary tests: (a) provider SDK imports legal
   only inside the LLM service module (backend-wide AST check); (b) agent tool handlers
   never import `TikTokClient` directly — guarded factories only; (c) agent-authored
   seller copy passes a server-side `SELLER_COPY_BANNED_PATTERNS` check.

7. **Structured output composes existing contracts.** The agent's final output extends
   shipped types rather than inventing a parallel schema: `WorkflowReasoningCopy` with
   `CopySource` extended `"rules" → "rules" | "agent"`; findings reuse
   `AdvisorySignal`/`Severity`/`KpiId` vocabulary; run narration reuses the
   `DemoExecutionNarrativeStep` `{state, message, at}` shape as the `workflow.status`
   event payload; progress reuses `ExecutionTimelineStep`/`ExecutionRecord`; responses
   keep the `{success, data, error}` envelope. Net-new only: a typed `proposed_actions[]`
   field diff for CONFIRM pauses (extending `ReviewInputFieldDescriptor` with field
   kinds, as ADR-055 already required), `requires_confirmation`, run-identity fields, and
   the frontend `failed` lifecycle. Existing contract tests remain the regression base.

## Consequences

- "LLM never decides" becomes over-broad vocabulary: it never decides *what*, it does
  decide *how*. CONTEXT.md records **Playbook-guided agent authority**, **Workflow
  playbook**, **Tool execution policy**, and **WorkflowRunStatus**.
- The Demo's "no backend dependency" invariant (`apps/demo/MODULE.md`) is deliberately
  reversed for the agent path, as Analytics already did.
- A production-read product and its sandbox-write counterpart have different product IDs;
  the Optimize Product playbook needs an explicit ID-mapping step, and the run's
  structured output records the proposed change independently of where it was applied.
- The five repeat-consent exclusions and their class-D shipped promises constrain any
  future CONFIRM→AUTO widening; copy changes first, deliberately (ADR-055 item 19).
- Downstream phases (tool registry, LLM service, loop, storage, streaming, UI) design
  against this ADR; the plan tracker lives in
  `docs/product/agent-workflow-execution/PLAN.md`.

## Amendment — production writes are the target state (2026-08-11, with user)

Decision 3's framing is sharpened: when a seller approves a real action, the system
must **eventually write to production, not sandbox**. The capability model's target
state is therefore three-lane:

- **READ** — production API via read-only credentials (unchanged, live today).
- **WRITE** — production API via an **explicit mutation capability** granted per
  deployment, exercised only behind seller confirmation (CONFIRM policy). Unlock
  prerequisites, now designed in [ADR-073](073-agent-execution-loop-and-write-path-hardening.md):
  the idempotent mutation ledger and compare-before-write concurrency control. The
  unlock itself remains a guard-configuration/capability-grant change, not an
  architecture change.
- **Agent testing** — TikTok **sandbox** merchant: CI, recorded replay, development,
  and the demo's live write smoke. Sandbox is a testing surface, not the write path's
  destiny.

Until the prerequisites ship and the capability is granted, agent WRITE tools continue
to target the sandbox shop exactly as decision 3 specifies.
