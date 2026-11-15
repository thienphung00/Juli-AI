# P101 spec: TikTok Shop promotions (BMSM, Bundle Deal, Flash sale) mapped from Juli's Shopee levers

Date: 2026-11-15. Decisions D86 / P101. Docs only: no live calls, no credentials.
Confidence: **(doc)** = in the docs mirror (`partner_documents/_raw`, crawled 2026-07-21) or bundled OAS; **(probe)** = not confirmed, needs the sandbox/Connector probe; **(recon)** = Seller Center form not documented, needs a read-only recon.
Shopee side read at git ref 1bdabc56 (`shopee_recommendations/bundle_tiers.py`, `listing_combo.py`, `evaluate.py`, `shopee_builder/specs.py`, `kinds.py`, D84, D85.11, p97 recon).

## 0. Summary and shared rules

| Shopee lever (change_kind / builder spec) | TikTok | Route | Capability | Write | Read-back |
|---|---|---|---|---|---|
| Combo khuyến mãi: `bundle_deal` / `ComboSpec` (kind `combo`) | Buy More Save More (BMSM) | api | `promo_bmsm` | `POST /promotion/202309/activities` (`BUY_MORE_SAVE_MORE`), `PUT .../{id}/products`, `POST .../{id}/deactivate` | `GET .../activities/{id}`, `POST .../activities/search` |
| Listing combo mới: `listing_combo` / `ListingComboSpec` | Bundle Deal (fixed combo price) | connector | `bundle` | none (no API); Connector fills seller-vn.tiktok.com, seller clicks Lưu | Connector saved signal + DOM read (no API read) |
| Flash Sale của shop: `flash_sale` / `FlashSaleSpec` | `FLASHSALE` activity | api | `promo_flash_sale` | same endpoints, `activity_type=FLASHSALE` | same |

Common (all three), from the project contract:
- Seller approval is the only human step (engine card or Tự tạo phương án). After approval API writes run on schedule inside guardrails: price floor (biên tối thiểu), max discount, spend cap, per-platform/action/shop kill switch, production write flag. Every write is read back and verified.
- Scopes: write `seller.promotion.write`, read `seller.promotion.info` (doc). The repo's known scope list lacks `seller.promotion.write`: Juli's app scope must be expanded and sellers re-authorised (W0 G). The production write allowlist has no promotion path (W0 F): needs allowlist expansion plus ADR before any production write.
- Currency VND. API money fields are strings; whole đồng (probe: amount format, docs examples show decimals and "70500").
- Seller Center link for any manual step: `https://seller-vn.tiktok.com/promotion/marketing-tools/management` (already in `lever_flows/promotion.py`).
- UI: Vietnamese, short labels, no captions or explanations; missing value shows "—". Labels (probe for exact TikTok VN names): "Mua nhiều giảm nhiều", "Bundle Deal", "Flash sale".
- Activity title (TikTok): unique across the shop's activities, at most 50 chars (doc). Juli title = `<name ≤ 30> · JC-<card code>` so that the title is Juli-owned and searchable (`activity_title` exact keyword, no fuzzy match, doc).
- Time: `begin_time`/`end_time` Unix seconds; `begin_time` must be greater than now (17029005). Juli computes in VN time (UTC+7). Seller-facing hours have minute precision at most (Shopee forms use hours).
- Webhook 39 (doc): fires on NOT_START→ONGOING, ONGOING→EXPIRED, any→DEACTIVATED, for FIXED_PRICE, DIRECT_DISCOUNT, SHIPPING_DISCOUNT, BUY_MORE_SAVE_MORE, FLASHSALE (SEA incl. VN). Payload: `type=39`, `tts_notification_id`, `shop_id`, `timestamp`, `data{activity_id, update_time, activity_type, product_level, status ∈ ONGOING|EXPIRED|DEACTIVATED}`. It does not carry NOT_EFFECTIVE (platform terminated) or DRAFT: those come only from polling.

### 0.1 TikTok limits used below (all (doc) unless marked)

