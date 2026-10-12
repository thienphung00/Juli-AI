# apiwatch — theo dõi thay đổi API/doc của TikTok Shop và Shopee

> **Quyết định:** `fasttrack/DECISIONS.md` D31.10 · **Code:** `infra/apiwatch/` ·
> **Workflow:** `.github/workflows/apiwatch.yml` · **Drift lúc chạy:**
> `backend/src/juli_backend/integrations/schema_drift.py`

TikTok Shop và Shopee đổi API và tài liệu thường xuyên, thường không báo trước. Juli
có hai lớp phát hiện:

1. **apiwatch (hằng tuần)** — đọc tài liệu CÔNG KHAI của hai nền tảng, chụp lại thành
   snapshot JSON, so với snapshot đã commit và mở issue khi có thay đổi.
2. **Schema drift (lúc chạy)** — mỗi client so response thật với các field Juli đọc và
   ghi log `api_schema_drift` khi thiếu field hoặc có field lạ.

---

## 1. Nguồn dữ liệu

| Nền tảng | Nguồn (không cần đăng nhập) | Nội dung |
| --- | --- | --- |
| TikTok Shop | `partner.tiktokshop.com/api/v1/document/tree?workspace_id=3` | toàn bộ cây tài liệu docv2 (API, webhook, changelog) |
| | `…/document/api_external/list?document_id=X&api_config_version=2` | mọi phiên bản của một API (cây chỉ có bản mới nhất) |
| | `…/document/api_meta?src_document_id=X` | path, method, tham số request, field response, scope |
| | `…/document/detail?document_id=X&workspace_id=3` | nội dung trang webhook / changelog |
| | GitHub `EcomPHP/tiktokshop-php`, `tiktok/tiktok-business-api-sdk` | SDK (SDK chính thức của TikTok Shop sinh riêng cho từng app trong Partner Center, cần đăng nhập — không theo dõi được) |
| Shopee | `open.shopee.com/opservice/api/v1/doc/module/?version=2` | danh sách module + API |
| | `…/doc/api/?api_name=v2.x.y&version=2` | tham số request/response, nhật ký cập nhật của từng API |
| | `…/push/category`, `…/push/doc?push_api_id=N` | danh mục push và field |
| | `…/developer_guide/list?language_code=en` | danh sách developer guide |
| | GitHub `congminh1254/shopee-sdk` | SDK cộng đồng |

"Juli dùng" được suy ra từ code: path trong `integrations/tiktok/constants.py`, mã
webhook trong `services/tiktok/webhook_catalog.py`; với Shopee là mọi path
`/api/v2/...` trong file backend có chữ `shopee` (chưa có), cộng danh sách dự kiến của
D31 trong `infra/apiwatch/apiwatch/juli_usage.py` (gắn nhãn "Juli dự kiến dùng").

## 2. Workflow chạy thế nào

- Thứ Hai 01:00 UTC (08:00 giờ VN), hoặc bấm **Run workflow** (`workflow_dispatch`).
- Không cần secret. Token mặc định chỉ dùng cho GitHub (issue, PR, rate limit API).
- Có thay đổi → **một issue mỗi nền tảng mỗi tuần**, tiêu đề `apiwatch: <platform> <YYYY-Www>`,
  nhãn `apiwatch`. Chạy lại trong cùng tuần thì issue đó được cập nhật, không tạo thêm.
- Snapshot mới được commit lên nhánh `apiwatch/<ngày>` và mở PR. **Merge PR = đã ghi nhận**;
  lần chạy sau so với snapshot mới.
- Nguồn nào lỗi (mất mạng, nền tảng đổi API doc) → issue vẫn được mở với mục
  **"Nguồn lỗi"**; phần đó giữ nguyên snapshot cũ, KHÔNG bị coi là "bị gỡ".
- Báo cáo đầy đủ + `changes.json` nằm trong artifact `apiwatch-<run_id>` (90 ngày).

Lưu ý: lịch chạy chỉ hoạt động khi workflow nằm trên nhánh mặc định; PR do
`GITHUB_TOKEN` mở không kích hoạt CI khác (PR chỉ chứa JSON); cần bật "Allow GitHub
Actions to create and approve pull requests" trong Settings → Actions.

## 3. Đọc issue

Thứ tự trong báo cáo:

1. **Juli dùng — xử lý trước**: endpoint/webhook Juli đang gọi, hoặc changelog nhắc tới
   chúng (theo path hoặc tên API). "phiên bản khác của endpoint Juli dùng" = TikTok ra
   phiên bản mới (hoặc gỡ phiên bản cũ) của endpoint Juli đang ghim.
2. **Deprecation / breaking**: mô tả có "deprecated / sunset / retired / coming offline",
   hoặc changelog gắn nhãn "Breaking Change" / "Deprecation".
