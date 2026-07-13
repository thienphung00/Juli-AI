# TikTok Shop API — Contract Collection (Cleaned Reference)

> **Purpose:** Canonical, sanitized reference of verified TikTok Shop Partner API endpoints
> for Phase 2 implementation. Organized by **credential/risk tier**, not by workflow order:
> - **Section A — Fujiwa (production, READ ONLY).** All GET/search/eligibility-check
>   operations. Safe to run repeatedly; no state mutation.
> - **Section B — SANDBOX_VN (WRITE / state-mutating).** All create/update/approve/reject/
>   ship/split/combine operations. Never run these against Fujiwa.
>
> **Authority:** [`EXECUTION.md`](../../EXECUTION.md) P2-A1 · Plan: Phase 2 TikTok Shop Backend & ETL.
>
> **Sanitization applied in this pass:** all `access_token`, `sign`, and `app_key` values in
> cURL samples have been replaced with `{access_token}` / `{sign}` / `{app_key}` placeholders.
> All response-body sample arrays have been truncated to a single representative item. Buyer
> PII (name, phone, email, full address) has been replaced with `"[REDACTED]"`.

**Merchant credentials (placeholders — real values live in `.env` / Partner Center only)**

| Merchant | Role | Use for |
|----------|------|---------|
| **Fujiwa** (production) | Read only | Section A — all read/search/eligibility endpoints |
| **SANDBOX_VN** (sandbox) | Write validation | Section B — all create/update/mutate endpoints |

**Global parameters (fill once, never commit real values)**

| Parameter | Notes |
|-----------|-------|
| `app_key` | Partner Center App Key |
| `app_secret` | Never commit — env var only |
| Fujiwa `shop_cipher` | From Get Authorized Shops (Fujiwa) |
| SANDBOX_VN `shop_cipher` | From Get Authorized Shops (SANDBOX_VN) |
| Fujiwa / SANDBOX_VN `access_token` | Short-lived — supplied out-of-band, never committed |
| Open API base URL | `https://open-api.tiktokglobalshop.com` |

> **Tokens:** access/refresh tokens are managed by the backend OAuth flow and stored encrypted
> (`TikTokCredential` in Postgres). Do not paste live tokens or ciphertext blobs into this doc.

---

## ⚠️ Note on return/refund search endpoints (A-16, A-17, A-18)

Three endpoints return overlapping return/refund data at different granularity. They are
**kept separate** because they map to different workflow entry points, but the overlap is
worth knowing about before building the client:

| Endpoint | Verification status | Role |
|----------|---------------------|------|
| **Search Returns** (A-6) | ✅ Verified — live Fujiwa capture | Canonical list endpoint for workflow 8b (Prevent Return); flat `return_orders` list |
| **Search RMA** (A-17) | ⏸️ **Deferred** — doc-sample only | Physical merchandise/package tracking status (e.g. `AWAITING_BUYER_RETURN`); used mid-chain in 8b before a decision |
| **Search Aftersales Request** (A-18) | ⏸️ **Deferred** — doc-sample only | Canonical entry point for workflow 8c (Prevent Refund); its `whitelisted_data_fields` param can optionally request `RETURN_MERCHANDISE_AUTHORIZATIONS`, which looks like it can return the same data as Search RMA in one call |

**Recommendation:** implement all three as written (they're genuinely different workflow
steps), but treat Search RMA as lower priority — capture a real sandbox response for Search
Aftersales Request with `RETURN_MERCHANDISE_AUTHORIZATIONS` included first, and only build a
separate Search RMA integration if that field doesn't actually cover the need. This has not
been sandbox-verified, so don't drop Search RMA yet on this assumption alone.

---

## Workflow endpoint coverage

| Workflow | API category | Endpoint chain | Required IDs |
|----------|--------------|----------------|--------------|
| Create Hero Product (formerly Create New Product Listing) | Products | Get Categories → Check Listing Prerequisites → Get Category Attributes → Get Brands → Upload Product Image → Get SEO Words → Get Recommended Title/Description → Create Product → Search Products | `category_id`, `brand_id` if required, image `uri`, returned `product_id` |
| Create Multi-SKU Product | Products | Same chain as Create Hero Product, Create Product with all SKU rows | `category_id`, `brand_id` if required, image `uri`, returned `product_id`, returned `sku_id`s |
| Optimize Product (formerly Update Product Listing) | Products | Get Product → Get Category Attributes → Get SEO Words → Get Recommended Title/Description → Upload Product Image → Edit Product → Update Price | `product_id`, `category_id` if changed |
| Process Order (formerly Accelerate Order Fulfillment) | Orders / Fulfillment / Supply Chain | Search Orders → Get Order Detail → Create Packages → Get Package Shipping Document → Ship Package (or Batch Ship Packages) → Confirm Package Shipment → Get Package Detail | `order_id`, returned `package_id` |
| Handle Split Package | Fulfillment | Get Order Split Attributes → Split Orders → Search Combinable Packages → Combine Package → Uncombine Packages | `order_id`, draft `package_id`s |
| Update / Replenish / Clear Inventory | Products | Inventory Search → Update Inventory | `product_id`, `sku_id`, `warehouse_id` |
| Prevent Cancellation (8a) | Return/Refund | Search Cancellations → Get Decision Eligibility → Get Reject Reasons → Approve Cancellation or Reject Cancellation | `cancel_id` from search, `order_id` for traceability |
| Prevent Return (8b) | Return/Refund + Products | Search Returns → Get Aftersale Eligibility → ~~Search RMA~~ *(deferred)* → Review Aftersales → Get Reject Reasons → Approve Return or Reject Return → Update Inventory | `return_id`, `order_id` for traceability |
| Prevent Refund (8c) | Return/Refund | ~~Search Aftersales Request~~ *(deferred)* → Calculate Refund → Get Reject Reasons → Approve Refund or Reject Refund | `return_id` |
| Create / Delete / Update Activity | Promotion | Create Activity → Update Activity Product → **Get Activity** → Deactivate Activity → Update Activity | `activity_id`, `product_id`, `sku_id` |
| ~~Create Voucher / Coupon~~ — REMOVED | Promotion | No seller-facing create-coupon operation exists; not implemented | — |

---

# Section A — Fujiwa (Production, Read Only)

Use **Fujiwa** credentials only. No write operations belong in this section.

## A-1. Get Authorized Shops

| Field | Value |
|-------|-------|
| Version | `202309` |
| Method / path | `GET /authorization/202309/shops` |
| Required | `app_key`, `timestamp`, `sign`; header `x-tts-access-token` |

**cURL**
```bash
curl -k -X 'GET' -H 'x-tts-access-token: {access_token}' \
'https://open-api.tiktokglobalshop.com/authorization/202309/shops?access_token={access_token}&app_key={app_key}&shop_id=&sign={sign}&timestamp=1783303591&version=202309'
```

**Sanitized response**
```json
{"code":0,"data":{"shops":[{"cipher":"{shop_cipher}","code":"VNLCTNWY6A","id":"7495274531001436791","name":"Fujiwa Vietnam Store","region":"VN","seller_type":"LOCAL"}]},"message":"Success","request_id":"{request_id}"}
```

---

## A-2. Search Products

| Field | Value |
|-------|-------|
| Version | `202309`
| Method / path | `POST /product/202309/products/search` |
| Required | `app_key`, `timestamp`, `sign`, `shop_cipher`; header `x-tts-access-token` |
| Optional body | `status` |
| Optional query | `page_size`, `page_token` |

**cURL**
```bash
curl -k -X 'POST' -d '{}' -H 'Content-Type: application/json' -H 'x-tts-access-token: {access_token}' \
'https://open-api.tiktokglobalshop.com/product/202309/products/search?access_token={access_token}&app_key={app_key}&page_size=1&shop_cipher={shop_cipher}&shop_id=&sign={sign}&timestamp=1783304875&version=202309'
```

