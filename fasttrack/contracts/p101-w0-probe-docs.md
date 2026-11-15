# P101 W0 part 1: TikTok Shop (VN) docs-only capability research

Date: 2026-11-15. No credentials, no live calls, no repo edits.

## 0. Sources and how far to trust them

| Source | What it gave | Caveat |
|---|---|---|
| Bundled OAS (`tts-openapi-guide`, 405 paths) | Request/response schemas, versions, field descriptions | Stale: lacks 202509 edit, 202602 returns, 202605 analytics etc. Used as baseline only |
| Local official-docs mirror `juli/.worktrees/adhoc/partner_documents` (docv2 text, `last_crawled` 2026-07-21) and `business_documents` (Business API v1.3, crawled 2026-07-24) | "Required scope" lines, newer versions, webhook pages, GMV Max pages | 4 months old at 2026-11-15: newer versions may exist (changelog drift). Not a live fetch |
| WebFetch of `partner.tiktokshop.com/docv2/page/...` | Returns only the SPA title (no content) | Cannot be used for live version checks; version check needs the Partner Center login or `tts-open-toolkit` doc commands |
| Repo at 1bdabc56 (`constants.py`, `capabilities.py`, `docs/integrations/tiktok_api/*`, ADR-106) | What Juli already calls and allowlists | Juli pins some older versions than the docs (see section 6) |
| WebSearch | Third-party only; nothing authoritative | Not used for any confirmed claim |

Confidence legend: **C** = confirmed in docs (OAS and/or mirror page), **L** = likely (inferred from adjacent docs), **N** = not found.
Doc link pattern: `https://partner.tiktokshop.com/docv2/page/{slug}`; slug = mirror file name without `.md` (given per row). Business API: `https://business-api.tiktok.com/portal/docs/{slug}/v1.3`.
Base URLs: Partner `https://open-api.tiktokglobalshop.com`; Business `https://business-api.tiktok.com/open_api/v1.3`.

---

## A. Capability registry rows (14 ids)

Summary: **api 10, connector 3, none 1** (provisional where marked).

| id | route | create / update / stop endpoint(s) | read-back endpoint (verify write) | scope | conf |
|---|---|---|---|---|---|
| read_orders | api | n/a read. `POST /order/202309/orders/search`, `GET /order/202507/orders?ids=` (detail), `GET /order/202407/orders/{id}/price_detail`, returns `POST /return_refund/202602/returns/search`, cancels `POST /return_refund/202602/cancellations/search` | itself | `seller.order.info`; returns/cancels `seller.return_refund.basic` | C |
| read_shop_totals | api | n/a read. `GET /analytics/202509/shop/performance` (granularity 1D) ; hourly `GET /analytics/202510/shop/performance/{date}/performance_per_hour` | itself | `data.shop_analytics.public.read` | C |
| read_ads | api (Business API, separate app + auth) | n/a read. `GET /gmv_max/report/get/` (v1.3) | itself | Business API token; scope name not found in mirror (see B.6) | C endpoint / N scope |
| write_price | api | `POST /product/202309/products/{product_id}/prices/update` (SKU-level) | `GET /product/202309/products/{product_id}` (price in skus[]) ; or `POST /product/202502/products/search` | `seller.product.write` (write), `seller.product.basic` (read) | C |
| write_listing | api | `PUT /product/202509/products/{product_id}` (full edit) or `POST /product/202509/products/{product_id}/partial_edit`; image `POST /product/202309/images/upload` | `GET /product/202309/products/{product_id}`; audit state via webhook 37 / `products/diagnoses` | `seller.product.write` | C |
| write_stock | api | `POST /product/202309/products/{product_id}/inventory/update` (warehouse_id + quantity per SKU; all warehouses required) | `POST /product/202309/inventory/search` | `seller.product.write`; read `seller.product.basic` | C |
| promo_discount | api | create `POST /promotion/202309/activities` (activity_type FIXED_PRICE or DIRECT_DISCOUNT) ; add/edit products `PUT /promotion/202309/activities/{id}/products` ; edit meta `PUT /promotion/202309/activities/{id}` ; remove `DELETE .../products` ; stop `POST .../{id}/deactivate` ; revive (expired < 7 days) `POST /promotion/202607/activities/{id}/republish` | `GET /promotion/202309/activities/{id}` ; `POST /promotion/202309/activities/search` | write `seller.promotion.write`; read `seller.promotion.info` | C |
| promo_flash_sale | api | same endpoints, activity_type FLASHSALE (docs: webhook 39 says FLASHSALE only in SEA incl. VN) | same | same | C (VN availability L, probe) |
| voucher | connector | none: "You cannot use OpenAPI to create coupon activities" (Create Activity + Promotion overview). Read only: `POST /promotion/202406/coupons/search`, `GET /promotion/202406/coupons/{id}` | coupons/search by `title_keyword` after the seller clicks Lưu | read `seller.promotion.info` | C |
| bundle | connector (provisional, see note) | No endpoint for a "Bundle Deal" (fixed combo price). ADR-106 already records "Bundle deals ... no Partner API write or read" | none found; Seller Center DOM read-back via Connector | n/a | N for Bundle Deal; C for BMSM |
| affiliate_commission | api | open collab: `POST /affiliate_seller/202412/open_collaborations` (products + `commission_rate`, hundredths of a percent, 1% to 80%), `POST /affiliate_seller/202405/open_collaboration_settings`, remove `DELETE /affiliate_seller/202409/open_collaborations/products/{product_id}` ; targeted: `POST /affiliate_seller/202508/target_collaborations`, `PUT .../{id}` (commission_rate, target_ad_commission_rate), `DELETE .../{id}` | `POST /affiliate_seller/202412/open_collaborations/search`, `GET /affiliate_seller/202409/open_collaboration_settings`, `GET /affiliate_seller/202508/target_collaborations/{id}` | write `seller.affiliate_collaboration.write`; read `seller.affiliate_collaboration.read` | C (update-in-place of an existing open-collab rate: L) |
| ads_campaign | api (Business API) for GMV Max; connector/none for platform campaign registration | create `POST /campaign/gmv_max/create/`, update `POST /campaign/gmv_max/update/` (budget, ROI target, on/off via operation_status), delete via update. Platform/registration campaigns (Chiến dịch sàn): no API found | `GET /campaign/gmv_max/info/` ; `GET /gmv_max/campaign/get/` | Business API; scope name not found | C endpoints / N scope |
| live_schedule | none (provisional) | No seller-side LIVE scheduling endpoint found. Only creator-side showcase/shoppable video APIs and read-only LIVE analytics | n/a | n/a | N |
| shop_tab | connector (provisional) | No endpoint found for shop tab / store decoration. Partner API has creator `showcase_products` only (`affiliate_creator`, creator scope) | Seller Center DOM read-back | n/a | N |

