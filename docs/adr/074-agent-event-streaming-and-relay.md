# ADR-074: Agent event streaming — Postgres-authoritative event log, Redis relay, SSE over fetch-streaming

**Status:** Proposed
**Date:** 2026-08-12
**Deciders:** grill-with-docs (Architect) with user

**Builds on:** [ADR-068](068-agent-workflow-execution-boundary.md) (WorkflowRunStatus),
[ADR-071](071-llm-service-openai-adapter.md) (turn-level blocks; `assistant.text.delta`
reserved), [ADR-073](073-agent-execution-loop-and-write-path-hardening.md)
(`WorkflowRunner`, run-state blob, `stop_reason`, checkpoint cancellation, one active
run per product — amended by this session: additive `worker_lost`).
**Locked upstream (not re-decided):** SSE transport with the D2 event names; Celery
worker + event relay (D3); the canonical event record
`{workflow_run_id, sequence_number, event_type, timestamp, payload}` with **Postgres as
replay authority and Redis as best-effort delivery** (user fix 2, 2026-08-11).
**Scope:** Phase P8 of [`PLAN.md`](../product/agent-workflow-execution/PLAN.md).
**Provider note:** the stream is Juli's own protocol generated from neutral
`AssistantTurn` blocks — switching the LLM provider touches only the ADR-071 adapter,
never this layer.

## Context

The event log is the stream: anything a client sees must exist as a
`workflow_run_events` row first; Redis only makes it fast. Six decisions were grilled.

## Decision

1. **Runner-owned sequence numbers.** The `WorkflowRunner` holds `next_sequence` in its
   run-state blob; each emit assigns `seq = next_sequence++` and inserts the row. Safe
   because exactly one writer per run exists (partial unique index + one Celery task);
   a unique index on `(workflow_run_id, sequence_number)` converts crash-replayed
   emits into no-ops. Rejected: per-run Postgres counter (insures against a
   structurally prevented state, +1 round-trip per event); global sequence (gaps on
   rollback break the exact "events after 47" contract).

2. **Typed event union, fixture-pinned in both languages.** Eight event types with an
   envelope `{workflow_run_id, sequence_number, event_type, timestamp, payload, v: 1}`;
   SSE wire: `id:` = sequence_number, `event:` = event_type, `data:` = envelope JSON.
   `workflow.started {workflow_key, product_ref, prompt_version}`;
   `workflow.status {phase_narration}` (VI copy; also carries extension grants);
   `assistant.text {text}`; `tool.started {tool_call_id, tool_name}`;
   `tool.completed {tool_call_id, tool_name, ok, summary}`;
   `workflow.approval_required {tool_call_id, tool_name, proposed_change, expires_at}`;
   `workflow.completed {stop_reason}`; `workflow.failed {status, stop_reason}` — the
   failure-class terminal covering `failed`/`cancelled`/`timed_out` (clients render two
   terminal shapes; `stop_reason` carries the precision, ADR-073's total mapping stays
   the single authority). `assistant.text.delta` remains reserved. Contract sharing:
   Pydantic models are the emitting source; `packages/contracts/src/agent-events.ts`
   mirrors the discriminated union; one golden fixture per event type lives in
   `packages/contracts` and both sides test against the same files. Rejected: distinct
   cancelled/timed_out event types (two more cases rendering identically); codegen TS
   from JSON Schema (build step + generated churn for 8 types).

