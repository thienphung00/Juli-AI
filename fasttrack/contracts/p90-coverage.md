# Coverage: contract input -> source field -> status -> gap (as built)

Companion of `field-spec.md` (section codes A1..A19, B1..B11, C1..C2, D refer to it). Contract = `fasttrack/contracts/p90-metrics.md`. Branch state `fasttrack/ops-reco-pipeline` @ `302999f7`. Status words: **OK** (source field loaded, usable now), **PARTIAL** (loaded but not at the grain/basis the contract wants), **GAP** (no source field feeds it). Real-data checks come from `scripts/load_shopee_exports.py --dry-run` on the four ORY folders (see top of `field-spec.md`).

Owner/action tags used in the gap register: `Thiên download` (a file we have not downloaded), `Hạnh grant finance` (Tài chính › Doanh thu access), `ORY import sheet` (ORY fills SKU / Mục tiêu), `connector live check` (run the reader against the live Seller Centre and confirm shape / unit), `migration 113` (new column / table), `parser to write` (loader or mapper code; "(fix)" = existing parser is wrong), `decision` (owner/contract choice needed before code).

## 0. Gap register (all gaps, referenced below as G-nn)

| ID | Gap | Impact on the contract | Owner / action |
|---|---|---|---|
| G-01 | Real file `oryvietnam.shopee-shop-stats.20261027-20261102.xlsx`, sheet `Đơn Đã Thanh Toán`, day 29-10-2026: `Tỷ lệ chuyển đổi đơn hàng` above 100 %. `ShopeeShopOverviewRow.conversion_rate` is capped at 1, so the gateway refuses the WHOLE `shop_overview` post (the loader exits 1: "1 post(s) the gateway would refuse"). Same hazard for any rate column on any daily row. | the loader aborts the entire run with exit 1 BEFORE sending anything (and over HTTP the paid post would answer 422 and stop the load): no daily shop GMV after 2026-10-28 until fixed | `parser to write (fix)`: drop `Tỷ lệ chuyển đổi đơn hàng` like `CTR` (it is derivable) or widen the model to `Ratio`; add a parser test |
| G-02 | Real file `oryvietnam.shopee-shop-stats.20260101-20260930.xlsx` is a MONTHLY roll-up (rows dated 01-01 .. 01-09-2026, each = a whole month). `parse_shop_stats` reads them as nine daily rows (27 posts). Same key as the daily files, equal rank: the later post wins. In sorted file order only 01-01-2026 stays corrupted (later monthly files re-write the other months); in any other order any 1st-of-month is wrong. Ops `_SHOP_MONTHLY` (`sum(gmv)` per month) would then double-count a month. | §1 shop GMV / §5 ④⑤ per month | `parser to write (fix)`: detect row spacing (rows exactly one month apart, or a period > 31 days with ≤ 12 rows) and skip or post as a period dataset; `Thiên download`: never export shop-stats with the monthly granularity picker |
| G-03 | NO order export (Đơn hàng › Xuất) is held or parsed; only affiliate order lines (A16, RESERVED). Browser-side PII strip ("path D") not built. | §1 line GMV + 2 % reconciliation, §3 all levers, §4 buyer_paid / seller promo / shop voucher share / combo / buyer shipping / bank promo / order status, §5 ① ② ③, §6 breach check, §7 Q, organic vs ad margins | `Thiên download` (Order export, headers first), then `parser to write` (strip + hash + `shopee_order_lines` mapper + gateway dataset), `migration 113` for G-04 columns |
| G-04 | `shopee_order_lines` has no column for buyer-paid shipping or bank promotion (`OrderLine.buyer_shipping_fee`, `bank_promo` feed the phí xử lý giao dịch base, §10). `traffic_source` exists but no export fills it; `ad_attributed` has no column or source. | §4 fees (formula path), §7 per-order organic vs ad-attributed margin | `migration 113` (+ `decision` on ad attribution) |
| G-05 | NO income / fee export (Tài chính › Doanh thu): the ORY sub-account has no such sidebar section. `shopee_order_lines.fee_*` / `payout` exist and stay NULL. | §4 "fees: actual from the income export" (wins over the formula), payout / release date, service fee (Voucher / Freeship Xtra enrolment) | `Hạnh grant finance`, then `Thiên download`, then `parser to write` |
| G-06 | Per-PRODUCT flow split cannot be built as written: the product sheet (A3) has only the four L1 blocks, NO L2 children, so no per-product `Cửa hàng` (Trang shop) and no per-product Thẻ sản phẩm children (Tìm kiếm / Đề xuất / Khuyến mãi). Also Live / Video / liên kết per-product "views" are `Lượt hiển thị sản phẩm` (product impressions), not session / video / content views as at shop level (A2). The connector's per-item reader (B3 `item_by_source`) is inactive and unverified for L2. | §2 "Trang shop" child per product, "Live / Video view definitions" per product | `connector live check` (item-list endpoint with `l1_source`) and `decision` (is per-product Trang shop required, or shop-level only?) |
| G-07 | Ads: the connector's daily feed has no per-product split and only runs forward (yesterday + 3 catch-up days, no 30-day backfill for ads). History = CSV windows of ~3 months that OVERLAP between exports (`ads_general_20260401-20260629` / `20260601-20260829` / `20260829-20261031`), stored as separate period rows (the key contains the window), so summing windows double-counts. | §4 product ad spend, total ad spend, "Σ product + QC không gắn sản phẩm = total" check | `Thiên download` non-overlapping ad CSVs (one per calendar month or one non-overlapping series) and `decision` (reader rule: daily where present, else period) |
| G-08 | Ad reports count PLACED orders only (`ads_campaign_period` hard-coded `placed`; `ads_campaign_daily` `placed` or `paid`, never `confirmed`). Contract default is confirmed. `Doanh số` / `Doanh số trực tiếp` / ROAS therefore cannot be restated on the confirmed basis. | §1 "every view states it", §4 ROAS vs break-even | `decision`: label ad GMV/ROAS "đơn đã đặt" in every view |
| G-09 | `item_snapshot` is RESERVED (connector holds; backend 404) and the destination `platform_item_snapshots` has different columns from `ShopeeItemSnapshotRow` (`title`, `image_urls`, `image_hashes`, `list_price`, `current_price`, `promo_label/start/end`, `stock`, `sold_total`, `rating`, `rating_count`, `likes`, `category_path`, `status`, `created_on` vs `price_min/max`, `selling_price_*`, `origin_price`, `promotion_price`, `*_stock`, `view_count`, `liked_count`, `sold_count`, `promo_has_*`, `campaign_count`, `tier_index`, `is_default`). No mapper, no image downloader (`product_image_assets`). | Product header (image, price, stock, sold, likes, created), §6 list price, §3 active promotion price | `parser to write` (gateway dataset + mapper row → snapshot, insert-on-change) and `connector live check` |
| G-10 | Product category path and rating are not in `get_product_list` (recon). Ratings export (`Quản lý đánh giá`) is a buyer-bearing file the parser never opens. | Product header (rating, category); §10a fixed-fee rate by category; §6 absolute floor fee % | `connector live check` (product detail / category-tree endpoint), `parser to write`, `decision` on the reviews export |
| G-11 | Fee-rate table: the 47-page PDF (non-Mall fixed fee by category) is not loaded; `platform_fee_formulas` has no seed; `shopee_vn_non_mall(rate, date)` takes the rate as an argument; item → category join does not exist (A16 drops `L1/L2/L3 Ngành hàng toàn cầu`; `sales_composition` unparsed). | §4 fees (formula path), §6 `platform_fee_rate`, §10a | `parser to write` (seed + category join); `parser to write` (keep L1-L3 in A16) |
| G-12 | Seller import sheets `SKU` and `Mục tiêu` have no importer, template generator or tests. Existing storage: rules `sku_cost`, `max_discount_pct`, `min_margin_pct`, `gmv_max_daily_budget`. Missing keys: packaging per SKU, tồn kho, ngày nhập lại, nhóm, trạng thái, monthly GMV / đơn / AOV / biên mục tiêu / trần ngân sách QC/ngày. SKU scope format undecided (`item_id:variation_id` or SKU text). | §4 giá vốn, đóng gói, §6 all, §5 trần chi/ngày, §8 Biên < target | `ORY import sheet` + `parser to write` (importer, new rule keys: no migration, `rule_key` is free text) + `decision` (SKU scope; per-campaign or total daily cap) |
| G-13 | `Shop_Prize_Key_Metrics_*.xlsx` (game prize cost) has no parser; real files cover only 2026-03..06. | §4 shop profit "other shop marketing costs", §9 `other costs × covered share` | `parser to write`; `Thiên download` later months |
| G-14 | Voucher export <-> connector settings cannot be joined by id: the export has no voucher id; the code (`Mã giảm giá`) is deliberately unread; the export's `starts_at` is date 00:00 while the settings' is the real clock time, so the promotions key `(promo_type, program_name, starts_at, ordinal, period)` never equal. Daily voucher cost (`Xu hướng số liệu` sheet) is not loaded. | §7 u from "the shop's comparable past vouchers", §7 spend/day, §5 ② chi | `parser to write` (join by normalised name + date, or hash the code into `extra`) and `decision` |
| G-15 | Affiliate commission per line: A16 has no base-commission column; which of `Chi phí(₫)` / `Hoa hồng Xtra …` is the seller's commission is undecided; `ProductPerformance`'s `Hoa hồng ước tính` (no ₫) is assumed to be clicks. Report status vocabulary not mapped to `OrderStatus`. | §4 commission, §5 chi, §6 hoa hồng % | `decision` + `parser to write` (mapper A16 → `shopee_order_lines`); verify the click assumption against the dashboard |
| G-16 | Connector never run live: `MONEY_DIVISOR = 1` (money may be × 100 000), response wrappers pinned by recon shapes only, `PILOT_SHOP_IDS = ["*"]` must become ORY's shop id before 0.3.0 (PROGRESS: release blocker), ads page upsell modal must never be clicked, no ORY shop in Ops yet. | B1-B10 all `LOADED*` | `connector live check` |
| G-17 | `shop_health_daily`, `ads_change_log` have no table (RESERVED). | not in P90 §; shop performance form, ads history | `migration 113` (when wanted) + `parser to write` |
| G-18 | Per-flow ads overlay ("trong đó", `FlowAdsRow(product_id, flow, spend, gmv, orders)`): no export says which flow an ad order lands in. Shop-stats ads L2 rows are ad TYPES (`Quảng cáo cửa hàng`, `Quảng cáo GMV tối đa …`), not landing flows; campaign rows carry no landing flow. | §2 ads overlay per flow | `decision` (landing-flow rule, or show the overlay at shop level only) |
| G-19 | `promo_kind` (programme vs Flash Sale vs none) cannot be read from an order line; needs the Flash Sale slots (A10 / A11) and the active programmes (discount list endpoint not read, B11). Bundle breakdown columns in the discount export are dropped (`-` at ORY today). | §3 `khuyen_mai` vs `khong_uu_dai`, `combo` split | `parser to write` (rule) + `connector live check` (discount list shape) |
| G-20 | Naming collision: `services/shopee_kpi/job.py FLOW_SOURCES["the_san_pham"]` = `traffic_overview / product_card / all` (Thẻ sản phẩm INCLUDING Trang shop) and `trang_shop` = `shop_page` (its child), whereas P90 §2 `the_san_pham` = total − Trang shop. | §2 | `decision` (rename one of them; both coexist today) |
| G-21 | §1 says GMV = "Shopee's Doanh số" but the shop export has two columns: `Tổng doanh số (VND)` (stored as `gmv`) and `Doanh số không bao gồm trợ giá bởi Shopee` (stored as `extra.sales_excl_shopee_subsidy`). The reconciliation target (Σ deal × qty) matches only one of them once Shopee subsidises price. | §1 reconciliation, §10 fee base | `decision` (state which column is the contract GMV) |
| G-22 | Equal source rank between file and connector: `traffic_overview` day rows can come from the xlsx (with L2) or the connector (L1 only, confirmed only, yesterday only); same key, later post wins, no precedence; values for a just-ended day can differ. | §2 flows (consistency) | `decision` (rank connector above file, or separate dataset name) |
| G-23 | Flash Sale rows may collide: `discount_*` `Biểu đồ` can carry `Loại khuyến mãi = Flash Sale` (→ `promotion_daily`, segment `flash_sale`) and `In_Shop_Flash_Sale_Metrics` writes `promotion_daily` for `Flash Sale` too: same key, last wins. Not verified on ORY data. | §3 `khuyen_mai` aggregate | `parser to write (fix)` after a check of the real `Biểu đồ` types |
| G-24 | Per-product ad keyword reports (`Dữ+liệu+Dịch+vụ+Hiển+thị+Sản+Phẩm-*.csv`) are not loaded and have 2 columns outside `ADS_COLUMNS`. `sales_composition_*`, `sales_overview_*` not loaded. | §8 keyword; §10a category split | `parser to write` |

