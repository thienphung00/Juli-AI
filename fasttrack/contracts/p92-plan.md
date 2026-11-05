# P92 — Tự tạo phương án: every strategy built precisely, compared on driver + profit

Owner decisions, 2026-11-05 (after P91 shipped as `fasttrack-deploy-20261104T1301Z`). Builds on P91 D-2 / D-3
(`p91-plan.md`: versions, compare, manual offers, `combo_multi`). UI is drawn first and approved by the owner
before it is built (same rule as P90 / P91). Branch `fasttrack/p92-builder`, based on the product-page hotfix
`fasttrack/p91-hotfix`.

Why: the builder (Quyết định › TỰ TẠO PHƯƠNG ÁN · SO SÁNH PHƯƠNG ÁN) only offers the products sold in the last
30 days (its list comes from the 30-day matrix), its voucher sliders are fixed at 5–30k value and 150–300k
minimum spend (so 5k / 100k cannot be entered), and most strategy types have no precise inputs.

## B-1 Product picker and excluded listings
- The picker lists **all active listings** Juli knows (Connector catalogue + order lines), sorted by 90-day
  GMV. Each row: name, item id, 30 / 90-day orders, whether a giá vốn is set ("thiếu giá vốn" chip).
- **Cài đặt › Loại trừ sản phẩm**: the shop lists listings to exclude, each with a reason (ngừng bán · quà tặng ·
  hàng phân phối · khác) and an undo. An excluded listing gets **no cards, no product rows, no builder entry,
  and no Phân tích flags**; shop totals (GMV, profit) **still include its sales** so they match Seller Centre,
  with one line "trong đó Xđ từ sản phẩm đã loại trừ". Stored as a shop rule (versioned like the other
  Thông số shop inputs, audited); also accepted in the Thông số shop file.

## B-2 Variation picker (product scope)
- After picking a product, the builder shows a **variation picker** (Combo 3 / 5 / 10 hộp …); a strategy
  applies to the chosen variation(s). Minimal by default.
- An **expand** ("So sánh phân loại") shows, per variation, **only price and profit margin**: list price,
  selling price, price per unit (pack count from the variation name or the Thông số shop pack column), margin %
  — every other metric is the product's and is not repeated. Same expand on the **product page (Sản phẩm)**.

## B-3 Outcome shown for every version
- Each version names its **driver metric(s)** and shows the same four for all: Δ GMV, Δ orders, Δ profit,
  margin after; plus the cost of the change. Conversion is always **CTOR** (orders ÷ clicks) across the app.
- Driver per strategy: voucher → AOV, CTOR · combo → AOV, CTOR · mua kèm → AOV · quà tặng → CTOR, orders
  (+ AOV with a min-spend trigger) · giảm giá → CTOR, orders · giá bán / flash sale → CTOR, orders · quảng cáo →
  spend, GMV, ROAS · tiêu đề → views, CTR · ảnh bìa → CTR · mô tả → CTOR · phân loại / set → AOV, CTOR ·
  affiliate / KOL → affiliate orders · hiển thị giá → CTR, CTOR · ẩn / đưa lại listing → views.
- **Estimate basis** (owner): this product's own past response first (e.g. its orders when discounted before),
  else the shop's other products, else category priors. Always a low–high range plus the basis label
  ("từ lịch sử sản phẩm" / "của shop" / "ước tính chung"); "không đủ dữ liệu" when no basis is solid.
  Break-even lift (the CTOR / orders / attach rate needed to keep profit flat) is always shown.
- Breaches of the margin floor or spend cap warn, never block (P91 rule).

## B-4 Strategy inputs
**Voucher** — typed numbers, no sliders. Kinds: shop voucher (whole shop), product voucher (chosen products),
follower / new-buyer voucher, livestream / video voucher. Inputs: discount type (đ or %), value, minimum spend
(from 0), % cap when %, usage limit, per-buyer limit, start / end. Suggested chips from the shop's AOV
(e.g. 5k/100k, 10k/100k, 10k/150k, 15k/200k). Each version shows how many past orders would have qualified and
the voucher cost at expected usage. So "5k cho đơn 100k" vs "10k cho đơn 100k" compare side by side.

**Combo nhiều sản phẩm** — 2–6 products, each with quantity and variation; price as fixed price, % off or đ off
the sum. Live: sum of list prices, combo price, savings %, total giá vốn + đóng gói, fees, profit per combo,
margin, floor line. Target: a new combo listing or Shopee "Combo khuyến mãi" (bundle deal).
**Gợi ý ghép**: "Sản phẩm hay mua cùng" from the shop's order lines (co-purchase counts), one click to start.