### A.1 Vietnamese reason lines for `connector` / `none`

| id | route | reason (vi) |
|---|---|---|
| voucher | connector | `TikTok Shop không có API tạo voucher của shop. Juli điền sẵn trên Seller Center, bạn kiểm tra rồi bấm Lưu.` |
| bundle | connector | `TikTok Shop không có API tạo Bundle Deal (combo giá cố định). Juli điền sẵn trên Seller Center, bạn kiểm tra rồi bấm Lưu.` |
| shop_tab | connector | `TikTok Shop không có API chỉnh tab Shop. Juli điền sẵn trên Seller Center, bạn kiểm tra rồi bấm Lưu.` |
| live_schedule | none | `TikTok Shop chưa có API đặt lịch LIVE cho shop. Juli chỉ đề xuất khung giờ, bạn tự đặt lịch trong TikTok LIVE Manager.` |
| ads_campaign (campaign sàn) | none | `Đăng ký chiến dịch sàn không có API. Bạn đăng ký trong Seller Center; Juli chỉ gợi ý.` |

### A.2 Notes that change routing

1. **bundle**: if Juli's Shopee "combo" maps to TikTok **Buy More Save More** (BMSM), that is an API route: `POST /promotion/202309/activities` with `activity_type=BUY_MORE_SAVE_MORE` and `discount.bmsm_discount.details[]` (max 2 tiers; threshold_type MINIMAL_ITEM_QUANTITY or MINIMAL_ORDER_AMOUNT; type PERCENTAGE_OFF or AMOUNT_OFF), products via `PUT .../products`. Webhook 39 lists BUY_MORE_SAVE_MORE as a supported type. Recommend the registry splits `bundle` (connector) from a BMSM row (api), or maps combo to BMSM. Gift With Purchase also exists (`discount.gift_discount`). Confidence C for BMSM in the schema; VN availability needs a probe.
2. **write_price vs promotions**: a product in a flash deal and a product discount shows only the flash price; TikTok campaign price beats both (Promotion overview). Read-back of the effective price therefore needs the activity read, not only the product read.
3. **write_listing**: Juli pins `PUT /product/202309/products/{id}`; docs show newer `202509` edit and `202509` partial_edit. Highest-version rule says use 202509 unless a probe shows a regression. The title bound for VN (25 to 255 chars) is in ADR-106.
4. **write_stock**: update must carry every warehouse the SKU is stocked in ("Multiple warehouses detected. Include all warehouse IDs"); error 12052xxx style "warehouse does not exist" if a wrong id. FBT stock is not writable here.
5. **ads_campaign / read_ads** need a TikTok API for Business app and an ad account authorised for the TikTok Shop (exclusive authorization endpoints exist: `GET/POST .../gmv_max/...` "Grant an ad account exclusive authorization for a TikTok Shop"). Juli's report already states "shop chưa cấp quyền Business API". This is a second OAuth flow, not the Partner Center token.