## 1. §1 Order basis and GMV

| Contract item | Source field(s) (verbatim) | Status | Gap / action |
|---|---|---|---|
| Default order type = confirmed; every view states it | file sheets named `Đơn đã xác nhận` / `(đơn đã xác nhận)Theo nguồn...` / `Theo sản phẩm (đơn đã xác n...` / columns `… (Đơn đã xác nhận)`; connector B1 asks `order_type=confirmed` only | OK for traffic, shop, product, promotions, vouchers | Ads reports are PLACED only (G-08) |
| Shop GMV (Doanh số), confirmed | `Tổng doanh số (VND)` on sheet `Đơn đã xác nhận` → `shop_overview.gmv` (A1) | OK, with hazards | G-01, G-02, G-21 |
| Product GMV | `Doanh số (Đơn đã xác nhận) (VND)` → `product_period.gmv` (A4) | OK | none |
| Flow GMV | `Doanh số (VND)` per L1 / L2 (A2) | OK shop level; PARTIAL per product (L1 only, G-06) | G-06 |
| Order-line GMV = deal price × qty (before shop voucher) | order export deal price × qty (D) | **GAP** | G-03 `Thiên download` order export |
| Reconciliation Σ order-line GMV vs export, warn > 2 % (`shop_profit.GMV_WARN_RATE`) | needs both sides | **GAP** (code exists, `P90::test_end_to_end_shop_consistency`; cannot run on real data) | G-03 |
| Orders (confirmed) | `Tổng số đơn hàng` (A1) | OK | none |
| Cancelled / returned totals (aggregate) | `Đơn đã hủy`, `Doanh số đơn hủy`, `Đơn đã hoàn trả / hoàn tiền`, `Doanh số các đơn Trả hàng/Hoàn tiền` (A1) | OK (aggregate only) | per-order status: G-03 / G-05 |

