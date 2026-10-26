# P64/P65 end-to-end edge cases (Shopee-reviewer sandbox walkthroughs)

A running log of every edge case found while walking the reviewer flow live on
`demo.app-juli.com`. The flow uses the partner account `shopee-review@`, pinned to Juli's
TikTok VN sandbox shop `1862f13b…`. The log is input for refining the end-to-end design of the
agent workflows: listing edit, create product, create discount, and later others.

Each entry gives: **what happened** (evidence) → **why** → **status** (fixed in PR / open) →
**design rule** to carry into every workflow.

Status keys: ✅ fixed and deployed · 🔧 fixed, not yet verified live · ⏳ open · 📌 operations.

---

## A. Connection, session, identity

| # | Edge case | Evidence | Why | Status | Design rule |
|---|---|---|---|---|---|
| A1 | Reviewer saw the bundled sample shop, not live data | 1st rejection; `REVIEWER_SHOP_ID` unset | Sample mode was the default for reviewers | ✅ P64 | A reviewer is pinned to a live shop. Sample data never appears when signed in |
| A2 | Sign-in from before a pin existed kept the sample after the pin was added | No active shop in localStorage, record `mode: sandbox` | Re-validation only *cleared* the active shop and never stored a new pin | ✅ #2151 | Session re-validation stores *and* clears derived state symmetrically |
| A3 | Access token expired (~1 h), so every `/v1` call returned 401 and the pages showed errors | 401s on reviewer/me, analysis, shop | No refresh of the Supabase session | ✅ #2154 (single-flight refresh, retry once) | Every client has proactive and reactive token refresh. A failed refresh leads to the right sign-in page, never to an error screen |
| A4 | "Mã shop TikTok" showed the internal shop cipher | `TaFcIwAAAA…` | `shops.tiktok_shop_id` held the cipher/open_id | ✅ row hidden | Never show internal identifiers to third parties. Show the TikTok shop *code* (needs a stored column, open) |
| A5 | Customer name ("Fujiwa") inside sandbox listing data: 2 manufacturer attributes, a description bullet, the main image | Seller Center edit page | Sandbox catalog was seeded from a real customer's data | ✅ owner cleaned, 📌 image has "SUNHOUSE" print | Seed data for demo or review shops must be brand-clean. Audit every text field *and the images* |
| A6 | Granted scopes list includes `*.delete`, `fulfillment.package.write`, and TikTok's own typo `serller.product.optimize` | Connection card | TikTok app scope set | ⏳ decision: keep visible | Show scopes as-is for transparency. Be ready to explain unused write scopes |

## B. Data and reports

