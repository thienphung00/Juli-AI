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
      `stock_history` has rows with `read_at` today.

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
| 2026-11-15 11:00 | 2 | 4 Queue after #2298 + reset | pass | Đề xuất opens with 3 `min_spend_voucher` cards carrying ranges (Nước rửa chén +12.742đ – +49.393đ, Túi rác −4.693đ – +22.732đ, Bình xịt −4.279đ – +8.602đ); q1 = voucher on …01/…03; …06 q1 = approved cover (in flight), voucher q2. |
| 2026-11-15 11:10 | 2 | 6 Mobile (390 px, same-origin iframe) | pass | Tổng quan (Luồng table scrolls in its card), Sản phẩm list, product page, Quyết định, Thực hiện: page scrollWidth 390, nothing past the edge. Minor: Sản phẩm list squeezed into a left column (S1 #2304 fixes), Thực hiện "1 thẻ" with 2 rows (#2304). |
| 2026-11-15 11:30 | 2 | 5 Tiêu đề | partial | Khăn lau: seeded 3 titles pass; "Viết lại bằng AI" once → gpt-5.4-nano, weak titles (keyword glued before old title; S1 drafts fix); 2nd try 403 `sample_llm_quota` (pass). Seeded set was replaced by the AI set → owner option A in db2b9848 (#2307). Keyword table "chưa tra": volumes pending the owner's shopeeanalytics upload. |
| 2026-11-15 11:30 | 2 | 5 Ảnh bìa | fail → built | Old Tự tạo cover = AI overlay only, 403 `sample_llm_off` dead end. Banner editor per design = #2305 (c4fcb89e); re-check after its deploy. |
| 2026-11-15 12:30 | 2 | A1 Voucher (Nước rửa chén) | pass | 5k/100k: Δ lợi nhuận −30.215đ, ΔGMV +138.539đ, Δ đơn +1, Chi phí 50.509đ, ROI 2,7. 15k/200k: +30.317đ, +801.701đ, +2,6 đơn, 111.600đ, ROI 7,2. Note: "Chi phí voucher 49.988đ" hint vs Chi phí 50.509đ on the same screen; "ROI" is ΔGMV ÷ chi phí, shown beside a loss. |
| 2026-11-15 12:30 | 2 | A2 Combo khuyến mãi | implausible | Nước rửa chén + Túi rác, Mua 2 −5% / Mua 3 −8%: −733.266đ, **ΔGMV +4.337.331đ with Δ đơn +1,6**, Chi phí 1.633.676đ, ROI 2,7, biên 15,9% → 10,7%. ΔGMV per extra order ≈ 2,7 tr. |
| 2026-11-15 12:30 | 2 | A3 Deal Sốc (Mua kèm) | pass | Main Nước rửa chén, add-on Khăn lau −20%: −128.885đ, ΔGMV +227.847đ, Δ đơn +0, Chi phí 174.712đ, ROI 1,3. Mua Để Nhận Quà not run. UX: the % field keeps a default (15) so typing appends ("1520"). |
| 2026-11-15 12:30 | 2 | A4 Chương Trình Của Shop | implausible | 10% on 500ml hương chanh (48 đơn/30 ngày, 59.000đ): −749.369đ, ΔGMV +181.302đ, Δ đơn +12, **Chi phí 995.058đ** (≈3× the variation's 10% of ~2,8 tr), ROI 0,2. |
| 2026-11-15 12:30 | 2 | A5 Giá bán + Flash sale | implausible (price engine, S1 review) | Giá +5% on hương chanh: **+299.919đ** (> +5% × all 88 units ≈ 260k), ΔGMV −195.167đ, −6,1 đơn. −5%: −339.333đ, +140.627đ, +6,2 đơn. Flash −15%, 2 h, 50 suất: **−40.616đ in 1 day**, ΔGMV +3.244đ, +0,6 đơn, "Không có chi phí thêm"; no "Trên giá sàn" line shown. Also on prod: JC-2611-0007 P50 +406k / ΔGMV −191k. |
| 2026-11-15 12:30 | 2 | A8 Mô tả | partial | AI draft off on the sample shop; a typed first line works → "—" with "Lưu ý: … thiếu phí hoặc giá vốn" (wrong reason: the product has costs; listing kinds have no estimate by design). |
| 2026-11-15 12:30 | 2 | A9 Hiển thị giá | fail (copy) | "Giá mỗi đơn vị: 59.000đ" for a 500ml bottle (no per-100 ml price); result "—" with the same wrong "thiếu phí hoặc giá vốn" note. |
| 2026-11-15 12:30 | 2 | A10 Phân loại / set | implausible | New "Combo 2 chai" 110.000đ ×2: +191.827đ, **ΔGMV +1.067.996đ with Δ đơn +3,1** (≈344k per extra order for a 110k set). |
| 2026-11-15 12:30 | 2 | A11 Dịch vụ hiển thị | partial | Strategy opens the DVHT tab. New single campaign, Nước rửa chén, 100.000đ/ngày, Shopee tối ưu: Δ "chưa ước tính được — cần chạy thử", Chi phí 3.000.000đ, hoà vốn +152 đơn. "Thông số chưa hợp lệ" when the prefilled budget is appended to (no field named). Edit of a running campaign not re-run (2026-11-13: evaluate 200). |
| 2026-11-15 12:30 | 2 | A12 Affiliate | fail (sample data, S2) | 10% / 15% + 3 mẫu: "—", "Chưa biết hoa hồng hiện tại của sản phẩm này" (sample shop has TTLK GMV 1,57 tr but no current commission); Chi phí 243.000đ shown. |
| 2026-11-15 12:30 | 2 | A13 Tool tabs | partial | Combo nhiều SKU: table of 6 options, **Giá column empty**, pack unit "hộp" for bottles, "10 hộp – Combo 3 chai" offered. KOL: "① Chọn KOL" with no KOL (sample data, S2). Switching tool tabs resets Từng phương án to step 1. |
| 2026-11-15 12:40 | 2 | A14–A15 Lưu → Kế hoạch | pass | Voucher 15k/200k → Lưu → JC-2611-0019 (sent, q1). Card range −5.600đ – +72.000đ; Thêm V1 vào kế hoạch → plan row −5.607đ – +71.951đ = card. Notes: V1 labelled "Juli đề xuất" on the seller's own card; "Giảm giá % GMV niêm yết Hôm nay 0,0%" though a voucher runs; confirm dialog says 28-day window vs 30-day plan row; empty plan shows "Hiện tại —". |
| 2026-11-15 12:45 | 2 | A16 Duyệt → Thực hiện | **fail (S2-D4)** | Duyệt kế hoạch → KH-2611-001, Thực hiện · 2, steps "Đã duyệt · Bạn điền · Bạn lưu · Khớp Seller Centre". **"Đã làm" on the Thực hiện row does nothing for a voucher**: POST …/executed 422 `voucher_id is required`, no message shown. On the card page "Đã làm" asks for "Mã voucher trên Seller Centre"; a sample code worked → "Đã ghi nhận". The card then stays `da_dien` (3/4): with no Connector read-back the sample shop never reaches "Khớp" → never Đo lường. |
| 2026-11-15 12:50 | 2 | A17 Đo lường | **fail** | JC-2610-0001 (measured voucher): "Khoảng −44.777đ – −39.589đ, **Thực tế −2,6778855896141057e+21đ**", AOV ▲32 %. API: lift p50 5e-18 (≈0) → actual blows up. JC-2611-0002 title: Đang đo 6/7, Khoảng — – —. |
