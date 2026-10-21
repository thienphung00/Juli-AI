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
  ready`; anonymous = the bundled sample — `lib/phan-tich/sample-data.ts`'s
  `sampleEnvelope()`, lazy-loaded, no request). Header, Trang chủ and Phân tích read it.
- **Signed in, no shop → the sample (P13).** `no-shop` renders the same sample
  screens as signed out — `SampleHome`, `SamplePhanTich`, `SampleQuyetDinh`
  (in-memory clients, nothing written) — under `NoShopSampleStrip`
  (`components/app-shell/no-shop-sample-strip.tsx`: "Bạn đang xem dữ liệu mẫu ·
  Kết nối TikTok Shop ›" → `/auth/connect-shop`). One sample shop everywhere:
  "Cửa hàng Mẫu Hoa Mai", the cosmetics shop (SM-012 …); its report carries
  Liên kết (Home's greyed row) and a shop-wide `total` summed over the additive
  streams (Home's GMV / Đơn / AOV cards).
- **Legacy routes removed (P53, owner C2, 2026-10-18).**
  `/decisions/in-progress/[executionId]`, `/decisions/recommendations/[recommendationId]`
  and `/settings/workflows/[workflowKey]` (no live link; pre-P10 fixture review,
  staged run view / replay run, workflow template detail) are gone with every
  module only they reached: the run-surface canvas (`RunDetailRoute`,
  `ReplayRunDetail`, `RunStagedView`, `RunStepper`, `RunStageCanvas`,
  `RunHeader`, `RunNarrationTypewriter`, `OptionPicker`), `InProgressPanel`,
  `RecommendationReview` / `PlanReviewCard` / `ImpactBlock*`,
  `RecommendationsView` / `RecommendationsPanel`, `DestinationPlaceholder`,
  `lib/analytics/{envelope-mapper,mock-data}`, `lib/settings/*`,
  `lib/run-surface/{replay-*,stage-*,motion,tokens,option-picker-copy,run-id,use-replay-events}`,
  the bundled golden scenario and `scripts/verify-replay-scenario-in-build.mjs`.
  Those URLs now 404 (no external link pointed at them). The shell no longer
  has a run-focus framing; every page gets the full shell.
  `RepeatConsentBlock` and `lib/repeat-consent.ts` are kept (consent code;
  the block is mounted nowhere now, DEBT P53).
- `DemoStateProvider` / `useDemoState` — single owner for mutable mock state,
  persisted Mock mode, disabled Sign-in feedback, deterministic reset, and
  `startExecution(workflowKey)` for approved workflow records.
- `lib/executions.ts` — Workflow 1 + post-sales (7–9) timeline fixtures and pure
  `startExecution` for review-executable keys only.
- `lib/reviews.ts` — Five-stage review content and input defaults for Workflow 1
  and workflows 7–9 (`prevent_cancellation_8a`, `prevent_return_8b`,
  `prevent_refund_8c`); FBT return intake key stays non-executable.
- `lib/recommendations.ts` — network-free fixtures (still read by
  `demo-state.tsx` through `lib/workflows/*`) and the `/decisions?highlight=`
  href builder. The authenticated clients live in
  `lib/recommendations-api-client.ts` (#1772): `fetchRecommendations()`
  reads the real `GET /v1/demo/decisions` (parsing its actual
  `DemoDecisionListResponse` envelope from `@juli/contracts`) and
  `approveDemoDecision()` performs the real
  `POST /v1/demo/decisions/{id}/approve` — both bearer-authenticated with
  `X-Shop-Id`, both called from `SignedInDecisions` (issue #1909), and
  neither ever falls back to `recommendationFixtures` on a failed or
  malformed fetch (#1320).
- **Phân tích (ADR-109 Amendment 2, P12, AC-12.1–12.4).** `/analytics` renders
  `AnalysisPageClient`. Signed in, the report comes from the shell's
  `useShopReport()` (one `GET /v1/demo/analysis` per visit, shared with the header
  and Home); signed out, `SamplePhanTich` renders the bundled "Bản minh họa"
  (`lib/phan-tich/sample-data.ts` — the Quyết định sample's cosmetics shop, same
  TikTok product ids as `lib/quyet-dinh/sample-data.ts`, in the report / ranking
  wire shapes; no request — an entry of `replay-module-graph.test.ts`). The URL
  holds `tab=san-pham|noi-dung`, `stream=the-san-pham|tab-cua-hang|video|live|dong`,
  `metric=hien-thi|ctr|ctor|aov` (old `them-gio` / `don-them-gio` open CTOR),
  `huong=len`, `row=<id>`. `PhanTichView` (`components/phan-tich/`) takes an
  injected source (`report`, `loadRanking`, `loadDecisions`) and renders the
  artboards in `docs/product/design/phan-tich/`: header (h1 = the default stream's
  weakest metric, window chip, ⓘ Cách tính), sub-tabs + "✦ Juli gợi ý · <metric>
  kéo GMV −N ₫/ngày · Xem N đề xuất ›", the LinkA caption line, one collapsible
  `StreamCard` per stream (one open; default = the stream whose weakest metric
  loses the most GMV) with 4 cells + GMV/ngày (`lib/phan-tich/model.ts`: value, Δ
  chip, the report's `factors[].contribution` as ₫/ngày, "trước X" on hover/tap,
  "✦ Juli gợi ý" on the weakest; content streams' CTOR/AOV grey "Phụ thuộc sản
  phẩm"), the ranking (`lib/phan-tich/rows.ts`: Kéo xuống / Kéo lên, rows expand
  in place with their facts — CTOR's two steps, SKU orders, the card's proposal —,
  "Còn lại · 3 dòng", "Tổng" = `stream_factor_gmv`), and on Sản phẩm the collapsed
  Khuyến mãi / Lịch sale và chiến dịch (`lib/phan-tich/extras.ts`, P12 report
  fields). Rows join cards by product id × metric (`lib/phan-tich/cards.ts`):
  "Xem đề xuất ›" → `/decisions?tab=de-xuat&the=<card>`; no card → "Chưa có đề
  xuất". Signed-in reads: `lib/phan-tich/rankings-client.ts` (per open cell) and
  `fetchRecommendations` (cards). Styles: `app/phan-tich.css` (`.pa-*`, the
  `--qd-*` tokens). Contract: `fasttrack/contracts/p12-phan-tich.md`.
  `lib/shop-analysis/sample-report.json` (the old household shop) is no longer
  read by the app — only two Quyết định e2e specs use it as a signed-in report
  stub; `sample-rankings.json` is kept only because `scripts/demo_analysis_sample.py
  --check` regenerates it. The old KPI dashboard (`/analytics/[metricKey]`) was
  removed (P9-C); `/analytics/<anything>` redirects to `/analytics`.
- **Đề xuất ← Phân tích (P12).** `/decisions?tab=de-xuat&the=<card id>` scrolls to
  that card and outlines it pink for 3 s (`DeXuatPanel` `focusCard`, `FOCUS_MS`);
  `&nhom=ctr|ctor|aov` does the same for the metric's group. Every card with a
  P7-B diagnosis carries "Xem phân tích ›" (`analysisHrefForDecision`) back to its
  stream, metric and row, expanded.
- **Quyết định signed out (P11, ADR-094 d.1).** No stored session →
  `DecisionsPageClient` renders `SampleQuyetDinh`
  (`components/quyet-dinh/sample-quyet-dinh.tsx`): the same P10 screens
  (`QuyetDinhView`, `components/quyet-dinh/quyet-dinh-view.tsx`) over
  `createSampleQdClients()` (`lib/quyet-dinh/sample-clients.ts`, an in-memory
  store seeded from `lib/quyet-dinh/sample-data.ts` in the P10 contract
  shapes). Approve / reject / confirm / photo / "Tôi đã áp dụng" / Hoàn tác
  change that store only and play the run's next events on a timer; "Làm
  mới Demo" starts it over (`resetReviewerSample` + `useDemoResetEpoch`).
  P37 (D47.2, 2026-10-16): the store is the tab-wide one of
  `lib/reviewer/sample-store.ts` (signed out, no shop and the sample reviewer
  alike; Phân tích reads its cards via `fetchDeskDecisions`, Trang chủ shows no
  cards) and walks the real card lifecycle: desk status as `ActionCard.status`
  (active / approved / dismissed / expired), seller status derived like
  `card_view._status` — approved is "Đã áp dụng" only when the latest run
  completed with a recorded write (Seller Center / promotion and content runs
  stay "Đang thực hiện"); Từ chối, a declined consent, "Không thực hiện" and
  Hoàn tác (at its start) close the card ("Đã từ chối", 7-day cooldown); a
  failed / cancelled / timed-out run puts it back to "Chờ duyệt"; runs start
  `queued`; 7 days after surfacing an untouched card reads "Hết hạn". Seams:
  `advanceTime` (consent lapses after 4 h → cancelled, external waits after 3
  days → timed_out, expiry) and `failRun`. `QdClients.subscribeDecisions`
  (sample only) makes `QuyetDinhView` re-read cards + runs from the store and
  drop its local status overrides. Proof: `sample-card-lifecycle.test.ts`,
  `sample-lifecycle-views.test.tsx`, `reviewer-all-features.test.tsx`. `QuyetDinhView` and
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
  time, `tool.completed.summary` / narration, consent inline with the
  confirmation client, terminal with day 7 / day 14 from the
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
- ~~`AnalyticsDataProvider` / `fetchDemoAnalytics`~~ — removed in fast track P61-D (owner D72.5, 2026-10-21): `GET /v1/demo/analytics` is retired (410 Gone); "Làm mới Demo" keeps its sample resets.
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
- Nothing reads `GET /v1/demo/analytics` any more (retired in P61-D, 410 Gone); the KPI dashboard route is gone. Signed-in Trang chủ and Phân tích read `GET /v1/demo/analysis` once via the shell's `ShopReportProvider` (Phân tích adds one rankings read per clicked cell); anonymous Trang chủ and Phân tích issue no request.
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
  (wired into `pnpm build`) now fails the build non-zero when they're absent, and
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
  `supabase-auth.ts`'s fetch, pinned to `/auth/v1/otp`, `/auth/v1/verify` and
  (P32-A) `/auth/v1/token`.
- Partner trial account (fast track P32-A, D42, contract
  `fasttrack/contracts/p32-reviewer-access.md`): `components/partner-sign-in.tsx`
  ("Tài khoản đối tác", `/auth/email#doi-tac` only — the landing links to it from
  the pill above the auth heading, "Đối tác thẩm định? Đăng nhập bằng tài khoản đối tác →"
  (D47.6, plain and trial entry view), and from the footer link; both share one href / click
  handler in `auth-screen.tsx`: in-page `#doi-tac` view where the form is rendered, else
  `/auth/email#doi-tac`)
  runs `signInWithPassword` (GoTrue password grant, dictionary `auth.password.*`)
  then `GET /v1/reviewer/me` (`lib/reviewer/api-client.ts`); a reviewer gets the
  aliased reference shop as active shop and a record under `juli_demo_reviewer`
  (`lib/reviewer/session.ts`). `ReviewerProvider` (`lib/reviewer/reviewer-context.tsx`,
  in `DemoShell`) re-confirms on every load (expired / revoked → signed out, back
  to the form with the reason); `lib/reviewer/mode.tsx` is the network-free
  context. Reviewer mode: `ReviewerBanner` (`reviewer.banner`, also on the
  run-focus layout), every page under `SellerViewProvider readOnly simulateApprove`
  (`reviewer.read_only_title`), no connect / reconnect / upload entry, no run SSE;
  a card's Duyệt (`useApproveControl`) opens `ReviewerSimulation`
  (`POST /v1/reviewer/decisions/{id}/simulate`, approve then execute,
  `reviewer.simulated`) and never the real approve. Presentation only: the API
  refuses every reviewer write on its own.
  P32-D (D42 amendment, 2026-10-15): when `/v1/reviewer/me` says `shop: null`
  (no `REVIEWER_SHOP_ID`), sign-in stores no active shop and the record carries
  `sample: true`, so every page takes P13's no-shop door (the bundled sample
  "Cửa hàng Mẫu Hoa Mai", no shop API) under the banner `reviewer.banner_sample`;
  the no-shop strip stays hidden. `SampleQuyetDinh` opens `SimulationDialog`
  (shared with `ReviewerSimulation`, `components/quyet-dinh/simulation-dialog.tsx`)
  over `lib/reviewer/sample-simulation.ts` — the API's simulation ported to the
  sample cards, in memory, nothing sent.
  P32-E (D42 amendment 2, 2026-10-15): in sample mode nothing is read-only —
  `DemoShell` wraps only the pinned reviewer in `SellerViewProvider readOnly`.
  Every seller write runs on `lib/reviewer/sample-store.ts` (one
  `createSampleQdClients` store per tab, shared by `SampleQuyetDinh` and
  `/settings`' rules; reset by the banner's "Đặt lại dữ liệu mẫu" and sign-out):
  Từ chối, the run after the dialog's "Theo dõi lượt chạy (mô phỏng) ›" (consent
  edits, photo, Seller Center, content drafts, Hoàn tác), Đo lường's day-7 /
  day-14 "tua nhanh" (`simulateMeasurement`), Quy tắc, and "Phân tích video"
  (file picked, never read: canned P15 analysis). `SimulatedLabel`
  (`components/app-shell/simulated-label.tsx`) prints `reviewer.simulated` /
  `reviewer.simulated_settings` only for the sample reviewer. Proof:
  `reviewer-all-features.test.tsx` — one full session through the real shell,
  the only request `GET /v1/reviewer/me`.
  P41 (D47.7, owner 2026-10-16): simulation copy is short and shows no backend
  internals. `SimulationDialog` shows Thao tác, Sản phẩm, the Mục / Trước / Sau
  table and `change.note` (one line per executor, `reviewer.simulation_note`) —
  never `change.request` (method, path, operation) and no second disclaimer;
  its label is the one "Mô phỏng · không gửi tới TikTok". The page label reads
  "Mô phỏng · không gửi tới TikTok · chạy trên dữ liệu mẫu". Sample runs carry
  per-product keyword lines and plain TikTok-flag wording ("Mô tả quá ngắn",
  never "Có mã"); `runPhase` says "queued" only while the events show no tool or
  consent. Proof: `sim-copy-p41.test.tsx` (no `/product/`, `PUT`,
  `update_product`, `gpt-`, "Có mã" anywhere in the reviewer's session).
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
- Manual Refresh re-fetches Analytics envelopes, resets mutable mock-state, and returns to
  `/decisions`, whose default view is Recommendations.
- Every navigation target is keyboard accessible with a visible focus state and
  at least a 44×44px target.
- The app never imports a sibling app.

## Owners

- domain: web
- code: `apps/demo/`