**Sanitized response**
```json
{"code":0,"data":{"next_page_token":"{page_token}","products":[{"audit":{"pre_approved_reasons":[],"status":"APPROVED"},"create_time":1775123176,"has_draft":false,"id":"1734952395144267383","is_not_for_sale":false,"product_tags":[],"recommended_categories":[],"sales_regions":["VN"],"skus":[{"id":"1734952449674217079","inventory":[{"quantity":43,"warehouse_id":"7272949914115966726"}],"price":{"currency":"VND","tax_exclusive_price":"72000"},"seller_sku":"XTM-C","status_info":{"status":"NORMAL"}}],"status":"ACTIVATE","title":"[Quà Tặng] Chai Xịt Thơm Miệng Fujisalt 14mL","update_time":1782892330}],"total_count":117},"message":"Success","request_id":"{request_id}"}
```

---

## A-3. Get Product (New)

| Field | Value |
|-------|-------|
| Version | `202309` |
| Method / path | `GET /product/202309/products/{product_id}` |
| Required | `product_id`, signing params, `shop_cipher`; header `x-tts-access-token` |

**cURL**
```bash
curl -k -X 'GET' -H 'x-tts-access-token: {access_token}' \
'https://open-api.tiktokglobalshop.com/product/202309/products/1734952395144267383?access_token={access_token}&app_key={app_key}&shop_cipher={shop_cipher}&shop_id=&sign={sign}&timestamp=1783305447&version=202309'
```

**Sanitized response** (product_attributes, images, and description truncated — full shape has `brand`, `category_chains`, `product_attributes[]`, `main_images[]`, `skus[]`, `subscribe_info`)
```json
{"code":0,"data":{"audit":{"status":"APPROVED"},"brand":{"id":"7273019489648756485","name":"Fujiwa Vietnam"},"category_chains":[{"id":"601693","is_leaf":true,"local_name":"Xịt miệng","parent_id":"849672"}],"description":"[TRUNCATED — HTML product description]","id":"1734952395144267383","main_images":[{"height":1200,"uri":"tos-alisg-i-aphluv4xwc-sg/{image_uri}","urls":["{signed_image_url}"],"width":1200}],"package_weight":{"unit":"KILOGRAM","value":"0.2"},"product_attributes":[{"id":"100149","name":"Quốc gia xuất xứ","values":[{"id":"1000854","name":"Việt Nam"}]}],"product_status":"ACTIVATE","skus":[{"id":"1734952449674217079","inventory":[{"quantity":43,"warehouse_id":"7272949914115966726"}],"price":{"currency":"VND","sale_price":"72000","tax_exclusive_price":"72000"},"seller_sku":"XTM-C","status_info":{"status":"NORMAL"}}],"status":"ACTIVATE","title":"[Quà Tặng] Chai Xịt Thơm Miệng Fujisalt 14mL","update_time":1782892330},"message":"Success","request_id":"{request_id}"}
```

---

## A-4. Get Order List (New)

| Field | Value |
|-------|-------|
| Version | `202309` |
| Method / path | `POST /order/202309/orders/search` |
| Optional body | `order_status`, `update_time_ge`, `update_time_lt` |
| Optional query | `page_size`, `page_token` |
| Notes | Kept distinct from A-5 (Get Order Detail) — this is the paginated listing/search call, A-5 fetches full detail by ID(s); both are required by the Process Order chain. |

**cURL**
```bash
curl -k -X 'POST' -d '{}' -H 'Content-Type: application/json' -H 'x-tts-access-token: {access_token}' \
'https://open-api.tiktokglobalshop.com/order/202309/orders/search?access_token={access_token}&app_key={app_key}&page_size=1&shop_cipher={shop_cipher}&shop_id=&sign={sign}&timestamp=1783305644&version=202309'
```

**Sanitized response**
```json
{"code":0,"data":{"next_page_token":"{page_token}","orders":[{"buyer_email":"[REDACTED]","cancel_reason":"Không thể giao hàng đến địa chỉ khách hàng","cancel_time":1696306119,"commerce_platform":"TIKTOK_SHOP","create_time":1695873653,"delivery_type":"HOME_DELIVERY","fulfillment_type":"FULFILLMENT_BY_SELLER","id":"577958834469439754","is_cod":true,"line_items":[{"cancel_reason":"Không thể giao hàng đến địa chỉ khách hàng","currency":"VND","display_status":"CANCELLED","id":"577958834469570826","original_price":"168000","package_id":"1153486604836964618","product_id":"1729700293904403063","product_name":"Nước Uống Ion Kiềm Cao Cấp Đóng Chai Fujiwa Vietnam","sale_price":"168000","seller_sku":"FUJIWA02-450","sku_id":"1729700293904534135","tracking_number":"3220279504"}],"order_type":"NORMAL","packages":[{"id":"1153486604836964618"}],"payment":{"currency":"VND","total_amount":"657000"},"payment_method_name":"Cash on delivery","recipient_address":"[REDACTED]","shipping_provider":"GHTK","status":"CANCELLED","tracking_number":"3220279504","update_time":1696306119,"warehouse_id":"7272949914115966726"}],"total_count":17472},"message":"Success","request_id":"{request_id}"}
```

---

## A-5. Get Order Detail

| Field | Value |
|-------|-------|
| Version | `202507` |
| Method / path | `GET /order/202507/orders` |
| Required query | `ids` (comma-separated order IDs) |

**cURL**
```bash
curl -k -X 'GET' -H 'x-tts-access-token: {access_token}' \
'https://open-api.tiktokglobalshop.com/order/202507/orders?access_token={access_token}&app_key={app_key}&ids=577958834469439754&shop_cipher={shop_cipher}&shop_id=&sign={sign}&timestamp=1783305819&version=202507'
```

**Sanitized response**
```json
{"code":0,"data":{"orders":[{"buyer_email":"[REDACTED]","cancel_reason":"Không thể giao hàng đến địa chỉ khách hàng","cancel_time":1696306119,"id":"577958834469439754","is_cod":true,"line_items":[{"currency":"VND","display_status":"CANCELLED","id":"577958834469570826","original_price":"168000","package_id":"1153486604836964618","product_id":"1729700293904403063","product_name":"Nước Uống Ion Kiềm Cao Cấp Đóng Chai Fujiwa Vietnam","sale_price":"168000","seller_sku":"FUJIWA02-450","sku_id":"1729700293904534135","tracking_number":"3220279504"}],"packages":[{"id":"1153486604836964618"}],"payment":{"currency":"VND","total_amount":"657000"},"recipient_address":"[REDACTED]","status":"CANCELLED","update_time":1696306119}]},"message":"Success","request_id":"{request_id}"}
```

---

## A-6. Search Returns

*(see overlap note above re: A-17 Search RMA, A-18 Search Aftersales Request)*

| Field | Value |
|-------|-------|
| Version | `202602` |
| Method / path | `POST /return_refund/202602/returns/search` |
| Optional body | `return_status`, `update_time_ge`, `update_time_lt` |
| Optional query | `page_size`, `page_token` |

**cURL**
```bash
curl -k -X 'POST' -d '{}' -H 'Content-Type: application/json' -H 'x-tts-access-token: {access_token}' \
'https://open-api.tiktokglobalshop.com/return_refund/202602/returns/search?access_token={access_token}&app_key={app_key}&shop_cipher={shop_cipher}&shop_id=&sign={sign}&timestamp=1783305860&version=202602'
```

