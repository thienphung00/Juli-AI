# P92 API contract — Tự tạo phương án, Loại trừ sản phẩm, Demo parity (B-8)

For the web wave. Backend: `services/shopee_builder` (module doc `MODULE.md`), routes
`demo_shopee_builder.py`, `ops_shopee_builder.py`, `demo_shopee_pages.py`. Plan: `p92-plan.md`.

## 0. Conventions

- **Demo** base `/v1/demo/shopee` (seller, `get_active_shop`; writes need a writable shop).
  **Ops** base `/v1/ops/shops/{shop_id}/shopee` (reads and evaluate/compare: Xem+; choose, drafts and
  exclusion writes: Vận hành, audited in `ops_audit_log`). Same paths and bodies below the base.
- Money is whole đồng (JSON number), percent is percent points (`12.5` = 12,5 %), CTOR / CTR in percent.
  `null` always means "not known / not computable", never 0 (exception: an AOV lever's Δ orders is a
  real `0` with `delta.orders_note`).
- `as_of` (optional `YYYY-MM-DD`, query or body) anchors the history window; default = newest data day.
- Errors are `{"detail": {"code", "message", ...}}`. Common: `409 reco_no_data` (no Shopee numbers),
  `409 not_a_shopee_shop`, `404 product_not_found`, `422` (FastAPI validation: a version breaks a bound
  below), `422 reco_manual_invalid`, `422 reco_breach_not_acknowledged` (+ `breaches[]`),
  `503 llm_off` ("LLM tắt"), `422 llm_no_valid_draft` (+ `dropped[]`), `422 exclusion_*`, `404
  exclusion_not_found`.

## 1. B-1 Product picker and exclusions

### GET `/builder/products`
Query: `q` (name / id), `include_excluded=false`, `sort` = `gmv_90d` (default) | `orders_90d` |
`orders_30d` | `name`, `limit` (1-1000, 200), `offset`, `as_of`.
```json
{"platform":"shopee","window":{"from":"2026-07-10","to":"2026-10-07","days":90},"sort":"gmv_90d",
 "count":3,"offset":0,"limit":200,"excluded_hidden":1,"missing_cost_count":1,
 "products":[{"item_id":"1001","name":"Găng tay …","status":"Đang hoạt động",
   "orders_30d":9,"orders_90d":9,"gmv_30d":815000,"gmv_90d":1010000,"gmv_basis":"order_lines",
   "price":90000,"stock":120,"variation_count":0,"has_cost":true,"variations_with_cost":1,
   "missing_cost_chip":null,"excluded":false,"exclude_reason":null}]}
```
`gmv_basis` = `shopee_product_period` when Shopee's product totals stand for the window. `missing_cost_chip`
is `"thiếu giá vốn"` when any variation has no giá vốn. Active = catalogue status is not
unlisted / banned / deleted. Excluded rows only with `include_excluded=true`.

### Exclusions (Cài đặt › Loại trừ sản phẩm)
- `GET /exclusions` -> `{"excluded":[{"item_id","name","reason","reason_label","set_by","set_at","note"}],"count",
  "reasons":[{"key":"ngung_ban","label":"Ngừng bán"},{"key":"qua_tang",…},{"key":"phan_phoi",…},{"key":"khac",…}]}`
- `PUT /exclusions/{item_id}` body `{"reason":"qua_tang","note":"…"}` (note optional) -> the row above.
  Same reason again writes nothing. `422 exclusion_reason_invalid | exclusion_item_invalid`.
- `DELETE /exclusions/{item_id}?note=` -> `204`; `404 exclusion_not_found` if it was not excluded (undo).
- Stored as shop rules `excluded` (bool) + `exclude_reason`, scope = item id, through the versioned
  `shop_rule_versions` path (who, when, note), so each add / undo is an old -> new entry. Ops writes also
  log `exclusion_add` / `exclusion_undo`.
- **Thông số shop file**: SKU sheet gains columns `loại trừ` (Có / Không) and `lý do` (Ngừng bán, Quà tặng,
  Hàng phân phối, Khác). Per listing: every row of one item must agree; "Có" needs a reason; rejection
  kind `invalid_value`; diffs are item-scoped (`scope_ref` = item id, fields `excluded`, `exclude_reason`).