| Limit | Value | Source |
|---|---|---|
| Activity types | FIXED_PRICE, DIRECT_DISCOUNT, FLASHSALE, SHIPPING_DISCOUNT, BUY_MORE_SAVE_MORE, BUY_X_GET_Y | create |
| Statuses | DRAFT, NOT_START, ONGOING, EXPIRED, DEACTIVATED, NOT_EFFECTIVE (platform terminated) | search |
| product_level | PRODUCT (SPU, `skus` must be `[]`), VARIATION (SKU level), SHOP (all products) | create |
| Title | unique, ≤ 50 chars (17029002, 17029004) | create |
| Time | `begin_time` > now; period too short / too long / flash too long: **numbers not documented** (17029006/7/8) | create (probe) |
| Begin time edit | not allowed once set/started (17029011) | update |
| `participation_limit[].type` | `BUYER_NO_LIMIT` (default) or `BUYER_LIMIT_ONLY_ONE` | create |
| `target_user_info.user_type` | ALL_USER, SHOP_NEW_CUSTOMER, SHOP_EXISTING_CUSTOMER, SHOP_REPEAT_CUSTOMER | create |
| BMSM `discount.bmsm_discount.details[]` | max 2 tiers; `tier` 1-based; `threshold_type` and `type` identical across tiers; tier 2 threshold and value strictly greater than tier 1 | create |
| BMSM `threshold_type` | `MINIMAL_ITEM_QUANTITY` (integer) or `MINIMAL_ORDER_AMOUNT` (local currency, 2 decimals) | create |
| BMSM `type` / `value` | `PERCENTAGE_OFF` (integer percent) or `AMOUNT_OFF` (currency, 2 decimals) | create |
| Add products | `PUT .../{id}/products`: ≤ 300 products per call, ≤ 300 SKUs per call across products, ≤ 10 000 products+SKUs per activity (17029025, 17029113 "exceeds max of the promotion") | update products |
| Product fields | `id`, `activity_price_amount` (FIXED_PRICE/FLASHSALE at PRODUCT level), `discount` (DIRECT_DISCOUNT; "10" = 10 % off), `quantity_limit`, `quantity_per_user` in [1, 99] or -1; `skus[]` same fields; VARIATION level: product-level quantities must be -1 | update products |
| Decrease rule | existing quantity_limit / per-user limit cannot be lowered (17029058, 17029065) | update products |
| Ongoing flash sale | products/SKUs cannot be updated or removed (17029047, 17029048) | update, remove |
| Expired / deactivated | products cannot be updated (17029012, 17029010) | update products |
| Conflicts | product/SKU cannot be in two ONGOING/NOT_START activities (17029022); another conflicting promotion (17029079, 17029103); already in another BMSM in the period (17029104) | update products |
| Price rules | flash deal price ≤ lowest price customers paid in the last 30 days (overview); discount outside the allowed range (17029020/21 above, 17029062/63 below): range "varies by product and region", **no numbers** | overview, errors (probe) |
| Stock | quantity above available stock (17029018/19); non-sellable product (17029064); invalid product status (17029056); auction products not eligible (17029067); invalid category (17029060) | update products |
| Deactivate | `POST .../{id}/deactivate` for ongoing or upcoming; returns `activity_id, title, status, update_time` | deactivate |
| Republish | `POST /promotion/202607/activities/{id}/republish` (`begin_time`, `end_time`): only FIXED_PRICE, FLASHSALE, DIRECT_DISCOUNT, expired or deactivated within 7 days; **not BMSM**; error 17003243 | republish |
| Read | Get Activity: products not returned for FIXED_PRICE/DIRECT_DISCOUNT/FLASHSALE ended > 180 days; `activity_commands` (e.g. IMMUTABLE = not editable or deactivatable). Search: `page_size` 0-100 (50 default), `page_token + page_size < 10 000` (17029059), filter `status`, `activity_title`, `activity_type` | get, search |
| Exclusivity | flash + product discount on a product: only the flash price is effective; flash + platform campaign: the campaign price always wins; coupons always apply | overview |
| Rate / transient | 17029054 "limit the request frequency", 17029055 timeout, 36009003 internal (retry), platform throttle 100005; numeric limits undocumented | errors, W0 E (probe) |
| Request id | docs list 17029027 "Empty RequestSerialNo" and 17029045 "Duplicated RequestSerialNo" but no such field in the request schema: no client idempotency key documented | errors (probe) |

---

## 1. Combo khuyến mãi (Shopee `bundle_deal`) to Buy More Save More (`promo_bmsm`, api)

### 1.1 Shopee model (what Juli holds)

`bundle_deal` card, kind label "Combo khuyến mãi (các bậc)", family combo, target metric AOV, sim kind `combo_pack`. Builder `ComboSpec`: `name` ≤ 25, `item_ids` 1-100 (no per-item quantity or variation), `discount_type` pct | amount | special_price, `tiers[{qty 2-9999, value}]` 1-5 rows, `purchase_limit` (combos per buyer, ≤ 999 999 999), `start`/`end` (+ `start_hour`/`end_hour`). Rules in code: effective discount ≤ 90 %, special price ≥ 1 000 đ and below N × average unit price, tiers strictly increasing in effective percent.

### 1.2 Field mapping

| Shopee field | TikTok field | Rule / difference |
|---|---|---|
| activity kind `combo` | `activity_type=BUY_MORE_SAVE_MORE` | direct |
| `name` (≤ 25) | `title` (≤ 50, unique) | append ` · JC-<code>`; keep name ≤ 30 |
| `item_ids` (1-100) | `PUT products` `products[].id`, `product_level=PRODUCT` | ≤ 300 per call; SKU-level (`VARIATION`) only if the card lists variations (probe: BMSM supports VARIATION) |
| `discount_type=pct` | `type=PERCENTAGE_OFF` | `value` must be an integer percent: Shopee allows decimals, Juli rounds down and shows the rounded value before approval |
| `discount_type=amount` | `type=AMOUNT_OFF` | `value` = currency off. Per unit or per order total: (probe) |
| `discount_type=special_price` | none | no fixed-price tier on BMSM. Juli converts to `AMOUNT_OFF = N × avg price - price` only when the seller accepts the converted preview; else "Không hỗ trợ". Real fixed price = Bundle Deal (section 2) |
| `tiers[].qty` | `details[].threshold_value` (string) with `threshold_type=MINIMAL_ITEM_QUANTITY` | TikTok quantity bounds (min / max) (probe) |
| `tiers[].value` | `details[].value` | tier 2 threshold and value > tier 1 |
| tiers 1-5 | `details[]` max **2**, `tier` 1-2 | tiers 3-5 have no counterpart: engine proposes at most 2; builder refuses more |
| `MINIMAL_ORDER_AMOUNT` | no Shopee counterpart | not used by Juli v1 |
| `purchase_limit` (number) | `participation_limit[0].type` | only none (`BUYER_NO_LIMIT`) or one (`BUYER_LIMIT_ONLY_ONE`); other numbers refused |
| `start`/`end`/hours | `begin_time`, `end_time` (Unix s) | `begin_time` > now; min / max period (probe) |
| (none) | `target_user_info.user_type` | Juli sends `ALL_USER` |
| (none) | `duration_type` | `NORMAL` (INDEFINITE valid only for SHIPPING_DISCOUNT) |
| inline voucher / gift in a Shopee basket | `discount.gift_discount` (GWP) | out of scope P101 |
| `bundle_deal` generated card `tier2_pct`, `tier3_pct` | `details[]` tier 1, tier 2 | tier3 dropped on TikTok |
| `purchase_limit` per-product quantity | `quantity_limit`/`quantity_per_user` on products | BMSM product quantity fields: required or ignored (probe) |

