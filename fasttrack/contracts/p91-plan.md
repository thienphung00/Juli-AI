# P91 — every card for every aspect, versions to compare, manual offers, card codes

Owner decisions, 2026-11-04 (after P90 shipped as `fasttrack-deploy-20261104T0109Z`). Builds on P90
(`p90-metrics.md`, `p90-plan.md`, ADR-120 / ADR-121). UI is drawn first and approved by the owner before it
is built (same rule as P90).

## D-1 All cards, all aspects, kept (no "phương án khác")
- The generators already propose cards per product across families (listing, ads, promotion, voucher, sale,
  combo, affiliate). Every eligible card is now **persisted** — ranking no longer drops a card because its
  product already has a better one.
- `duplicate_product` stops being a drop filter. It becomes the per-product queue: each open card gets
  `product_queue` = 1, 2, 3 … among the open cards of the same product (best score first). The other hard
  filters (`locked_by_plan`, `out_of_stock`, `below_operating_floor`, `over_spend_cap`,
  `negative_profit_p50`) still drop.
- **Sản phẩm (product page)** shows every open card of that product, grouped by family, each with its versions.
- **Quyết định stays one card per product**: the card with `product_queue = 1`.
- **Replacement when a card closes**: when the product's Quyết định card closes, the next open card of that
  product moves up (re-numbered queue, the new #1 appears in Quyết định). Closed =
  `dismissed` / `withdrawn` / `expired` / `superseded` / `executed` — **all at once** (owner 2026-11-04: an
  executed card is replaced right away so Quyết định stays on top). Adding a card to the draft plan (D-6) also
  moves the product's next card up, so several changes of one product can be stacked in one plan. A card whose
  product is still being measured carries `product_measuring = {until, change_set}` so the UI can say
  "Sản phẩm đang đo: còn N ngày"; executing it early follows D-7.
- No "phương án khác" label anywhere.

## D-2 Versions inside a card (comparison)
- Every card carries **2–4 versions**: `versions[]`, each a full evaluation of the same change with other inputs
  (e.g. voucher 10k / 15k / 20k with its min spend; combo tier 5 % / 10 % / fixed price; ads budget −20 % /
  +20 % / +50 %; title A / B). Version 1 = the engine's default (the ranked one). Each version has the same
  payload as a card today (five numbers before → after, Δ profit P50 and range, margin, AOV, cost, floor breaches,
  spend check, certain vs predicted layers).
- The generator picks the alternative inputs per change_kind from the kind's sliders (`kinds.py`); a version that
  is refused or breaches the floor is still shown, marked, never ranked.
- The seller approves **one version**; `chosen_version` is recorded on the decision and in the card events.
  What-if on a version updates that version only.

## D-3 Manual offers and comparison ("Tự tạo phương án", "So sánh phương án")
- `POST …/recommendations/compare` (Ops Xem+ and Demo seller; saves nothing): 2–4 variants, each
  `{change_kind, items, extra (addon_item, gift_item, pair items), inputs}` → the same `build_card` output per
  variant, side by side, plus the deltas between them (profit, margin, AOV, orders, GMV, cost).
- `POST …/recommendations/manual` (Ops Vận hành and Demo seller): saves one variant (or a compare's chosen one)
  as a card with `origin = "manual"`, `created_by` (staff or seller user id), its own versions if more than one
  variant was sent. It enters the product's queue at its score; if the creator asks `primary = true`, it takes
  `product_queue = 1` and the previous #1 moves to 2. Approve / Đã làm / verification / learning work unchanged;
  learning statistics keep `origin` so manual and engine cards are calibrated and reported separately.
- **Combo calculator widened** (existing `eval_bundle` / `eval_add_on` / `eval_gift` reused):
  - a combo of **2–3 different products** (each with qty), not only tiers of one product;
  - discount as **% / amount (đ) / fixed combo price (đ)**;
  - optional **stacked voucher** (existing voucher rule) and optional **gift item** (cost = giá vốn + đóng gói);
  - per combo: buyer pays, fees (per-order fees once, split by value), contribution, margin, AOV, floor check per
    SKU in the combo, cost per combo order, break-even extra combo orders; predicted range via the lift model
    (`combo_pack`).

## D-4 Titles: 100 characters
- `MAX_TITLE_CHARS = 100` for Shopee title cards (was 120). Every title a card proposes — rule-based today, an
  LLM writer later — is cut to 100 at a word boundary and refused above 100; the manual/what-if title input is
  refused above 100 (422). The LLM writer, when added, gets the 100 limit in its prompt AND the same hard check.

## D-5 Card codes (for the future Excel export)
- Every card gets a **human-readable code**, unique per shop and never reused: `JC-<yymm>-<seq4>` (e.g.
  `JC-2611-0007`, sequence per shop across months) assigned when the card is first persisted; versions are
  `JC-2611-0007-V1` … `-V4`; a card that replaces another through re-generation keeps `supersedes` → the old code.
  The UUID stays the primary key; the code is shown on the card (Demo and Ops) and carried in events.
- New migration 116: `shop_proposals.code` (unique per shop) + a per-shop counter; backfill existing Shopee cards.
- Export itself is a later step; the code, versions, chosen version, inputs before/after, status history
  (`card_events`) and verification result must all be readable by card code so the export is one query.

## D-6 Draft plan ("Kế hoạch"): approve without executing, see the aggregate, confirm all at once
- Each shop has one open **draft plan**. "Thêm vào kế hoạch" on a card (a chosen version) puts it in the plan
  (card status `planned`; nothing is executed, nothing is sent to the team). Cards can be removed, their version
  switched or what-if adjusted while planned; each change re-aggregates at once.
- **Aggregate panel** (seller and Ops): today → after the plan for the five numbers, Δ lợi nhuận/tháng (chắc
  chắn + dự kiến range), biên, AOV, số đơn, GMV, **chi phí** (per day and per month, vs trần chi/ngày), floor
  breaches, and per card its contribution to the total. Also "if you remove this card" deltas.
- **Joint, not summed**: cards on the same product are evaluated together on the same order lines (a discount +
  a voucher + a combo stack on the same orders; fees recomputed once per order; the floor check runs on the stacked
  price — a plan can breach a floor no single card breaches). Cards on different products add up; a shop-wide
  lever (shop voucher, shop ads budget) is applied to the orders the product changes already modified (overlap
  counted once). Predicted ranges: P50s add after the joint certain layer; the range combines the cards' ranges
  (simulation draws or root-sum-of-squares — implementer chooses, documents, tests).
- Confirm ("Xác nhận kế hoạch"): **never blocked** (owner 2026-11-04). A floor breach or spend-cap breach shows a
  warning naming each SKU / the amount over the cap; the seller (or Ops) confirms a second time ("Vẫn tiếp tục") to
  proceed. The acknowledged warnings are recorded on the plan and in each card's events (who, when, which
  breaches). Same rule everywhere a breach appears: approving a breaching version, saving a breaching manual
  variant, adding a breaching card to the plan — warning + confirm, never a disabled button. On confirm every card becomes `approved` with the plan id, one planned
  execution date, and the plan enters the team's queue; assisted execution (human clicks Save, read-back
  verification per card) marks each card executed; the plan is "đã thực hiện" when all are.
