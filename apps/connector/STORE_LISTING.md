# Juli Connector — Chrome Web Store listing (DRAFT)

Visibility: **Unlisted** (pilot shops get the link), Public later (D31.4).
Category: Productivity / Workflow & planning. Language: Vietnamese (primary), English.

## Name

Juli Connector

## Short description (≤ 132 chars)

Gửi số liệu Seller Centre (Shopee) của chính shop bạn sang Juli để nhận phân tích và đề xuất tăng doanh số.

## Detailed description

Juli Connector kết nối shop Shopee của bạn với Juli (app-juli.com).

- Đọc các số liệu Seller Centre đã hiển thị cho chính shop bạn: doanh số theo
  nguồn (Thẻ sản phẩm, Video, Live, Tiếp thị liên kết, Dịch vụ Hiển thị), lượt
  hiển thị, lượt nhấp, đơn hàng, lượt truy cập shop.
- Gửi số liệu theo ngày sang tài khoản Juli của bạn để Juli phân tích và đề xuất.
- Mỗi ngày một lần, khi bạn đang mở Seller Centre, tự đồng bộ số liệu hôm qua với
  tốc độ thấp. Lần đầu kết nối, lấy thêm số liệu 30 ngày trước, từng ngày một.
- Không lưu mật khẩu. Kết nối bằng mã dùng một lần tạo trong Juli; bạn có thể ngắt
  kết nối bất cứ lúc nào.

## Single purpose statement

Send the signed-in seller's own Shopee Seller Centre performance data (traffic,
sales and conversion numbers of their shop and products) to their Juli account,
where Juli analyses it and suggests improvements.

## Permission justifications

| Permission | Why |
|---|---|
| Host `https://banhang.shopee.vn/*` | Read the responses Seller Centre's own data pages load for the seller's shop (four `/api/mydata/...` endpoints), and repeat those same requests once a day while Seller Centre is open (plus, once after linking, one request set per day for the last 30 finished days). No other site is accessed. |
| Host `https://api.app-juli.com/*` | Send the numbers to the seller's Juli account and read sync status. |
| `storage` | Keep the Juli access token (not a password), per-dataset sync status, the 30-day backfill progress and a small retry queue on this device. |
| `alarms` | Schedule the once-a-day sync (with a random start) without a background page. |

Not requested: `tabs`, `cookies`, `webRequest`, `scripting`, `<all_urls>`, remote
code. Content scripts are bundled; the extension pages' CSP is `script-src 'self'`.

## Data usage disclosures (Privacy practices tab)

- Collects: "Website content" (the seller's own shop / product performance
  numbers shown in Seller Centre). Not collected: personally identifiable
  information, health, financial / payment information, authentication
  information, personal communications, location, web history, user activity.
- Certifications: not sold to third parties; not used or transferred for
  purposes unrelated to the single purpose; not used for creditworthiness or
  lending.
- Privacy policy URL: https://app-juli.com/privacy (publish `PRIVACY.md`'s text
  there or as a section of it before submitting).

## Assets still needed

Icons 16 / 48 / 128 px, at least one 1280×800 screenshot (popup + Seller Centre),
a 440×280 small promo tile.