### 1.3 Validation before approval (builder and engine; all must pass)

| # | Rule | Source | Error line shown to the seller |
|---|---|---|---|
| B1 | 1-300 products per call (split into batches), ≤ 10 000 in total | doc | "Tối đa 300 sản phẩm mỗi lượt." |
| B2 | 1-2 tiers | doc | "Chỉ có tối đa 2 mức ưu đãi." |
| B3 | Tier 2 threshold and value both greater than tier 1 | doc | "Mức sau cần mua nhiều hơn và giảm nhiều hơn mức trước." |
| B4 | Same threshold type and same discount type in both tiers | doc | "Hai mức cần cùng loại giảm giá." |
| B5 | `PERCENTAGE_OFF` value an integer; `AMOUNT_OFF` whole đồng | doc | "Mức giảm phải là số nguyên." |
| B6 | Effective discount per tier ≤ shop `max_discount_pct` (per-SKU cap, smallest applies) and ≤ 90 % | rules | "Mức giảm vượt mức tối đa của shop." |
| B7 | Per tier, per SKU: unit price after discount ≥ price floor (biên tối thiểu, giá vốn known) | rules | "Giá sau giảm thấp hơn biên tối thiểu." |
| B8 | Spend cap: estimated discount cost (qualifying orders of the window, as `eval_bundle_tiers`) ≤ cap | rules | "Chi phí giảm giá vượt ngân sách." |
| B9 | No product already in another ONGOING/NOT_START BMSM that overlaps the window (read `activities/search` + `GET`) | 17029104 | "Sản phẩm đang có Mua nhiều giảm nhiều khác." |
| B10 | No overlap with another Juli group on the same SKU and field (one live value, section 1.5) | contract | "Sản phẩm đang có ưu đãi khác cùng thời gian." |
| B11 | Product sellable, in stock, not auction, category valid (Search Products read) | 17029064/56/67/60 | "Sản phẩm không đủ điều kiện." |
| B12 | `begin_time` ≥ now + lead; end after begin; period within TikTok min/max and Juli cap (30 days, existing `MAX_DURATION_DAYS`) | doc / probe | "Thời gian chạy không hợp lệ." |
| B13 | Title unique (search by `activity_title` first) | 17029004 | (silent: Juli renames with suffix) |
| B14 | Not `special_price` without an accepted conversion | mapping | "Không hỗ trợ giá đặc biệt." |
| B15 | Seller connected, scope `seller.promotion.write` granted, kill switches and production write flag on | contract | "Cần kết nối lại TikTok Shop." / "Tạm tắt tự động." |
| B16 | Products without cost known: floor unknown, card refused for auto write | D18 | "Thiếu giá vốn." |

### 1.4 Execution sequence

| Step | Action | Notes |
|---|---|---|
| 0 | Idempotency key = `sha256(card_id + group_id + step + payload_hash)`; stored with the step row. TikTok has no documented key, so Juli dedupes by title token `JC-<code>` | before any create, search `activity_title`; if found with Juli token, adopt it (timeout-safe) |
| 1 | Create: `POST /promotion/202309/activities` body `{title, activity_type, product_level, begin_time, end_time, participation_limit, discount.bmsm_discount.details, target_user_info}` | state applying; returns `activity_id`, `status` (example shows ONGOING, update example shows DRAFT: probe which status a new activity has before products) |
| 2 | Add products: `PUT .../{id}/products`, batches ≤ 300, sequential | partial add: section 1.6 |
| 3 | Read back: `GET .../{id}` (and `activities/search` by title to confirm uniqueness) | state verifying; compare fields below |
| 4 | Start: automatic at `begin_time` (no start endpoint); webhook 39 ONGOING, else poll | verified once read-back matches AND status ∈ NOT_START/ONGOING |
| 5 | Stop (end early or rollback): `POST .../{id}/deactivate` | ongoing or upcoming only; then read back status DEACTIVATED |
| 6 | Edit a live Juli BMSM (tier or products) | `PUT /activities/{id}` and `PUT .../products` (probe whether BMSM ongoing edits are allowed; flash is not). If not allowed: deactivate and create a new one in the next group |

Read-back compared: `activity_type`, `title`, `product_level`, `begin_time`, `end_time` (exact), `status`, `participation_limit[].type`, `target_user_info.user_type`, `discount.bmsm_discount.details[]` (`tier`, `threshold_type`, `threshold_value`, `type`, `value`, numeric compare after decimal normalisation), the product id set (equals the approved set; extra or missing = mismatch), per-product `quantity_limit`/`quantity_per_user` when sent. If Get Activity does not return `products` for BMSM, the product check uses `PUT` response `total_count` plus a Seller Center check (probe).

Timing: create+add+verify finishes at least `lead` before `begin_time` (default 15 minutes, owner may change; `begin_time` > now is the only doc rule). Group: all members use the same `begin_time`; all must be verified NOT_START by `begin_time - 2 min`; every member must be ONGOING by `begin_time + 15 min`, else the whole group rolls back (deactivate all members, in reverse order of creation).

### 1.5 Conflicts and exclusivity

| Case | TikTok behaviour | Juli rule |
|---|---|---|
| BMSM vs BMSM on same product, overlapping | rejected, 17029104 | validation B9; the second card waits as queued for the next group |
| BMSM vs product discount (FIXED_PRICE / DIRECT_DISCOUNT) | 17029022 says a product cannot be in two ONGOING/NOT_START activities; overview says only discount vs flash resolve by priority; BMSM vs discount stacking not documented | (probe) until probed treat as exclusive: one live value per SKU per field, second card goes to the next group |
| BMSM vs flash | not documented | (probe); default exclusive |
| BMSM vs platform campaign | campaign price wins over seller promotions for flash; BMSM (probe) | no API read of campaign registration (W0 A.1): read-back cannot see it; measurement flags orders with `platform_discount > 0` |
| BMSM vs coupon / voucher | coupons always apply | not exclusive; measurement subtracts voucher effect (section 1.7) |
| Overlap of two Juli cards | n/a | the group planner serialises: `scheduled_for` of the later card = end of the earlier + 0 |
| Seller's own activity on the same product (created in Seller Center) | read by `activities/search` | not edited by Juli; card queues or errors "Sản phẩm đang có ưu đãi khác." |