**Mua kèm (add-on deal)** — 1 main product, 1–5 add-on products each with add-on price (or % off) and a
per-order limit. Shows each add-on's margin at the add-on price, the attach rate needed to break even, and the
expected AOV lift.

**Quà tặng** — pick the gift from the listings (or "quà không bán" with a typed unit cost), quantity, and the
trigger: buy product X, or order ≥ minimum spend. Shows gift cost = giá vốn + đóng gói, cost per order, the
gift's stock and how many gifts the expected orders use, and the CTOR / orders lift needed to pay for it.

**Giảm giá** — per variation, % or final price; dates; per-buyer limit. Shows the price buyers see after the
shop voucher, margin per variation, the giá sàn line (warning), orders needed to keep profit flat, and the
product's past response to discounts.

**Giá bán + Flash sale** — change the list price, or a shop flash-sale slot with price, stock and slot time.
Same economics as giảm giá.

**Phân loại / set** — add or merge variations (Set 3, Set 5 …) with their own prices and SKUs (as in the XM1 /
XM3 planned changes); shows price per unit and margin per new variation; hide-old-listing follow-ups.

**Quảng cáo** — four levers: daily budget (đ/day per campaign), ROAS target (GMV Max / auto bidding), add /
remove products per campaign (each product's break-even ROAS vs actual ROAS), keywords + bids for manual
keyword campaigns (search volume from the keyword data). Shows expected spend, GMV, ROAS range and the
break-even ROAS line.

**Tiêu đề** — after picking the product, a keyword table: keywords in the current title, search suggestions,
top competitor titles, the ads keyword report; each with search volume, difficulty, in-title yes / no. Tick
keywords → the LLM writes 2–4 titles ≤ 100 characters (P91 D-4) using them; free edit with a live counter and
keyword-coverage check. "Điền bằng Connector" fills the chosen title.

**Ảnh bìa** — the LLM proposes 2–4 overlay concepts from the product's numbers (unit price, % off, voucher,
benefit line); Juli's cover tool renders them on the **real product photo** (the photo is never altered);
edit text, pick. **Mô tả** — the LLM drafts 2–4 first lines (unit price, key benefit); edit, pick; fill via
Connector.

**Affiliate / KOL** — commission rate per product, target campaign, sample sending (cost = giá vốn + đóng gói +
ship, P91 D-9 / D-11).

**Hiển thị giá + listing** — show price per unit; hide or relist a listing (planned-change kinds, P91 D-13).

## B-5 So sánh phương án
- Up to 4 versions in one table, **any types mixed** (e.g. P1 voucher 5k/100k, P2 voucher 10k/100k, P3 combo,
  P4 quà tặng). Rows: cost, Δ GMV, Δ orders, Δ profit, margin after, then each version's driver metric.
  "Chọn" sends the chosen version to Quyết định as a manual card (P91: JC code, measurement window, plan).

## B-6 Out of scope
- No automated writes to Seller Centre (assisted only; a person saves). No buyer data. LLM text never claims a
  certification or ingredient the shop has not given. Image generation of new product photos is not built.

## Waves (after the artboards are approved)
1. Backend: catalogue picker endpoint + exclusions rule (B-1), variation economics (B-2), per-kind input
   schemas and evaluators (B-4), estimate basis (B-3).
2. Keyword table + LLM title / overlay / description drafts (B-4 tiêu đề, ảnh, mô tả).
3. Web: builder per kind, variation picker + expand, compare table, Cài đặt exclusions, product-page expand.
4. Integration + one deploy.

## B-7 Artboard follow-ups (decided 2026-11-05, owner delegated "build and push together when finished")
1. A listing without giá vốn can be built: profit and biên show "chưa tính" with a link to Thông số shop.
2. Combo "cost of the change" = the discount given to buyers (per-combo discount × expected combos).
3. Thông số shop file columns "loại trừ" (Có / Không) and "lý do"; stored keys `excluded`, `exclude_reason`;
   same versioned old → new diff and audit as the other inputs.
