# P0 - TikTok Shop webhook coverage cho thay doi seller-side (D11(2))
Ngay: 2026-10-20. Read-only. Nguon chinh: corpus vendor (crawl 2026-07-21)
C = <vendor corpus: .worktrees/adhoc/partner_documents>
F = <repo> (docs/integrations/tiktok_api/webhooks.md, webhook-contract-collection.md, backend/src/juli_backend/services/tiktok/webhook_catalog.py, services/product_history/webhooks.py)

Juli da subscribe (webhooks.md, catalog Phase 2): 1,2(legacy v1, thay bang 11+12),3,4,5,6,7,11,12,15,16,18,21,24,27,37,39,58,63,64,65,67,68.
Chua subscribe nhung co trong docs: 19 size chart, 25 opportunity matching, 38 strikethrough price expired, 42 combined listing, 46 image translation, 50 SKU status change, 51/52 global replication/listing method, 62, 66.
Huong Juli da lam: 15/16/18/39/63 -> khong ETL, chi enqueue "re-read + diff" (product_history/webhooks.py), coalesce 60s/(shop, subject), dedupe bang tts_notification_id (ttsn:<id>).

Payload chung: type(int), tts_notification_id(string), shop_id(string), timestamp(s), data{...}. Webhook 68 thuc te khong co shop_id top-level (dung data.seller_id + seller_open_id).
Scope: webhook 15/37/... can scope "Product Basic" (seller.product.basic); 39 can "Promotion Information". API version: webhook khong co version trong URL (topic id); quan ly subscription bang Event API 202309 (/event/202309/webhooks, scope seller.authorization.info).

## (a) Title / description
| webhook? | event / type | payload | nguon |
|---|---|---|---|
| YES | PRODUCT_INFORMATION_CHANGE, type 15 | data: product_id, change_source (SELLER_CENTER \| OPEN_API), changed_fields[] (title, description, main_images, product_attributes, size_chart_image, size_chart_template, others), update_time. KHONG gui gia tri cu/moi -> phai Get Product de doc lai | C/webhooks/product/15-product-information-change.md ; https://partner.tiktokshop.com/docv2/page/15-product-information-change ; thay 2026-07-21 |
Fire cho seller edit trong Seller Center: CO (change_source=SELLER_CENTER ghi ro). Chi fire khi thay doi "take effect online" cua san pham dang live (edit bi re-audit chua len live thi chua fire; xem 37/5).

