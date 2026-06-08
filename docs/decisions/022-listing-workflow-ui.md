# ADR 022: Listing Workflow UI State Machine

## Status
Accepted

## Context

- [ADR-020](020-new-seller-listing-workflow-scope.md) scoped Phase 1.6 dual-path listing
  workflow launched from approved `list_products` copilot tasks.
- Issue #154 shipped the rules engine (`generateProductDraft`); issue #155 implements
  the client-side UI state machine and modal workflow shell.
- `docs/architecture/map.md` gains a deployed row for
  `web/src/components/workflows/new-seller/listing/`.

## Decision

- We will: launch listing workflow as a modal overlay from `TaskQueue` when
  `list_products` is approved; other task types retain Phase 1 no-op feedback.
- We will: implement Path A (product form → distributor → draft review) and Path B
  (constraints → opportunity browse → distributor → draft review) as a pure reducer
  with session-scoped React state — no new route, no backend calls.
- We will: call `generateProductDraft` (#154) when entering draft review; export
  step remains a placeholder until #156.
- We will not: persist drafts in Postgres, call TikTok API, or add cloud LLM in P1.6.

## Rationale

Modal entry preserves copilot continuity (recommend → approve → workflow). A small
state-machine module keeps navigation testable without XState or server sessions.
Reusing the rules engine at draft review avoids duplicating compliance/readiness logic.

## Consequences

- **Positive:** E2E copilot → workflow path validated in UI-only mode; #156 export
  plugs into existing export placeholder step.
- **Negative:** Session state is lost on full page reload (acceptable for P1.6 demos).
- **Follow-ups:** CSV/JSON export (#156); shop progress widget (#157).