---

## B. Reads for the per-day components

Per-day = one calendar day in the shop's timezone (VN = UTC+7). Analytics takes `start_date_ge` inclusive / `end_date_lt` exclusive "in shop registered timezone".

### B.1 Component map

| component | endpoint (version) | field(s) | scope | notes | conf |
|---|---|---|---|---|---|
| gmv | `GET /analytics/202509/shop/performance`, granularity=1D | `performance.intervals[].sales.gmv.overall.amount` | `data.shop_analytics.public.read` | Docs: "Total amount paid for orders ... **including canceled and refunded orders**". See B.2 conflict | C |
| orders | same | `sales.orders_count` ("paid orders") ; `sales.sku_orders_count` | same | "orders_count" counts paid orders; cancels not removed | C |
| units | same | `sales.items_sold` | same | Total items, e.g. 3 of SKU A + 2 of SKU B = 5 | C |
| refunds (platform total) | same | `sales.refunds.amount` | same | Refund amount generated; no date-of-refund semantics documented | C / L semantics |
| gross_revenue (platform) | same | `sales.gross_revenue.overall` + `breakdowns[]` | same | = (customer payment + platform product subsidies) minus taxes. For SEA breakdown type NON_GMV_MAX / GMV_MAX with percentage: **an ads-attributed revenue share** | C |
| order lines | `GET /order/202507/orders?ids=` (up to batch), after `POST /order/202309/orders/search` | `line_items[]`: sku_id, product_id, sale_price, original_price, seller_discount, platform_discount, is_gift, combined_listing_skus, cancel_reason, display_status ; `payment.*` | `seller.order.info` | Search by create_time or update_time window (Juli learned: window by creation time, ADR-106 amendment 5). Line items repeat per unit; quantity = count of identical rows (verify) | C |
| net_revenue | `GET /finance/202501/orders/{order_id}/statement_transactions` | order-level `revenue_amount` (= net sales), SKU-level `revenue_breakdown.subtotal_before_discount_amount`, `seller_discount_amount`, `refund_subtotal_before_discount_amount` | `seller.finance.info` | Exists only **after settlement**. Before that: `GET /finance/202507/orders/unsettled` (estimate) | C |
| fees | same endpoint + `GET /finance/202501/statements/{statement_id}/statement_transactions` | `fee_tax_breakdown.fee.*`, `.tax.*` (map in B.3) | `seller.finance.info` | Statement-level rollups: `GET /finance/202309/statements` (fee_amount, revenue_amount, settlement_amount, adjustment_amount) | C |
| shipping_net | same | `shipping_cost_amount` and `shipping_cost_breakdown.*` | `seller.finance.info` | Net = actual carrier fee minus customer-paid and platform subsidies; negative means seller receives money | C |
| affiliate_commission | finance fee fields (settled) ; `POST /affiliate_seller/202410/orders/search` (estimated and actual) | finance: `affiliate_commission_amount`, `affiliate_ads_commission_amount`, `affiliate_partner_commission_amount`, `cofunded_creator_bonus_amount`; affiliate orders: `skus[].estimated_paid_commission`, `actual_paid_commission`, `*_shop_ads_commission`, `content_type` (SHOP / VIDEO / LIVE / PRE_LIVE / PROMOTION_PAGE / LINKSHARE) | finance `seller.finance.info` ; affiliate `seller.affiliate_collaboration.read` | Affiliate orders endpoint gives commission **before** settlement (estimate), by content type | C |
| ads_spend | Business API `GET /gmv_max/report/get/` | metric `cost` ; `net_cost` excludes ad credit/coupons | Business API (scope N) | B.6 | C |
| ads_gmv | same | `gross_revenue` ("amount the user pays plus platform subsidies"), `orders`, `roi` | same | Not the same basis as analytics `gmv` (see B.6) | C |
| offer_promo / offer_voucher / offer_combo | order detail `line_items[].seller_discount`, `payment.seller_discount`; `price_detail` `subtotal_deduction_seller`, `voucher_deduction_seller`; finance `revenue_breakdown.seller_discount_amount` | one lumped seller-funded number | `seller.order.info`, `seller.finance.info` | **No split by promotion type in any order or finance field** (finance doc: lumps Product Discount, Flash Deal, BMSM, Voucher, Bundle and the seller share of co-funded voucher). Splitting needs reconstruction (B.5) | C (lump) / N (split) |
| views | `GET /analytics/202605/shop_videos/performance` (`views`, `click_through_rate`) ; product `GET /analytics/202509/shop_products/{id}/performance` traffic.breakdowns (`page_views`, `impressions`, `ctr`) ; shop `traffic.avg_page_views`, `avg_visitors` | see B.4 | `data.shop_analytics.public.read` | Shop-level traffic fields are **daily averages**; with granularity=1D one day = its own value (verify) | C |
| clicks | derived: `impressions x ctr` (product breakdown); `click_through_rate x views` (video) | see B.4 | same | No direct "clicks" integer found | L |
| stock_units | `POST /product/202309/inventory/search` ; `GET /product/202309/products/{id}` | `inventory[].quantity` per warehouse; `skus[].inventory` | `seller.product.basic` | Point-in-time snapshot; webhook 68/27 for changes | C |