## (b) Price
| webhook? | event / type | payload | nguon |
|---|---|---|---|
| NO (UNCONFIRMED) | Khong co topic gia rieng. 15.changed_fields khong liet ke "price"; chi co "others" (mo ta "other properties not specified above") - chua xac nhan gia nam trong "others" | - | C/webhooks/product/*.md (liet ke het 17 topic product). 38 STRIKETHROUGH_PRICE_EXPIRED chi la het han gia gach. Edit price/inventory khong qua re-audit va len ngay (partial-edit-product-202509.md dong 18) |
Da thu: doc 15, danh sach topic product, grep "price". Can bat 1 delivery that (webhook_raw_events) sau khi doi gia trong Seller Center de xac nhan co fire 15/others hay khong.

## (c) Main / cover images
| webhook? | event / type | payload | nguon |
|---|---|---|---|
| YES | type 15, changed_fields co "main_images" (anh thu vien: them/xoa/doi) | nhu (a) | nhu (a) |
Anh SKU-level / anh mo ta: UNCONFIRMED (co the vao "others"). 46 IMAGE_TRANSLATION_COMPLETED chi cho tac vu dich anh.

## (d) SKU add/remove / SKU attributes
| webhook? | event / type | payload | nguon |
|---|---|---|---|
| PARTIAL | (50) SKU status change - type 50 "pending final assignment", mau JSON ghi "type":"TBD" | data: product_id, skus[{sku_id, status: CREATED\|DELETED\|ACTIVATED\|DEACTIVATED, deactivation_source: SELLER\|PLATFORM\|COMBO_RELATION}], update_time | C/webhooks/product/u94ho74u.md (page u94ho74u) ; crawl 2026-07-21 |
| PARTIAL | 15 voi product_attributes | chi attribute cua san pham, KHONG phai sales attribute/SKU (UNCONFIRMED) | nhu (a) |
Webhook 50 moi, topic id chua chot -> chua nen dua vao no. Chua biet fire cho seller-edit Seller Center hay chi API (khong co truong change_source). Juli chua subscribe 50.

## (e) Stock / inventory
| webhook? | event / type | payload | nguon |
|---|---|---|---|
| YES (rat tot) | INVENTORY_CHANGED, type 68 | data: event_id (idempotency cap event), occurred_at, product_id, sku_id, seller_id, quantity_snapshot_after_change{total, in_shop, available, committed, campaign_locked, creator_locked}, change_detail[]{trigger_source, *_delta, idempotency_key, occurred_at}. trigger_source: order_created/canceled/shipped, manual_adjustment (Seller Center), api_sync, campaign_lock/unlock, creator_lock/unlock, system_auto_replenish. "real-time", moi thi truong | C/webhooks/product/7u0ofsrd.md ; F contract-collection #68 live capture 2026-07-14 |
| YES (nguong) | INVENTORY_STATUS_CHANGE, type 27 | product_id, sku_id, trigger_reason{alert_type REALTIME\|PREDICTION}, current_inventory_status (SUFFICIENT/LOW/OUT_OF_STOCK), inventory_distribution, update_time. Chi khi xuong LOW/OUT hoac du bao het hang | C/webhooks/product/27-inventory-status-change.md |
Fire cho seller edit Seller Center: CO (manual_adjustment). Luu y: 68 phat sinh moi don hang -> volume cao; Juli da coalesce 15 phut (COALESCE_68_SECONDS).

## (f) Product status (activate/deactivate/delete/audit)
| webhook? | event / type | payload | nguon |
|---|---|---|---|
| YES | PRODUCT_STATUS_CHANGE, type 5 | product_id, status (PRODUCT_FIRST_PASS_REVIEW \| PRODUCT_STATUS_CHANGED \| PRODUCT_AUDIT_FAILURE), suspended_reason, update_time. Khong noi ro seller-deactivate/delete co fire hay chi platform/audit -> UNCONFIRMED cho seller activate/deactivate/delete | C/webhooks/product/5-product-status-change.md |
| YES | PRODUCT_AUDIT_STATUS_CHANGE, type 37 | product_id, audit{status NONE/AUDITING/FAILED/PRE_APPROVED/APPROVED, pre_approved_reasons[]}, integrated_platform_statuses, update_time. Can scope Product Basic | C/webhooks/product/37-product-audit-status-change.md |
| YES | PRODUCT_CREATION type 16 (product_id, product_types[GPR_PRODUCT\|COMBINED_PRODUCT], update_time); PRODUCT_CATEGORY_CHANGE type 18 (previous/current_category_id; fire ca khi seller/dev/TikTok doi) | | C/webhooks/product/16-*.md, 18-*.md |
Xoa san pham (DELETE) khong co topic rieng da thay: UNCONFIRMED.

## (g) Promotions / activities / coupons
| webhook? | event / type | payload | nguon |
|---|---|---|---|
| YES (activity) | ACTIVITY_STATUS_CHANGE, type 39 | activity_id, activity_type (FIXED_PRICE, DIRECT_DISCOUNT, SHIPPING_DISCOUNT, BUY_MORE_SAVE_MORE, FLASHSALE-SEA), product_level, status (ONGOING \| EXPIRED \| DEACTIVATED), update_time. Chi start/expire/deactivate; can scope Promotion Information | C/webhooks/promotion/39-activity-status-change.md |
| YES (activity) | ACTIVITY_CHANGE, type 63 | activity_id, update_time, change_type (CREATE\|UPDATE\|DEACTIVATE), product_update_list{product_ids, exclude_product_ids, benefit_product_ids}, product_remove_list{product_ids, sku_ids,...}. Cho biet san pham nao them/bot, khong gui gia tri thay doi khac. Doc ghi mau change_type "product_update" khong khop enum (doc tu mau thuan) | C/webhooks/promotion/x6legjl9.md (page x6legjl9) |
| NO | Coupon: khong thay webhook nao cho coupon trong thu muc webhooks/promotion (chi 39, 63) | | C/webhooks/promotion/ |
Seller Center vs API cho 39/63: khong co truong source -> UNCONFIRMED; doc noi "activity" nhung khong gioi han API-only.

## Delivery guarantees
- Retry/order/dedupe: trang Webhooks overview KHONG doc duoc (WebFetch/Chrome: docv2/page/webhooks-overview va 650a99c4... tra "No document found"; khong tim thay overview trong corpus). UNCONFIRMED chinh thuc.
- Co dinh: tts_notification_id (dedupe cap notification); webhook 68 them event_id + idempotency_key. Juli da quan sat: trung lap la binh thuong (webhooks.md "Duplicate delivery is normal"), ACK <3s (so Juli dat ra, khong phai trich dan TikTok). Khong co bang chung ve thu tu: dung update_time/timestamp, khong tin thu tu den.
- Webhook la "latest-state trigger": 15 khong mang gia tri, nen thiet ke luon la re-read.

## Polling theo update_time
- Search Products (POST /product/202502/products/search, scope seller.product.basic): body co update_time_ge / update_time_le (Unix s; thieu le thi = now; thieu ge thi = tu dau shop). page_size bat buoc, 1-100; phan trang bang page_token. Nguon: C/api-reference/products/search-products-202502.md dong 83-178. Get Product 202309 la doc chi tiet theo product_id (khong co filter thoi gian).
- Search Promotion Activities 202309: page_size 0-100 (mac dinh 50), page_token+page_size < 10000; tra create_time/update_time trong ket qua, chua thay filter update_time trong request (UNCONFIRMED, can doc ky muc request). Search Coupon List 202406: page_size 1-100 (mac dinh 50), ket qua co update_time (ms).
- Inventory Search 202309 ton tai (inventory-search-202309.md) - chua doc chi tiet gioi han.

## Ket luan cho D11(2)
Near-real-time (webhook): title/description/main_images/product_attributes (15, co changed_fields + change_source nen biet Seller Center hay API), stock (68 tot nhat, 27 chi nguong), status/audit (5, 37), category (18), tao moi (16), activity start/expire/deactivate (39) va activity create/update/product list (63). Webhook chi bao "co thay doi", payload khong chua gia tri moi -> luon re-read bang Get Product / Get Activity.
Can incremental poll: GIA (khong co webhook; 15/others chua xac nhan), SKU add/remove va SKU attribute (50 chua chot type; 15 khong phu), seller xoa/deactivate san pham (5 khong ro), coupon (khong co webhook), thay doi gia tri khuyen mai (63 chi nho san pham, khong gia tri), va moi nhu cau doi soat vi khong co dam bao retry/thu tu da xac nhan.
De xuat poll fallback: Search Products voi update_time_ge = (cursor - 10 phut overlap), page_size=100, moi 15 phut (khop quy tac Juli "reconciliation <=15 phut") + 1 lan full reconcile/ngay (thuc dung cho xoa/mat webhook); activities/coupons moi 30-60 phut. Dung update_time lam cursor, upsert idempotent, bo qua trung bang product_id+update_time.
Viec con lai de chot: (1) doi gia 1 SKU trong Seller Center tren shop test va xem webhook_raw_events co type 15 (others) khong; (2) thu SKU add/remove va deactivate/delete; (3) lay trang Webhooks overview (retry policy) qua Partner Center khi dang nhap hoac ticket.