3. Juli dự kiến dùng (Shopee D31), endpoint bị gỡ / thay đổi / mới, webhook/push,
   changelog, SDK.

Ký hiệu field: `+` thêm, `−` bỏ, `~` đổi kiểu hoặc đổi bắt buộc. `a[].b` là field `b`
trong từng phần tử của mảng `a`. Path request có tiền tố vị trí (`query.`, `body.`,
`path.`, `header.`).

## 4. Xử lý

| Tình huống | Làm gì |
| --- | --- |
| Field response Juli đọc bị bỏ / đổi kiểu | Mở issue fix ngay; tìm chỗ đọc field (`integrations/tiktok/mapping.py`, `schemas.py`, `services/*`). Kiểm tra log `api_schema_drift` trên production để biết đã ảnh hưởng chưa. |
| Endpoint Juli ghim bị đánh dấu deprecated / có ngày retire | Tạo issue nâng version (hằng số `*_API_VERSION` trong `constants.py`), ghi hạn chót từ changelog. |
| Có phiên bản mới của endpoint Juli dùng | Đọc trang doc mới; nâng version khi có field cần dùng hoặc trước hạn retire. Không bắt buộc ngay. |
| Request param mới **bắt buộc** | Ưu tiên cao: call có thể bị từ chối. Kiểm tra sandbox. |
| Webhook Juli nhận đổi field | Sửa handler trong `services/webhook/` và catalog. |
| Changelog mới nhắc API Juli dùng | Đọc trang (link trong issue), quyết định có cần việc không. |
| SDK ra bản mới | Chỉ để tham khảo (Juli tự viết client); đọc release note khi nghi có thay đổi signing/auth. |
| Chỉ có thay đổi không liên quan Juli | Lướt qua, đóng issue, merge PR snapshot. |
| Mục "Nguồn lỗi" lặp lại 2 tuần | Chạy tay (dưới đây) để xem lỗi; có thể nền tảng đổi API doc — sửa `infra/apiwatch/apiwatch/<platform>.py`. |

Xong việc: đóng issue (ghi link issue/PR fix nếu có) và merge PR snapshot. Nếu merge PR
mà không xử lý, thay đổi đó sẽ không được báo lại.

## 5. Chạy tay

```bash
# Không cần venv của backend: chỉ cần python3 + requests.
PYTHONPATH=infra/apiwatch python3 -m apiwatch run --platform tiktok --out-dir /tmp/apiwatch
#   --write       ghi đè snapshot nếu đổi   --limit 5   lấy ít trang (debug)
#   --raw-dir D   lưu response thô          --raw-in D  normalize lại từ response thô
PYTHONPATH=infra/apiwatch python3 -m apiwatch diff old.json new.json --platform shopee
```

Mặc định cách nhau 0,35 s giữa các request, retry có backoff với 429/5xx. Một lượt đầy
đủ ≈ 1.000 request TikTok + ≈ 500 request Shopee.

Snapshot > ~5 MB tự chuyển sang dạng gọn (chỉ path field, bỏ kiểu/bắt buộc;
`"compact": true`). Diff vẫn hoạt động, nhưng không còn thấy đổi kiểu.

## 6. Schema drift lúc chạy (`api_schema_drift`)

`report_schema_drift(platform, endpoint, payload, expected, documented=...)` so một
response với các field client dựa vào và ghi **một** warning có cấu trúc cho mỗi
(platform, endpoint, tập field lệch) trong mỗi process:

```json
{"message": "api_schema_drift", "event": "api_schema_drift", "platform": "tiktok",
 "endpoint": "GET /product/202309/products/{product_id}",
 "missing_fields": ["skus[].price.sale_price"], "unexpected_fields": [], ...}
```

- `missing_fields`: field Juli đọc mà response không có → số liệu có thể sai im lặng.
  **Xử lý như lỗi.** (Field trong mảng chỉ tính thiếu khi KHÔNG phần tử nào có; mảng rỗng
  thì bỏ qua.)
- `unexpected_fields`: field không có trong tài liệu lúc viết code → nền tảng vừa thêm
  field. Thường vô hại; đối chiếu với issue apiwatch.
- Check không bao giờ ném lỗi và không đổi dữ liệu trả về.

TikTok đang được kiểm tra: product detail, search products, orders search/detail,
analytics (shop performance, product performance list/detail, SKU list), promotion
activities search/detail — danh sách và field nằm ở
`backend/src/juli_backend/integrations/tiktok/schema_expectations.py`. Khi Juli đọc
thêm field hoặc nâng version, cập nhật file đó; test
`tests/unit/test_tiktok_schema_expectations.py` kiểm tra mọi field kỳ vọng có trong
snapshot tài liệu. Client Shopee / Juli Connector dùng cùng helper khi được viết.

