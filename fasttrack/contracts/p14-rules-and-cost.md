# P14-C/F contract — cost data (read-only) and rule fields for what TikTok does not give us

Owner decisions: DECISIONS D24.5 (discounts only within the seller's margin
rule), D24.12 (ROI = (incremental GMV × margin − seller-funded cost) ÷
seller-funded cost; platform-funded discounts are not a cost; needs cost price
in Quy tắc), D24.13 (ingest price detail and per-order finance transactions,
read-only), and the owner's "Thêm ô quy tắc những thông tin chúng ta không truy
cập được".

One migration, **`081_order_cost_data`** (onto `080_lever_flows`; the deferred
`074_users_placeholder_phone_cleanup` is re-parented onto 081 and stays the
tail). The rule fields need no schema: they are new `rule_key` values in 078's
`shop_rules` key/value store.

## 1. TikTok reads (P14-C)

| Read | Path | Scope | Allowlist |
|---|---|---|---|
| Price detail | `GET /order/202407/orders/{order_id}/price_detail` | `seller.order.info` | `^/order/202407/orders/\d+/price_detail$` |
| Finance transactions by order | `GET /finance/202501/orders/{order_id}/statement_transactions` | `seller.finance.info` | `^/finance/202501/orders/\d+/statement_transactions$` |
| Line item → SKU (existing) | `GET /order/202507/orders?ids=…` (≤ 50 ids) | `seller.order.info` | already allowlisted |

