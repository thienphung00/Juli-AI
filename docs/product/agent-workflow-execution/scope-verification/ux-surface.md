# Scope scout — S-FR-1 seller-facing surfaces (2026-09-05)

Headline: **the plan-review card is built and good; every other surface S-FR-1 names is
either unbuilt, unwired, or fixture-only.** All ten W6-A UI slices (#1314–#1321) are OPEN;
the `w6-wave-open` branch carries zero `apps/**` diff. No W9/W10 issues exist yet.

## A. Surface inventory

| Surface | Exists today | Real API or mock | What v1 needs beyond it |
|---|---|---|---|
| **Card** (recommendation) | Yes — `apps/demo/src/components/recommendations-panel.tsx`, `recommendation-review.tsx`, fixtures in `lib/recommendations.ts` | **Mock.** `fetchRecommendations()` exists but **no component calls it**, and `/v1/demo/recommendations` **does not exist in the backend** | Real card feed; per-workflow subject (dispatch window, SKU set); executability discriminator (#1309, open) |
| **Plan review** | Yes, and it matches ADR-055 — `components/plan-review-card.tsx` + `lib/plan-reviews.ts` + `lib/workflows/<wf>/plan.ts` for all 11 workflows | Mock fixtures; impact block reads real KPI via `/v1/demo/analytics` | Seller-editable numeric field (stock goal), checklist items, two-labelled-numbers display, needed-by date |
| **Confirmation sheet** | **No renderer.** Backend endpoint exists (`POST /v1/demo/runs/{run_id}/confirmations/{tool_call_id}`); `lib/agent-event-stream.ts` is a working SSE transport whose own header says "Nothing under `apps/demo` imports this module" | n/a | Entire surface: option picker (#1317), expiry countdown, list shape, form shape |
| **Staged run view** | **No.** No `useRunStream`, no reducer, no stepper (#1315, #1316 open) | n/a | Entire surface |
| **Digest / notification** | **No in-app, no push, no email reaching a seller.** `backend/.../services/alerts/` has rules/cooldown + `FcmAdapter` (**delivery is a stub — logs `fcm_send_stub`, no FCM HTTP client**) + `ZaloOaAdapter` (**real POST to `openapi.zalo.me/v3.0/oa/message/cs`**, gated on `ZALO_OA_ACCESS_TOKEN`) — **zero callers outside its own package**, no route, no beat task, no `device_token` column or registration endpoint. No toast/banner/bell/unread anywhere in `apps/demo` | n/a | Everything: producer, channel choice, delivery record, deep link |
| **Completion message** | Partial — `in-progress-panel.tsx` renders `LIFECYCLE_STATUS_LABELS` + `repeat-consent-block.tsx` | Mock (localStorage `startExecution`) | Honest terminal states per S-FR-7 named causes; ledger sections (#1318) |
| **Exception list** | **No concept anywhere** — no list of excluded/dropped items with reasons | n/a | Entire surface (PO-FR-4/7) |
| **Human checklist item** | **No concept anywhere** — grep finds "checklist" only in ADR/PLAN prose | n/a | New field kind + tracking model |
| **Attested report form** | **No.** `received_quantity` was *deliberately deleted* from the approval flow (#766); the mock supplier wait is narration text with no input | n/a | New confirmation kind, params hash over seller-supplied values |

Backend that *does* exist and has no client: `GET /v1/demo/decisions`, `GET /v1/demo/decisions/{id}`,
`POST /v1/demo/decisions/{id}/approve` (approve = atomic run creation), `GET /v1/demo/runs`,
`GET /v1/demo/runs/{id}/events` (SSE), `POST /v1/demo/runs/{id}/cancel`,
`POST /v1/demo/runs/{id}/confirmations/{tool_call_id}`. `apps/demo` calls **none** of them —
only `GET /v1/demo/analytics`, and that silently falls back to a mock envelope on failure.
There is **no mock/live switch**: `components/demo-state.tsx` hardcodes `mode: "mock"` and
reads no env var.

Other apps: **`apps/dashboard`** is seller-facing per its own MODULE.md (chart-first Home,
5-step decision detail, AI chat, demo login gated by `isDemoLoginEnabled`); it calls
`/v1/shops|orders|products|creators|recommendations` — **zero `/v1/demo` or agent calls**.
**`ios/`** (35 Swift files) is a **different product shape** — DailyLoop / PreStream /
LiveAlerts, most tabs literal `PlaceholderTabView`, a GET-only `APIClient`, deep links for
`order` / `livestream` / `inventory` only. It requests `UNUserNotificationCenter` authorization
and calls `registerForRemoteNotifications()` (its MODULE.md's "no push registration in this
slice" is stale) and parses typed VI alert payloads — but **never uploads the device token**,
has **no `.entitlements` file**, and the backend has nowhere to put a token. The push loop is
broken at both ends.

## B. Card anatomy — designed vs built

ADR-055's spine **Situation → Decision → Details** is faithfully implemented in
`plan-review-card.tsx`: Situation collapsed into the header with a question-shaped disclosure
("Juli dựa vào thông tin nào?"), summary-row-not-enumeration, reasoning expansion,
class-D reassurance as a trust line, uploads unfolded in a "needs you" section that keeps
Phê duyệt disabled.

- **Agent-proposed value for every field:** yes, via `buildXReviewInputDefaults()` per workflow.
- **Ask-before-deciding (item 3):** **not built** — explicitly cut by item 14.
- **Two-step consent at approval:** exists — `Phê duyệt` opens `@juli/ui`'s `ConfirmDialog`
  with `SELLER_APPROVE_GATE` copy (`lib/review-seller-copy.ts`). This is the approve gate,
  not the in-run CONFIRM pause; the latter has no UI at all.
- **Closest thing to a checklist today:** clear-excess's `zero_floor_stock_ack`, a *read-only*
  note ("Bước sau — chưa phê duyệt trước khi xả hàng"). Not tickable, not tracked.
  Grep for "Thanh lý" across the repo returns **zero** hits.
- **Options list:** contract now has `kind?: "option-list" | "upload" | "free-text"` and
  `options?` (`packages/contracts/src/review.ts`), but **no `number` kind, no checklist kind,
  no attested-form kind.** Every value is a `string`. `CE-FR-4`'s seller-editable numeric
  stock goal with `0 ≤ goal < sellable` has no expressible validator here.
- **Human checklist items:** no concept in contracts, components, or fixtures.
- **Main KPI tie:** built — `impact-block.tsx` renders real value + trend from the envelope,
  directional goal, no projected magnitude, missing reading renders as missing. Bindings live
  per workflow (`defaultReplenishInventoryAnalyticsMetricKey = "gmv-tiktok"`).
- **Divergence to flag:** ADR-055's card is a *pre-approval plan*; S-FR-1's card is stage B of
  a five-stage run whose CONFIRM comes *later, inside the run*. Nothing today spans both.

## C. Confirmation — three shapes, none built

1. **Single-option (N=1).** Protocol exists: `WorkflowApprovalRequiredPayload{tool_call_id,
   tool_name, proposed_change, expires_at, options?[]}` with `ConfirmationOptionPayload
   {option_id, proposed_change, rationale, params_sha}` in `packages/contracts/src/agent-events.ts`.
   **No renderer.** #1317 (picker) and #1272 (rationale is still an English tool-schema
   description) are both open. PUI-DESIGN §3 specifies the design in full.
2. **List-shaped (Process Order batch).** `proposed_change` is `Record<string, unknown>` — an
   untyped bag. A batch of orders with buckets, an earliest deadline, and an excluded-with-reasons
   list has **no contract shape and no component**. Wholly new.
3. **Form-shaped (Replenish attested report).** Wholly new on both sides: `params_sha` today
   binds server-computed params; RI-NFR-1 requires the hash over **seller-supplied** values as
   shared code. No form, no per-warehouse rows, no "ordered" then "received" two-report chain.

Also note the event union is a **closed 8-member set** and `workflow.status` carries only
`phase_narration: string` — no structured progress. `agent-runs.ts` already models the ledger
row (`WorkflowRunListItem` with `latest_narration` and `decision_summary: {tool_call_id,
expires_at}`), so the countdown data exists server-side with no consumer.

## D. Notifications

Nothing reaches a seller today. Three latent pieces, none connected:
`services/alerts/` (FCM + Zalo, retries, cooldown, `AlertHistory` persistence, **no callers**);
iOS push permission + `AppNotificationRouter` (**no token upload**); the demo has no toast,
banner, badge, or unread concept at all. PLAN.md §14 assumes a deadline clock that "escalates
by push, then email" — no email transport exists anywhere in the backend.
PO-FR-8 ("one push 2 h before the earliest deadline") and RI-FR-7 ("the clock nags") therefore
depend on a channel that does not exist. Cheapest honest v1 = an in-app surface in `apps/demo`;
Zalo OA is the only *seller-reaching* adapter already written.

## E. Which app is the seller's v1 surface — the docs disagree

- **ADR-055, ADR-076, ADR-084, PUI-DESIGN, PRD #1308** all say **`apps/demo`**, mobile-web,
  dual entry (Dùng thử Demo → Supabase anonymous JWT scoped to a seeded demo tenant; Đăng nhập
  với Google → Supabase Auth → separate TikTok OAuth for shop authorization). #1312 (demo
  tenant) is **merged**; #1313 (anonymous session) and #1319 (dual entry / connect-shop) are
  **open**. `apps/demo/MODULE.md` still asserts "Mock is the only enabled mode" and sign-in
  "never routes or requests data" — ADR-084 says that must be rewritten in the same wave.
- **`docs/product/design/` (Screens/, Flows/, flows.md)** says the opposite: *"All implementation
  references use `apps/dashboard/...`"*, and `Flows/home/login.md` is an email+password+OTP form
  against `apps/dashboard`, with a `/mode-select` Seller-vs-Affiliate gate. That contradicts the
  Google/anonymous model entirely.
- ADR-055 scope line: *"`apps/demo` mobile-web only. Native iOS/Android is explicitly out of scope."*

## F. Owner-only questions (each with the options the code and docs actually support)

1. **Which app is v1's seller surface?** (a) `apps/demo` — matches every agent ADR and the ten
   open W6 slices; (b) `apps/dashboard` — matches the design package's Screens/Flows; (c) both,
   demo public + dashboard authenticated. *No default: the two doc sets contradict each other.*
2. **Login for a real merchant.** (a) Google → Supabase → separate TikTok OAuth (ADR-076/084);
   (b) the dashboard's email+password+OTP (`Flows/home/login.md`); (c) demo-only for v1, real
   login deferred. Also: keep the `/mode-select` Seller/Affiliate gate or drop it?
3. **Notification channel for the 2 h push and the digest.** (a) in-app only (no new infra);
   (b) Zalo OA — the one written adapter that reaches a Vietnamese seller; (c) FCM push, which
   requires an app that uploads a device token (today none does); (d) email — no transport exists.
4. **Does iOS ship in v1 at all?** (a) no — web only, `ios/` stays the livestream prototype;
   (b) yes, as the push receiver only; (c) yes, full parity (largest cost — the app has no
   decisions/run screens and a GET-only client).
5. **Checklist item tracking.** (a) display-only text on the card, nothing recorded;
   (b) a seller tick stored on the run and shown in the ledger; (c) a tick that gates the next
   run stage. Affects `Thanh lý` (CE-FR-8) and "place the order" (RI-FR-4).
6. **List-shaped confirmation layout (Process Order).** (a) count + earliest deadline + one tap,
   details behind an expansion; (b) full scrollable order list with per-order rows;
   (c) grouped by bucket with the exclusion list as a peer section.
7. **Where the exception list lives.** (a) a section inside the completion message;
   (b) its own tab/screen in the ledger; (c) notification-only with a deep link per order
   (PO-FR-7 implies a deep link — deep link to *what* screen? none exists).
8. **Attested report form.** (a) one form at receipt (v1 spec's minimum); (b) two forms,
   "ordered" then "received" (ADR-093 d.2); (c) per-warehouse rows always vs only when
   multi-warehouse. Also: does an edited quantity re-arm consent or invalidate the hash?
9. **Stock goal editing (CE-FR-4).** (a) a numeric input; (b) a slider over the valid range;
   (c) three preset chips (30/60/90 days of supply). Contract has no number kind today.
10. **Decision list shape.** (a) one flat ranked list as today; (b) grouped per workflow family;
    (c) grouped by deadline urgency. Process Order's subject is a *dispatch window*, not a
    product — today's card fixtures assume a product.
11. **Is a deadline/timeline view wanted?** A new surface S-FR-1 does not list, but PO-FR-8 and
    RI-FR-7 both nag against a clock. (a) no — nags are notifications only; (b) a countdown chip
    on existing cards; (c) a real deadline screen (**adds a surface — needs an explicit waiver**).
12. **Vietnamese-only?** `dictionary.md` + `design-context.md` mandate VI seller copy. (a) VI only;
    (b) VI + EN toggle for the demo audience. Note PUI-DESIGN §7's copy table is **not yet landed**
    in `dictionary.md` (#1321, open) — and `dictionary.md` is **never imported at runtime**;
    every seller string is a hardcoded VI literal in `.ts`/`.tsx`, post-processed by
    `sanitizeSellerReviewText()`. A copy-review pass has no single place to look.
13. **Repeat consent.** S-FR-9 bans it in v1, but `repeat-consent-block.tsx` and
    `lib/repeat-consent.ts` are **shipped and wired** into the in-progress page. (a) remove the
    component; (b) leave it dark behind a flag; (c) keep for the 11 legacy mock workflows, off
    for the four v1 workflows.
