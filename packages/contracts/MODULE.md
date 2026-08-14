# Module: contracts

## Responsibility

Shared typed contracts for execution lifecycle, review stages, and workflow input
descriptors introduced in Phase 2.6. Demo apps import these shapes; fixture prose
remains in app-level libs until a later migration.

## Public interface

- `ExecutionTimelineStepStatus` — pending, running, succeeded, failed.
- `ExecutionLifecycleStatus` — needs_input, executing, completed.
- `ExecutionTimelineStep` — numbered action/wait/outcome step with optional recovery.
- `ExecutionRecord` — one approved workflow execution with timeline and input snapshot.
- `ReviewStage` / `ReviewStageContent` — five-stage recommendation review copy.
- `ReviewInputFieldDescriptor` — editable Inputs-stage field metadata.
- `DemoAnalyticsEnvelope` / `AnalyticsKpiEntry` — masked public Analytics KPI envelope (#525/#531); `gmv_tiktok` label law, no `net_revenue` alias.
- `deriveLifecycleFromTimeline(timeline)` — maps step states to lifecycle status.
- `SELLER_COPY_BANNED_PATTERNS` — compiled `RegExp[]` built from
  `seller-copy-banned-patterns.json` (ADR-070 decision 6, #990), the single
  language-neutral banned-pattern source also loaded by the Python agent guard
  (`backend/src/juli_backend/services/agent/sanitize`). Extraction only — this
  package must never add, remove, or alter a pattern without updating the JSON
  and re-verifying `tests/unit/test_agent_banned_patterns_contract.py`.
- `AgentEvent` (`agent-events.ts`, ADR-074 decision 2, #1125/#1126, AGT-W3B) —
  discriminated union (on `event_type`) mirroring the eight
  `workflow_run_events` Pydantic event types in
  `backend/src/juli_backend/services/agent/events/{payloads,envelope}.py`
  field-for-field. `assistant.text.delta` (ADR-071) has no member and never
  will in this slice. `validateAgentEvent` is a hand-rolled runtime
  structural check (no schema library — ADR-074 d.2 rejects adding one) that
  throws naming the offending `event_type`; `PAYLOAD_FIELDS`/
  `ENVELOPE_FIELDS` expose the exact field sets for cross-language diffing.
  Golden fixtures (one per event type, plus an envelope-`v:1` snapshot and
  negative fixtures) live in `packages/contracts/fixtures/agent-events/` and
  are tested byte-equal-in-shape from both languages by
  `tests/unit/test_agent_events_contract.py`.

## Dependencies

- None (pure TypeScript types and helpers) besides `resolveJsonModule` (tsconfig
  flag, not a package) to read `seller-copy-banned-patterns.json`.

## Invariants

- Helpers are pure and perform no network or environment access.
- Lifecycle values match `demo-state` and In Progress design docs exactly.
- This package never imports an app.

## Owners

- domain: web
- code: `packages/contracts/`