- **Effect**: an excluded listing gets no cards, is not in `env.item_ids`, matrix `products`, rankings,
  Phân tích flags (shop-level flags stay), the picker, and `manual` / builder refuse it
  (`item_excluded:<id>`). Shop totals are unchanged. New figure for the Tổng quan line "trong đó Xđ từ sản
  phẩm đã loại trừ": `GET /overview` -> `gmv.excluded_gmv` and `GET /matrix` -> `excluded`:
  `{"count":1,"gmv":700000,"orders":8,"items":[{"item_id","name","reason","gmv","orders"}],"note":"…"}`.

## 2. B-2 Variations

### GET `/builder/products/{item_id}/variations`
```json
{"item_id":"2001","name":"Hộp đựng","excluded":false,"exclude_reason":null,
 "columns":["list_price","selling_price","price_per_unit","margin_pct"],
 "margin_basis":"Biên của một đơn gồm 1 đơn vị bán của phân loại này, sau phí sàn, giá vốn, đóng gói và VAT",
 "vat":{"basis":"after_vat","prices_include_vat":true,"cost_includes_vat":false,"label":"…"},
 "missing_cost":["v1"],
 "variations":[{"variation_id":"v3","name":"Combo 3 hộp","sku":"BOX","sku_key":"BOX×3",
   "list_price":300000,"selling_price":270000,"pack_count":3,"pack_source":"name",
   "pack_source_label":"đọc từ tên phân loại","price_per_unit":90000,
   "margin_pct":54.8,"profit_per_unit":148000,"margin_label":null,"margin_reason":null,
   "has_cost":true,"stock":9}]}
```
`pack_source` = `set` (Thông số shop pack column) | `name` ("Combo N", "Set N") | `single`. No giá vốn ->
`margin_pct`/`profit_per_unit` `null`, `margin_label` `"chưa tính"`, `margin_reason` "Chưa có giá vốn trong
Thông số shop" (never the 1/3 fallback). VAT per the P91 D-12/D-14 flags. A listing without variations is one
row, `variation_id` `""`, name `"Mặc định"`. The product page (Sản phẩm) reads the same endpoint.
`sku_key` is internal (the engine's cost key); send `variation_id` in versions.

### GET `/builder/products/{item_id}/co-purchase` ("Sản phẩm hay mua cùng")
```json
{"anchor":{"item_id":"1001","name":"…"},"orders_with_anchor":9,"orders_total":19,"min_together":2,
 "window":{…90 days…},"suggestions":[{"item_id":"1002","name":"…","together":4,"orders_with_partner":6,
   "share_of_anchor_orders":0.44,"share_of_partner_orders":0.67}]}
```
Counts only; excluded listings are never suggested; `404` for an excluded / unknown anchor.

### GET `/builder/ads/campaigns`
`{"window","daily_cap":500000,"cap_rule":"daily_marketing_cap","campaigns":[{"campaign_key","name","running",
"daily_budget","roas_target","spend_per_day","roas_direct","break_even_roas","products":[{"item_id","name",
"spend","roas_direct","break_even_roas","below_break_even","excluded"}]}]}`. Feeds the ads form (pick a
campaign; each product's break-even vs actual ROAS).

## 3. Versions (B-4) — request bodies

`POST /builder/evaluate` (1-4 versions), `POST /builder/compare` (2-4), `POST /builder/choose`:
```json
{"versions":[{"kind":"voucher","label":"5k/100k","discount_type":"amount","value":5000,"min_spend":100000}],
 "as_of":"2026-10-07"}
```
`choose` also takes `chosen` (index, default 0), `primary` (take the product's #1 slot), and
`acknowledge_breaches`. Unknown keys / out-of-bound numbers are `422`. `label` ≤ 60 chars on every kind.

| `kind` | fields (bounds) |
|---|---|
| `voucher` | `scope` shop\|product\|follower\|livestream (default shop); `item_ids` (product scope only, ≤20); `discount_type` amount\|pct; `value` (pct: >0, ≤90); `min_spend` 0..2e9 (0 allowed); `max_value` (pct cap); `usage_limit`; `per_buyer_limit`; `start`,`end` (≤90 days) |
| `combo` | `items[2..6]` `{item_id, variation_id?, qty 1-20}` (distinct products); `pricing` pct\|amount\|fixed_price; `value`; `target` bundle_deal\|new_listing; `voucher?` `{discount_type,value,min_spend,max_value}`; `gift_item_id?` |
| `add_on` | `main_item_id`; `addons[1..5]` `{item_id, variation_id?, price xor pct, limit_per_order 1-20}` |
| `gift` | `gift` `{item_id xor unit_cost, packaging?, label?, qty 1-20}` ("quà không bán" = `unit_cost`, never touches stock); `trigger` `{type:"buy_item",item_id}` or `{type:"min_spend",amount}` |
| `product_discount` | `item_id`; `variations[]` `{variation_id, discount_pct xor final_price}` (required, ≥1); `start`,`end`; `per_buyer_limit` |
| `price` | `item_id`; `variations[]` `{variation_id, final_price xor change_pct (-50..100)}` |
| `flash_sale` | `item_id`; `variations[]` (as discount, required); `units`; `slot_start?`; `slot_hours 1-72` |
| `variation_set` | `item_id`; `new_variations[1..12]` `{name, price, sku?, pack_count?, stock?}`; `hide_item_ids?` — saved as a `variation_restructure` card; numbers from the set model |
| `ads` | `lever` budget\|roas\|add_product\|remove_product\|keywords; `campaign_key` (not for keywords); `daily_budget`; `roas_target`; `item_id`; `keywords[]` `{keyword,bid,match broad\|exact}` |
| `title` | `item_id`; `title` ≤100 chars; `keywords[]` (ticked) |
| `cover_image` | `item_id`; `overlay` `{layout banner_top\|banner_bottom\|corner_tag, price_vnd?, original_price_vnd?, discount_pct?, voucher_text?, pack_text?, badge_text?, hook_text?}` (CoverVariant fields; photo never altered; `hook_text` is drawn only with banner_bottom) |
| `description_first_line` | `item_id`; `first_line` ≤300 (no line break; saved card limit 500) |
| `affiliate` | `item_id`; `commission_pct 0-50`; `target_campaign`; `sample_qty 0-50`; `sample_ship_fee` |
| `price_display` | `item_id`; `variation_id?`; `text?` (default: price per unit) |
| `listing_hide` / `listing_relist` | `item_id`; relist: `stock?` |

Variation-less listings use `variation_id: ""`. A variation with no orders in the last 30 days cannot be
priced by `combo` / `product_discount` / `price` / `flash_sale` (`variation_unknown` / refusal), see §6.

## 4. Responses

### POST `/builder/evaluate` and `/builder/compare` (nothing saved)
```json
{"saved":false,"best_profit_p50":0,"today":{"as_of","window","gmv_30d","orders_30d","aov","margin_pct","spend_per_day","spend_cap"},
 "table":{"rows":[
   {"key":"cost","label":"Chi phí của thay đổi","unit":"vnd","values":[1750,3500]},
   {"key":"delta_gmv","unit":"band","values":[{"low":17953,"p50":44884,"high":71814},…]},
   {"key":"delta_orders","unit":"band","values":[…]},{"key":"delta_profit","unit":"band","values":[…]},
   {"key":"margin_after","unit":"pct","values":[33.6,…]},
   {"key":"driver:aov","label":"AOV","unit":"driver","values":[{"before":84368,"after_p50":89430},null,…]},
   {"key":"driver:ctor",…}]},
 "versions":[ <outcome> , … ]}
```
`best_profit_p50` = index of the best P50 Δ profit among versions that break no floor/cap and know their
cost (`null` if none). Table values are `null` for a refused version / a metric that version does not drive.

### The outcome (one per version; `ok:false` versions carry only `index, kind, label, refusal, warnings`)
```json
{"index":0,"kind":"voucher","change_kind":"min_spend_voucher","card_kind":"min_spend_voucher","label":"5k/100k",
 "ok":true,"refusal":null,"title":"Voucher đơn tối thiểu",
 "driver":{"metrics":[{"key":"aov","label":"AOV","unit":"vnd","before":84368,"after_p50":89430},
                      {"key":"ctor","label":"CTOR","unit":"pct","before":7.143,"after_p50":7.143}],
           "target_metric":"aov","relative_lift":{"p10":0.024,"p25":0.041,"p50":0.06,"p75":0.079,"p90":0.096}},
 "delta":{"gmv":{"low","p50","high"},"orders":{…},"profit":{…},"certain_profit":-1750,"orders_note":null,"per":"month"},
 "margin_before_pct":33.7,"margin_after_pct":33.6,
 "profit_status":"ok","cost_known":true,
 "cost":{"amount":1750,"period_days":14,"per_unit":null,"label":"Voucher ở mức dùng dự kiến"},
 "break_even":{"applies":true,"extra_orders":1,"period_days":14,"ctor_now":7.143,"ctor_needed":7.44,
               "orders_base":15.4,"clicks_base":213,"reason":null,"ctor_reason":null},
 "basis":{"key":"prior","label":"ước tính chung","detail":"…","volume_estimate":true},
 "warnings":[{"type":"floor","sku","kind","floor","min_unit_price","lines"},{"type":"spend_cap",…},…],
 "breach":false,
 "details":{ …the kind's own figures, see below… }}
```
- **Driver** (B-3): voucher AOV+CTOR · combo AOV+CTOR · add_on AOV · gift CTOR+orders · product_discount /
  price / flash_sale CTOR+orders · ads spend+GMV+ROAS · title views+CTR · cover CTR · description CTOR ·
  variation_set AOV+CTOR · affiliate affiliate_orders · price_display CTR+CTOR · hide/relist views. CTOR =
  orders ÷ clicks everywhere. `after_p50` is `before × (1 + P50 lift)` when the lift is on that metric.
- **delta** is per month vs doing nothing; bands are P10 / P50 / P90. A basket lever (voucher, combo,
  add_on, variation_set) has `orders = 0` with `orders_note`. When `basis.key = insufficient` every band
  is `null`. **B-7.1**: a listing without giá vốn -> `profit_status:"chua_tinh"`, `cost_known:false`,
  `delta.profit`, `certain_profit` and margins `null`, warning `cost_unknown {items[]}`; GMV/orders stay.
- **cost** (B-7.2): combo = discount per combo × expected combos (`per_unit`, `expected_units`,
  `expected_units_basis` history|minimum_one); voucher = cost at expected usage over `period_days`;
  add_on = discount on orders already holding both; gift = gift cost × qualifying orders; discount/price =
  profit lost at the same volume; ads = Δ spend / month; affiliate = Δ commission + `sample`
  `{qty,unit_cost,ship_fee,total}` (giá vốn + đóng gói + ship).
- **break_even** (B-7.5): `extra_orders` over `period_days` and `ctor_needed` = (orders + extra) ÷ clicks of
  the same scope and pace ("≥ 18 đơn, CTOR ≥ 2,71 %"). add_on adds `attach[]` `{item_id, attach_rate_now,
  attach_rate_break_even, extra_attaches}`. `applies:false` for listing / ads / affiliate.
- **basis** (B-3): `product_history` (this product's days with / without a price cut, ≥5 days each, ≥10
  orders) · `shop` (the other products' median, or the shop's measured calibration) · `prior` (general
  estimate) · `insufficient`. Labels: "từ lịch sử sản phẩm", "của shop", "ước tính chung", "không đủ dữ liệu".
- **warnings** never block: `floor`, `spend_cap` (`cap_rule:"daily_marketing_cap"`, the shop's "trần chi
  marketing / ngày" from Cài đặt › Mục tiêu — the plan's `ads_daily_cap`), `cost_unknown`, `floor_unknown`,
  `profit_unknown`, `note`, `refused`.
- **details** per kind: voucher `qualifying_orders,total_orders,voucher_cost_scenario,usage_limit,usage_capped,
  per_user_limit,days,voucher_scope,expected_qualifying_orders,…`; combo `lines[] (price, discount, fees,
  contribution, floor per line), list_value, value_now, combo_discount, savings_pct, buyer_pays, platform_fees,
  cogs, packaging, gift_cost, contribution, margin_pct, existing_combo_baskets, target`; add_on `addons[]
  {price_before, price_after, discount_pct, limit_per_order, margin_pct, below_floor, orders_with_both_today,
  attach_rate_now, discount_cost_on_existing, break_even_extra_attaches, attach_rate_break_even,
  aov_lift_at_break_even}`; gift `gift {cost_per_gift, qualifying_orders, gift_cost_window, stock,
  units_used_in_window, stock_covers_window, stock_note, trigger, break_even_extra_orders,
  margin_before_pct, margin_after_pct}`; discount / price / flash `skus[] {sku, list_price, price_before,
  price_after, margin_pct_before, margin_pct_after, orders, profit_delta_same_volume, floor_*}`;
  variation_set `new_variations[] {name, price, pack_count, price_per_unit, margin_pct, margin_label}`; ads
  keywords `keywords[] {keyword, bid, match, volume, difficulty, cpc_min, cpc_max, bid_below_cpc_min,
  own_report}`; cover `overlay`.

### POST `/builder/choose` -> `201`
Same as `/v1/.../recommendations/manual`: `{id, code:"JC-2611-0007", status (sent for the seller, draft for
Ops), origin:"manual", position, product_queue, primary, versions[] (chosen first, `chosen:true`;
refused ones `status:"refused"`), card}` plus `outcome` (the chosen version's outcome). Demo hides model
internals in `card`; Ops sees the full card. The chosen version must be buildable (`422
reco_manual_invalid`). A floor / spend-cap breach -> `422 reco_breach_not_acknowledged` with `breaches[]`
(`{"type":"floor","sku","floor","min_unit_price"}` / `{"type":"spend_cap",…}`): the web shows the P91
"Vẫn tiếp tục" dialog and re-sends with `acknowledge_breaches:true` (stored on the card with who / when).
Ops audit action `builder_choose`.

## 5. Keywords and LLM drafts

### GET `/builder/products/{item_id}/keywords`
```json
{"item_id":"1001","title":"…","title_chars":33,"max_title_chars":100,
 "sources":[{"key":"title","label":"Tiêu đề hiện tại","present":true,"count":2,"reason":null},
            {"key":"suggestion",…},{"key":"competitor",…},{"key":"ads","present":false,"count":0,"reason":"Báo cáo từ khoá quảng cáo chưa có dòng nào cho sản phẩm này."}],
 "keywords":[{"keyword":"găng tay","sources":["title","competitor"],"volume":5000,"difficulty":40,"cpc_min":500,"cpc_max":900,
   "volume_status":"ok","in_title":true,"role":"chinh","competitor_titles":4,
   "ads":{"spend":90000,"clicks":40,"orders":3,"gmv":270000,"roas":3.0,"basis":"đơn đã đặt"}}]}
```
Sources: `title` (the product's keyword seeds + title phrases with numbers), `suggestion` (related rows of the
seeds' lookups), `competitor` (2-3-word phrases shared by most top search titles), `ads` (the shop's ads
keyword report). A source Juli does not store is `present:false` with its `reason`; nothing is invented. A
keyword never looked up has `volume:null`, `volume_status:"chua_tra"`. Sorted by volume, highest first. The
public market tables may be closed to the role: those sources then come back absent with
`"Không đọc được dữ liệu thị trường…"`.

### POST `/builder/drafts/title` `{item_id, keywords[≤12], count 2-4}`
`{"item_id","current_title","model","max_chars":100,"drafts":[{"title","chars","keywords":{"covered":[…],"missing":[]},"late_keywords":[…],"note"}],"dropped":[{"text","reason"}],"warnings":[]}`.
Every draft ≤100 chars, holds every ticked keyword, has no banned term, and no certification / ingredient /
health claim, price or percent the product's facts do not state; failing ones are listed in `dropped`.
### POST `/builder/drafts/cover` `{item_id, count}`
`{"concepts":[{"overlay":{CoverOverlay fields},"variation_id","hook_text","rationale"}],"dropped":[],"layouts":[…],"note":"Ảnh thật … giữ nguyên; chỉ thêm chữ."}`.
Prices / % / voucher / unit price are filled from the product's own numbers, not by the model; the overlay
goes straight into a `cover_image` version. Rendering is the content engine's CoverVariant (outside this API).
### POST `/builder/drafts/description` `{item_id, count}`
`{"drafts":[{"first_line","chars","note"}],"dropped":[],"max_chars":500}` (fill via Connector as in P91 D-13).
- **Errors**: `503 {"code":"llm_off","message":"LLM tắt","reason":"switch_off|not_configured|consent|provider|bad_output"}`
  when the model is off (`SHOPEE_BUILDER_LLM=0`, no `OPENAI_API_KEY`, no `llm_processing` consent, provider
  failure); `422 llm_no_valid_draft` with `dropped[]`. Calls go through the OpenAI gate (`llm_call_log`).

## 6. Changes to existing contracts

- `combo_multi` now takes 2-6 products (P91 `/recommendations/compare|manual` limit 3 -> 6).
- New change kind `ads_keywords` (family ads, no read-back, no preset lift) and per-kind inputs on
  existing kinds (`add_on.inputs.addons`, `gift.inputs.gift/trigger`, `*.inputs.variations`); P91
  inputs still work.
- `manual.build_variant` refuses an excluded listing (`item_excluded:<id>`).
- `GET /overview` -> `gmv.excluded_gmv`; `GET /matrix` -> `excluded` (see §1).
- Thông số shop template: two new SKU columns (16 total); `shop_rules` keys `excluded`, `exclude_reason`.
- Limits to know: a variation with no order in the 30-day window has no cost key, so `combo`,
  `product_discount`, `price`, `flash_sale` on it are refused (`variation_unknown…`); `variation_set` and the
  variations endpoint price it from the rules instead.

## 7. B-8 Seller Demo parity (read-only, own shop, no buyer data)

| Demo | Ops mirror | Content |
|---|---|---|
| `GET /keywords?min_volume=` | `GET /keywords` | Từ khóa board: seeds, volume, difficulty, CPC, coverage, ads keywords |
| `GET /dashboard/products?order_type&period_from&period_to&limit` | `…/products` | Sản phẩm: funnel per product for one export period, flags, 12-month history |
| `GET /dashboard/flows?from&to&order_type` | `…/flows` | GMV by traffic flow (Thẻ sản phẩm / Trang shop …) |
| `GET /dashboard/ads?from&to&order_type` | `…/ads` | Quảng cáo: cost / orders / ROAS by ad type, monthly + daily, low-ROAS alert |
| `GET /dashboard/promotions?from&to&order_type` | `…/promotions` | Khuyến mãi / voucher programme timeline |
| `GET /orders` (new) | `GET /orders` (new) | Đơn hàng |
| (existing) `GET /matrix`, `/ranking`, `/products/{id}` | same | product × source matrix and product page |

The dashboards and keywords answer exactly what the Ops routes answer (same services,
`services/ops/shopee_dashboards`, `services/shop_keywords`), scoped to the seller's shop. The product ×
traffic-source matrix is `GET /matrix` (rows carry `flows`, `levers`, `ads`, `card_children`), already a
Demo route. Ops keyword *writes* (generate seeds, upload metrics) are not exposed to the seller.

### GET `/orders`
Query: `period` 7d|30d|90d|month|custom (30d), `month`, `from`,`to`, `as_of`, `status` (delivered |
refunded_accepted | in_transit | cancelled | refunded_not_received), `lever` (promotion | flash_sale |
voucher | combo | affiliate), `sort` date|gmv|contribution, `limit` (≤500, 100), `offset`.
```json
{"platform":"shopee","order_basis":{"key":"confirmed","label":"Đơn đã xác nhận"},"window":{…},"sort":"date",
 "count":13,"offset":0,"limit":100,"by_status":{"delivered":12,"cancelled":1},
 "privacy":"Mã đơn là khoá băm rút gọn; không có thông tin người mua.",
 "orders":[{"order_key":"0000000000a1","ordered_on":"2026-10-07","status":"delivered","lines":1,"units":1,
   "items":["1001"],"levers":["voucher"],"gmv":90000,"voucher":2000,"promo_discount":10000,"combo_discount":0,
   "buyer_paid":88000,"fees":18000,"fee_source":"formula","cogs":30000,"contribution":38000,
   "income":{"payout":65000,"fees_total":18000,"refund":null,"net_shipping_cost":0}}]}
```
`order_key` = the first 12 characters of the keyed hash the order lines are stored under (never a
platform order id, no buyer field anywhere). `contribution` is `null` for an order outside the profit base
(cancelled, in transit) or with a missing cost / fee. `income` is `null` when the income export has no row.

## 8. B-9 price and margin on every product table

`GET /matrix` rows and `GET /ranking?kind=products` rows (Demo and Ops) gain: `price_min`, `price_max` (selling
price per unit that buyers paid in the window; the catalogue's current price when nothing sold),
`list_price` (highest list price of the window's lines, else the catalogue's), `price_basis`
(`order_lines` | `catalogue` | `null`) and `margin_basis` (`"theo đơn thực tế"` every order has an Income row
and a stated giá vốn · `"ước tính"` fee formula or assumed cost stands in · `"chưa tính"` no margin).
`GET /matrix` also returns `idle_products[]` = active, non-excluded listings with no order in the window
(`product_id`, `name`, price fields, `margin_basis:"chưa tính"`), for the collapsed "N sản phẩm không có đơn
trong kỳ". The fee backtest is not part of this change.