## 2. §2 Traffic flows (five flows + residual + ads overlay)

Source for the flows is `traffic_overview` (day rows) / `traffic_overview_period` (file) and, for L1 only, the connector B1. Per product it is `item_by_source_period` (A3). `Flow` ↔ rows: `the_san_pham` = `product_card/all` − `product_card/shop_page`; `trang_shop` = `product_card/shop_page`; `live` = `seller_live/all`; `video` = `seller_video/all`; `lien_ket` = `affiliate/all`.

| Flow | Metric | Shop level: source field(s) | Status | Per product: source field(s) | Status |
|---|---|---|---|---|---|
| `the_san_pham` (total incl. Trang shop − Trang shop) | views | `Lượt hiển thị sản phẩm` on `Thẻ sản phẩm` minus the same on child `Cửa hàng` | OK (file) | `Lượt hiển thị sản phẩm` under `Thẻ sản phẩm` (child not available) | PARTIAL, G-06 |
| | clicks | `Lượt nhấp vào sản phẩm` (same subtraction) | OK (file) | same | PARTIAL, G-06 |
| | orders | `Tổng số đơn hàng` | OK (file) | same | PARTIAL, G-06 |
| | GMV | `Doanh số (VND)` | OK (file) | same | PARTIAL, G-06 |
| `trang_shop` (child `Cửa hàng` of Thẻ sản phẩm) | views / clicks / orders / GMV | the four columns of the `Cửa hàng` row (segment `shop_page`) | OK (file); NOT from the connector (B1 drops breakdown) | **no per-product child in the product sheet** | **GAP**, G-06 |
| `live` | views = **Lượt xem Livestream** (sessions) | `Lượt xem Livestream` on `Live` | OK | `Lượt hiển thị sản phẩm` under `Live` (product impressions, different definition) | PARTIAL, G-06 |
| | clicks / orders / GMV | `Lượt nhấp vào sản phẩm`, `Tổng số đơn hàng`, `Doanh số (VND)` | OK | same names | OK |
| `video` | views = **Lượt xem Video** (videos) | `Lượt xem Video` on `Video` | OK | `Lượt hiển thị sản phẩm` under `Video` | PARTIAL, G-06 |
| | clicks / orders / GMV | as live | OK | as live | OK |
| `lien_ket` (incl. Affiliate Live / Video) | views | `Lượt xem nội dung` on `Tiếp thị liên kết` (children `Affiliate Live`, `Affiliate Video`) | OK | `Lượt hiển thị sản phẩm` under `Tiếp thị liên kết` | PARTIAL, G-06 |
| | clicks / orders / GMV | as live | OK | as live | OK |
| Residual `chenh_lech_nguon` | GMV, orders | computed: `shop_gmv`/`shop_orders` minus Σ five flows (`shop_overview` `Tổng doanh số (VND)`, `Tổng số đơn hàng`) | OK | `product_totals` from `product_period` | OK |
| Thẻ sản phẩm children drill-down (Tìm kiếm, Đề xuất, Giỏ hàng, Đơn mua của tôi, Khác) | all four | L2 rows of `Thẻ sản phẩm` (segments search / recommend / cart / my_orders / other) | OK (file, shop level) | not in product sheet | **GAP**, G-06 |
| Flash Sale page traffic = child `Khuyến mãi` of `Thẻ sản phẩm` | all four | L2 `Khuyến mãi` (segment promo) | OK (file, shop level) | not in product sheet | **GAP**, G-06 |
| CTR = clicks ÷ views, CTOR = orders ÷ clicks, AOV = GMV ÷ orders | derived | Shopee's `CTR`, `Tỷ lệ chuyển đổi đơn hàng`, `Doanh số trên mỗi đơn hàng` are NOT used (dropped / extra) | OK (derived, `flows.py`; `P90::test_flow_ratios_and_exact_identity`) | | |
| Quảng cáo overlay ("trong đó"), per flow | spend, GMV, orders landing in a flow | none | **GAP**, G-18; the shop-level ads totals exist: `Chi phí quảng cáo`, `ROAS quảng cáo`, `Doanh số (VND)`, `Ads Impression`, `Tổng số đơn hàng` on `Dịch vụ Hiển thị Shopee` | |
| Flows ADD UP to shop GMV | | needs `shop_overview` + all flows on the same order type | OK (residual row guarantees it) | |

