# Module: demo

## Responsibility

Standalone public-facing Next.js Demo for Juli's four-destination product shape.
The blanket "no backend or authentication dependency" claim from Phase 2.6 no
longer holds app-wide and is retired here (issue #1321) — Analytics, the
signed-in Decisions/run surfaces, and Đăng nhập với Google all depend on the
real backend and Supabase Auth. What remains true, surface by surface, is in
Invariants below.

## Public interface

- `/` — `HomePageClient`: a signed-in seller gets their shop's Trang chủ
  (`SignedInHome`); anyone else gets the two-door landing (`DemoLanding`),
  whose "Dùng thử Demo" door reveals the sample Trang chủ (`SampleHome`).
- **Trang chủ (AC-8.5, ADR-109 d.3).** `components/home/home-overview.tsx`
  (`HomeOverview`, `StreamMatrix`) renders one ADR-108 envelope: GMV / Đơn /
  AOV cards ("trước … ▲/▼ %") and the 5-stream matrix (Thẻ sản phẩm, Tab cửa
  hàng | Video của shop, LIVE của shop | Liên kết greyed "chỉ theo dõi"; columns
  Lượt hiển thị sản phẩm/ngày, CTR, CTOR, AOV; cells tinted by direction).
  `lib/shop-report/home-metrics.ts` (`buildHomeOverview`) is the one mapping
  (daily averages × window days; a missing stream → "Chưa có dữ liệu"; Tab
  cửa hàng CTOR/AOV flagged "ước tính"). Each non-affiliate cell links to
  `/analytics?tab=san-pham|noi-dung&stream=the-san-pham|tab-cua-hang|video|live&metric=hien-thi|ctr|ctor|aov`
  (`analyticsCellHref`) — **P8-E reads this query** for its sub-tabs.
- `/decisions`, `/analytics`, `/settings` — pages inside the shell; `/settings`
  is reached from the shop-avatar menu, not the nav.
- **App shell (AC-8.5, ADR-109 d.1/d.7/d.8) — `DemoShell`
  (`components/demo-shell.tsx`).** Layout every page renders in:
  `AppNavigation` (`components/app-shell/app-navigation.tsx`) — Trang chủ /
  Quyết định / Phân tích / **Juli locked** (`<span role="link"
  aria-disabled="true">`, lock mark, tooltip "Sắp có: nhật ký 24 giờ"; list
  in `lib/app-navigation.ts`) — a left rail with the Juli. wordmark from 768px,
  a bottom bar below (ONE `<nav>`, CSS-only switch); `ShopHeader`
  (`components/app-shell/shop-header.tsx`) — avatar initials, shop name,
  "TikTok Shop · ngành · N SKU" (parts only when known; the report carries
  neither yet), and "Juli đang chạy · cập nhật HH:MM" from the report's
  `built_at` (omitted when no report; anonymous shows "Dữ liệu mẫu · cập nhật
  HH:MM" plus a "Bản minh họa" badge). The avatar opens the shop menu: Cài
  đặt, Đổi shop / Kết nối TikTok Shop, Đăng xuất (signed in) or Cài đặt,
  Đăng nhập, Làm mới Demo (anonymous). **No global stepper** (d.8: it lives
  inside Quyết định). No assistance aside, no mode toggle (retired by AC-8.5).
  **The slot:** the page is `children` of `<main class="app-content">`; a page
  just renders its own content.
- **Page header (for P8-E / P8-F).** `AppPageHeader`
  (`components/app-shell/page-header.tsx`): `eyebrow` (pink uppercase, e.g.
  "PHÂN TÍCH · SẢN PHẨM"), `title` (large conclusion-style h1 — the finding,
  not the page name), optional `lede`, `actions` (right side) and `titleId`
  (for `<section aria-labelledby>`). Classes `.eyebrow`, `.page-title`,
  `.page-lede` are reusable on their own.
- **Shop report context.** `ShopReportProvider` / `useShopReport()`
  (`lib/shop-report/shop-report-context.tsx`, mounted by the shell) resolves
  the session once and holds the acting shop's latest `GET /v1/demo/analysis`
  envelope (`resolving | anonymous | no-shop | loading | empty | error |
  ready`; anonymous = the bundled sample, lazy-loaded, no request). Header, Trang chủ and Phân tích read it.
- **Run route exception** (#1910, PUI-DESIGN.md §2, owner amendment
  2026-09-14): the real run route (`/decisions/in-progress/<id>` where
  `looksLikeRunId(id)`) renders WITHOUT the shop header and feedback region
  while the nav rail STAYS; the run surface owns the region to its right.
  `RunStagedView` supplies the §2 header row itself (`RunHeader`). Legacy mock
  `exec-*` execution details keep the full shell.
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
  Superseded by `SignedInQuyetDinh` (P10) and, signed out, by
  `SampleQuyetDinh` (P11, below); `RecommendationsView` is no longer
  rendered by `/decisions`.
- **Phân tích (AC-8.6, ADR-109 d.2–5).** `/analytics` renders
  `AnalysisPageClient` (inside `<Suspense>`, it reads `useSearchParams`): the
  report comes from the shell's `useShopReport()` — one `GET /v1/demo/analysis`
  per visit, shared with the header and Home (P8-D's double fetch is gone) —
  and the URL holds `tab=san-pham|noi-dung`, `stream=the-san-pham|tab-cua-hang|video|live`,
  `metric=hien-thi|ctr|ctor|them-gio|don-them-gio|aov` (`router.replace`, so
  Home's matrix links land on the cell). `PhanTichView`
  (`components/phan-tich/`) is pure of I/O: sub-tabs, one `StreamFunnel` per
  stream (clickable cells per d.4 — `CLICKABLE` in `lib/phan-tich/model.ts`
  mirrors the backend's `STREAM_METRICS`; Video CTOR/AOV and LIVE AOV show
  "phụ thuộc sản phẩm → xem tab Sản phẩm"; Thẻ sản phẩm's CTOR tile carries
  its two steps), the **bottleneck** (`findBottleneck`: across the sub-tab's
  two streams, the clickable factor whose report contribution is negative,
  "Rõ" and largest; none → no outline, no strip) outlined with "✦ Juli gợi
  ý" (`suggestionLine`, from the report's numbers only; no target — the
  backend gives none), the h1 from it (`pageTitle`), the `RankingTable`
  (Kéo xuống / Kéo lên, closing rows incl. the other direction folded, "Tổng
  = stream_factor_gmv"; 404 → "Chưa có bảng xếp hạng cho chỉ số này"), the
  `DetailPanel` ("Ví dụ · <mã>", the hero profile when the row is a hero),
  `HeroList` (expands in place to `HeroProfileDetails`) and
  `CollapsedSection`s (Khuyến mãi, Dòng thời gian, Cách tính — body mounts
  on "Xem thêm"). Rankings come through a `RankingLoader`: signed in →
  `lib/phan-tich/rankings-client.ts` (`GET /v1/demo/analysis/rankings`,
  bearer + `X-Shop-Id`, 404 → null), memoised per cell; anonymous →
  `SamplePhanTich` with the bundled `sample-rankings.json` (no request; an
  entry of `replay-module-graph.test.ts`). Both sample files are generated by
  `scripts/demo_analysis_sample.py` (real `build_report` / `build_rankings`
  over the synthetic helpers in `tests/support/shop_diagnosis.py`; `--check`
  fails when stale). The old KPI dashboard (`/analytics/[metricKey]`) was removed (P9-C);
  `/analytics/<anything>` redirects to `/analytics` (`next.config.ts`).
- **Quyết định signed out (P11, ADR-094 d.1).** No stored session →
  `DecisionsPageClient` renders `SampleQuyetDinh`
  (`components/quyet-dinh/sample-quyet-dinh.tsx`): the same P10 screens
  (`QuyetDinhView`, `components/quyet-dinh/quyet-dinh-view.tsx`) over
  `createSampleQdClients()` (`lib/quyet-dinh/sample-clients.ts`, an in-memory
  store seeded from `lib/quyet-dinh/sample-data.ts` in the P10 contract
  shapes). Approve / reject / confirm / photo / "Tôi đã áp dụng" / Hoàn tác
  change that store only and play the run's next events on a timer; "Làm
  mới Demo" remounts it (`useDemoResetEpoch`). `QuyetDinhView` and
  `lib/quyet-dinh/client-types.ts` (the `QdClients` contract, `QdApiError`
  and pure helpers) hold no fetch call site or backend route literal — the
  sample door is an entry of `replay-module-graph.test.ts`.
- **Session storage (P11).** `lib/supabase-auth.ts` and `lib/shop-session.ts`
  keep the sign-in and active shop in `localStorage`
  (`lib/persistent-storage.ts`, every access in try/catch, one-time
  migration from `sessionStorage`, sign-out clears both) so a seller stays
  signed in across new tabs and a browser restart.
- **Quyết định (AC-8.7, ADR-109 d.6, 8–13) — signed in.** `DecisionsPageClient`
  renders `SignedInQuyetDinh` (`components/quyet-dinh/signed-in-quyet-dinh.tsx`,
  replaces `SignedInDecisions`) — the one module wiring the real clients
  (injectable `clients`) into `QuyetDinhView`. URL: `tab=de-xuat|dang-thuc-hien|do-luong`,
  `run=<id>`, `quy-tac=1` (rules editor open). **Đề xuất** (`DeXuatPanel`):
  `lib/quyet-dinh/grouping.ts` groups `GET /v1/demo/decisions` items by
  `channel_scope` × `stage.code` ("N thẻ tối ưu để nâng CTOR Thẻ sản phẩm",
  "GMV dự kiến" = Σ recoverable GMV/day × 30, ước tính theo quy tắc — no
  target rate, the backend gives none); price/promotion/non-executable cards
  say "Bạn áp dụng trên Seller Center" and never enter "Duyệt N thẻ"; batch
  approve = `approveSequentially` (one approve call at a time → N runs);
  blocked until a stability band is set (d.11) — "Giữ ổn định" and "Quy tắc
  do bạn đặt" read `GET /v1/demo/rules`. `FiveStageStepper` sits on a group or
  a run only (d.8). **Rules editor** (`RulesEditor`, d.12) opens from "Sửa"
  and is the signed-in `/settings` page (avatar menu Cài đặt,
  `settings-rules.tsx`); "Điền thay Seller (đội ngũ Juli)" → `set_by:
  "team"`; a 422 shows the rule's Vietnamese range inline. **Đang thực
  hiện**: `buildRunTimeline` (`lib/quyet-dinh/timeline.ts`, pure, idempotent
  by sequence) turns the run's SSE events (`useRunStream`; a finished run's
  stream replays its history) into steps — tool → Vietnamese label, event
  time, `tool.completed.summary` / narration, consent inline with the existing
  `OptionPicker` + confirmation client, terminal with day 7 / day 14 from the
  completion timestamp (D14); playbook steps not reached yet are greyed
  without time. Right: `RunQueue` ("Hàng chờ thẻ tối ưu", ledger sections
  and honest terminal labels from `lib/run-ledger`). Finished runs show
  `GET …/changes` before → after and "Hoàn tác" (`POST …/revert` → the new
  run; 409/503 messages verbatim; disabled with `revert.message`). **Đo
  lường** (`DoLuongPanel`): executed runs with changed fields and "Đang chờ
  đủ 7 ngày dữ liệu · đo lúc dd/mm/yyyy" (no measurement API yet — DEBT
  P8-F), `GET /v1/demo/revert-questions` with Hoàn tác / Giữ thay đổi
  (dismiss). Anonymous `/decisions` is unchanged (fixtures, DEBT P8-F).
- **Quyết định to the artboards (AC-10.3, ADR-109 Amendment 1).** Supersedes
  the card / run / Đo lường parts above; design source
  `docs/product/design/quyet-dinh-flows/*.dc.html`, API
  `fasttrack/contracts/p10-quyet-dinh.md`. Card: `RecommendationCard`
  (`cardView` in `lib/quyet-dinh/card-model.ts` reads `recommendation.card`,
  else degrades to the P7-B diagnosis); Main layout ≥ 768 px, Mobile below
  (`useNarrow`); Phê duyệt → in-card notice + "Xem tiến độ ›"; Từ chối /
  Không thực hiện / Hoàn tác open `ReasonDialog` (one `reason_code`
  required, `lib/quyet-dinh/reasons.ts`). Run: `RunPanel` per run kind
  (`runKind`/`runPhase` in `run-model.ts`; timeline plans in `timeline.ts`)
  — consent with "✎ Sửa nội dung" → `edited_values`, photo upload
  (`awaiting="photo"`), Seller Center checklist (`awaiting="seller_action"`,
  "Tôi đã áp dụng" → `POST applied`), done / declined / conflict panels;
  flat `RunQueue`. Đo lường: `DoLuongPanel`, tabs `moc=ngay-0|ngay-7|ngay-14`
  by `measurement.stage` (`measure-model.ts`). Styles: `app/quyet-dinh.css`
  (`qv-*`, `--qd-*` = the artboards' hex); font Be Vietnam Pro
  (`--font-be-vietnam-pro`, `app/layout.tsx`) on Quyết định only.
  `DecisionsPageClient` follows the requested href immediately (the
  production router may not commit `replace` on a deep-linked page).
- **Quyết định evidence (AC-7.6).** `lib/decision-evidence.ts` is the one
  mapper for an Optimize Product item's `recommendation.diagnosis` /
  `recommendation.evidence` (P7-B, typed in `@juli/contracts`);
  `DecisionEvidenceBlock` renders stage, lever, trigger, the rule-based
  recoverable GMV and the funnel table only when `diagnosis` is present.
- **Look (D21, AC-7.5).** `globals.css` carries the `colors_and_type.css` kit
  (tokens, `.card`, `.btn-primary`, `.badge`, `.app-header` …) after the older
  rules. AC-8.5 appends the shell/Trang chủ block (rail, header, `.eyebrow`,
  matrix) drawn only from those kit tokens — one token source.
- `AnalyticsDataProvider` / `fetchDemoAnalytics` — Phase 2.10-A live Analytics read via `GET /v1/demo/analytics` (Home/Settings/Decisions remain mock).
- **The staged run view (issues #1316/#1317/#1319/#1752/#1909, ADR-076 decision 3/4, ADR-094).** `RunDetailRoute` (`components/run-detail-route.tsx`) dispatches on whether a bearer `token` is present — the same absence-as-signal `useRunStream` itself gates on. Since issue #1909 that token is actually supplied: the `[executionId]` page's `RunDetailDoor` reads `readAuthSession()` and passes `token` (plus the acting shop's `shopId`) when a session is stored — before #1909 no caller passed one, so the signed-in door below was unreachable from any browser:
  - **Signed-in (token present):** `SignedInRunDetail` calls `fetchDemoRuns` (`lib/run-ledger/api-client.ts`, real `GET /v1/demo/runs`) to resolve the run, then `useRunStream(runId)` (`lib/run-surface/use-run-stream.ts`) opens the real SSE transport (`lib/agent-event-stream.ts`) with reconnect/backoff via `Last-Event-ID`. `RunStagedView` renders the live event fold; `OptionPicker`'s confirm/decline calls `submitConfirmationDecision` (`lib/run-surface/confirmation-client.ts`), a real bearer-authenticated `POST /v1/demo/runs/{id}/confirmations/{tool_call_id}`. This path is live-backed end to end.
  - **Replay/anonymous (no token):** `ReplayRunDetail` seeds `RunStagedView` from `useReplayEvents` (`lib/run-surface/use-replay-events.ts`), which reveals the one bundled, tool-captured golden scenario (`lib/run-surface/golden-scenarios/optimize_product_confirm_pause.json`, imported statically — never fetched, verified absent-from-build-fails-loudly by `scripts/verify-replay-scenario-in-build.mjs`) paced by its own captured inter-event deltas, rebased to now. Reaching and viewing this run issues zero `/v1/*` requests — matches `RunDetailRoute`'s own test, `run-detail-route.test.tsx`'s "replay path ... zero /v1/* requests" case.
- `RunStagedView` / `RunStepper` / `RunStageCanvas` / `OptionPicker` — the one-stage-at-a-time canvas, top stepper, and consent-grade option picker (PUI-DESIGN.md §2/§3); shared verbatim by both doors above, so replay and signed-in render identically by construction.
- `POST /api/tt/event` — the TikTok Events API relay, sharing one data source
  with `apps/landing`. Same-origin, so an ad blocker that stops the pixel does
  not stop this. Accepts only this site's own origins (`lib/site-origins.ts`)
  and only the events in `@juli/tiktok-events`'s allowlist. It reaches TikTok,
  never `juli-api`, so it is outside every `/v1/*` claim below. Only ever
  called for an ad visitor — see the invariant.

## Dependencies

- `@juli/contracts` — execution, review stage, and Demo Analytics envelope types.
- `@juli/theme` — semantic tokens.
- `@juli/ui` — buttons, cards and shared primitives (the demo renders its own nav since AC-8.5).
- `@juli/utils` — Vietnamese date/number formatting.
- `@juli/tiktok-events` — TikTok pixel, event vocabulary, and the relay handler.

## Invariants

- Home (Trang chủ) shows the shop report overview (cards + 5-stream matrix, ADR-109 d.3) and no recommendation action, execution queue, template, or threshold.
- User-visible copy is Vietnamese with correct diacritics.
- The shell's `AnalyticsDataProvider` (feeds the plan impact block) is the remaining reader of `GET /v1/demo/analytics`; the KPI dashboard route is gone. Signed-in Trang chủ and Phân tích read `GET /v1/demo/analysis` once via the shell's `ShopReportProvider` (Phân tích adds one rankings read per clicked cell); anonymous Trang chủ and Phân tích issue no request.
- **The TikTok channel is loaded only for a visitor who arrived from a TikTok
  ad** — a `ttclid` on the landing URL, or one stored from an earlier visit
  (`components/tiktok-tracking.tsx`, and the same gate in
  `lib/tiktok-registration.ts` so the server relay cannot report an organic
  visitor either). Owner decision, 2026-09-21. `apps/landing` loads it for
  everyone; the Demo cannot, because entering and browsing the anonymous
  replay issues no request that leaves the origin — asserted by
  `e2e/exit-gate/locale-and-assistance.spec.ts` and kept covered by
  `tests/unit/test_phase_2_6_demo_exit_gate.py`. The consequence, stated so it
  is not rediscovered as a bug: no retargeting or lookalike audience is built
  from organic Demo visitors. `e2e/analytics/tiktok-ad-visitor.spec.ts` owns
  the other direction — that the pixel really does load for an ad visitor,
  which an absence test cannot show.
- Dùng thử Demo stays sessionless and issues no request at all for an organic
  visitor; Đăng nhập với Google
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
- **Đăng nhập bằng email (AC-9.1).** Beside Google on the landing's sign-in
  door (disclosure revealing `components/email-sign-in.tsx` `EmailSignIn`),
  in the anonymous shop-avatar menu ("Đăng nhập với Google" + "Đăng nhập bằng
  email" → `/auth/email`, `app/auth/email/page.tsx`). `lib/supabase-auth.ts`
  `requestEmailOtp` (`POST /auth/v1/otp?redirect_to=<origin>/auth/callback`,
  `{email, create_user: true}`) and `verifyEmailOtp` (`POST /auth/v1/verify`,
  `{type: "email", email, token}`) — plain fetch, anon key header, no SDK, no
  new env. Success stores the SAME `AuthSession` under the same key as the
  Google callback, reports the TikTok registration, and full-loads
  `/auth/connect-shop` (so the shell's providers re-resolve the session).
  The magic link lands on `/auth/callback` with the implicit-grant hash
  (`type=magiclink`), parsed by the unchanged `parseAuthCallbackHash`;
  `error_code=otp_expired` (hash or query) → `auth.email.link_expired`.
  Errors are fixed Vietnamese (`EMAIL_OTP_ERROR_COPY`, dictionary
  `auth.email.*`), never GoTrue text or the code; resend locked 60 s (or the
  wait GoTrue names). Unconfigured env → disabled with
  `auth.email.unavailable`. The replay module-graph guard allows
  `supabase-auth.ts`'s fetch, pinned to `/auth/v1/otp` and `/auth/v1/verify`.
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
- `RecommendationsPanel`/`RecommendationsView` — formerly the ANONYMOUS
  Decisions branch (no longer rendered by `/decisions` since P11; kept for
  the fixture review / replay routes' tests) — make no backend request or real write anywhere in the
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
- **(Fixed since — #1764 / `rebaseTemporalFields`; kept for history)** the captured golden scenario's
  `workflow.approval_required.expires_at` (`2026-08-28T12:32:13.308159Z`) was
  never rebased — only the envelope's own `timestamp` is shifted to "now"
  (`lib/run-surface/replay-scenario.ts`'s `rebaseEvent`). Once real
  wall-clock time passes that fixed date, the option picker renders
  permanently expired for every visitor. Not fixed here — out of this
  issue's file boundary; worked around for test determinism only via a
  pinned fake clock in the e2e spec, never in production source.
- Every navigation target is keyboard accessible with a visible focus state and
  at least a 44×44px target.
- The app never imports a sibling app.

## Owners

- domain: web
- code: `apps/demo/`