### 1.6 States and error handling

State machine (contract): queued → applying → applied → verifying → verified / retrying → failed → rolling_back → rolled_back.

| Event | Handling | Card line |
|---|---|---|
| 17029054 / 100005 (rate) | backoff with jitter, per-shop serial queue, counts as one retry only after 3 deferrals; state retrying | "Đang thử lại." |
| 17029055 / 36009003 (timeout / internal) | search by title token first (it may have been created), then retry once | "Đang thử lại." |
| 17029004 duplicate title | rename with new suffix, 1 retry | silent |
| 17029005 begin earlier than now | re-plan `begin_time` once (+lead), else failed | "Quá giờ bắt đầu." |
| 17029006/7 period too short/long | failed, no retry (probe numbers) | "Thời gian chạy không hợp lệ." |
| 17029104 / 17029103 / 17029079 / 17029022 conflict | failed, rollback created activity, queue card for next group | "Sản phẩm đang có ưu đãi khác." |
| 17029020/21/62/63 discount range | failed, no retry | "Mức giảm ngoài khoảng TikTok cho phép." |
| 17029018/19 stock | failed | "Tồn kho không đủ." |
| 17029025 / 17029113 product count | failed | "Quá số sản phẩm cho phép." |
| 17029035 ShopRisk check failed | failed, ops alert | "TikTok từ chối. Liên hệ hỗ trợ." |
| 17029009 / 17029028 / 17029069 not found or not ours | failed | "Không tìm thấy khuyến mãi." |
| Partial product add (batch k fails after batch 1..k-1 ok) | read back products; retry only missing ids once; still missing = mismatch → rollback (deactivate) | "Đã hoàn tác." |
| Read-back mismatch | 1 retry (re-PUT or re-read after 60 s), then rolling_back → rolled_back, card error | "Số liệu không khớp. Đã hoàn tác." |
| Deactivate fails | retry 3x with backoff; ops alert; card stays rolling_back | "Đang hoàn tác." |
| Webhook 39 EXPIRED | state done; start measurement closing | "Đã kết thúc." |
| Webhook 39 DEACTIVATED not initiated by Juli, or read shows status NOT_EFFECTIVE, or `update_time`/fields differ from Juli's last write | seller edit: **contaminated**, keep the seller's value, stop writing, close measurement as `chua_ket_luan` | "Bạn đã sửa trên TikTok." |
| `needs_reauth` (token refresh fails, webhook 6/7) | pause all queued steps for the shop; resume automatically after re-auth, re-validating B15 and time (if `begin_time` passed: re-plan or fail "Quá giờ bắt đầu.") | "Cần kết nối lại TikTok Shop." |
| Kill switch (platform/action/shop) or write flag off | no new write; applied activities stay; rollback still allowed | "Tạm tắt tự động." |

Webhook handling: ACK < 3 s, dedupe on `tts_notification_id`, webhook only triggers a read-back; polling reconcile every ≤ 15 min stays the backstop (W0 C).

### 1.7 Measurement

| Item | Rule |
|---|---|
| Unit | per card / group, frozen baseline: same SKUs, 14 days before `begin_time` (frozen at approval), per D85.4 |
| Active window | `[begin_time, min(end_time, deactivate time)]` from read-back and webhook 39 `update_time` |
| Attribution | order line (`GET /order/202507/orders`): `sku_id`/`product_id` in the activity product set AND order `create_time` in the window AND not cancelled. No promotion id on order lines (W0 B.5 gap) |
| Qualifying order | units of eligible products in the order ≥ tier threshold (line items repeat per unit: count identical rows, probe); expected tier from the activity read |
| Discount amount | `line_items[].seller_discount` is one lump (promotion, voucher, BMSM, bundle). Reconstruct: expected BMSM discount from tier and `original_price`; the remainder = other seller discount (voucher via coupon `usage_stats`). Label "ước tính" in data, not on screen |
| Metrics | orders, units, GMV, AOV (target metric), seller-funded discount cost, margin after fees (finance statement after settlement) |
| Flags | `platform_discount > 0` on a line = platform campaign overlapped; seller edit contaminated (1.6); activity deactivated early |
| Result | `chua_ket_luan` if < 20 orders after or another change touched the SKU (Shopee rule reused) |

---

## 2. Listing combo mới (Shopee `listing_combo`) to Bundle Deal (`bundle`, connector)

### 2.1 Shopee model and the difference

Shopee `ListingComboSpec` is a **new listing**: `title` ≤ 100, `image_refs` ≤ 9, `price` 1 000-2 000 000 000, `stock` ≥ 0, `sku` ≤ 100, `member_ids` 2-20. Estimate (`eval_listing_combo`): no new orders; demand = last-30-day orders already holding every member (baskets); P10/P50/P90 switch share 0 / 0.5 / 1; price must be below the sum of singles or change = 0; fill form not recorded.
TikTok **Bundle Deal** (owner D86) is a promotion over existing products at a fixed combo price: no new listing, so title/images/SKU/stock have no counterpart. No TikTok API (W0 A, ADR-106: "no Partner API write or read"); Create Activity enumerates no Bundle Deal type (doc).

### 2.2 Field mapping

