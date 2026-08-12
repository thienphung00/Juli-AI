# ADR-073: Agent execution loop — WorkflowRunner, stop_reason termination, idempotent and version-checked writes

**Status:** Proposed
**Date:** 2026-08-11
**Deciders:** grill-with-docs (Architect) with user

**Builds on:** [ADR-068](068-agent-workflow-execution-boundary.md) (WorkflowRunStatus,
tool policy — amended by this session for the production-write target state),
[ADR-069](069-agent-tool-registry-and-write-path.md) (ToolSpecs, `ToolExecution` —
amended: promoted to idempotency ledger), [ADR-070](070-agent-safe-sanitization-contract.md)
(sanitizer, one-retry error rule), [ADR-071](071-llm-service-openai-adapter.md)
(`AssistantTurn` blocks, stateless adapter), [ADR-072](072-agent-prompt-architecture.md)
(`compose()`, `Playbook`).
**Scope:** Phase P1 of [`PLAN.md`](../product/agent-workflow-execution/PLAN.md), plus the
write-path hardening the user directed (idempotency, concurrency, termination policy) —
designed now because they are **prerequisites for the production-write unlock**
(ADR-068 amendment), even though demo writes stay on the sandbox shop.
**Deferral principle (user, 2026-08-11):** P-CS (chat storage) and P7 (structured
output) are deferred; the loop must function without them and expose clean seams to
wire them in later (decision 5).

## Context

The agent loop is where every prior ADR converges: it consumes blocks, prompts, tools,
sanitized results, and statuses, and must survive CONFIRM pauses across processes,
worker retries, and concurrent edits to the same product. Six decisions were grilled.

## Decision

