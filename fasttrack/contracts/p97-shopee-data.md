# P97 — Shopee data you can trust, and the Connector fills approved cards (D85, owner 2026-11-09)

Owner grill, 9 Nov 2026, after verifying production `86c6f673` (Connector 0.3.10). Leads over
`contracts/plan-2026-11-09.md` (branch `cursor/plan-2026-11-09-5df0`, not merged): that plan stops after
its Monday steps 2–5 (gates, mock shapes, bug-log fields written down) and resumes when this contract's
T1 and T2 are done. P94 and P95 wait.

Why: on ORY, Tổng quan misses data the Connector could read, the tabs show different numbers for the
same metric, and in Kế hoạch adding and removing options gives different totals. Approved cards still
have to be typed into Seller Centre by hand for every kind except title and description.

## Findings this contract answers (production 86c6f673)

| # | Finding | Where |
|---|---|---|
| F1 | No Connector reader for shop totals, order lines, income, product period, ads per product. GMV / Đơn on Tổng quan stop at the last file upload while the end date follows the newest Connector day (`shop_totals_partial`). Profit, margin, 5 con số, Đơn hàng and KOL need the order export. | `apps/connector/src/shopee/endpoints.ts`; `shopee_analytics/loaders.py:330-370, 949` |
| F2 | Connector posts `order_type=confirmed` only; Quảng cáo reads `placed` → its charts stay empty from the Connector. | `connector/src/shopee/sync.ts:96,141`; `ops/shopee_dashboards.py:42` |
| F3 | Ads: a homepage entry without `campaign_id` (GMV Max shop-level) is drift and stops ads for the version; a day with only the ROAS-target row counts as posted. | `reader-map.ts:476, 479-486`; `scheduler.ts:101, 377-383` |
| F4 | KOL rows only mark existing order-export lines; 5 of 8 affiliate datasets are written and read by no screen; numeric `order_id` or a different money scale would stop the dataset. | `ingest/writers.py:232-297`; `affiliate-map.ts:123, 186, 239` |
| F5 | Kế hoạch: re-adding an option resets it to V1 with empty inputs; a shop voucher's reach = union of the other options' products; only the first voucher is stacked while every option's P50 is still summed; "today" margin moves with the plan's products; each call reloads the newest anchor day. | `sr/plans.py:398`; `plan.tsx:96`; `sr/mega.py:167, 203`; `sr/plan_aggregate.py:112-142, 327-347` |
| F6 | No single metrics layer: Tổng quan (Shopee totals), Sản phẩm (export or lines per row), Luồng (export period, raw SQL), builder (90 d mixed), Kế hoạch (lines added onto totals) each pick their own GMV, window and anchor. Cards P25, plan P50. | `shopee_analytics/compute.py`, `matrix.py:134-142`, `ops/shopee_dashboards.py:420-426`, `shopee_builder/catalogue.py:110-154`, `sr/cards.py:166` |
| F7 | Fill-in types only title and description first line, for ORY's explicit id. Voucher, combo, ads, affiliate: no server payload, no matcher, no recon of any create form; the filler handles text inputs only (no select / radio / date picker). Approval queues nothing. | `sr/fill.py:38-39, 83-86`; `connector/src/fill/*`; `config.ts:275` |
| F8 | Two AOVs on Tổng quan for the same shop and window: one is Shopee shop totals GMV ÷ đơn (`rankings.py:300-305`, the "AOV · Tất cả" cell), the other is the traffic-flow table's GMV ÷ đơn (Connector mydata, `overview.py:122-145`) or the matrix line GMV ÷ đơn (`tong-quan-matrix.tsx:70`). Different source, different previous window → 159.265 vs 158.845, ▼9,7 % vs ▼9,9 %. | as listed |

## Decisions (D85)

1. **Order.** Shopee data first. Three tracks: T1 and T2 start now in parallel, T3 starts when the voucher
   create form is recorded.
2. **One GMV basis.** Headline GMV and Đơn on every tab = Shopee shop totals (read daily by the Connector).
   Per-product splits, profit and Δ estimates use order lines scaled to those totals so they add up. One
   window function: 30 days ending on the last complete day that every dataset the screen uses has posted;
   the screen names the day. One AOV = shop GMV ÷ shop orders; the Seller Centre AOV (minus shop voucher)
   stays a labelled second line only where the seller compares against Seller Centre.
3. **Ads orders.** The Connector posts both `placed` and `confirmed`. Quảng cáo shows placed (as Shopee Ads
   does), labelled; Tổng quan, cards and plans use confirmed.