**Sanitized response**
```json
{"code":0,"data":{"next_page_token":"{page_token}","return_orders":[{"create_time":1724558837,"handover_method":"DROP_OFF","order_id":"579238058323577347","refund_amount":{"currency":"VND","refund_total":"864000"},"return_id":"4035463945335048707","return_line_items":[{"product_name":"Thùng 24 Lon Nước Uống Giàu Hydrogen Cao Cấp Fujiwa","refund_amount":{"currency":"VND","refund_total":"432000"},"seller_sku":"FUJIWA04-24","sku_id":"1730420785344318071"}],"return_method":"PLATFORM_SHIPPED","return_provider_name":"J&T Express","return_reason":"ecom_order_delivered_refund_and_return_reason_damaged","return_reason_text":"Package or product is damaged","return_status":"RETURN_OR_REFUND_REQUEST_COMPLETE","return_type":"RETURN_AND_REFUND","role":"BUYER","update_time":1724833101}],"total_count":71},"message":"Success","request_id":"{request_id}"}
```

---

## A-7. Search Cancellations

| Field | Value |
|-------|-------|
| Version | `202602` |
| Method / path | `POST /return_refund/202602/cancellations/search` |
| Optional body | `update_time_ge`, `update_time_lt` |
| Optional query | `page_size`, `page_token` |

**cURL**
```bash
curl -k -X 'POST' -d '{}' -H 'Content-Type: application/json' -H 'x-tts-access-token: {access_token}' \
'https://open-api.tiktokglobalshop.com/return_refund/202602/cancellations/search?access_token={access_token}&app_key={app_key}&page_size=1&shop_cipher={shop_cipher}&shop_id=&sign={sign}&timestamp=1783306117&version=202602'
```

**Sanitized response**
```json
{"code":0,"data":{"cancellations":[{"cancel_id":"4035348475003308298","cancel_line_items":[{"cancel_line_item_id":"4035348475003373834","order_line_item_id":"577958834469570826","product_name":"Nước Uống Ion Kiềm Cao Cấp Đóng Chai Fujiwa Vietnam","seller_sku":"FUJIWA02-450","sku_id":"1729700293904534135"}],"cancel_reason":"seller_cancel_paid_reason_address_not_deliver","cancel_reason_text":"Unable to deliver to customer address","cancel_status":"CANCELLATION_REQUEST_COMPLETE","cancel_type":"CANCEL","create_time":1696306119,"order_id":"577958834469439754","role":"SELLER","should_replenish_stock":true,"update_time":1696306119}],"next_page_token":"{page_token}","total_count":2817},"message":"Success","request_id":"{request_id}"}
```

---

## A-8. Inventory Search

| Field | Value |
|-------|-------|
| Version | `202309` |
| Method / path | `POST /product/202309/inventory/search` |
| Optional body | `sku_ids` |

**cURL**
```bash
curl -k -X 'POST' -d '{"product_ids":["{product_id}"],"sku_ids":["{sku_id}"]}' -H 'Content-Type: application/json' -H 'x-tts-access-token: {access_token}' \
'https://open-api.tiktokglobalshop.com/product/202309/inventory/search?access_token={access_token}&app_key={app_key}&shop_cipher={shop_cipher}&shop_id=&sign={sign}&timestamp=1783306596&version=202309'
```

**Sanitized response**
```json
{"code":0,"data":{"inventory":[{"product_id":"1729700293904403063","skus":[{"id":"1729700293904534135","seller_sku":"FUJIWA02-450","total_available_quantity":995,"total_committed_quantity":0,"warehouse_inventory":[{"available_quantity":995,"committed_quantity":0,"warehouse_id":"7272949914115966726"}]}]}]},"message":"Success","request_id":"{request_id}"}
```

---

## A-9. Get Category Attributes

| Field | Value |
|-------|-------|
| Version | `202309` |
| Method / path | `GET /product/202309/categories/{category_id}/attributes` |
| Required | `category_id`; include category version if exposed |
| Notes | Required before create/edit when category attributes are mandatory or category changes |

**cURL**
```bash
curl -k -X 'GET' -H 'x-tts-access-token: {access_token}' \
'https://open-api.tiktokglobalshop.com/product/202309/categories/605254/global_attributes?access_token={access_token}&app_key={app_key}&shop_id={shop_id}&sign={sign}&timestamp=1783478062&version=202309'
```

**Sanitized response** (values arrays truncated — full response returns dozens of enum values per attribute, e.g. full country list under `Country of origin`)
```json
{"code":0,"data":{"attributes":[{"id":"101164","is_customizable":false,"is_multiple_selection":false,"is_requried":false,"name":"Movement Type","optional_regions":["VN"],"type":"PRODUCT_PROPERTY","values":[{"id":"1002241","name":"Mechanical"}]},{"id":"100149","is_customizable":true,"is_multiple_selection":false,"is_requried":true,"name":"Country of origin","required_regions":["VN"],"type":"PRODUCT_PROPERTY","values":[{"id":"1000854","name":"Vietnam"}]},{"id":"101490","is_customizable":true,"is_multiple_selection":false,"is_requried":true,"name":"Manufacturer/Trader Address","required_regions":["VN"],"type":"PRODUCT_PROPERTY"},{"id":"101489","is_customizable":true,"is_multiple_selection":false,"is_requried":true,"name":"Manufacturer/Trader Name","required_regions":["VN"],"type":"PRODUCT_PROPERTY"}]},"message":"Success","request_id":"{request_id}"}
```

---

## A-10. Get Order Split Attributes

| Field | Value |
|-------|-------|
| Version | `202309` (verify) |
| Method / path | `GET /fulfillment/202309/orders/split_attributes` |
| Required | `order_ids` |

**cURL**
```bash
curl -k -X 'GET' -H 'x-tts-access-token: {access_token}' \
'https://open-api.tiktokglobalshop.com/fulfillment/202309/orders/split_attributes?access_token={access_token}&app_key={app_key}&order_ids=584920493510067210&shop_cipher={shop_cipher}&shop_id={shop_id}&sign={sign}&timestamp=1783490423&version=202309'
```

**Sanitized response**
```json
{"code":0,"data":{"split_attributes":[{"can_split":false,"must_split_reasons":[],"order_id":"584920493510067210","reason":"split same sku in Multi Package not allow"}]},"message":"Success","request_id":"{request_id}"}
```

---

## A-11. Search Combinable Packages

| Field | Value |
|-------|-------|
| Version | `202309` |
| Method / path | `GET /fulfillment/202309/combinable_packages/search` |
| Required | `order_id` or eligible package/order filter |
| Notes | Returns draft/combinable package IDs for the split/combine flow |

**cURL**
```bash
curl -k -X 'GET' -H 'x-tts-access-token: {access_token}' \
'https://open-api.tiktokglobalshop.com/fulfillment/202309/combinable_packages/search?access_token={access_token}&app_key={app_key}&page_size=1&page_token={page_token}&shop_cipher={shop_cipher}&shop_id=&sign={sign}&timestamp=1783497875&version=202309'
```

**Sanitized response** (example — no live sandbox data available at capture time)
```json
{"code":0,"data":{"combinable_packages":[{"id":"57466538837665","order_ids":["57466538837665"]}],"next_page_token":"{page_token}","total_count":10},"message":"Success","request_id":"{request_id}"}
```

---

## A-12. Get Package Shipping Document

| Field | Value |
|-------|-------|
| Version | `202309` |
| Method / path | `GET /fulfillment/202309/packages/{package_id}/shipping_documents` (verify) |
| Required | package/order identifier, `document_type` |

**cURL**
```bash
curl -k -X 'GET' -H 'x-tts-access-token: {access_token}' \
'https://open-api.tiktokglobalshop.com/fulfillment/202309/packages/1202809545811788810/shipping_documents?access_token={access_token}&app_key={app_key}&document_type=SHIPPING_LABEL_AND_PACKING_SLIP&shop_cipher={shop_cipher}&shop_id=&sign={sign}&timestamp=1783492066&version=202309'
```