| # | Edge case | Evidence | Why | Status | Design rule |
|---|---|---|---|---|---|
| B1 | Sandbox Analytics (A-34) is all zero, so GMV showed 0 | Probe: `latest_available_date`, all-zero intervals | Sandbox has no traffic | ✅ D73.3 orders source | When analytics are zero, compute from real paid orders and label the source. Never seed analytics |
| B2 | Today's orders are absent from the report | Report window "đến 21/10" | Report ends yesterday (UTC+7) | by design | Tell the user the window end. Test orders must be created a day ahead |
| B3 | Headline "đi ngang" (flat) while the previous period was 0 ₫ | Trang chủ | Trend copy assumed a non-zero base | ✅ #2154 | No trend claim without a comparable base |
| B4 | "Tính từ đơn hàng TikTok (Orders API)" note didn't render | Live Trang chủ | Flag placement or condition | ⏳ still not seen live | Verify source labels live, not only in unit tests |
| B5 | GMV 904k vs 902k from list price × units | 6 orders × bottle | Order totals include fees/shipping | ⏳ explain or verify with SQL | Define GMV precisely (paid order totals vs item subtotal) and show the definition |
| B6 | Test orders can't be back-dated | Partner Center create = now | Sandbox tool limit | 📌 spread orders over real days (Q3) | Plan demo data N days before a review |
| B7 | Order status change seemed to fail, then applied later ("Awaiting collection") | Partner Center | Async status transitions in the sandbox | 📌 | Re-read state after a delay before concluding a sandbox action failed |
| B8 | Seller Center edits can be lost: "Discard changes?" on navigation; custom option fields allow only 1 value ("Only 1 options supported") even after clearing | Manufacturer address field | Seller Center form quirks | 📌 | Make operator data edits in one pass. Clear old option values before adding new ones |
| B9 | Seller Center shows a CAPTCHA ("Verify to continue", drag puzzle) mid-session on Promotions | Promotions page | TikTok bot check | 📌 a person must solve it; agents may not | Operator steps in Seller Center need a person on hand. Never plan an unattended Seller Center step |
| B10 | Seed data blocks a workflow: a product discount from 07/05/2026 to 01/01/2027 (from the sandbox setup) made the only eligible product ineligible for a new discount | Promotions › Ongoing 3 (1 product discount, 2 vouchers) | Long-running seed promotion | 📌 product discount deactivated by owner decision (A); vouchers kept as Khuyến mãi data | Demo/review shop seed data must leave room for every workflow's preconditions. Check them before a review |
| B11 | TikTok auto-cancels sandbox orders that are never shipped. All 9 orders from 21/10 were `cancelled` by 26/10, so the shop had **no** paid orders in the 30-day window | `silver.orders` for shop 1862f13b: 9×cancelled (21/10), 2×delivered (07/2026) | Sandbox fulfilment timeout | 📌 new orders must be advanced to DELIVERED/COMPLETED via `sandbox order transition` | Review/demo seed orders have to reach a terminal *paid* state, or they disappear from every paid-order view a few days later |
| B12 | Trang chủ kept showing GMV 904k / 6 orders after every one of those orders was cancelled, while quick scan (live query) said `no_paid_orders`. Two surfaces disagreed about the same shop | Report from 21/10 vs `shop_quick_scan_done skipped_reason=no_paid_orders` (24/10) | The daily report is a snapshot and is not recomputed when order status changes | 📌 open | A cancellation/return after the report date must refresh (or flag) the stored report. Any surface that reads a snapshot must show its as-of date |
| B13 | Ad-hoc SQL on the wrong schema returned "no rows" and pointed at a false cause: `public.orders` is empty, the real table is `silver.orders`, and `order_items` stays in `public` | Supabase SQL editor, 26/10 | Split schemas | 📌 | Diagnostic SQL always names the schema (`silver.orders`, `public.order_items`) |
| B14 | Sandbox orders are made and moved in Partner Center › Development Shops › Test functions: Create test order (On hold), then "Change order status" one step at a time: Awaiting shipment → Awaiting collection → In transit → Delivered. Each step lags 3-10 s, and the Delivered step sometimes has to be confirmed twice. A confirm on a Delivered order returns "current order status does not support changes" (harmless). The toolkit CLI (`sandbox shop list/order list`) cannot see this shop | 26/10: 3 orders 5867922… on the hot pot, all Delivered | Partner Center UI only; CLI sees no shops for this account | 📌 | Seed orders: create, then walk each one to Delivered in the same session. Refresh the list before each confirm and read the target status in the dialog |
| B15 | "Đồng bộ ngay" does not fetch new orders: commerce steps (orders/products/returns) run at most once per 60 min per shop (`commerce_interval`), so a sync pressed inside that window only runs analytics (10 s poll). 3 orders created at 01:01 UTC arrived only with the hourly run at 01:52 | `POST /v1/reviewer/shop/sync` 202 at 01:08 → `poll_shop` 10 s; `shop_ingestion_state.commerce_last_run_at` 01:52 | `_commerce_due` ignores a user-initiated sync | 📌 open | A user-pressed sync must bypass (or shorten) the commerce interval, with its own rate limit. The UI should say when the next order fetch happens |

## C. Cards and emission

