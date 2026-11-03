# Field-level extraction spec: Shopee seller view (as built)

Branch state read: `/Users/macos/Juli-AI-v2/juli/.worktrees/ops-reco-pipeline` (branch `fasttrack/ops-reco-pipeline`, HEAD `302999f7`). Nothing in any git repo was modified.
Contract: `fasttrack/contracts/p90-metrics.md` (section numbers `§1`..`§10` below). Real header names come from `scratchpad/cols/headers.txt` and the raw files under `~/.juli-shop-snapshots/sim-pilot/ory/seller_center/*/raw/` (headers only; no values quoted).

As-built evidence added in this pass: `scripts/load_shopee_exports.py --dry-run` was run on the four real ORY folders (counts only):

| Folder | Result |
|---|---|
| `2026-10-29/raw` (shop-stats, parentskudetail, discount, productoverview, traffic_overview, sales_*) | 238 posts validate; 12 `sales_composition_*` + `sales_overview_*` listed "files not loaded" |
| `2026-10-30/raw` (voucher, flash sale, affiliate_product, Shop_Prize, productlist) | 63 posts validate; 4 `Shop_Prize_Key_Metrics_*` + 2 `productlist_p*.json` not loaded |
| `2026-11-01/raw` (ads_general, ads_group, ads_keyword) | 6 posts validate (ads_campaign_period 5 posts/40 rows, ads_keyword_period 1/5) |
| `2026-11-02/raw` (affiliate, ops_log, SellerConversionReport, product ad reports) | 16 posts validate + 8 reserved (ads_change_log 6 posts/40 rows, affiliate_order_lines 2 posts/42 rows); 2 `Dữ+liệu+Dịch+vụ+Hiển+thị+Sản+Phẩm-*.csv` not loaded. Needs `--window` of at most 31 days for the 3 dashboard exports that state no period |
| `2026-11-03/raw` (shop-stats 27/10-02/11, traffic_overview 27/10-02/11) | **REFUSED by the gateway validator**: one `shop_overview` row (order type `paid`, day 29-10-2026) has `Tỷ lệ chuyển đổi đơn hàng` above 100 % and `ShopeeShopOverviewRow.conversion_rate` is capped at 1. The whole post would be rejected. Details in `coverage.md` (G-01). |

## Legend

**Status**
- `LOADED`: parser (or connector mapper) and gateway dataset are both live; the value reaches a table.
- `LOADED*`: connector mapper and gateway dataset are live and unit-tested, but never run against the live Seller Centre (response shapes come from the 2026-11-03 recon only; money unit scale `MONEY_DIVISOR = 1` is UNVERIFIED).
- `RESERVED`: parsed/mapped and validated, deliberately not stored (`reserved.py`, `HELD_DATASETS`); gateway answers 404 for the dataset name.
- `NOT PARSED`: the file is in our hands (or the field is on a sheet we hold) but no code reads it, or the code reads and discards it (reason given as "dropped: ...").
- `NOT AVAILABLE`: the source file/endpoint has not been obtained, or does not exist for this sub-account.

**Targets.** `daily` = `platform_daily_metrics`, `period` = `platform_period_metrics`, `items` = `platform_items`, `flags` = `platform_product_flags`, `promos` = `platform_promotions`. KPI columns on daily/period rows: `impressions, clicks, ctr, orders, gmv, buyers, visitors, add_to_cart, units, page_views, bounce_rate`. `extra.<key>` = a numeric/boolean key of the row's `extra` JSON (strings are dropped on the server, owner decision D16). Row identity on daily/period rows: `(dataset, day or period, item_id, stream, segment, order_type)` + `variation_id` on period rows.

**Order type** `placed` = Đơn đã đặt / đặt hàng, `confirmed` = Đơn đã xác nhận / Đơn đặt hàng được xác nhận, `paid` = Đơn Đã Thanh Toán, `none` = not order-dependent. Contract default is `confirmed` (§1).

**Number formats.** xlsx exports store numbers as formatted text and are read by `parse.number`: `"12.345.678"` (dot thousands), `"123.456,70"` (comma decimals), `"4,25%"` (becomes the fraction 0.0425), `"-"` = no value, `"00:00:47"` = seconds. Counts may be fractional (`"6,00"`: multi-item orders are apportioned). CSV exports (ads, affiliate) use plain `1234.56` and `4.25%`; a cell with a comma is read as Vietnamese. Dates in xlsx: `DD-MM-YYYY` (range totals `DD-MM-YYYY-DD-MM-YYYY`); ads CSV window `DD/MM/YYYY - DD/MM/YYYY`; affiliate target_campaign `YYYY/MM/DD hh:mm`; order report times `YYYY-MM-DD hh:mm:ss`. Seller Centre calendar is GMT+7. Rates are fractions in [0,1] (ads/affiliate ratios `Ratio` may exceed 1); a rate above 1 makes the gateway refuse the whole post.

**Test column.** Aliases: `EXP` = `tests/unit/test_shopee_export_loader.py`, `AFF` = `tests/unit/test_shopee_affiliate_loader.py`, `FD` = `tests/unit/test_shopee_file_datasets.py`, `RD` = `tests/unit/test_shopee_reader_datasets.py`, `S108` = `tests/unit/test_shopee_ops_data_schema.py`, `S112` = `tests/unit/test_shopee_profit_schema.py`, `P90` = `tests/unit/test_shopee_profit_p90.py`, `PRF` = `tests/unit/test_shopee_profit.py`, `C-MAP` = `apps/connector/test/map.test.ts`, `C-RM` = `apps/connector/test/reader-map.test.ts`, `C-RD` = `apps/connector/test/reader.test.ts`, `C-CT` = `apps/connector/test/contract.test.ts`, `C-CR` = `apps/connector/test/connector-readers.test.ts`, `C-SY` = `apps/connector/test/sync.test.ts`. Tests use synthetic headers with a SUBSET of columns; a "dataset-level" mark means the test exercises the parser/dataset path and the column is not itself pinned by a value assertion. `none` = no test touches it.

**Storage rule (`gateway._upsert`)**: a row is replaced only by a source of the same or higher `source_rank` (`vendor` 1 < `file` = `extension` 2 < `api` 3). File and connector have EQUAL rank, so the later post wins on the same key; the key includes `dataset`, so a file dataset and a connector dataset with different names never collide (see `coverage.md` section 10).

---

# A. Seller Centre export files

File-name patterns come from `parse.PARSERS` (anything else is listed as skipped and never opened). Gateway ingest sets `source = "file"`, `source_version = "seller-centre-xlsx-1"`, `mapper_version = 1`.

## A1. `*.shopee-shop-stats.<YYYYMMDD>-<YYYYMMDD>.xlsx`, sheets `Đơn hàng đã đặt` / `Đơn đã xác nhận` / `Đơn Đã Thanh Toán` → dataset `shop_overview`

Real example: `oryvietnam.shopee-shop-stats.20251101-20251130.xlsx`. One post per sheet = one order type (sheet name → `placed` / `confirmed` / `paid`); day rows (`Ngày` = `DD-MM-YYYY`) → `daily` row, stream `total`, `item_id ''`, segment `all`. The sheet's first data row (`DD-MM-YYYY-DD-MM-YYYY`, the period total) is skipped. Posts are cut at calendar months (≤ 31 days, ≤ 2 000 rows).

