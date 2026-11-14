# P100 — Chrome check after deploy 20261114T2054Z (c822225c)

Production, 2026-11-15. Tick each line. Write down anything that fails, with the screen and the
value seen, before moving on. Edge cases go to `fasttrack/p64-e2e-edge-cases.md`.

**Rules for the check:** read only. Nothing is saved in Seller Centre. On Juli, ORY may be
changed only through Juli itself (the owner allowed this). Never touch Fujiwa. The sample shop
(`bf06da92…`) must never show a Connector or a stock alert.

---

## Session 1 — ORY on app-juli.com (seller account, shop "ORY · Shopee")

### 1. Tổng quan › Shop (`/tong-quan?ky=90d`)
- [ ] "Cập nhật" shows today. "Số liệu đến dd/mm" shows above the KPIs and above "Luồng".
- [ ] No negative "Đơn" in any row, and Thẻ sản phẩm shows no −24 any more.
- [ ] The GMV split (Organic / Quảng cáo / Tiếp thị liên kết) adds up to 100 %, and its GMV equals the KPI GMV.
- [ ] DVHT Sản phẩm and DVHT Shop+ both show Lượt xem. Their CTR and CTOR show a value whenever
      the period has ad clicks (2026-11-15: still "—", **to check**).
- [ ] The "Quảng cáo" KPI and the DVHT rows show the "Báo cáo DVHT" tag. Total ads cost is read
      from one source only, with no double count of the "all" row.
- [ ] After the Connector's first run, "Số liệu đến" moves past 04/11 (orders) and 09/11 (traffic).

### 2. Tổng quan › Sản phẩm (`/tong-quan?ky=90d&cap=san-pham`)
- [ ] Product names are the shop's real names, never "Sản phẩm đã xoá" or a bare id.
- [ ] Item status reads "Đang hoạt động", not "1".
- [ ] **Stock panel** (after the first 06:30 read): every variation shows its SKU code in the row title,
      the stock, "còn ~n ngày", and "Bán ~n/tuần" when it sells under 1 per day.
- [ ] The "Theo dõi" switch: turning one SKU off removes it from the next email and hides its
      cards. Turn it back on afterwards.

### 3. Phân tích
- [ ] Channel-split numbers on Phân tích equal Tổng quan for the same period and product (GMV, orders, views).

### 4. Quyết định / Đề xuất
- [ ] After Ops generate + publish, ORY has new Shopee cards, and none has a negative P50 profit.
- [ ] Every card's number matches its detail (one card, one number).

### 5. Juli Connector 0.3.19 (the Chrome logged in to ORY's Seller Centre)
- [ ] `chrome://extensions`: Juli Connector **0.3.19**, enabled, no "Errors" button.
- [ ] Popup: paired to ORY, last sync time is today.
- [ ] Seller Centre › Phân tích bán hàng is not the only page that syncs: product, ads and orders
      data also land, and Juli's "Số liệu đến" moves forward.
- [ ] 06:30 GMT+7: the stock read runs by itself. Ops check:
      `shopee_stock_history` has rows with `read_at` today.

### 6. Stock alert email (07:00 GMT+7, automatic)
- [ ] Preview stage (status `preview`): one email to lienhe@app-juli.com, subject
      `[Juli - Báo cáo tồn kho] … · 15/11`.
- [ ] Groups "Mới hôm nay" / "Đang sắp hết" / "Đã hết hàng"; each row carries the SKU code,
      stock, days left (≤ 7) or "trước khi thẻ kết thúc".
- [ ] No row for a SKU with no order in 30 days, an inactive listing, or 0 stock for more than 7 days.
- [ ] "Mở Juli" opens Tổng quan › Sản phẩm on that SKU's product.
- [ ] Footer: stock read time + an unsubscribe link → `/huy-email` confirm page (do not confirm on the Ops address).
- [ ] No read in the last 48 h → the "chưa đọc được" email instead (expected only if the Connector missed 06:30).
- [ ] Owner checks the rows against Seller Centre stock → then `--status on --days 7`.

### 7. Mobile (390 px)
- [ ] Tổng quan, the stock panel and the email all read without horizontal scrolling.

---

## Session 2 — sample shop "Dữ liệu mẫu" (`bf06da92-8988-450a-ad84-86d88367efaa`, reviewer pin)

Run after `python -m scripts.sample_shop --reset … --yes` (step 5). Sign in as the sample-shop reviewer.

### 1. Entry and banner
- [ ] `/` goes to Tổng quan (not the TikTok Trang chủ). No 403 on `/tong-quan`.
- [ ] The banner says "Dữ liệu mẫu". The word "demo" appears nowhere on screen.

### 2. No Juli Connector anywhere (S2-D4)
- [ ] Tổng quan, Phân tích, Sản phẩm, Quyết định, Thực hiện: no Connector bar or status, and no "qua Juli
      Connector" caption.
- [ ] Thực hiện: no "Connector điền" / "Điền bằng Connector" / "Mở Seller Centre" / "Mở trang sửa
      sản phẩm" / sheet links, and no fill-queue checklist. "Đã làm" still works on a "Chờ điền" row.
- [ ] Product page and product tabs: no Connector link or source caption.

### 3. No stock alert (owner rule)
- [ ] Tổng quan › Sản phẩm: no stock panel and no "Theo dõi" switch.
- [ ] (Ops) `stock_alert_status.py --shop bf06da92… --show` says `status=off`, and no email goes out for this shop.