| # | Edge case | Evidence | Why | Status | Design rule |
|---|---|---|---|---|---|
| C1 | Only card was a legacy `seller_center` card (not executable) | Approve → "Juli không ghi gì lên TikTok" | Executable cards need traffic | ✅ quick scan by orders | Every shop with orders must be able to get ≥1 executable card |
| C2 | Legacy card "Lý do" was raw English internals ("opportunity:", "proxy") | Quyết định | Stored before the Vietnamese copy existed | ✅ hidden for sandbox; VN copy for new cards | Copy is rendered at read time from signals, or migrated, never stored final text only |
| C3 | Hiding by "no Vietnamese letters" missed a card that mixed EN/VN | 19/10 card still showed | Heuristic too weak | ✅ (gone after deploy) | Use explicit card versions or flags, not text heuristics |
| C4 | Forced quick scan surfaced no listing card | After `shop_quick_scan(force)` | Daily budget full, or title lever blocked by an existing card | 🔧 #2154 | Operator-forced runs must surface ≥1 card or say why not |
| C5 | Create-product card labelled "Tối ưu sản phẩm" | Card | Workflow label hard-coded | ✅ | Label comes from the lever or workflow, never a constant |
| C6 | Run header doubled: "Tạo sản phẩm · từ Tạo sản phẩm mới từ «…»" | Run panel | Header prefixes a title that already has the prefix | ⏳ | Header = verb + subject. Never prefix a pre-labelled title |
| C7 | Old declined or failed runs stay in the "Hàng chờ" queue ("Sự cố", "Không thay đổi") | Queue | Queue shows recent history | ⏳ decide retention for reviewers | The reviewer queue should show only the current session's runs, or label older ones clearly |
| C8 | "Đo lường" lists 11 old cards (6 × nồi lẩu 25–26/08, 5 × bình nước 20/08), all "Tối ưu sản phẩm" | Reviewer Đo lường tab | Team's W5 live-verification runs (Aug) on the same sandbox shop are shown to the reviewer | ⏳ P66 | A reviewer/demo account sees only its own runs (since the account was created). A shared test shop needs per-actor history |

## D. Agent run, confirm, execute