## 3. §3 Price levers per order line (each line exactly one; they add up)

| Contract item | Needed input | Source field(s) | Status | Gap / action |
|---|---|---|---|---|
| `combo` (Combo khuyến mãi, Mua kèm deal sốc) | `bundle_discount` > 0 | order export combo discount (D) | **GAP** | G-03; aggregate GMV only: `discount_*` `Loại khuyến mãi` = `Combo Khuyến Mãi` / `Mua Kèm Deal Sốc` rows (A6), bundle columns dropped (G-19) |
| `khuyen_mai` (discount programme incl. Flash Sale price) | `promo_kind` ≠ none (original_price > deal_price) | order export original / deal price; programme and slot lists for the Flash vs programme split | **GAP** | G-03, G-19; aggregates: `discount_*` `Khuyến Mãi` / `Flash Sale`, `flash_sale_performance_list_*`, `In_Shop_Flash_Sale_Metrics_*` (A6, A10, A11) |
| `voucher` (shop voucher) | `shop_voucher_share` > 0 | order export shop voucher amount | **GAP** | G-03; aggregates: `voucher_*` `Bán hàng …`, `Đơn đặt hàng …`, `Chi phí …` (A9) |
| `khong_uu_dai` | none of the above | derived | **GAP** | G-03 |
| Shopee-funded vouchers are not a seller cost | `platform_voucher_share`; voucher export `Người tạo` (→ `extra.created_by_shopee`); connector `rule.is_seller_absorbed` | OK for the voucher export and connector; GAP for order lines | G-03 |
| Precedence combo > khuyen_mai > voucher > none | code `sources.price_lever` | OK (`PRF::test_sources_lever_sums_to_totals`, `PRF::test_additivity_property_over_generated_lines`) | none |

