# scripts/seo — theo dõi và cải thiện app-juli.com trên Google (D43)

Mục tiêu: **chỉ domain chính `app-juli.com` được index**; `demo.app-juli.com` và
`ops.app-juli.com` ra khỏi Google; các trang chính được index đúng canonical và tăng dần
lượt hiển thị / nhấp.

| Script | Cần Google? | Làm gì | Khi nào chạy |
|---|---|---|---|
| `seo_live_check` | Không | Đọc sitemap, kiểm tra từng trang như Googlebot thấy (HTTP 200, 1 H1, heading không nhảy cấp, title ≤ 60, description ≤ 155, canonical tự trỏ, OG, JSON-LD Organization + WebSite, không trùng title/description) và kiểm tra subdomain có noindex mà robots.txt không chặn | Sau **mỗi** deploy |
| `gsc_index_audit` | Có | URL Inspection API cho mọi URL trong sitemap (phải PASS, canonical Google chọn = canonical khai báo) và các URL mẫu của demo / ops (không được PASS) | Hằng tuần, và vài ngày sau deploy |
| `gsc_pull` | Có | Kéo dữ liệu Hiệu suất 1 ngày đã chốt (mặc định 3 ngày trước) vào SQLite | Hằng ngày |
| `gsc_report` | Có (dữ liệu đã kéo) | Báo cáo việc cần làm: tổng 7 ngày, rò rỉ subdomain, trang CTR thấp, truy vấn vị trí 8–20, trùng truy vấn, trang sitemap không có hiển thị, lỗi inspection; mục 8 (`gsc_blog`, D56 G6): từng URL `/blog/*`, `/cong-cu/*` 7 / 28 ngày (hiển thị, nhấp, CTR, vị trí, truy vấn mới) và cờ: ≥ 100 hiển thị mà CTR < 1 % → viết lại title/meta; vị trí 11–20 → bổ sung nội dung, link nội bộ; một truy vấn trên ≥ 2 URL → trùng ý định; đăng ≥ 56 ngày → xem lại 8 tuần (ngày đăng đọc từ `posts.ts` bằng regex; tăng `updatedAt` sau khi xem lại) | Hằng tuần |
| `gsc_sitemaps` | Có | Liệt kê sitemap (lỗi, cảnh báo), `--submit` để gửi lại | Sau deploy đổi URL |

Chạy từ gốc repo: `python -m scripts.seo.<tên>`. `seo_live_check` chỉ dùng thư viện chuẩn.

## Cài đặt một lần (chủ sở hữu)

1. **Search Console**: thêm property **Domain** `app-juli.com` (xác minh bằng bản ghi TXT DNS
   trên Cloudflare). Property Domain bao gồm cả `demo.` và `ops.`, nên một property vừa theo dõi
   trang chính vừa chứng minh subdomain đã ra khỏi index.
2. **Gửi sitemap**: Search Console › Sitemaps › `https://app-juli.com/sitemap.xml`
   (hoặc `gsc_sitemaps --submit`).
3. **Google Cloud Console**: tạo project → bật *Google Search Console API* → OAuth consent
   screen (Internal / Testing, thêm e-mail của bạn) → Credentials › *OAuth client ID* loại
   **Desktop app** → tải JSON về `~/.config/juli-seo/client_secret.json`.
4. Thư viện: `pip install -r scripts/seo/requirements.txt` (venv riêng là tốt nhất).
5. Lần chạy đầu mở trình duyệt để đồng ý; token lưu ở `~/.config/juli-seo/token.json`
   (quyền 600). API chỉ nhận OAuth 2.0; scope chỉ đọc là đủ, trừ `--submit`.

Dữ liệu: `~/.local/share/juli-seo/gsc.sqlite`, báo cáo `~/.local/share/juli-seo/reports/`.
Đổi bằng biến môi trường `JULI_SEO_DATA`, `JULI_SEO_CONFIG`, `JULI_GSC_SITE`,
`JULI_GSC_CLIENT_SECRET`.

## De-index subdomain — quy trình

1. Deploy P33-A: demo / ops trả `X-Robots-Tag: noindex, nofollow` + meta robots noindex.
   **Không** chặn chúng trong robots.txt — trang bị chặn sẽ không được tải, Google không thấy
   noindex và URL có thể nằm lại trong index.
2. `seo_live_check` phải báo `ok [noindex]` cho mọi URL của demo / ops.
3. (Nhanh hơn, tuỳ chọn) Search Console › **Removals** › New request › *Remove all URLs with
   this prefix* `https://demo.app-juli.com/` — ẩn ~6 tháng trong lúc Google thu thập lại và
   thấy noindex. API **không** có chức năng này.
4. `gsc_index_audit` hằng tuần: URL demo / ops chuyển sang NEUTRAL với
   `BLOCKED_BY_HTTP_HEADER` / `BLOCKED_BY_META_TAG`; `gsc_report` mục 2 về 0.

## Giới hạn API cần nhớ (tài liệu Search Console API, đọc 2026-10-15)

- Search Analytics: 1.200 truy vấn / phút / site; tải nặng nhất khi nhóm theo cả page và query
  và khi khoảng ngày dài — vì vậy `gsc_pull` kéo **1 ngày mỗi lần**. Tối đa 25.000 dòng / trang,
  50.000 dòng / ngày / loại tìm kiếm. Dữ liệu chốt sau 2–3 ngày; ngày không có dữ liệu bị bỏ qua.
- URL Inspection: 2.000 / ngày và 600 / phút cho mỗi site; chỉ trả trạng thái của bản trong
  index (không kiểm tra live URL).
- Khác (sitemaps, sites): 20 / giây, 200 / phút cho mỗi người dùng.
- Lỗi "quota exceeded": chờ 15 phút; client tự lùi lại khi gặp 429 / 5xx.

## Lịch gợi ý (cron trên máy chủ hoặc máy của bạn)

```cron
# 07:10 hằng ngày: kéo dữ liệu đã chốt
10 7 * * *  cd ~/juli-fasttrack && .venv-seo/bin/python -m scripts.seo.gsc_pull
# 07:30 thứ Hai: inspection + báo cáo tuần
30 7 * * 1  cd ~/juli-fasttrack && .venv-seo/bin/python -m scripts.seo.gsc_index_audit; .venv-seo/bin/python -m scripts.seo.gsc_report
```
