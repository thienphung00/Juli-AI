# Module: demo

## Responsibility

Standalone public-facing Next.js Demo for Juli's four-destination product shape.
The blanket "no backend or authentication dependency" claim from Phase 2.6 no
longer holds app-wide and is retired here (issue #1321) — Analytics, the
signed-in Decisions/run surfaces, and Đăng nhập với Google all depend on the
real backend and Supabase Auth. What remains true, surface by surface, is in
Invariants below.

## Public interface

- `/` — sparse Home launcher with exactly two cards: Hành động and Phân tích.
- `/decisions`, `/analytics`, `/settings` — discoverable shell destinations;
  content is delivered by later vertical slices.
- `DemoShell` — responsive four-destination application frame. **Exception
  (#1910, PUI-DESIGN.md §2, owner amendment 2026-09-14):** the real run route
  (`/decisions/in-progress/<id>` where `looksLikeRunId(id)`, the one matcher in
  `lib/run-surface/run-id.ts`) renders WITHOUT the shell chrome — no
  `demo-header`, no `demo-feedback` strip, no `demo-assistance` aside, no mode
  toggle — while the `PrimaryNavigation` rail STAYS; the run surface owns the
  whole region to the rail's right. `RunStagedView` supplies the §2 header row
  itself (`RunHeader`: `← Hành động` back control to `/decisions`, the
  `RUN_WORKFLOW_TITLE` heading, and a dictionary-governed status chip — never
  a raw `stop_reason`). Legacy mock `exec-*` execution details keep the full
  shell.
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
- `lib/recommendations.ts` — network-free fixtures and href builders for the
  ANONYMOUS branch only. The authenticated clients live in
  `lib/recommendations-api-client.ts` (#1772): `fetchRecommendations()`
  reads the real `GET /v1/demo/decisions` (parsing its actual
  `DemoDecisionListResponse` envelope from `@juli/contracts`) and
  `approveDemoDecision()` performs the real
  `POST /v1/demo/decisions/{id}/approve` — both bearer-authenticated with
  `X-Shop-Id`, both called from `SignedInDecisions` (issue #1909), and
  neither ever falls back to `recommendationFixtures` on a failed or
  malformed fetch (#1320).
- `SignedInDecisions` (`components/signed-in-decisions.tsx`, issue #1909) —
  the signed-in Decisions branch's OWN module, mirroring
  `replay-run-detail.tsx`'s split in the opposite direction: it alone
  imports the authenticated Decisions clients, renders the acting shop
  (`lib/shop-session.ts`, written by the connect-shop screen), and on a
  consented approve navigates to `/decisions/in-progress/{run_id}` using
  the `run_id` from the approve response — never a client-constructed id.
  `DecisionsPageClient` selects it when `readAuthSession()` finds a stored
  session; with none, the anonymous `RecommendationsView` renders
  unchanged.
- `AnalyticsDataProvider` / `fetchDemoAnalytics` — Phase 2.10-A live Analytics read via `GET /v1/demo/analytics` (Home/Settings/Decisions remain mock).
- **The staged run view (issues #1316/#1317/#1319/#1752/#1909, ADR-076 decision 3/4, ADR-094).** `RunDetailRoute` (`components/run-detail-route.tsx`) dispatches on whether a bearer `token` is present — the same absence-as-signal `useRunStream` itself gates on. Since issue #1909 that token is actually supplied: the `[executionId]` page's `RunDetailDoor` reads `readAuthSession()` and passes `token` (plus the acting shop's `shopId`) when a session is stored — before #1909 no caller passed one, so the signed-in door below was unreachable from any browser:
  - **Signed-in (token present):** `SignedInRunDetail` calls `fetchDemoRuns` (`lib/run-ledger/api-client.ts`, real `GET /v1/demo/runs`) to resolve the run, then `useRunStream(runId)` (`lib/run-surface/use-run-stream.ts`) opens the real SSE transport (`lib/agent-event-stream.ts`) with reconnect/backoff via `Last-Event-ID`. `RunStagedView` renders the live event fold; `OptionPicker`'s confirm/decline calls `submitConfirmationDecision` (`lib/run-surface/confirmation-client.ts`), a real bearer-authenticated `POST /v1/demo/runs/{id}/confirmations/{tool_call_id}`. This path is live-backed end to end.
  - **Replay/anonymous (no token):** `ReplayRunDetail` seeds `RunStagedView` from `useReplayEvents` (`lib/run-surface/use-replay-events.ts`), which reveals the one bundled, tool-captured golden scenario (`lib/run-surface/golden-scenarios/optimize_product_confirm_pause.json`, imported statically — never fetched, verified absent-from-build-fails-loudly by `scripts/verify-replay-scenario-in-build.mjs`) paced by its own captured inter-event deltas, rebased to now. Reaching and viewing this run issues zero `/v1/*` requests — matches `RunDetailRoute`'s own test, `run-detail-route.test.tsx`'s "replay path ... zero /v1/* requests" case.
- `RunStagedView` / `RunStepper` / `RunStageCanvas` / `OptionPicker` — the one-stage-at-a-time canvas, top stepper, and consent-grade option picker (PUI-DESIGN.md §2/§3); shared verbatim by both doors above, so replay and signed-in render identically by construction.
- `POST /api/tt/event` — the TikTok Events API relay, sharing one data source
  with `apps/landing`. Same-origin, so an ad blocker that stops the pixel does
  not stop this. Accepts only this site's own origins (`lib/site-origins.ts`)
  and only the events in `@juli/tiktok-events`'s allowlist. It reaches TikTok,
  never `juli-api`, so it is outside every `/v1/*` claim below.

## Dependencies

- `@juli/contracts` — execution, review stage, and Demo Analytics envelope types.
- `@juli/theme` — semantic tokens.
- `@juli/ui` — accessible destination cards and primary navigation.
- `@juli/utils` — Vietnamese date/number formatting.
- `@juli/tiktok-events` — TikTok pixel, event vocabulary, and the relay handler.

## Invariants

- Home contains no KPI, recommendation action, execution queue, template, or threshold.
- User-visible copy is Vietnamese with correct diacritics.
- Analytics (`/analytics`) performs read-only `GET /v1/demo/analytics` (no force-recompute); Home, Settings, and Decisions remain mock fixtures.
- Dùng thử Demo stays sessionless and issues no `/v1/*` request. Since the
  TikTok pixel landed it does emit analytics beacons to its own
  `/api/tt/event`, which carry no session and no identifier for an anonymous
  visitor — the `zero /v1/* requests` tests are unaffected and still enforce
  the backend half of this; Đăng nhập với Google
  (issue #1319) is real code, but only a real LINK when
  `NEXT_PUBLIC_SUPABASE_URL`/`NEXT_PUBLIC_SUPABASE_ANON_KEY` were present at
  `next build` time (Next inlines `NEXT_PUBLIC_*` at build, never at
  runtime) — issue #1905 found that nothing in the release lane ever set
  them, so every artifact CI had built rendered the honest-disabled `<span
  role="link">` branch instead. `scripts/verify-supabase-env-in-build.mjs`
  (wired into `pnpm build`, same discipline as the replay-scenario check
  above) now fails the build non-zero when they're absent, and
  `.github/workflows/release.yml`'s `app-release-artifact` job sources both
  from repository secrets for `matrix.app == 'demo'`. When configured, it
  routes to Supabase Auth and, from the connect-shop screen, makes a real
  bearer-authenticated `GET /v1/shops` call. When not, the disabled state
  now also renders visible Vietnamese copy (`dictionary.md`
  `auth.google.unavailable`), not only an `aria-label`.
- `ConnectShopView`'s "Kết nối TikTok Shop" control is LIVE from issue #1970,
  where it used to be `aria-disabled` beside a disclaimer saying it did
  nothing. It calls `lib/tiktok-connect-client.ts`'s bearer-authenticated
  `GET /v1/auth/tiktok/start` and navigates to the authorize URL that returns.
  It never assembles a TikTok URL itself: the only thing that makes that URL
  safe is the server-signed `state` naming the signed-in seller, and a
  client-built one would carry no owner. Both this call and `GET /v1/shops`
  are same-origin relative paths (#397, no client-side API base), which is
  why `infra/nginx/demo.app-juli.com.conf` now proxies `/v1/` to the API
  upstream — without that, both are served by Next.js and 404.
- `RecommendationsPanel`/`RecommendationsView` — the ANONYMOUS Decisions
  branch — make no backend request or real write anywhere in the
  recommendations flow (asserted in `decisions-recommendations.test.tsx`,
  and structurally by `replay-module-graph.test.ts`). Issue #1909 delivered
  the component-level anonymous/signed-in split this invariant was waiting
  for: `DecisionsPageClient` resolves the stored session and renders EITHER
  this fixture branch (no session — unchanged, still fixture-only) OR
  `SignedInDecisions` (session present), which is the only Decisions module
  that calls `fetchRecommendations()`/`approveDemoDecision()`. The claim
  is therefore scoped: the signed-in branch DOES issue bearer-authenticated
  `/v1/*` requests, by design; the anonymous branch still issues none, and
  a failed signed-in fetch renders an honest error — never
  `recommendationFixtures` standing in (#1320).
- Manual Refresh re-fetches Analytics envelopes, resets mutable mock-state, and returns to
  `/decisions`, whose default view is Recommendations.
- **The staged run view's no-backend invariant is retired for the SIGNED-IN
  door only (issue #1321), and that door is REACHABLE since issue #1909.**
  The signed-in path is live-backed AND wired: the `[executionId]` page
  passes the stored session's token (no caller did before #1909), and the
  run lookup (`GET /v1/demo/runs`), the SSE connection, and the
  confirmation POST all carry the bearer token plus the acting shop's
  `X-Shop-Id` — the pre-#1909 clients sent no credentials on the lookup and
  no shop id anywhere, which the authenticated routes reject. The
  REPLAY/anonymous door stays request-free for *reaching and viewing* a
  run, exactly as ADR-094 decision 1 requires.
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
