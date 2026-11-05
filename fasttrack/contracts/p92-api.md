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
trong kỳ". The fee backtest is in §9.4.

## 9. B-10 competitor prices ("Giá thị trường"), draft plans in order, fee backtest

Branch `fasttrack/p92-market` (backend + Connector 0.3.5 + a small web block). Plan: `p92-plan.md` B-10 / B-9.

### 9.1 Collection (Connector 0.3.5 -> ingest)
- `GET /v1/ingest/market/keywords` (ingest-token auth): `{"enabled","max_per_product":3,"due_after_days":6,
  "products":[{"item_id","keywords":[…]}],"due_keywords":[…],"last_collected":{"<keyword>":"2026-11-02"},"as_of"}`.
  Keywords = each product's 1-3 main seeds (`shop_keyword_seeds`: enabled, role `chinh` first, then `phu` /
  `thuong_hieu`, never `loai_tru`). `due_keywords` = no capture in the last 6 days. `enabled:false` (empty lists)
  unless the server switch `CONNECTOR_MARKET_SEARCH` is on (default off) and, when `CONNECTOR_MARKET_SHOP_IDS`
  is set, the shop is listed (pilot: ORY only; the Connector also gates on the explicit ORY id).
- `POST /v1/ingest/shopee/market_search` (`granularity:"period"`, start = end = capture day GMT+7, no
  `order_type`). Row: `keyword, sort ("relevancy"|"sales"), page (1-3), pos (1-based, ads counted), is_ad,
  item_id, shop_id?, shop_title?, title, price, price_min?, price_max?, price_before_discount?, discount_pct?,
  rating?, sold_monthly?, sold_lifetime?, sold_text?, image_id?` (VND; `title` / `shop_title`, not `name`: the
  privacy test forbids keys containing "name"). The keyword must be one of the shop's seeds (`422
  market_keyword_unknown`); switch off -> `403 market_search_disabled`; drift stops the dataset per version as
  for the other datasets (`409 dataset_in_drift`).
- Lands in the existing public tables, **no migration**: `market_listing_snapshots` (one row per card; ad flag,
  price range, before-discount price, shop title and image id in `extra`; `collector` = the post's `source`, a
  card key is replaced only by the same or a higher rank vendor < extension < file < api) and
  `market_keyword_snapshots` (per keyword x sort x day: cards, shops, median price, share discounted, sold
  median / P75 -- ads left out). Both tables stay Ops-only: the write and the Demo / Ops reads run in a short
  `ops_role` block (`SET LOCAL ROLE juli_ops`), the runtime role needs the same `juli_ops` membership as `/v1/ops`.

### 9.2 Giá thị trường (Demo + Ops, read-only)
- Demo `GET /v1/demo/shopee/products/{item_id}/market-price`; Ops `GET /v1/ops/shops/{id}/shopee/products/{item_id}/market-price` (Xem+).
  Query: `variation_id` (default: the variation with the lowest price per unit), `price` (a drafted selling price
  of that variation, VND -> `marker`), `as_of`.
- Lightweight builder call (no `closest`): Demo `GET /v1/demo/shopee/builder/products/{item_id}/market-range`,
  Ops `GET /v1/ops/shops/{id}/shopee/builder/products/{item_id}/market-range`.
- **Seller (Demo) body = aggregates only** (owner 2026-11-05, enforced by `market_price.seller_view`, a whitelist, and
  tested): `market` = `n_similar`, `median`, `average` (mean of the same filtered set, ads excluded), `own_vs_median_pct`,
  `own_vs_average_pct`; `marker` = `price`, `pack_count`, `price_per_unit`, `vs_median_pct`, `vs_average_pct`; plus unit,
  keyword, `collected_on`, `age_days`, `stale`, `own`, `note`. NO `closest`, `keywords`, `p25`, `p75`, `position`, titles,
  shop names or other shops' item ids. Ops keeps the full body (adds `market.average` too).
- Tenant rule: the product must belong to the caller's shop (`404 not_found` otherwise); the public market rows are read
  in a short `ops_role` block inside the service and only aggregates of them leave it on the seller route.
```json
{"item_id":"1002","name":"…","available":true,"reason":null,"reason_text":null,
 "keyword":"nước rửa chén","collected_on":"2026-11-03","age_days":2,"stale":false,"stale_after_days":14,
 "keywords":[{"keyword","collected_on","age_days","stale","n_cards":58,"n_similar":18}],
 "unit":{"key":"ml","label":"500 ml","per_label":"giá / 500 ml"},
 "own":{"variation_id":"","selling_price":90000,"price_min":90000,"price_max":90000,"pack_count":1,"price_per_unit":90000},
 "market":{"n_similar":18,"median":85000,"p25":80000,"p75":92500,"own_vs_median_pct":5.9,"position":"within"},
 "closest":[{"item_id","name","shop_name","price","price_min","price_max","pack_count","quantity","price_per_unit",
   "sold_monthly","sold_lifetime","position","is_ad":false,"similarity":0.67}],
 "marker":{"price":88000,"pack_count":1,"price_per_unit":88000,"position":"within","vs_median_pct":3.5},
 "note":"…"}