3. **Sink and SSE mechanics.** `PersistingEventSink` (the production `EventSink`):
   INSERT + commit first — the event now exists — then PUBLISH to
   `run_events:{workflow_run_id}`; publish failure is logged and swallowed (liveness
   degrades, correctness doesn't; a subscriber can never see an uncommitted event).
   SSE endpoint: resolve `after_seq` (`Last-Event-ID` header or `?after=`, default 0);
   **subscribe before replay** (closes the replay-end→subscribe-start gap); replay
   from Postgres in order; stream live through server-side seq-dedupe (`last_sent`
   tracking — clients never deduplicate); 15s heartbeat comments; terminal event
   closes the stream (a run already terminal at connect replays and closes — late
   joiners free). If subscribe fails, degrade to polling Postgres every 2s — Redis is
   optional for availability, not just correctness. Rejected: publish-then-insert
   (phantom events); replay-then-subscribe (needs a second catch-up pass).

4. **Celery wiring and the reaper.** Real Redis broker via `CELERY_BROKER_URL` in
   agent-enabled deployments (`memory://` stays the unit-test default) with a
   fail-closed startup assertion (ADR-071 key-assertion pattern) — agent workflows on
   a memory broker crash at boot. Dedicated `agent_runs` queue so multi-minute runs
   never starve beat/analytics tasks. Two tasks: `run_agent_workflow(run_id)` and
   `resume_agent_workflow(run_id, tool_call_id, decision)` (P9 owns the authorization
   endpoint that enqueues the latter). `acks_late=True, max_retries=1`: a worker crash
   redelivers once; the retried worker reconstructs from the run-state blob —
   at-least-once delivery absorbed by the idempotent event emit (decision 1) and
   mutation ledger (ADR-073). A **reaper** beat task every 5 minutes closes the two
   abandonment holes through the normal sink, so connected clients watch runs die
   honestly: stale `running`/`queued` (no event for `wall_clock_timeout_s` + slack, no
   live task) → `stop_reason: worker_lost` (**additive ADR-073 enum member**, → `failed`;
   reusing `tool_error_unrecoverable` would corrupt the execution-quality metric), and
   `waiting_approval` past the 4h `approval_timeout_h` → `confirmation_expired` →
   `cancelled` (ADR-073 defined the policy; the reaper is where it physically runs).

5. **Endpoints and auth.** `GET /v1/demo/runs/{run_id}/events` (SSE),
   `POST /v1/demo/runs/{run_id}/cancel` (202, idempotent), and the reserved shape
   `POST /v1/demo/runs/{run_id}/confirmations/{tool_call_id}` `{decision}` implemented
   by P9. Every run route resolves the run under the caller's active shop
   (`get_active_shop` pattern); cross-tenant IDs **404, never 403** (no existence
   oracle). The client consumes SSE via **fetch + ReadableStream** (e.g.
   `@microsoft/fetch-event-source` shape), not native `EventSource`: bearer auth stays
   in headers (no credential in URLs/logs/history), reconnect is owned (we track
   sequence numbers anyway), failures are inspectable (401 vs 404 vs 500), and
   `AbortController` cancels cleanly. Rejected: EventSource + minted short-lived
   stream tokens (a token-minting subsystem costs more than the ~100-line parser it
   avoids, for a weaker posture); deferring auth (cross-tenant-readable streams).

6. **Test strategy and phase gate.** Units: sink ordering (publish only after commit;
   swallowed publish failure; replay no-op) and reaper decisions (both closures + no
   false kill at the boundary). Contract: golden fixtures green in both languages;
   envelope snapshot pins `v: 1`. Integration (real Postgres, fake pub/sub): exact
   replay (`after=k` → exactly k+1..N, ordered, no duplicates); handoff overlap
   (events published during replay arrive exactly once); Redis loss (fallback polling
   delivers; reconnect replays gapless — fix 2's acceptance test automated);
   lifecycle (terminal close, late joiner, cancel at checkpoint visible on stream);
   crash-resume (task run twice against one blob → no duplicate events, one
   completion). Gate: all of the above green + one observed browser E2E (live run,
   offline-toggle reconnect) + the boot assertion verified.

## Consequences

- The client's streaming code is protocol-version-aware from day one (`v: 1`
  envelope); `assistant.text.delta` and new event types are additive.
- The reaper gives every abandonment path an owner; no run can stay `running` forever
  or hold the one-run-per-product index hostage.
- Redis remains fully disposable: flush or lose it and every open stream degrades to
  2s polling while reconnects replay from Postgres.
- P-UI consumes the fetch-streaming client and event union as-is; P9 fills in the
  confirmation route's authorization without touching transport.
