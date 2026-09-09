# Module: demo

## Responsibility

Standalone public-facing Next.js Demo for Juli's four-destination product shape.
The blanket "no backend or authentication dependency" claim from Phase 2.6 no
longer holds app-wide and is retired here (issue #1321) — Analytics, the
signed-in Decisions/run surfaces, and Đăng nhập với Google all depend on the
real backend and Supabase Auth. What remains true, surface by surface, is in
Invariants below.

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
- **The staged run view (issues #1316/#1317/#1319/#1752, ADR-076 decision 3/4, ADR-094).** `RunDetailRoute` (`components/run-detail-route.tsx`) dispatches on whether a bearer `token` is present — the same absence-as-signal `useRunStream` itself gates on:
  - **Signed-in (token present):** `SignedInRunDetail` calls `fetchDemoRuns` (`lib/run-ledger/api-client.ts`, real `GET /v1/demo/runs`) to resolve the run, then `useRunStream(runId)` (`lib/run-surface/use-run-stream.ts`) opens the real SSE transport (`lib/agent-event-stream.ts`) with reconnect/backoff via `Last-Event-ID`. `RunStagedView` renders the live event fold; `OptionPicker`'s confirm/decline calls `submitConfirmationDecision` (`lib/run-surface/confirmation-client.ts`), a real bearer-authenticated `POST /v1/demo/runs/{id}/confirmations/{tool_call_id}`. This path is live-backed end to end.
  - **Replay/anonymous (no token):** `ReplayRunDetail` seeds `RunStagedView` from `useReplayEvents` (`lib/run-surface/use-replay-events.ts`), which reveals the one bundled, tool-captured golden scenario (`lib/run-surface/golden-scenarios/optimize_product_confirm_pause.json`, imported statically — never fetched, verified absent-from-build-fails-loudly by `scripts/verify-replay-scenario-in-build.mjs`) paced by its own captured inter-event deltas, rebased to now. Reaching and viewing this run issues zero `/v1/*` requests — matches `RunDetailRoute`'s own test, `run-detail-route.test.tsx`'s "replay path ... zero /v1/* requests" case.
- `RunStagedView` / `RunStepper` / `RunStageCanvas` / `OptionPicker` — the one-stage-at-a-time canvas, top stepper, and consent-grade option picker (PUI-DESIGN.md §2/§3); shared verbatim by both doors above, so replay and signed-in render identically by construction.

## Dependencies

- `@juli/contracts` — execution, review stage, and Demo Analytics envelope types.
- `@juli/theme` — semantic tokens.
- `@juli/ui` — accessible destination cards and primary navigation.
- `@juli/utils` — Vietnamese date/number formatting.

## Invariants

- Home contains no KPI, recommendation action, execution queue, template, or threshold.
- User-visible copy is Vietnamese with correct diacritics.
- Analytics (`/analytics`) performs read-only `GET /v1/demo/analytics` (no force-recompute); Home, Settings, and Decisions remain mock fixtures.
- Dùng thử Demo stays sessionless and issues no request; Đăng nhập với Google
  (issue #1319) is real — it routes to Supabase Auth and, from the
  connect-shop screen, makes a real bearer-authenticated `GET /v1/shops` call.
- `RecommendationsPanel`/`RecommendationsView` make no backend request or
  real write anywhere in the recommendations flow (asserted in
  `decisions-recommendations.test.tsx`) — this is deliberately **not**
  changed by #1320's path fix. `fetchRecommendations()` targeting the real
  `GET /v1/demo/decisions` route no longer masks a failure with
  `recommendationFixtures` (issue #1320's defects 2 and 3, at the function
  level), but the function is not called from this component: doing so today
  would (a) break the "no backend request" invariant just above, since this
  single component tree still serves both the anonymous replay and a
  signed-in visitor identically — #1319 split the *entry points*, not this
  component tree — and (b) make the anonymous "Dùng thử Demo" replay issue a
  live `/v1/*` request, which ADR-094 forbids outright. Wiring the live call
  in belongs with the component-level anonymous/signed-in split, not before
  it — the same "delete before the replacement exists" risk the issue's own
  dependency ordering warns about.
- Manual Refresh re-fetches Analytics envelopes, resets mutable mock-state, and returns to
  `/decisions`, whose default view is Recommendations.
- **The staged run view's no-backend invariant is retired for the SIGNED-IN
  door only (issue #1321).** The signed-in path is live-backed: real run
  lookup (`GET /v1/demo/runs`), a real SSE connection, and a real
  bearer-authenticated confirmation POST — see Public interface above. The
  REPLAY/anonymous door stays request-free for *reaching and viewing* a run,
  exactly as ADR-094 decision 1 requires — verified directly against a
  running build, not inferred.
- **Approving "Tối ưu sản phẩm" from Decisions reaches this captured run's
  staged view (issue #1320 part 2 / #1762).** The list card's "Phê duyệt"
  navigates to the review page; a second "Phê duyệt" in
  `.demo-plan__actions` arms a `ConfirmDialog` (two-step consent, #1317);
  confirming inside that dialog is what triggers `onApproveConfirm`'s push
  to `/decisions/in-progress/{REPLAY_SCENARIO_RUN_ID}`
  (`recommendation-review.tsx`). Verified end to end by
  `e2e/exit-gate/replay-run-journey.spec.ts` walking the real click path
  including the consent gate — not by a direct URL.
- **Known gap, verified against this branch, not yet fixed here — tracked
  as issue #1764.** The replay door's Đề xuất option picker has no
  replay-local confirm path. Selecting an option and clicking "Xác nhận
  phương án này" or "Không thực hiện" in the anonymous replay currently
  falls through to `OptionPicker`'s default `confirm =
  submitConfirmationDecision` — the same real, bearer-less `POST
  /v1/demo/runs/{id}/confirmations/{tool_call_id}` the signed-in door uses,
  observed 404ing (no backend session backs the replay door) and leaving
  the run stuck in a "cannot be confirmed" state. This contradicts ADR-094
  decision 1. `e2e/exit-gate/replay-run-journey.spec.ts` asserts this fails
  loudly (no rejection alert) immediately after the confirm click, and is
  expected to keep failing there until #1764 lands — a replay-local
  confirm that resolves from the captured scenario's own
  `continuations.approve`/`continuations.decline` without a network call
  does not exist yet.
- **A second known gap, same investigation:** the captured golden scenario's
  `workflow.approval_required.expires_at` (`2026-08-28T12:32:13.308159Z`) is
  never rebased — only the envelope's own `timestamp` is shifted to "now"
  (`lib/run-surface/replay-scenario.ts`'s `rebaseEvent`). Once real
  wall-clock time passes that fixed date, the option picker renders
  permanently expired for every visitor. Not fixed here — out of this
  issue's file boundary; worked around for test determinism only via a
  pinned fake clock in the e2e spec, never in production source.
- Contextual Juli assistance explains the active destination and never
  authorizes approval, rejection, or execution.
- Every navigation target is keyboard accessible with a visible focus state and
  at least a 44×44px target.
- The app never imports a sibling app.

## Owners

- domain: web
- code: `apps/demo/`