- Reuse what exists: `shop_proposals.lever_plan_id`, `plan.py` (measurement plan), the `locked_by_plan` filter,
  mega_sale aggregation code where it fits.

## D-7 Measurement when changes run together (owner approved 2026-11-04)
- **Unit of measurement = the product's change set**, not the card: all cards of one product executed on the same
  day are one change set, measured together against the product's baseline (flow baseline counterfactual) and
  compared with the plan's joint prediction for that product. Different products → separate change sets; the plan's
  shop total is measured too (Σ predicted vs shop actual).
- Shop-wide cards are measured at shop level; product change sets executed with them carry a flag
  "kèm thay đổi toàn shop" in their result.
- **Learning**: a change set with one card calibrates its change_kind as today (clean); a multi-card change set
  calibrates the joint prediction and counts for each change_kind with a reduced weight (config, default 0.25), never
  as a clean single-kind sample.
- **Executing on a product that is still being measured**: allowed; the running measurement is cut that day.
  ≥ 3 days measured → its result is kept as "đo được N ngày" (lower confidence); < 3 days → "không kết luận". A new
  change set starts. The confirm dialog says which products' measurements will be cut.

## D-8 Measurement window chosen by the user
- Per plan (default for all its cards) and overridable per change set: **minimum 3 days**, presets **7 / 14 / 28**
  plus custom (3–90). The recommended preset is marked: the smallest preset whose minimum detectable effect
  (`plan.py`, α 5 %, power 80 %) is ≤ 30 %; `plan.py` is extended to compute MDE for any N.