| Source field | Unit/format | Order type | Target | Used by | Status | Test |
|---|---|---|---|---|---|---|
| `Ngày` | `DD-MM-YYYY` | n/a | row `date` | key | LOADED | `EXP::test_shop_stats_becomes_daily_sources_period_totals_and_shop_overview` |
| `Tổng doanh số (VND)` | VND, `1.234.567` | sheet (placed/confirmed/paid) | shop_overview → daily.`gmv` | §1 GMV (Doanh số) shop level; §2 shop GMV the flows add up to (`shop_gmv`); §4 reconciliation (order lines vs export > 2 %); §5 AOV | LOADED | `EXP::test_shop_stats_becomes_daily_sources_period_totals_and_shop_overview` (`Tổng doanh số (VND)` in `SHOP_HEADER`) |
| `Doanh số không bao gồm trợ giá bởi Shopee` | VND | sheet | → daily.`extra.sales_excl_shopee_subsidy` | §10 fee base is "giá trước Shopee trợ giá" (not wired to any calc); AMBIGUITY: contract §1 says "Shopee's Doanh số" without saying which of the two columns | LOADED | `FD::test_shop_and_product_overview_map_onto_the_total_stream` (dataset-level) |
| `Tổng số đơn hàng` | count, may be fractional (`6,00`) | sheet | → daily.`orders` | §2 `shop_orders`; §5 ④ số đơn; §5 ⑤ AOV | LOADED | `EXP::test_shop_stats_becomes_daily_sources_period_totals_and_shop_overview` |
| `Doanh số trên mỗi đơn hàng` | VND | sheet | → daily.`extra.sales_per_order` | §5 ⑤ AOV (Shopee's own; code recomputes GMV ÷ đơn) | LOADED | `FD::test_shop_and_product_overview_map_onto_the_total_stream` (dataset-level) |
| `Lượt nhấp vào sản phẩm` | count | sheet | → daily.`clicks` | §2 shop clicks (cross-check of Σ flow clicks) | LOADED | `FD::test_shop_and_product_overview_map_onto_the_total_stream` |
| `Số lượt truy cập` | count | sheet | → daily.`visitors` | none in the contract (shop visits) | LOADED | `EXP::test_shop_stats_becomes_daily_sources_period_totals_and_shop_overview` (`Số lượt truy cập` in `SHOP_HEADER`) |
| `Tỷ lệ chuyển đổi đơn hàng` | `%` text → fraction | sheet | → daily.`extra.conversion_rate` (model cap ≤ 1) | none; **REFUSES the whole post when > 100 %** (real: `paid` sheet, 29-10-2026) | LOADED (fails on real 2026-11-03 file) | none |
| `Đơn đã hủy` | count | sheet | → daily.`extra.cancelled_orders` | §4 order status (cancelled orders carry no fee/profit) at AGGREGATE level only | LOADED | none |
| `Doanh số đơn hủy` | VND | sheet | → daily.`extra.cancelled_sales` | §4 order status (aggregate) | LOADED | none |
| `Đơn đã hoàn trả / hoàn tiền` | count | sheet | → daily.`extra.returned_orders` | §4 order status (aggregate) | LOADED | none |
| `Doanh số các đơn Trả hàng/Hoàn tiền` | VND | sheet | → daily.`extra.returned_sales` | §4 order status (aggregate) | LOADED | none |
| `số người mua` | count (aggregate; not PII) | sheet | → daily.`buyers` | none in the contract | LOADED | `FD::test_shop_and_product_overview_map_onto_the_total_stream` |
| `số người mua mới` | count | sheet | → daily.`extra.new_buyers` | none | LOADED | none |
| `số người mua hiện tại` | count | sheet | → daily.`extra.existing_buyers` | none | LOADED | none |
| `số người mua tiềm năng` | count, can be negative | sheet | → daily.`extra.potential_buyers` | none | LOADED | none |
| `Tỉ lệ quay lại của người mua` | `%` → fraction | sheet | → daily.`extra.repeat_purchase_rate` | none | LOADED | none |

Hazard (G-02): the real file `oryvietnam.shopee-shop-stats.20260101-20260930.xlsx` is a MONTHLY roll-up: its rows are dated `01-01-2026`, `01-02-2026` ... `01-09-2026` and each holds that whole month's total. The parser reads them as nine daily rows (27 posts) and would overwrite the 1st-of-month day of Jan-Sep 2026 with a month total (same key, equal rank, later post wins). Nothing detects row granularity.

## A2. same file, sheets `(đơn đã đặt)Theo nguồn lưu ...` / `(đơn đã xác nhận)Theo nguồn...` / `(đơn đã thanh toán)Theo ngu...` → datasets `traffic_overview` (day rows) and `traffic_overview_period` (total rows)

Each sheet holds five blocks, one per L1 group (title row `Thẻ sản phẩm`, `Live`, `Video`, `Tiếp thị liên kết`, `Dịch vụ Hiển thị Shopee`), each with its own header row starting `Nguồn lưu lượng`. Under the header: the L1 total row (label = group title; after it day rows `DD-MM-YYYY`), then one block per L2 child (label row, then its day rows). L1 total → stream, segment `all`; L2 child → same stream, segment = code below (a breakdown of the L1 total, never added to it). Day rows → `traffic_overview` (daily); label rows' totals → `traffic_overview_period` (period = file name period, must be ≤ 31 days, else the whole load stops with ValueError). Order type = sheet. The `Nguồn truy cập cho Đơn hàng...`, `Nguồn lưu lượng truy cập (đ...` and `Nguồn truy cập từ Đơn hàng ...` sheets are shop-level summary pivots: NOT PARSED (duplicate of the totals; counted in notes "sheet not loaded (summary)").

L1 / L2 maps (`mapping.SHOPEE_L1_TO_STREAM`, `schemas.SHOPEE_L2_SOURCES`; an unlisted L2 label is refused 422):

| L1 title (file) | stream | L2 labels → segment |
|---|---|---|
| `Thẻ sản phẩm` | `product_card` | `Tìm kiếm` search, `Đề xuất` recommend, `Cửa hàng` **shop_page** (= contract "Trang shop"), `Giỏ hàng` cart, `Đơn mua của tôi` my_orders, `Khác` other, `Khuyến mãi` promo, `Chat` chat |
| `Live` | `seller_live` | the six card-like labels above, `Thẻ Live` live_tab, `Trang chủ Shopee Live` live_home, `Video` video |
| `Video` | `seller_video` | the six card-like labels, `Thẻ Video` video_tab, `Trang chủ Shopee Video` video_home |
| `Tiếp thị liên kết` | `affiliate` | `Affiliate Live` aff_live, `Affiliate Video` aff_video |
| `Dịch vụ Hiển thị Shopee` | `ads` (overlay, never summed) | `Quảng cáo GMV tối đa ROAS tùy chỉnh cho sản phẩm` ads_roas_custom, `Quảng cáo GMV tối đa tự động đấu thầu cho sản phẩm` ads_auto_bid, `Quảng cáo cửa hàng` ads_shop, `Product Ads (GMV Max-Shop)` ads_gmvmax_shop, `Khác` other |

Column set differs per group (real header, `(đơn đã xác nhận)Theo nguồn...`): product card block has `Lượt hiển thị sản phẩm`; Live has `Lượt xem Livestream` and `Người xem Livestream`; Video has `Lượt xem Video` / `Người xem Video`; affiliate has `Lượt xem nội dung` / `Người xem nội dung`; the ads block has only `Nguồn lưu lượng | Tỷ lệ doanh số | Doanh số (VND) | Ads Impression | Tổng số đơn hàng | Tỷ lệ chuyển đổi | Chi phí quảng cáo | ROAS quảng cáo` (no clicks column).

| Source field | Unit/format | Order type | Target | Used by | Status | Test |
|---|---|---|---|---|---|---|
| `Nguồn lưu lượng` (L1 title / L1 total label / L2 label / `DD-MM-YYYY`) | text; date | n/a | → stream, `platform_source` (raw L1 enum e.g. `psd_label_product_card`), `segment`, day | §2 flow identity: `the_san_pham` = product_card/all − product_card/shop_page; `trang_shop` = product_card/shop_page; `live` = seller_live/all; `video` = seller_video/all; `lien_ket` = affiliate/all (incl. aff_live/aff_video) | LOADED | `FD::test_a_level_two_source_is_a_segment_beside_the_level_one_total`, `FD::test_an_unknown_level_two_label_is_refused`, `EXP::test_shop_stats_becomes_daily_sources_period_totals_and_shop_overview` |
| `Tỷ lệ doanh số` | `%` | sheet | dropped: Shopee's own share, derivable | none | NOT PARSED (dropped) | header accepted by `EXP::test_shop_stats_becomes_daily_sources_period_totals_and_shop_overview`; absence not asserted |
| `Doanh số (VND)` | VND | sheet | → `gmv` | §2 GMV per flow; §5 | LOADED | `EXP::test_shop_stats_becomes_daily_sources_period_totals_and_shop_overview` |
| `Lượt hiển thị sản phẩm` | count | sheet | → `impressions` (product_card); on live/video/affiliate it stays `extra.product_impressions` when the stream's own views column exists | §2 views for `the_san_pham`/`trang_shop` (product impressions) | LOADED | `FD::test_live_impressions_are_views_and_ads_rows_keep_the_post_order_type` |
| `Lượt xem Livestream` | count (**live sessions viewed**) | sheet | → `impressions` (seller_live) | §2 Live "Lượt xem phiên"; CTR never compared across flows | LOADED | `FD::test_live_impressions_are_views_and_ads_rows_keep_the_post_order_type` |
| `Lượt xem Video` | count (**videos viewed**) | sheet | → `impressions` (seller_video) | §2 Video "Lượt xem video" | LOADED | none (live path pinned only) |
| `Lượt xem nội dung` | count | sheet | → `impressions` (affiliate) | §2 liên kết views | LOADED | none |
| `Ads Impression` | count | sheet | → `impressions` (ads) | §2 ads overlay | LOADED | `EXP::test_shop_stats_becomes_daily_sources_period_totals_and_shop_overview` (`ADS_HEADER`) |
| `Lượt nhấp vào sản phẩm` | count | sheet | → `clicks` | §2 clicks, CTR = clicks ÷ views | LOADED | `EXP::test_shop_stats_becomes_daily_sources_period_totals_and_shop_overview` |
| `Tổng số đơn hàng` | count, fractional | sheet | → `orders` | §2 CTOR = orders ÷ clicks; AOV | LOADED | same |
| `Sản phẩm` | units | sheet | → `units` | none | LOADED | `FD::test_source_period_totals_keep_the_segment_and_item_rows_skip_extra_names` |
| `CTR` | `%` (can exceed 100 % on L2) | sheet | dropped: gateway rate guard (≤ 1) would refuse; readers derive clicks ÷ impressions | §2 CTR is DERIVED, not read | NOT PARSED (dropped) | `EXP::test_shop_stats_becomes_daily_sources_period_totals_and_shop_overview` (asserts no `ctr` in rows) |
| `Tỷ lệ chuyển đổi đơn hàng` | `%` | sheet | dropped: derive orders ÷ clicks | §2 CTOR derived | NOT PARSED (dropped) | none |
| `Tỷ lệ chuyển đổi` (ads block only) | `%` | sheet | → `extra.conversion` | none | LOADED | none |
| `Doanh số trên mỗi đơn hàng` | VND | sheet | → `extra.sales_per_order` | §2 AOV (derived by code instead) | LOADED | none |
| `Người mua` | count | sheet | → `buyers` | none | LOADED | none |
| `Lượt hiển thị sản phẩm duy nhất` | count | sheet | → `extra.unique_product_impressions` | none | LOADED | none |
| `Người xem Livestream` / `Người xem Video` / `Người xem nội dung` | count | sheet | → `extra.live_viewers` / `video_viewers` / `content_viewers` | none | LOADED | none |
| `Lượt nhấp sản phẩm duy nhất` | count | sheet | → `extra.unique_product_clicks` | none | LOADED | none |
| `Chi phí quảng cáo` (ads block) | VND | sheet | → `extra.ads_expense` | §4 total ad spend (SHOP-LEVEL daily, by order-type sheet); §5 chi | LOADED | `EXP::test_shop_stats_becomes_daily_sources_period_totals_and_shop_overview` |
| `ROAS quảng cáo` (ads block) | ratio (may be > 1) | sheet | → `extra.ads_roas` | §4 shop-level broad ROAS | LOADED | same |

## A3. same file, sheets `Theo sản phẩm (đơn đã đặt)` / `Theo sản phẩm (đơn đã xác n...` / `Theo sản phẩm (đơn đã thanh...` → dataset `item_by_source_period`

Four L1 blocks only (`Thẻ sản phẩm`, `Live`, `Video`, `Tiếp thị liên kết`); header `Mã sản phẩm | Sản phẩm | Tình trạng sản phẩm hiện tại | Tỷ lệ doanh số | Doanh số (VND) | Lượt hiển thị sản phẩm | Lượt nhấp vào sản phẩm | Tổng số đơn hàng | Sản phẩm | CTR | Tỷ lệ chuyển đổi đơn hàng | Doanh số trên mỗi đơn hàng | Người mua | Lượt hiển thị sản phẩm duy nhất | Lượt nhấp sản phẩm duy nhất` (identical in all four blocks). One row per item × L1 source for the file period (≤ 31 days). NO L2 split exists in this sheet (so no per-product "Cửa hàng" / Trang shop figure) and NO `Dịch vụ Hiển thị` block (no per-product ads in this export).

| Source field | Unit/format | Order type | Target | Used by | Status | Test |
|---|---|---|---|---|---|---|
| `Mã sản phẩm` | digits | n/a | → row `item_id`, `period.item_id` | §2 per-product flow table (`FlowRow.product_id`) | LOADED | `FD::test_source_period_totals_keep_the_segment_and_item_rows_skip_extra_names` |
| `Sản phẩm` (col 2, product name) | text ≤ 500 | n/a | → `items.name` (not copied to extra) | product header (name) | LOADED | same |
| `Tình trạng sản phẩm hiện tại` | text | n/a | → `items.status` | product header (status) | LOADED | same |
| `Tỷ lệ doanh số`, `CTR`, `Tỷ lệ chuyển đổi đơn hàng` | % | sheet | dropped (derived) | n/a | NOT PARSED (dropped) | none |
| `Doanh số (VND)` | VND | sheet | → `period.gmv` stream per L1 | §2 per-product GMV per flow | LOADED | same |
| `Lượt hiển thị sản phẩm` | count | sheet | → `impressions` (**product impressions for EVERY L1**, including Live/Video/affiliate: NOT the shop-level Live session or Video view definition) | §2 per-product views. DEFINITION MISMATCH vs A2 (see coverage G-06) | LOADED | none |
| `Lượt nhấp vào sản phẩm` | count | sheet | → `clicks` | §2 | LOADED | same (dataset) |
| `Tổng số đơn hàng` | count | sheet | → `orders` | §2 | LOADED | same |
| `Sản phẩm` (col 9, units), `Doanh số trên mỗi đơn hàng`, `Người mua`, `Lượt hiển thị sản phẩm duy nhất`, `Lượt nhấp sản phẩm duy nhất` | | sheet | → `units`, `extra.sales_per_order`, `buyers`, `extra.unique_product_impressions`, `extra.unique_product_clicks` | none | LOADED | none |

## A4. `parentskudetail.<YYYYMMDD>_<YYYYMMDD>.xlsx`, sheet `Sản Phẩm Hiệu Quả Tốt` → dataset `product_period` (+ `platform_items`)

One row per product (variation columns `-`) and per variation. Two posts per file (placed, confirmed); the sheet has `placed`/`confirmed` column pairs, each post takes its own pair and the order-independent columns repeat. `variation_id ''` = the item. Period = file name (≤ 31 days). Real files range from 1 day (`parentskudetail.20251112_20251112.xlsx`) and 7 days (`parentskudetail.20261019_20261025.xlsx`) to a month.

| Source field | Unit/format | Order type | Target | Used by | Status | Test |
|---|---|---|---|---|---|---|
| `Mã sản phẩm` | digits | n/a | → `period.item_id`; `items.item_id` | key; §8 "product id" | LOADED | `EXP::test_parentskudetail_posts_each_order_type_with_variations_and_flags` |
| `Sản phẩm` | text ≤ 500 | n/a | → `items.name` | product header | LOADED | same |
| `Tình trạng sản phẩm hiện tại` | text | n/a | → `items.status` (item row) | product header (status) | LOADED | same |
| `Mã phân loại hàng` | digits or `-` | n/a | → `variation_id` | §4 per-SKU keys (variation) | LOADED | same |
| `Tên Phân Loại` | text ≤ 255 | n/a | → `items.variation_name` | product header (variations) | LOADED | same |
| `Trạng thái phân loại sản phẩm hiện tại` | text | n/a | → `items.status` (variation row) | product header | LOADED | none (not asserted) |
| `SKU phân loại` / `SKU sản phẩm` | text ≤ 100 | n/a | → `items.seller_sku` (`SKU phân loại` when a variation, else `SKU sản phẩm`) | §4 giá vốn join key (SKU sheet `SKU`); §6 | LOADED | same (`seller_sku` asserted) |
| `Doanh số (Đơn đã đặt) (VND)` / `Doanh số (Đơn đã xác nhận) (VND)` | VND | placed / confirmed | → `period.gmv` | §1/§2 per-product GMV (`product_totals`); §4 reconciliation | LOADED | same (`sales` asserted) |
| `Lượt xem sản phẩm` | count | n/a | → `impressions` (**assumed equal to "Lượt hiển thị sản phẩm"**) | §2 views | LOADED | same (in header) |
| `Lượt nhấp vào sản phẩm` | count | n/a | → `clicks` | §2 | LOADED | dataset |
| `CTR` | `%` | n/a | → `ctr` | §2 (Shopee's; code derives its own) | LOADED | dataset |
| `Tỷ lệ chuyển đổi đơn (Đơn đã đặt)` / `(Đơn đã xác nhận)` | % | placed / confirmed | → `extra.product_clicks_to_orders_rate` | §2 CTOR (code derives orders ÷ clicks) | LOADED | none |
| `Đơn hàng đã đặt` / `Đơn đã xác nhận` | count | placed / confirmed | → `orders` | §2 `product_totals`, §5 ④ per product | LOADED | same (`orders` asserted) |
| `Sản phẩm (Đơn đã đặt)` / `Sản phẩm (Đơn đã xác nhận)` | units | placed / confirmed | → `units` | none | LOADED | dataset |
| `Người mua đã đặt hàng` / `Người mua có đơn đã xác nhận` | count | placed / confirmed | → `buyers` | none | LOADED | dataset |
| `Tỷ lệ chuyển đổi (Đơn đã đặt)` / `(Đơn đã xác nhận)` | % | placed / confirmed | → `extra.conversion_rate` | none | LOADED | none |
| `Doanh thu trên mỗi đơn (Đơn đã đặt) (VND)` / `(Đơn đã xác nhận) (VND)` | VND | placed / confirmed | → `extra.sales_per_order` | §5 ⑤ AOV (Shopee's) | LOADED | none |
| `Lượt hiển thị sản phẩm duy nhất`, `Lượt nhấp sản phẩm duy nhất` | count | n/a | → `extra.unique_product_impressions`, `extra.unique_product_clicks` | none | LOADED | none |
| `Lượt truy cập sản phẩm` | count | n/a | → `visitors` | none | LOADED | none |
| `Lượt xem trang sản phẩm` | count | n/a | → `page_views` | none | LOADED | none |
| `Số lượng khách thoát trang sản phẩm` | count | n/a | → `extra.bounced_visitors` | none | LOADED | none |
| `Tỷ lệ thoát Trang sản phẩm` | % | n/a | → `bounce_rate` | none | LOADED | none |
| `Lượt click từ Trang tìm kiếm` | count | n/a | → `extra.search_clicks` | §8 keyword/search views (partial proxy) | LOADED | none |
| `Lượt thích` | count | n/a | → `extra.likes` | product header "likes" (period count, not the live total) | LOADED | none |
| `Lượt truy cập sản phẩm (Thêm vào giỏ hàng)` | count | n/a | → `add_to_cart` | none | LOADED | none |
| `Sản phẩm (Thêm vào giỏ hàng)` | units | n/a | → `extra.atc_units` | none | LOADED | none |
| `Tỷ lệ chuyển đổi (theo lượt thêm vào giỏ hàng)` | % | n/a | → `extra.atc_rate` | none | LOADED | none |
| `Tỷ lệ mua lại (Đơn đã đặt)` / `Tỷ lệ đặt hàng lặp lại (Đơn hàng đã được xác nhận)` | % | placed / confirmed | → `extra.repeat_purchase_rate` | none | LOADED | none |
| `Số ngày trung bình mà Người mua quay lại đặt hàng (Đơn đã đặt)` / `Số ngày trung bình để lặp lại đơn hàng (Đơn hàng đã được xác nhận)` | days | placed / confirmed | → `extra.repeat_purchase_days` | none | LOADED | none |

## A5. same file, flag sheets → dataset `product_flags`

Sheets matched by prefix (Excel cuts names at 31 characters): `Sản Phẩm Mới` new_product, `Giá cạnh tranh` price_competitive, `Giá không cạnh tranh` price_uncompetitive, `Tăng trưởng cùng DVHT` ads_grow, `Tối ưu chiến dịch DVHT` ads_optimize, `Theo dõi hiệu quả chiến dịc...` ads_track. ONLY column 0 (`Mã sản phẩm`) is read; one `(item_id, flag)` row per distinct id.

| Source field | Unit/format | Order type | Target | Used by | Status | Test |
|---|---|---|---|---|---|---|
| `Mã sản phẩm` (every flag sheet) | digits | none | → flags.`item_id`, flags.`flag`, period of the file | §8 hints (price competitive, ads grow/optimize) | LOADED | `EXP::test_parentskudetail_posts_each_order_type_with_variations_and_flags` |
| `Sản Phẩm Mới`: `Ngày tạo` | date | n/a | not read | product header "created" (created_on) | NOT PARSED | none |
| `Sản Phẩm Mới`: `Số ngày tạo` | days | n/a | not read | product header "age" | NOT PARSED | none |
| `Giá không cạnh tranh`: `Giá đang bán`, `Phân loại không cạnh tranh`; `Giá cạnh tranh`: `Giá đang bán`, `Các phân loại cạnh tranh` | VND / text | n/a | not read (only the id is kept) | §6/§8 price display and variation-level competitiveness | NOT PARSED | none |
| All the metric columns repeated in the flag sheets (`Lượt xem sản phẩm` ... `Số ngày trung bình để lặp lại đơn hàng (Đơn hàng đã được xác nhận)`) | | | not read: duplicates of `Sản Phẩm Hiệu Quả Tốt` | n/a | NOT PARSED (dropped: duplicate) | none |

Note: `Tăng trưởng cùng DVHT` / `Tối ưu chiến dịch DVHT` / `Theo dõi hiệu quả chiến dịc...` carry the same product metric columns minus `Giá`/`Ngày tạo`; `Sản Phẩm Hiệu Quả Tốt` (A4) is the only metrics source.

## A6. `discount_<YYYYMMDD>-<YYYYMMDD>.xlsx` → datasets `promotion_daily` (sheet `Biểu đồ`) and `promotions` (sheet `Danh sách hiệu suất`)

Sheets: `Tổng quan` (NOT PARSED: period summary, silently ignored), `Biểu đồ` (day rows), `Danh sách hiệu suất` (one row per programme). Headers (identical column set in all three): `Ngày | Loại khuyến mãi | Bán hàng (đặt hàng) (VND) | Bán hàng (Đơn đặt hàng được xác nhận) (VND) | Đơn đặt hàng (đặt hàng) | Đơn đặt hàng (Đơn đặt hàng được xác nhận) | Đơn vị được bán (đặt hàng) | Đơn vị được bán (đơn đặt hàng được xác nhận) | Người mua (đặt hàng) | Người mua (Đơn đặt hàng được xác nhận) | Bán hàng cho mỗi người mua (đặt hàng) (VND) | Bán hàng cho mỗi người mua (đơn đặt hàng được xác nhận) (VND) | ...bundle/add-on columns`; `Danh sách hiệu suất` begins `Tên chương trình | Loại khuyến mãi | Thời gian diễn ra chương trình | Trạng thái`. Two posts per sheet (placed, confirmed). Promo type labels → code: `Tất cả` all, `Khuyến Mãi` / `Chương Trình Khuyến Mãi` discount, `Combo Khuyến Mãi` bundle, `Mua Kèm Deal Sốc` add_on_deal, `Flash Sale` flash_sale, `Voucher` voucher (unknown label refused).

| Source field | Unit/format | Order type | Target | Used by | Status | Test |
|---|---|---|---|---|---|---|
| `Ngày` (Biểu đồ) | `DD-MM-YYYY` | n/a | promotion_daily → row date | key | LOADED | `EXP::test_twin_promotion_programs_get_ordinals` |
| `Loại khuyến mãi` | text | n/a | → `daily.segment` (promo code), stream `promo`; or `promos.promo_type` | §3 levers: `khuyen_mai` (discount, flash_sale) and `combo` (bundle, add_on_deal) as programme-level aggregates; NOT an input of the line lever (levers are per order line) | LOADED | same |
| `Tên chương trình` | text ≤ 255 (seller's listing text) | n/a | → `promos.program_name` | §3 cross-check; §5 chi (khuyến mãi) per programme | LOADED | same |
| `Thời gian diễn ra chương trình` | `HH:MM DD-MM-YYYY - HH:MM DD-MM-YYYY` | n/a | → `promos.starts_at`, `ends_at` | programme dates | LOADED | same |
| `Trạng thái` | text ≤ 64 | n/a | → `promos.status` | programme status | LOADED | same (assert not explicit) |
| `Bán hàng (đặt hàng) (VND)` / `Bán hàng (Đơn đặt hàng được xác nhận) (VND)` | VND | placed / confirmed | → `daily.gmv` / `promos.gmv` | §3 `khuyen_mai`/`combo` GMV aggregate; the programme discount VND itself is NOT in this export | LOADED | same |
| `Đơn đặt hàng (đặt hàng)` / `Đơn đặt hàng (Đơn đặt hàng được xác nhận)` | count | placed / confirmed | → `orders` | §3 | LOADED | same |
| `Đơn vị được bán (đặt hàng)` / `(đơn đặt hàng được xác nhận)` | units | placed / confirmed | → `units` | none | LOADED | none |
| `Người mua (đặt hàng)` / `(Đơn đặt hàng được xác nhận)` | count | placed / confirmed | → `buyers` | none | LOADED | none |
| `Bán hàng cho mỗi người mua (đặt hàng) (VND)` / `(đơn đặt hàng được xác nhận) (VND)` | VND | placed / confirmed | → `daily.extra.sales_per_buyer` / `promos.extra.sales_per_buyer` | none | LOADED | none |
| `Các giao dịch gói đặt hàng (…)`, `Bán hàng của các mặt hàng chính (…)`, `Bán hàng bổ trợ (…)`, `Đơn vị của các mặt hàng chính được bán (…)`, `Đơn vị của các mặt hàng bổ sung được bán (…)`, `Bán hàng của các mặt hàng chính cho mỗi người mua (…)`, `Doanh số bán hàng của các mặt hàng chính cho mỗi người mua (…)` | | | dropped: `-` in every ORY export so far (bundle / add-on breakdown) | §3 combo split (would be needed once ORY runs Combo / Mua kèm) | NOT PARSED (dropped) | `EXP::test_twin_promotion_programs_get_ordinals` (header includes `Các giao dịch gói đặt hàng (đặt hàng)`) |

## A7. `productoverview<YYYYMMDD>-<YYYYMMDD>.xlsx`, sheet `overview` → dataset `product_overview`

Shop-level daily product funnel (no item split). Two posts (placed, confirmed); the order-independent columns repeat in both. Row key: day, stream `total`, segment `all`. Real file: `productoverview20261001-20261028.xlsx`. Parser tests: none (gateway mapping only, `FD::test_shop_and_product_overview_map_onto_the_total_stream`).

| Source field | Unit/format | Order type | Target | Used by | Status | Test |
|---|---|---|---|---|---|---|
| `Ngày` | `DD-MM-YYYY` | n/a | row date | key | LOADED | none (parser) |
| `Lượt truy cập sản phẩm` | count | n/a | → `visitors` | none (shop product visits) | LOADED | `FD::test_shop_and_product_overview_map_onto_the_total_stream` |
| `Lượt xem trang sản phẩm` | count | n/a | → `page_views` | none | LOADED | same |
| `Sản phẩm được truy cập` | count | n/a | → `extra.products_visited` | none | LOADED | none |
| `Số lượng khách thoát trang sản phẩm` | count | n/a | → `extra.bounced_visitors` | none | LOADED | none |
| `Tỷ lệ thoát Trang sản phẩm` | % | n/a | → `bounce_rate` | none | LOADED | same |
| `Lượt click từ Trang tìm kiếm` | count | n/a | → `extra.search_clicks` | §8 views (search) shop total | LOADED | none |
| `Lượt thích` | count | n/a | → `extra.likes` | none | LOADED | none |
| `Lượt truy cập sản phẩm (Thêm vào giỏ hàng)` | count | n/a | → `add_to_cart` | none | LOADED | same |
| `Sản phẩm (Thêm vào giỏ hàng)` | units | n/a | → `extra.atc_units` | none | LOADED | none |
| `Tỷ lệ chuyển đổi (theo lượt thêm vào giỏ hàng)` | % | n/a | → `extra.atc_rate` | none | LOADED | none |
| `Người mua đã đặt hàng` / `Người mua có đơn đã xác nhận` | count | placed / confirmed | → `buyers` | none | LOADED | same |
| `Sản phẩm (Đơn đã đặt)` / `Sản phẩm (Đơn đã xác nhận)` | units | placed / confirmed | → `units` | none | LOADED | same |
| `Số sản phẩm đã bán` / `Sản phẩm được duyệt` | units | placed / confirmed | → `extra.products_sold` | none | LOADED | none |
| `Doanh số (Đơn đã đặt) (VND)` / `Doanh số (Đơn đã xác nhận) (VND)` | VND | placed / confirmed | → `gmv` | §1 GMV cross-check (shop) | LOADED | same |
| `Tỷ lệ chuyển đổi (Đơn đã đặt)` / `(Đơn đã xác nhận)` | % | placed / confirmed | → `extra.conversion_rate` | none | LOADED | none |
| `Tỷ lệ chuyển đổi (Từ Đơn đã đặt thành Đơn đã xác nhận)` | % | n/a | → `extra.placed_to_confirmed_rate` | §1 placed→confirmed gap | LOADED | none |

## A8. `traffic_overview_<YYYYMMDD>_<YYYYMMDD>.xlsx`, sheets `Tất cả` / `Máy tính` / `Ứng dụng` → dataset `shop_traffic`

Shop visits by device (segment `all` / `pc` / `app`, stream `total`, no order type). A sheet with another name stops the load (UnknownColumn). Parser tests: none (`FD::test_shop_and_product_overview_map_onto_the_total_stream` covers the mapping).

| Source field | Unit/format | Order type | Target | Used by | Status | Test |
|---|---|---|---|---|---|---|
| `Ngày` | date | none | row date | key | LOADED | none |
| `Lượt xem` | count | none | → `page_views` | none | LOADED | none |
| `Số lượt xem trung bình` | count | none | → `extra.avg_page_views` | none | LOADED | none |
| `Thời gian xem trung bình` | `hh:mm:ss` → seconds | none | → `extra.avg_stay_time` | none | LOADED | none |
| `Tỉ lệ thoát trang` | % | none | → `bounce_rate` | none | LOADED | none |
| `Lượt truy cập` | count | none | → `visitors` | none | LOADED | none |
| `Số khách truy cập mới` / `Số khách truy cập hiện tại` | count | none | → `extra.new_visitors` / `extra.existing_visitors` | none | LOADED | none |
| `Người theo dõi mới` | net count (may be negative) | none | → `extra.new_followers` | none | LOADED | none |

## A9. `voucher_<YYYYMMDD>-<YYYYMMDD>.xlsx` → dataset `promotions` (type `Voucher`), sheet `Danh sách hiệu suất`

Sheets `Tổng quan` (header `Khung thời gian | Bán hàng (đặt hàng) (VND) | ... | Chi phí (Đơn đặt hàng được xác nhận) (VND)`) and `Xu hướng số liệu` (same columns with `Thời Gian` per day): NOT PARSED ("sheet not loaded (daily / summary)"); the daily voucher spend is therefore not stored. One programme row per voucher; two posts (placed, confirmed). Programme key = `(Tên mã giảm giá, starts_at, ordinal)`; there is NO voucher id in this export and the code (`Mã giảm giá`) is deliberately not read.

| Source field | Unit/format | Order type | Target | Used by | Status | Test |
|---|---|---|---|---|---|---|
| `Tên mã giảm giá` | text ≤ 255 | n/a | → `promos.program_name` | §7 voucher identity (join to connector settings by name only) | LOADED | `EXP::test_vouchers_become_promotions_without_the_code` |
| `Mã giảm giá` | text (voucher code) | n/a | dropped: not read (code kept out of the repo/db; would be the only join key to connector `voucher_id`) | §7 join to `voucher_settings` | NOT PARSED (dropped) | same (asserts the code is absent) |
| `Khung Thời Gian` | `DD-MM-YYYY - DD-MM-YYYY` or `-` | n/a | → `promos.starts_at` (00:00 of day 1), `ends_at` (23:59 last day); `-` = run dates unknown (`extra.run_dates_unknown`, starts_at = file period start) | §7 days | LOADED | same |
| `Trạng thái` | text | n/a | → `promos.status` | voucher status | LOADED | same |
| `Người tạo` | text | n/a | → `promos.extra.created_by_shopee` (bool: starts with "Shopee") | §3: Shopee-funded vouchers are not a seller cost / lever | LOADED | same |
| `Loại Voucher`, `Loại ưu đãi` | text | n/a | dropped: free text, no contract field | §7 (voucher kind would help pick comparable past vouchers) | NOT PARSED (dropped) | none (in `VOUCHER_HEADER`) |
| `Nhận` | count (claims) | n/a | → `extra.claims` | §7 context | LOADED | same |
| `Đơn đặt hàng (đặt hàng)` / `(Đơn đặt hàng được xác nhận)` | count | placed / confirmed | → `promos.orders` | §7 used orders; §3 voucher lever aggregate | LOADED | same |
| `Tỷ lệ sử dụng (đặt hàng)` / `(Đơn đặt hàng được xác nhận)` | % → fraction | placed / confirmed | → `extra.usage_rate` | **§7 u** (usage rate of comparable past vouchers; "shown") | LOADED | same (`13,33%` case) |
| `Bán hàng (đặt hàng) (VND)` / `(Đơn đặt hàng được xác nhận) (VND)` | VND | placed / confirmed | → `promos.gmv` | §3 voucher lever GMV aggregate | LOADED | same |
| `Chi phí (đặt hàng) (VND)` / `Chi phí (Đơn đặt hàng được xác nhận) (VND)` | VND (= seller-borne discount × orders) | placed / confirmed | → `extra.voucher_cost` | **§7 cost actual, §10 voucher cost**; §5 ② chi (voucher); reconciles with `voucher_settings` value × used | LOADED | same (`voucher_cost: 20000` asserted) |
| `Đơn vị được bán (đặt hàng)` / `(đơn đặt hàng được xác nhận)` | units | placed / confirmed | → `promos.units` | none | LOADED | none |
| `Người mua (đặt hàng)` / `(Đơn đặt hàng được xác nhận)` | count | placed / confirmed | → `promos.buyers` | none | LOADED | none |
| `Bán hàng cho mỗi người mua (đặt hàng) (VND)` / `(đơn đặt hàng được xác nhận) (VND)` | VND | placed / confirmed | → `extra.sales_per_buyer` | none | LOADED | none |
| `Số người xem cửa sổ thông báo (pop-up)` | count | n/a | → `extra.popup_viewers` | none | LOADED | none |
| `Tỉ lệ nhận` | % | n/a | → `extra.claim_rate` | none | LOADED | none |
| `Người theo dõi mới`, `Đóng góp của Follower` | count / VND | n/a | → `extra.new_followers`, `extra.follower_contribution` | none | LOADED | none |

## A10. `flash_sale_performance_list_<DDMMYYYY>.xlsx`, sheet `Danh sách hiệu suất` → dataset `promotions` (type `Flash Sale`)

One row per time slot; `Khung giờ` = `HH:MM-HH:MM DD-MM-YYYY` (optional ` +N` days). Posted per calendar month with period `month first day .. min(month end, export day)`. Order-type pairs as in A6.

| Source field | Unit/format | Order type | Target | Used by | Status | Test |
|---|---|---|---|---|---|---|
| `Khung giờ` | slot string | n/a | → `program_name` (`Flash Sale HH:MM-HH:MM`), `starts_at`, `ends_at` | §3 `khuyen_mai` (Flash Sale price) aggregate | LOADED | `EXP::test_flash_sale_slots_become_promotions_per_month` |
| `Lượt Nhắc Nhở` | count | n/a | → `extra.reminders` | none | LOADED | same |
| `Lượt xem sản phẩm` / `Lượt nhấp vào sản phẩm` | count | n/a | → `extra.product_views` / `extra.product_clicks` | §2 Flash Sale page traffic = "Khuyến mãi" child (here only per slot) | LOADED | same |
| `Tỷ lệ click vào sản phẩm (CTR)` | % (can exceed 100 %) | n/a | dropped: gateway rate guard | none | NOT PARSED (dropped) | same (in `FLASH_HEADER`) |
| `Bán hàng (đặt hàng)(₫)` / `Bán hàng (Đơn đặt hàng được xác nhận)(₫)` | VND (₫ sign, no space) | placed / confirmed | → `promos.gmv` | §3 | LOADED | same |
| `Đơn đặt hàng (đặt hàng)` / `Đơn đặt hàng (Đơn đặt hàng được xác nhận)` | count | placed / confirmed | → `promos.orders` | §3 | LOADED | same |
| `Đơn vị được bán (đặt hàng)` / `(đơn đặt hàng được xác nhận)`, `Người mua (…)`, `Bán hàng cho mỗi người mua (…)(₫)` | | placed / confirmed | → `units`, `buyers`, `extra.sales_per_buyer` | none | LOADED | none |

## A11. `In_Shop_Flash_Sale_Metrics_<DDMMYYYY>-<DDMMYYYY>.xlsx` → datasets `promotion_daily` (sheet `Chỉ Số`) and `promotion_period` (sheet `Tổng quan`)

Header `Thời Gian` (Chỉ Số, day) / `Khung thời gian` (Tổng quan, a `DD-MM-YYYY - DD-MM-YYYY` row), then `Bán hàng (đặt hàng)(₫) | Bán hàng (Đơn đặt hàng được xác nhận)(₫) | Đơn đặt hàng (đặt hàng) | Đơn đặt hàng (Đơn đặt hàng được xác nhận) | Người mua (đặt hàng) | Người mua (Đơn đặt hàng được xác nhận) | Tỷ lệ click vào sản phẩm (CTR) | Lượt xem sản phẩm | Lượt nhấp vào sản phẩm | Bán hàng cho mỗi người mua (đặt hàng)(₫) | Bán hàng cho mỗi người mua (đơn đặt hàng được xác nhận)(₫)`. Mapping identical to A10 (CTR dropped; views/clicks → `extra.product_views`/`extra.product_clicks`; sales → `gmv`, orders, buyers); `promo_type` fixed `Flash Sale`. Used by §3 `khuyen_mai` aggregate. Status LOADED. Test: `AFF::test_flash_sale_metrics_are_daily_rows_plus_a_period_total`, `AFF::test_keyword_and_flash_total_posts_land_in_the_period_table`.

## A12. Shop_Prize_Key_Metrics_<DDMMYYYY>-<DDMMYYYY>.xlsx (game prizes): NOT PARSED

Real files exist for 2026-03 .. 2026-06 only (`2026-10-30/raw`). No `PARSERS` entry: listed under "files not loaded". Sheets `Tổng quan` / `Chỉ Số` columns: `Khung thời gian` (`Thời Gian`) | `Tổng lượt chơi` | `Người chơi` | `Tỷ lệ tham gia Game` | `Giải thưởng được sử dụng (thứ tự đặt)` | `Giải thưởng được sử dụng (Đơn đặt hàng được xác nhận)` | `Bán hàng (đặt hàng)(₫)` | `Bán hàng (Đơn đặt hàng được xác nhận)(₫)` | `Tổng lượt xem trang` | `Giải thưởng đã được nhận` | `Chi phí giải thưởng (Đơn đặt hàng)(₫)` | `Chi phí giải thưởng (Đơn đặt hàng được xác nhận)(₫)` | `Đơn đặt hàng (đặt hàng)` | `Đơn đặt hàng (Đơn đặt hàng được xác nhận)`.
Used by: §4 "other shop marketing costs not on orders (e.g. game prizes)" = `Chi phí giải thưởng (Đơn đặt hàng được xác nhận)(₫)`, §9 `other costs × covered share`, `shop_profit(other_marketing_costs=)`. Status NOT PARSED. Test none.

## A13. Ads CPC / group reports (CSV) → dataset `ads_campaign_period`

Files: `ads_general_<YYYYMMDD>-<YYYYMMDD>.csv`, `ads_group_<…>.csv`, `Dữ+liệu-Chiến+Dịch+Nhóm-<campaign id>-<DD_MM_YYYY>-<DD_MM_YYYY>.csv`. Preamble: report title; `Tên đăng nhập` (login), `Tên gian hàng`, `Mã Người bán`, `Thời gian tạo báo cáo`, `Khoảng thời gian` (`DD/MM/YYYY - DD/MM/YYYY`, window ≤ 100 days; real windows ~ 3 months, OVERLAPPING between exports), then the header row starting `Thứ tự`. Period post, `order_type = placed` always, stream `ads` (overlay), `segment = 'c' + sha1(campaign_name|ordinal)[:12]`, `platform_source = campaign name[:64]`, `item_id` = `Mã sản phẩm` (empty for shop-level campaign rows). Group reports: the campaign's own row is the sum of its product rows, so only the product rows are posted (a campaign row is posted only if no product row follows = "campaign with no product"). CSV numbers are plain (`1234.56`, `4.25%`).

| Source field | Unit/format | Order type | Target | Used by | Status | Test |
|---|---|---|---|---|---|---|
| `Thứ tự` | row no. | n/a | not posted | n/a | NOT PARSED (dropped: ordering) | `EXP::test_cpc_ads_report_is_one_period_post_never_cut_into_days` |
| `Tên Dịch vụ Hiển thị` (CPC) / `Chiến dịch / Tên sản phẩm` (group) | text ≤ 255 | n/a | → `campaign_name` → `period.platform_source`, hashed `segment` | §4 campaign identity; "QC không gắn sản phẩm" bucket | LOADED | `EXP::test_cpc_ads_report_is_one_period_post_never_cut_into_days`, `EXP::test_group_campaign_report_posts_product_rows_not_the_campaign_total` |
| `Mã sản phẩm` | digits or `-` | n/a | → `period.item_id` (`''` for shop-level) | **§4 ad spend per product**; unattributed = rows with `item_id ''` | LOADED | same |
| `Trạng thái` / `Trạng thái chiến dịch` | `Đang diễn ra` / other | n/a | → `extra.running` (bool) | §8 ads_pause | LOADED | same (`running` asserted) |
| `Loại Dịch vụ Hiển thị` | text (ad type) | n/a | dropped (read, not posted) | §8 ads purpose: ad type would seed `hien_thi` / `chuyen_doi` (purpose is set by seller/team in `ad_campaign_purposes`) | NOT PARSED (dropped) | none |
| `Nội dung Dịch vụ Hiển thị` | text (listing text) | n/a | dropped | none | NOT PARSED (dropped) | none |
| `Phương thức đấu thầu`, `Vị trí` | text | n/a | dropped | §8 ads_roas_target context | NOT PARSED (dropped) | `EXP::test_cpc_ads_report_is_one_period_post_never_cut_into_days` (header only) |
| `Ngày bắt đầu`, `Ngày kết thúc` | `DD/MM/YYYY hh:mm:ss` | n/a | dropped (campaign run dates) | §8 ra_mat launch end date | NOT PARSED (dropped) | header only |
| `Số lượt xem` | count | placed | → `impressions` | §2 ads overlay views | LOADED | same |
| `Số lượt click` | count | placed | → `clicks` | §2 ads overlay | LOADED | same |
| `Tỷ Lệ Click` | % → fraction (Ratio) | placed | → `ctr` | §8 CTR | LOADED | same (`0.025`) |
| `Thêm vào giỏ hàng` / `Add to Cart` | count | placed | → `add_to_cart` | none | LOADED | `FD::test_ad_campaign_totals_land_in_the_period_table_as_ads_overlay_rows` (dataset) |
| `Tỷ lệ Thêm vào giỏ hàng` / `Add to Cart Rate` | % | placed | → `extra.add_to_cart_rate` | none | LOADED | none |
| `Lượt chuyển đổi` | count (broad conversions) | placed | → `orders` | §4 ad-attributed orders (broad) | LOADED | `EXP::test_cpc_ads_report_is_one_period_post_never_cut_into_days` |
| `Lượt chuyển đổi trực tiếp` | count | placed | → `extra.direct_conversions` | §10 direct orders | LOADED | same |
| `Tỷ lệ chuyển đổi`, `Tỷ lệ chuyển đổi trực tiếp` | % | placed | → `extra.conversion_rate`, `extra.direct_conversion_rate` | none | LOADED | none |
| `Chi phí cho mỗi lượt chuyển đổi`, `Chi phí cho mỗi lượt chuyển đổi trực tiếp` | VND | placed | → `extra.cost_per_conversion`, `extra.direct_cost_per_conversion` | none | LOADED | none |
| `Sản phẩm đã bán` / `Sản phẩm đã bán trực tiếp` | units | placed | → `units` / `extra.direct_units_sold` | none | LOADED | same / none |
| `Doanh số` | VND (**broad**: advertised product AND other products bought within 7 days of the click) | placed | → `gmv` | **§4 ad GMV broad; §10 ROAS broad (shop-level ads); `AdsFigures.gmv`** | LOADED | same |
| `Doanh số trực tiếp` | VND (advertised product only) | placed | → `extra.direct_sales` | **§4 direct ad GMV; §10 break-even compares ROAS trực tiếp; `AdsFigures.direct_gmv`** | LOADED | `FD::test_ad_campaign_totals_land_in_the_period_table_as_ads_overlay_rows` (dataset) |
| `Chi phí` | VND | placed | → `extra.ads_expense` | **§4 product ad spend (product rows) and total ad spend (Σ all rows); §5 chi** | LOADED | `EXP::test_cpc_ads_report_is_one_period_post_never_cut_into_days` (`ads_expense` asserted) |
| `ROAS`, `ROAS trực tiếp` | ratio | placed | → `extra.ads_roas`, `extra.direct_roas` | §10 (derived by code from spend and GMV) | LOADED | `ads_roas` asserted; `direct_roas` none |
| `ACOS`, `ACOS trực tiếp` | fraction | placed | → `extra.acos`, `extra.direct_acos` | none | LOADED | `acos` asserted |
| `Lượt xem Sản phẩm`, `Lượt clicks Sản phẩm`, `Tỷ lệ Click Sản phẩm` | count / count / % | placed | → `extra.product_views`, `extra.product_clicks`, `extra.product_ctr` | none | LOADED | none |
| `Voucher Amount`, `Vouchered Sales` | VND | placed | → `extra.voucher_amount`, `extra.voucher_sales` | §7/§5 voucher spend attributed to ads (overlap with voucher export, do not add) | LOADED | none |

## A14. `ads_keyword_<YYYYMMDD>-<YYYYMMDD>.csv` → dataset `ads_keyword_period`

Same preamble and metric columns as A13 plus `Từ khóa / Vị trí` and `Loại từ khóa`. One row per campaign × product × keyword, stream `ads`, `segment = 'k' + sha1(campaign|keyword|type|ordinal)[:12]`, `platform_source = "campaign › keyword"` (30 + 30 chars). A keyword cell equal to "quảng cáo tự động" becomes `auto_placement = true` with no keyword; `-` = no keyword.

| Source field | Unit/format | Order type | Target | Used by | Status | Test |
|---|---|---|---|---|---|---|
| `Từ khóa / Vị trí` | text ≤ 255 | placed | → `period.platform_source` (packed), hashed `segment`; the keyword text itself lives only in the raw copy | §8 `keyword`, `ads_budget` cards; keyword table (ADR-119) | LOADED | `AFF::test_keyword_rows_map_to_distinct_ads_overlay_rows`, `AFF::test_keyword_rows_without_a_keyword_are_kept` |
| `Loại từ khóa` | text | placed | hashed into `segment` only | keyword type (broad / exact) | LOADED | same |
| all A13 metric columns | as A13 | placed | as A13 (same `_ADS_COLUMNS` table) | per-keyword ad spend / ROAS (not in P90 §) | LOADED | same |
| `Thứ tự`, `Tên Dịch vụ Hiển thị`, `Mã sản phẩm`, `Trạng thái`, … | | | as A13 | | LOADED / dropped as A13 | same |

Not parsed siblings: `Dữ+liệu+Dịch+vụ+Hiển+thị+Sản+Phẩm-<product ad id>-<DD_MM_YYYY>-<DD_MM_YYYY>.csv` (2 real files, one per product ad: `Báo cáo Sản phẩm - Shopee Việt Nam`, preamble lines `Tên đăng nhập`, `Tên gian hàng`, `Mã Người bán`, `Tên Dịch vụ Hiển thị`, `Mã sản phẩm`, `Thời gian tạo báo cáo`, `Khoảng thời gian`, then a bid-mode line `Giá thầu Tự động`, then the header `Thứ tự | Từ khóa / Vị trí | Loại từ khóa | Lệnh tìm kiếm | Phương thức đấu thầu | Vị trí | Số lượt xem | Số lượt click | Tỷ Lệ Click | Thêm vào giỏ hàng | Tỷ lệ Thêm vào giỏ hàng | Lượt chuyển đổi | Lượt chuyển đổi trực tiếp | Tỷ lệ chuyển đổi | Tỷ lệ chuyển đổi trực tiếp | Chi phí cho mỗi lượt chuyển đổi | Chi phí cho mỗi lượt chuyển đổi trực tiếp | Sản phẩm đã bán | Sản phẩm đã bán trực tiếp | Doanh số | Doanh số trực tiếp | Chi phí | Thứ hạng trung bình | ROAS | ROAS trực tiếp | ACOS | ACOS trực tiếp | Voucher Amount | Vouchered Sales`). No `PARSERS` entry, so skipped; it also has two columns `Lệnh tìm kiếm` and `Thứ hạng trung bình` absent from `ADS_COLUMNS`, so adding the pattern without extending the table raises UnknownColumn. Status NOT PARSED. Test none.

## A15. Affiliate dashboard exports (CSV) → stream `affiliate`, period rows, `order_type none`

Products: `affiliate_product_<YYYYMM>.csv` (period = that month, clipped to the file's modified day) and `ProductPerformance_<ts>.csv` (no period in the file; needs `--window`, ≤ 31 days). Same column set, dataset `affiliate_product_period`, `platform_source = affiliate_product`, `item_id` = `Mã sản phẩm`.

| Source field | Unit/format | Order type | Target | Used by | Status | Test |
|---|---|---|---|---|---|---|
| `Mã sản phẩm` (`Item id` in older files) | digits | none | → `period.item_id` | §4 commission per product, §8 `affiliate_commission` | LOADED | `AFF::test_affiliate_product_month_becomes_a_period_post_for_that_month` |
| `Tên sản phẩm` (`Item Name`) | text | none | dropped (names come from the catalog) | n/a | NOT PARSED (dropped) | same |
| `Giá(₫)` (`Price(₫)`) | VND | none | → `extra.price` | none | LOADED | same |
| `Doanh thu(₫)` (`Sales(₫)`) | VND | none | → `gmv` | §2 `lien_ket` cross-check (program's own estimate, not the shop-stats affiliate source) | LOADED | same |
| `Sản phẩm đã bán` (`Item Sold`) | units | none | → `units` | none | LOADED | same |
| `Số đơn hàng` (`Orders`) | count | none | → `orders` | §8 | LOADED | same |
| `Hoa hồng ước tính` (**no ₫**) | **click count** (assumed equal to `Clicks` of `affiliate_product`; the header is misleading) | none | → `clicks` | none | LOADED (assumption; not verifiable from the file) | `AFF::test_exports_without_a_period_need_a_window` |
| `Hoa hồng ước tính(₫)` (`Est.Commission(₫)`) | VND | none | → `extra.est_commission` | **§4 affiliate commission, aggregate estimate** (the per-line commission is the order report, A18) ; §5 chi | LOADED | same |
| `ROI` | ratio | none | → `extra.roi` | §8 | LOADED | same |
| `Tất cả người mua` (`Total Buyers`) | count | none | → `buyers` | none | LOADED | same |
| `Người mua mới` (`New Buyers`) | count | none | → `extra.new_buyers` | none | LOADED | same |

`Open Campaign Analytics_<ts>.csv` → `affiliate_open_campaign_period` (needs `--window`; `platform_source open_campaign`):

| Source field | Unit/format | Order type | Target | Used by | Status | Test |
|---|---|---|---|---|---|---|
| `Tên Sản phẩm` | text | none | dropped | n/a | NOT PARSED (dropped) | `AFF::test_exports_without_a_period_need_a_window` |
| `Mã Sản phẩm` | digits | none | → `item_id` | §8 `affiliate_target_campaign` | LOADED | same |
| `KOLs` | count | none | → `extra.kols` | §8 | LOADED | same |
| `Doanh thu(₫)` | VND | none | → `gmv` | §2 | LOADED | same |
| `Sản phẩm đã bán` | units | none | → `units` | none | LOADED | same |
| `Hoa hồng ước tính(₫)` | VND | none | → `extra.est_commission` | §4 | LOADED | same |

`AMSAffiliatePerformance_<ts>.csv` → `affiliate_partner_period` (needs `--window`; one row per creator, `segment = 'a' + sha1(Affiliate ID)[:12]`, `platform_source` = public handle, the id itself is not stored):

| Source field | Unit/format | Order type | Target | Used by | Status | Test |
|---|---|---|---|---|---|---|
| `Affiliate ID` | digits | none | → hashed `segment` only | KOL ranking key (§8 liên kết) | LOADED | `AFF::test_exports_without_a_period_need_a_window`, `AFF::test_affiliate_posts_land_in_the_period_table_as_affiliate_rows` |
| `Affiliate Username` (else `Affiliate Name`) | public creator handle ≤ 120 | none | → `platform_source` | KOL ranking label | LOADED | same |
| `Affiliate Name` (when a username exists) | text | none | dropped (duplicate of the handle) | n/a | NOT PARSED (dropped) | none |
| `Sales(₫)`, `Item Sold`, `Orders`, `Clicks`, `Total Buyers` | VND / units / count | none | → `gmv`, `units`, `orders`, `clicks`, `buyers` | §8 liên kết share | LOADED | same |
| `Est.Commission(₫)`, `ROI`, `New Buyers` | VND / ratio / count | none | → `extra.est_commission`, `extra.roi`, `extra.new_buyers` | §4 commission, §8 | LOADED | same |

`target_campaign_<ts>.csv` → `affiliate_campaign_terms` (one-day snapshot = the `Date` line; `Type Commission List` preamble; one row per campaign × product):

| Source field | Unit/format | Order type | Target | Used by | Status | Test |
|---|---|---|---|---|---|---|
| `Tên chiến dịch` | text ≤ 255 | none | → `platform_source` | §8 `affiliate_target_campaign` | LOADED | `AFF::test_campaign_terms_are_one_snapshot_day_with_the_kol_count` |
| `ID của chiến dịch` | digits | none | → `extra.campaign_id`, hashed `segment` | key | LOADED | same |
| `Thời gian chạy` | `YYYY/MM/DD hh:mm - YYYY/MM/DD hh:mm` or `No limit` | none | → `extra.starts_ymd`, `extra.ends_ymd` (YYYYMMDD numbers) | campaign window | LOADED | same |
| `Trạng thái` | `Ongoing` / other | none | → `extra.running` | §8 | LOADED | same |
| `ID sản phẩm` | digits | none | → `item_id` | **§4 commission rate per product (affiliate_rate input)** | LOADED | same |
| `Tên sản phẩm` | text | none | dropped | n/a | NOT PARSED (dropped) | same |
| `Tỉ lệ hoa hồng` | % → fraction | none | → `extra.commission_rate` | **§4 commission %; §6 hoa hồng % in the operating floor** (the rate for the product's campaign; NOT the per-order commission) | LOADED | same |
| `Tên tài khoản KOL` | `KOL cụ thể[N]` | none | → `extra.targeted_kols` (N only; names not stored) | §8 | LOADED | same |

`ValidationBill<ts>.csv` → `affiliate_bill_period` (one post per bill month; period = month first day .. min(last, export day); `segment = 'b' + sha1(Mã đối soát)[:12]`):

| Source field | Unit/format | Order type | Target | Used by | Status | Test |
|---|---|---|---|---|---|---|
| `Mã đối soát` | text | none | hashed `segment` | key | LOADED | `AFF::test_each_bill_month_is_its_own_post_and_the_formula_quote_is_stripped` |
| `Tháng đối soát` | `YYYY-MM` | none | → period | month | LOADED | same |
| `Hoa hồng hằng tháng(₫)` | VND | none | → `extra.commission` | **§4 commission ACTUAL per month** (settlement) | LOADED | same |
| `Số tiền thuế(₫)` | VND | none | → `extra.tax` | §4 | LOADED | same |
| `Chi phí hàng tháng(₫)` | VND | none | → `extra.cost` | §4 | LOADED | same |
| `Trạng thái khấu trừ` | `Completed` / other | none | → `extra.deduction_completed` | none | LOADED | same |
| `Tổng khấu trừ(₫)`, `Số dư ví của chương trình Tăng đơn cùng KOL bị cấn trừ(₫)`, `Tổng số tiền chờ xử lý(₫)` | VND | none | → `extra.total_deduction`, `extra.wallet_offset`, `extra.pending_amount` | none | LOADED | same |

## A16. `SellerConversionReport_<ts>.csv` (affiliate ORDER LINES) → RESERVED dataset `affiliate_order_lines`

The only order-line-grained file we can parse today, and it covers AFFILIATE orders only. The order id is replaced by `order_ref = HMAC-SHA256(key, "shopee-order|" + id.upper())[:32]` inside the parser (key `JULI_ORDER_REF_KEY`, else random per run so refs are run-local). Rows are cut by order month, ≤ 1 000 rows per post, validated against `ShopeeAffiliateOrderLineRow`, never sent (gateway 404). Intended home: `shopee_order_lines` (migration 112, no mapper written). Any header matching the buyer regex (`người mua`, `khách hàng`, `người nhận`, `điện thoại`, `địa chỉ`, `email`, `buyer`, `phone`, `address`, `recipient`, `customer`, `username người`) is dropped unread; any other unknown header stops the load.

| Source field | Unit/format | Order type | Target (reserved row field → intended `shopee_order_lines` column) | Used by | Status | Test |
|---|---|---|---|---|---|---|
| `Mã đơn hàng` | order id (text) | n/a | hashed → `order_ref` (the raw id never leaves the parser) | key for every §3/§4 line join | RESERVED | `AFF::test_order_lines_are_reserved_with_a_keyed_order_ref_and_no_raw_id` |
| (derived) | n/a | n/a | `line_no` (place among same order+item+model) → `line_no` | key | RESERVED | same |
| `Trạng thái đơn hàng` | text ≤ 64 | the report's own status | → `status` | **§4 order status** (delivered / cancelled / refund); the report's vocabulary has never been mapped to `OrderStatus` | RESERVED | same |
| `Trạng thái gian lận` | `Hợp lệ` / other | n/a | → `valid` bool (no column in `shopee_order_lines`) | affiliate validity | RESERVED | same |
| `Thời gian đặt hàng` | `YYYY-MM-DD hh:mm:ss` | n/a | → `ordered_at` | order date (fee formula version; window) | RESERVED | same |
| `Thời gian đơn hàng hoàn thành` | datetime | n/a | → `completed_at` (no column) | delivery date (fees only on delivered) | RESERVED | none |
| `Thời gian chuyển đổi hoàn tất` | datetime | n/a | → `conversion_at` (no column) | none | RESERVED | none |
| `Mã sản phẩm` | digits | n/a | → `item_id` | §4 product join | RESERVED | same |
| `Model id` | digits | n/a | → `model_id` → `variation_id` | §4 per-SKU join | RESERVED | same |
| `Giá(₫)` | VND (unit price? meaning not confirmed) | n/a | → `price` → `deal_price` or `original_price` (undecided) | §3/§4 deal price | RESERVED | same |
| `Số lượng` | count | n/a | → `qty` | §4 | RESERVED | same |
| `Giá trị đặt hàng(₫)` | VND (line or order scope unconfirmed) | n/a | → `order_value` (no column) | §1 order-line GMV | RESERVED | none |
| `Số tiền hoàn(₫)` | VND | n/a | → `refund_amount` (no column) | §4 refund | RESERVED | none |
| `Loại đơn hàng` | text | n/a | → `order_kind` | none | RESERVED | none |
| `Tên đối tác`, `Tài khoản Tiếp thị liên kết`, `MCN được liên kết`, `Đối tác chiến dịch`, `Mã hoa hồng`, `Loại chiến dịch`, `Kênh` | creator public handles / codes ≤ 120 | n/a | → `partner_name`, `affiliate_account`, `mcn`, `campaign_partner`, `commission_code`, `campaign_type`, `channel` (no columns; `traffic_source` could hold `channel`) | §8 liên kết; line is `affiliate = true` | RESERVED | none |
| `Hoa hồng Xtra trên sản phẩm(₫)` and the 8 further `Hoa hồng Xtra ...` / `Tỷ lệ hoa hồng Xtra ...` columns | VND / % | n/a | → `xtra_*` fields (no columns) | **§4 affiliate commission per line**: the report has NO base commission column; which of `Chi phí(₫)` / `Hoa hồng Xtra …` equals `shopee_order_lines.commission` is undecided | RESERVED | none |
| `Chi phí(₫)` | VND | n/a | → `cost` (could map to `commission`) | **§4 commission** (candidate) | RESERVED | none |
| `Trạng thái khấu trừ`, `Phương pháp khấu trừ`, `Thời gian khấu trừ` | text / datetime | n/a | → `deduction_status`, `deduction_method`, `deducted_at` | none | RESERVED | none |
| `Tên sản phẩm`, `Ghi chú sản phẩm`, `Mã khuyến mãi` | text | n/a | dropped (names from catalog; free text; promo code not mapped) | `Mã khuyến mãi` could mark the programme (§3 lever) | NOT PARSED (dropped) | none |
| `L1 Ngành hàng toàn cầu`, `L2 Ngành hàng toàn cầu`, `L3 Ngành hàng toàn cầu` | category names | n/a | dropped (set to `None` in `CONVERSION_COLUMNS`) | **§10a fixed-fee rate by category** (the contract names this report as the category source) | NOT PARSED (dropped) | none |

## A17. `ops_log_*.csv` (ad change history) → RESERVED dataset `ads_change_log`

Preamble (real): report title, `Tên gian hàng`, `Mã Người bán`, `Thời gian tạo báo cáo`, `Khoảng thời gian`, `ID chiến dịch` (+ `Mã sản phẩm` for the product-level logs), then header `Thời gian cập nhật | Người thao tác | Nền tảng | Loại sự kiện | Chi tiết`. Parsed, validated, not stored (no table, no migration). Fields: `campaign_id` (preamble), `item_id` (preamble), `occurred_at` ← `Thời gian cập nhật`, `actor_kind` (system if the actor starts with "hệ thống") + `actor` ← `Người thao tác`, `surface` ← `Nền tảng`, `event_type` ← `Loại sự kiện`, `detail` ← `Chi tiết` (≤ 500), `budget_from/budget_to` parsed from `Ngân sách hàng ngày: ₫a -> ₫b`, `products_from/products_to` from `số lượng sản phẩm …: a -> b`. Used by: nothing in P90; context for §8 `ads_roas_target` / `ads_pause` cards. Status RESERVED. Test: `AFF::test_the_ad_change_log_is_reserved_not_posted`.

## A18. Files on hand that no parser reads

| File (real examples) | Sheets / columns | Would feed | Status | Test |
|---|---|---|---|---|
| `sales_composition_<YYYYMMDD>-<YYYYMMDD>.xlsx` (11 files, Nov 2025-Sep 2026) | sheets `Đặt hàng`, `Đơn đặt hàng xác nhận`; cols `Ngành Hàng | Ngành Hàng Con | Người mua | Doanh số (VND) | % Doanh Số | Tỷ lệ chuyển đổi` | shop sales by category: §10a (which fixed-fee rate applies to what share of sales); NOT per item | NOT PARSED (no `PARSERS` entry) | `EXP::test_files_the_loader_does_not_know_are_never_opened` (listed as skipped) |
| `sales_overview_<YYYYMMDD>-<YYYYMMDD>.xlsx` (1 file, Sep 2026) | sheet `Tổng Quan về Doanh Số`; cols `Ngày | Lượt truy cập | Khách đã đặt hàng, chưa thanh toán | Sản phẩm khách chưa thanh toán | Tất cả các đơn | Doanh số (Đơn đã đặt) (VND) | Tỷ lệ chuyển đổi (Từ Lượt truy cập thành Đơn được đặt) | Người mua có đơn đã xác nhận | Sản phẩm (Đơn đã xác nhận) | Đơn đã xác nhận | Doanh số (Đơn đã xác nhận) (VND) | Doanh số trên mỗi Người mua (Đơn đã xác nhận) (VND) | Tỷ lệ chuyển đổi | Tỷ lệ chuyển đổi (Từ Đơn đã đặt thành Đơn đã xác nhận)` | unpaid-cart funnel (`Khách đã đặt hàng, chưa thanh toán`); the rest duplicates `shop_overview` | NOT PARSED | none |
| `Shop_Prize_Key_Metrics_*.xlsx` | see A12 | §4 other marketing costs | NOT PARSED | none |
| `Dữ+liệu+Dịch+vụ+Hiển+thị+Sản+Phẩm-*.csv` | see A14 | per-product keyword ad rows | NOT PARSED | none |
| `productlist_p1.json`, `productlist_p2.json` | a browser text dump: JSON array of `{type: "text", text: "..."}` (90 291 and 208 characters), not Seller Centre JSON | product list (replaced by the connector reader B5) | NOT PARSED | none |
| `shop-stats` summary sheets `Nguồn truy cập cho Đơn hàng...`, `Nguồn lưu lượng truy cập (đ...`, `Nguồn truy cập từ Đơn hàng ...`; `discount` `Tổng quan`; `voucher` `Tổng quan` / `Xu hướng số liệu` | period summaries and daily voucher trend (`Thời Gian`, `Chi phí (…) (VND)`) | daily voucher cost (§7 spend per day) | NOT PARSED (sheet not loaded) | `EXP::test_vouchers_become_promotions_without_the_code` (asserts the `Tổng quan` note) |

## A19. Seller Centre files we do NOT hold yet (NOT AVAILABLE), and what they must carry

None of these has a parser, a header capture or a test. Header names must be captured from a real download before writing any parser (names only; never values). `parse.py` treats the order export and `Quản lý đánh giá` as buyer-bearing files that are never opened (`Orders_202611.csv` and `Order.all.*.xlsx` appear in the skip tests). The labels below are SEMANTIC names from the contract; the Vietnamese header strings are TBD.

| Needed file | Where in Seller Centre | Fields the contract needs from it | Status | Test |
|---|---|---|---|---|
| Order export (Đơn hàng › Xuất), then "Lịch sử Xuất Báo cáo"; recon: ≈ 5 660 orders visible; path D = trigger the export, collect the file, strip PII in the browser | Bán hàng › Đơn hàng | per order line: order id (to be hashed), order time, status (+ delivered time), item id, model id, SKU, qty, original price, deal price (after seller promotion), seller-promotion amount, shop voucher amount, Shopee voucher amount, combo / Mua kèm discount, bank promotion, buyer-paid shipping, total buyer paid, voucher code, (fees if present) | NOT AVAILABLE | `EXP::test_files_the_loader_does_not_know_are_never_opened`, `EXP::test_buyer_level_and_unlisted_reports_are_never_opened` (never opened) |
| Income export (Tài chính › Doanh thu) | Tài chính › Doanh thu | per order: commission fee, fixed fee (phí cố định), service fee, transaction fee (phí xử lý giao dịch), infrastructure fee, payment fee, voucher/Freeship Xtra fee, payout amount, release date, refund amounts | NOT AVAILABLE: the ORY sub-account sidebar has no Tài chính › Doanh thu (Hạnh must grant the finance section) | none |
| Returns / refunds ("Trả hàng/Hoàn tiền") list | Bán hàng › Trả hàng/Hoàn tiền | per order: return reason class ("Hoàn tiền ngay" vs "Chưa nhận được hàng"), accepted/not, refund amount (decides `OrderStatus`) | NOT AVAILABLE | none |
| Fee schedule: "Shopee non-Mall_ Phi Co Dinh tu 23.05.2026.pdf" (47 pages), articles 2150 / 2139 / 25223 | Học viện Shopee | fixed-fee % by L1›L2›L3 category (§10a); 6 % transaction; 3.000đ infrastructure | have the PDF (outside the repo); NOT PARSED | `PRF::test_fee_components_bases_and_caps`, `P90::test_non_mall_formula_bases_once_per_order` (formula only, rates injected) |
| Category per item (L1/L2/L3 or category id) | product detail page / category-tree endpoint | to pick the fixed-fee rate per item | NOT AVAILABLE from the product list (recon: "Missing here: rating, category path"); only the dropped affiliate report columns (A16) carry it | none |
| Ratings (`Quản lý đánh giá`) | Chăm sóc khách hàng | rating, rating count (product header) | NOT AVAILABLE (buyer-bearing export never opened; not in the product-list endpoint) | none |

# B. Juli Connector endpoints (`apps/connector/src`)

Common to all: Chrome extension on `banhang.shopee.vn`, the seller's own session, read-only, ≥ 2 s + jitter between requests (`MIN_REQUEST_GAP_MS`), stop on CAPTCHA/login. Post body: `source = "extension"` (rank 2 = file), `source_version` = extension version, `captured_at`, `period {start = end = mapped.date, granularity}`, `order_type`, optional `platform_shop_id`, `rows` (≤ 400 per post, `MAX_ROWS_PER_POST`). Numbers are read as JSON numbers (or numeric strings); a negative/non-numeric value is dropped, not posted. Rates must be fractions; a "percentage where a fraction is expected" is drift (dataset stopped, nothing posted). Strings the contract does not name never leave the browser. Gate: `READERS_ACTIVE` all true, `PILOT_SHOP_IDS = ["*"]` (open item P90 freeze: must become ORY's shop id before 0.3.0), `ITEM_READERS_ACTIVE = false`, `HELD_DATASETS = {item_snapshot, shop_health_daily}`. `MONEY_DIVISOR = {products: 1, ads: 1, vouchers: 1}` is UNVERIFIED (money might arrive as VND × 100 000): ceilings `MAX_PLAUSIBLE_PRICE_VND` 500 000 000 and `MAX_PLAUSIBLE_AD_VND` 5 000 000 000 turn a wrong scale into drift. `LOADED*` below = mapper and gateway live, never run live.

## B1. `GET /api/mydata/v1/product/traffic/overview/` (daily sync + 30-day backfill) → dataset `traffic_overview`

Active sync asks for yesterday only, `order_type=confirmed` only (placed/paid are never requested). Response `{code:0,result:{overview, product_card, live, video, affiliate, paid_ads}}`; each block has `total` (L1) and an optional `breakdown` (L2). Only `total` is mapped (one row per L1 source, source enum = key); `breakdown` is NOT mapped (only `extra.l2_breakdown_count`), so **no L2 child (Trang shop / Cửa hàng, Tìm kiếm, Đề xuất, Khuyến mãi …) comes from the connector**. `overview` key tolerated, not mapped.

| Source field (JSON path) | Unit/format | Order type | Target | Used by | Status | Test |
|---|---|---|---|---|---|---|
| `result.<key>.total.source` | enum `psd_label_*` (must equal the key) | confirmed (URL `order_type`, default confirmed) | → row `source` → stream | §2 flow identity | LOADED* | `C-MAP::maps one row per L1 source, ratios to extra, comparisons dropped`, `C-CT::traffic_overview` |
| `…total.sales` | VND | confirmed | → `gmv` | §2 GMV per flow (L1 only) | LOADED* | same |
| `…total.orders`, `…units`, `…buyers` | count | confirmed | → `orders`, `units`, `buyers` | §2, §5 | LOADED* | same |
| `…total.product_impressions` (product_card, paid_ads) | count | confirmed | → `impressions` | §2 views `the_san_pham` incl. Trang shop | LOADED* | same |
| `…total.live_views` / `video_views` / `content_views` | count | confirmed | → `impressions` (live / video / affiliate) | §2 Live / Video / liên kết views (session / video / content definitions) | LOADED* | same |
| `…total.live_viewers` / `video_viewers` / `content_viewers` | count | confirmed | → `extra.*` | none | LOADED* | same |
| `…total.product_clicks`, `unique_product_clicks` | count | confirmed | → `clicks`, `extra.unique_product_clicks` | §2 | LOADED* | same |
| `…total.sales_per_order`, `ctr`, `product_clicks_to_orders_rate` | VND / fraction | confirmed | → `extra.sales_per_order`; `ctr` → `ctr` (drift if > 1); `product_clicks_to_orders_rate` → `extra` | §2 (derived by code anyway) | LOADED* | `C-MAP::treats a percentage where a fraction is expected as drift` |
| `…total.unique_product_impressions` | count | confirmed | → `extra.unique_product_impressions` | none | LOADED* | same |
| `…total.sales_ratio`, `orders_ratio`, `product_clicks_ratio`, `content_views_ratio`, `video_views_ratio`, `live_views_ratio`, `product_impressions_ratio` | fraction (share) | confirmed | → `extra.<name>` | none | LOADED* | same |
| `…total.<metric>_pct_diff` | comparison vs previous period | confirmed | dropped: derivable | none | NOT PARSED (dropped) | same |
| `paid_ads.total.ads_expense`, `ads_roas`, `conversion`, `live_views`, `video_views` | VND / ratio / fraction | confirmed | → `extra.ads_expense`, `extra.ads_roas`, `extra.conversion` | §4 total ad spend (shop-level, daily) | LOADED* | same |
| `…breakdown[]` (all L2 children) | | | not mapped (count only) | **§2 `trang_shop` and the Thẻ sản phẩm children (Tìm kiếm, Đề xuất, Giỏ hàng, Đơn mua, Khuyến mãi, Khác)** | NOT PARSED | none |
| unexpected key / missing required (`sales`, `orders`, `product_impressions`, `product_clicks` for product_card; `sales`, `orders` for live/video/affiliate; `sales`, `orders`, `ads_expense` for paid_ads) | | | drift → dataset stopped for this version | all | LOADED* | `C-MAP::reports an unexpected field as drift`, `C-MAP::reports a missing field, a new source key and a renamed enum as drift` |

## B2. `GET /api/mydata/traffic/dashboard/overview/` → dataset `shop_traffic`

Template-replayed for yesterday (the page's last call must be `period=yesterday`) or `period=day&dt=YYYYMMDD` in backfill. Response `result.data.{all,pc,app}` + `data_ready`.

| Source field | Unit/format | Order type | Target | Used by | Status | Test |
|---|---|---|---|---|---|---|
| `result.data.<device>.visitors`, `page_views` | count | none | → `visitors`, `page_views` (segment = device) | none | LOADED* | `C-MAP::maps one row per device; hh:mm:ss to seconds; '-' dropped`, `C-CT::shop_traffic` |
| `…avg_page_views`, `new_visitors`, `existing_visitors`, `new_followers` | count | none | → `extra.*` | none | LOADED* | same |
| `…avg_stay_time` | `hh:mm:ss` → seconds | none | → `extra.avg_stay_time` | none | LOADED* | same |
| `…bounce_rate` | fraction | none | → `bounce_rate` | none | LOADED* | same |
| `…<field>_pct_diff` | comparison | none | dropped | none | NOT PARSED (dropped) | same |

## B3. `GET /api/mydata/v1/product/traffic/item-list/` → dataset `item_by_source` (DAILY, per item × L1)

`ITEM_READERS_ACTIVE = false`: the active sync and backfill never request it; only a response the page itself loads is mapped (passive capture). Item rows are PROVISIONAL (recon saw empty lists). Mapped: `result.item[]` with id from `item_id | itemid | product_id | id`, name from `item_name | name | product_name`; known metric names (`sales, orders, units, buyers, product_impressions, unique_product_impressions, product_clicks, unique_product_clicks, ctr, product_clicks_to_orders_rate, conversion, sales_per_order, live_*, video_*, content_*, ads_expense, ads_roas`) → same targets as B1 at item level; other fields → `extra`. Used by: would give the daily per-product flow split (§2) that the monthly file (A3) gives per period. Status NOT PARSED in the active sync (mapper exists, endpoint inactive). Test: `C-MAP::maps item × source rows with known metric names, the rest to extra`, `C-SY::asks for yesterday's shop-level calls; item readers wait for D31.6`.

## B4. `GET /api/mydata/v4/product/performance/` → dataset `item_performance` (DAILY, per item, all sources)

Inactive like B3. `result.items[]`; order-type prefixed fields (`confirmed_sales` …) are reduced to the requested type; names map `sales|gmv → sales`, `orders|order → orders`, `units|unit_num → units`, `buyers`, `product_impressions|impressions`, `product_clicks|clicks`, `ctr`, `uv|product_visitors → uv`, `pv`, `atc_uv`, `atc_unit_num → atc_units`, `atc_rate`, `conversion_rate|order_conversion_rate`; the rest → `extra`. Used by: daily per-product GMV (cross-check against order lines, §1). Status NOT PARSED (inactive). Test: `C-MAP::strips the order-type prefix on item performance and keeps other order types aside`, `C-MAP::an item without an id is drift`.

## B5. `GET /api/v3/opt/mpsku/list/v2/get_product_list` (`page_number`, `page_size`, `list_type`, `need_ads`; total 114 items) → dataset `item_catalog` → `platform_items`

Paged by the page's own `page_size` until `total`; one post (period granularity, one-day snapshot) of item rows and model rows.

| Source field (JSON path) | Unit/format | Order type | Target | Used by | Status | Test |
|---|---|---|---|---|---|---|
| `product.id` | digits | none | → `items.item_id` | product header id | LOADED* | `C-RM::maps items and models to item_catalog (platform_items fields)`, `RD::test_item_catalog_describes_items_and_variations` |
| `product.name` | text ≤ 500 | none | → `items.name` | product header name | LOADED* | same |
| `product.parent_sku` | text ≤ 100 | none | → `items.seller_sku` (item row) | §4 giá vốn join (SKU) | LOADED* | same |
| `product.status` | number or label → string | none | → `items.status` | product header status | LOADED* | same |
| `product.model_list[].id` | digits | none | → `items.variation_id` | §4 per-SKU key | LOADED* | same |
| `product.model_list[].name` | text ≤ 255 | none | → `items.variation_name` | product header variations | LOADED* | same |
| `product.model_list[].sku` | text ≤ 100 | none | → `items.seller_sku` (variation row) | §4 giá vốn join (SKU) | LOADED* | same |

## B6. same endpoint → dataset `item_snapshot` (RESERVED: connector holds it, backend 404)

Rows: one per item (`model_id ''`) and per model. Backend model `ShopeeItemSnapshotRow` is validated by `reserved.py`; the destination table `platform_item_snapshots` (migration 112) exists but its columns differ (see `coverage.md` G-09). Never posted.

| Source field (JSON path) | Unit/format | Order type | Row field → intended `platform_item_snapshots` column | Used by | Status | Test |
|---|---|---|---|---|---|---|
| `product.cover_image` | image id or URL ≤ 300 | none | `image` → `image_urls[0]` (+ `image_hashes`, `product_image_assets` need a download step that does not exist) | product header image, §8 `cover_image` card, image history | RESERVED | `C-RM::maps the snapshot: price, stock per model, counts, images, times, promo tags, campaigns`, `C-CT::item_snapshot (reserved until migration 112)` |
| `product.create_time` | unix seconds → ISO UTC | none | `create_time` → `created_on` | product header "created" | RESERVED | same |
| `product.modify_time` | unix seconds | none | `modify_time` → (no column) | freshness | RESERVED | same |
| `price_detail.price_min`, `price_max` | VND (scale unverified) | none | `price_min/max` → `list_price` (min/max of the range; no multi-model rule) | **§6 list price**, product header price | RESERVED | same |
| `price_detail.selling_price_min`, `selling_price_max` | VND | none | → `current_price` | product header "đang bán" | RESERVED | same |
| `price_detail.has_discount`, `max_discount_percentage`, `max_discount` | bool / 0..100 / VND | none | `has_discount`, `discount_percent`, `max_discount` → `promo_label`? (no column) | §3 promotion price active | RESERVED | same |
| `stock_detail.total_available_stock`, `total_seller_stock`, `total_shopee_stock`, `low_stock_status`, `advanced_stock.sellable_stock`, `advanced_stock.in_transit_stock` | count / tag | none | → `stock` (from `total_available_stock`; others have no column) | product header stock | RESERVED | same |
| `statistics.view_count` | count | none | `view_count` → (no column) | product header | RESERVED | same |
| `statistics.liked_count` | count | none | `liked_count` → `likes` | product header "likes" | RESERVED | same |
| `statistics.sold_count` | count | none | `sold_count` → `sold_total` | product header "sold" | RESERVED | same |
| `tag.has_discount`, `tag.has_bundle_deal` (or `promotion.has_bundle_deal`), `tag.has_add_on_deal`, `tag.has_ams_commission`, `tag.unlist`, `promotion.wholesale` | bool | none | `promo_has_*`, `unlisted` → (no columns) | §3 which lever is active; §8 | RESERVED | same |
| `get_campaign_info_by_item_list` answer (the page's own call, not replayed) | active campaigns per item → count | none | `campaign_count` → (no column) | §3 | RESERVED | `C-RM::reads campaign counts from the page's own answer` |
| `model_list[].image`, `.price_detail.origin_price`, `.price_detail.promotion_price`, `.stock_detail.*`, `.statistics.sold_count`, `.is_default`, `.tier_index` | | none | model row: `image`, `origin_price`, `promotion_price`, stock fields, `sold_count`, `is_default`, `tier_index` | **§6 list price and §3 promotion price per SKU**; stock per variation | RESERVED | same |
| `product.boost_info` | object | none | not mapped | none | NOT PARSED | none |
| `rating`, `rating_count`, `category path` | | | NOT in this endpoint (recon) | product header rating/category; §10a fee rate | NOT AVAILABLE | none |
| `get_product_extensive_info?product_ids=…` (bidding price hints, buy box, ads_potential) | | | never called | §8 `ads_budget`, price market | NOT AVAILABLE (not wired) | none |

## B7. `POST /api/pas/v1/homepage/query/` (body `start_time`, `end_time`, `filter_list`, `offset`, `limit`, `use_paid_gmv`) → dataset `ads_campaign_daily`

One finished GMT+7 day per call (day bounds `start`, `start + 86 399`), paged by `limit`; up to `ADS_CATCHUP_DAYS = 3` unread earlier days plus yesterday per run; no 30-day backfill for ads. Post per day, `order_type` = `paid` if the page's template had `use_paid_gmv: true` else `placed` (never `confirmed`). Row key `(date, campaign_id)`; stream `ads`, `segment = 'c' + sha1(campaign_id)[:12]`, `platform_source = title[:64]`. KPI columns written: `impression → impressions`, `click → clicks`, `ctr`, `broad_order → orders`, `broad_gmv → gmv`, `atc → add_to_cart`; everything else goes to `extra` under the platform name.

| Source field (JSON path) | Unit/format | Order type | Target | Used by | Status | Test |
|---|---|---|---|---|---|---|
| `entry.campaign.campaign_id` | digits | placed / paid | → hashed `segment` (the id itself is not stored) | campaign key (daily) | LOADED* | `C-RM::maps one finished day: a row per campaign plus the day's ROAS target`, `RD::test_ads_daily_rows_are_ads_overlay_rows_per_campaign_and_day`, `C-CT::ads_campaign_daily` |
| `entry.title` | text ≤ 255 | | → `platform_source` | campaign label | LOADED* | same |
| `entry.type`, `entry.subtype`, `entry.state` | number or label | | → `extra.ad_type`, `extra.ad_subtype`, `extra.state` (platform enum, number or short label) | §8 ads purpose seed (type), `ads_pause` (state) | LOADED* | same |
| `entry.campaign.daily_budget`, `total_budget` | VND (scale unverified) | | → `extra.daily_budget`, `extra.total_budget` | §5 "chi marketing / ngày vs trần" is the SHOP cap (Mục tiêu), not this; §8 | LOADED* | same |
| `entry.campaign.roi_two_target` | ratio | | → `extra.roi_two_target` | §8 `ads_roas_target` | LOADED* | same |
| `entry.report.impression`, `click` | count | | → `impressions`, `clicks` | §2 ads overlay | LOADED* | same |
| `entry.report.ctr`, `product_ctr`, `avg_rank`, `sov`, `broad_roi`, `broad_cir`, `direct_roi`, `direct_cir` | ratio | | → `ctr` (KPI) / `extra.*` | §8; §10 ROAS | LOADED* | same |
| `entry.report.cost` | VND | | → `extra.cost` (**note the key**: the file datasets use `extra.ads_expense`) | **§4 ad spend (daily) per campaign; total ad spend**; §5 chi | LOADED* | same |
| `entry.report.cpc`, `cpm` | VND | | → `extra.cpc`, `extra.cpm` | none | LOADED* | same |
| `entry.report.broad_gmv`, `broad_order` | VND / count | | → `gmv`, `orders` | **§4 broad ad GMV; ROAS broad (shop-level)** | LOADED* | same |
| `entry.report.direct_gmv`, `direct_order` | VND / count | | → `extra.direct_gmv`, `extra.direct_order` | **§4/§10 direct ad GMV; product break-even compares ROAS trực tiếp** | LOADED* | same |
| `entry.report.product_impression`, `product_click`, `reach`, `page_views`, `unique_visitors`, `checkout`, `atc`, `voucher_amount`, `voucher_sales` | count / VND | | → `extra.*` (`atc` → `add_to_cart`) | none / voucher overlap | LOADED* | same |
| `entry.report.<unknown numeric key>` | | | → `extra.<key>` (≤ 20) | | LOADED* | same |
| `entry.ratio.*` (change vs previous period) | | | dropped | none | NOT PARSED (dropped) | none |
| per-PRODUCT split of a campaign (product rows of a group campaign) | | | **not in `homepage/query`**: one row per campaign only, `item_id` is never set | **§4 product ad spend** from the daily feed | NOT AVAILABLE | none |
| `status`/dates of the campaign (`campaign.start_time`, `campaign.end_time`) | unix | | not mapped | §8 `ra_mat` end date | NOT PARSED | none |

## B8. `POST /api/pas/v1/report/get_time_graph/` (body `agg_interval`, `campaign_type`, `start_time`, `end_time`, `need_roi_target_setting`, `filter_params`) → dataset `ads_campaign_daily`, shop-level row

| Source field (JSON path) | Unit/format | Order type | Target | Used by | Status | Test |
|---|---|---|---|---|---|---|
| `report_by_time[].roi_target_setting.value` (last non-empty of the day) | ratio > 0 | placed / paid | → row with `campaign_id` null: `extra.roi_target`, segment `all`, `platform_source ads_roas_target` | §8 `ads_roas_target`: the ROAS target in force that day | LOADED* | `C-RM::ROAS target: the last non-empty setting of the day, none when unset` |
| `…roi_target_setting.is_cold_start` | bool | | → `extra.roi_target_cold_start` | §8 | LOADED* | same |
| `target_broad_roi_setting`, boost settings, the metric series | | | not mapped | none | NOT PARSED | none |

Not read at all: `POST /api/pas/v1/report/export_job/...` (file reports via the export centre), the ads page upsell modal ("Áp dụng cho tất cả": must never be clicked).

## B9. `GET /api/marketing/v3/voucher/list/` (`offset`, `limit`, `promotion_type`) → dataset `voucher_settings` → `platform_promotions` (`promo_type voucher`, one-day snapshot period, `order_type none`)

Twins (same name and start) get an `ordinal` by voucher id. `gmv/orders/units/buyers` are NULL (results stay in the voucher export, A9). Row key `voucher_id`; the code goes to the raw copy only.

| Source field (JSON path) | Unit/format | Order type | Target | Used by | Status | Test |
|---|---|---|---|---|---|---|
| `voucher_id` | digits | none | → `extra.voucher_id` | voucher identity | LOADED* | `C-RM::maps settings and live usage; the platform wall clock is GMT+7`, `RD::test_voucher_settings_land_as_voucher_promotions_with_twins_told_apart`, `C-CT::voucher_settings` |
| `name` | text ≤ 255 | | → `promos.program_name` | §7 name (join key to the export) | LOADED* | same |
| `voucher_code` | text ≤ 64 | | raw copy only (not in `extra`: D16) | §7 join key (lost) | LOADED* | `RD::test_the_raw_copy_of_a_voucher_post_keeps_listed_fields_only` |
| `start_time`, `end_time` | unix s → GMT+7 wall clock | | → `promos.starts_at`, `ends_at` | **§7 days** | LOADED* | same |
| `fe_status` (else `status`) | label / number → string ≤ 64 | | → `promos.status` | voucher status | LOADED* | same |
| `value` | VND off (fixed voucher) | | → `extra.discount_amount` | **§7 value (đ)** | LOADED* | same |
| `discount` | percent 0..100 (>0) | | → `extra.discount_percent` | **§7 value (%)** | LOADED* | same, `RD::test_voucher_settings_refuse_a_percent_over_100_and_a_duplicate_voucher` |
| `max_value` | VND cap | | → `extra.max_value` | **§7 value cap (max)** | LOADED* | same |
| `min_price` | VND | | → `extra.min_spend` | **§7 đơn tối thiểu** | LOADED* | same |
| `usage_limit` | count | | → `extra.usage_limit` | **§7 số lượng voucher (usage limit)** | LOADED* | same |
| `current_usage`, `distributed_count` | count | | → `extra.current_usage`, `extra.distributed_count` | §7 live usage (u cross-check) | LOADED* | same |
| `rule.usage_limit_per_user` | count | | → `extra.usage_limit_per_user` | §7/§9 per-user limit: shown, never enforced (no buyer key) | LOADED* | same |
| `use_type`, `rule.reward_type`, `rule.purpose` | integer enums | | → `extra.use_type/reward_type/purpose` (meanings unmapped) | §7 voucher kind (what is a shop voucher vs a Shopee-funded one) | LOADED* | same |
| `rule.is_seller_absorbed` | bool | | → `extra.is_seller_absorbed` | **§3 / §7 seller-borne vs Shopee-funded** | LOADED* | same |
| `rule.items` | array | | → `extra.item_count`, `item_scope` (items / shop) | §7 which SKUs qualify (the list of item ids is NOT kept) | LOADED* | same |
| `rule.choose_users`, `rule.display_from`, `GET …/promotion_tool/metrics/` | | | not mapped / not called | none | NOT PARSED | none |

## B10. Account health: `GET /api/accounthealth/v1/sc/shops/overview`, `…/shops/metric_list`, `…/metric/configs` → dataset `shop_health_daily` (HELD)

Day = capture day (GMT+7). Held by the connector (`HELD_DATASETS`) and RESERVED in the backend (no table, no migration). Used by: shop performance (chat response %, penalty points) replacing the operator form; NOT in P90 §1-§10.

| Source field (JSON path) | Unit/format | Order type | Row field | Status | Test |
|---|---|---|---|---|---|
| `overview.failed_metric_count`, `penalty_point` | count | none | `failed_metric_count`, `penalty_point` | RESERVED | `C-RM::joins the metric list with the config names and the overview row`, `RD::test_shop_health_daily_is_reserved_and_validated_by_its_own_model` |
| `overview.performance_rating` | label | none | `performance_rating` | RESERVED | same |
| `metric_list[].metric_id` | digits | none | `metric_id` (day overview row has none) | RESERVED | same |
| `metric_list[].display_value`, `target_value` | text like `92,5%` | none | `display_value`, `target_display` (≤ 64) + parsed number `value`, `target` | RESERVED | `C-RM::parses display numbers and pass / fail words` |
| `metric_list[].compare_result` | label | none | `compare_result`, derived `passed` | RESERVED | same |
| `metric_list[].metric_tag` | label | none | `metric_tag` | RESERVED | same |
| `metric/configs[].metric_name|name|title|display_name|metric_title` | text | none | `label` | RESERVED | same |

## B11. Endpoints seen in the recon that no reader calls

| Endpoint | Content | Would feed | Status |
|---|---|---|---|
| `/api/marketing/v3/public/discount/list/`, `/discount/active/`, `/discount/metrics/` | discount programme settings (ORY has no programme running: `data = null`) | §3 `khuyen_mai` programme settings (discount %, dates, item list) | NOT AVAILABLE (no sample shape) |
| `/portal/marketing/shop-flash-sale/list` | Flash Sale schedule (not opened) | §3 Flash Sale price | NOT AVAILABLE |
| `/api/v3/affiliateplatform/gql`, `creator/list`, `commissions/category_setting`, `dashboard/latest_report_date` | affiliate commission settings by category | §6 hoa hồng %, §4 | NOT AVAILABLE (path D = the page's own CSV exports, A15) |
| Orders list `/portal/sale/order` ("Xuất", "Lịch sử Xuất Báo cáo") | the order export | §3/§4 order lines | NOT AVAILABLE (path D not built; no list endpoint observed) |
| Tài chính › Doanh thu | income / fees | §4 fees actual | NOT AVAILABLE (no access for the sub-account) |

# C. Seller import template (Cài đặt › Thông số shop): sheets `SKU` and `Mục tiêu`

Source of truth today: the design artboard `docs/product/design/shopee-shop/CaiDatImport.dc.html` (constant `FLD`, the Mục tiêu table), ADR-120 decision 12 and the shared context note. **No importer, template generator, parser, validator or test exists.** The only code near it: `services/shop_rules/rules.py` (`shop_rules` current projection + `shop_rule_versions` append-only history from migration 112; `import_product_costs_csv` reads a `product_id,cost` CSV for TikTok products and is not this template). `shop_rule_versions.rule_key` and `shop_rules.rule_key` are `String(40)` with NO check constraint on the key, so a new rule key is a code change (`RULE_KEYS`, `validate_rule`), not a migration. File type `.xlsx`, 2 sheets; "no buyer name, phone or address in the file"; empty cell = keep the old value; every apply is a new version (who / when / reason / file hash, restorable); rows rejected individually (unknown SKU, giá vốn ≥ giá bán, giá vốn empty and no old value, giảm tối đa outside 0-100).

## C1. Sheet `SKU` (10 columns, bold = required)

Pre-filled by Juli from Seller Centre ("42 SKU rows of 12 products", the seller's existing giá vốn written back). Key: `item_id` + `variation_id` (SKU text is shown and checked against `platform_items.seller_sku`).

| Source field | Unit/format | Order type | Target | Used by | Status | Test |
|---|---|---|---|---|---|---|
| `item_id` * | digits (Mã sản phẩm) | n/a | key; → `shop_rules.scope_ref` (format of the SKU scope undecided: `sku_cost` accepts any string ≤ 100) | join to `shopee_order_lines.item_id`, `platform_items` | NOT AVAILABLE (no importer) | none |
| `variation_id` * | digits (Mã phân loại; empty = item) | n/a | key | join to `shopee_order_lines.variation_id` | NOT AVAILABLE | none |
| `SKU` * | text ≤ 100 | n/a | validation against `platform_items.seller_sku` (A4/B5) | §4 `SkuCost.sku`, `OrderLine.sku`; rule says SKU is unknown → reject | NOT AVAILABLE | none |
| `giá vốn` * | VND per unit | n/a | → rule `sku_cost` (exists: scope = SKU, VND ≥ 0, wins over `product_cost`) in `shop_rules` + `shop_rule_versions` | **§4 giá vốn × qty**; §6 floor `cogs`; §9 cost coverage | Storage exists (rule `sku_cost`); importer NOT AVAILABLE | `tests/unit/test_shop_rules_off_api.py` (rule validation only, TikTok-era SKU ids) |
| `đóng gói` | VND per ORDER LINE (§9: one pack per product line, set per SKU) | n/a | NO rule key (`packaging` does not exist) | **§4 đóng gói**; §6 floor | NOT AVAILABLE (new key needed) | none |
| `giảm tối đa (%)` | 0..100 | n/a | → rule `max_discount_pct` (exists, scope = SKU id, 0-100) | §6 "min with the seller's cap" (`seller_max_discount_rate`) | Storage exists; importer NOT AVAILABLE | `tests/unit/test_shop_rules_off_api.py` |
| `tồn kho` | count | n/a | NO rule key; stock also read by connector B6 (RESERVED) | product header stock; days to sell-out | NOT AVAILABLE | none |
| `ngày nhập lại` | date | n/a | NO rule key | product header restock date | NOT AVAILABLE | none |
| `nhóm` | text (e.g. Thương hiệu ORY / Phân phối) | n/a | NO rule key | product header group; Ưu tiên tag | NOT AVAILABLE | none |
| `trạng thái` | text | n/a | NO rule key | product header (seller-side status) | NOT AVAILABLE | none |

## C2. Sheet `Mục tiêu` (one row per month)

| Source field | Unit/format | Order type | Target | Used by | Status | Test |
|---|---|---|---|---|---|---|
| `Tháng` | `T12/2026` in the artboard | n/a | would be the scope of a monthly rule | key | NOT AVAILABLE | none |
| `GMV` | VND | confirmed (assumed) | NO rule key | shop goal; reasonableness check `GMV ≈ đơn × AOV`, > 5 % apart = warning | NOT AVAILABLE | none |
| `Đơn` | count | confirmed | NO rule key | §5 ④ target | NOT AVAILABLE | none |
| `AOV` | VND | confirmed | NO rule key | §5 ⑤ target | NOT AVAILABLE | none |
| `Biên mục tiêu` | % (design: 10,0 % → 12,0 %) | n/a | closest existing key `min_margin_pct` (shop-wide, not monthly) | **§6 operating floor `target_margin_rate`**; §8 Biên < target | NOT AVAILABLE (monthly scope needs a new key; the floor input is a single fraction today) | `PRF::test_worked_example_floors_and_max_discount` (floor arithmetic only) |
| `Trần ngân sách QC/ngày` | VND per day (open question in the design README: per campaign or total?) | n/a | closest existing key `gmv_max_daily_budget` (TikTok, shop-wide) | **§5 "chi marketing / ngày vs trần"**, §7 spend check (`spend_cap_per_day`), `five_numbers(spend_cap=)` | NOT AVAILABLE | `PRF::test_five_numbers_before_after_and_cap`, `P90::test_voucher_usage_rate_days_scaling_and_spend_cap` (arithmetic only) |

---

# D. Where the order-line inputs must land: `shopee_order_lines` (migration 112) versus `OrderLine`

Table has columns: `order_ref`, `line_no`, `ordered_at`, `status`, `item_id`, `variation_id`, `qty`, `original_price`, `deal_price`, `shop_voucher_share`, `platform_voucher_share`, `bundle_discount`, `promo_kind` (`none|voucher|discount|flash_sale|bundle|add_on`), `voucher_code`, `traffic_source`, `affiliate`, `commission`, `fee_fixed`, `fee_service`, `fee_payment`, `fee_other`, `payout`, provenance (`source`, `source_version`, `raw_payload_id`). **Nothing writes it** (no gateway dataset, no mapper, no loader). Money columns Numeric(18,2); fees/payout NULL when absent (never 0).

| Profit input (`order_profit.OrderLine` / `SkuCost` / others) | Column in `shopee_order_lines` | Source file/field that must feed it | Status |
|---|---|---|---|
| `order_id` | `order_ref` (HMAC of the id) | Order export `Mã đơn hàng` (hash in browser / parser) or A16 for affiliate lines | column EXISTS; feeder NOT AVAILABLE (A16 RESERVED only for affiliate orders) |
| `order_date` | `ordered_at` | Order export order time | EXISTS; feeder NOT AVAILABLE |
| `status` (`OrderStatus`: delivered, refunded_accepted, in_transit, cancelled, refunded_not_received) | `status` String(64) | Order export status + returns list; mapping to the enum not written | EXISTS; mapper NOT WRITTEN |
| `sku`, `product_id` | `item_id`, `variation_id` (SKU via `platform_items.seller_sku`) | Order export item / model ids | EXISTS; join rule not written |
| `qty` | `qty` | Order export quantity | EXISTS |
| `original_price` | `original_price` | Order export "Giá gốc" | EXISTS |
| `deal_price` | `deal_price` | Order export deal price (after seller promotion) | EXISTS |
| (seller promotion discount) | derived `original_price − deal_price` | derived | no column needed |
| `shop_voucher_share` | `shop_voucher_share` | Order export shop voucher amount (split across lines by value) | EXISTS |
| (Shopee-funded voucher) | `platform_voucher_share` | Order export Shopee voucher | EXISTS (not used by the profit code, correct per §3) |
| `bundle_discount` (combo) | `bundle_discount` | Order export combo / Mua kèm discount | EXISTS |
| `promo_kind` (`PromoKind`: none / promotion / flash_sale) | `promo_kind` | Order export alone cannot tell a programme from Flash Sale price; needs the Flash Sale slots (A10/A11, connector campaign info B6) | EXISTS; derivation rule NOT WRITTEN |
| `ad_attributed` | none | no export marks an order as ad-attributed (orders carry no traffic source) | NOT AVAILABLE |
| `affiliate`, `commission` | `affiliate`, `commission` | A16 `Chi phí(₫)` / `Hoa hồng Xtra …` (undecided) | EXISTS; mapper NOT WRITTEN |
| `actual_fees` | `fee_fixed` + `fee_service` + `fee_payment` + `fee_other` | Income export (§4 "actual from the income export") | EXISTS; feeder NOT AVAILABLE (no finance access) |
| `buyer_shipping_fee` | **none** | Order export buyer-paid shipping | **MISSING COLUMN → migration 113** |
| `bank_promo` | **none** | Order export bank promotion | **MISSING COLUMN → migration 113** |
| `payout` | `payout` | Income export | EXISTS; feeder NOT AVAILABLE |
| `SkuCost.cogs`, `SkuCost.packaging` | not in this table | SKU sheet (C1) → `shop_rules` | rule `sku_cost` EXISTS; packaging key MISSING |
| fee rate by category (`FeeComponent.rate` for `phi_co_dinh`) | `platform_fee_formulas` (reference table, empty: no seed) | fee PDF (A19) + item category | table EXISTS; seed and category join NOT WRITTEN |
| `AdsPool`, `AdsFigures`, `AdCampaign` | none (ads live in `platform_period_metrics` / `platform_daily_metrics`) | A13 / B7 | see `coverage.md` §4 |
| ad purpose per campaign | `ad_campaign_purposes` (seller / team set; `campaign_key` String(128) vs the hashed `segment` of the ads rows: join convention undecided) | seller input | table EXISTS; UI/feeder out of scope |
