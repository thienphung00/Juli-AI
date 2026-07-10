# TikTok Shop API — Contract Collection Template

> **Purpose:** Collect verified Request Demo cURL and Response Status from the Partner Center
> **API Testing Tool** before Phase 2 implementation begins.  
> **Authority:** [`EXECUTION.md`](../../EXECUTION.md) P2-A1 · Plan: Phase 2 TikTok Shop Backend & ETL.

**How to use**

1. **Automated (issue #279):** with `.env` containing `DATABASE_URL`, `TIKTOK_APP_KEY`, `TIKTOK_APP_SECRET`, and token encryption key:
   ```bash
   python scripts/collect_authorized_shops_contract.py --write-docs
   ```
   Calls `GET /authorization/202309/shops` for Fujiwa + SANDBOX_VN and fills §3 below.
2. Open [Partner Center → Documents → API Testing Tool](https://partner.tiktokshop.com/docv2/page/).
3. For each endpoint below, run the operation with the correct merchant credentials.
4. Paste the **Request Demo cURL** and record the **Response Status** (HTTP code + TikTok `code` field).
5. Optionally paste a **sanitized response body** (redact tokens, buyer PII, full signed URLs).
6. Return this file (or a copy) when complete. Implementation starts only after Layer 1 + selected Layer 2 rows are filled.

**Merchant credentials**

| Merchant | Authorization ID | Use for layers |
|----------|------------------|----------------|
| **Fujiwa** (production) | `7658073774813611784` | Layer 1 — read only |
| **SANDBOX_VN** (sandbox) | `7658096633384781588` | Layer 2 — write validation |

---

## Workflow endpoint coverage

Use this table as the canonical checklist for the Phase 2 execution workflows. Rows marked
`Sandbox evidence required` must have API Testing Tool cURL + response status before a
write resource is implemented.

| Workflow | API category | Endpoint chain | Required IDs | Contract rows |
|----------|--------------|----------------|--------------|---------------|
| Create Hero Product (formerly Create New Product Listing) | Products | Get Category → Check Listing Prerequisites → Get Category Attributes → Get Brands → Upload Product Image → Get SEO Words → Get Recommended Title/Description → Create Product → Search Product | `category_id`, `brand_id` if required, image `uri`, returned `product_id` | 4, 15-17, 51-55 |
| Create Multi-SKU Product | Products | Same chain as Create Hero Product, Create Product with all SKU rows | `category_id`, `brand_id` if required, image `uri`, returned `product_id`, returned `sku_id`s | 4, 15-17, 51-55 |
| Optimize Product (formerly Update Product Listing) | Products | Get Product → Get Category Attributes → Get SEO Words → Get Recommended Title/Description → Upload Product Image → Edit Product → Update Price | `product_id`, `category_id` if changed | 5, 15-16, 18, 53-54, 56 |
| Process Order (formerly Accelerate Order Fulfillment) | Orders / Fulfillment / Supply Chain | Search Orders → Get Order Detail → Create Packages → Get Package Shipping Document → Ship Package (or Batch Ship Packages) → Confirm Package Shipment → Get Package Detail | `order_id`, returned `package_id` | 6-7, 31-33, 38-40 |
| Handle Split Package | Fulfillment | Get Order Split Attributes → Split Orders → Search Combinable Packages → Combine Package → Uncombine Packages | `order_id`, draft `package_id`s | 28-30, 41-42 |
| Update / Replenish / Clear Inventory | Products | Inventory Search → Update Inventory | `product_id`, `sku_id`, `warehouse_id` | 10, 14 |
| Prevent Cancellation (8a, formerly Process Cancellation / Prevent Order Cancellations) | Return/Refund | Search Cancellations → Get Decision Eligibility → Get Reject Reasons → Approve Cancellation or Reject Cancellation | `cancel_id` from search, `order_id` for traceability | 9, 24-25, 43, 45 |
| Prevent Return (8b, formerly Manage Return / Refund / Prevent Product Returns) | Return/Refund + Products | Search Returns → Get Aftersale Eligibility → Search RMA → Review Aftersales → Get Reject Reasons → Approve Return or Reject Return → Update Inventory | `return_id`, `order_id` for traceability | 8, 26-27, 44-47, 14 |
| Prevent Refund (8c, new this pass) | Return/Refund | Search Aftersales Request → Calculate Refund → Get Reject Reasons → Approve Refund or Reject Refund | `return_id` | 26-27, 45, 48-49 |
| Create / Delete / Update Activity (formerly Create / Activate Promotion) | Promotion | Create Activity → Update Activity Product → Search Activity → Deactivate Activity → Update Activity | `activity_id`, `product_id`, `sku_id` | 20-23 |
| ~~Create Voucher / Coupon~~ — REMOVED | Promotion | No seller-facing create-coupon operation exists; do not implement | `coupon_id` | 34-37 (marked removed) |

---

## Global parameters (fill once)

| Parameter | Your value | Notes |
|-----------|------------|-------|
| `app_key` | | Partner Center App Key |
| `app_secret` | | Never commit — env var only |
| Fujiwa `shop_cipher` | | From Get Authorized Shops (Fujiwa) |
| SANDBOX_VN `shop_cipher` | | From Get Authorized Shops (SANDBOX_VN) |
| Fujiwa `access_token` | | Short-lived — supplied out-of-band, never committed |
| SANDBOX_VN `access_token` | | Short-lived — supplied out-of-band, never committed |
| Open API base URL used | | Default `https://open-api.tiktokglobalshop.com` |
| Date tested (UTC) | | |

> **Tokens:** access/refresh tokens are managed by the backend OAuth flow and stored encrypted
> (`TikTokCredential` in Postgres). Do not paste live tokens or ciphertext blobs into this doc.

---

## Layer 1 — Production read validation (Fujiwa)

Use **Fujiwa** credentials only. Do not run write operations on production.

### 3. Get Authorized Shops

| Field | Expected | Verified |
|-------|----------|----------|
| Version | `202309` | |
| Method / path | `GET /authorization/202309/shops` | |
| Required | `app_key`, `timestamp`, `sign`; header `x-tts-access-token` | |

**Request Demo cURL**

```bash
curl -k -X 'GET' -H 'x-tts-access-token: ROW_9A2D_gAAAABbUg_84te3E8INEevR-bbuEOnDJM8WtbRPbpEwfsb5vN-A3kch8o1Z75o0SKWI1WMZNro6FFwXDAoubTUFWba-wu0a6b8xw8B7Q6Fc1f97S1sAFq4mI6QebiXx05mg_cJbx-b8V2Pbxwjylm_S4HwMzrK-wmUhl-pdudAys_OUQHHd5Qfbz-ITIJuoXrj1Q0k' 'https://open-api.tiktokglobalshop.com/authorization/202309/shops?access_token=ROW_9A2D_gAAAABbUg_84te3E8INEevR-bbuEOnDJM8WtbRPbpEwfsb5vN-A3kch8o1Z75o0SKWI1WMZNro6FFwXDAoubTUFWba-wu0a6b8xw8B7Q6Fc1f97S1sAFq4mI6QebiXx05mg_cJbx-b8V2Pbxwjylm_S4HwMzrK-wmUhl-pdudAys_OUQHHd5Qfbz-ITIJuoXrj1Q0k&app_key=6kdu4f07vvlv9&shop_id=&sign=bd25e840c5dc439a2886e76ca3f777054d4fb39d8b5be268bb5e98be32877615&timestamp=1783303591&version=202309'
```

**Response**

{"code":0,"data":{"shops":[{"cipher":"ROW_aiVo7gAAAAB2vvlFyfTxbVr4ZFHoDbhK","code":"VNLCTNWY6A","id":"7495274531001436791","name":"Fujiwa Vietnam Store","region":"VN","seller_type":"LOCAL"}]},"message":"Success","request_id":"20260706100631FA1A0EF987AB287080F1"}

**Sanitized response body (optional)**

```json

```

---

### 4. Search Products

| Field | Expected | Verified |
|-------|----------|----------|
| Version | `202309` | |
| Method / path | `POST /product/202309/products/search` | |
| Required | `app_key`, `timestamp`, `sign`, `shop_cipher`; header `x-tts-access-token` | |
| Optional body | `status` | |
| Optional query | `page_size`, `page_token` | |
| Optional body (verify) | `update_time_ge`, `update_time_lt` | |

> **Version note:** `execution_layer.md` targets `202309` (Search Product). The captured cURL
> below was run at `202502`; re-capture at `202309` to finalize the contract.



**Request Demo cURL**

```bash
curl -k -X 'POST' -d '{}' -H 'Content-Type: application/json' -H 'x-tts-access-token: ROW_9A2D_gAAAABbUg_84te3E8INEevR-bbuEOnDJM8WtbRPbpEwfsb5vN-A3kch8o1Z75o0SKWI1WMZNro6FFwXDAoubTUFWba-wu0a6b8xw8B7Q6Fc1f97S1sAFq4mI6QebiXx05mg_cJbx-b8V2Pbxwjylm_S4HwMzrK-wmUhl-pdudAys_OUQHHd5Qfbz-ITIJuoXrj1Q0k' 'https://open-api.tiktokglobalshop.com/product/202502/products/search?access_token=ROW_9A2D_gAAAABbUg_84te3E8INEevR-bbuEOnDJM8WtbRPbpEwfsb5vN-A3kch8o1Z75o0SKWI1WMZNro6FFwXDAoubTUFWba-wu0a6b8xw8B7Q6Fc1f97S1sAFq4mI6QebiXx05mg_cJbx-b8V2Pbxwjylm_S4HwMzrK-wmUhl-pdudAys_OUQHHd5Qfbz-ITIJuoXrj1Q0k&app_key=6kdu4f07vvlv9&page_size=1&shop_cipher=ROW_aiVo7gAAAAB2vvlFyfTxbVr4ZFHoDbhK&shop_id=&sign=7ee652775980e569d57cb9cdf67792c02204eaa14cd0bb7328a3966fb2e1e0f0&timestamp=1783304875&version=202502'
```

**Response**

{"code":0,"data":{"next_page_token":"WzE3NzUxMjMyMTQzMTAsIjE3MzQ5NTIzOTUxNDQyNjczODMiXQ==","products":[{"audit":{"pre_approved_reasons":[],"status":"APPROVED"},"create_time":1775123176,"has_draft":false,"id":"1734952395144267383","is_not_for_sale":false,"product_tags":[],"recommended_categories":[],"sales_regions":["VN"],"skus":[{"id":"1734952449674217079","inventory":[{"quantity":43,"warehouse_id":"7272949914115966726"}],"price":{"currency":"VND","tax_exclusive_price":"72000"},"seller_sku":"XTM-C","status_info":{"status":"NORMAL"}}],"status":"ACTIVATE","title":"[Quà Tặng] Chai Xịt Thơm Miệng Fujisalt 14mL Khử Mùi Hiệu Quả, Giữ Hơi Thở Thơm Mát","update_time":1782892330}],"total_count":117},"message":"Success","request_id":"20260706102754BEFE657E67887D654C06"}

**Sanitized response body (optional)**

```json

```

---

### 5. Get Product (New)

| Field | Expected | Verified |
|-------|----------|----------|
| Version | `202309` | |
| Method / path | `GET /product/202309/products/{product_id}` | |
| Required | `product_id`, signing params, `shop_cipher`; header `x-tts-access-token` | |
| `product_id` used | | Fill test product ID |

**Request Demo cURL**

```bash
curl -k -X 'GET' -H 'x-tts-access-token: ROW_9A2D_gAAAABbUg_84te3E8INEevR-bbuEOnDJM8WtbRPbpEwfsb5vN-A3kch8o1Z75o0SKWI1WMZNro6FFwXDAoubTUFWba-wu0a6b8xw8B7Q6Fc1f97S1sAFq4mI6QebiXx05mg_cJbx-b8V2Pbxwjylm_S4HwMzrK-wmUhl-pdudAys_OUQHHd5Qfbz-ITIJuoXrj1Q0k' 'https://open-api.tiktokglobalshop.com/product/202309/products/1734952395144267383?access_token=ROW_9A2D_gAAAABbUg_84te3E8INEevR-bbuEOnDJM8WtbRPbpEwfsb5vN-A3kch8o1Z75o0SKWI1WMZNro6FFwXDAoubTUFWba-wu0a6b8xw8B7Q6Fc1f97S1sAFq4mI6QebiXx05mg_cJbx-b8V2Pbxwjylm_S4HwMzrK-wmUhl-pdudAys_OUQHHd5Qfbz-ITIJuoXrj1Q0k&app_key=6kdu4f07vvlv9&shop_cipher=ROW_aiVo7gAAAAB2vvlFyfTxbVr4ZFHoDbhK&shop_id=&sign=a66eab805774fe950e0f5cea2232653e1cdbe9cb004d4c2f69c16b198639719f&timestamp=1783305447&version=202309'
```

**Response**

{"code":0,"data":{"audit":{"pre_approved_reasons":[],"status":"APPROVED"},"brand":{"id":"7273019489648756485","name":"Fujiwa Vietnam"},"category_chains":[{"id":"601450","is_leaf":false,"local_name":"Chăm sóc sắc đẹp & Chăm sóc cá nhân","parent_id":"0"},{"id":"849672","is_leaf":false,"local_name":"Chăm sóc mũi & răng miệng","parent_id":"601450"},{"id":"601693","is_leaf":true,"local_name":"Xịt miệng","parent_id":"849672"}],"create_time":1775123176,"description":"<p style=\"text-align: left;\"><span>MÔ TẢ SẢN PHẨM</span></p><p style=\"text-align: left;\"><span>Chai xịt thơm miệng Fujisalt công nghệ tiên tiến 100% từ Nhật Bản.</span></p><p style=\"text-align: left;\"><span>- Khối lượng: 14ml/ 1 chai</span></p><p style=\"text-align: left;\"><span>- Thương Hiệu: Fujisalt</span></p><p style=\"text-align: left;\"><span>- Xuất xứ: Việt Nam</span></p><p style=\"text-align: left;\"><span>---------------------------------</span></p><p style=\"text-align: left;\"><span>- Không chỉ giúp khử mùi và mang lại hơi thở thơm mát ngay lập tức, sản phẩm này còn có thể loại bỏ đi cả mùi tỏi đặc biệt khó chịu. Đặc biệt, sản phẩm không chứa đường và không gây sâu răng giúp bảo vệ sức khỏe răng miệng của bạn mỗi ngày một cách tốt nhất</span></p><p style=\"text-align: left;\"><span>- Với thiết kế nhỏ gọn và nhẹ nhàng bạn có thể dễ dàng mang theo sản phẩm này bất kỳ chỗ nào, bất kỳ nơi đâu.</span></p><p style=\"text-align: left;\"><span>- Mỗi chai cung cấp sự tiện ích vượt trội có thể sử dụng lên đến 250 lần giúp tiết kiệm chi phí và thời gian cho bạn.</span></p><p style=\"text-align: left;\"><span><br></span></p><p style=\"text-align: left;\"><span>ĐỐI TƯỢNG SỬ DỤNG</span></p><p style=\"text-align: left;\"><span>- Dùng cho mọi đối tượng, người lớn và trẻ em từ 3 tuổi trở lên.</span></p><p style=\"text-align: left;\"><span>- Người cần vệ sinh răng miệng, người bị viêm họng hoặc các vấn đề về răng miệng.</span></p><p style=\"text-align: left;\"><span><br></span></p><p style=\"text-align: left;\"><span>HƯỚNG DẪN SỬ DỤNG</span></p><p style=\"text-align: left;\"><span>- Dựng thẳng chai và phun trực tiếp vào miệng.</span></p><p style=\"text-align: left;\"><span>- Sử dụng từ 3 đến 5 lần mỗi ngày.</span></p><p style=\"text-align: left;\"><span>---------------------------------</span></p><p style=\"text-align: left;\"><span>CÁCH BẢO QUẢN ĐÚNG CÁCH</span></p><p style=\"text-align: left;\"><span>- Bảo quản trong môi trường khô ráo, sạch sẽ, không bị nhiễm bụi và tránh xa nguồn nhiệt.</span></p><p style=\"text-align: left;\"><span>- Tránh va đập và không để sản phẩm tiếp xúc với hóa chất độc hại hoặc chất nặng có thể gây hỏng hoặc vỡ.</span></p><p style=\"text-align: left;\"><span>- Bảo quản ở nhiệt độ phòng.</span></p><p style=\"text-align: left;\"><span>- Tránh ánh nắng mặt trời trực tiếp.</span></p><p style=\"text-align: left;\"><span><br></span></p><p style=\"text-align: left;\"><span>14ml/ 1 chai</span></p><p style=\"text-align: left;\"><span>- Xuất xứ: Việt Nam</span></p>","has_draft":false,"id":"1734952395144267383","is_cod_allowed":true,"is_not_for_sale":false,"is_pre_owned":false,"is_replicated":false,"main_images":[{"height":1200,"thumb_urls":["https://p16-oec-sg.ibyteimg.com/tos-alisg-i-aphluv4xwc-sg/c85e41d2a1af49d4b42e011677e05aa0~tplv-aphluv4xwc-resize-jpeg:300:300.jpeg?dr=15584&from=520841845&idc=my&ps=933b5bde&shcp=2c1af732&shp=1f0b6a75&t=555f072d","https://p19-oec-sg.ibyteimg.com/tos-alisg-i-aphluv4xwc-sg/c85e41d2a1af49d4b42e011677e05aa0~tplv-aphluv4xwc-resize-jpeg:300:300.jpeg?dr=15584&from=520841845&idc=my&ps=933b5bde&shcp=2c1af732&shp=1f0b6a75&t=555f072d"],"uri":"tos-alisg-i-aphluv4xwc-sg/c85e41d2a1af49d4b42e011677e05aa0","urls":["https://p16-oec-sg.ibyteimg.com/tos-alisg-i-aphluv4xwc-sg/c85e41d2a1af49d4b42e011677e05aa0~tplv-aphluv4xwc-origin-jpeg.jpeg?dr=15568&from=520841845&idc=my&ps=933b5bde&shcp=2c1af732&shp=1f0b6a75&t=555f072d","https://p19-oec-sg.ibyteimg.com/tos-alisg-i-aphluv4xwc-sg/c85e41d2a1af49d4b42e011677e05aa0~tplv-aphluv4xwc-origin-jpeg.jpeg?dr=15568&from=520841845&idc=my&ps=933b5bde&shcp=2c1af732&shp=1f0b6a75&t=555f072d"],"width":1200},{"height":1024,"thumb_urls":["https://p16-oec-sg.ibyteimg.com/tos-alisg-i-aphluv4xwc-sg/699c8cea479d42e19918d2d6c5edfd08~tplv-aphluv4xwc-resize-jpeg:300:300.jpeg?dr=15584&from=520841845&idc=my&ps=933b5bde&shcp=2c1af732&shp=1f0b6a75&t=555f072d","https://p19-oec-sg.ibyteimg.com/tos-alisg-i-aphluv4xwc-sg/699c8cea479d42e19918d2d6c5edfd08~tplv-aphluv4xwc-resize-jpeg:300:300.jpeg?dr=15584&from=520841845&idc=my&ps=933b5bde&shcp=2c1af732&shp=1f0b6a75&t=555f072d"],"uri":"tos-alisg-i-aphluv4xwc-sg/699c8cea479d42e19918d2d6c5edfd08","urls":["https://p16-oec-sg.ibyteimg.com/tos-alisg-i-aphluv4xwc-sg/699c8cea479d42e19918d2d6c5edfd08~tplv-aphluv4xwc-origin-jpeg.jpeg?dr=15568&from=520841845&idc=my&ps=933b5bde&shcp=2c1af732&shp=1f0b6a75&t=555f072d","https://p19-oec-sg.ibyteimg.com/tos-alisg-i-aphluv4xwc-sg/699c8cea479d42e19918d2d6c5edfd08~tplv-aphluv4xwc-origin-jpeg.jpeg?dr=15568&from=520841845&idc=my&ps=933b5bde&shcp=2c1af732&shp=1f0b6a75&t=555f072d"],"width":1024},{"height":1200,"thumb_urls":["https://p16-oec-sg.ibyteimg.com/tos-alisg-i-aphluv4xwc-sg/5377fbf0513244bf9f712fde61f4f9e2~tplv-aphluv4xwc-resize-jpeg:300:300.jpeg?dr=15584&from=520841845&idc=my&ps=933b5bde&shcp=2c1af732&shp=1f0b6a75&t=555f072d","https://p19-oec-sg.ibyteimg.com/tos-alisg-i-aphluv4xwc-sg/5377fbf0513244bf9f712fde61f4f9e2~tplv-aphluv4xwc-resize-jpeg:300:300.jpeg?dr=15584&from=520841845&idc=my&ps=933b5bde&shcp=2c1af732&shp=1f0b6a75&t=555f072d"],"uri":"tos-alisg-i-aphluv4xwc-sg/5377fbf0513244bf9f712fde61f4f9e2","urls":["https://p16-oec-sg.ibyteimg.com/tos-alisg-i-aphluv4xwc-sg/5377fbf0513244bf9f712fde61f4f9e2~tplv-aphluv4xwc-origin-jpeg.jpeg?dr=15568&from=520841845&idc=my&ps=933b5bde&shcp=2c1af732&shp=1f0b6a75&t=555f072d","https://p19-oec-sg.ibyteimg.com/tos-alisg-i-aphluv4xwc-sg/5377fbf0513244bf9f712fde61f4f9e2~tplv-aphluv4xwc-origin-jpeg.jpeg?dr=15568&from=520841845&idc=my&ps=933b5bde&shcp=2c1af732&shp=1f0b6a75&t=555f072d"],"width":1200},{"height":1200,"thumb_urls":["https://p16-oec-sg.ibyteimg.com/tos-alisg-i-aphluv4xwc-sg/38fdee004d3f4b318d6171eff0408a91~tplv-aphluv4xwc-resize-jpeg:300:300.jpeg?dr=15584&from=520841845&idc=my&ps=933b5bde&shcp=2c1af732&shp=1f0b6a75&t=555f072d","https://p19-oec-sg.ibyteimg.com/tos-alisg-i-aphluv4xwc-sg/38fdee004d3f4b318d6171eff0408a91~tplv-aphluv4xwc-resize-jpeg:300:300.jpeg?dr=15584&from=520841845&idc=my&ps=933b5bde&shcp=2c1af732&shp=1f0b6a75&t=555f072d"],"uri":"tos-alisg-i-aphluv4xwc-sg/38fdee004d3f4b318d6171eff0408a91","urls":["https://p16-oec-sg.ibyteimg.com/tos-alisg-i-aphluv4xwc-sg/38fdee004d3f4b318d6171eff0408a91~tplv-aphluv4xwc-origin-jpeg.jpeg?dr=15568&from=520841845&idc=my&ps=933b5bde&shcp=2c1af732&shp=1f0b6a75&t=555f072d","https://p19-oec-sg.ibyteimg.com/tos-alisg-i-aphluv4xwc-sg/38fdee004d3f4b318d6171eff0408a91~tplv-aphluv4xwc-origin-jpeg.jpeg?dr=15568&from=520841845&idc=my&ps=933b5bde&shcp=2c1af732&shp=1f0b6a75&t=555f072d"],"width":1200},{"height":1200,"thumb_urls":["https://p16-oec-sg.ibyteimg.com/tos-alisg-i-aphluv4xwc-sg/79a64d9ca60140b9a139031dd9119be5~tplv-aphluv4xwc-resize-jpeg:300:300.jpeg?dr=15584&from=520841845&idc=my&ps=933b5bde&shcp=2c1af732&shp=1f0b6a75&t=555f072d","https://p19-oec-sg.ibyteimg.com/tos-alisg-i-aphluv4xwc-sg/79a64d9ca60140b9a139031dd9119be5~tplv-aphluv4xwc-resize-jpeg:300:300.jpeg?dr=15584&from=520841845&idc=my&ps=933b5bde&shcp=2c1af732&shp=1f0b6a75&t=555f072d"],"uri":"tos-alisg-i-aphluv4xwc-sg/79a64d9ca60140b9a139031dd9119be5","urls":["https://p16-oec-sg.ibyteimg.com/tos-alisg-i-aphluv4xwc-sg/79a64d9ca60140b9a139031dd9119be5~tplv-aphluv4xwc-origin-jpeg.jpeg?dr=15568&from=520841845&idc=my&ps=933b5bde&shcp=2c1af732&shp=1f0b6a75&t=555f072d","https://p19-oec-sg.ibyteimg.com/tos-alisg-i-aphluv4xwc-sg/79a64d9ca60140b9a139031dd9119be5~tplv-aphluv4xwc-origin-jpeg.jpeg?dr=15568&from=520841845&idc=my&ps=933b5bde&shcp=2c1af732&shp=1f0b6a75&t=555f072d"],"width":1200}],"manufacturer_ids":[],"package_dimensions":{"height":"10","length":"2","unit":"CENTIMETER","width":"2"},"package_weight":{"unit":"KILOGRAM","value":"0.2"},"product_attributes":[{"id":"102872","name":"Loại giấy phép đăng kí sản phẩm","values":[{"id":"1298954","name":"Giấy tiếp nhận đăng ký bản công bố sản phẩm"}]},{"id":"102999","name":"Số đăng kí","values":[{"id":"7621141332983121684","name":"240000161/PCBA-HCM"}]},{"id":"103000","name":"Ngày cấp","values":[{"id":"7188885906408605445","name":"22/01/2024"}]},{"id":"103001","name":"Nơi cấp","values":[{"id":"7130916683098916614","name":"Thành phố Hồ Chí Minh"}]},{"id":"100149","name":"Quốc gia xuất xứ","values":[{"id":"1000854","name":"Việt Nam"}]},{"id":"101489","name":"Tên tổ chức chịu trách nhiệm hàng hóa","values":[{"id":"7404781769532278534","name":"Fujiwa"}]},{"id":"101490","name":"Địa chỉ tổ chức chịu trách nhiệm hàng hóa","values":[{"id":"7404781769532278534","name":"Fujiwa"}]}],"product_status":"ACTIVATE","product_tags":[],"recommended_categories":[],"responsible_person_ids":[],"shipping_insurance_requirement":"NOT_SUPPORTED","skus":[{"global_listing_policy":{"inventory_type":"EXCLUSIVE","price_sync":false},"id":"1734952449674217079","inventory":[{"quantity":43,"warehouse_id":"7272949914115966726"}],"price":{"currency":"VND","sale_price":"72000","tax_exclusive_price":"72000"},"sales_attributes":[],"seller_sku":"XTM-C","sku_dimensions":{"height":"10","length":"2","unit":"CENTIMETER","width":"2"},"sku_weight":{"unit":"KILOGRAM","value":"0.2"},"status_info":{"status":"NORMAL"}}],"status":"ACTIVATE","subscribe_info":{"subscribe_promotion_config":[{"discount_level":"REGULAR"},{"discount_level":"FIRST_ORDER","max_discount":99,"min_discount":1}],"subscribe_status":"NOT_ENABLED","support_subscribe":false},"title":"[Quà Tặng] Chai Xịt Thơm Miệng Fujisalt 14mL Khử Mùi Hiệu Quả, Giữ Hơi Thở Thơm Mát","update_time":1782892330},"message":"Success","request_id":"20260706103727583215B8DA0B60A2EA68"}

**Sanitized response body (optional)**

```json

```

---

### 6. Get Order List (New)

| Field | Expected | Verified |
|-------|----------|----------|
| Version | `202309` | |
| Method / path | `POST /order/202309/orders/search` | |
| Optional body | `order_status`, `update_time_ge`, `update_time_lt` | |
| Optional query | `page_size`, `page_token` | |

**Request Demo cURL**

```bash
curl -k -X 'POST' -d '{}' -H 'Content-Type: application/json' -H 'x-tts-access-token: ROW_9A2D_gAAAABbUg_84te3E8INEevR-bbuEOnDJM8WtbRPbpEwfsb5vN-A3kch8o1Z75o0SKWI1WMZNro6FFwXDAoubTUFWba-wu0a6b8xw8B7Q6Fc1f97S1sAFq4mI6QebiXx05mg_cJbx-b8V2Pbxwjylm_S4HwMzrK-wmUhl-pdudAys_OUQHHd5Qfbz-ITIJuoXrj1Q0k' 'https://open-api.tiktokglobalshop.com/order/202309/orders/search?access_token=ROW_9A2D_gAAAABbUg_84te3E8INEevR-bbuEOnDJM8WtbRPbpEwfsb5vN-A3kch8o1Z75o0SKWI1WMZNro6FFwXDAoubTUFWba-wu0a6b8xw8B7Q6Fc1f97S1sAFq4mI6QebiXx05mg_cJbx-b8V2Pbxwjylm_S4HwMzrK-wmUhl-pdudAys_OUQHHd5Qfbz-ITIJuoXrj1Q0k&app_key=6kdu4f07vvlv9&page_size=1&shop_cipher=ROW_aiVo7gAAAAB2vvlFyfTxbVr4ZFHoDbhK&shop_id=&sign=5f2d32e62f811f63b75792e2f5bc34623e3e5083dddf76880f2c6eb2a89ad2c6&timestamp=1783305644&version=202309'
```

**Response**

{"code":0,"data":{"next_page_token":"aDV5MXBtU1pha2hPU0dGSTh5Nkliamc1RFlncjR5eE5OUXh0YVFaMFlzRWtwZz09","orders":[{"buyer_email":"v4bGVXWORK4Z6F5ANJPUGM7BB352Y@scs2.tiktok.com","buyer_message":"","cancel_order_sla_time":1696438799,"cancel_reason":"Không thể giao hàng đến địa chỉ khách hàng","cancel_time":1696306119,"cancellation_initiator":"SELLER","commerce_platform":"TIKTOK_SHOP","create_time":1695873653,"delivery_option_id":"7057025213938009858","delivery_option_name":"Standard shipping","delivery_type":"HOME_DELIVERY","fulfillment_type":"FULFILLMENT_BY_SELLER","has_updated_recipient_address":false,"id":"577958834469439754","is_cod":true,"is_on_hold_order":false,"is_replacement_order":false,"is_sample_order":false,"line_items":[{"cancel_reason":"Không thể giao hàng đến địa chỉ khách hàng","cancel_user":"SELLER","currency":"VND","display_status":"CANCELLED","gift_retail_price":"0","id":"577958834469570826","is_gift":false,"original_price":"168000","package_id":"1153486604836964618","package_status":"CANCELLED","platform_discount":"0","product_id":"1729700293904403063","product_name":"Nước Uống Ion Kiềm Cao Cấp Đóng Chai Fujiwa Vietnam","rts_time":1695969425,"sale_price":"168000","seller_discount":"0","seller_sku":"FUJIWA02-450","shipping_provider_id":"7099654067386844933","shipping_provider_name":"GHTK","sku_id":"1729700293904534135","sku_image":"https://p16-oec-va.ibyteimg.com/tos-maliva-i-o3syd03w52-us/cd87288197f84f3192c50fa57cfe98de~tplv-o3syd03w52-origin-jpeg.jpeg?dr=15568&t=555f072d&ps=933b5bde&shp=54477afb&shcp=3c3d9ffb&idc=my&from=1413970683","sku_name":"Thùng 24 Chai-450ml","sku_type":"NORMAL","tracking_number":"3220279504"},{"cancel_reason":"Không thể giao hàng đến địa chỉ khách hàng","cancel_user":"SELLER","currency":"VND","display_status":"CANCELLED","gift_retail_price":"0","id":"577958834469636362","is_gift":false,"original_price":"168000","package_id":"1153486604836964618","package_status":"CANCELLED","platform_discount":"0","product_id":"1729700293904403063","product_name":"Nước Uống Ion Kiềm Cao Cấp Đóng Chai Fujiwa Vietnam","rts_time":1695969425,"sale_price":"168000","seller_discount":"0","seller_sku":"FUJIWA02-450","shipping_provider_id":"7099654067386844933","shipping_provider_name":"GHTK","sku_id":"1729700293904534135","sku_image":"https://p16-oec-va.ibyteimg.com/tos-maliva-i-o3syd03w52-us/cd87288197f84f3192c50fa57cfe98de~tplv-o3syd03w52-origin-jpeg.jpeg?dr=15568&t=555f072d&ps=933b5bde&shp=54477afb&shcp=3c3d9ffb&idc=my&from=1413970683","sku_name":"Thùng 24 Chai-450ml","sku_type":"NORMAL","tracking_number":"3220279504"},{"cancel_reason":"Không thể giao hàng đến địa chỉ khách hàng","cancel_user":"SELLER","currency":"VND","display_status":"CANCELLED","gift_retail_price":"0","id":"577958834469701898","is_gift":false,"original_price":"168000","package_id":"1153486604836964618","package_status":"CANCELLED","platform_discount":"0","product_id":"1729700293904403063","product_name":"Nước Uống Ion Kiềm Cao Cấp Đóng Chai Fujiwa Vietnam","rts_time":1695969425,"sale_price":"168000","seller_discount":"0","seller_sku":"FUJIWA02-450","shipping_provider_id":"7099654067386844933","shipping_provider_name":"GHTK","sku_id":"1729700293904534135","sku_image":"https://p16-oec-va.ibyteimg.com/tos-maliva-i-o3syd03w52-us/cd87288197f84f3192c50fa57cfe98de~tplv-o3syd03w52-origin-jpeg.jpeg?dr=15568&t=555f072d&ps=933b5bde&shp=54477afb&shcp=3c3d9ffb&idc=my&from=1413970683","sku_name":"Thùng 24 Chai-450ml","sku_type":"NORMAL","tracking_number":"3220279504"}],"order_type":"NORMAL","packages":[{"id":"1153486604836964618"}],"payment":{"currency":"VND","original_shipping_fee":"153000","original_total_product_price":"504000","platform_discount":"0","seller_discount":"0","shipping_fee":"153000","shipping_fee_cofunded_discount":"0","shipping_fee_platform_discount":"0","shipping_fee_seller_discount":"0","sub_total":"504000","tax":"0","total_amount":"657000"},"payment_method_name":"Cash on delivery","recipient_address":{"address_detail":"","address_line1":"","address_line2":"","address_line3":"","address_line4":"","delivery_preferences":{"drop_off_location":""},"first_name":"","full_address":"","last_name":"","name":"","phone_number":"","postal_code":"","region_code":""},"rts_sla_time":1696006799,"rts_time":1695969425,"shipping_provider":"GHTK","shipping_provider_id":"7099654067386844933","shipping_type":"TIKTOK","status":"CANCELLED","tracking_number":"3220279504","tts_sla_time":1696093199,"update_time":1696306119,"user_id":"7494037984113493258","warehouse_id":"7272949914115966726"}],"total_count":17472},"message":"Success","request_id":"202607061040437EAC551111B625627AC8"}

**Sanitized response body (optional)**

```json

```

---

### 7. Get Order Detail

| Field | Expected | Verified |
|-------|----------|----------|
| Version | `202507` | |
| Method / path | `GET /order/202507/orders` | |
| Required query | `ids` (comma-separated order IDs) | |
| Order IDs used | | |

**Request Demo cURL**

```bash
curl -k -X 'GET' -H 'x-tts-access-token: ROW_9A2D_gAAAABbUg_84te3E8INEevR-bbuEOnDJM8WtbRPbpEwfsb5vN-A3kch8o1Z75o0SKWI1WMZNro6FFwXDAoubTUFWba-wu0a6b8xw8B7Q6Fc1f97S1sAFq4mI6QebiXx05mg_cJbx-b8V2Pbxwjylm_S4HwMzrK-wmUhl-pdudAys_OUQHHd5Qfbz-ITIJuoXrj1Q0k' 'https://open-api.tiktokglobalshop.com/order/202507/orders?access_token=ROW_9A2D_gAAAABbUg_84te3E8INEevR-bbuEOnDJM8WtbRPbpEwfsb5vN-A3kch8o1Z75o0SKWI1WMZNro6FFwXDAoubTUFWba-wu0a6b8xw8B7Q6Fc1f97S1sAFq4mI6QebiXx05mg_cJbx-b8V2Pbxwjylm_S4HwMzrK-wmUhl-pdudAys_OUQHHd5Qfbz-ITIJuoXrj1Q0k&app_key=6kdu4f07vvlv9&ids=577958834469439754&shop_cipher=ROW_aiVo7gAAAAB2vvlFyfTxbVr4ZFHoDbhK&shop_id=&sign=e438e6df76877d4bd2c433070a4afa1101b2bd6271c23dd710a85335406f2657&timestamp=1783305819&version=202507'
```

**Response**

{"code":0,"data":{"orders":[{"buyer_email":"v4bGVXWORK4Z6F5ANJPUGM7BB352Y@scs2.tiktok.com","buyer_message":"","cancel_order_sla_time":1696438799,"cancel_reason":"Không thể giao hàng đến địa chỉ khách hàng","cancel_time":1696306119,"cancellation_initiator":"SELLER","commerce_platform":"TIKTOK_SHOP","create_time":1695873653,"delivery_option_id":"7057025213938009858","delivery_option_name":"Standard shipping","delivery_type":"HOME_DELIVERY","fulfillment_type":"FULFILLMENT_BY_SELLER","has_updated_recipient_address":false,"id":"577958834469439754","is_cod":true,"is_on_hold_order":false,"is_replacement_order":false,"is_sample_order":false,"line_items":[{"cancel_reason":"Không thể giao hàng đến địa chỉ khách hàng","cancel_user":"SELLER","currency":"VND","display_status":"CANCELLED","gift_retail_price":"0","id":"577958834469570826","is_gift":false,"original_price":"168000","package_id":"1153486604836964618","package_status":"CANCELLED","platform_discount":"0","product_id":"1729700293904403063","product_name":"Nước Uống Ion Kiềm Cao Cấp Đóng Chai Fujiwa Vietnam","rts_time":1695969425,"sale_price":"168000","seller_discount":"0","seller_sku":"FUJIWA02-450","shipping_provider_id":"7099654067386844933","shipping_provider_name":"GHTK","sku_id":"1729700293904534135","sku_image":"https://p19-oec-general.tiktokcdn.com/tos-maliva-i-o3syd03w52-us/cd87288197f84f3192c50fa57cfe98de~tplv-o3syd03w52-origin-jpeg.jpeg?dr=15568&t=555f072d&ps=933b5bde&shp=54477afb&shcp=3c3d9ffb&idc=my&from=1413970683","sku_name":"Thùng 24 Chai-450ml","sku_type":"NORMAL","tracking_number":"3220279504"},{"cancel_reason":"Không thể giao hàng đến địa chỉ khách hàng","cancel_user":"SELLER","currency":"VND","display_status":"CANCELLED","gift_retail_price":"0","id":"577958834469636362","is_gift":false,"original_price":"168000","package_id":"1153486604836964618","package_status":"CANCELLED","platform_discount":"0","product_id":"1729700293904403063","product_name":"Nước Uống Ion Kiềm Cao Cấp Đóng Chai Fujiwa Vietnam","rts_time":1695969425,"sale_price":"168000","seller_discount":"0","seller_sku":"FUJIWA02-450","shipping_provider_id":"7099654067386844933","shipping_provider_name":"GHTK","sku_id":"1729700293904534135","sku_image":"https://p16-oec-general.tiktokcdn.com/tos-maliva-i-o3syd03w52-us/cd87288197f84f3192c50fa57cfe98de~tplv-o3syd03w52-origin-jpeg.jpeg?dr=15568&t=555f072d&ps=933b5bde&shp=54477afb&shcp=3c3d9ffb&idc=my&from=1413970683","sku_name":"Thùng 24 Chai-450ml","sku_type":"NORMAL","tracking_number":"3220279504"},{"cancel_reason":"Không thể giao hàng đến địa chỉ khách hàng","cancel_user":"SELLER","currency":"VND","display_status":"CANCELLED","gift_retail_price":"0","id":"577958834469701898","is_gift":false,"original_price":"168000","package_id":"1153486604836964618","package_status":"CANCELLED","platform_discount":"0","product_id":"1729700293904403063","product_name":"Nước Uống Ion Kiềm Cao Cấp Đóng Chai Fujiwa Vietnam","rts_time":1695969425,"sale_price":"168000","seller_discount":"0","seller_sku":"FUJIWA02-450","shipping_provider_id":"7099654067386844933","shipping_provider_name":"GHTK","sku_id":"1729700293904534135","sku_image":"https://p16-oec-general.tiktokcdn.com/tos-maliva-i-o3syd03w52-us/cd87288197f84f3192c50fa57cfe98de~tplv-o3syd03w52-origin-jpeg.jpeg?dr=15568&t=555f072d&ps=933b5bde&shp=54477afb&shcp=3c3d9ffb&idc=my&from=1413970683","sku_name":"Thùng 24 Chai-450ml","sku_type":"NORMAL","tracking_number":"3220279504"}],"order_type":"NORMAL","packages":[{"id":"1153486604836964618"}],"payment":{"currency":"VND","original_shipping_fee":"153000","original_total_product_price":"504000","platform_discount":"0","seller_discount":"0","shipping_fee":"153000","shipping_fee_cofunded_discount":"0","shipping_fee_platform_discount":"0","shipping_fee_seller_discount":"0","sub_total":"504000","tax":"0","total_amount":"657000"},"payment_method_name":"Cash on delivery","recipient_address":{"address_detail":"","address_line1":"","address_line2":"","address_line3":"","address_line4":"","delivery_preferences":{"drop_off_location":""},"first_name":"","full_address":"","last_name":"","name":"","phone_number":"","postal_code":"","region_code":""},"rts_sla_time":1696006799,"rts_time":1695969425,"shipping_provider":"GHTK","shipping_provider_id":"7099654067386844933","shipping_type":"TIKTOK","status":"CANCELLED","tracking_number":"3220279504","tts_sla_time":1696093199,"update_time":1696306119,"user_id":"7494037984113493258","warehouse_id":"7272949914115966726"}]},"message":"Success","request_id":"202607061043390450F88540E0666624DD"}

**Sanitized response body (optional)**

```json

```

---

### 8. Search Returns

| Field | Expected | Verified |
|-------|----------|----------|
| Version | `202602` | |
| Method / path | `POST /return_refund/202602/returns/search` | |
| Optional body | `return_status`, `update_time_ge`, `update_time_lt` | |
| Optional query | `page_size`, `page_token` | |

**Request Demo cURL**

```bash
curl -k -X 'POST' -d '{}' -H 'Content-Type: application/json' -H 'x-tts-access-token: ROW_9A2D_gAAAABbUg_84te3E8INEevR-bbuEOnDJM8WtbRPbpEwfsb5vN-A3kch8o1Z75o0SKWI1WMZNro6FFwXDAoubTUFWba-wu0a6b8xw8B7Q6Fc1f97S1sAFq4mI6QebiXx05mg_cJbx-b8V2Pbxwjylm_S4HwMzrK-wmUhl-pdudAys_OUQHHd5Qfbz-ITIJuoXrj1Q0k' 'https://open-api.tiktokglobalshop.com/return_refund/202602/returns/search?access_token=ROW_9A2D_gAAAABbUg_84te3E8INEevR-bbuEOnDJM8WtbRPbpEwfsb5vN-A3kch8o1Z75o0SKWI1WMZNro6FFwXDAoubTUFWba-wu0a6b8xw8B7Q6Fc1f97S1sAFq4mI6QebiXx05mg_cJbx-b8V2Pbxwjylm_S4HwMzrK-wmUhl-pdudAys_OUQHHd5Qfbz-ITIJuoXrj1Q0k&app_key=6kdu4f07vvlv9&shop_cipher=ROW_aiVo7gAAAAB2vvlFyfTxbVr4ZFHoDbhK&shop_id=&sign=c3a43582f344bc7c8ebf17a4e73d0e075ce60849e7206ecfcf29bff8818861e9&timestamp=1783305860&version=202602'
```

**Response**

{"code":0,"data":{"next_page_token":"aDU2dHIzMlFha2hLU21aSzhpbVJZOEtCdW1kdFF3OHV4VE1IWkhMWTBEZGtlZmkvL0ZuYg==","return_orders":[{"combined_return_id":"0","create_time":1724558837,"discount_amount":[{"currency":"VND","product_platform_discount":"0","product_seller_discount":"288000","shipping_fee_platform_discount":"166100","shipping_fee_seller_discount":"0"}],"handover_method":"DROP_OFF","is_combined_return":false,"order_id":"579238058323577347","refund_amount":{"currency":"VND","refund_shipping_fee":"0","refund_subtotal":"864000","refund_tax":"0","refund_total":"864000"},"return_id":"4035463945335048707","return_line_items":[{"order_line_item_id":"579238050604288515","product_image":{"height":200,"url":"https://p16-oec-general.tiktokcdn.com/tos-maliva-i-o3syd03w52-us/da2d6906c6ed4f9f814f303bb1ef3cae~tplv-o3syd03w52-origin-jpeg.jpeg?dr=15568&from=4246405447&idc=my&ps=933b5bde&shcp=3c3d9ffb&shp=fd1b0147&t=555f072d","width":200},"product_name":"Thùng 24 Lon Nước Uống Giàu Hydrogen Cao Cấp Fujiwa Đóng Lon 330ml - Hỗ trợ tiêu hoá, Cải thiện đường ruột, Giải độc gan","refund_amount":{"currency":"VND","refund_shipping_fee":"0","refund_subtotal":"432000","refund_tax":"0","refund_total":"432000"},"return_line_item_id":"4035463945335114243","seller_sku":"FUJIWA04-24","sku_id":"1730420785344318071","sku_name":"Mặc định, Mặc định"},{"order_line_item_id":"579238050604222979","product_image":{"height":200,"url":"https://p16-oec-general.tiktokcdn.com/tos-maliva-i-o3syd03w52-us/da2d6906c6ed4f9f814f303bb1ef3cae~tplv-o3syd03w52-origin-jpeg.jpeg?dr=15568&from=4246405447&idc=my&ps=933b5bde&shcp=3c3d9ffb&shp=fd1b0147&t=555f072d","width":200},"product_name":"Thùng 24 Lon Nước Uống Giàu Hydrogen Cao Cấp Fujiwa Đóng Lon 330ml - Hỗ trợ tiêu hoá, Cải thiện đường ruột, Giải độc gan","refund_amount":{"currency":"VND","refund_shipping_fee":"0","refund_subtotal":"432000","refund_tax":"0","refund_total":"432000"},"return_line_item_id":"4035463945335179779","seller_sku":"FUJIWA04-24","sku_id":"1730420785344318071","sku_name":"Mặc định, Mặc định"}],"return_method":"PLATFORM_SHIPPED","return_provider_id":"6841743441349706241","return_provider_name":"J&T Express","return_reason":"ecom_order_delivered_refund_and_return_reason_damaged","return_reason_text":"Package or product is damaged","return_status":"RETURN_OR_REFUND_REQUEST_COMPLETE","return_tracking_number":"854205793213","return_type":"RETURN_AND_REFUND","return_warehouse_address":{"full_address":"121/32 Trung Mỹ Tây 13, Khu phố 4, Quận 12, Hồ Chí Minh, Việt Nam,,Trung My Tay,District 12,Ho Chi Minh,Vietnam"},"role":"BUYER","shipment_type":"PLATFORM","shipping_fee_amount":[{"buyer_paid_return_shipping_fee":"0","currency":"VND","platform_paid_return_shipping_fee":"0","seller_paid_return_shipping_fee":"166100"}],"update_time":1724833101},{"combined_return_id":"0","create_time":1726503478,"discount_amount":[{"currency":"VND","product_platform_discount":"35782","product_seller_discount":"79436","shipping_fee_platform_discount":"90000","shipping_fee_seller_discount":"0"}],"is_combined_return":false,"order_id":"579318273458211351","refund_amount":{"currency":"VND","refund_shipping_fee":"0","refund_subtotal":"173900","refund_tax":"0","refund_total":"173900"},"return_id":"4035473108649216535","return_line_items":[{"order_line_item_id":"579318273458342423","product_image":{"height":200,"url":"https://p16-oec-general.tiktokcdn.com/tos-maliva-i-o3syd03w52-us/6dd550627cac46bfbee398ffe54d2a5d~tplv-o3syd03w52-origin-jpeg.jpeg?dr=15568&from=4246405447&idc=my&ps=933b5bde&shcp=3c3d9ffb&shp=fd1b0147&t=555f072d","width":200},"product_name":"Fujiwa - Thùng 24 Chai 450ml Nước Uống Ion Kiềm Cao Cấp Đóng Chai - Nước uống Detox với Công Nghệ Điện Phân Ion Kiềm","refund_amount":{"currency":"VND","refund_shipping_fee":"0","refund_subtotal":"86950","refund_tax":"0","refund_total":"86950"},"return_line_item_id":"4035473108649282071","seller_sku":"FUJIWA02-450","sku_id":"1730420770070956663","sku_name":"Mặc định, Mặc định"},{"order_line_item_id":"579318273458407959","product_image":{"height":200,"url":"https://p16-oec-general.tiktokcdn.com/tos-maliva-i-o3syd03w52-us/6dd550627cac46bfbee398ffe54d2a5d~tplv-o3syd03w52-origin-jpeg.jpeg?dr=15568&from=4246405447&idc=my&ps=933b5bde&shcp=3c3d9ffb&shp=fd1b0147&t=555f072d","width":200},"product_name":"Fujiwa - Thùng 24 Chai 450ml Nước Uống Ion Kiềm Cao Cấp Đóng Chai - Nước uống Detox với Công Nghệ Điện Phân Ion Kiềm","refund_amount":{"currency":"VND","refund_shipping_fee":"0","refund_subtotal":"86950","refund_tax":"0","refund_total":"86950"},"return_line_item_id":"4035473108649347607","seller_sku":"FUJIWA02-450","sku_id":"1730420770070956663","sku_name":"Mặc định, Mặc định"}],"return_reason":"ecom_order_delivered_refund_reason_missing_product","return_reason_text":"Received parcel, but some items were missing","return_status":"RETURN_OR_REFUND_REQUEST_COMPLETE","return_type":"REFUND","role":"BUYER","shipping_fee_amount":[{"buyer_paid_return_shipping_fee":"0","currency":"VND","platform_paid_return_shipping_fee":"0","seller_paid_return_shipping_fee":"0"}],"update_time":1726639570},{"combined_return_id":"0","create_time":1728663600,"discount_amount":[{"currency":"VND","product_platform_discount":"16100","product_seller_discount":"144900","shipping_fee_platform_discount":"0","shipping_fee_seller_discount":"0"}],"is_combined_return":false,"order_id":"579455212076239383","refund_amount":{"currency":"VND","refund_shipping_fee":"39500","refund_subtotal":"175000","refund_tax":"0","refund_total":"214500"},"return_id":"4035487117141117463","return_line_items":[{"order_line_item_id":"579455212076370455","product_image":{"height":200,"url":"https://p16-oec-general.tiktokcdn.com/tos-maliva-i-o3syd03w52-us/56696854001944bb8d5fe904d615ee58~tplv-o3syd03w52-origin-jpeg.jpeg?dr=15568&from=4246405447&idc=my&ps=933b5bde&shcp=3c3d9ffb&shp=fd1b0147&t=555f072d","width":200},"product_name":"Thùng 2 Bình 6 Lít Nước Uống Ion Kiềm Cao Cấp Fujiwa Dạng Bình 6L Xách Tay Tiện Lợi đi du lịch, dã ngoại","refund_amount":{"currency":"VND","refund_shipping_fee":"19750","refund_subtotal":"87500","refund_tax":"0","refund_total":"107250"},"return_line_item_id":"4035487117141182999","seller_sku":"FUJIWA07-6L2","sku_id":"1730420787059722871","sku_name":"Mặc định, Mặc định"},{"order_line_item_id":"579455212076435991","product_image":{"height":200,"url":"https://p16-oec-general.tiktokcdn.com/tos-maliva-i-o3syd03w52-us/56696854001944bb8d5fe904d615ee58~tplv-o3syd03w52-origin-jpeg.jpeg?dr=15568&from=4246405447&idc=my&ps=933b5bde&shcp=3c3d9ffb&shp=fd1b0147&t=555f072d","width":200},"product_name":"Thùng 2 Bình 6 Lít Nước Uống Ion Kiềm Cao Cấp Fujiwa Dạng Bình 6L Xách Tay Tiện Lợi đi du lịch, dã ngoại","refund_amount":{"currency":"VND","refund_shipping_fee":"19750","refund_subtotal":"87500","refund_tax":"0","refund_total":"107250"},"return_line_item_id":"4035487117141248535","seller_sku":"FUJIWA07-6L2","sku_id":"1730420787059722871","sku_name":"Mặc định, Mặc định"}],"return_reason":"ecom_order_delivered_refund_reason_not_received","return_reason_text":"Did not receive parcel","return_status":"RETURN_OR_REFUND_REQUEST_CANCEL","return_type":"REFUND","role":"OPERATOR","shipping_fee_amount":[{"buyer_paid_return_shipping_fee":"0","currency":"VND","platform_paid_return_shipping_fee":"0","seller_paid_return_shipping_fee":"0"}],"update_time":1728701481},{"combined_return_id":"0","create_time":1729478487,"discount_amount":[{"currency":"VND","product_platform_discount":"0","product_seller_discount":"59000","shipping_fee_platform_discount":"15800","shipping_fee_seller_discount":"0"}],"is_combined_return":false,"order_id":"579500271985003338","refund_amount":{"currency":"VND","refund_shipping_fee":"0","refund_subtotal":"61000","refund_tax":"0","refund_total":"61000"},"return_id":"4035492900113582922","return_line_items":[{"order_line_item_id":"579500271985134410","product_image":{"height":200,"url":"https://p16-oec-general.tiktokcdn.com/tos-maliva-i-o3syd03w52-us/c0eb7662c7ec4775808bfa7f79b16a80~tplv-o3syd03w52-origin-jpeg.jpeg?dr=15568&from=4246405447&idc=my&ps=933b5bde&shcp=3c3d9ffb&shp=fd1b0147&t=555f072d","width":200},"product_name":"QUÀ TẶNG - 1 Túi Nước Uống Ion Kiềm Giàu Hydrogen Cao Cấp Fujiwa Dạng Túi Bạc 270ml","refund_amount":{"currency":"VND","refund_shipping_fee":"0","refund_subtotal":"61000","refund_tax":"0","refund_total":"61000"},"return_line_item_id":"4035492900113648458","seller_sku":"FUJIWA05-2","sku_id":"1730983199709039223","sku_name":"Mặc định, Mặc định"}],"return_reason":"ecom_order_to_ship_canceled_reason_created_by_mistakes_RTS_RO","return_reason_text":"No longer needed","return_status":"RETURN_OR_REFUND_REQUEST_CANCEL","return_type":"REFUND","role":"BUYER","shipping_fee_amount":[{"buyer_paid_return_shipping_fee":"0","currency":"VND","platform_paid_return_shipping_fee":"0","seller_paid_return_shipping_fee":"0"}],"update_time":1730090672},{"combined_return_id":"0","create_time":1730634194,"discount_amount":[{"currency":"VND","product_platform_discount":"0","product_seller_discount":"58800","shipping_fee_platform_discount":"100000","shipping_fee_seller_discount":"0"}],"handover_method":"PICKUP","is_combined_return":false,"is_quick_refund":true,"order_id":"579557561832868731","refund_amount":{"currency":"VND","refund_shipping_fee":"26600","refund_subtotal":"114000","refund_tax":"0","refund_total":"140600"},"return_id":"4035501470040361851","return_line_items":[{"order_line_item_id":"579557561832999803","product_image":{"height":200,"url":"https://p16-oec-general.tiktokcdn.com/tos-maliva-i-o3syd03w52-us/70da5b8668a1412d8bed916bd6448937~tplv-o3syd03w52-origin-jpeg.jpeg?dr=15568&from=4246405447&idc=my&ps=933b5bde&shcp=3c3d9ffb&shp=fd1b0147&t=555f072d","width":200},"product_name":"Thùng 24 Chai 300ml Nước Uống Ion Kiềm Cao Cấp Đóng Chai Fujiwa - Nước uống Detox với Công Nghệ Điện Phân Ion Kiềm Không Đường","refund_amount":{"currency":"VND","refund_shipping_fee":"26600","refund_subtotal":"114000","refund_tax":"0","refund_total":"140600"},"return_line_item_id":"4035501470040427387","seller_sku":"FUJIWA02-300","sku_id":"1730420771165538935","sku_name":"Mặc định, Mặc định"}],"return_method":"PLATFORM_SHIPPED","return_provider_id":"6841743441349706241","return_provider_name":"J&T Express","return_reason":"ecom_order_delivered_refund_and_return_reason_not_match_description","return_reason_text":"Product doesn't match description","return_status":"RETURN_OR_REFUND_REQUEST_COMPLETE","return_tracking_number":"854201439919","return_type":"RETURN_AND_REFUND","return_warehouse_address":{"full_address":"121/32 Trung Mỹ Tây 13, Khu phố 4, Quận 12, Hồ Chí Minh, Việt Nam,,Trung My Tay,District 12,Ho Chi Minh,Vietnam"},"role":"BUYER","shipment_type":"PLATFORM","shipping_fee_amount":[{"buyer_paid_return_shipping_fee":"0","currency":"VND","platform_paid_return_shipping_fee":"0","seller_paid_return_shipping_fee":"126600"}],"update_time":1731120946},{"combined_return_id":"0","create_time":1731408279,"discount_amount":[{"currency":"VND","product_platform_discount":"139900","product_seller_discount":"761000","shipping_fee_platform_discount":"102737","shipping_fee_seller_discount":"0"}],"is_combined_return":false,"next_return_id":"4035508318941448659","order_id":"579615191908583891","refund_amount":{"currency":"VND","refund_shipping_fee":"0","refund_subtotal":"1259100","refund_tax":"0","refund_total":"1259100"},"return_id":"4035508291033729491","return_line_items":[{"order_line_item_id":"579615191908714963","product_image":{"height":200,"url":"https://p16-oec-general.tiktokcdn.com/tos-maliva-i-o3syd03w52-us/475995d3b39f45b8906f3a458ad251f4~tplv-o3syd03w52-origin-jpeg.jpeg?dr=15568&from=4246405447&idc=my&ps=933b5bde&shcp=3c3d9ffb&shp=fd1b0147&t=555f072d","width":200},"product_name":"Thùng 48 Túi Nước Uống Ion Kiềm Giàu Hydrogen Cao Cấp Fujiwa pH9 Dạng Túi Bạc 270ml Chống oxy hoá, Trung hoà gốc tự do không Đường","refund_amount":{"currency":"VND","refund_shipping_fee":"0","refund_subtotal":"1259100","refund_tax":"0","refund_total":"1259100"},"return_line_item_id":"4035508291033795027","seller_sku":"FUJIWA05-40","sku_id":"1730420769435257463","sku_name":"Mặc định, Mặc định"}],"return_reason":"ecom_order_delivered_refund_reason_missing_product","return_reason_text":"Received parcel, but some items were missing","return_status":"RETURN_OR_REFUND_REQUEST_CANCEL","return_type":"REFUND","role":"BUYER","shipping_fee_amount":[{"buyer_paid_return_shipping_fee":"0","currency":"VND","platform_paid_return_shipping_fee":"0","seller_paid_return_shipping_fee":"0"}],"update_time":1731411155},{"combined_return_id":"0","create_time":1731411155,"discount_amount":[{"currency":"VND","product_platform_discount":"139900","product_seller_discount":"761000","shipping_fee_platform_discount":"102737","shipping_fee_seller_discount":"0"}],"handover_method":"PICKUP","is_combined_return":false,"order_id":"579615191908583891","pre_return_id":"4035508291033729491","refund_amount":{"currency":"VND","refund_shipping_fee":"0","refund_subtotal":"1259100","refund_tax":"0","refund_total":"1259100"},"return_id":"4035508318941448659","return_line_items":[{"order_line_item_id":"579615191908714963","product_image":{"height":200,"url":"https://p19-oec-general.tiktokcdn.com/tos-maliva-i-o3syd03w52-us/475995d3b39f45b8906f3a458ad251f4~tplv-o3syd03w52-origin-jpeg.jpeg?dr=15568&from=4246405447&idc=my&ps=933b5bde&shcp=3c3d9ffb&shp=fd1b0147&t=555f072d","width":200},"product_name":"Thùng 48 Túi Nước Uống Ion Kiềm Giàu Hydrogen Cao Cấp Fujiwa pH9 Dạng Túi Bạc 270ml Chống oxy hoá, Trung hoà gốc tự do không Đường","refund_amount":{"currency":"VND","refund_shipping_fee":"0","refund_subtotal":"1259100","refund_tax":"0","refund_total":"1259100"},"return_line_item_id":"4035508318941514195","seller_sku":"FUJIWA05-40","sku_id":"1730420769435257463","sku_name":"Mặc định, Mặc định"}],"return_method":"PLATFORM_SHIPPED","return_provider_id":"6841743441349706241","return_provider_name":"J&T Express","return_reason":"ecom_order_delivered_refund_and_return_reason_not_match_description","return_reason_text":"Product doesn't match description","return_status":"RETURN_OR_REFUND_REQUEST_CANCEL","return_type":"RETURN_AND_REFUND","return_warehouse_address":{"full_address":"121/32 Trung Mỹ Tây 13, Khu phố 4, Quận 12, Hồ Chí Minh, Việt Nam,,Trung My Tay,District 12,Ho Chi Minh,Vietnam"},"role":"OPERATOR","shipment_type":"PLATFORM","shipping_fee_amount":[{"buyer_paid_return_shipping_fee":"0","currency":"VND","platform_paid_return_shipping_fee":"0","seller_paid_return_shipping_fee":"131500"}],"update_time":1732090613},{"combined_return_id":"0","create_time":1732435123,"discount_amount":[{"currency":"VND","product_platform_discount":"0","product_seller_discount":"171000","shipping_fee_platform_discount":"0","shipping_fee_seller_discount":"30000"}],"is_combined_return":false,"order_id":"579662417403939653","refund_amount":{"currency":"VND","refund_shipping_fee":"86700","refund_subtotal":"369000","refund_tax":"0","refund_total":"455700"},"return_id":"4035514753044220741","return_line_items":[{"order_line_item_id":"579662417404070725","product_image":{"height":200,"url":"https://p16-oec-general.tiktokcdn.com/tos-maliva-i-o3syd03w52-us/04dc497a15214f5ebf45d13fc0572501~tplv-o3syd03w52-origin-jpeg.jpeg?dr=15568&from=4246405447&idc=my&ps=933b5bde&shcp=3c3d9ffb&shp=fd1b0147&t=555f072d","width":200},"product_name":"Fujiwa Hộp 12 Túi Nước Uống Ion Kiềm Giàu Hydrogen Cao Cấp Fujiwa Dạng Túi Bạc 270ml không Chua","refund_amount":{"currency":"VND","refund_shipping_fee":"86700","refund_subtotal":"369000","refund_tax":"0","refund_total":"455700"},"return_line_item_id":"4035514753044286277","seller_sku":"FUJIWA05-10","sku_id":"1730420788048726647","sku_name":"Mặc định, Mặc định"}],"return_method":"BUYER_SHIPPED","return_provider_id":"6707206504077901825","return_provider_name":"Others","return_reason":"ecom_order_delivered_refund_and_return_reason_damaged","return_reason_text":"Package or product is damaged","return_status":"RETURN_OR_REFUND_REQUEST_CANCEL","return_type":"RETURN_AND_REFUND","return_warehouse_address":{"full_address":"121/32 Trung Mỹ Tây 13, Khu phố 4, Quận 12, Hồ Chí Minh, Việt Nam,,Trung My Tay,District 12,Ho Chi Minh,Vietnam"},"role":"BUYER","shipment_type":"BUYER_ARRANGE","shipping_fee_amount":[{"buyer_paid_return_shipping_fee":"0","currency":"VND","platform_paid_return_shipping_fee":"0","seller_paid_return_shipping_fee":"0"}],"update_time":1733338888},{"combined_return_id":"0","create_time":1732439043,"discount_amount":[{"currency":"VND","product_platform_discount":"0","product_seller_discount":"59000","shipping_fee_platform_discount":"57100","shipping_fee_seller_discount":"0"}],"handover_method":"PICKUP","is_combined_return":false,"is_quick_refund":true,"order_id":"579669030929468045","refund_amount":{"currency":"VND","refund_shipping_fee":"0","refund_subtotal":"143000","refund_tax":"0","refund_total":"143000"},"return_id":"4035514779895827085","return_line_items":[{"order_line_item_id":"579669030929599117","product_image":{"height":200,"url":"https://p19-oec-general.tiktokcdn.com/tos-maliva-i-o3syd03w52-us/07ab8f3942744e7798e41879d0b7796f~tplv-o3syd03w52-origin-jpeg.jpeg?dr=15568&from=4246405447&idc=my&ps=933b5bde&shcp=3c3d9ffb&shp=fd1b0147&t=555f072d","width":200},"product_name":"Fujiwa - Thùng 24 Chai 450ml Nước Uống Ion Kiềm Cao Cấp Đóng Chai - Nước uống Detox với Công Nghệ Điện Phân Ion Kiềm","refund_amount":{"currency":"VND","refund_shipping_fee":"0","refund_subtotal":"143000","refund_tax":"0","refund_total":"143000"},"return_line_item_id":"4035514779895892621","seller_sku":"FUJIWA02-450","sku_id":"1730420770070956663","sku_name":"Mặc định, Mặc định"}],"return_method":"PLATFORM_SHIPPED","return_provider_id":"6841743441349706241","return_provider_name":"J&T Express","return_reason":"ecom_order_delivered_refund_and_return_reason_defective","return_reason_text":"Product is defective or doesn't work","return_status":"RETURN_OR_REFUND_REQUEST_COMPLETE","return_tracking_number":"854205592824","return_type":"RETURN_AND_REFUND","return_warehouse_address":{"full_address":"121/32 Trung Mỹ Tây 13, Khu phố 4, Quận 12, Hồ Chí Minh, Việt Nam,,Trung My Tay,District 12,Ho Chi Minh,Vietnam"},"role":"BUYER","shipment_type":"PLATFORM","shipping_fee_amount":[{"buyer_paid_return_shipping_fee":"0","currency":"VND","platform_paid_return_shipping_fee":"0","seller_paid_return_shipping_fee":"57100"}],"update_time":1732800390},{"combined_return_id":"0","create_time":1732744055,"discount_amount":[{"currency":"VND","product_platform_discount":"52114","product_seller_discount":"428580","shipping_fee_platform_discount":"71500","shipping_fee_seller_discount":"0"}],"handover_method":"PICKUP","is_combined_return":false,"order_id":"579678756175383513","refund_amount":{"currency":"VND","refund_shipping_fee":"0","refund_subtotal":"599306","refund_tax":"0","refund_total":"599306"},"return_id":"4035516426519350233","return_line_items":[{"order_line_item_id":"579678752847793113","product_image":{"height":200,"url":"https://p16-oec-general.tiktokcdn.com/tos-maliva-i-o3syd03w52-us/bd165671ab264df7985c477df931907a~tplv-o3syd03w52-origin-jpeg.jpeg?dr=15568&from=4246405447&idc=my&ps=933b5bde&shcp=3c3d9ffb&shp=fd1b0147&t=555f072d","width":200},"product_name":"Fujiwa Hộp 12 Túi Nước Uống Ion Kiềm Giàu Hydrogen Cao Cấp Fujiwa Dạng Túi Bạc 270ml không Chua","refund_amount":{"currency":"VND","refund_shipping_fee":"0","refund_subtotal":"299653","refund_tax":"0","refund_total":"299653"},"return_line_item_id":"4035516426519415769","seller_sku":"FUJIWA05-10","sku_id":"1730420788048726647","sku_name":"Mặc định, Mặc định"},{"order_line_item_id":"579678752847858649","product_image":{"height":200,"url":"https://p16-oec-general.tiktokcdn.com/tos-maliva-i-o3syd03w52-us/bd165671ab264df7985c477df931907a~tplv-o3syd03w52-origin-jpeg.jpeg?dr=15568&from=4246405447&idc=my&ps=933b5bde&shcp=3c3d9ffb&shp=fd1b0147&t=555f072d","width":200},"product_name":"Fujiwa Hộp 12 Túi Nước Uống Ion Kiềm Giàu Hydrogen Cao Cấp Fujiwa Dạng Túi Bạc 270ml không Chua","refund_amount":{"currency":"VND","refund_shipping_fee":"0","refund_subtotal":"299653","refund_tax":"0","refund_total":"299653"},"return_line_item_id":"4035516426519481305","seller_sku":"FUJIWA05-10","sku_id":"1730420788048726647","sku_name":"Mặc định, Mặc định"}],"return_method":"PLATFORM_SHIPPED","return_provider_id":"6841743441349706241","return_provider_name":"J&T Express","return_reason":"ecom_order_delivered_refund_and_return_reason_wrong_product","return_reason_text":"Wrong product sent","return_status":"RETURN_OR_REFUND_REQUEST_COMPLETE","return_tracking_number":"854210282029","return_type":"RETURN_AND_REFUND","return_warehouse_address":{"full_address":"121/32 Trung Mỹ Tây 13, Khu phố 4, Quận 12, Hồ Chí Minh, Việt Nam,,Trung My Tay,District 12,Ho Chi Minh,Vietnam"},"role":"BUYER","shipment_type":"PLATFORM","shipping_fee_amount":[{"buyer_paid_return_shipping_fee":"0","currency":"VND","platform_paid_return_shipping_fee":"0","seller_paid_return_shipping_fee":"71500"}],"update_time":1733232234}],"total_count":71},"message":"Success","request_id":"20260706104420DB06C6750400ADA3EB4A"}

**Sanitized response body (optional)**

```json

```

---

### 9. Search Cancellations

| Field | Expected | Verified |
|-------|----------|----------|
| Version | `202602` | |
| Method / path | `POST /return_refund/202602/cancellations/search` | |
| Optional body | `update_time_ge`, `update_time_lt` | |
| Optional query | `page_size`, `page_token` | |

**Request Demo cURL**

```bash
curl -k -X 'POST' -d '{}' -H 'Content-Type: application/json' -H 'x-tts-access-token: ROW_9A2D_gAAAABbUg_84te3E8INEevR-bbuEOnDJM8WtbRPbpEwfsb5vN-A3kch8o1Z75o0SKWI1WMZNro6FFwXDAoubTUFWba-wu0a6b8xw8B7Q6Fc1f97S1sAFq4mI6QebiXx05mg_cJbx-b8V2Pbxwjylm_S4HwMzrK-wmUhl-pdudAys_OUQHHd5Qfbz-ITIJuoXrj1Q0k' 'https://open-api.tiktokglobalshop.com/return_refund/202602/cancellations/search?access_token=ROW_9A2D_gAAAABbUg_84te3E8INEevR-bbuEOnDJM8WtbRPbpEwfsb5vN-A3kch8o1Z75o0SKWI1WMZNro6FFwXDAoubTUFWba-wu0a6b8xw8B7Q6Fc1f97S1sAFq4mI6QebiXx05mg_cJbx-b8V2Pbxwjylm_S4HwMzrK-wmUhl-pdudAys_OUQHHd5Qfbz-ITIJuoXrj1Q0k&app_key=6kdu4f07vvlv9&page_size=1&shop_cipher=ROW_aiVo7gAAAAB2vvlFyfTxbVr4ZFHoDbhK&shop_id=&sign=172a10fab2721d9fc6cf900bb80a4c2ee0d596ad30bfed660a461042cb459542&timestamp=1783306117&version=202602'
```

**Response**

{"code":0,"data":{"cancellations":[{"cancel_id":"4035348475003308298","cancel_line_items":[{"cancel_line_item_id":"4035348475003373834","order_line_item_id":"577958834469570826","product_image":{"height":200,"url":"https://p16-oec-va.ibyteimg.com/tos-maliva-i-o3syd03w52-us/cd87288197f84f3192c50fa57cfe98de~tplv-o3syd03w52-origin-jpeg.jpeg?dr=15568&from=4246405447&idc=my&ps=933b5bde&shcp=3c3d9ffb&shp=fd1b0147&t=555f072d","width":200},"product_name":"Nước Uống Ion Kiềm Cao Cấp Đóng Chai Fujiwa Vietnam","seller_sku":"FUJIWA02-450","sku_id":"1729700293904534135","sku_name":"Thùng 24 Chai-450ml"},{"cancel_line_item_id":"4035348475003439370","order_line_item_id":"577958834469636362","product_image":{"height":200,"url":"https://p16-oec-va.ibyteimg.com/tos-maliva-i-o3syd03w52-us/cd87288197f84f3192c50fa57cfe98de~tplv-o3syd03w52-origin-jpeg.jpeg?dr=15568&from=4246405447&idc=my&ps=933b5bde&shcp=3c3d9ffb&shp=fd1b0147&t=555f072d","width":200},"product_name":"Nước Uống Ion Kiềm Cao Cấp Đóng Chai Fujiwa Vietnam","seller_sku":"FUJIWA02-450","sku_id":"1729700293904534135","sku_name":"Thùng 24 Chai-450ml"},{"cancel_line_item_id":"4035348475003504906","order_line_item_id":"577958834469701898","product_image":{"height":200,"url":"https://p16-oec-va.ibyteimg.com/tos-maliva-i-o3syd03w52-us/cd87288197f84f3192c50fa57cfe98de~tplv-o3syd03w52-origin-jpeg.jpeg?dr=15568&from=4246405447&idc=my&ps=933b5bde&shcp=3c3d9ffb&shp=fd1b0147&t=555f072d","width":200},"product_name":"Nước Uống Ion Kiềm Cao Cấp Đóng Chai Fujiwa Vietnam","seller_sku":"FUJIWA02-450","sku_id":"1729700293904534135","sku_name":"Thùng 24 Chai-450ml"}],"cancel_reason":"seller_cancel_paid_reason_address_not_deliver","cancel_reason_text":"Unable to deliver to customer address","cancel_status":"CANCELLATION_REQUEST_COMPLETE","cancel_type":"CANCEL","create_time":1696306119,"order_id":"577958834469439754","role":"SELLER","should_replenish_stock":true,"update_time":1696306119}],"next_page_token":"aDU2dHIzMlFhMEpPVG1KSTh5MmRZLy91VGxYNDNuQjBseldPT0tLTllzeHJRY0dWUXVLSQ==","total_count":2817},"message":"Success","request_id":"20260706104837924FC6F94AE7EA730774"}

**Sanitized response body (optional)**

```json

```

---

### 10. Inventory Search

| Field | Expected | Verified |
|-------|----------|----------|
| Version | `202309` | |
| Method / path | `POST /product/202309/inventory/search` | |
| Optional body | `sku_ids` | |
| Notes | Read contract for SKU context; not production inventory management scope | |

**Request Demo cURL**

```bash
curl -k -X 'POST' -d '{"product_ids":["1729700293904403063"],"sku_ids":["1729700293904534135","1730420785344318071"]}' -H 'Content-Type: application/json' -H 'x-tts-access-token: ROW_9A2D_gAAAABbUg_84te3E8INEevR-bbuEOnDJM8WtbRPbpEwfsb5vN-A3kch8o1Z75o0SKWI1WMZNro6FFwXDAoubTUFWba-wu0a6b8xw8B7Q6Fc1f97S1sAFq4mI6QebiXx05mg_cJbx-b8V2Pbxwjylm_S4HwMzrK-wmUhl-pdudAys_OUQHHd5Qfbz-ITIJuoXrj1Q0k' 'https://open-api.tiktokglobalshop.com/product/202309/inventory/search?access_token=ROW_9A2D_gAAAABbUg_84te3E8INEevR-bbuEOnDJM8WtbRPbpEwfsb5vN-A3kch8o1Z75o0SKWI1WMZNro6FFwXDAoubTUFWba-wu0a6b8xw8B7Q6Fc1f97S1sAFq4mI6QebiXx05mg_cJbx-b8V2Pbxwjylm_S4HwMzrK-wmUhl-pdudAys_OUQHHd5Qfbz-ITIJuoXrj1Q0k&app_key=6kdu4f07vvlv9&shop_cipher=ROW_aiVo7gAAAAB2vvlFyfTxbVr4ZFHoDbhK&shop_id=&sign=dba6634a9e71852252df2d2b65ffd40750236d3dec556b5b43a0ff82ad702d5e&timestamp=1783306596&version=202309'
```

**Response**

{"code":0,"data":{"inventory":[{"product_id":"1729700293904403063","skus":[{"id":"1729700293904534135","seller_sku":"FUJIWA02-450","total_available_inventory_distribution":{"in_shop_inventory":{"quantity":995}},"total_available_quantity":995,"total_committed_quantity":0,"warehouse_inventory":[{"available_quantity":995,"committed_quantity":0,"warehouse_id":"7272949914115966726"}]}]}]},"message":"Success","request_id":"2026070610563544F20DCA1C9F4865F084"}

**Sanitized response body (optional)**

```json

```

---

## Layer 2 — Sandbox write validation (SANDBOX_VN)

Use **SANDBOX_VN** credentials only. Business failures from sparse sandbox data are acceptable;
goal is technical validation (signing, payload, auth, response parsing).

### 14. Update Inventory

| Field | Expected | Verified |
|-------|----------|----------|
| Version | `202309` | |
| Method / path | `POST /product/202309/products/{product_id}/inventory/update` | |
| Body | `skus[].id`, `skus[].inventory[].warehouse_id`, `skus[].inventory[].quantity` | |
| `product_id` used | | |

**Request Demo cURL**

```bash

```

curl -k -X 'POST' -d '{"skus":[{"id":"1736404513645233795","inventory":[{"quantity":15}]},{"id":"1736404611682436739","inventory":[{"quantity":20}]}]}' -H 'Content-Type: application/json' -H 'x-tts-access-token: ROW_OWTKHgAAAABbUg_84te3E8INEevR-bbu-NChB9NPjPmsZdcMZbMrcCH2ZefY7NsUfZuci9oYsU1_a_t0kPBv1ZWV_1SBbZcmk3preZBFU3D7rIRCZHpnVChT5kUZS2m8ips6JC9MWqSwCENR3g1isOXvpmOnXVH-2pqRsYnwTdnEABMKbitcmNRobFHCxxHqqpi-TfZcdxc' 'https://open-api.tiktokglobalshop.com/product/202309/products/1736363193934775939/inventory/update?access_token=ROW_OWTKHgAAAABbUg_84te3E8INEevR-bbu-NChB9NPjPmsZdcMZbMrcCH2ZefY7NsUfZuci9oYsU1_a_t0kPBv1ZWV_1SBbZcmk3preZBFU3D7rIRCZHpnVChT5kUZS2m8ips6JC9MWqSwCENR3g1isOXvpmOnXVH-2pqRsYnwTdnEABMKbitcmNRobFHCxxHqqpi-TfZcdxc&app_key=6kdu4f07vvlv9&shop_cipher=ROW_6uQ0CgAAAABvDtviDc-R779RLLDiUzjR&shop_id=7494751643546977923&sign=9f2bb1acf91cfeb286f995a9af74a4504de33a02e9f6dac96ae86652f0f244a5&timestamp=1783310676&version=202309'

**Response**

{"code":0,"data":{},"message":"Success","request_id":"20260706120436B68CEC044C979801CB59"}

**Sanitized response body (optional)**

```json

```

---

### 15. Get Category Attributes

| Field | Expected | Verified |
|-------|----------|----------|
| Operation | `Get Category Attributes` (execution_layer.md §1 step 3) | |
| Version | `202309` | |
| Method / path | `GET /product/202309/categories/{category_id}/attributes` | |
| Required | `category_id`; include category version if exposed | |
| Notes | Required before create/edit when category attributes are mandatory or category changes | |

**Request Demo cURL**

```bash

```

**Response**

| HTTP status | TikTok `code` | `message` | Notes |
|-------------|---------------|-----------|-------|
| | | | |

**Sanitized response body (optional)**

```json

```

---

### 16. Upload Product Image

| Field | Expected | Verified |
|-------|----------|----------|
| Operation | `Upload Product Image` | |
| Version | `202309` | |
| Method / path | `POST /product/202309/images/upload` | |
| Response | Image `uri` / URL used by Create Product | |
| Notes | Redact signed image URLs in committed samples | |

**Request Demo cURL**

```bash

```

**Response**

| HTTP status | TikTok `code` | `message` | Notes |
|-------------|---------------|-----------|-------|
| | | | |

**Sanitized response body (optional)**

```json

```

---

### 17. Create Product

| Field | Expected | Verified |
|-------|----------|----------|
| Version | `202309` | |
| Method / path | `POST /product/202309/products` | |
| Body | `category_id`, `title`, `description`, `main_images[].uri`, `skus[]`, required `product_attributes[]` | |
| Notes | Same endpoint for single-SKU and multi-SKU creation; multi-SKU payload must include every SKU and sales attribute | |
Body request parameters
{
  "description": "Durable Stainless Water Bottle for everyday use",
  "category_id": "605254",
  "category_version": "v2",
  "title": "Premium Stainless Steel Water Bottle 750ml",
  "main_images": [
    {
      "uri": "tos-alisg-i-aphluv4xwc-sg/c85e41d2a1af49d4b42e011677e05aa0"
    }
  ],
  "skus": [
    {
      "seller_sku": "water-bottle-100ml",
      "inventory": [
        {
          "warehouse_id": "7657265511696664340",
          "quantity": 100
        }
      ],
      "price": {
        "amount": "100000",
        "currency": "VND"
      },
      "list_price": {
        "amount": "100000",
        "currency": "VND"
      },
      "sales_attributes": [],
      "combined_skus": [],
      "external_urls": [],
      "extra_identifier_codes": [],
      "external_list_prices": [],
      "fees": []
    }
  ],
  "product_attributes": [
    {
      "id": "102872",
      "values": [
        {
          "id": "1298954"
        }
      ]
    },
    {
      "id": "102999",
      "values": [
        {
          "name": "240000161/PCBA-HCM"
        }
      ]
    },
    {
      "id": "103000",
      "values": [
        {
          "name": "22/01/2024"
        }
      ]
    },
    {
      "id": "103001",
      "values": [
        {
          "name": "Thành phố Hồ Chí Minh"
        }
      ]
    },
    {
      "id": "100149",
      "values": [
        {
          "id": "1000854"
        }
      ]
    },
    {
      "id": "101489",
      "values": [
        {
          "name": "Fujiwa"
        }
      ]
    },
    {
      "id": "101490",
      "values": [
        {
          "name": "Fujiwa"
        }
      ]
    }
  ],
  "package_weight": {
    "value": "500",
    "unit": "GRAM"
  }
}

**Request Demo cURL**

```bash
curl -k -X 'POST' -d '{"description":"Durable Stainless Water Bottle for everyday use","category_id":"605254","category_version":"v2","title":"Premium Stainless Steel Water Bottle 750ml","main_images":[{"uri":"tos-alisg-i-aphluv4xwc-sg/c85e41d2a1af49d4b42e011677e05aa0"}],"skus":[{"seller_sku":"water-bottle-100ml","inventory":[{"warehouse_id":"7657265511696664340","quantity":100}],"price":{"amount":"100000","currency":"VND"},"list_price":{"amount":"100000","currency":"VND"},"sales_attributes":[],"combined_skus":[],"external_urls":[],"extra_identifier_codes":[],"external_list_prices":[],"fees":[]}],"product_attributes":[{"id":"102872","values":[{"id":"1298954"}]},{"id":"102999","values":[{"name":"240000161/PCBA-HCM"}]},{"id":"103000","values":[{"name":"22/01/2024"}]},{"id":"103001","values":[{"name":"Thành phố Hồ Chí Minh"}]},{"id":"100149","values":[{"id":"1000854"}]},{"id":"101489","values":[{"name":"Fujiwa"}]},{"id":"101490","values":[{"name":"Fujiwa"}]}],"package_weight":{"value":"500","unit":"GRAM"}}' -H 'Content-Type: application/json' -H 'x-tts-access-token: ROW_OWTKHgAAAABbUg_84te3E8INEevR-bbu-NChB9NPjPmsZdcMZbMrcCH2ZefY7NsUfZuci9oYsU1_a_t0kPBv1ZWV_1SBbZcmk3preZBFU3D7rIRCZHpnVChT5kUZS2m8ips6JC9MWqSwCENR3g1isOXvpmOnXVH-2pqRsYnwTdnEABMKbitcmNRobFHCxxHqqpi-TfZcdxc' 'https://open-api.tiktokglobalshop.com/product/202309/products?access_token=ROW_OWTKHgAAAABbUg_84te3E8INEevR-bbu-NChB9NPjPmsZdcMZbMrcCH2ZefY7NsUfZuci9oYsU1_a_t0kPBv1ZWV_1SBbZcmk3preZBFU3D7rIRCZHpnVChT5kUZS2m8ips6JC9MWqSwCENR3g1isOXvpmOnXVH-2pqRsYnwTdnEABMKbitcmNRobFHCxxHqqpi-TfZcdxc&app_key=6kdu4f07vvlv9&shop_cipher=ROW_6uQ0CgAAAABvDtviDc-R779RLLDiUzjR&shop_id=7494751643546977923&sign=946f16d052693fde3ff979bb01d4ae0183cc6b32fc281adbfecf1fefa0d01320&timestamp=1783316518&version=202309'
```

**Response**

{"code":0,"data":{"product_id":"1736405947247986307","skus":[{"fees":[],"id":"1736405690908575363","sales_attributes":[],"seller_sku":"water-bottle-100ml"}],"warnings":[]},"message":"Success","request_id":"20260706134157C43D65A356658703FB9F"}

**Sanitized response body (optional)**

```json

```

---

### 18. Edit Product (Partial)

| Field | Expected | Verified |
|-------|----------|----------|
| Operation | `Partial Edit Product` (execution_layer.md §2 step 5) | |
| Version | `202309` | |
| Method / path | `PUT /product/202309/products/{product_id}` — a `202509` full-replace variant is unconfirmed; do not use until verified | |
| Required | `product_id`; edited fields; category attributes if category changes | |

**Request Demo cURL**

```bash

```

**Response**

| HTTP status | TikTok `code` | `message` | Notes |
|-------------|---------------|-----------|-------|
| | | | |

**Sanitized response body (optional)**

```json

```

---

### 20. Create Promotion Activity

| Field | Expected | Verified |
|-------|----------|----------|
| Operation | `createActivity` | |
| Version | `202309` (verify) | |
| Method / path | **TBD from Promotion API Testing Tool** | |
| Body | `activity_type`, `title`, `begin_time`, `end_time`, product level / discount config | |

**Request Demo cURL**

```bash

```

**Response**

| HTTP status | TikTok `code` | `message` | Notes |
|-------------|---------------|-----------|-------|
| | | | |

**Sanitized response body (optional)**

```json

```

---

### 21. Update Promotion Products

| Field | Expected | Verified |
|-------|----------|----------|
| Operation | `updateActivityProduct` | |
| Version | `202309` (verify) | |
| Method / path | **TBD from Promotion API Testing Tool** | |
| Required | `activity_id`, `product_id`, `sku_id`, activity price/discount | |

**Request Demo cURL**

```bash

```

**Response**

| HTTP status | TikTok `code` | `message` | Notes |
|-------------|---------------|-----------|-------|
| | | | |

**Sanitized response body (optional)**

```json

```

---

### 22. Search Promotion Activity

| Field | Expected | Verified |
|-------|----------|----------|
| Operation | `searchActivity` | |
| Version | `202309` (verify) | |
| Method / path | **TBD from Promotion API Testing Tool** | |
| Notes | Validates created activity lifecycle state in sandbox | |

**Request Demo cURL**

```bash

```

**Response**

| HTTP status | TikTok `code` | `message` | Notes |
|-------------|---------------|-----------|-------|
| | | | |

**Sanitized response body (optional)**

```json

```

---

### 23. Deactivate Promotion Activity

| Field | Expected | Verified |
|-------|----------|----------|
| Operation | `deactivateActivity` | |
| Version | `202309` (verify) | |
| Method / path | **TBD from Promotion API Testing Tool** | |
| Required | `activity_id` | |

**Request Demo cURL**

```bash

```

**Response**

| HTTP status | TikTok `code` | `message` | Notes |
|-------------|---------------|-----------|-------|
| | | | |

**Sanitized response body (optional)**

```json

```

---

### 24. Approve Cancellation

| Field | Expected | Verified |
|-------|----------|----------|
| Operation | `Approve Cancellation` | |
| Version | `202602` — best-guess, matches the **verified** Search Cancellations family (§9); not yet independently confirmed for this specific write operation | |
| Method / path | `POST /return_refund/202602/cancellations/{cancel_id}/approve` | |
| Required | `cancel_id`; query `idempotency_key` | |
| Notes | Use SANDBOX_VN only; do not approve production cancellations | |

**Request Demo cURL**

```bash

```

**Response**

| HTTP status | TikTok `code` | `message` | Notes |
|-------------|---------------|-----------|-------|
| | | | |

**Sanitized response body (optional)**

```json

```

---

### 25. Reject Cancellation

| Field | Expected | Verified |
|-------|----------|----------|
| Operation | `Reject Cancellation` | |
| Version | `202602` — best-guess, matches the **verified** Search Cancellations family (§9); not yet independently confirmed for this specific write operation | |
| Method / path | `POST /return_refund/202602/cancellations/{cancel_id}/reject` | |
| Required | `cancel_id`; query `idempotency_key`; rejection reason payload | |

**Request Demo cURL**

```bash

```

**Response**

| HTTP status | TikTok `code` | `message` | Notes |
|-------------|---------------|-----------|-------|
| | | | |

**Sanitized response body (optional)**

```json

```

---

### 26. Approve Return

| Field | Expected | Verified |
|-------|----------|----------|
| Operation | `Approve Return` (also used for Approve Refund, 8c) | |
| Version | `202602` — best-guess, matches the **verified** Search Returns family (§8); not yet independently confirmed for this specific write operation | |
| Method / path | `POST /return_refund/202602/returns/{return_id}/approve` | |
| Required | `return_id`; query `idempotency_key`; refund/return approval payload | |

**Request Demo cURL**

```bash

```

**Response**

| HTTP status | TikTok `code` | `message` | Notes |
|-------------|---------------|-----------|-------|
| | | | |

**Sanitized response body (optional)**

```json

```

---

### 27. Reject Return

| Field | Expected | Verified |
|-------|----------|----------|
| Operation | `Reject Return` (also used for Reject Refund, 8c) | |
| Version | `202602` — best-guess, matches the **verified** Search Returns family (§8); not yet independently confirmed for this specific write operation | |
| Method / path | `POST /return_refund/202602/returns/{return_id}/reject` | |
| Required | `return_id`; query `idempotency_key`; rejection reason payload | |

**Request Demo cURL**

```bash

```

**Response**

| HTTP status | TikTok `code` | `message` | Notes |
|-------------|---------------|-----------|-------|
| | | | |

**Sanitized response body (optional)**

```json

```

---

### 28. Get Order Split Attributes

| Field | Expected | Verified |
|-------|----------|----------|
| Operation | `Get Order Split Attributes` | |
| Version | `202309` (verify) | |
| Method / path | **TBD from Fulfillment API Testing Tool** | |
| Required | `order_id` | |
| Notes | Determines whether the order can/must be split before package creation | |

**Request Demo cURL**

```bash

```

**Response**

| HTTP status | TikTok `code` | `message` | Notes |
|-------------|---------------|-----------|-------|
| | | | |

**Sanitized response body (optional)**

```json

```

---

### 29. Search Combinable Packages

| Field | Expected | Verified |
|-------|----------|----------|
| Operation | `Search Combinable Packages` | |
| Version | `202309` | |
| Method / path | `GET /fulfillment/202309/combinable_packages/search` | |
| Required | `order_id` or eligible package/order filter from Testing Tool | |
| Notes | Returns draft/combinable package IDs for the split/combine flow | |

**Request Demo cURL**

```bash

```

**Response**

| HTTP status | TikTok `code` | `message` | Notes |
|-------------|---------------|-----------|-------|
| | | | |

**Sanitized response body (optional)**

```json

```

---

### 30. Combine Package

| Field | Expected | Verified |
|-------|----------|----------|
| Operation | `Combine Package` | |
| Version | `202309` | |
| Method / path | `POST /fulfillment/202309/packages/combine` | |
| Required | `combinable_packages[]` / package IDs from Search Combinable Packages | |

**Request Demo cURL**

```bash

```

**Response**

| HTTP status | TikTok `code` | `message` | Notes |
|-------------|---------------|-----------|-------|
| | | | |

**Sanitized response body (optional)**

```json

```

---

### 31. Create Fulfillment Packages

| Field | Expected | Verified |
|-------|----------|----------|
| Operation | `Create Packages` | |
| Version | `202512` (verify) | |
| Method / path | **TBD** | |

**Request Demo cURL**

```bash

```

**Response**

| HTTP status | TikTok `code` | `message` | Notes |
|-------------|---------------|-----------|-------|
| | | | |

**Sanitized response body (optional)**

```json

```

---

### 32. Ship Package

| Field | Expected | Verified |
|-------|----------|----------|
| Version | `202309` | |
| Method / path | `POST /fulfillment/202309/packages/{package_id}/ship` | |
| `package_id` used | | |
| Body fields | **TBD** from cURL demo | |

**Request Demo cURL**

```bash

```

**Response**

| HTTP status | TikTok `code` | `message` | Notes |
|-------------|---------------|-----------|-------|
| | | | |

**Sanitized response body (optional)**

```json

```

---

### 33. Get Package Shipping Document

| Field | Expected | Verified |
|-------|----------|----------|
| Operation | `Get Package Shipping Document` | |
| Version | `202309` | |
| Method / path | `GET /fulfillment/202309/packages/{package_id}/shipping_documents` (verify) | |
| Required | package/order identifier, `document_type` | |

**Request Demo cURL**

```bash

```

**Response**

| HTTP status | TikTok `code` | `message` | Notes |
|-------------|---------------|-----------|-------|
| | | | |

**Sanitized response body (optional)**

```json

```

---

### 34-37. Coupon operations — REMOVED

**Investigated and removed this pass.** No `POST` (create) operation exists for
seller-facing coupon creation via the Partner API — coupons appear to be Seller
Center-only in the current API surface. `Create Coupon`, `Search Coupons`, `Get Coupon
Detail`, and `Delete / Deactivate Coupon` are **not implemented and not planned**. See
[`execution_layer.md`](../execution_layer.md) Promotion section for the removal
rationale. Row numbers 34-37 retired (not reused) to avoid shifting the numbering of
verified rows above. Re-add only if a verified create-coupon contract is found in a
future API version.

---

### 38. Get Package Detail

| Field | Expected | Verified |
|-------|----------|----------|
| Operation | `Get Package Detail` — replaces prior "Monitor Shipment Status" / "Get Package Shipping Info" labels | |
| Version | `202309` | |
| Method / path | `GET /fulfillment/202309/packages/{package_id}` | |
| Required | `package_id` | |
| Notes | Live Partner Center doc page confirmed at `get-package-detail-202309` | |

**Request Demo cURL**

```bash

```

**Response**

| HTTP status | TikTok `code` | `message` | Notes |
|-------------|---------------|-----------|-------|
| | | | |

**Sanitized response body (optional)**

```json

```

---

### 39. Confirm Package Shipment (Supply Chain API)

| Field | Expected | Verified |
|-------|----------|----------|
| Operation | `Confirm Package Shipment` — **moved from Fulfillment API to Supply Chain API** this pass | |
| Version | `202309` | |
| Method / path | `POST /supply_chain/202309/packages/sync` | |
| Required | `package_id`, shipment confirmation payload (TBD from Testing Tool) | |
| Notes | USER-CONFIRMED move; first Supply Chain API contract row in this file | |

**Request Demo cURL**

```bash

```

**Response**

| HTTP status | TikTok `code` | `message` | Notes |
|-------------|---------------|-----------|-------|
| | | | |

**Sanitized response body (optional)**

```json

```

---

### 40. Batch Ship Packages

| Field | Expected | Verified |
|-------|----------|----------|
| Operation | `Batch Ship Packages` — alternative to single Ship Package (§32) for shipping multiple packages in one call | |
| Version | `202309` | |
| Method / path | `POST /fulfillment/202309/packages/ship` | |
| Required | `package_id[]`, shipment payload (TBD from Testing Tool) | |

**Request Demo cURL**

```bash

```

**Response**

| HTTP status | TikTok `code` | `message` | Notes |
|-------------|---------------|-----------|-------|
| | | | |

**Sanitized response body (optional)**

```json

```

---

### 41. Split Orders

| Field | Expected | Verified |
|-------|----------|----------|
| Operation | `Split Orders` | |
| Version | `202309` (verify) | |
| Method / path | `POST /fulfillment/202309/orders/{order_id}/split` | |
| Required | `order_id`, split line-item allocation | |
| Notes | Follows Get Order Split Attributes (§28) in the Handle Split Package workflow | |

**Request Demo cURL**

```bash

```

**Response**

| HTTP status | TikTok `code` | `message` | Notes |
|-------------|---------------|-----------|-------|
| | | | |

**Sanitized response body (optional)**

```json

```

---

### 42. Uncombine Packages

| Field | Expected | Verified |
|-------|----------|----------|
| Operation | `Uncombine Packages` — optional rollback before shipment | |
| Version | `202309` (verify) | |
| Method / path | `POST /fulfillment/202309/packages/{package_id}/uncombine` | |
| Required | `package_id` | |

**Request Demo cURL**

```bash

```

**Response**

| HTTP status | TikTok `code` | `message` | Notes |
|-------------|---------------|-----------|-------|
| | | | |

**Sanitized response body (optional)**

```json

```

---

### 43. Get Decision Eligibility (8a Prevent Cancellation)

| Field | Expected | Verified |
|-------|----------|----------|
| Operation | `Get Decision Eligibility` — confirms the seller's decision window hasn't lapsed | |
| Version | `202601` | |
| Method / path | `GET /return_refund/202601/decision_eligibility` | |
| Required | `cancel_id` or `order_id` (TBD from Testing Tool) | |

**Request Demo cURL**

```bash

```

**Response**

| HTTP status | TikTok `code` | `message` | Notes |
|-------------|---------------|-----------|-------|
| | | | |

**Sanitized response body (optional)**

```json

```

---

### 44. Get Aftersale Eligibility (8b Prevent Return)

| Field | Expected | Verified |
|-------|----------|----------|
| Operation | `Get Aftersale Eligibility` — confirms the buyer's request is eligible (30-day window, item condition rules) | |
| Version | `202602` | |
| Method / path | `GET /return_refund/202602/orders/{order_id}/aftersale_eligibility` | |
| Required | `order_id` | |
| Notes | Shares the `202602` version tag with Search Returns/Cancellations (§8-9) but is a distinct resource path — no conflict, TikTok versions per release, not per resource | |

**Request Demo cURL**

```bash

```

**Response**

| HTTP status | TikTok `code` | `message` | Notes |
|-------------|---------------|-----------|-------|
| | | | |

**Sanitized response body (optional)**

```json

```

---

### 45. Get Reject Reasons (8a/8b/8c shared)

| Field | Expected | Verified |
|-------|----------|----------|
| Operation | `Get Reject Reasons` — SEA-market requirement before rejecting a cancellation or return | |
| Version | `202309` | |
| Method / path | `GET /return_refund/202309/reject_reasons` | |
| Notes | SEA-specific: Partner Center changelog explicitly lists "Get Rejection Reasons before Cancellation or Return Rejection" for SEA markets | |

**Request Demo cURL**

```bash

```

**Response**

| HTTP status | TikTok `code` | `message` | Notes |
|-------------|---------------|-----------|-------|
| | | | |

**Sanitized response body (optional)**

```json

```

---

### 46. Search Return Merchandise Authorization (RMA) (8b Prevent Return)

| Field | Expected | Verified |
|-------|----------|----------|
| Operation | `Search Return Merchandise Authorization` — tracks the physical item coming back before a decision is finalized | |
| Version | `202604` | |
| Method / path | `POST /return_refund/202604/rma/search` | |
| Optional body | `return_id` / `order_id` filter (TBD from Testing Tool) | |

**Request Demo cURL**

```bash

```

**Response**

| HTTP status | TikTok `code` | `message` | Notes |
|-------------|---------------|-----------|-------|
| | | | |

**Sanitized response body (optional)**

```json

```

---

### 47. Review Aftersales (8b Prevent Return)

| Field | Expected | Verified |
|-------|----------|----------|
| Operation | `Review Aftersales` — escalation-path review for ambiguous/high-risk cases (high T6 fraud score, e.g. suspected `item_swap`/`empty_return`) before a seller decision | |
| Version | `202603` | |
| Method / path | `POST /return_refund/202603/aftersales/review` | |
| Required | `return_id`, review outcome payload (TBD from Testing Tool) | |

**Request Demo cURL**

```bash

```

**Response**

| HTTP status | TikTok `code` | `message` | Notes |
|-------------|---------------|-----------|-------|
| | | | |

**Sanitized response body (optional)**

```json

```

---

### 48. Search Aftersales Request (8c Prevent Refund)

| Field | Expected | Verified |
|-------|----------|----------|
| Operation | `Search Aftersales Request` — refund request intake | |
| Version | `202603` | |
| Method / path | `POST /return_refund/202603/aftersales/search` | |
| Optional body | `update_time_ge`, `update_time_lt` (TBD from Testing Tool) | |

**Request Demo cURL**

```bash

```

**Response**

| HTTP status | TikTok `code` | `message` | Notes |
|-------------|---------------|-----------|-------|
| | | | |

**Sanitized response body (optional)**

```json

```

---

### 49. Calculate Refund (8c Prevent Refund)

| Field | Expected | Verified |
|-------|----------|----------|
| Operation | `Calculate Refund` — refund amount preview (partial vs. full) | |
| Version | `202309` | |
| Method / path | `POST /return_refund/202309/returns/{return_id}/calculate` | |
| Required | `return_id` | |

**Request Demo cURL**

```bash

```

**Response**

| HTTP status | TikTok `code` | `message` | Notes |
|-------------|---------------|-----------|-------|
| | | | |

**Sanitized response body (optional)**

```json

```

---

### 50. Get Return Records (8b Prevent Return)

| Field | Expected | Verified |
|-------|----------|----------|
| Operation | `Get Return Records` | |
| Version | `202309` (verify) | |
| Method / path | `GET /return_refund/202309/returns/{return_id}/records` | |
| Required | `return_id` | |

**Request Demo cURL**

```bash

```

**Response**

| HTTP status | TikTok `code` | `message` | Notes |
|-------------|---------------|-----------|-------|
| | | | |

**Sanitized response body (optional)**

```json

```

---

## Layer 2 (cont.) — Product listing read-support (execution_layer.md Product API)

These endpoints back the Create Hero Product / Optimize Product chains in
[`execution_layer.md`](../execution_layer.md) §1–2. Reads may be validated on Fujiwa; they
carry no write risk.

### 51. Get Category (Create Hero Product step 1)

| Field | Expected | Verified |
|-------|----------|----------|
| Operation | `Get Category` — resolve `category_id` before attributes | |
| Version | `202309` | |
| Method / path | `GET /product/202309/categories` | |
| Required | signing params, `shop_cipher`; header `x-tts-access-token` | |

**Request Demo cURL**

```bash

```

**Response**

| HTTP status | TikTok `code` | `message` | Notes |
|-------------|---------------|-----------|-------|
| | | | |

**Sanitized response body (optional)**

```json

```

---

### 52. Check Listing Prerequisites / Get Brands (Create Hero Product steps 2, 4)

| Field | Expected | Verified |
|-------|----------|----------|
| Operation | `Check Listing Prerequisites` (seller/category eligibility) + `Get Brands` (`brand_id` where required) | |
| Version | `202309` (verify in Products API Testing Tool) | |
| Method / path | **TBD from API Testing Tool** — brands under `GET /product/202309/brands` | |
| Required | `category_id` | |

**Request Demo cURL**

```bash

```

**Response**

| HTTP status | TikTok `code` | `message` | Notes |
|-------------|---------------|-----------|-------|
| | | | |

**Sanitized response body (optional)**

```json

```

---

### 53. Get Products SEO Words (Create Hero Product step 6 · Optimize Product step 2)

| Field | Expected | Verified |
|-------|----------|----------|
| Operation | `Get Products SEO Words` | |
| Version | `202405` | |
| Method / path | `GET /product/202405/products/seo_words` | |
| Required | signing params, `shop_cipher`; header `x-tts-access-token` | |

**Request Demo cURL**

```bash

```

**Response**

| HTTP status | TikTok `code` | `message` | Notes |
|-------------|---------------|-----------|-------|
| | | | |

**Sanitized response body (optional)**

```json

```

---

### 54. Get Recommended Product Title and Description (Create Hero Product step 7 · Optimize Product step 3)

| Field | Expected | Verified |
|-------|----------|----------|
| Operation | `Get Recommended Product Title and Description` | |
| Version | `202405` | |
| Method / path | `GET /product/202405/products/suggestions` | |
| Required | signing params, `shop_cipher`; header `x-tts-access-token` | |

**Request Demo cURL**

```bash

```

**Response**

| HTTP status | TikTok `code` | `message` | Notes |
|-------------|---------------|-----------|-------|
| | | | |

**Sanitized response body (optional)**

```json

```

---

### 55. Search Product (Create Hero Product step 9)

| Field | Expected | Verified |
|-------|----------|----------|
| Operation | `Search Product` — confirm listing status post-review | |
| Version | `202309` | |
| Method / path | `POST /product/202309/products/search` | |
| Notes | Same operation as §4; step 9 uses it to confirm the newly created product is live | |

**Request Demo cURL**

```bash

```

**Response**

| HTTP status | TikTok `code` | `message` | Notes |
|-------------|---------------|-----------|-------|
| | | | |

**Sanitized response body (optional)**

```json

```

---

### 56. Update Price (Optimize Product step 6 · Clear Excess Inventory step 3)

| Field | Expected | Verified |
|-------|----------|----------|
| Operation | `Update Price` | |
| Version | `202309` | |
| Method / path | `POST /product/202309/products/{product_id}/prices/update` | |
| Required | `product_id`, `skus[].id`, `skus[].price` payload | |
| Merchant | SANDBOX_VN (write) | |

**Request Demo cURL**

```bash

```

**Response**

| HTTP status | TikTok `code` | `message` | Notes |
|-------------|---------------|-----------|-------|
| | | | |

**Sanitized response body (optional)**

```json

```

---

## Submission checklist

- [ ] Layer 1 read endpoints 3–10 have cURL + response status (or documented failure with TikTok `code`)
- [ ] Layer 2 write endpoints 14–33, 38–50, 56 have cURL + response status (business errors OK) — rows 34–37 (coupons) are retired/removed, not pending
- [ ] Product listing read-support endpoints 51–55 verified against the Products API Testing Tool
- [ ] Search Products / Get Product (§4–5) re-captured at `202309` per execution_layer.md
- [ ] Approve/Reject Cancellation and Return (24-27) confirm or correct the `202602` best-guess version before implementation
- [ ] No secrets in pasted cURL (redact `app_secret`, tokens, buyer PII)

**Return to:** coding agent via chat or PR comment after filling. Docs will be updated with
verified deltas; then see [`docs/handoffs/phase-2-tiktok-implementation.md`](../handoffs/phase-2-tiktok-implementation.md).