- The chooser shows what each window can detect ("7 ngày: chỉ thấy thay đổi ≥ 45 %"); a window below the
  recommendation is allowed with a "khó kết luận" note. The preliminary reading at 7 days stays for windows > 7.
- Stored on the change set; `measure.py` uses it instead of `measurement_plan.planned_days` when set.

## D-10 Design-pass answers (owner 2026-11-04)
- **Window default (D-8)**: auto per product — the shortest preset (7 / 14 / 28) whose MDE ≤ 30 % for that product's
  volume is pre-selected; the user can change it (min 3 days).
- **Approving on a product still being measured (D-7)**: allowed for every family; the confirm dialog warns that the
  running measurement is cut (≥ 3 days kept as "đo được N ngày"). Never blocked.
- **Excel export button**: hidden until the export is built (codes are visible meanwhile).
- **Mobile**: add a mobile artboard for Tự tạo / So sánh (KeHoach and SanPhamDeXuat already have one); card versions
  and Quyết định stay desktop-only in this pass.
- **Plan codes**: every confirmed plan gets `KH-<yymm>-<seq3>` (per shop, never reused); every card in it carries the
  plan code; the "card by code" read and the later export include it.

## D-9 KOL: who sells what, at what profit, and which product to send as a sample
- **Data**: keep the KOL on each affiliate order line (`SellerConversionReport` → `affiliate_order_lines` marks the
  order export's lines): hashed affiliate key + public handle (as `affiliate_partner_period` does; the raw id is never
  stored) and the channel (`Kênh`: Shopee Video / Facebook / TikTok …). New column(s) on `shopee_order_lines` in
  migration 116 or 117.