```
- **Matching**: the newest page-1 capture of each of the product's main keywords; ads, the product's own item and
  cards without a price are dropped; the pack of every card is read from its title (`unit_price.parse`, same
  `combo N` / `set N` rule as the variation pack parser, plus `N hộp`, `N cái`, `N ml / l`, `N g / kg`, `N cuộn`)
  and only cards of the SAME unit are compared, per hộp / 100 cái / 500 ml / 100 g / cuộn (`item` = nothing
  readable: per sold unit); the card must share >= 25 % of the title words (Dice) with the product. Median / P25 /
  P75 (linear interpolation) of the per-unit price over the merged, de-duplicated cards; the 5 closest by title
  similarity then position. The product's own per-unit price = selling price / (unit quantity of its title x the
  variation's pack count).
- **Absent, never invented**: `available:false` with `reason` = `no_keyword` | `no_capture` | `no_similar` (< 3
  similar cards; `n_similar` given) | `market_closed`; `market`, `closest`, `marker` are `null`. `stale:true`
  when the newest capture is older than 14 days (the date is always shown). `position` = `below_p25` | `within` |
  `above_p75`. `404 product_not_found`, `409 reco_no_data` as the other product reads.

### 9.3 Draft plans in order (extends the P91 plan endpoints; nothing parallel)
- `GET …/recommendations/plan` (Demo + Ops): each `aggregate.products[i]` gains `steps`:
```json
"steps":{"order":["price","giam_gia","voucher","combo","ads"],"custom_order":false,"margin_basis":"…",
 "items":[{"index":1,"step":"giam_gia","step_label":"Giảm giá","card_id","code","title","change_kind","version_label",
   "margin_pct_before":31.2,"margin_pct_after":27.9,"dprofit_step_p50":-120000,"dprofit_total_p50":-120000,
   "dprofit_total_certain":-150000,"dgmv_total_p50":900000,"cost_month_total":150000,"floor_ok":true}],
 "total":{"margin_pct_before","margin_pct_after","dprofit_p50","dprofit_certain","dgmv_p50","floor_ok"}}
```
  and the aggregate gains `steps_summary.shop` `{products, dprofit_p50, dprofit_certain, dgmv_p50,
  margin_pct_before, margin_pct_after}` (the shop-wide totals: the plan's joint total, shop margin today -> after).
- **Semantics**: step *k* = the product's first *k* cards re-priced TOGETHER on the same history orders
  (`mega.evaluate_mega` stacking: new price, then the voucher on the new basket, fees recomputed once per order on
  the new buyer-paid amount with the shop's size-dependent fee formula, floor on the stacked price) - not a sum of
  the cards' own numbers. `dprofit_total_*` is Δ lợi nhuận / tháng after steps 1..k (P50 = certain + predicted;
  `certain` = same volume), `dprofit_step_p50` = what step k adds over k-1; the last step equals the product's
  joint total. `margin_pct_*` = margin of the product's orders at the certain layer (no volume change), from the
  joint five numbers; for cards the stacking does not model (add-on, gift, multi-product combo) derived from
  the baseline and the cards' certain profit / GMV; `null` = "chưa tính". `null` P50 = profit unknown, never 0.
- **Order**: the plan order of the product's cards. A card joins at its canonical step slot
  (price/flash sale -> giảm giá -> voucher -> combo/mua kèm/quà tặng -> ads, other kinds last); positions are
  renumbered. `custom_order:true` when the plan order differs from canonical. Cards of different products stay
  independent (each product its own `steps`); shop-wide levers are not steps.
- `POST …/recommendations/plan/cards/{card_id}/move` `{"position": 1..30}` (1-based among the plan's cards,
  clamped) -> the re-aggregated plan (same payload as add / remove). Demo (writable shop) and Ops (Vận hành,
  audit `reco_plan_move_card`). `404 reco_card_not_in_plan`, `404 reco_plan_not_found`. Removing a card
  (`/remove`) and every other edit re-evaluate all prefixes. Nothing executes before the confirm (P91 D-6).

### 9.4 Fee-formula backtest (B-9, Ops only)
`GET /v1/ops/shops/{id}/shopee/fee-backtest?days=90&as_of=` (Xem+; `days` 7-180):
```json
{"window":{…},"days":90,"orders_in_profit_base":240,"orders_with_income":120,"target_pct":1.0,
 "orders_compared":118,"orders_skipped":{"no_income":120,"no_fee_status":0,"no_formula":2},
 "mean_abs_gap":3150.0,"mean_gap":-420.5,"mean_formula_fees":18200.0,"mean_actual_fees":18620.5,
 "mean_buyer_paid":210000.0,"pct_of_buyer_paid":0.84,"within_target":true,
 "worst":[{"order_key":"0000000000a1","formula_fees":…,"actual_fees":…,"gap":…,"buyer_paid":…}],"definition":"…"}
```
Per order with an Income row: `gap = formula - actual` (formula = the same lines with income / reported fees
stripped, the shop's schedule on the order date, per-order fees split once per order; actual = fixed + service +
payment + PiShip + NTTD from the Income row). `pct_of_buyer_paid` = Σ|gap| / Σ buyer-paid; the contract's
target is <= 1 % (`within_target`; `null` when nothing is comparable). `worst` = the 5 largest |gap| (order key =
the first 12 characters of the keyed hash; no buyer field). `409 reco_no_data` without Shopee numbers.
