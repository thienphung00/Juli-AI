# Module: demo

## Responsibility

Standalone public-facing Next.js Demo for Juli's four-destination product shape.
Analytics, Recommendations and agent runs read live `/v1/demo/*` endpoints; Home
and Settings remain deterministic mock fixtures.

## Public interface

- `/` — sparse Home launcher with exactly two cards: Quyết định and Phân tích.
- `/decisions`, `/analytics`, `/settings` — discoverable shell destinations;
  content is delivered by later vertical slices.
- `DemoShell` — responsive four-destination application frame.
- `DemoStateProvider` / `useDemoState` — single owner for mutable mock state,
  persisted Mock mode, disabled Sign-in feedback, deterministic reset, and
  `startExecution(workflowKey)` for approved workflow records.
- `lib/executions.ts` — Workflow 1 + post-sales (7–9) timeline fixtures and pure
  `startExecution` for review-executable keys only.
- `lib/plan-reviews.ts` / `lib/plan-caveats.ts` — the [ADR-055](../../docs/adr/055-decision-plan-review.md)
  sectioned agent-proposed plan review that replaced the five-stage review, composed
  per workflow from `lib/workflows/`; `lib/reviews.ts` keeps the input defaults.
- `lib/workflows/` — per-workflow plan review, caveats and seller copy, one directory
  per demo workflow key. FBT return intake stays non-executable.
- `lib/recommendations.ts` — Decisions read against `GET /v1/demo/recommendations`.
- `lib/agent-event-stream.ts` — fetch-streaming SSE transport for
  `GET /v1/demo/runs/{run_id}/events` (ADR-074 d.5).
- `lib/repeat-consent.ts` — the post-completion repeat-consent ask (ADR-055 item 19).
- `lib/review-seller-copy.ts` — seller-facing plan-review copy, banned-pattern guarded.
- `lib/settings/` — Settings fixtures, validation and save.
- `RecommendationsPanel` / `InProgressPanel` — Decisions tab panels composed by
  `RecommendationsView`.
- `AnalyticsDataProvider` / `fetchDemoAnalytics` — Phase 2.10-A live Analytics read via `GET /v1/demo/analytics` (Home and Settings remain mock).

## Dependencies

- `@juli/contracts` — execution, review stage, and Demo Analytics envelope types.
- `@juli/theme` — semantic tokens.
- `@juli/ui` — accessible destination cards and primary navigation.
- `@juli/utils` — Vietnamese date/number formatting.

## Invariants

- Home contains no KPI, recommendation action, execution queue, template, or threshold.
- User-visible copy is Vietnamese with correct diacritics.
- Analytics (`/analytics`) performs read-only `GET /v1/demo/analytics` (no force-recompute); Home and Settings remain mock fixtures.
- Analytics, Recommendations and agent runs read live endpoints (`/v1/demo/analytics`,
  `/v1/demo/recommendations`, `/v1/demo/refresh`, `/v1/demo/runs` SSE); Home and
  Settings remain mock. Under [ADR-094](../../docs/adr/094-demo-surface-splits-anonymous-replay-and-signed-in-runs.md)
  the anonymous entry is a client replay that calls nothing, and signed-in users get
  real runs.
- Manual Refresh re-fetches Analytics envelopes, resets mutable mock-state, and returns to
  `/decisions`, whose default view is Recommendations.
- Contextual Juli assistance explains the active destination and never
  authorizes approval, rejection, or execution.
- Every navigation target is keyboard accessible with a visible focus state and
  at least a 44×44px target.
- The app never imports a sibling app.

## Owners

- domain: web
- code: `apps/demo/`