## 4. §4 Profit inputs

| Input | Source field(s) | Status | Gap / action |
|---|---|---|---|
| buyer_paid = deal × qty − shop voucher share − combo discount | order export deal price, qty, shop voucher, combo (D) | **GAP** | G-03 `Thiên download` |
| Seller promotion (khuyến mãi người bán) | original − deal price (order export); programme VND discount is NOT in `discount_*` | **GAP** | G-03 |
| Shop voucher share (per line) | order export; aggregate cost `Chi phí (Đơn đặt hàng được xác nhận) (VND)` (A9, `extra.voucher_cost`) and connector `value`/`discount` × `current_usage` | PARTIAL (aggregate only) | G-03, G-14 |
| Combo discount (per line) | order export | **GAP** | G-03 |
| Buyer-paid shipping | order export; no column in `shopee_order_lines` | **GAP** | G-03 + G-04 `migration 113` |
| Bank promotion | order export; no column in `shopee_order_lines` | **GAP** | G-03 + G-04 `migration 113` |
| Platform fees, actual | income export (`fee_fixed`, `fee_service`, `fee_payment`, `fee_other`, `payout`) | **GAP** | G-05 `Hạnh grant finance` → `Thiên download` → `parser to write` |
| Platform fees, formula fallback (6 % per order + 3.000đ per order + fixed % per item by category) | rate by category (PDF), item category | **GAP** (code exists: `fees.shopee_vn_non_mall`, `PRF::test_fee_components_bases_and_caps`, `P90::test_non_mall_formula_bases_once_per_order`) | G-11 |
| Order status / delivered date | order export + returns list | **GAP** | G-03, G-05 |
| giá vốn per SKU | SKU sheet `giá vốn` → rule `sku_cost` | **GAP** (storage OK, importer missing) | G-12 `ORY import sheet` |
| đóng gói per order line | SKU sheet `đóng gói` | **GAP** (no rule key) | G-12 |
| Affiliate commission | per line: A16 (RESERVED; amount column undecided); rate: `Tỉ lệ hoa hồng` (A15 `target_campaign`); estimate: `Hoa hồng ước tính(₫)` (A15 `affiliate_product`); actual: `Hoa hồng hằng tháng(₫)` (`ValidationBill`) | PARTIAL (aggregates OK, per line GAP) | G-15 |
| Ad spend per product | ads CSV `Chi phí` + `Mã sản phẩm` on product rows (A13 → `extra.ads_expense`, `item_id`) | PARTIAL (period windows, placed, overlapping) | G-07, G-08 |
| Ad spend total (all campaigns, incl. no-revenue campaigns) | A13 Σ of all rows (a campaign without product rows is posted as its own row, `item_id ''`); or `Chi phí quảng cáo` (A2 ads block); or connector `report.cost` (B7) | PARTIAL: three sources, none primary (section 10) | G-07, G-22 |
| "QC không gắn sản phẩm / không ra đơn" = total − Σ product | rows with `item_id ''` in A13 | PARTIAL | G-07 |
| Direct ad GMV | `Doanh số trực tiếp` (A13), `report.direct_gmv` (B7) | PARTIAL (placed basis) | G-08 |
| Broad ad GMV | `Doanh số` (A13), `report.broad_gmv` (B7), `Doanh số (VND)` on `Dịch vụ Hiển thị Shopee` (A2) | PARTIAL (placed basis) | G-08 |
| Other shop marketing costs not on orders | `Chi phí giải thưởng (Đơn đặt hàng được xác nhận)(₫)` (A12) | **GAP** (file held, no parser) | G-13 |
| Cost coverage (share of buyer_paid whose SKU has giá vốn) | needs order lines + `sku_cost` | **GAP** | G-03, G-12 |
| Margin = profit ÷ buyer_paid; break-even ROAS = buyer_paid ÷ contribution | derived | OK in code (`P90::test_end_to_end_shop_consistency`, `P90::test_roas_broad_and_direct_per_product_and_campaign`) | none |

## 5. §5 The five numbers