| Shopee field | Bundle Deal form field | Status |
|---|---|---|
| `member_ids` (2-20) | products in the bundle | (recon) min/max products |
| `price` (combo price) | bundle price (fixed) | (recon) per bundle or per SKU |
| `title` | bundle name | (recon) max length, shown to buyers? |
| start/end (none in Shopee listing) | start and end time | (recon) Bundle Deal is time-boxed; Juli proposes a window like BMSM, default 30 days |
| `stock` | purchase / quantity limit | (recon) may map to a limit; otherwise "—" |
| `image_refs`, `sku` | none | no counterpart, not sent |
| per-buyer limit | purchase limit per buyer | (recon) |
| Shopee `combo_pack` estimate | same estimate (baskets holding every member) | kept; label "Bundle Deal" |

Docs gap: the Seller University index has "Buy More Save More & BXGY" (knowledge_id 7160023202432811) but **no Bundle Deal article**; every form field above is (recon). Recon is read-only in the owner's logged-in Chrome, same method as the p97 recon (stop at the password dialog).

### 2.3 Validation before approval

| # | Rule | Error line |
|---|---|---|
| C1 | 2 ≤ members ≤ TikTok max (recon) | "Số sản phẩm không hợp lệ." |
| C2 | Combo price < sum of current member prices (else change = 0) | "Giá combo cần thấp hơn tổng giá lẻ." |
| C3 | Price floor: per member, allocated unit price ≥ biên tối thiểu (allocation = pro-rata of list prices) | "Giá sau giảm thấp hơn biên tối thiểu." |
| C4 | Discount vs sum ≤ max discount (shop rule, ≤ 90 %) | "Mức giảm vượt mức tối đa của shop." |
| C5 | Members sellable, in stock, not already in another conflicting bundle/promotion (read `activities/search` for the SKU; bundle conflicts unreadable) | "Sản phẩm đang có ưu đãi khác." |
| C6 | Spend cap: estimated discount cost ≤ cap | "Chi phí giảm giá vượt ngân sách." |
| C7 | Connector paired, Seller Center tab open or openable, `bundle` kill switch and `fill_bundle` flag on | "Mở Connector để điền." |
| C8 | Price ≥ 1 000 đ | "Giá combo quá thấp." |

### 2.4 Execution sequence (no API write)

| Step | State | Detail |
|---|---|---|
| 1 | queued | approval creates a fill job (idempotency key = `card_id + group_id + "bundle"`); no auto time-of-day (a person must save), so the 15-minute group window does not apply to this member: the group starts when the API members verify; a Bundle Deal member is saved by the seller within 24 h, and API members of the same group wait for it or run without it (owner: decide, probe) |
| 2 | filled_waiting_save | Connector opens the create page, fills name, products, price, dates, limits; shows "Juli đã điền — kiểm tra rồi bấm Lưu". Never clicks Lưu/Xác nhận. Title carries `JC-<code>` if the name field allows (recon) |
| 3 | saved | Connector sees the saved signal (2.5); Juli stores the new id |
| 3b | timed_out | no save after 24 h (one reminder before); job closed |
| 4 | verified | Connector re-opens the saved bundle and compares fields (DOM read-back) |
| Stop | | seller clicks stop in Seller Center, or Juli shows the manual step; no API deactivate. Juli never rolls back a bundle by itself: rollback of the group stops the API members and marks the bundle "Dừng thủ công" (seller task) |

### 2.5 Saved signal, new id, timed_out (all (recon))

| Item | Plan |
|---|---|
| Saved signal | after the seller clicks Lưu: success toast or redirect to the bundle list/detail URL; Connector then reads the list row whose name carries `JC-<code>` (or matches name + members + dates) |
| New id | read from the detail URL or list row attribute; stored as `external_id`. Fallback: no id found → card keeps `saved` without id and measurement uses SKU + window only |
| Read-back | DOM read of the detail page: name, member ids, price, begin/end, limit; compare to the approved sheet; mismatch = "Số liệu không khớp", **no auto fix** (seller edits in Seller Center) |
| Seller edits after save | Connector reconcile (periodic, like the Shopee reconcile command) re-reads; difference = contaminated, keep the seller's value |
| timed_out | at 24 h (one reminder before): job `timed_out`, card "Quá hạn", no write was made, no measurement, group members unaffected. A save after the timeout is still adopted by the reconcile read (matched by title token) and measured from its real start (probe whether Juli wants this) |
| Anti-automation / DOM drift | Connector stops on login wall, password dialog, captcha (p97 rule); job `failed` with "Không điền được. Làm thủ công." |

### 2.6 Conflicts, errors

| Case | Handling |
|---|---|
| Bundle vs discount/flash/BMSM on same SKU | no documented rule (probe); default exclusive: next group |
| Bundle activity not visible to `activities/search` | the API conflict check cannot see it: Connector list read supplies the conflict set (recon) |
| Webhook 39 | does not list Bundle Deal: no status push; status by Connector read only |
| Connector offline / tab closed / reauth | job stays queued; `needs_reauth` pauses; resume re-fills |

### 2.7 Measurement

| Item | Rule |
|---|---|
| Window | saved start to end read from the form (DOM) |
| Attribution | order lines holding every member at the combo price signature: sum of `sale_price` across member lines in one order vs combo price within a tolerance; `combined_listing_skus` is a different feature (probe whether bundle orders show a marker) |
| Metrics | combos sold, GMV, AOV, discount cost (sum of `seller_discount` lump on member lines), switch share vs the P10/P50/P90 assumption |
| Baseline | frozen 30-day baskets (as `eval_listing_combo`) |

---

## 3. Flash sale (Shopee `flash_sale`) to `FLASHSALE` (`promo_flash_sale`, api)

### 3.1 Shopee model