**Sanitized response**
```json
{"code":0,"data":{"doc_url":"{signed_document_url}","tracking_number":"17398843333472"},"message":"Success","request_id":"{request_id}"}
```

---

## A-13. Get Package Detail

| Field | Value |
|-------|-------|
| Operation | `Get Package Detail` — replaces prior "Monitor Shipment Status" / "Get Package Shipping Info" labels |
| Version | `202309` |
| Method / path | `GET /fulfillment/202309/packages/{package_id}` |
| Required | `package_id` |
| Notes | Live Partner Center doc page confirmed at `get-package-detail-202309` |

**cURL**
```bash
curl -k -X 'GET' -H 'x-tts-access-token: {access_token}' \
'https://open-api.tiktokglobalshop.com/fulfillment/202309/packages/1202828821220066314?access_token={access_token}&app_key={app_key}&shop_cipher={shop_cipher}&shop_id={shop_id}&sign={sign}&timestamp=1783498706&version=202309'
```

**Sanitized response**
```json
{"code":0,"data":{"create_time":1783498675,"delivery_option_name":"Standard shipping","order_line_item_ids":["584922195665454090"],"orders":[{"id":"584922195665323018","skus":[{"id":"1736433041572857475","quantity":1}]}],"package_id":"1202828821220066314","package_status":"TO_FULFILL","package_sub_status":"STOCKING","recipient_address":"[REDACTED]","sender_address":"[REDACTED]","shipping_provider_name":"TT Virtual# JNT express","update_time":1783498676,"weight":{"unit":"GRAM","value":"520"}},"message":"Success","request_id":"{request_id}"}
```

---

## A-14. Get Decision Eligibility (8a Prevent Cancellation)

| Field | Value |
|-------|-------|
| Version | `202601` |
| Method / path | `GET /return_refund/202601/decision_eligibility` |
| Required | `return_or_cancel_id` |

**cURL**
```bash
curl -k -X 'GET' -H 'x-tts-access-token: {access_token}' \
'https://open-api.tiktokglobalshop.com/return_refund/202601/decision_eligibility?access_token={access_token}&app_key={app_key}&return_or_cancel_id=4041276424777991178&shop_cipher={shop_cipher}&shop_id={shop_id}&sign={sign}&timestamp=1783494743&version=202601'
```

**Sanitized response**
```json
{"code":0,"data":{"decisions":[{"decision":"APPROVE_RETURN","eligible":true},{"decision":"REJECT_RECEIVED_PACKAGE","eligible":false,"ineligible_code":25011014,"ineligible_reason":"status can't reject receive"}]},"message":"Success","request_id":"{request_id}"}
```

---

## A-15. Get Aftersale Eligibility (8b Prevent Return)

| Field | Value |
|-------|-------|
| Version | `202602` |
| Method / path | `GET /return_refund/202602/orders/{order_id}/aftersale_eligibility` |
| Required | `order_id` |
| Notes | Shares the `202602` version tag with A-6/A-7 but is a distinct resource path — TikTok versions per release, not per resource |

**cURL**
```bash
curl -k -X 'GET' -H 'x-tts-access-token: {access_token}' \
'https://open-api.tiktokglobalshop.com/return_refund/202602/orders/584920516705354762/aftersale_eligibility?access_token={access_token}&app_key={app_key}&shop_cipher={shop_cipher}&shop_id={shop_id}&sign={sign}&timestamp=1783492799&version=202602'
```

**Sanitized response**
```json
{"code":0,"data":{"sku_eligibility":[{"line_item_eligibility":[{"eligible":false,"ineligible_code":25001011,"ineligible_reason":"there are processing reverse order exists","order_line_items_ids":["584920516705485834"],"request_type":"CANCEL"}],"sku_id":"1736433041572857475"}]},"message":"Success","request_id":"{request_id}"}
```

---

## A-16. Get Reject Reasons (8a/8b/8c shared)

| Field | Value |
|-------|-------|
| Version | `202309` |
| Method / path | `GET /return_refund/202309/reject_reasons` |
| Notes | SEA-specific requirement before rejecting a cancellation or return |

**cURL**
```bash
curl -k -X 'GET' -H 'x-tts-access-token: {access_token}' \
'https://open-api.tiktokglobalshop.com/return_refund/202309/reject_reasons?access_token={access_token}&app_key={app_key}&return_or_cancel_id=4041276424777991178&shop_cipher={shop_cipher}&shop_id={shop_id}&sign={sign}&timestamp=1783499025&version=202309'
```

**Sanitized response**
```json
{"code":0,"data":{"reasons":[{"name":"reverse_reject_request_reason_3","text":"Product already used, damaged or removed from original packaging"}]},"message":"Success","request_id":"{request_id}"}
```

---

## A-17. Search RMA (8b Prevent Return) — DEFERRED

*(Deferred — doc-sample only; see overlap note above. Implement after Fujiwa capture.)*

| Field | Value |
|-------|-------|
| Version | `202604` |
| Method / path | `POST /return_refund/202604/rma/search` |
| Optional body | `rma_ids`, `package_ids`, `statuses`, `aftersales_request_ids`, `main_order_ids`, time filters |

**cURL**
```bash
curl -X POST 'https://open-api.tiktokglobalshop.com/return_refund/202604/rma/search?sign={sign}&timestamp=1623812664&app_key={app_key}&shop_cipher={shop_cipher}&locale=en-US' \
-H 'x-tts-access-token: {access_token}' -H 'content-type: application/json' \
-d '{"whitelisted_data_fields":["LINE_ITEMS","SKU_RETURN_REQUESTS"],"filters":{"main_order_ids":["577686530908261117"]},"pagination":{"page_size":100}}'
```

**Sanitized response** (nested `sku_return_requests[].return_line_items[].return_sub_line_items[]` truncated to 1 each)
```json
{"code":0,"data":{"return_merchandise_authorizations":[{"aftersales_request_id":"4035318504086604101","id":"2894521704838895640","line_items":[{"main_order_id":"577686530908261117","return_line_item_id":"4035227657962164811","sku_id":"2729382476852921560","sub_return_line_item_id":"4035227657962164815"}],"package_id":"2894521704838895645","sku_return_requests":[{"order_id":"577686530908261117","refund_amount":{"currency":"USD","refund_total":"1.23"},"return_id":"4035318504086604100","return_reason":"ecom_order_to_ship_canceled_reason_created_by_mistakes","return_status":"RETURN_OR_REFUND_REQUEST_PENDING","return_type":"REFUND","role":"BUYER"}],"status":"AWAITING_BUYER_RETURN"}],"next_page_token":"{page_token}","total_count":12345},"message":"Success","request_id":"{request_id}"}
```

---

## A-18. Search Aftersales Request (8c Prevent Refund) — DEFERRED

*(Deferred — doc-sample only; see overlap note above. Implement after Fujiwa capture.)*

| Field | Value |
|-------|-------|
| Version | `202603` |
| Method / path | `POST /return_refund/202603/aftersales/search` |
| Optional body | `aftersales_request_ids`, `aftersales_request_statuses`, `return_types`, `main_order_ids`, `buyer_ids`, time filters, `whitelisted_data_fields` (can include `RETURN_MERCHANDISE_AUTHORIZATIONS` — see overlap note) |

**cURL**
```bash
curl -X POST 'https://open-api.tiktokglobalshop.com/return_refund/202603/aftersales/search?timestamp=1623812664&app_key={app_key}&sign={sign}&shop_cipher={shop_cipher}&locale=en-US' \
-H 'x-tts-access-token: {access_token}' -H 'content-type: application/json' \
-d '{"whitelisted_data_fields":["LINE_ITEMS","SKU_RETURN_REQUESTS","RETURN_MERCHANDISE_AUTHORIZATIONS"],"filters":{"main_order_ids":["577686530908261117"]},"pagination":{"page_size":100}}'
```

