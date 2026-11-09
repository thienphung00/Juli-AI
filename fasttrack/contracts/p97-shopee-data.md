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
10. **Open:** the headline quantile. Today cards show P25 and plans P50. Recommended: P50 headline with the
    P10–P90 range beside it, the same on card, builder, compare and plan. Owner to confirm.

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

## Not in this cut

TikTok parity (P95), groups beyond what 0.3.8 already approves (P94), the ISV mock shell, the bug-log
extension, Seller Centre ad-type field limits beyond what the ads recon records.