| # | Edge case | Evidence | Why | Status | Design rule |
|---|---|---|---|---|---|
| D1 | Duyệt disabled until stability bands are set; reviewer couldn't set them | "Đặt ngưỡng" read-only | Rules write blocked for reviewers | ✅ sandbox rule writes | Every prerequisite of a flow must be completable in the same role |
| D2 | Simulation chip "Đã chạy thử" on a real sandbox write | Run chip | `run.simulated` set for sandbox merchant writes | ✅ | A real write is never labelled simulated, and vice versa |
| D3 | Confirm with edits → 422 "Bước này không có nội dung sửa được" | create_product confirm | Only listing edits were editable | ✅ #2154 | Every write step declares editable fields; UI edit and server validation share one map |
| D4 | After "Huỷ sửa" the edit persisted ("Bạn đã sửa") | UI | Cancel didn't clear state | ✅ #2154 | Cancel restores the model proposal exactly |
| D5 | After "Huỷ sửa" the confirm button was disabled; the proposal had to be re-selected | Button `disabled` | Selection state cleared by cancel | ⏳ | Cancelling an edit keeps the proposal selected |
| D6 | After confirming, the panel stayed "Đang chờ bạn" until reload | Two runs | SSE update after confirm not applied | ⏳ | Confirm must move the panel optimistically and follow SSE; never a stale wait state |
| D7 | Model put "Fujiwa" in the title (from the description excerpt) | Proposal | Source text not filtered | ✅ D73.5 source-name rule (data, not hard-coded) | Rules are gates for the LLM as data. Source names are withheld from the model and checked on output, edits and execution |
| D8 | Required compliance attributes (VN manufacturer name/address) dropped by the name rule, so create can never pass | Code review | Over-broad rule | ✅ copy required attrs verbatim, never to the model | Separate legal facts (copied) from marketing copy (generated, gated) |
| D9 | **TikTok 12052217: category_version must be V2 for all-region shops** | Run 74aefd1a | v1 categories sent | ✅ #2158 deployed, ⏳ live create not yet retried | Pin API versions per shop type. Read the vendor's error text |
| D10 | **Refused TikTok write shown as success** ("Đã ghi lên TikTok", measurement scheduled) | Run 74aefd1a | Runner ignored the tool's `ok`; ledger marked succeeded | ✅ #2158 | A write is a success only when the vendor confirms it. ok=false means a failed run, no measurement, card returned |
| D11 | Old run 74aefd1a still stored as success | events `ok=true` | Data written before the fix | ⏳ SQL correction | Fixes to outcome logic need a data backfill for already-written runs |
| D12 | TikTok's refusal reason missing from logs and UI | `catalog_create_create_failed` code only | `extra=` dropped by journald | ✅ #2156 | Log vendor code + message + request_id in the message line; show the reason to the user |
| D13 | Create cap 3/24h hit → 429 with **no message in the UI** | approve 401 → refresh → 429 | Cap reached by test runs; no UI copy | ⏳ | Every server refusal has user-facing copy (cap: "Đã tạo 3 sản phẩm trong 24 giờ; thử lại lúc HH:MM") |
| D14 | Test runs consume the reviewer's daily cap | Cap counted on approve | Shared counter | ⏳ decide: count only successful creates, or reset before submission | Caps should count successful writes, and the operator must be able to reset them for a demo account |
| D15 | Discount run ended without proposing: "1 khuyến mãi giá đang chạy hoặc sắp chạy", then "Luồng đã kết thúc. Vui lòng xem lại tại Quyết định." | Run 12d703c0 | Product already in a price promotion (no stacking) | ⏳ | An agent that declines must say why in plain words and propose the next step (another product, or end date of the existing promotion). The card should not be emitted for an ineligible product |
| D16 | Discount card emitted for a product that already has an active/upcoming price promotion | Same | Emission doesn't check eligibility | ⏳ | Emit only when the TikTok preconditions hold (stock, no overlapping promotion) |
| D17 | Only 1 of 2 products "còn hàng, đủ điều kiện" for promotion | Run step 1 | Stock/eligibility read | ⏳ verify which and why | Show which products were excluded and why |
| D18 | ✅ **First real TikTok write verified**: discount "Combo mini tiện dụng 12%" (id 7699734374178817800) created via Promotion API, shown in Seller Center (Upcoming, 23/10 12:45 → 30/10 23:59, Product discount) and in Juli ("TikTok xác nhận lúc 12:43") | Run 887bb1be + Seller Center | — | ✅ live 2026-10-23 | Always cross-check a write in the vendor's own UI |
| D19 | Proposal not selected by default (confirm disabled even without "Huỷ sửa") | Run 887bb1be | Default selection missing | ⏳ P66 (D5) | A single proposal is selected by default |
| D20 | Run panel steps out of order (the create step listed first) after reload | Run 887bb1be | Step ordering by completion/insert, not plan order | ⏳ P66 | Steps render in plan order |
| D21 | After the promotion was created, listing-edit template steps still show ("Ghi lên TikTok Shop", "TikTok duyệt lại trang sản phẩm", "Kết thúc · đặt lịch đo") with "Juli đang ghi lên TikTok Shop…"; run stays "Đang chạy" | Run 887bb1be | Step template not per workflow; run not finalised after the write | ⏳ P66 | Each workflow has its own step template; a run finishes when its final write is confirmed |
| D22 | Run header generic "Juli tự áp dụng lên TikTok Shop · Lượt chạy · …" for a promotion run (the queued view showed "Tạo khuyến mãi · …") | Run 887bb1be | Header falls back after reload | ⏳ P66 | Header derives from the workflow on every render |
| D23 | Measurement copy contradicts itself: "Chờ đo · ngày 0" and "Đã qua ngày 7 nhưng Juli chưa có số đo…"; a sandbox can never be measured; "Hoàn tác" offered on others' runs | Đo lường cards | Status label ignores elapsed days; sandbox runs scheduled for measurement | ⏳ P66 | No measurement on shops that can't produce readings, with a plain statement why. One status per card. Revert only for the actor's own runs |
| D24 | Đo lường says "Chưa có lượt chạy nào ghi thay đổi lên TikTok Shop" while the reviewer has 2 successful writes (product create, discount create) | Live after P66 | Đo lường counts only measurable listing edits | ⏳ P67 (D75 Q2) | Đo lường lists every confirmed write with its TikTok id; a sandbox says "Không đo · shop sandbox" |
| D25 | ✅ Product create verified live: TikTok product 1738157559581542019 "… (dùng nấu lẩu, mì, súp)", category 1216272 "Nồi lẩu điện" (V2), Live, SKU JULI-F7B54199 — also in Seller Center; panel advanced without reload; proposal pre-selected | Run 0b92db41 | — | ✅ live 2026-10-23 | — |
| D26 | Forced quick scan (after P66) still surfaces no listing-edit card | Task a3a6330c | Unknown | ⏳ P67 (D75 Q1) | An operator-forced scan surfaces ≥1 card or records why |
| D27 | Our test writes block the reviewer's own flow: the 12% test discount covers both products until 30/10, so the discount card won't appear for Shopee; the account carries our test history | Live | Shared sandbox state across testers | ⏳ D75 Q4: recreate the account + end the test discount just before submission | A review account must be reset to a clean, demo-ready state right before submission (history, promotions, caps) |
| D28 | Stale run 74aefd1a (refused create shown as written) corrected by SQL → now "Thất bại" | Owner SQL + live check | Data written before #2158 | ✅ | Outcome-logic fixes need a data backfill |

## E. Platform and operations