| Number | Inputs | Source status | Gap |
|---|---|---|---|
| ① % giảm giá = (khuyến mãi + voucher + combo) ÷ GMV at list price | the three discounts and list value per line | **GAP** (order export) | G-03 |
| ② Doanh thu thêm / chi thêm = ΔGMV ÷ Δchi; chi = QC + voucher + khuyến mãi + combo + hoa hồng | ΔGMV `Tổng doanh số (VND)` OK; QC `Chi phí` / `Chi phí quảng cáo` OK-ish; voucher `Chi phí (…) (VND)` OK (aggregate); khuyến mãi VND and combo VND GAP; hoa hồng PARTIAL | PARTIAL | G-03, G-15 |
| ③ Biên cuối | all of §4 | **GAP** | G-03, G-05, G-12 |
| ④ Số đơn (confirmed) | `Tổng số đơn hàng` | OK | none |
| ⑤ AOV = GMV ÷ orders | `Tổng doanh số (VND)`, `Tổng số đơn hàng` | OK | none |
| Chi marketing / ngày vs trần | chi (see ②) and `Trần ngân sách QC/ngày` (C2) | **GAP** for the cap | G-12 `ORY import sheet` |
| Card before → after snapshots | `snapshot_from_orders` over order groups | **GAP** (order lines) | G-03 |

## 6. §6 Floor price and max discount

| Input (`FloorInputs`) | Source | Status | Gap |
|---|---|---|---|
| `list_price` (giá niêm yết) | connector `price_detail.price_min/max` or `model_list[].price_detail.origin_price` (B6, RESERVED); order export `original_price` | **GAP** (neither stored) | G-09 `parser to write`, G-03 |
| `cogs` | `giá vốn` (C1) | **GAP** | G-12 |
| `packaging` | `đóng gói` (C1) | **GAP** | G-12 |
| `fixed_fee_per_order` | `phi_ha_tang` 3.000đ in `shopee_vn_non_mall` (code constant); phí cố định is a % per item, not fixed | OK as constant | G-11 |
| `platform_fee_rate` (phí sàn %) | fixed-fee % by category + 6 % transaction (`FeeFormula.pct_rate_on_buyer_paid`) | **GAP** (category rate) | G-11 |
| `ads_rate` (QC %) | not defined in the contract beyond "QC %"; candidates: ad spend ÷ ad-attributed buyer_paid from A13 / B7 | **GAP** (definition) | `decision` |
| `affiliate_rate` (hoa hồng %) | `Tỉ lệ hoa hồng` (A15 `target_campaign`, per campaign × product) | PARTIAL | G-15 |
| `target_margin_rate` (biên mục tiêu %) | `Biên mục tiêu` (C2) | **GAP** | G-12 |
| `seller_max_discount_rate` (cap) | `giảm tối đa (%)` (C1) | **GAP** (storage OK) | G-12 |
| Breach test: buyer_paid per unit after all discounts < operating floor | order lines | **GAP** | G-03 |

## 7. §7 Voucher what-if

The inputs of a NEW voucher are card inputs (typed by the seller); the data needed from sources is the history and the shop's existing vouchers.

| Input | Source field(s) | Status | Gap |
|---|---|---|---|
| Q = confirmed orders ≥ đơn tối thiểu in the window, scaled to the voucher's days | order lines (order subtotal, `ordered_at`) | **GAP** | G-03 |
| u = usage rate of comparable past vouchers ("shown") | `Tỷ lệ sử dụng (Đơn đặt hàng được xác nhận)` → `promos.extra.usage_rate` (A9); live `current_usage` ÷ `usage_limit` or `distributed_count` (B9) | OK (stored); selection of "comparable" vouchers not coded (caller passes `usage_rate`; default 1 = `default_1`) | G-14 |
| số lượng voucher (usage limit) | connector `usage_limit` → `extra.usage_limit` (B9) | OK* | G-16 |
| giá trị (đ or %, with max) | `value` / `discount` / `max_value` → `extra.discount_amount` / `discount_percent` / `max_value` (B9) | OK* (existing vouchers; a new voucher is typed) | G-16 |
| đơn tối thiểu (min spend) | `min_price` → `extra.min_spend` (B9) | OK* | G-16 |
| giới hạn mỗi người | `rule.usage_limit_per_user` (B9) | OK* but never enforced (§9, no buyer key) | by design |
| thời gian (days) | `start_time`, `end_time` (B9); export `Khung Thời Gian` (A9) | OK* | G-16 |
| cost actual per voucher | `Chi phí (Đơn đặt hàng được xác nhận) (VND)` (A9) | OK | G-14 (join) |
| Per-order discount %, buyer_paid, fees, contribution, margin (organic vs ad-attributed) | order lines + `ad_attributed` | **GAP** | G-03, G-04 |
| Floor breach per SKU in qualifying orders | order lines + floors (§6) | **GAP** | G-03, G-12 |
| Spend check: cost ÷ days vs trần chi/ngày | `Trần ngân sách QC/ngày` (C2) | **GAP** | G-12 |
| Break-even extra orders = ⌈Δcost ÷ contribution/order⌉ | contribution per order | **GAP** | G-03 |
| "Dự kiến" predicted range | caller range (models never disclosed) | not a source | none |

## 8. §8 Metric → recommendation wiring (data needed per `change_kind` / critical metric)