`flash_sale` card, family sale, "Đăng ký Flash Sale của shop", sliders `discount_pct` 0-70, `units` 1-100 000. Builder `FlashSaleSpec`: `item_id`, `variations[{variation_id, discount_pct | final_price}]`, `units` 1-1 000 000, `slot_start`, `slot_hours` 1-72 (default 2). Generator inputs `{discount_pct, units, slot_days}`; cap `min(cap, 25)`; guards in `optimize_product/config.py`: no flash on the product in last 14 days, price ≤ lowest unit price paid in last 14 days × 0.99, 1-3 days. Estimate scales by the slot's hours and units (`_slot_share`).

### 3.2 Field mapping

| Shopee field | TikTok field | Difference |
|---|---|---|
| `item_id` | `products[].id` | one product per card; `product_level=PRODUCT` for one price, `VARIATION` for per-SKU prices |
| `variations[].variation_id` | `skus[].id` | `VARIATION` level only |
| `discount_pct` | none: TikTok FLASHSALE takes a price | `activity_price_amount = floor100(list × (1 - d))`; sending `discount` is an error (17029030/32) |
| `final_price` | `activity_price_amount` (product or SKU) | must be ≤ lowest price paid in last 30 days; Juli guard becomes 30 days (Shopee guard is 14) |
| `units` (≤ 1 000 000) | `quantity_limit` | TikTok range [1, 99] or -1 (unlimited): `units > 99` cannot be sent: use -1 and rely on a spend cap, or refuse (probe: real limit, stock reservation) |
| `per_buyer_limit` | `quantity_per_user` | [1, 99] or -1 |
| `slot_start`, `slot_hours` | `begin_time`, `end_time` | seller-created time, not a platform slot; max period "FlashSale Period Too Long" (17029008, number probe); Juli keeps 1-3 days |
| `slot_days` | derived from begin/end | |
| Shopee shop slot registration | none | no slot registry or registration |
| (none) | `participation_limit`, `target_user_info` | `BUYER_NO_LIMIT`, `ALL_USER` |
| (none) | `title` | `Flash · <name> · JC-<code>` ≤ 50 |

VN availability: webhook 39 lists FLASHSALE for SEA incl. VN (doc); creation in a VN shop (probe D.9). Stock reservation behaviour (probe; the Seller University "Campaign Reserved Stock" article concerns platform campaigns).

### 3.3 Validation before approval

| # | Rule | Source | Error line |
|---|---|---|---|
| F1 | Product in stock, sellable, not auction, quantity ≤ available (17029018/19) | doc | "Tồn kho không đủ." |
| F2 | Flash price ≤ lowest price customers paid in last 30 days (from order lines; needs ≥ 30 days of data, else "—" and refuse) | overview | "Giá flash cao hơn giá thấp nhất 30 ngày." |
| F3 | Price after discount ≥ price floor (biên tối thiểu) for every SKU | rules | "Giá flash thấp hơn biên tối thiểu." |
| F4 | Discount ≤ shop `max_discount_pct` and ≤ 70 % (Shopee slider cap) | rules | "Mức giảm vượt mức tối đa của shop." |
| F5 | Discount within TikTok's allowed range for the product | 17029020/21/62/63 (probe numbers) | "Mức giảm ngoài khoảng TikTok cho phép." |
| F6 | No other ONGOING/NOT_START activity on the SKUs overlapping (17029022, 17029079, 17029103) | doc | "Sản phẩm đang có ưu đãi khác." |
| F7 | No flash on the product in the last 14 days (Juli guard, kept) | D84 / config | "Sản phẩm vừa chạy flash sale." |
| F8 | Period 1-3 days, ≥ TikTok min, ≤ TikTok max | doc / probe | "Thời gian chạy không hợp lệ." |
| F9 | `units` ≤ 99 or unlimited choice; `quantity_limit` per SKU if `VARIATION` | doc | "Số lượng tối đa 99." |
| F10 | `begin_time` ≥ now + lead | 17029005 | "Quá giờ bắt đầu." |
| F11 | Scope, kill switch, write flag, spend cap (discount × qty cap) | contract | "Cần kết nối lại TikTok Shop." / "Chi phí giảm giá vượt ngân sách." |

### 3.4 Execution sequence

Same as 1.4 with `activity_type=FLASHSALE`, body `discount` omitted, products carry `activity_price_amount`. Differences:

| Topic | Rule |
|---|---|
| Edits | an ONGOING flash cannot be changed or have products removed (17029047/48): a change to a running flash = deactivate + new activity in the next group; before begin (NOT_START) edits allowed (probe) |
| Stop / rollback | `deactivate` works on ongoing or upcoming (doc); rollback of an ongoing flash is a deactivate, not an edit |
| Re-run | optional `POST /promotion/202607/activities/{id}/republish` within 7 days of expiry (new `begin_time`/`end_time`, products kept): fewer calls than recreate (probe) |
| Read-back compared | `activity_type`, `title`, `begin_time`, `end_time`, `status`, `product_level`, per product/SKU `activity_price.amount` and `currency` (VND), `quantity_limit`, `quantity_per_user`, product id set |
| Effective price check | product detail price is not enough (W0 A.2 note 2): flash price wins over product discount, platform campaign over both. Verify from the activity read; (probe) whether product `GET` or order `sale_price` shows the active price |
| Group window | same as 1.4: all members verified NOT_START by begin - 2 min, ONGOING by begin + 15 min or whole group rolls back |

### 3.5 Conflicts and exclusivity

| Case | Rule |
|---|---|
| Flash vs product discount (FIXED_PRICE, DIRECT_DISCOUNT) on the same SKU | overview: only the flash price shows. 17029022: a SKU cannot be in two ONGOING/NOT_START activities. Contradiction (probe). Juli: the discounted price is one exclusive field per SKU: the earlier group holds it; the later card is queued to the next group |
| Flash vs platform campaign | campaign price always wins; no API read of campaign registration; measurement flags `platform_discount > 0`; Juli price floor is checked against the flash price only |
| Flash vs BMSM / Bundle | not documented (probe); default exclusive |
| Flash vs price write (`prices/update`) | probe D.11: error or silent while ongoing; Juli does not run both on one SKU |
| Overlapping Juli flash cards | same SKU: sequential groups; no overlap |