- **KOL × sản phẩm × kênh table** (Phân tích › KOL, and each product's Tiếp thị liên kết tab lists its KOLs): orders,
  units, GMV, clicks, conversion (orders ÷ clicks), commission, **net profit** (after platform fees, giá vốn, đóng gói
  and commission), sample cost, profit after samples, ROI incl. samples, payback orders.
- **Commission per product sold** (owner): commission is computed per order line from the rate that applied to that
  product (targeted-campaign rate from `affiliate_campaign_terms`, else the open-campaign rate, else the line's actual
  commission from the conversion report, which wins when present). Forecasts use the product's current rate.
- **"Mẫu KOL" sheet** in the Cài đặt `.xlsx` template (file upload, versioned like the SKU sheet): KOL handle, product
  (item id / SKU), số lượng mẫu, ngày gửi, phí ship gửi mẫu. Sample cost = số lượng × (giá vốn + đóng gói) + phí ship.
  No KOL booking fee (owner: not part of sample cost).
- **ROI incl. samples** = (net profit of the KOL's orders − sample cost) ÷ (commission + sample cost). Shopee's own ROI
  (commission only) is shown beside it, labelled.
- **Card `affiliate_sample` "Gửi mẫu cho KOL"** (family affiliate): for one KOL, the product with the best expected
  profit per sample. Expected orders for a KOL × product pair from the KOL's clicks and conversion, the product's
  affiliate conversion and the channel fit, **shrunk toward the shop average** while the KOL has few orders (labelled
  "ít dữ liệu", wide range). Versions (D-2) = different products or sample counts; what-if knobs: product, số lượng mẫu,
  hoa hồng %. Shows sample cost, expected orders (range), expected net profit, ROI, payback orders. Plus an
  "Mời KOL" card (no sample cost) for KOLs not yet sent samples. Both join plans (D-6); measured per KOL × product
  pair before vs after the send date (D-7).

## D-11 KOL details (owner 2026-11-04)
- "ROI Shopee" is the `ROI` value from Shopee's KOL export as-is (labelled "ROI Shopee (chỉ hoa hồng)"), never
  recomputed; our "ROI (gồm mẫu)" sits beside it.
- "Ít dữ liệu" = fewer than **10** orders for the KOL × product pair (the same threshold drives the shrinkage label
  and the wide range on the card).
- "Mời KOL" versions vary the **product** pitched (like "Gửi mẫu"); hoa hồng % is a what-if knob.

## D-12 Doanh thu (income) export and the seller's cost file (owner 2026-11-04)
Real files arrived (header names only recorded here; files stay outside the repo).
- **Income export** `Income.T<m>.<yyyymmdd>_<yyyymmdd>.xlsx` (Tài chính › Doanh thu): sheets `Summary`, `Service Fee
  Details` (`Mã giao dịch`, `Mã đơn hàng`, `Phí Hạ Tầng`, `Voucher Xtra`), sometimes `Shipping Fee Discrepancy`
  (`Mã đơn hàng`, `Phí vận chuyển ước tính:`, `Phí vận chuyển thực tế:`, `Lý do chênh lệch`), and `Doanh thu` (3 header
  rows; one `Order` row per order + `Sku` rows per product). Columns used: Mã đơn hàng (→ keyed order_ref, raw id
  never stored), Mã sản phẩm, Phân Loại, Ngày đặt hàng, Ngày hoàn thành thanh toán, Tổng tiền đã thanh toán, Giá sản
  phẩm, Số tiền hoàn lại, Phí vận chuyển Người mua trả / thực tế / được trợ giá từ Shopee / trả hàng (2 kinds) / được
  hoàn bởi PiShip / Người bán hỗ trợ, Mã ưu đãi (Đồng Tài Trợ) do Người Bán chịu, Mã hoàn xu (Đồng Tài Trợ) do Người
  Bán chịu, Phí cố định, Phí Dịch Vụ, Phí xử lý giao dịch, Phí hoa hồng Tiếp thị liên kết, Phí dịch vụ PiShip, Phí dịch
  vụ hiển thị NTTD, Thuế GTGT, Thuế TNCN, Trade-in Bonus by Seller, Đền bù đơn mất hàng, Shopee xu/voucher (not seller
  costs), Transaction Fee Rate (%). **Dropped unread in the sender**: Người Mua, Amount Paid By Buyer, Phương thức thanh
  toán của Người mua, Buyer Payment Method Details_1, Mã Số Thuế (an invoice tax code), Tên sản phẩm, Mã voucher text.
- It becomes the **actual** per order (wins over the order export's fee columns and over the formula): every
  platform fee incl. Phí hạ tầng and the Voucher Xtra service fee, net shipping cost to the seller (thực tế − trợ giá
  Shopee − người mua trả − PiShip hoàn), return-shipping and failed-delivery shipping, refunds, lost-parcel
  compensation, affiliate commission per order, withheld VAT/PIT, payout. Loaded for Aug–Oct 2026 (3 files).
- Findings on ORY (Aug–Oct 2026): **Thuế GTGT = Thuế TNCN = 0 in every order** → Shopee withholds nothing (consistent
  with a company that invoices VAT itself — titles say "Có VAT"); **Phí Dịch Vụ = Voucher Xtra fee ≈ 5,5 % of product
  value** every month; Phí hạ tầng 3.000đ/order confirmed; fixed fee ≈ 13,7 %, transaction fee 6 % as in §10.
- **VAT for a company seller** (new): profit after the seller's own VAT = buyer-paid revenue ÷ (1 + VAT rate) when the
  price includes VAT, and giá vốn ex-VAT when input VAT is credited. Per SKU `vat_rate` (0 / 5 / 8 / 10 %) and a shop
  flag `prices_include_vat` + `cost_includes_vat`; until set, profit is shown before VAT and labelled.
- **Cost file** `Tồn kho và giá.xlsx` (Mã nội bộ, Tên, Đơn vị tính, Giá bán, Giá vốn, Số lượng dự báo, Số lượng hiện
  có, Kích thước đóng gói): Mã nội bộ = Shopee variation SKU for single items. Imported through the Cài đặt seller
  import (versioned) via a converter, never by hand.
- **Pack multiplier / bill of materials** (new, required): combo variations reuse the base SKU (e.g. G500001 for
  "Combo 3/5/10 hộp"), so cost per order line = Σ component cost × quantity per variation. Template gets a
  `số món / phân loại` column per variation (parsed default from the variation name "Combo N …", editable) and a BOM
  sheet for listings with no SKU (multi-product combos). Without it combo costs are understated N-fold.

## D-13 Listing changes as cards, imported from a file, with Connector fill-in (owner 2026-11-04)
- **New change kinds** (family listing): `description_first_line`, `variation_restructure` (gom phân loại: target
  variations with names/prices/SKUs, listings to hide after it runs), `listing_hide` (ẩn, never delete), `listing_relist`
  (nhập hàng / đưa trở lại). Existing: `title` (100-char rule, D-4), `cover_image`. Each has an execution sheet (page,
  fields, before → after, dependencies such as "chỉ sau khi CB3/CB4 chạy") and a read-back check (title / description
  / variations / status / stock from the product snapshot).
- **Import from a file** (Cài đặt › Đề xuất, `.xlsx`, preview → apply with reason, versioned like the seller import):
  columns ref (e.g. TD1, XM3), item id, change kind, before, after (title / description / variation table / image ref),
  reason, chi phí, ngày thực hiện, cửa sổ đo (days), depends_on (refs), ORY decision (đồng ý / không / chỉnh sửa),
  status (chưa / đang / hoàn thành). Each row → a manual card (`origin = "import"`, JC code, `external_ref` kept for the
  export). Rows already executed carry their real execution date; measurement baseline comes from history. Validation:
  title > 100 chars, unknown item, two changes of one product on different days within 3 days (D-7 warning).
- **Connector fill-in** (flag `fill_listing`, ORY pilot shop only): on the product edit page the Connector fills the title
  and the first line of the description with the card's approved value and highlights them; it never clicks Save /
  Cập nhật / Xác nhận / Ẩn. Cover image: offered as a download to drop in by hand. Variation restructure: a step checklist
  beside the page (no fill). Hide / relist: page opened only. Field location by visible label text, verified once by a
  read-only recon of the edit page with a logged-in Seller Centre; unknown layout → no fill, copy buttons only.

## D-14 Operations decisions (owner 2026-11-04)
- Connector fixes 0.3.2/0.3.3 go to fasttrack/optimize-product as their own PR (connector-only); D-13's connector
  becomes 0.3.4.
- Learning / calibration runs **daily, right after the daily Shopee KPI beat**, for the pilot shop(s) only (DB only,
  idempotent); Ops can still trigger it by hand.
- P91 ships as **one deploy** after D-12 + D-13 are merged and the full deploy gate passes.
- Update-permission test: register the P90/P91 tables that need UPDATE (with their call sites) inside P91; the 23
  older tables go to a separate ticket after P91.
- Income "Phí vận chuyển – Người bán hỗ trợ": stored as reference, not subtracted; Ops warning the first time a
  non-zero value arrives.
- VAT flags apply to card what-ifs too (versions, compare, plan totals) so card Δ profit matches shop profit.
- Connector fill-in: read-only recon of ORY's product edit page now (field labels, the page's own detail call); fill-in
  for ORY ships in P91 if the recon confirms the labels.

## Waves
1. Backend core (D-1, D-2, D-4, D-5) ‖ Backend manual + compare + combo (D-3) ‖ Design artboards (all of D-1..D-10).
   Parallel; file ownership below.
1b. After core + manual merge: Backend plan + aggregation + measurement + plan codes (D-6, D-7, D-8, D-10) ‖ Backend KOL (D-9) ‖ Backend income + cost import (D-12) ‖ Listing changes + import + Connector fill-in (D-13).
2. Owner approves the artboards. **Done 2026-11-04** (19 artboards in `docs/product/design/shopee-shop/`, branch merged).
3. Frontend Demo + Ops ‖ integration tests on ORY data. Then one deploy.

File ownership in wave 1 (no agent edits another's files; the orchestrator integrates):
- Core: `ranking.py`, `service.py`, `store.py`, `config.py`, `generators.py`, `listing.py`, `cards.py`,
  `models/shop_proposals.py`, migration 116, existing reco routes, their tests.
- Manual: new `manual.py`, `combo.py` (calculator), `evaluate.py` additions only as new functions, new route files
  `ops_shopee_reco_manual.py`, `demo_shopee_reco_manual.py` (+ router registration lines), their tests.
- Design: `docs/product/design/shopee-shop/` only.
- Bookkeeping (`DECISIONS.md`, `PROGRESS.md`, `LOG.md`, this file): orchestrator only.

## Integration notes (P91 integration branch, 2026-11-04)
- Merge order: p91-plan, p91-kol, p91-web. Migration chain: 116_shopee_reco_codes -> 117_shopee_reco_plans -> 118_shopee_kol_lines (KOL renumbered from 117);
  the deferred write-mode tail (`deferred/101_*`) and its test pins sit on 118. D-12 income and D-13 listing become 119 / 120.
- Plan and KOL screens are ON by default; `NEXT_PUBLIC_P91_PLAN=0` / `NEXT_PUBLIC_P91_KOL=0` switch them off. Types mirror the backend answers.
- Backend: `versions.OPTIONAL_EVAL_FIELDS = ("kol",)` so every version of a KOL card carries its own `kol` block.
- Not available from the backend, so not shown: MDE for a custom window length (no route), per-pair clicks, ROI/payback ranges for KOL, margin/AOV in "bỏ thẻ này thì".