| Critical metric (card kinds) | Data keys needed | Source field(s) | Status | Gap |
|---|---|---|---|---|
| Lượt xem (flow / keyword) low (`title`, `keyword`, `ads_budget` purpose hien_thi, `affiliate_commission`) | views per flow / product; keyword views | A2/A3 views; `ads_keyword_period` (`Từ khóa / Vị trí`, `Số lượt xem`, `Số lượt click`, `Chi phí`); `Lượt click từ Trang tìm kiếm`; keyword volume tables (ADR-119) | PARTIAL | G-06; ad purpose per campaign is seller-set (`ad_campaign_purposes`) |
| CTR low (`cover_image`, `title`, `price_display`) | clicks ÷ views per product / flow; image; price shown | `Lượt nhấp vào sản phẩm`, `Lượt xem sản phẩm`/`Lượt hiển thị sản phẩm` (A3/A4); image + price from B6 | PARTIAL (image/price RESERVED) | G-09 |
| CTOR low (`product_discount`, `min_spend_voucher`, `review_voucher`, `price`) | orders ÷ clicks; current discount / voucher state; rating | A3/A4; `tag.has_discount`, `price_detail.has_discount` (B6); voucher settings (B9); rating | PARTIAL | G-09, G-10 |
| AOV low (`bundle_deal`, `add_on`, `min_spend_voucher`, `variation_set`) | AOV per product; bundle / add-on state; variations | `Doanh thu trên mỗi đơn (…)` (A4); `tag.has_bundle_deal`, `has_add_on_deal` (B6); `platform_items` variations | PARTIAL | G-09 |
| Biên < target or floor breach (`price`, `voucher_cap`, `ads_roas_target`, `ads_pause`) | margin, floor, target | §4, §6 | **GAP** | G-03, G-12 |
| ROAS < break-even, purpose chuyen_doi (`ads_roas_target`, `ads_pause`, `ads_purpose`) | direct ROAS per product; break-even; ROAS target in force; campaign state | `Doanh số trực tiếp` / `Chi phí` (A13); `roi_target` (B8); `roi_two_target`, `state` (B7); contribution before ads (§4) | PARTIAL | G-03, G-08 |
| Liên kết share / commission (`affiliate_commission`, `affiliate_target_campaign`) | affiliate share of GMV; commission rate; campaign terms; KOL ranking | `Tiếp thị liên kết` L1 (A2); `Tỉ lệ hoa hồng`, `Tên chiến dịch` (A15); `AMSAffiliatePerformance` rows | OK | G-15 for per-line commission |
| Card payload: metric key, flow/lever, product id, `change_kind`, ₫ at stake | product id = `Mã sản phẩm` (all) | OK | none |
| Flags (price_competitive / uncompetitive, ads_grow / optimize / track) | `product_flags` | OK (id only; `Giá đang bán`, `Phân loại (không) cạnh tranh` not parsed) | A5 |

## 9. Product header fields (Sản phẩm page)

| Field | Source field(s) | Status | Gap |
|---|---|---|---|
| Mã SP, tên, trạng thái | `Mã sản phẩm`, `Sản phẩm`, `Tình trạng sản phẩm hiện tại` (A3/A4) → `platform_items`; B5 `id`, `name`, `status` | OK | none |
| SKU, variations | `SKU phân loại`, `SKU sản phẩm`, `Mã phân loại hàng`, `Tên Phân Loại` (A4); B5 `parent_sku`, `model_list[].sku`, `.name` | OK | none |
| Cover image + gallery + image history | B6 `cover_image`, `model_list[].image`; image copies | RESERVED; no gallery list (only cover); no downloader | G-09 |
| Price (niêm yết, đang bán, active programme) | B6 `price_detail.*`, `model_list[].price_detail.origin_price/promotion_price`; flag sheet `Giá đang bán` (A5, not parsed) | RESERVED | G-09 |
| Stock (per variation, days to sell-out, restock date) | B6 `stock_detail.*`; C1 `tồn kho`, `ngày nhập lại` | RESERVED / GAP | G-09, G-12 |
| Rating, rating count | none | **GAP** | G-10 |
| Category path | none (A16 drops L1-L3) | **GAP** | G-10, G-11 |
| Sold (total) | B6 `statistics.sold_count`; period `Sản phẩm (Đơn đã xác nhận)` (A4) | RESERVED (total) / OK (period) | G-09 |
| Likes | B6 `statistics.liked_count` (total); `Lượt thích` (A4/A7, period) | RESERVED / OK (period) | G-09 |
| Created date, age | B6 `create_time`; `Ngày tạo`, `Số ngày tạo` (A5 `Sản Phẩm Mới`) | RESERVED / NOT PARSED | G-09 |
| Nhóm, Ưu tiên, seller status | C1 `nhóm`, `trạng thái` | **GAP** | G-12 |
| Per-block freshness ("Cập nhật … · nguồn …") | `ingest_dataset_status` (`last_ingest_at`, `last_source`) | OK | none |

## 10. Duplicate sources: which one does the code treat as primary

Rule in the gateway: `source_rank` (`api` 3 > `file` 2 = `extension` 2 > `vendor` 1) only arbitrates writes to the SAME row key; the key contains `dataset`, so two datasets never compete in storage. Which dataset is "primary" is decided by each reader (SQL in `services/ops/shopee_dashboards.py`, `services/shopee_kpi/job.py`) or by the arguments the caller gives `services/shopee_profit/*`. Test for the rank rule: `FD::test_an_api_post_replaces_a_file_post_on_the_same_period_key`.