### 3.6 States and error handling

As 1.6 (and 3.4), plus:

| Event | Handling | Card line |
|---|---|---|
| 17029047/48 edit on ongoing flash | convert into deactivate + recreate, or fail | "Flash đang chạy, không sửa được." |
| 17029030/32 wrong price field | bug in mapping: failed, ops alert | "Lỗi cấu hình. Đã báo hỗ trợ." |
| 17029015/50 quantity range | failed, no retry | "Số lượng tối đa 99." |
| 17029008 flash period too long | failed | "Thời gian chạy không hợp lệ." |
| Flash ended early (stock sold out?) | read shows status; webhook 39 EXPIRED/DEACTIVATED | "Đã kết thúc." |

### 3.7 Measurement

| Item | Rule |
|---|---|
| Window | `[begin_time, min(end_time, deactivate)]` (hours-level, VN) |
| Attribution | order lines in window with SKU in the activity and `sale_price == activity_price.amount` (exact match, the clean signal) and no `platform_discount` from a campaign; units capped by `quantity_limit` if set |
| Cost | `(original_price - sale_price) × qty` over attributed lines (and `seller_discount` lump as check) |
| Metrics | orders, units, GMV, discount cost, margin, units vs `units` input; shopee-style slot share |
| Baseline | frozen 14 days before begin, same SKUs, same hours of day |
| Confound | a campaign price (platform discount) or another seller activity: `chua_ket_luan` |
| `flash_sales_service_fee_amount` | finance fee exists (W0 B.3): include in margin after settlement |

---

## 4. Open questions for the sandbox / Connector probe

| # | Question |
|---|---|
| P1 | Can a VN sandbox/production shop create `BUY_MORE_SAVE_MORE` and `FLASHSALE` via API (scope `seller.promotion.write`)? Any region error (17029036, 17029049)? |
| P2 | Status of a new activity: DRAFT until products added? When does it become NOT_START? Does the Create example ONGOING mean immediate start? |
| P3 | Min and max period (17029006/7/8) in VN for BMSM and FLASHSALE; minimum lead before `begin_time`. |
| P4 | BMSM: does `PUT products` need `activity_price_amount`/`discount`/quantity fields, or only ids? `VARIATION` level supported? Does Get Activity return BMSM `products`? |
| P5 | BMSM `AMOUNT_OFF`: per unit or per order total? Quantity threshold bounds? `MINIMAL_ORDER_AMOUNT` min? |
| P6 | Is `PUT products` atomic (all or nothing per call) or partial? Behaviour on one bad id. |
| P7 | Discount range numbers (17029020/21/62/63) per category in VN; the 30-day lowest-price check source. |
| P8 | `quantity_limit` max 99 real? Stock reservation for flash/BMSM? Behaviour when sold out. |
| P9 | Overlap matrix: flash vs FIXED_PRICE / DIRECT_DISCOUNT (17029022 vs overview), BMSM vs discount, BMSM vs flash, BMSM vs platform campaign. |
| P10 | Can an ONGOING or NOT_START BMSM be edited (tiers, products)? Can NOT_START flash be edited? Does `PUT /activities/{id}` accept tier changes? |
| P11 | Is there a client idempotency key (RequestSerialNo)? Does Create with a duplicate title give 17029004 reliably after a timeout? |
| P12 | Rate limits per shop/app for promotion endpoints; `X-RateLimit-*` headers; 17029054 frequency. |
| P13 | Webhook 39 latency and delivery for BMSM and FLASHSALE in VN sandbox; is `NOT_EFFECTIVE` ever pushed? |
| P14 | Does `activities/search` return Bundle Deal, or no Bundle record at all? Does order data carry any bundle or promotion marker? |
| P15 | Seller Center Bundle Deal form (recon): fields, limits, min/max members, price semantics, dates, purchase limit, title length, DOM stability, how the id appears after Lưu, whether the list shows it immediately. |
| P16 | Effective price visibility: do product `GET`, `prices/update` response or order `sale_price` show the active flash/BMSM price? Is a platform campaign visible? |
| P17 | `prices/update` while a product sits in an ONGOING activity (D.11). |
| P18 | `republish` for FLASHSALE in VN; republish for BMSM (docs say no). |
| P19 | Amount format for VND in `activity_price_amount` and BMSM values (string integer?). |
| P20 | Does order `line_items` repeat per unit (quantity = rows)? Needed for BMSM qualifying-order counts. |

---

## 5. TESTING CHECKLIST

### 5.1 Common (all three)

- [ ] State machine unit tests: every legal transition (queued → applying → applied → verifying → verified; verifying → retrying → verifying; retrying → failed → rolling_back → rolled_back); illegal ones raise; Connector path filled_waiting_save → saved | timed_out.
- [ ] Idempotency: replaying a step with the same key sends no second create; a timeout then search-by-title adopts the existing activity.
- [ ] Guardrail unit tests: price floor, max discount, spend cap, kill switch (platform / action / shop), production write flag each block the write and give the Vietnamese line.
- [ ] Contract tests against recorded TikTok responses (code 0, each error code in the tables 1.6 / 3.5, webhook 39 samples for ONGOING / EXPIRED / DEACTIVATED, Get Activity and Search samples incl. empty `products`).
- [ ] Webhook 39: ACK < 3 s, dedupe on `tts_notification_id`, triggers read-back only; reconcile poll ≤ 15 min.
- [ ] Re-auth: `needs_reauth` pauses queued steps; re-auth resumes; elapsed `begin_time` re-planned or failed.
- [ ] Seller edit: webhook DEACTIVATED not from Juli, or read-back diff on a Juli-owned activity → contaminated, no rewrite, measurement `chua_ket_luan`.
- [ ] Group all-or-nothing: one member fails verify → all members deactivated; a member not ONGOING by begin + 15 min → whole group rolls back; no group left half-applied.
- [ ] One live value per exclusive field: two cards on the same SKU never run together; the later one is queued to the next group.
- [ ] Production allowlist: promotion paths are blocked in production until the flag and ADR; sandbox allows.