**Sanitized response** (nested arrays truncated to 1 each)
```json
{"code":0,"data":{"aftersales_requests":[{"id":"4035318504086604101","line_items":[{"main_order_id":"577686530908261117","return_line_item_id":"4035227657962164811","sku_id":"2729382476852921560"}],"return_merchandise_authorizations":[{"aftersales_request_id":"4035318504086604101","id":"2894521704838895640","package_id":"2894521704838895645","status":"AWAITING_BUYER_RETURN"}],"sku_return_requests":[{"order_id":"577686530908261117","refund_amount":{"currency":"USD","refund_total":"1.23"},"return_id":"4035318504086604100","return_reason":"ecom_order_to_ship_canceled_reason_created_by_mistakes","return_status":"RETURN_OR_REFUND_REQUEST_PENDING","return_type":"REFUND","role":"BUYER"}],"status":"PENDING_REQUEST_REVIEW"}],"next_page_token":"{page_token}","total_count":12345},"message":"Success","request_id":"{request_id}"}
```

---

## A-19. Calculate Refund (8c Prevent Refund)

| Field | Value |
|-------|-------|
| Operation | Refund amount preview (partial vs. full) — read-only calculation, no state change |
| Version | `202602` |
| Method / path | `POST /return_refund/202602/refunds/calculate` |
| Required | `order_id`, `order_line_item_ids` or `skus[]` |

**cURL**
```bash
curl -X POST 'https://open-api.tiktokglobalshop.com/return_refund/202602/refunds/calculate?app_key={app_key}&sign={sign}&timestamp=1623812664&shop_cipher={shop_cipher}' \
-H 'content-type: application/json' -H 'x-tts-access-token: {access_token}' \
-d '{"order_id":"576469648086175911","request_type":"REFUND","shipment_type":"PLATFORM","handover_method":"DROP_OFF","reason_name":"ecom_order_delivered_refund_reason_missing_product_seller","order_line_item_ids":["576469648086306986"],"skus":[{"sku_id":"1729386416015578024","quantity":1}]}'
```

**Sanitized response**
```json
{"code":0,"data":{"order_refund_amount":{"currency":"USD","refund_shipping_fee":"0.2","refund_subtotal":"1","refund_tax":"0.03","refund_total":"1.23"}},"message":"Success","request_id":"{request_id}"}
```

---

## A-20. Get Return Records (8b Prevent Return)

| Field | Value |
|-------|-------|
| Version | `202309` (verify) |
| Method / path | `GET /return_refund/202309/returns/{return_id}/records` |
| Required | `return_id` |

**cURL**
```bash
curl -X GET 'https://open-api.tiktokglobalshop.com/return_refund/202309/returns/4035318504086604100/records?app_key={app_key}&sign={sign}&timestamp=1623812664&shop_cipher={shop_cipher}&locale=en-US' \
-H 'x-tts-access-token: {access_token}' -H 'content-type: application/json'
```

**Sanitized response**
```json
{"code":0,"data":{"records":[{"create_time":1690532213,"description":"Customer submitted a return request","event":"ORDER_RETURN","note":"[REDACTED]","reason_text":"Wrong product was sent","role":"Buyer"}]},"message":"Success","request_id":"{request_id}"}
```

---

## A-21. Get Categories (Create Hero Product step 1)

| Field | Value |
|-------|-------|
| Version | `202309` |
| Method / path | `GET /product/202309/categories` |
| Required | signing params, `shop_cipher`; header `x-tts-access-token` |

**cURL**
```bash
curl -k -X 'GET' -H 'x-tts-access-token: {access_token}' \
'https://open-api.tiktokglobalshop.com/product/202309/categories?access_token={access_token}&app_key={app_key}&shop_cipher={shop_cipher}&shop_id={shop_id}&sign={sign}&timestamp=1783502536&version=202309'
```

**Sanitized response** (example — array truncated to 1 category; live response returns full category tree)
```json
{"code":0,"data":{"categories":[{"id":"601450","is_leaf":false,"local_name":"Chăm sóc sắc đẹp & Chăm sóc cá nhân","parent_id":"0","permission_statuses":["AVAILABLE"]}],"next_page_token":"{page_token}","total_count":"{count}"},"message":"Success"}
```

---

## A-22. Check Listing Prerequisites / Get Brands (Create Hero Product steps 2, 4)

| Field | Value |
|-------|-------|
| Operation | `Check Listing Prerequisites` (seller/category eligibility) + `Get Brands` (`brand_id` where required) |
| Version | `202312` (verify in Products API Testing Tool) |
| Method / path | `GET /product/202312/prerequisites` (brands under separate `GET /product/202309/brands`, not yet captured) |
| Required | `category_id` |

**cURL**
```bash
curl -k -X 'GET' -H 'x-tts-access-token: {access_token}' \
'https://open-api.tiktokglobalshop.com/product/202312/prerequisites?access_token={access_token}&app_key={app_key}&shop_cipher={shop_cipher}&shop_id={shop_id}&sign={sign}&timestamp=1783502868&version=202312'
```

**Sanitized response**
```json
{"code":0,"data":{"check_results":[{"check_item":"SHOP_STATUS","fail_reasons":[],"is_failed":false},{"check_item":"SHOP_TAX","fail_reasons":[],"is_failed":false}]},"message":"Success","request_id":"{request_id}"}
```

---

## A-23. Get Products SEO Words (Create Hero Product step 6 · Optimize Product step 2)

| Field | Value |
|-------|-------|
| Version | `202405` |
| Method / path | `GET /product/202405/products/seo_words` |

**cURL**
```bash
curl -X GET 'https://open-api.tiktokglobalshop.com/product/202405/products/seo_words?app_key={app_key}&sign={sign}&timestamp=1623812664&shop_cipher={shop_cipher}&product_ids=1734952395144267383' \
-H 'x-tts-access-token: {access_token}' -H 'content-type: application/json'
```

**Sanitized response**
```json
{"code":0,"data":{"products":[{"id":"1734952395144267383","seo_words":[]}]},"message":"Success","request_id":"{request_id}"}
```

---

## A-24. Get Recommended Product Title and Description (Create Hero Product step 7 · Optimize Product step 3)

| Field | Value |
|-------|-------|
| Version | `202405` |
| Method / path | `GET /product/202405/products/suggestions` |

**cURL**
```bash
curl -k -X 'GET' -H 'x-tts-access-token: {access_token}' \
'https://open-api.tiktokglobalshop.com/product/202405/products/suggestions?access_token={access_token}&app_key={app_key}&product_ids=1734952395144267383&shop_cipher={shop_cipher}&shop_id={shop_id}&sign={sign}&timestamp=1783503876&version=202405'
```

**Sanitized response**
```json
{"code":0,"data":{"products":[{"id":"1734952395144267383","suggestions":[{"field":"TITLE","items":[]},{"field":"DESCRIPTION","items":[]}]}]},"message":"Success","request_id":"{request_id}"}
```

---

## A-25. Get Activity (Promotion lifecycle read)

Replaces Search Promotion Activity — no list/search endpoint exists. Use `activity_id`
from B-5 Create Activity response or webhook #39 (`PROMOTION_ACTIVITY_STATUS_CHANGE`).

| Field | Value |
|-------|-------|
| Version | `202309` |
| Method / path | `GET /promotion/202309/activities/{activity_id}` |
| Required | `activity_id`; query `app_key`, `sign`, `timestamp`, `shop_cipher`; header `x-tts-access-token` |

