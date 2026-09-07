# Module: demo

## Responsibility

Standalone public-facing Next.js Demo for Juli's four-destination product shape.
Phase 2.6 uses deterministic mock data and has no backend or authentication
dependency.

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
- `lib/reviews.ts` — Five-stage review content and input defaults for Workflow 1
  and workflows 7–9 (`prevent_cancellation_8a`, `prevent_return_8b`,
  `prevent_refund_8c`); FBT return intake key stays non-executable.
- `RecommendationsPanel` / `InProgressPanel` — Decisions tab panels composed by
  `RecommendationsView`.
- `lib/recommendations.ts` — `fetchRecommendations()`'s route constant now
  matches the server-side route that actually exists (`GET /v1/demo/decisions`,
  `backend/src/juli_backend/api/routes/demo_decisions.py`), and the function
  itself never falls back to `recommendationFixtures` on a failed or malformed
  fetch (#1320, partial — see Invariants). It is not yet called from
  `RecommendationsPanel`/`RecommendationsView`: those still render
  `recommendationFixtures` directly and unconditionally, as before this
  change. Wiring the live call into that shared component is **not** done in
  this diff (see Invariants for why).
- `AnalyticsDataProvider` / `fetchDemoAnalytics` — Phase 2.10-A live Analytics read via `GET /v1/demo/analytics` (Home/Settings/Decisions remain mock).

## Dependencies

- `@juli/contracts` — execution, review stage, and Demo Analytics envelope types.
- `@juli/theme` — semantic tokens.
- `@juli/ui` — accessible destination cards and primary navigation.
- `@juli/utils` — Vietnamese date/number formatting.

## Invariants

- Home contains no KPI, recommendation action, execution queue, template, or threshold.
- User-visible copy is Vietnamese with correct diacritics.
- Analytics (`/analytics`) performs read-only `GET /v1/demo/analytics` (no force-recompute); Home, Settings, and Decisions remain mock fixtures.
- Mock is the only enabled mode; Sign-in remains focusable for truthful
  coming-soon feedback but never routes or requests data.
- `RecommendationsPanel`/`RecommendationsView` make no backend request or
  real write anywhere in the recommendations flow (asserted in
  `decisions-recommendations.test.tsx`) — this is deliberately **not**
  changed by #1320's path fix. `fetchRecommendations()` targeting the real
  `GET /v1/demo/decisions` route no longer masks a failure with
  `recommendationFixtures` (issue #1320's defects 2 and 3, at the function
  level), but the function is not called from this component: doing so today
  would (a) break the "no backend request" invariant just above, since this
  single component tree currently serves both the anonymous replay and any
  future signed-in visitor identically — there is no split at this layer yet
  (ADR-094, #1319, not yet landed on this branch) — and (b) make the
  anonymous "Dùng thử Demo" replay issue a live `/v1/*` request, which
  ADR-094 forbids outright. Wiring the live call in belongs with (or after)
  the anonymous/signed-in split, not before it — the same "delete before the
  replacement exists" risk the issue's own dependency ordering warns about.
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