### 5.2 BMSM (`promo_bmsm`)

Unit
- [ ] Mapping `ComboSpec` → body: tiers ≤ 2, `MINIMAL_ITEM_QUANTITY`, `PERCENTAGE_OFF` integer, `AMOUNT_OFF` whole đồng, `participation_limit`, `target_user_info`.
- [ ] Refusals B1-B16: 3 tiers, non-increasing tier, mixed types, decimal percent, `special_price` without conversion, `purchase_limit` > 1, > 300 products batching, missing cost.
- [ ] `special_price` conversion preview math; tier effective-percent equal to Shopee's `effective_pct`.
Contract
- [ ] Create body golden file; Get Activity response compare (field normalisation of string numbers); 17029104 / 17029103 / 17029022 / 17029113 fixtures.
Sandbox E2E
- [ ] Create BMSM (2 tiers), add 2 products, read back, status NOT_START → ONGOING at begin; webhook 39 received.
- [ ] Conflict: second BMSM on the same product → 17029104, queued; a product discount on the same product (P9).
- [ ] Deactivate → DEACTIVATED, read back, webhook.
- [ ] Rollback: force mismatch (edit tier in Seller Center) → retry → deactivate → card error.
- [ ] Group: 2 BMSM + 1 flash same window, one forced failure → all rolled back.
- [ ] Re-auth: revoke token mid-run → pause; re-authorise → resume.
- [ ] Partial add (bad id in batch 2) → read back, missing retry, rollback (P6).
Measurement
- [ ] Qualifying-order count from synthetic order lines; tier expected discount vs `seller_discount`; voucher remainder; platform-discount flag; baseline frozen at approval; `chua_ket_luan` thresholds.
UI
- [ ] Labels short Vietnamese, no captions; "—" for missing cost / tier 2; the 2-tier cap visible in the builder; each error line from 1.3 / 1.6 renders.

### 5.3 Bundle Deal (`bundle`, connector)

Unit
- [ ] Validation C1-C8; allocation of combo price to members pro-rata; combo ≥ sum → change 0 and refuse.
- [ ] Fill job lifecycle: queued → filled_waiting_save → saved | timed_out (24 h, one reminder, no second).
Connector fixtures
- [ ] HTML fixtures of the Seller Center create page (recon): fill each field, never click Lưu; stop on login wall / password dialog / captcha.
- [ ] Saved-signal fixture: toast / redirect / list row with `JC-<code>`; id extraction; missing id fallback.
- [ ] DOM read-back fixture: matches, mismatch, seller edit after save → contaminated.
- [ ] Late save after timeout adopted by reconcile (if enabled).
- [ ] Flag `fill_bundle` off and kill switch: job not created.
Measurement
- [ ] Combo-signature attribution: member lines at combo price; switch share vs P10 / P50 / P90; baskets frozen.
UI
- [ ] Card shows "Điền bằng Connector" then "Đã điền, chờ lưu" / "Quá hạn"; no explanation text; "—" when id unknown.

### 5.4 Flash sale (`promo_flash_sale`)

Unit
- [ ] Mapping: `discount_pct` → `activity_price_amount` (floor 100 đ); `final_price` passthrough; `discount` never sent (17029030/32); `units` > 99 refused or -1; VARIATION quantity rules (product-level -1).
- [ ] F1-F11 including 30-day lowest-price check (needs ≥ 30 days of orders), 14-day recent-flash guard.
Contract
- [ ] Fixtures: 17029047/48, 17029008, 17029015/50, 17029054; Get Activity with `activity_price`.
Sandbox E2E
- [ ] Create FLASHSALE (PRODUCT level) and (VARIATION level), add products, read back price and quantity, ONGOING at begin.
- [ ] Conflict with a product discount on the same product (P9) and with an existing activity (17029022).
- [ ] Edit while ongoing refused (17029047); change = deactivate + new.
- [ ] Deactivate and rollback; republish within 7 days (P18).
- [ ] Group window: begin + 15 min boundary test.
- [ ] Re-auth pause / resume.
Measurement
- [ ] Attribution by exact `sale_price == activity_price`; discount cost = (original - sale) × qty; platform-campaign flag; hour-of-day-matched baseline; units vs `units`.
UI
- [ ] Labels, "—" for missing 30-day price, error lines.

### 5.5 Acceptance criteria

- [ ] A seller approves one card and nothing else is asked; the API write chain runs on schedule and ends `verified` for BMSM and Flash with read-back equal to the approved sheet (all fields in 1.4 / 3.4).
- [ ] No write when any guardrail, kill switch or the production write flag blocks it; the card shows one short Vietnamese line.
- [ ] A mismatch ends `rolled_back` with the activity DEACTIVATED (verified by read), never half-applied; a group never ends partly live.
- [ ] A seller's own Seller Center edit is never overwritten; the card is marked contaminated.
- [ ] Bundle Deal: the Connector fills, the seller saves, Juli records the id and verifies by DOM read; `timed_out` after 24 h with one reminder.
- [ ] Sandbox probe answered P1-P20 (at least P1-P6, P9, P11, P15) and this spec updated before production enablement.
- [ ] Measurement per card/group runs with frozen baseline and labels overlapped cases `chua_ket_luan`.