1. **`WorkflowRunner` class with injected protocol dependencies.**
   `services/agent/runner.py` owns the run while it executes: `WorkflowRunStatus`
   transitions, conversation append, block dispatch (`TextBlock` → event;
   `ToolCallBlock` → validate → execute → sanitize → append; `FinalResponse` →
   terminate), and termination-policy evaluation each iteration. Collaborators are
   constructor-injected protocols: `LLMService`, `ToolExecutor`, `EventSink`,
   `ConversationStore`. The run's state (conversation window, iteration count, pending
   confirmation, basis snapshots) is an explicit object serialized to a
   **`workflow_runs.state` JSONB blob** — written per iteration and on pause, reloaded
   on resume, so a CONFIRM pause can resume in a different worker process. The Celery
   task (P8) is a thin shell: load context → construct runner → run. Rejected: free
   async function (state in locals — reinvents the state object the week CONFIRM
   lands); loop inline in the Celery task (integration-only tests; contradicts D3 and
   ADR-071's fake-LLMService double).

2. **Declarative termination policy + total `stop_reason` vocabulary.** The `Playbook`
   (ADR-072) gains a `TerminationPolicy`: for Optimize Product v1 —
   `max_iterations=6` (soft; one iteration = one `LLMService.complete()` call),
   `max_extensions=1` (+2 iterations each), `wall_clock_timeout_s=300` measured over
   **running time only** (the clock pauses during `waiting_approval`),
   `approval_timeout_h=4`, and `required_steps` naming the steps whose completion
   defines "did the job". Every loop exit records exactly one `stop_reason` on
   `workflow_runs` — no silent exits — with a **total mapping** to `WorkflowRunStatus`
   asserted by a test:

   | stop_reason | status |
   |---|---|
   | `final_response`, `confirmation_declined` | `completed` |
   | `paused_for_confirmation` | `waiting_approval` |
   | `cancelled_by_seller`, `confirmation_expired` (4h unanswered CONFIRM) | `cancelled` |
   | `iteration_cap_exceeded`, `wall_clock_timeout` | `timed_out` |
   | `tool_error_unrecoverable`, `llm_error`, `concurrency_conflict`, `output_validation_failed` (reserved for P7) | `failed` |

   The model may propose **`continue`** at the soft cap: the runner auto-grants up to
   `max_extensions` extensions (hard cap 6+2=8), emitting a visible `workflow.status`
   event per grant; the hard cap fails the run. `stop_reason` records *how* the loop
   ended; whether it *did the job* (`required_steps` completed) is an outcome fact on
   the run record feeding the execution-quality metric — a `final_response` without the
   required mutation is honest data, not a synthetic failure. Cancellation is
   **checkpoint-based, never preemptive**: `cancel_requested` on the run row is checked
   at the top of each iteration and before each tool execution; an in-flight mutation
   is never interrupted.

3. **Idempotent mutation execution — `ToolExecution` promoted to ledger.** Unique key
   `(workflow_run_id, tool_call_id, operation)` with states `in_flight → succeeded |
   failed`; `tool_call_id` is the LLM block ID, stable across worker retries because
   the conversation is rebuilt from persisted run state. Write path (reads skip the
   ledger): SELECT by key — `succeeded` → return the **stored sanitized result** (the
   retried conversation replays byte-identically, no API call); `in_flight` →
   **verify-then-decide**: re-read TikTok state and compare against the intended
   mutation — applied → mark succeeded retroactively; not applied → re-execute; an
   operation not verifiable by read-back fails closed (`tool_error_unrecoverable`) —
   never a maybe-duplicate write. No record → INSERT `in_flight` (a concurrent
   duplicate loses on the unique index) → call TikTok → UPDATE. Rejected: separate
   mutation-ledger table (1:1 shadow of ToolExecution); Celery exactly-once (doesn't
   exist — Celery is at-least-once, which is why the ledger is needed).

4. **Concurrency control — basis-hash versioning + one-run-per-product.** TikTok
   exposes no product version number, so version = a server-held SHA of the mutable
   fields (title, description, price, images) captured when the agent reads the
   product (**basis snapshot**, held in run state, invisible to the LLM). Immediately
   before any write, `ToolExecutor` re-reads the product and recomputes the hash over
   the fields that write mutates: match → proceed; mismatch → the write is rejected
   **before signing** (fail-closed, like the transport guards) and the conflict
   returns to the LLM once as a sanitized structured result (`{conflict: true,
   current_values: …}`) for one bounded re-proposal; a second conflict on the same
   operation stops the run (`concurrency_conflict`). Juli-vs-Juli races are prevented
   structurally: a partial unique index on active runs `(shop_id, product_id) WHERE
   status IN (queued, running, waiting_approval)` fails the second run at enqueue,
   before any LLM cost. Rejected: last-write-wins (the bug); lock-only (cannot lock
   the seller); unbounded revalidation (infinite loop against an actively-editing
   seller).

5. **Deferral seams (P-CS, P7).** The loop functions without both and wires to both
   without refactor: P-CS's stand-in is the `workflow_runs.state` blob behind the
   `ConversationStore` protocol — full Redis/Postgres chat storage later swaps the
   implementation, not the runner; P7's stand-in is ADR-072's prose output guidance
   (final response = text + actions list) — the machine schema later attaches at the
   `FinalResponse` block and the prompt's v2 bump. `output_validation_failed` is
   reserved in the enum now so P7 adds no vocabulary.

6. **Test strategy and phase gate.** Pure-unit scenario suite against the fake
   `LLMService`: one scripted scenario per `stop_reason` (including extension granted
   then exhausted, paused-clock assertion, cancel at both checkpoints, conflict →
   revalidate → success and conflict → conflict → stop); the total-mapping test;
   idempotency tests (stored-result replay without API call, both verify-then-decide
   branches, unique-key race); pause/resume round-trip (serialize at
   `waiting_approval`, reconstruct a fresh runner from the blob, complete) — the P-CS
   kill-and-resume gate in miniature; self-correction (malformed tool params returned
   to the model once). Behind the `live` marker, **two smokes**: (a) a real GPT-5.4
   nano Optimize Product run with read-only tools reaching `final_response`; (b) a
   full write-path run — CONFIRM pause, ledger, compare-before-write — executing
   against the **sandbox shop**. Gate: full matrix + mapping + round-trip green; both
   smokes complete; `stop_reason` and `state` columns exist on `workflow_runs`.

## Consequences

- P8 wraps the runner in Celery unchanged and gets replay-stable events; the
  production-write unlock (ADR-068 amendment) is now a capability-grant flip whose
  safety machinery (ledger, compare-before-write) is already exercised by the sandbox
  smoke.
- The run-state blob is a single-row working set — fine for demo scale; if runs ever
  need high-frequency state writes, the P-CS store absorbs them (documented seam).
- One active run per product means a seller cannot queue a second optimization while
  one waits for approval — accepted; expiry (4h) bounds the blocking window.

## Amendment — `worker_lost` and reaper enforcement (2026-08-12, [ADR-074](074-agent-event-streaming-and-relay.md))

One additive `stop_reason` member: **`worker_lost`** (→ `failed`) — assigned by
ADR-074's reaper to runs whose worker died twice (crash + failed redelivery), keeping
the execution-quality metric honest about infrastructure deaths vs task failures. The
reaper is also where `approval_timeout_h` physically runs: `waiting_approval` past 4h
→ `confirmation_expired` → `cancelled`. The total-mapping test covers both.
