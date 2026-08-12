# ADR-075: Agent approval gate and security prerequisites — approve-is-run-creation, decision requests, authenticated demo

**Status:** Proposed
**Date:** 2026-08-12
**Deciders:** grill-with-docs (Architect) with user

**Builds on:** [ADR-068](068-agent-workflow-execution-boundary.md) (CONFIRM policy,
production-write amendment), [ADR-070](070-agent-safe-sanitization-contract.md)
(sanitizer chokepoints — extended here with invisible-Unicode stripping),
[ADR-073](073-agent-execution-loop-and-write-path-hardening.md) (waiting_approval,
params at pause, one-run-per-product), [ADR-074](074-agent-event-streaming-and-relay.md)
(routes, `workflow.approval_required` — extended here with an additive `options[]`).
**Baseline re-verified 2026-08-12:** JWT auth is already fail-closed
(`require_env("SUPABASE_JWT_SECRET")`, #902) and `/docs`/`/openapi.json` are
production-gated — these become verification tests, not builds. Live gaps closed by
this ADR: caller-trusted `approval_id`, absent confirmation authorization, no inbound
rate limiting. **Scope:** Phase P9+P14 of
[`PLAN.md`](../product/agent-workflow-execution/PLAN.md).

## Context

Everything between "seller clicked Approve" and "agent mutated a product" must be
server-verified state, never a caller claim. Six decisions were grilled; a user
directive mid-session generalized confirmations into plan-mode-style decision requests.

## Decision

1. **Approve is run creation, atomically.** No "create run" endpoint and no
   `approval_id` parameter exist on the agent path. `POST
   /v1/demo/decisions/{card_id}/approve` performs one transaction: verify the
   ActionCard belongs to the caller's shop **and** is `active` → flip to `approved` →
   INSERT the `workflow_run` (FK to the card) + an approval audit row (who, when, card
   snapshot) → check the one-run-per-product index → enqueue. Double-approve hits the
   non-`active` status and 409s — raced or sequential, exactly one run can exist. The
   only path to a run is a server-observed card transition; there is nothing to forge
   because there is no claim to make. The legacy `/v1/executions` surface (pre-agent
   dispatcher) is hardened separately by verifying its `approval_id` server-side, but
   is not how agent runs start. Rejected: minted approval tokens (re-proves what the
   card row records); patching the legacy shape as the primary path (keeps a
   caller-supplied authority claim in the API forever).

2. **Decision requests — confirmation generalized to 1..N options (user directive).**
   At a CONFIRM point the agent presents one or more reasoned, HOW-level options
   (plan-mode style): instead of approve/decline on a single price, the agent may
   propose e.g. three price moves — "₫189,000 (undercut category median)", "₫199,000
   (hold margin, fee floor safe)", "₫209,000 (premium with new listing copy)" — each
   with rationale grounded in signals and tool results; likewise title/keyword
   variants for listing updates. The seller picks one or declines all. At pause the runner writes a `run_confirmations` row:
   `{run_id, tool_call_id, options: [{option_id, proposed_change (verbatim JSON — the
   audit is what was shown), rationale, params_sha}], status: pending, created_at}`.
   `workflow.approval_required` gains an **additive** `options[]` payload (envelope
   `v: 1` unchanged); the endpoint accepts `{decision: approve, option_id}` or
   `{decision: decline}`. Authorization ladder, fail-closed and ordered: run under
   caller's shop (else 404) → status `waiting_approval` (else 409) → `tool_call_id`
   matches **the** pending confirmation (else 404) → not expired (else 410; the
   reaper's `confirmation_expired` finishes the run). **Consent binding:** on approve,
   the resume task re-hashes the selected option's params from reconstructed run state
   and executes only on a `params_sha` match — divergence between shown and
   about-to-execute is a hard failure. Single-use: `pending → approved(option_id) |
   declined | expired` exactly once; second POST 409s. **Decline is a conversation,
   not a kill:** the model is told the seller declined, wraps up honestly, and the run
   ends `completed`/`confirmation_declined` — a declined price change must not
   vaporize the analysis already paid for. The row is the consent audit and the
   approval-rate metric source. Binary confirm is the N=1 case. Free-form mid-run
   seller Q&A is a conversational surface deferred with P-CS. Rejected:
   decline-kills-run (conflates seller choice with failure); skipping the hash
   binding (unshown changes could execute).

3. **Authenticated everywhere — including the demo (user choice, strict option).**
   All agent run routes (approve, events/SSE, cancel, confirmations) require Supabase
   JWT via `get_current_user` + `get_active_shop` — one router, one resolution. The
   demo is a real authenticated account whose active shop is the reference shop; no
   special demo dependency exists on the agent path. **P-UI inherits a login
   requirement** (Supabase sign-in or pre-provisioned demo session). Read-only legacy
   demo fixture endpoints are P-UI's call; everything that can create, watch, steer,
   or confirm a run authenticates. A consolidated `assert_agent_runtime_config()` at
   app/worker boot fails the process with a named check: (1) `OPENAI_API_KEY`;
   (2) real broker, never `memory://`; (3) banned-patterns file loads and compiles;
   (4) sandbox-write guard config resolvable for every registered WRITE tool;
   (5) `SUPABASE_JWT_SECRET` present — unconditional; (6) production-write capability
   requires zero unauthenticated route groups (structural backstop). Rejected:
   unauthenticated demo bounded to sandbox (the recommended option — user chose the
   stricter posture); scattered boot checks.

4. **Inbound abuse limits** (existing Redis token bucket pointed inward; keyed by
   shop after auth; config-driven; 429 + `Retry-After` + a security event): approve /
   run creation **5/hour burst 2** per shop; confirmations 30/hour; SSE 10 concurrent
   streams; **cancel is never throttled** — it is the safety valve. Out of scope:
   IP/edge DDoS (proxy concern), per-user sub-quotas, daily token budgets (P10 cost
   observability per ADR-071).

5. **Injection posture assembled + two additions; RLS deferred with a hard trigger.**
   The six layers, auditable as a set: structural (no IDs/credentials/endpoints;
   playbook-scoped tools; approval policy-triggered, never model-requested),
   provenance (source roles; vendor data-never-instructions), content shape (caps +
   signaled truncation; **new:** the sanitizer strips control characters, zero-width/
   invisible Unicode, and bidi overrides from vendor text — closing hidden-text and
   homoglyph channels at the existing chokepoint), output (fail-closed banned-pattern
   guard, both chokepoints), consent (decision request → human → params-hash →
   compare-before-write), blast radius (sandbox writes, iteration/wall-clock caps,
   rate limits). **New:** an adversarial fixture suite — recorded injection attempts
   (instruction-bearing product descriptions, tool-shaped JSON in vendor text,
   invisible-Unicode payloads, seller notes requesting tool unlocks) asserted
   neutralized by the sanitizer and behavior-invariant in the scripted loop; the
   regression net for every future prompt version. **RLS** (13 tables, policies keyed
   to a setting never set) stays deferred: service-layer tenancy is the operative
   enforcement; functional RLS is a **hard precondition on the same list as the
   production-write unlock** — no multi-tenant production launch with real seller
   data before it.

6. **Tests and phase gate.** Approval gate: cross-tenant/nonexistent 404, non-active
   409, raced double-approve → one run, crash-between-flip-and-insert rolls back
   both, in-transaction one-run-per-product rejection. Confirmation: the full ladder;
   params-hash mismatch never executes; single-use 409s; decline →
   `completed`/`confirmation_declined` with an empty ledger for that operation; option
   selection executes exactly the chosen option. Auth: every agent route (including
   the fetch-streamed SSE) 401s without a valid JWT; boot matrix — each of the six
   checks individually unmet fails the process naming the check. Limits: exhaustion →
   429 + security event; cancel unthrottled mid-storm. Injection: fixture suite green
   (sanitizer + scripted loop). Verification: empty `SUPABASE_JWT_SECRET` fails at
   boot; production serves no docs routes. **Gate:** all suites green + a manual
   red-team pass — "create a run without an approval, by any route" and "execute a
   mutation that was never shown" both demonstrably impossible — + security events
   observed for limit violations.

## Consequences

- The approval-rate metric (four-layer metrics) reads straight off `run_confirmations`
  rows, including per-option selection data — which options sellers actually pick
  feeds the future eval pipeline.
- P12's prompt (recommend-within-scope section) gains instruction to present up to N
  reasoned options at CONFIRM points — a prompt-content change riding the existing
  v-bump mechanism, not a new architecture.
- P-UI's spec now includes Supabase sign-in and an option-picker confirmation UI
  (radio selection + rationale display), not just an approve/decline pair.
- The demo's zero-friction invariant is fully retired for the agent surface; the
  structural backstop (check 6) keeps auth posture and write capability coupled even
  if postures drift later.