**cURL**
```bash
curl -X GET \
'https://open-api.tiktokglobalshop.com/promotion/202309/activities/7402881377634567979?app_key={app_key}&sign={sign}&timestamp=1623812664&shop_cipher={shop_cipher}' \
-H 'x-tts-access-token: {access_token}' \
-H 'content-type: application/json'
```

**Sanitized response**
```json
{"code":0,"data":{"activity_id":"7136104329798256386","title":"FlashSale 20230707","activity_type":"FIXED_PRICE","duration_type":"INDEFINITE","begin_time":1661756811,"end_time":1661856811,"participation_limit":[{"type":"NO_LIMIT"}],"products":[{"id":"7136011254174631686","activity_price":{"amount":"70500","currency":"IDR"},"quantity_limit":-1,"quantity_per_user":-1,"discount":"10","skus":[{"id":"7136382541418366725","discount":"10","quantity_limit":-1,"quantity_per_user":-1,"activity_price":{"amount":"70500","currency":"IDR"}}]}],"status":"ONGOING","create_time":1661750811,"update_time":1661750811,"product_level":"PRODUCT","activity_commands":"IMMUTABLE","target_user_info":{"user_type":"ALL_USER"}},"message":"Success","request_id":"{request_id}"}
```

---

# Section B — SANDBOX_VN (Write / State-Mutating)

Use **SANDBOX_VN** credentials only. Never run these against Fujiwa. Business failures from
sparse sandbox data are acceptable; the goal is technical validation (signing, payload, auth,
response parsing).

## B-1. Update Inventory

| Field | Value |
|-------|-------|
| Version | `202309` |
| Method / path | `POST /product/202309/products/{product_id}/inventory/update` |
| Body | `skus[].id`, `skus[].inventory[].warehouse_id`, `skus[].inventory[].quantity` |

**cURL**
```bash
curl -k -X 'POST' -d '{"skus":[{"id":"1736404513645233795","inventory":[{"quantity":15}]}]}' -H 'Content-Type: application/json' -H 'x-tts-access-token: {access_token}' \
'https://open-api.tiktokglobalshop.com/product/202309/products/1736363193934775939/inventory/update?access_token={access_token}&app_key={app_key}&shop_cipher={shop_cipher}&shop_id={shop_id}&sign={sign}&timestamp=1783310676&version=202309'
```

**Sanitized response**
```json
{"code":0,"data":{},"message":"Success","request_id":"{request_id}"}
```

---

## B-2. Upload Product Image — NOT AVAILABLE VIA TESTING TOOL

| Field | Value |
|-------|-------|
| Version | `202309` |
| Method / path | `POST /product/202309/images/upload` |
| Response | Image `uri` used by Create Product |
| Notes | No cURL/response captured — Partner Center Testing Tool does not support multipart image upload. Needs a direct integration test against sandbox before the Create Hero Product chain can be automated end-to-end. |

---

## B-3. Create Product

| Field | Value |
|-------|-------|
| Version | `202309` |
| Method / path | `POST /product/202309/products` |
| Body | `category_id`, `title`, `description`, `main_images[].uri`, `skus[]`, required `product_attributes[]` |
| Notes | Same endpoint for single-SKU and multi-SKU creation; multi-SKU payload must include every SKU and sales attribute |

**cURL**
```bash
curl -k -X 'POST' -d '{"description":"Durable Stainless Water Bottle for everyday use","category_id":"605254","category_version":"v2","title":"Premium Stainless Steel Water Bottle 750ml","main_images":[{"uri":"tos-alisg-i-aphluv4xwc-sg/{image_uri}"}],"skus":[{"seller_sku":"water-bottle-100ml","inventory":[{"warehouse_id":"7657265511696664340","quantity":100}],"price":{"amount":"100000","currency":"VND"},"list_price":{"amount":"100000","currency":"VND"}}],"product_attributes":[{"id":"100149","values":[{"id":"1000854"}]},{"id":"101489","values":[{"name":"Fujiwa"}]},{"id":"101490","values":[{"name":"Fujiwa"}]}],"package_weight":{"value":"500","unit":"GRAM"}}' -H 'Content-Type: application/json' -H 'x-tts-access-token: {access_token}' \
'https://open-api.tiktokglobalshop.com/product/202309/products?access_token={access_token}&app_key={app_key}&shop_cipher={shop_cipher}&shop_id={shop_id}&sign={sign}&timestamp=1783316518&version=202309'
```

**Sanitized response**
```json
{"code":0,"data":{"product_id":"1736405947247986307","skus":[{"id":"1736405690908575363","seller_sku":"water-bottle-100ml"}],"warnings":[]},"message":"Success","request_id":"{request_id}"}
```

---

## B-4. Edit Product (Partial)

| Field | Value |
|-------|-------|
| Version | `202309` |
| Method / path | `PUT /product/202309/products/{product_id}` — a `202509` full-replace variant is unconfirmed; do not use until verified |
| Required | `product_id`; edited fields; category attributes if category changes |

**cURL**
```bash
curl -k -X 'PUT' -d '{"description":"Highly durable Stainless Water Bottle for active use","category_id":"605254","title":"Authentic Stainless Steel Water Bottle 750ml","category_version":"v2","skus":[{"inventory":[{"warehouse_id":"7657265511696664340","quantity":50}],"price":{"amount":"100000","currency":"VND"}}],"package_weight":{"value":"500","unit":"GRAM"}}' -H 'Content-Type: application/json' -H 'x-tts-access-token: {access_token}' \
'https://open-api.tiktokglobalshop.com/product/202309/products/1736405947247986307?access_token={access_token}&app_key={app_key}&shop_cipher={shop_cipher}&shop_id={shop_id}&sign={sign}&timestamp=1783484523&version=202309'
```

**Sanitized response**
```json
{"code":0,"data":{"audit":{"status":"APPROVED"},"product_id":"1736405947247986307","skus":[{"id":"1736433041572857475"}],"warnings":[]},"message":"Success","request_id":"{request_id}"}
```

---

## B-5. Create Activity

| Field | Value |
|-------|-------|
| Operation | `createActivity` |
| Version | `202309` |
| Method / path | `POST /promotion/202309/activities` |
| Body | `activity_type`, `title`, `begin_time`, `end_time`, product level / discount config |

**cURL**
```bash
curl -k -X 'POST' -d '{"title":"7/7 Flash Sale","activity_type":"FLASHSALE","product_level":"VARIATION","duration_type":"FIXED_TIME","begin_time":1783411200,"end_time":1783432800,"target_user_info":{},"participation_limit":[{"type":"BUYER_LIMIT_ONLY_ONE"}]}' -H 'Content-Type: application/json' -H 'x-tts-access-token: {access_token}' \
'https://open-api.tiktokglobalshop.com/promotion/202309/activities?access_token={access_token}&app_key={app_key}&shop_cipher={shop_cipher}&shop_id={shop_id}&sign={sign}&timestamp=1783485034&version=202309'
```

**Sanitized response**
```json
{"code":0,"data":{"activity_id":"7660009586606409490","create_time":1783485034,"status":"EXPIRED","update_time":1783485034},"message":"Success","request_id":"{request_id}"}
```

---

## B-6. Update Activity

| Field | Value |
|-------|-------|
| Version | `202309` |
| Method / path | `PUT /promotion/202309/activities/{activity_id}` |
| Required | `activity_id`, updated title/schedule |

**cURL**
```bash
curl -k -X 'PUT' -d '{"title":"URGENT 7/7 FLASHSALE BUY NOW!!!","begin_time":1783600001,"end_time":1783686401}' -H 'Content-Type: application/json' -H 'x-tts-access-token: {access_token}' \
'https://open-api.tiktokglobalshop.com/promotion/202309/activities/7660012771723118343?access_token={access_token}&app_key={app_key}&shop_cipher={shop_cipher}&shop_id={shop_id}&sign={sign}&timestamp=1783485981&version=202309'
```