4. "Quà không bán" takes a typed unit cost and never touches Juli's stock figure.
5. Break-even shown both as extra orders and as CTOR ("≥ 18 đơn, CTOR ≥ 2,71%").
6. Ads daily-spend cap: per shop from Cài đặt › Mục tiêu (`ads_daily_cap`); per-campaign caps are not built.
7. "Chọn" on a version with a floor breach opens the P91 warning dialog ("Vẫn tiếp tục"), never blocks.
8. P91 `TuTaoPhuongAn*.dc.html` are kept as history; README marks P92 as current.
Not drawn and built from the desktop artboards: mobile of the kinds panels, CaiDatLoaiTru and the SanPham
variation expand (same content, stacked).

The product-page hotfix (`fasttrack/p91-hotfix`: version shape, partial product-period GMV) ships in the same
deploy as P92.

## B-8 Seller Demo parity for the Ops shop pages (owner 2026-11-05)
The seller app (Demo) gets the four Ops shop pages, read-only, same numbers as Ops, own shop only, no buyer
data (order IDs hashed): **Từ khóa** (keyword volumes, positions, ads keywords; also the source of the B-4
title keyword table), **Quảng cáo + khuyến mãi** (per campaign / voucher / promotion breakdown), **Đơn hàng**
(order-level levers, status, income per order), **Sản phẩm + luồng** (product × traffic-source matrix).
Backend: demo routes mirroring the Ops ones (same services, `get_active_shop` scope). Web: four Demo nav
entries reusing the Ops components. Seller access stays the existing "Mời seller" handover (P9-B): after the
first accept the seller signs in at demo.app-juli.com with her e-mail and a 6-digit code, no new invite.

## B-9 Price and margin on every product table, seller side included (owner 2026-11-05)
- **Sản phẩm list, Sản phẩm + luồng table, Phân tích** (Demo and Ops) show for every product: **giá** (selling
  price; min–max across variations, list price struck through when different) and **biên** (margin %), next to
  GMV / orders. The list shows every active, non-excluded listing: products with sales in the window first
  (GMV sort), the rest under a collapsed "N sản phẩm không có đơn trong kỳ".
- **Margin basis, stated on screen:**
  - *Per order / per product (history)*: profit of each real order — Income-file actual fees (fixed fee,
    service fee incl. Voucher Xtra, payment fee, infrastructure fee per order), seller voucher share, combo /
    discount, affiliate commission, shipping the seller bore, ads allocated by the product's share, giá vốn +
    đóng gói, VAT per P91 D-12 — summed per product. Basis label "theo đơn thực tế"; "ước tính" when an order
    has no Income row (fee formula used) or the cost is assumed; "chưa tính" without giá vốn.
  - *Per strategy (builder, cards)*: every affected order is recomputed with the size-dependent fee formula
    (per-order components split across the order's lines, percentage fees on the new buyer-paid amount), the
    new voucher / discount / gift / add-on and the ads change, so the margin follows the basket size.
  - A backtest guards the formula: for orders with an Income row, formula fees vs actual fees per order;
    the mean absolute gap is reported in Ops and must stay ≤ 1 % of buyer-paid (test on synthetic data, Ops
    figure on real data).

## B-10 Competitor prices and draft plans that build on each other (owner 2026-11-05)
- **Price card trigger unchanged**: margin under target / price under the floor (raise to floor + 2 %). Competitor
  prices are context, not a trigger.
- **Collection**: the Connector reads public Shopee search pages weekly for each product's 1–3 main keywords
  (from the keyword table): page-1 listings (name, shop name, price, price range, sold/month, item id, image
  id), no login, no buyer data, background tab, ORY pilot only, drift handling as the other readers. New
  ingest dataset → the existing `market_listing_snapshots` / `market_keyword_snapshots`. Juli matches similar
  listings (same keyword, pack-normalised) and computes price per unit (per hộp / 100 cái / 500 ml / cuộn …).
  Data older than 14 days shows its date and a "cũ" chip.
- **Display**: product page block "Giá thị trường" (price per unit vs page-1 median, P25–P75, the 5 closest
  similar listings with name, shop, price, per-unit price, sold/month; keyword; collected date) on Demo and Ops;
  builder price / discount / flash-sale panel shows a live marker of the drafted price inside that range.
- **Draft plans compose in order**: per product the draft is a sequence price → giảm giá → voucher (e.g. cap
  100k) → combo / mua kèm / quà tặng → ads. Each step is evaluated on top of the previous ones (new price, new
  basket, size-dependent fees, B-9), showing margin and Δ profit after each step and in total, plus shop-wide
  totals. Nothing executes until the plan is confirmed (P91 D-6); reordering or removing a step re-evaluates
  the rest.
- Seller (Demo) sees only median and average of similar products; listings and shop names are Ops-only.