### B.2 GMV definition conflict (probe needed)

| Source | Definition quoted |
|---|---|
| `shop/performance` 202509 (+ product list/detail) | "Total amount paid for orders during the selected period, **including canceled and refunded orders**" |
| `performance_per_hour` 202510 `overall.gmv` | "total amount paid by customers, **including shipping fees, but subtracts platform co-funding and seller promotions**. GMV does not subtract cancellations or refunds" |
| `gross_revenue` | (customer payment + platform product subsidies) minus taxes |
| GMV Max `gross_revenue` | amount the user pays plus all TikTok Shop platform subsidies |

Consequence: TikTok GMV **does include cancels and refunds**. Juli's "one GMV" (see connector-sync plan C) must be defined once and the platform GMV is "paid-order GMV before cancel/refund". Whether shipping is inside GMV differs between the two endpoints; a sandbox/live probe must compare against the sum of order `payment` fields (open question D.1).

### B.3 Fee map: finance `fee_tax_breakdown` to Juli categories

Applies to `GET /finance/202501/orders/{order_id}/statement_transactions` (SKU-level; sum over `sku_transactions[]`). Fields are strings; many are market-specific (the VN-relevant ones are bold).

| Juli category | fields | conf |
|---|---|---|
| commission | **`platform_commission_amount`**, `dynamic_commission_amount` (ID only), `referral_fee_amount` (US only), `tsp_commission_amount` | C |
| payment | **`transaction_fee_amount`**, `credit_card_handling_fee_amount`, `seller_paylater_handling_fee_amount` | C |
| service / program | `flash_sales_service_fee_amount`, `voucher_xtra_service_fee_amount`, `bonus_cashback_service_fee_amount`, `cofunded_promotion_service_fee_amount`, `live_specials_fee_amount`, `sfp_service_fee_amount`, `mall_service_fee_amount`, `pre_order_service_fee_amount`, `campaign_resource_fee`, `shipping_fee_guarantee_service_fee`, `installation_service_fee`, **`vn_fix_infrastructure_fee`** (VN fixed infrastructure fee on delivered orders) | C |
| affiliate commission | **`affiliate_commission_amount`**, `affiliate_ads_commission_amount`, `affiliate_partner_commission_amount`, `affiliate_commission_amount_before_pit` (SEA), `cofunded_creator_bonus_amount`, `tap_shop_ads_commission`, `external_affiliate_marketing_fee_amount`; deposit/release pair `affiliate_commission_deposit` / `_release` (cash timing, not cost) | C |
| shipping net | `shipping_cost_amount` (order and SKU level) and `shipping_cost_breakdown` (actual fee, customer paid, platform discount, return shipping, subsidies, insurance). `fee_and_tax_amount` EXCLUDES shipping; `settlement_amount = revenue_amount - shipping_cost_amount - fee_tax_amount` | C |
| tax | `fee_tax_breakdown.tax.*`: **`pit_amount`**, `vat_amount`, `local_vat_amount`, `sst_amount`, etc. (VN: PIT / VAT paid by the platform on seller's behalf) | C |
| voucher (seller-funded) | not in fees; inside `revenue_breakdown.seller_discount_amount` (lumped, see B.1) | C |
| ads | **not in finance** (ads billed through the ad account). Only `tap_shop_ads_commission` / `affiliate_ads_commission_amount` (commission on ad-driven affiliate orders) | C |
| refund-related | `refund_administration_fee_amount`, `seller_discount_refund_amount`, `refund_subtotal_before_discount_amount` | C |

Sign/amount conventions (negative numbers = deductions) are not stated in the schema: probe D.4. Fee fields are populated at settlement; statement is created daily 00:00 UTC (= 07:00 VN) so statement day != order day.

### B.4 Traffic by source

| Level | Endpoint | Source keys available | What is NOT split |
|---|---|---|---|
| Shop GMV | `shop/performance` 202509 `sales.gmv.breakdowns[].type` | `VIDEO`, `LIVE`, `PRODUCT_CARD` | no search, no affiliate, no ads here |
| Shop revenue | `sales.gross_revenue.breakdowns[].type` (SEA) | `NON_GMV_MAX`, `GMV_MAX` (+ `percentage`) | gives the paid (GMV Max) share of revenue, not traffic |
| Product detail | `shop_products/{id}/performance` 202509 | sales and traffic `breakdowns[].content_type`: `VIDEO`, `LIVE`, `PRODUCT_CARD`; traffic: `avg_unique_page_views`, `page_views`, `impressions`, `ctr`, `avg_conversion_rate` ; also `top_contents` (LIVE/VIDEO ids), `top_creators`, `cancel_and_refunds`, `ratings` | search source, affiliate source, ads source |
| Product list | `shop_products/performance` 202605 (Juli pins 202605; OAS has 202509) | `overall_performance`: gmv, items_sold, orders | no source split |
| SKU | `shop_skus/performance` and `/{sku_id}/performance` 202509 | per OAS list | no source split in list |
| Video | `shop_videos/performance` 202605 (`account_type` ALL / OFFICIAL_ACCOUNTS / MARKETING_ACCOUNTS / AFFILIATE_ACCOUNTS) ; batch details 202609 (Juli uses) | views, ctr, gmv, gpm, items_sold, sku_orders | gives affiliate vs official by account type only |
| LIVE | `shop_lives/performance` 202509, `.../overview_performance`, `shop_lives/{id}/performance_per_minutes` 202510, `shop/{live_id}/products_performance` 202512 | per-session | |
| Affiliate | `affiliate_seller orders/search` 202410 `skus[].content_type` | SHOP, VIDEO, LIVE, PRE_LIVE, PROMOTION_PAGE, LINKSHARE | order-level, commission only |

Conclusion: the shop-level API gives only **VIDEO / LIVE / PRODUCT_CARD** (what ADR-107 already assumed: "A-34 does not split" paid vs organic). **Search, affiliate and ads are not distinct source keys** in analytics. Ads share can be bounded using `gross_revenue.breakdowns` (GMV_MAX share) plus Business API reports. "Traffic source" parity with Shopee therefore maps: Shopee organic/TTLK/ads -> TikTok organic(video/live/product card) / affiliate (via affiliate orders content_type, with the `account_type=AFFILIATE_ACCOUNTS` video filter) / ads (GMV Max).

### B.5 Seller-funded promo split (offer_promo / offer_voucher / offer_combo)

| Approach | Needs | Verdict |
|---|---|---|
| Use `line_items[].seller_discount` | order detail | total only |
| `price_detail.voucher_deduction_seller` / `voucher_deduction_platform` (enum strings 1010000, 1020000, 1030000) | `seller.order.info` | only 3 documented codes, which look like platform codes (PLATFORM_NEW_USER, SELLER_SKU_PRICE, PLATFORM_FREE_SHIPPING); cannot be assumed to isolate seller vouchers. Probe |
| Reconstruct: join order line SKU + time against `promotion/202309/activities/search` + `activities/{id}` (discount price/percent per product) and `coupons/search` (voucher usage_stats) | `seller.promotion.info` | possible for product discount, flash sale, BMSM (price known); vouchers only via coupon `usage_stats` aggregate, not per order. Heuristic, label as estimated |
| No promotion id appears on order line items (checked OAS fields) | | confirmed gap |

### B.6 GMV Max reads and writes (Business API v1.3)

Docs read from `business_documents/api-reference/gmv-max/` (crawled 2026-07-24).

| Purpose | Method + path | Key params / fields | doc slug |
|---|---|---|---|
| Shop-level daily spend | `GET /gmv_max/report/get/` | `advertiser_id`, `store_ids=["..."]`, `start_date`, `end_date`, `dimensions=["advertiser_id","stat_time_day"]` (or `stat_time_hour`), `metrics=["cost","orders","cost_per_order","gross_revenue","roi","net_cost"]`, `gmv_max_promotion_types` PRODUCT / LIVE, page_size up to 1000. "Regardless of whether created in Ads Manager or Seller Center" | `metrics-in-gmv-max-campaign-reports` |
| Campaign / product / creative / livestream / duration reports | same endpoint, other dimensions | per-level metrics (product-level, creative-level, `room_ids`) | same |
| List campaigns | `GET /gmv_max/campaign/get/` | filtering gmv_max_promotion_types, store_ids, primary_status | `get-gmv-max-campaigns` |
| Campaign info | `GET /campaign/gmv_max/info/` | | `get-the-details-of-a-gmv-max-campaign` |
| Create / update | `POST /campaign/gmv_max/create/`, `POST /campaign/gmv_max/update/` | budget, ROI target (`roas_bid`), schedule, creatives | `create-a-gmv-max-campaign`, `update-a-gmv-max-campaign` |
| Shops available | `GET /gmv_max/store/list/` | `is_gmv_max_available`, `store_authorized_bc_id` | `get-tiktok-shops-for-gmv-max-campaigns` |
| Authorisation | "Grant an ad account exclusive authorization for a TikTok Shop" + "Get the TikTok Shop exclusive authorization status" | Business Center user needs permission to the shop | `grant-an-ad-account-exclusive-authorization-for-a-tiktok-shop` |
| Recommended ROI/budget | `GET .../recommended GMV Max ROI target and budget` | | `get-the-recommended-gmv-max-roi-target-and-budget` |

Facts that matter for the data model:
- `cost` = "estimated total amount spent"; `net_cost` excludes ad credit and coupons; some net-cost fields carry **data latency up to 11 hours**.
- `gross_revenue` (GMV Max) is revenue attributed to ads (customer pays + platform subsidies); it is a subset of shop revenue, so `ads_gmv <= shop gmv` is expected but not guaranteed (attribution window).
- Report time zones: the page states "Time zone: UTC+0" for some metric blocks (lines in the reporting doc); day buckets may be UTC days, not VN days. Use `stat_time_hour` and re-bucket to UTC+7 (probe D.7).
- Product GMV Max since 2025-07 is the only Shop Ads campaign type with no keyword control (ADR-106).
- Required scope / permission name for the Business API token: **not found** in the mirror. Needs Business API app review (advertiser authorisation: ad management and reporting) and the shop authorisation above.

---

## C. Webhooks (Partner Center event `type` ids)

Pages in `partner_documents/webhooks/`. Signature: HMAC-SHA256 over `app_key + raw_body`, header `Authorization` (Juli docs/webhooks.md). Registered with `PUT /event/202309/webhooks` (scope `seller.authorization.info`) or in Partner Center.

| type | name | area | relevance for Juli | conf |
|---|---|---|---|---|
| 1 | ORDER_STATUS_CHANGE | order | UNPAID, ON_HOLD, AWAITING_SHIPMENT, AWAITING_COLLECTION, CANCEL, IN_TRANSIT, DELIVERED, COMPLETED; `order_id`, `update_time` (Unix s) | C |
| 11 | CANCELLATION_STATUS_CHANGE | order | cancel request lifecycle | C |
| 12 | RETURN_STATUS_CHANGE | returns | legacy-ish; superseded by 64/65/67 for newer flows | C |
| 64 | AFTERSALES_REQUEST_STATUS_UPDATE | returns | new unified after-sales | C |
| 65 | RMA_STATUS_UPDATE | returns | return merchandise authorisation | C |
| 67 | REFUND_SUCCESS | returns | refund paid: trigger re-pull of order finance | C |
| 3 | RECIPIENT_ADDRESS_UPDATE | logistics | | C |
| 4 | PACKAGE_UPDATE | logistics | | C |
| 36 | INVOICE_STATUS_CHANGE | fulfillment | | C |
| 5 | PRODUCT_STATUS_CHANGE | product | on/off sale, freeze | C |
| 37 | PRODUCT_AUDIT_STATUS_CHANGE | product | verifies `write_listing` audit outcome | C |
| 15 / 16 / 18 | PRODUCT_INFORMATION_CHANGE / CREATION / CATEGORY_CHANGE | product | product history re-read (P23) | C |
| 27 / 68 / 50 | INVENTORY_STATUS_CHANGE / INVENTORY_CHANGED / SKU_STATUS_CHANGE | product | stock read-back after `write_stock`; 68 may omit top-level `shop_id` (Juli handles via `data.seller_id`) | C |
| 38 | STRIKETHROUGH_PRICE_EXPIRED | product | relevant to price display after price writes | C |
| 66 | APPEAL_COMPLETED | product | | C |
| 39 | ACTIVITY_STATUS_CHANGE | promotion | start (NOT_START to ONGOING), expire, deactivate; types FIXED_PRICE, DIRECT_DISCOUNT, SHIPPING_DISCOUNT, BUY_MORE_SAVE_MORE, FLASHSALE (SEA incl. VN); **requires Promotion Information scope** | C |
| 63 | ACTIVITY_CHANGE | promotion | Juli notes name UNKNOWN; page exists as "(63) Activity change" | C (title) |
| 56 | SAMPLE_APPLICATION_STATUS_CHANGE | affiliate seller | | C |
| 6 / 7 | SELLER_DEAUTHORIZATION / UPCOMING_AUTHORIZATION_EXPIRATION | seller | pause automations / re-auth prompt | C |
| (none) | settlement / statement / payment | finance | **No finance or settlement webhook exists in the docs mirror.** Settlement must be polled: statements daily 00:00 UTC | N |
| (none) | ads / GMV Max events | business | none (Business API has "Reporting Subscription API", not evaluated) | N |

Delivery: ACK within 3 s, expect duplicates (dedupe on `tts_notification_id` / `event_id`), polling stays the backstop (Juli rule: reconcile at most every 15 minutes).

---

## D. Open questions for the sandbox probe (W0 part 2 checklist)

Priority order. "Sandbox" = SANDBOX_VN dev shop; "live read" = read-only call on a real shop.

| # | Question | Why it blocks | How to probe |
|---|---|---|---|
| D.1 | Does `shop/performance` `gmv.overall` for a day equal the sum of order `payment` (incl./excl. shipping, incl. cancelled)? Which of the two GMV definitions (B.2) is right? | Fixes the single GMV and the cancel/refund adjustment | live read: one day, compare analytics vs order search sum, with cancelled orders present |
| D.2 | Is a day's analytics value final at T+0 / T+1? What is `latest_available_date` at 08:00 VN and 23:00 VN? Do values change after the day (late payment, cancels)? Hourly endpoint is "today plus 30 days" | Sync schedule and "freshness" labels | poll same day at 3 times; re-pull D-1, D-2, D-7 |
| D.3 | Is there a Business API token path for ORY/real shops (advertiser authorised with exclusive TikTok Shop authorisation)? Which exact scope/permission names? | read_ads, ads_campaign | read-only `GET /gmv_max/store/list/` then `/gmv_max/report/get/` with a real advertiser; confirm app permissions in the Business developer portal |
| D.4 | Sign and magnitude convention of finance fee fields (negative = charge?), and which VN fields are populated (commission, transaction, vn_fix_infrastructure_fee, affiliate, pit/vat) | Fee mapping and net_revenue | `statement_transactions` for 3 settled orders (with and without affiliate, with voucher) |
| D.5 | Pre-settlement estimates: does `/finance/202507/orders/unsettled` give the same fee fields for orders not yet settled? How many days after delivery does settlement happen in VN? | Per-day fees for recent days | pick delivered-not-settled order |
| D.6 | Can seller-funded discount be split into promo / voucher / combo from any field (price_detail voucher codes, order `payment`, finance breakdown)? Is there an activity id anywhere on order lines? | offer_* components | order detail + price_detail + transactions for an order with a known voucher and a known product discount |
| D.7 | Time zones: GMV Max `stat_time_day` and "UTC+0" blocks vs VN day; statement day (UTC) vs VN; order `create_time` Unix | Day-bucket alignment across sources | request `stat_time_hour` for a day, compare hours to order timestamps |
| D.8 | Rate limits per shop and per app: numeric limits are undocumented (repo: "UNKNOWN"; only error 100005). Analytics list endpoints page_size max 100, statements 100, search page_size up to 100 | Backfill pacing for many shops | burst test on a low-risk read; record 100005 rate and any `X-RateLimit-*` headers |
| D.9 | Is FLASHSALE creatable on a VN shop via API (webhook 39 says SEA incl. VN), and is BMSM available in VN? Which constraints (price <= 30-day lowest, quantity_limit 1..99, reserved stock)? | promo_flash_sale and bundle/BMSM rows | sandbox create + `GET activity` + deactivate (sandbox allowlist already includes create/update/deactivate) |
| D.10 | Do `activity_type` FIXED_PRICE and DIRECT_DISCOUNT with `product_level=SHOP` work for a shop-wide discount? Do edits to a live activity's price propagate (UpdateActivityProduct "cannot decrease quantity")? | Offer parity with Shopee | sandbox |
| D.11 | `prices/update` on a product that sits in an ongoing activity: error or silent? Does price write work for production shops (Juli policy forbids price writes; capability must still be proven) | write_price read-back design | sandbox |
| D.12 | Existing open-collaboration product: does re-POST of `open_collaborations` update the rate, or must the product be removed first? Is target collaboration updated by PUT? Does VN allow open collab commission 1% to 80% | affiliate_commission update path | sandbox / a test product |
| D.13 | Does `partial_edit` 202509 vs `PUT edit` 202509 differ for title/description/images (Juli currently uses PUT 202309)? Does audit status come back via webhook 37 within minutes? | write_listing version and verify step | sandbox |
| D.14 | Voucher: does any scope allow coupon creation (docs say no)? Is Seller Center (seller-vn.tiktok.com) voucher form fillable by Connector (DOM stability, anti-automation)? Same for Bundle Deal, Shop tab, LIVE schedule (does Seller Center expose a LIVE schedule page at all?) | Final route for the 3 connector rows and `live_schedule` none vs connector | Connector spike, not API |
| D.15 | `traffic` parity: does `shop/performance` traffic split by source on any newer version (202605+?), e.g. search/affiliate/ads keys? | Traffic-source tabs | pull current OAS for newer shop performance versions via Partner Center changelog |
| D.16 | Newer versions after the mirror crawl (2026-07-21): analytics 202609/202610?, finance, promotion 202607 republish, product search 202502 vs repo 202309 | Highest-version rule | compare against live docv2 or `tts-open-toolkit` doc commands |
| D.17 | `affiliate_seller/.../orders/search` coverage: do estimated commissions appear before settlement for orders from the same day; does it include ads (Shop Ads) commission as separate field for VN | affiliate_commission per-day | live read |
| D.18 | Refund day mapping: `sales.refunds` on `shop/performance` is by refund date or order date? Returns search lag | net_revenue per day | live read with a known refund |
| D.19 | `inventory/search` returning FBT vs seller warehouse; does `quantity` equal on-hand minus reserved? | stock_units meaning | sandbox |

---

## E. Rate limits, lags, timezones (consolidated)

| Topic | Finding | Conf |
|---|---|---|
| Rate limit | Not published. Throttled response code `100005`. Bucket per (app, shop). Developer guide mirror has no numbers. Repo `rate-limits.md` says UNKNOWN | N |
| Auth timestamp window | `timestamp` within 5 minutes of signing | C (repo, guide) |
| Analytics date params | `start_date_ge` / `end_date_lt` in **shop registered timezone** (VN shop = UTC+7); `latest_available_date` returned in local timezone | C |
| Analytics lag | No SLA stated; use `latest_available_date`. Hourly detail covers "within 30 days, including today" | C / N for lag |
| Order timestamps | Unix seconds (UTC) | C |
| Statements | Generated daily 00:00 UTC, one per seller per day; payment follows one-to-one. Settled N days after delivery (varies by region, VN value not in doc) | C / N for VN days |
| Finance data window | Only data after 2023-07-01 available | C |
| GMV Max | up to 11 h latency on some net-cost metrics; some report blocks UTC+0 | C |
| Pagination | analytics list 100 max, statements 100 max, coupons 100, activities 100, GMV Max report 1000 | C |
| Webhook ACK | 3 s; duplicates normal | C |

---

## F. Juli code vs docs: version drift to fix or justify

| Item | Juli pin (1bdabc56) | Docs newest seen | Action |
|---|---|---|---|
| Product search | 202309 (`PRODUCT_API_VERSION`; production-read allowlist only `/products/search` any version via regex `\d+`) | 202502 (mirror), 202312 in bundled OAS | adopt 202502 after probe |
| Product edit | `PUT /product/{202309}/products/{id}` | `PUT /product/202509/products/{id}`, `partial_edit` 202509 | adopt 202509 after probe |
| Order detail | 202507 | 202507 | ok |
| Return/cancel search | 202602 | 202602 (plus 202603 aftersales, 202604 rma) | consider 64/65 flow |
| Finance statements | 202309 | 202309 ; payments 202605 | ok |
| Order transactions | 202501 | 202501 | ok |
| Analytics shop performance | 202509 | 202509 | ok |
| Promotion | 202309 / coupons 202406 | 202309 / 202406 / republish 202607 | add republish only if needed |
| Analytics video list | 202605 ; batch 202609 | 202605 ; batch 202609 (not in mirror) | ok |
| Production write allowlist | listing PUT + image upload only | price/inventory/promotion not allowlisted | policy, not capability: a TikTok `api` route needs an explicit allowlist expansion plus ADR |

Existing allowlist notes: `WRITE_PATH_PATTERNS` already covers `/inventory/update`, `/images/upload`, `/activities`, `/activities/{id}/products`, `/deactivate`; sandbox allowlist includes `prices/update`, promotion create/update/deactivate. Production write currently has none of price, stock, promotion.

---

## G. Gaps in this document

- Business API scope names, shop-level traffic source keys beyond VIDEO/LIVE/PRODUCT_CARD, rate-limit numbers, VN settlement lag days, and anything after the mirror crawl date are not confirmed.
- Live Partner Center docv2 pages could not be read through WebFetch (SPA); the "Required scope" values come from the mirror and agree with scopes already seen in the repo (`seller.order.info`, `seller.finance.info`, `seller.product.basic`, `seller.promotion.info`, `seller.product.write`).
- `seller.promotion.write`, `seller.affiliate_collaboration.write`, and `data.shop_analytics.public.read` are NOT in the repo's known scope list (only `seller.promotion.info` and `seller.product.write` once): the Juli app's scope request must be expanded before W1 and re-authorised by sellers.