**Sanitized response**
```json
{"code":0,"data":{"activity_id":"7660012771723118343","title":"URGENT 7/7 FLASHSALE BUY NOW!!!","update_time":1783485981},"message":"Success","request_id":"{request_id}"}
```

---

## B-7. Update Activity Product

| Field | Value |
|-------|-------|
| Operation | `updateActivityProduct` |
| Version | `202309` |
| Method / path | `PUT /promotion/202309/activities/{activity_id}/products` |
| Required | `activity_id`, `product_id`, `sku_id`, activity price/discount |

**cURL**
```bash
curl -k -X 'PUT' -d '{"activity_id":"7660012771723118343","products":[{"id":"1736405947247986307","quantity_limit":-1,"quantity_per_user":1,"skus":[{"id":"1736433041572857475","quantity_limit":-1,"quantity_per_user":1,"activity_price_amount":"80000"}]}]}' -H 'Content-Type: application/json' -H 'x-tts-access-token: {access_token}' \
'https://open-api.tiktokglobalshop.com/promotion/202309/activities/7660012771723118343/products?access_token={access_token}&app_key={app_key}&shop_cipher={shop_cipher}&shop_id={shop_id}&sign={sign}&timestamp=1783486680&version=202309'
```

**Sanitized response**
```json
{"code":0,"data":{"activity_id":"7660012771723118343","status":"NOT_START","title":"URGENT 7/7 FLASHSALE BUY NOW!!!","total_count":1,"update_time":1783486681},"message":"Success","request_id":"{request_id}"}
```

---

## B-8. Deactivate Activity

| Field | Value |
|-------|-------|
| Version | `202309` |
| Method / path | `POST /promotion/202309/activities/{activity_id}/deactivate` |
| Required | `activity_id` |

**cURL**
```bash
curl -k -X 'POST' -d '{}' -H 'Content-Type: application/json' -H 'x-tts-access-token: {access_token}' \
'https://open-api.tiktokglobalshop.com/promotion/202309/activities/7660012771723118343/deactivate?access_token={access_token}&app_key={app_key}&shop_cipher={shop_cipher}&shop_id={shop_id}&sign={sign}&timestamp=1783487506&version=202309'
```

**Sanitized response**
```json
{"code":0,"data":{"activity_id":"7660012771723118343","status":"DEACTIVATED","title":"URGENT 7/7 FLASHSALE BUY NOW!!!","update_time":1783487506},"message":"Success","request_id":"{request_id}"}
```

---

## B-9. Approve Cancellation

| Field | Value |
|-------|-------|
| Version | `202309` — best-guess, matches verified Search Cancellations family (A-7); not independently confirmed for this write |
| Method / path | `POST /return_refund/202309/cancellations/{cancel_id}/approve` |
| Required | `cancel_id`; query `idempotency_key` |

**cURL**
```bash
curl -X POST 'https://open-api.tiktokglobalshop.com/return_refund/202309/cancellations/98001001/approve?idempotency_key={idempotency_key}&app_key={app_key}&sign={sign}&timestamp=1623812664&shop_cipher={shop_cipher}' \
-H 'x-tts-access-token: {access_token}' -H 'content-type: application/json' -d '{}'
```

**Sanitized response**
```json
{"code":0,"data":{},"message":"Success","request_id":"{request_id}"}
```

---

## B-10. Reject Cancellation

| Field | Value |
|-------|-------|
| Version | `202309` — best-guess, matches verified Search Cancellations family (A-7); not independently confirmed for this write |
| Method / path | `POST /return_refund/202309/cancellations/{cancel_id}/reject` |
| Required | `cancel_id`; query `idempotency_key`; rejection reason payload |

**cURL**
```bash
curl -X POST 'https://open-api.tiktokglobalshop.com/return_refund/202309/cancellations/4035319218955782461/reject?app_key={app_key}&sign={sign}&timestamp=1623812664&shop_cipher={shop_cipher}&idempotency_key={idempotency_key}' \
-H 'x-tts-access-token: {access_token}' -H 'content-type: application/json' \
-d '{"reject_reason":"seller_reject_apply_product_has_been_packed","comment":"[REDACTED]","images":[{"image_id":"tos-maliva-i-o3syd03w52-us/{image_id}","mime_type":"image/png","height":200,"width":200}]}'
```

**Sanitized response**
```json
{"code":0,"data":{},"message":"Success","request_id":"{request_id}"}
```

---

## B-11. Approve Return (also used for Approve Refund, 8c)

| Field | Value |
|-------|-------|
| Version | `202309` — best-guess, matches verified Search Returns family (A-6); not independently confirmed for this write |
| Method / path | `POST /return_refund/202309/returns/{return_id}/approve` |
| Required | `return_id`; query `idempotency_key`; refund/return approval payload |

**cURL**
```bash
curl -k -X 'POST' -d '{"decision":"APPROVE_REFUND"}' -H 'Content-Type: application/json' -H 'x-tts-access-token: {access_token}' \
'https://open-api.tiktokglobalshop.com/return_refund/202309/returns/4041276083648758794/approve?access_token={access_token}&app_key={app_key}&shop_cipher={shop_cipher}&shop_id=&sign={sign}&timestamp=1783495422&version=202309'
```

**Sanitized response**
```json
{"code":0,"data":{},"message":"Success","request_id":"{request_id}"}
```

---

## B-12. Reject Return (also used for Reject Refund, 8c)

| Field | Value |
|-------|-------|
| Version | `202309` — best-guess, matches verified Search Returns family (A-6); not independently confirmed for this write |
| Method / path | `POST /return_refund/202309/returns/{return_id}/reject` |
| Required | `return_id`; query `idempotency_key`; rejection reason payload |

**cURL**
```bash
curl -X POST 'https://open-api.tiktokglobalshop.com/return_refund/202309/returns/4035319218955782461/reject?app_key={app_key}&sign={sign}&timestamp=1623812664&shop_cipher={shop_cipher}&idempotency_key={idempotency_key}' \
-H 'x-tts-access-token: {access_token}' -H 'content-type: application/json' \
-d '{"decision":"REJECT_RECEIVED_PACKAGE","reject_reason":"seller_reject_apply_package_has_not_exceeded_estimated_delivery_time","comment":"[REDACTED]","images":[{"image_id":"tos-maliva-i-o3syd03w52-us/{image_id}","mime_type":"image/png","height":200,"width":200}]}'
```

**Sanitized response**
```json
{"code":0,"data":{},"message":"Success","request_id":"{request_id}"}
```

---

## B-13. Combine Package

| Field | Value |
|-------|-------|
| Version | `202309` |
| Method / path | `POST /fulfillment/202309/packages/combine` |
| Required | `combinable_packages[]` / package IDs from Search Combinable Packages (A-11) |

**cURL** (example — no live sandbox data available at capture time)
```bash
curl -X POST 'https://open-api.tiktokglobalshop.com/fulfillment/202309/packages/combine?app_key={app_key}&sign={sign}&timestamp=1623812664&shop_cipher={shop_cipher}' \
-H 'x-tts-access-token: {access_token}' -H 'content-type: application/json' \
-d '{"combinable_packages":[{"id":"12321313133","order_ids":["1233213123123"]}]}'
```

**Sanitized response** (example)
```json
{"code":0,"data":{"packages":[{"id":"413234134123412","order_ids":["1233213123123"]}],"errors":[{"code":10007014,"message":"fulfillment not allow combine package","detail":{"package_id":"{package_id}"}}]},"message":"Success","request_id":"{request_id}"}
```

---