4. **Plan totals do not depend on which options are present or their order.** Every option is evaluated on
   the same base, frozen per draft plan (`as_of` pinned at creation, refreshed only by an explicit "Cập nhật
   số"); shop-wide levers always apply to all shop orders; one joint lift per product (no summing of P50s
   on the same product); a second option on an exclusive field is refused or moved to the next group (P94);
   remove-then-re-add restores the removed row's version and inputs. Add → remove → add returns the same
   number (test).
5. **Connector reads orders and shop totals.** New readers: shop totals daily, order list + income (hashed
   order ids, no buyer PII), product period, ads per product. The order export file becomes a fallback.
6. **Fill-in on approval.** Approval queues a fill job for the token's shop. The Connector opens the right
   Seller Centre create page, fills every field the card holds, highlights it, and the person clicks Lưu /
   Xác nhận. After the save the Connector captures the new id (voucher_id, combo id, campaign id) and posts it,
   so read-back starts without a typed id. Never submits. `CONNECTOR_FILL_LISTING` stays the kill switch; the
   allowlist is "this token's shop", not `PILOT_SHOP_IDS`.
7. **Fill order.** Voucher → Combo nhiều sản phẩm → Quảng cáo → Affiliate / KOL. Each starts with a
   read-only recon of its create form on ORY's Seller Centre, driven by the agent in the owner's Chrome, never
   clicking Lưu / Xác nhận / Tạo.
8. **Local p96 work** (worktree `p96-strategies`, uncommitted) is ported onto this branch as Connector
   **0.3.11**: migration 122 `shopee_affiliate_lines` + KOL view from Connector lines, ads campaign settings and
   edit-page reader, seller Connector tab. The Ops pairing rewrite is dropped except the Shopee-only guard and
   the own-scope `_shop_row` read. The local combo-test change is dropped (production has it).
9. **So sánh phương án** shows before → after for GMV, biên lợi nhuận, số đơn, AOV, CTOR, CTR, lượt xem,
   each with its range. A lever that has no modelled effect on a metric shows "không đổi" with the reason, not
   an invented lift (e.g. a voucher moves AOV and CTOR; title, cover and ads move lượt xem and CTR).
10. **Headline estimate = P50** with the P10–P90 range beside it, identical on card, builder, So sánh and
    Kế hoạch (owner, round 4). Cards stop showing P25.
11. **Goal of Tự tạo phương án** (owner, round 3): compare many strategies, of the same and of different kinds,
    and run several at once with little effort. Repetitive strategies take many targets; choosing products
    is easy and clear.
12. **One picker for every kind**, Shopee-style table: search by name or ID; filters (ngành hàng, biên, CTOR
    giảm, có đề xuất, đang chạy QC / KOL); checkbox rows with GMV, biên, tồn kho; "chọn tất cả theo bộ lọc";
    paste a list of IDs; the selection stays visible with counts and ×.
13. **One card, many targets.** A strategy applied to many products / SKUs / campaigns is one card with a
    target list: total plus per-target breakdown, untick a target that breaks a floor. Approval fills them in
    one pass, using Shopee's own bulk edit where it exists (affiliate commission, product pickers).
14. **Groups (P94) come into P97.** In So sánh, select several versions or strategies → "Chạy cùng nhau" =
    Nhóm A with one period; the combined before → after comes from the D85.4 plan math; one approval queues
    every fill; the Connector works through them one page at a time and shows a checklist of done / waiting.
15. **Combo khuyến mãi = Shopee's form** (recon): product list without per-item qty or variation; tiers
    "Mua N → x % / ₫ / giá đặc biệt"; giới hạn đặt hàng; name ≤ 25; dates. Same model as the generated
    `bundle_deal` cards. The inline voucher and the gift leave the combo and are their own kinds.
16. **Listing combo mới is its own kind**: title, images, price, stock, SKU; its estimate starts with no
    history or ranking and takes demand from the singles it contains. Fill-in after the Thêm sản phẩm form is
    recorded.