| # | Edge case | Evidence | Why | Status | Design rule |
|---|---|---|---|---|---|
| E1 | `EMAXCONNSESSION` at pool 15 → intermittent 500s, crashed runs | worker + API journal | Two blue/green API slots (5+5 each) + per-task worker connections | 📌 stale slot stopped; #2157 | Connection budget per service ≤ the pooler cap (nano = 15) and an alert on EMAXCONN |
| E2 | `systemctl restart juli-api` crash-looped on port 8000 | journal | Legacy unit vs blue/green candidates | 📌 never use it | Runbooks name the blue/green units, not the legacy unit |
| E3 | A space in an AWS secret key broke `/etc/juli/api.env`, and the deploy failed in migration detection | line 30 "command not found" | Unvalidated env generation | 📌 fixed by owner | fetch-secrets must validate keys (`^[A-Z0-9_]+$`) and refuse a bad secret; check with `( set -a; . file )`, not `bash -n` |
| E4 | VPS journal is UTC; UI is UTC+7 | empty greps | Time zones | 📌 memory | Always shift by −7 h when correlating UI times with logs |
| E5 | Deploy gates the local check.sh doesn't run: full unit suite (facade export, ratchet), full demo suite, Postgres integration on changed tests | 3 failed deploys | Local check is change-scoped | 📌 | Before tagging, run the full unit + demo suites (or wait for CI) |
| E6 | Flaky tests under load (ops-pages vitest, status-record migration, onboarding speed) | reruns pass | Timing | ⏳ | Track flakes; a flake must not block a review-critical deploy |
| E7 | Fresh worktree: contract tests fail without node_modules | 32 local failures | pnpm install per worktree | 📌 known | Run `pnpm install` in each new worktree before suites |
| E8 | Generated files (quality corpus, surface inventory) conflict on every merge | Every merge | Generated from the tree | 📌 | Take upstream, regenerate on the combined tree, commit last |
| E9 | Claude-in-Chrome extension disconnects mid-action (twice; once right after clicking an irreversible Deactivate) | Tool error | Extension/session | 📌 | After any reconnect, re-read the page state before assuming an action applied or failed |
| E10 | After each blue/green deploy, the old slot (`juli-api-candidate-8000/8020`) keeps running with its own pool, exhausting Supavisor nano (15) → EMAXCONNSESSION | 24/10: stopped 8020 by hand after deploy 2d56fb65 | Deploy script does not stop the drained slot | 📌 open (#2157 adjacent) | The deploy stops (or scales the pool of) the old slot once the new one passes health. Pool budget per process is part of deploy review |
| E11 | TikTok order webhooks for the sandbox shop go to DLQ as `unknown shop tiktok_shop_id=7495274531001436791`: `shops.tiktok_shop_id` holds the shop **cipher** (`TaFcIwAA…`), while webhooks carry the numeric shop id | `etl_dlq` 01:16 UTC ×2, ORDER_STATUS_CHANGE | Shop identity stored as one key; webhook lookup uses another | 📌 open | Store both the numeric shop id and the cipher on connect and resolve webhooks by either. Alert on any `unknown shop` DLQ for a connected shop |

---

## Open questions for the end-to-end design

1. What does "success" mean per workflow? Vendor-confirmed write + read-back (D10). How is it shown, and when does measurement start?
2. Eligibility before emission: each write workflow declares its TikTok preconditions (stock, overlapping promotions, category rules) and is emitted only when they hold (D15–D16).
3. Declines and refusals: one copy contract for "the agent decided not to act", "TikTok refused" and "Juli refused (rule/cap)" (D13, D15, D12).
4. Caps and quotas for demo/review accounts (D13–D14).
5. Run history visible to a reviewer (C7, D11).
6. Rules as data drafted by the LLM per shop/category/product (#2153); forecasting/ROI for promotions (separate phase).

## Decisions taken in the follow-up grill (D75, owner, 2026-10-23/24)

1. **Listing edit**: re-run the forced quick scan, then test; no card appeared → root cause + fix in P67.
2. **Đo lường (sandbox reviewer)**: list every confirmed write (create product, discount, listing edit) with its TikTok id and confirmation time, chip "Không đo · shop sandbox"; sellers unchanged.
3. **429 copy and the decline explanation**: verified by backend and frontend tests only; no live trigger, no extra sandbox products, no env change.
4. **Before submission**: recreate the review account (fresh user id and created_at → clean history) and end the 12% test discount so the reviewer has an eligible discount card. Keep the 3 products.