| Metric | Source A | Source B (/C) | Primary in code | Conflict / flag |
|---|---|---|---|---|
| Shop GMV, orders, per day | `shop_overview` (file) `Tổng doanh số (VND)`, `Tổng số đơn hàng` | Σ L1 flows `traffic_overview` (file or connector); `product_overview` `Doanh số (Đơn đã xác nhận) (VND)`; `sales_overview` (not parsed); Σ `product_period`; order lines | `shop_overview`: P90 `build_flow_tables(shop_gmv=)`, ops `_SHOP_MONTHLY`; gap to flows shown as the `chenh_lech_nguon` row; order lines reconciled at 2 % | G-02 (monthly roll-up corrupts day-1), G-21 (which GMV column) |
| Flow GMV / views / clicks per day | `traffic_overview` day rows from the xlsx (with L2) | the same dataset from connector B1 (L1, confirmed only, yesterday) | none: equal rank, later post wins | G-22 |
| Flow totals per month | `traffic_overview` day rows summed | `traffic_overview_period` total rows (file) | daily for months that have day rows; period rows fill months with none (`_merge_months` in `ops/shopee_dashboards.py`) | two datasets for the same month; never add them (the code does not) |
| Product GMV / orders per period | `product_period` (`parentskudetail`) | Σ `item_by_source_period` over L1 sources (Shopee de-duplicates, so not equal); connector `item_performance` B4 (inactive); order lines | `product_period` as `product_totals` of `build_flow_tables`; difference = residual row | none coded between A and B |
| Per-product flow metrics | `item_by_source_period` (file) | connector `item_by_source` B3 (inactive, daily) | file | G-06 |
| Total ad spend | ads CSV `Chi phí` Σ rows (period, placed, overlapping windows) | `Chi phí quảng cáo` on `Dịch vụ Hiển thị Shopee` (shop-stats, daily, per order-type sheet, key `extra.ads_expense`); connector `report.cost` (daily, key **`extra.cost`**) | none: `shop_profit.shop_profit(campaigns=, product_ad_spend=)` takes the caller's numbers; ops ads view reads the shop-stats ads rows (`DEFAULT_ADS_ORDER_TYPE = 'placed'`) | G-07, G-22; key names differ (`ads_expense` vs `cost`) |
| Ad GMV broad / orders | CSV `Doanh số`, `Lượt chuyển đổi` | shop-stats ads `Doanh số (VND)`, `Tổng số đơn hàng`; connector `broad_gmv`, `broad_order` | none | G-08 (placed vs confirmed vs paid) |
| Ad GMV direct | CSV `Doanh số trực tiếp` | connector `direct_gmv` | none | only these two |
| Product ad spend | CSV group rows with `Mã sản phẩm` | none (connector has no product split) | CSV | G-07 |
| ROAS target | connector get_time_graph `roi_target_setting.value` | campaign `roi_two_target` (B7); rule `target_roas`; `ops_log` budget text (RESERVED) | none | informational |
| Voucher cost / usage | `voucher_*.xlsx` `Chi phí`, `Tỷ lệ sử dụng` | connector `value × current_usage`; order lines Σ `shop_voucher_share`; ads `Voucher Amount` | none coded (contract §10 says the export reconciles exactly with value × orders) | G-14; do not add ads `Voucher Amount` to voucher cost |
| Commission | `ValidationBill` `Hoa hồng hằng tháng(₫)` (actual, monthly) | `affiliate_product` `Hoa hồng ước tính(₫)` (estimate); A16 per line (RESERVED); `target_campaign` rate | none: `order_profit.line_profit` takes `line.commission` else `affiliate_rate × buyer_paid` else MISSING | G-15 |
| Affiliate GMV | `traffic_overview` `Tiếp thị liên kết` (by order-type sheet) | `affiliate_product_period` `Doanh thu(₫)` (program estimate, `order_type none`) | none; `mapping._affiliate_product` states they are not the same | informational |
| Platform fees | income export actuals (`actual_fees`) | formula by date (`FeeSchedule.formula_on`) | actual wins when not NULL (`line_profit`) | G-05, G-11 |
| Promotions (Flash Sale) | `discount_*` `Biểu đồ` rows of type `Flash Sale` | `In_Shop_Flash_Sale_Metrics` (`promotion_daily`); `flash_sale_performance_list` (`promotions`) | none | G-23 |
| Product identity (name, SKU, status) | `product_period` / `item_by_source_period` → `platform_items` | connector `item_catalog` → `platform_items` | newest post wins when rank ≥; null never overwrites (coalesce) | equal rank: connector and file overwrite each other |
| Likes / sold / created | period counts (A4) | connector snapshot totals (B6, RESERVED) | none yet | G-09 |
| Category | `sales_composition` (shop split, unparsed) | A16 L1-L3 (dropped) | none | G-10, G-11 |
| KPI job flow naming | `shopee_kpi.job.FLOW_SOURCES["the_san_pham"]` = `product_card/all` (incl. Trang shop) | P90 `the_san_pham` = total − Trang shop | both used | G-20 |