17. **Ads levers = Shopee's edit form**: daily budget (≥ ₫100.000 or unlimited), ROAS (system / custom; warn
    above Shopee's hint; warn on a second change within 7 days — performance support is lost), products,
    dates. Keyword bids leave the builder (no such field in Shopee's product-ads form).
18. **ORY now:** campaign 160675212 (Nước Rửa Chén 500ml) at ₫22.000/day (below ₫100.000) and ROAS 5.0 (hint
    ≤ 3.5), 0 views on 08-11 → an ads card for Ops today.

19. **Bot risk (owner, 2026-11-09).** Shopee's Điều Khoản Dịch Vụ Chung (k) forbids account access through
    unapproved "phần mềm tự động" (aimed at fraud, wording not exempting us); article 12339 says software not
    registered through Open Platform is not licensed. Open Platform approval is in progress, so the Connector
    readers go ahead with: one daily request budget per shop shared by all readers; per-order income only for
    newly completed orders, ≤ 100/day, no historical sweep; order list ≤ 5 pages/run; one reader at a time at
    the existing pace; any CAPTCHA / login wall / 403 / 429 stops every reader for the shop and is reported to
    Ops. When the Open Platform app is approved, orders, income, vouchers, combos and ads move to the API and
    the Connector keeps only what the API lacks (traffic sources, affiliate pages).

## Tracks

### T1 — Connector 0.3.11 + readers (connector + ingest agents)

| Task | AC |
|---|---|
| Port p96 local: migration 122 + KOL from Connector lines; ads settings + edit-page reader; seller Connector tab; Shopee-only pairing guard | KOL tab fills with no order export; tests from p96 pass on this base; LOG names 0.3.11 |
| Ads: an entry without `campaign_id` is skipped and counted, not drift; a day is done only when campaigns posted or Shopee shows zero campaigns | GMV Max shop entry fixture posts the other campaigns |
| Post `placed` and `confirmed` for traffic and ads | Quảng cáo charts fill from the Connector alone |
| KOL: `order_id` accepts number or string; money scale chosen from a captured answer, not assumed; nested GraphQL period read | fixtures from ORY captures |
| Recon then readers: shop totals, order list + income, product period, ads per product | Tổng quan has no `shop_totals_partial` / `order_lines_partial` on a shop with only a Connector; files still accepted |
| The 5 unread affiliate datasets: show on KOL or stop posting | none written and unread |
| `fasttrack/LOG.md` entries for 0.3.8–0.3.10 (missing) and 0.3.11 | — |

### T2 — One metrics layer + plan math (backend agent)

| Task | AC |
|---|---|
| `ShopMetrics` read model: GMV, đơn, AOV, units, lượt xem, CTR, CTOR, chi QC, ROAS, profit, biên, with one window / anchor function | Tổng quan, Phân tích, Sản phẩm, Luồng, builder, cards, Kế hoạch read it; Luồng drops raw SQL; a test asserts the same value on every tab for ORY fixtures |
| Kế hoạch per D85.4 | add → remove → add idempotent; total independent of option order; shop voucher reach constant; duplicate exclusive field refused with Vietnamese text |
| So sánh per D85.9 | seven before → after rows per version |
| One AOV (D85.2) | the two Tổng quan AOVs agree or the second is labelled "theo Seller Centre" |

### T3 — Fill-in on approval (connector + backend + demo agents)

| Task | AC |
|---|---|
| Fill queue: approval → job for the token's shop; Connector polls, opens the page | no fill for another shop's token |
| Filler: selects, radios, date pickers, repeated rows (combo items, keywords) | unit tests on recorded forms |
| Voucher (recon first): name, code, dates, value / %, max, min spend, usage, per-buyer, scope, products | fills ORY's form; person saves; voucher_id posted; read-back verifies |
| Combo nhiều sản phẩm, then Quảng cáo, then Affiliate / KOL | same pattern, each after its recon |

### T4 — Tự tạo phương án: compare and run many (demo + backend agents; after T2's plan math)

| Task | AC |
|---|---|
| Table picker (D85.12) shared by every kind | 30 products picked by filter in < 5 clicks; paste-IDs works; selection list editable |
| One card, many targets (D85.13) | per-target rows; untick recomputes; fill uses Shopee bulk edit where it exists |
| Groups / "Chạy cùng nhau" (D85.14, P94 contract) | mixed kinds in one group; total = plan math; one approval → fill checklist |
| Combo reshaped to tiers; Listing combo mới as its own kind; inline voucher / gift split out (D85.15–16) | builder combo = generated bundle_deal shape; old saved combos migrate or are marked legacy |
| Ads levers per D85.17 | budget < ₫100.000 refused with Shopee's text; keyword bids removed |
| P50 + range everywhere (D85.10) | same number for one option on card, builder, So sánh, Kế hoạch |

## Not in this cut

TikTok parity (P95), the ISV mock shell, the bug-log extension, Seller Centre ad-type field limits beyond
what the ads recon records. Recon still to do: Thêm sản phẩm (new listing), Mua kèm, Quà tặng, Flash Sale.