Tìm log: `journalctl -u <service> | grep api_schema_drift` trên VPS (log JSON ra stdout).

## 7. Đã xử lý

### 2026-10-12 — Get Shop Video Performance Details bị thay (changelog Analytics 2026-09-28)

- **Nguồn:** changelog `docv2/page/6az7iwe9` ("Analytics API Changelog: Enhanced Shop,
  Video, and LIVE Analytics"). API cũ `GET /analytics/202509/shop_videos/{video_id}/performance`
  bị retire **chậm nhất 2026-12-28**; thay bằng **Get Shop Videos Performance Details
  202609** `GET /analytics/202609/shop_videos/batch_performance` (`video_ids` dạng
  `[]int`, tối đa 500; cửa sổ ngày ≤ 60 ngày).
- **Field:** `data.performance` → `data.videos[].performance` (intervals, `sales.overall`,
  `traffic`, `viewer_profile` giữ tên); `latest_available_date` giữ ở gốc; thêm
  `videos[].video_id`, `video{…}`, `error{code,message}` (lỗi riêng từng video).
  `sales.breakdowns[]` bị bỏ (chuyển sang Get Shop Video Product Performance List) — Juli
  không đọc field này.
- **Scope:** không đổi — cả hai đều `data.shop_analytics.public.read` (gói "TikTok Shop
  Analytics"). Không cần xin scope mới.
- **Juli:** chỉ một chỗ gọi — `services/shop_diagnosis_daily/video_windows.py` (xếp hạng
  video 30/30, P8-B) qua `AnalyticsResource.get_video_performance`. Hàm này giờ gọi API
  batch (một id mỗi lần) và trả lại đúng shape 202509. Nếu API mới bị từ chối vì
  scope/quyền (`PermissionDeniedError`, mã `105005`, HTTP 403/404) thì dùng API cũ tới hết
  2026-12-28 và ghi log `tiktok_endpoint_fallback` **một lần mỗi process**. Thấy log này
  trên production → kiểm tra scope/app trong Partner Center trước 2026-12-28.
- Drift: `schema_expectations.py` có mục "shop videos performance details". apiwatch tự
  đọc path mới từ `constants.py`; path cũ vẫn được theo dõi tới khi gỡ fallback.
- **Cần kiểm tra live (owner):** cách mã hoá `video_ids` (Juli gửi `[id]` như request mẫu
  trong doc). Nếu TikTok trả `invalid request params`, sửa `get_videos_performance`.
- Sau 2026-12-28: xoá `get_video_performance_legacy`, pattern 202509 trong
  `capabilities.py` và hằng số `ANALYTICS_VIDEO_DETAILS_LEGACY_*`.

### 2026-10-12 — Webhook 2 (`REVERSE_STATUS_UPDATE`) không còn trong tài liệu

- Cây docv2 (workspace 3) không có trang type 2. Trang duy nhất là bản **docv1** "Reverse
  Status Update" (`/doc/page/63fd7459715d622a338c5437`, keyword `v1_deprecated`, sửa lần
  cuối 2024-01-29). Changelog "Introducing API version 202309" (2023-09-19) giới thiệu
  **11 Cancellation status change** và **12 Return status change** thay cho luồng này.
  Không có changelog nào ghi ngày retire riêng cho type 2.
- `REVERSE_STATUS_UPDATE` **vẫn** nằm trong enum `event_type` của Update/Get Shop Webhook
  202309 và bảng Overview (sửa 2026-07-06), nhưng link của nó trỏ về trang docv1 → coi là
  legacy, có thể vẫn được gửi cho shop đã đăng ký.
- **Juli:** giữ mục 2 trong catalog (vẫn route, vẫn ack 200 và lưu raw như mọi type).
  11 thành *material* (fetch `orders`, `analytics_shop`); 12 thêm workflow `prevent_refund_8c`
  (refund-only giờ đến qua 12, `return_type = REFUND`) và fetch `orders`. 11 + 12 phủ đủ
  những gì type 2 từng kích hoạt (`LEGACY_SUPERSEDED_BY`, test trong
  `tests/unit/test_webhook_catalog.py`).
- **Owner, Partner Center:** đăng ký **11** (`CANCELLATION_STATUS_CHANGE`) và **12**
  (`RETURN_STATUS_CHANGE`) nếu chưa có; giữ **2** tới khi thấy 11/12 về production, rồi
  huỷ **2**. Các type hậu mãi mới **64** (Aftersales Request Status Update), **65** (RMA),
  **67** (Refund Success) đã có trong catalog, đăng ký tuỳ nhu cầu.