## B-14. Ship Package

| Field | Value |
|-------|-------|
| Version | `202309` |
| Method / path | `POST /fulfillment/202309/packages/{package_id}/ship` |

**cURL**
```bash
curl -k -X 'POST' -d '{}' -H 'Content-Type: application/json' -H 'x-tts-access-token: {access_token}' \
'https://open-api.tiktokglobalshop.com/fulfillment/202309/packages/1202809545811788810/ship?access_token={access_token}&app_key={app_key}&shop_cipher={shop_cipher}&shop_id=&sign={sign}&timestamp=1783491980&version=202309'
```

**Sanitized response**
```json
{"code":0,"data":{},"message":"Success","request_id":"{request_id}"}
```

---

## B-15. Confirm Package Shipment (Supply Chain API)

| Field | Value |
|-------|-------|
| Operation | Moved from Fulfillment API to Supply Chain API this pass |
| Version | `202309` |
| Method / path | `POST /supply_chain/202309/packages/sync` |
| Required | `package_id`, shipment confirmation payload |
| Notes | Not yet captured — no cURL/response available. First Supply Chain API contract row in this file; needs a sandbox capture before implementation. |

---

## B-16. Batch Ship Packages

| Field | Value |
|-------|-------|
| Operation | Alternative to single Ship Package (B-14) for shipping multiple packages in one call |
| Version | `202309` |
| Method / path | `POST /fulfillment/202309/packages/ship` |
| Required | `package_id[]`, shipment payload |

**cURL** (example — no live sandbox data available at capture time)
```bash
curl -X POST 'https://open-api.tiktokglobalshop.com/fulfillment/202309/packages/ship?app_key={app_key}&sign={sign}&timestamp=1623812664&shop_cipher={shop_cipher}' \
-H 'x-tts-access-token: {access_token}' -H 'content-type: application/json' \
-d '{"packages":[{"id":"12321312312431","handover_method":"PICKUP","pickup_slot":{"start_time":1623812664,"end_time":1623812664},"self_shipment":{"tracking_number":"JX12345","shipping_provider_id":"6617675021119438849"}}]}'
```

**Sanitized response** (example)
```json
{"code":0,"data":{"errors":[{"code":10007014,"message":"package in freeze status","detail":{"package_id":"{package_id}"}}]},"message":"Success","request_id":"{request_id}"}
```

---

## B-17. Split Orders

| Field | Value |
|-------|-------|
| Version | `202309` (verify) |
| Method / path | `POST /fulfillment/202309/orders/{order_id}/split` |
| Required | `order_id`, split line-item allocation |
| Notes | Follows Get Order Split Attributes (A-10) in the Handle Split Package workflow |

**cURL** (example — no live sandbox data available at capture time)
```bash
curl -X POST 'https://open-api.tiktokglobalshop.com/fulfillment/202309/orders/556643423444/split?sign={sign}&timestamp=1623812664&shop_cipher={shop_cipher}&app_key={app_key}' \
-H 'content-type: application/json' -H 'x-tts-access-token: {access_token}' \
-d '{"splittable_groups":[{"id":"123","order_line_item_ids":["57646237751283022"]}]}'
```

**Sanitized response** (example)
```json
{"code":0,"data":{"packages":[{"splittable_group_id":"123","id":"223362377512830222"}]},"message":"Success","request_id":"{request_id}"}
```

---

## B-18. Uncombine Packages

| Field | Value |
|-------|-------|
| Operation | Optional rollback before shipment |
| Version | `202309` (verify) |
| Method / path | `POST /fulfillment/202309/packages/{package_id}/uncombine` |
| Required | `package_id` |

**cURL** (example — no live sandbox data available at capture time)
```bash
curl -X POST 'https://open-api.tiktokglobalshop.com/fulfillment/202309/packages/1231231231231313123132/uncombine?shop_cipher={shop_cipher}&app_key={app_key}&sign={sign}&timestamp=1623812664' \
-H 'x-tts-access-token: {access_token}' -H 'content-type: application/json' \
-d '{"order_ids":["11132131131"]}'
```

**Sanitized response** (example)
```json
{"code":0,"data":{"packages":[{"id":"123456","order_ids":["576462377512830168"]}]},"message":"Success","request_id":"{request_id}"}
```

---

## B-19. Review Aftersales (8b Prevent Return escalation path)

| Field | Value |
|-------|-------|
| Operation | Escalation-path review for ambiguous/high-risk cases (high fraud score, e.g. suspected `item_swap`/`empty_return`) before a seller decision |
| Version | `202603` |
| Method / path | `POST /return_refund/202603/aftersales/review` |
| Required | `return_id`, review outcome payload |

**cURL** (example — no live sandbox data available at capture time)
```bash
curl -X POST 'https://open-api.tiktokglobalshop.com/return_refund/202603/aftersales/review?app_key={app_key}&sign={sign}&timestamp=1623812664&shop_cipher={shop_cipher}' \
-H 'x-tts-access-token: {access_token}' -H 'content-type: application/json' \
-d '{"aftersales_request_decisions":[{"request_id":"4035319218955782461","request_id_type":"AFTERSALES","line_item_decisions":[{"line_items":[{"return_line_item_id":"4035227657962164811"}],"action":"APPROVE_REQUEST"}],"idempotency_key":"{idempotency_key}"}]}'
```

**Sanitized response** (example)
```json
{"code":0,"data":{"errors":[{"code":"98001004","message":"Invalid parameters. Please verify your input before retrying"}]},"message":"Success","request_id":"{request_id}"}
```

---

## B-20. Update Price (Optimize Product step 6 · Clear Excess Inventory step 3)

| Field | Value |
|-------|-------|
| Version | `202309` |
| Method / path | `POST /product/202309/products/{product_id}/prices/update` |
| Required | `product_id`, `skus[].id`, `skus[].price` payload |

**cURL**
```bash
curl -k -X 'POST' -d '{"skus":[{"id":"1736433041572857475","price":{"currency":"VND","amount":"80000"}}]}' -H 'Content-Type: application/json' -H 'x-tts-access-token: {access_token}' \
'https://open-api.tiktokglobalshop.com/product/202309/products/1736405947247986307/prices/update?access_token={access_token}&app_key={app_key}&shop_cipher={shop_cipher}&shop_id={shop_id}&sign={sign}&timestamp=1783504020&version=202309'
```

**Sanitized response**
```json
{"code":0,"data":{},"message":"Success","request_id":"{request_id}"}
```

---

## Removed operations — do not implement

**Coupon operations** (Create Coupon, Search Coupons, Get Coupon Detail, Delete/Deactivate
Coupon): investigated and removed. No `POST` (create) operation exists for seller-facing
coupon creation via the Partner API — coupons appear to be Seller Center-only in the current
API surface. Re-add only if a verified create-coupon contract is found in a future API version.

---

## Submission checklist

- [Good] Section A read endpoints (A-1 through A-25) have cURL + response status (or documented failure with TikTok `code`)
- [Good] Section B write endpoints (B-1 through B-20) have cURL + response status (business errors OK)
- **Both Endpoints are not available, remove**  B-2 (Upload Product Image) and B-15 (Confirm Package Shipment) still need a first capture — no sample exists yet
- **KEEP Search Aftersales Request endpoint** A-17 (Search RMA) vs A-18 (Search Aftersales Request) — **deferred** until Fujiwa sandbox capture
- **Get Activity replaces Search** A-25 verified — `GET /promotion/202309/activities/{activity_id}`; B-5–B-8 promotion writes verified
- **Use version 202309** A-2 (Search Products) re-captured at `202502` per execution_layer.md
- **Verify this, credentials will be store in supabase** No secrets in any cURL — all tokens/signs are placeholders in this file; real values only in `.env` / secrets manager