### 4. Data after the reset (S2-D3/D4)
- [ ] Every product image shows (`/sample-shop/<sku>.svg`). No broken image.
- [ ] Ads per product are not 0 (Quảng cáo / ROAS thực tế have values).
- [ ] HN-KLD costs 85.000đ.
- [ ] At least one voucher card (`min_spend_voucher`, HN-TDR 10.000đ from 200.000đ) shows with a positive P50.

### 5. Quyết định as a reviewer (S2-D2)
- [ ] Tự tạo shows every kind and tool tab. Combo, Deal Sốc, a DVHT campaign and Affiliate all evaluate.
- [ ] Duyệt / Thực thi are simulated: the status moves, and nothing reaches Shopee.
- [ ] Tiêu đề: seeded titles, plus "Viết lại bằng AI (còn 1 lần)" once per product. A second try is refused.
- [ ] Writes stay on the sample shop. ORY and Fujiwa are never reachable from this account.

### 6. Mobile (390 px)
- [ ] The four screens read without horizontal scrolling.

---

## Results
| Date | Session | Section | Pass/Fail | Note |
|---|---|---|---|---|
| 2026-11-15 05:30 | 1 | 1 Tổng quan › Shop | partial | "Số liệu đến" shows (orders 04/11, traffic 13/11); no negative Đơn; DVHT views on both rows; 90 d split 41/42/17 = 100 % and = KPI GMV. **Fail:** 30 d Organic / Quảng cáo GMV "—", so the split is only Affiliate 9 %. **Fail:** DVHT CTR / CTOR "—" while Quảng cáo › Theo chiến dịch has clicks (209, 146, 47 …). |
| 2026-11-15 05:30 | 1 | 2 Sản phẩm | partial | Real names everywhere, product page "● Đang hoạt động", stock 26 (Connector read 14/11 12:48). **Fail:** list footer says "14 sản phẩm không có đơn trong kỳ" while 5 of 14 have orders (should be 9). Stock panel not yet (no 0.3.19 read). |
| 2026-11-15 05:30 | 1 | 3 Phân tích | pass | 30 d: Trang shop 345.220, Video 0, DVHT SP 9,57 tr, Shop+ 210.600, Affiliate 1,21 tr, GMV ▼35 % = Tổng quan. |
| 2026-11-15 05:30 | 1 | 4 Quyết định | fail | 1 open card (Voucher đơn tối thiểu, Combo găng tay) shows Δ lợi nhuận −139.442đ – −89.342đ (fully negative), from before the P50 filter. Withdraw it or regenerate in step 6. |
| 2026-11-15 05:30 | 1 | Quảng cáo (extra) | note | Chi phí theo tháng 11/2026 = 247.779đ, 2 đơn, while Theo loại (15/10–13/11, 30/30 days) = 2,79 tr: Nov months look short of the daily rows. |
| 2026-11-15 05:30 | 1 | 5 Connector, 6 Email | pending | chrome://extensions is not reachable by Claude; email at 07:00. |
| 2026-11-15 06:00 | 2 | 1 Entry and banner | pass | `/` → `/tong-quan`, no 403; "Dữ liệu mẫu" banner + "Tài khoản đối tác · … không gửi tới Shopee"; no "demo" in page text. |
| 2026-11-15 06:00 | 2 | 2 No Connector | pass | Tổng quan (Shop, Sản phẩm), Phân tích, Sản phẩm list + product page, Quyết định (Đề xuất, Thực hiện): no "Connector", "Điền bằng", "Mở trang sửa", fill links. Thực hiện steps read "Bạn điền · Bạn lưu · Khớp Seller Centre"; "Đã làm" shows on the "Chờ điền" row. Note: product page keeps "nguồn: Seller Centre" captions (allowed). |
| 2026-11-15 06:00 | 2 | 3 No stock alert | pass (UI) | No stock panel, no "Theo dõi", no stock testids on Tổng quan › Sản phẩm. Ops `--show` for bf06da92 still to run. |
| 2026-11-15 06:00 | 2 | 4–5 | waiting | Page still "Cập nhật 12/11 16:30": the `--reset --yes` has not landed. |
| 2026-11-15 06:40 | 2 | 4 Data after reset | partial | Reset landed (Cập nhật 14/11 16:30). HN-KLD 85.000đ, `/sample-shop/hn-kld.svg` loads, DVHT cost per product 725.800đ (not 0). **Fail:** all 7 Đề xuất cards read "Chưa ước tính được". DB: 3 `min_spend_voucher` + 2 `price` cards are `sent` and estimable, but each product's queue-1 card is a `no_spec` / `not_estimable` kind (combo, title, cover, commission, review voucher, ads purpose), so the estimable cards never show. Ranking: an estimable card should outrank a not-estimable one in `product_queue`. |
| 2026-11-15 06:40 | 2 | 5 Quyết định as reviewer | pass | Tự tạo: tool tabs Từng phương án / Combo nhiều SKU / KOL / DVHT; step 2 lists every strategy; Voucher 5k/100k evaluates (Δ lợi nhuận −30.215đ, Δ GMV +138.539đ, ROI 2,7; not saved). Tiêu đề: 3 seeded titles + "Viết lại bằng AI (còn 1 lần)" (not pressed). Duyệt V1 of "Đổi hoa hồng chiến dịch mở" → "Đã duyệt · chờ làm", no error, no Connector. |
| 2026-11-15 06:40 | 2 | 3 (Ops half) | pending | `stock_alert_status.py --shop bf06da92… --show` output not received. |
| 2026-11-15 06:40 | 2 | 6 Mobile | not run | Window will not resize. |
| 2026-11-15 05:30 | 1 | 7 Mobile | not run | The Chrome window would not resize (stays 1470 px); check on a phone or in DevTools device mode. |