Client: `integrations/tiktok/resources/order_costs.py` (`OrderCostsResource`,
on `ProductionReadResources.order_costs`). Path helpers refuse a non-numeric
order id. Documented in `docs/integrations/tiktok_api/endpoints.md` ("Cost
data"). Both are **read-only GETs**; nothing writes to TikTok.

The price-detail `line_items[]` carry a line-item `id` but **no SKU id**; the
order detail maps `line_items[].id → (sku_id, product_id)`. Only those three
ids are read from the order detail — it also carries the buyer's e-mail and
address, which are never stored or logged.

## 2. Stored data (migration 081)

All three tables are `tenant_direct` (RLS per verb through
`app_current_shop_id()`; `juli_app` gets SELECT/INSERT/UPDATE, plus DELETE on
the two data tables, whose rows are replaced as a set per order). Amounts are
`Numeric(18,2)`, vendor field names. **No buyer data, no product or SKU names.**

### `order_price_details` — one row per (shop, order, SKU) + one order-level row

| Column | Source | Status |
|---|---|---|
| `tiktok_sku_id` (`''` = the order's own totals), `tiktok_product_id`, `line_item_count` | order detail; line items summed per SKU (one line item per unit) | — |
| `sku_list_price`, `sku_sale_price`, `subtotal`, `subtotal_tax_amount`, `tax_amount`, `net_price_amount`, `payment`, `total`, `shipping_list_price`, `shipping_sale_price`, `currency` | price detail | documented (OAS), not seen live |
| `subtotal_deduction_seller`, `subtotal_deduction_platform`, `shipping_fee_deduction_seller`, `shipping_fee_deduction_platform` | price detail | documented, not seen live |
| `voucher_deduction_seller`, `voucher_deduction_platform`, `shipping_fee_deduction_platform_voucher` | price detail | **UNVERIFIED** — the docs describe them as a voucher *type* (`1010000` PLATFORM_NEW_USER, `1020000` SELLER_SKU_PRICE, `1030000` PLATFORM_FREE_SHIPPING) while the example shows a value; stored as amounts, excluded from the totals below |
| `seller_funded_amount` | `subtotal_deduction_seller + shipping_fee_deduction_seller` | derived |
| `platform_funded_amount` | `subtotal_deduction_platform + shipping_fee_deduction_platform` | derived |

Never sum the `''` row with the SKU rows of the same order. Shipping deductions
are usually only on the order row. Fields not stored: `cod_fee*`, `distance_*`
(not VN), `sku_gift_*`, `tax_rate`.

### `order_finance_transactions` — one row per (shop, order, SKU, statement) + one order-level row (`''`, `''`)

Columns: `quantity`, `revenue_amount`, `settlement_amount`, `fee_tax_amount`
(order level: vendor `fee_and_tax_amount`), `shipping_cost_amount`,
`subtotal_before_discount_amount`, `seller_discount_amount`,
`refund_subtotal_before_discount_amount`, `seller_discount_refund_amount`,
`platform_commission_amount`, `transaction_fee_amount`,
`affiliate_commission_amount`, `voucher_xtra_service_fee_amount`,
`flash_sales_service_fee_amount`, `campaign_resource_fee`,
`sfp_service_fee_amount`, `vn_fix_infrastructure_fee`, `order_create_time`;
`fee_breakdown` JSON (`{"fee.<name>"|"tax.<name>": "<amount>"}`, every fee and
tax line present) and `shipping_breakdown` JSON (`{"<name>"|"supplementary_component.<name>": …}`).
All documented in the OAS, **none seen live yet**; which fee lines a VN shop
actually gets is unverified (hence the JSON keeps all of them). Amounts keep
TikTok's sign (fees negative). `sku_name` / `product_name` are dropped.
Empty `sku_transactions` = the order has not settled yet. TikTok serves data
only after 2023-07-01.

### `order_cost_fetches` — one row per (shop, order)

`price_fetched_at`, `price_order_update_time` (the order's `update_time` when
read), `price_attempts`, `finance_fetched_at`, `finance_settled`,
`finance_attempts`, `last_error` (exception class + vendor code only).

## 3. Polling

`services/order_costs/sync.py::sync_order_costs`, called by
`workers/services/polling/ingestion.run_shop_cycle` after the commerce steps
and the cycle verdict (so it runs under the per-shop ingest lock and the sticky
shop scope, on orders just synced). Never fails the cycle.

- **Window**: orders whose `tiktok_created_at` (else `created_at`) is within 60 days.
- **Price pass**: orders not `UNPAID`/`CANCELLED`, never read or with a newer
  `update_time` than when read (a refund re-reads), < 5 failed attempts;
  newest first; `ORDER_COSTS_PRICE_PER_CYCLE` (default 10) per cycle.
- **Finance pass**: `DELIVERED`/`COMPLETED`, not settled, not asked in the last
  24 h, < 5 failed attempts; `ORDER_COSTS_FINANCE_PER_CYCLE` (default 10).
- **Rate limits**: one token per call from the shared Redis `RateLimiter`
  (10 per 60 s, the poll steps' window) keyed by the endpoint *template*; no
  waiting — an empty bucket ends the pass and the next 15-min cycle continues
  (~960 orders/day/shop at the defaults). A vendor `RateLimitError` ends the
  pass; `PermissionDeniedError` (scope not granted) ends it and is logged
  (`order_costs_permission_denied`); any other vendor error is counted on the
  order and retried on later cycles. Each order's rows + bookkeeping commit
  together.
- `ORDER_COSTS_SYNC=0` switches the step off.

Read accessor (nothing calls it yet): `services.order_costs.sku_deductions(session,
shop_id, since=…)` → per SKU: orders, units, list / sale totals, seller-funded,
platform-funded.

## 4. Rule fields for what no TikTok API gives Juli (P14-F)

Checked against the bundled OAS (product, promotion, seller, finance,
analytics) and our endpoint inventory. Every field is **optional**, unset by
default, set through the existing `GET / PUT / DELETE /v1/demo/rules/{key}`
with `set_by` (`seller` | `team`), and read by the ranking layer through
`services.shop_rules.shop_economics(session, shop_id) -> ShopEconomics`
(nothing else reads them yet).

| `rule_key` | Label (VI) | Value | Why no API gives it |
|---|---|---|---|
| `sku_cost` (scope: SKU id) | Giá vốn theo SKU | VND ≥ 0; wins over `product_cost` | No cost field anywhere in the Product API. Product-level `product_cost` already existed (P8-C). |
| `default_gross_margin_pct` | Biên lợi nhuận gộp mặc định | % 0 < v < 100 | Same — the fallback when a product has no cost, so ROI (D24.12) and break-even ROAS (D24.11) can still be computed. |
| `min_margin_pct` (existing, relabelled) | Biên lợi nhuận tối thiểu khi giảm giá | % 0 ≤ v < 100 | Seller policy. |
| `default_max_discount_pct` | Trần giảm giá tối đa (toàn shop) | % 0 ≤ v ≤ 100 | Seller policy; the per-SKU `max_discount_pct` (P8-C) still wins. |
| `program_fee_pct` | Phí tham gia chương trình (Voucher Xtra, Flash Sale…) | % 0 ≤ v < 100 | Finance shows the fee only per settled order (`voucher_xtra_service_fee_amount`, …), after the fact; the rate the seller signed up for is not exposed. |
| `joins_platform_campaigns` | Tham gia chiến dịch sàn | true / false | No campaign-registration API. `campaign_inventory` on a SKU (D24.10) shows stock already locked for an approved campaign, not intent, registration in progress, or the discount offered. |
| `platform_campaign_note` | Chiến dịch đang đăng ký | text ≤ 500 | Same. |
| `target_roas` | Mục tiêu ROAS | 0 < v ≤ 100 (GMV ÷ ad cost) | GMV Max is in the TikTok Business API, not approved for Juli yet; Shop analytics only splits GMV into GMV_MAX / NON_GMV_MAX (no spend, no ROI target). |
| `gmv_max_daily_budget` | Ngân sách GMV Max hằng ngày | VND/day ≥ 0 | Same. |
| `live_schedule` | Khung giờ LIVE thường xuyên | ≤ 14 × `{days: [mon…sun], start: "HH:MM", end: "HH:MM"}` (end < start = past midnight) | Analytics lists past LIVE sessions only; the seller's plan is not anywhere. |

Considered and not added: packaging / handling cost per order (no consumer in
D24 yet — DEBT), seller-funded shipping subsidy (now read from price detail),
platform commission rate (read per settled order from finance).

`ShopEconomics` helpers: `unit_cost(sku_id, product_id, unit_price)` (SKU cost >
product cost > price × (1 − default margin)), `gross_margin(...)` ((price − cost
− programme fee) ÷ price), `break_even_roas(...)` (1 ÷ margin, `None` when
margin unknown or ≤ 0), `max_discount_pct(sku_id)` (SKU cap > shop cap). All
return `None` rather than guess.

### API shape (`GET /v1/demo/rules` additions)

```json
"sku_cost": { "<sku_id>": { "value": 85000, "set_by": "seller", "set_by_user_id": "…", "set_at": "…" } },
"default_gross_margin_pct": null | RuleValueItem,
"default_max_discount_pct": null | RuleValueItem,
"program_fee_pct": null | RuleValueItem,
"joins_platform_campaigns": null | RuleValueItem,      // value: bool
"platform_campaign_note": null | RuleValueItem,        // value: string
"target_roas": null | RuleValueItem,
"gmv_max_daily_budget": null | RuleValueItem,
"live_schedule": null | RuleValueItem,                 // value: [{days, start, end}]
"weekdays": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
```

`PUT /v1/demo/rules/{key}` body `{scope_ref?, value, set_by}`; 422 with a plain
English message when out of range (the UI shows its own Vietnamese copy).

### Demo UI

The existing rules editor ("Quy tắc của shop": `/settings`, and Quyết định's
"Sửa") gains a group **"Thông tin TikTok không cung cấp"** with one row per
field (label, one-line help, who set it, Lưu / Bỏ đặt), in the editor's current
style. LIVE slots are typed one per line (`T2 T4 T6 20:00-22:00`,
`T7-CN 21:00-23:00`). Signed in only: the signed-out sample (and signed in
without a shop) shows the sample's values read-only in the same group, with a
"Đăng nhập để đặt" note and no inputs.
