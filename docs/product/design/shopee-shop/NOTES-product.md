# Shopee shop · Sản phẩm, thẻ what-if, nhập thông số (ghi chú thiết kế)

Owner-approved direction 2026-11-03 (broad → precise). Artboards follow the Phân tích / Quyết định conventions:
`.dc.html` = HTML with inline styles plus a `renderVals()` script that drives every state; Be Vietnam Pro;
canvas palette of `phan-tich/` and `quyet-dinh-flows/` (the hex values there are the `colors_and_type.css`
tokens: `#b0386a` pink-text, `#c2306d` primary action, `#146c2e` / `#a3222f` / `#8a4b00` / `#1d4f91` status text);
no new colours. Synthetic household-goods shop (combo "Bộ vệ sinh bếp 5 món"), illustrative numbers, placeholder
images are colour blocks. Worked example of the context file is reproduced exactly (giá sàn 121.176đ / 181.979đ,
giảm tối đa 9,0 % = 18.000đ, A 58.500đ 30,8 % / 21.700đ 11,4 %, B 54.250đ 29,3 % / 17.450đ 9,4 %, hoà vốn ≥ 3 đơn).
The data in the file is computed with the shop formula, not typed per state.

## Artboards

| Artboard | What | Where in app | States |
|---|---|---|---|
| `SanPham.dc.html` (1280) | Product page: cover + gallery with "‹ N phiên bản ảnh" stepper, title with char count /120 and key-list highlighting (chính / phụ / ngoài 100 ký tự), Mã SP + copy, SKU, category, status, group, Ưu tiên, links; Giá / Tồn kho / Uy tín blocks each with a freshness line (stock shows "Cũ 3 ngày"); variation table; 5-number strip; sub-tabs | Sản phẩm › [product] | Image version 1–3; copy done; select variation (drives Chi phí tab); tabs below |
| ↳ Hiệu suất | KPI chain by period (7 / 30 / 90 ngày), daily chart (GMV / lượt xem / biên) with ◆ markers of executed cards and their T+7 / ngày 14 result | tab | period, series |
| ↳ Nguồn | Traffic table on the five flows (Thẻ sản phẩm ngoài Trang shop, Trang shop, Live, Video, Tiếp thị liên kết; Thẻ sản phẩm opens into six children) and price-lever table, each = 100 %; source × lever cross-table with row and column sums; "Quảng cáo (trong đó)" overlay with purpose badges (Chuyển đổi, Hiển thị, Lượt vào shop, Ra mắt) judged by their own metric; "→ đề xuất" chip per row | tab | overlay off / on |
| ↳ Từ khoá | Key list: max 5 Chính + Phụ / Thương hiệu / Loại trừ; volume + trend, difficulty, CPC, position in title, our rank, market median vs ours vs floor, coverage %, links to title / ad / price cards; limit state "Đã đủ 5 từ khoá chính" | tab | 5/5 (limit), Hạ xuống Phụ → 4/5 and "Nâng lên Chính" unlocks; "+ Thêm từ khoá chính" at 5/5 shows the limit message |
| ↳ Chi phí & giá sàn | Per-order waterfall (niêm yết → voucher → khách trả → phí sàn → giá vốn → đóng gói → quảng cáo → hoa hồng → lợi nhuận) for tự nhiên and từ QC; absolute and operating floor with formulas, giảm tối đa, price gauge, verdict | tab | 4 variations; BEP-S3 = "Chưa có giá vốn" empty state pointing to Cài đặt |
| ↳ Lịch sử | Append-only timeline: card events, whatif_adjusted, detected changes (title text diff, image before→after, price before→after), input versions | tab | filter Tất cả / Thẻ / Thay đổi phát hiện / Thông số |
| `SanPhamMobile.dc.html` (390) | Header + Giá on top, 5 số / Tồn kho / Uy tín / Phiên bản collapsed, scrolling sub-tab bar, condensed tabs | Sản phẩm, mobile | block open/closed, same tab states |
| `CardWhatIf.dc.html` (920) | Voucher card with what-if: options A / B / C and every contract §7 input (giá trị in đ or % with a max, đơn tối thiểu, số lượng voucher, giới hạn mỗi người, số ngày) with Q, u and the used count shown; every number recomputes from the inputs (used = min(Q × u, số lượng)); floor check, ad-order margin warning, spend cap, break-even, "Chắc chắn" vs "Dự kiến" 5 numbers (VND and %), Lý do + "Xem phân tích ›", Phê duyệt / Yêu cầu chỉnh / Từ chối (ADR-107 reasons dialog) | Quyết định › Đề xuất (and Đo lường) | Mặc định A → C · Kéo về B (ad orders 9,4 % warning) · Chạm giá sàn 25k (red, approve locked, "Đặt về mức tối đa") · Đã phê duyệt (whatif_adjusted note if changed) · Kết quả ngày 7 · Chốt 28 ngày (good / bad example, Giữ C / Hoàn tác về A with revert reasons) · sliders are live in the first three |
| `CaiDatImport.dc.html` (1040) | Download pre-filled template, upload, validation (unknown SKU, giá vốn ≥ giá, giá vốn trống, ngoài khoảng), diff cũ → mới with consequences, apply with required reason → v4, version list per SKU with Khôi phục (new version copying the old one), banner "N đề xuất sẽ được tính lại", Mục tiêu sheet | Cài đặt › Thông số shop | 6 tabs: Mẫu và tải lên · Kiểm tra · So sánh · Áp dụng (before / after) · Phiên bản (confirm, restored) · Mục tiêu (warning row) |

Demo-only affordances (not product): the scenario pills in CardWhatIf, "Kết quả tốt / xấu", the file picker button.

## Links to the parallel branch (same folder)

`TongQuan*.dc.html`, `Ranking*.dc.html`, `PhanTich*.dc.html` and `README.md` are written on the other branch;
filenames are not known here, so links are by role:
- Card "Xem phân tích ›" opens the Ranking for the card's metric × source with the row highlighted (contract §8); "Mở sản phẩm ›" opens `SanPham.dc.html#id=<product>&tab=ng`.
- Ranking rows' "→ đề xuất" chip leads to `CardWhatIf.dc.html`; the Nguồn rows here use the same chip.
- Missing giá vốn → `CaiDatImport.dc.html`.

## Decisions to approve

1. Chart colour: `design.md` forbids brand pink in charts, but `PtProduct` bars are pink. Here bars use
   `--chart-neutral`, diamonds are ink. Say if the pink of PtProduct should win.
2. Approve is locked below the operating floor, with a one-tap "Đặt về mức tối đa". No override path drawn.
3. Dòng lỗi in an import do not block the valid rows (shown as "Tiếp tục với 38 dòng hợp lệ").
4. The 5-number strip uses the contract §5 definitions (one function shared with Tổng quan and the card); ② = ΔGMV ÷ Δchi.
5. What-if "Chắc chắn" assumes buyers behave as in the last 30 orders (Q, u = 100 % shown); ad orders = 30 % of orders for the margin. ② appears only in "Dự kiến"; "Chắc chắn" shows the break-even extra orders. Giới hạn mỗi người is an input that cannot be checked from the data and changes no number (contract §9).
6. Keyword limits: 5 Chính hard cap; Thương hiệu and Loại trừ do not count.
7. Names: approver shown as "Quản lý shop"; no real client names or data.

## Open questions

- Is the ad-share (30 %) and the seller's voucher budget cap (500.000đ/tháng, drawn in the spend line) a field in the
  Mục tiêu sheet? Today the sheet has only the daily ad budget cap.
- Should "Yêu cầu chỉnh" carry the slider values (drawn: yes) or a free note only?
- At ngày 28, when result is bad, does Juli propose revert only, or also a new what-if card?
- Keyword source is owner-collected (ADR-119); how does the seller add a keyword (typed vs picked from the data)?
- Market median price per keyword compares a combo to single items for broad keywords; a "cùng nhóm giá" filter may be needed.
- Image versions come from detected changes; is a restore of an older image ever offered, or view only?
- Mobile: Chi phí waterfall shows two columns at 390 px; is a swipe between tự nhiên / QC preferred?

## How these were checked

Each file was rendered headless (Playwright) with a small dev-only runtime that implements `sc-if`, `sc-for`,
`{{path}}` and `setState`; every state was captured, every button clicked once, no console or template errors.
Layout avoids `<table>` and inline SVG because of that runtime's parser limits; sliders are native range inputs.

---

## P91 (2026-11-04): thẻ theo sản phẩm, phiên bản, phương án thủ công, kế hoạch

Artboards and decisions: see the P91 section of `README.md`. Notes that belong with the product screens:

- **Sản phẩm › Đề xuất** is a new sub-tab between Nguồn and Từ khoá. It lists every open card of the product (not only #1), grouped by family; the product's Quyết định card is the one marked `#1 · Đang ở Quyết định`.
- **Thẻ có phiên bản** replaces the A/B/C option buttons of `CardWhatIf` when a card has 2–4 versions: the user picks a column, the sliders change that column only (`whatif_adjusted` is recorded for that version), and `Duyệt Vn` records `chosen_version`. A version that breaches the floor or the spend cap is drawn and marked, and never blocked: Duyệt opens a warning (gap in đ per SKU, amount over cap) with "Quay lại" / "Vẫn tiếp tục", and the acknowledgement is recorded on the card.
- **Tiêu đề**: 100 characters (counter `97/100`); above 100 the text is not saved and Duyệt is locked. Both versions of the drawn title card are under 100.
- **Card codes**: `JC-2611-0007`, versions `-V1…-V4`. Export to Excel is later; Ops shows a disabled "Xuất Excel · Sắp có".

### D-7 Measurement when changes run together (approved by the owner, 2026-11-04)

- Unit of measurement is the **product's change set**: every card of one product executed the same day is one set, measured against the product's baseline and compared with the plan's joint prediction for that product. Different products are separate sets; the plan's shop total is measured too (Σ predicted vs shop actual).
- Shop-wide cards are measured at shop level; product sets executed with them carry **"Kèm thay đổi toàn shop"**.
- Learning: a one-card set calibrates its change kind as today; a multi-card set calibrates the joint prediction and counts for each kind with weight 0,25, never as a clean sample.
- Executing on a product still being measured is allowed: the running measurement is cut that day. **≥ 3 days measured: result kept as "Đo được N ngày"** (lower confidence); **< 3 days: "Không kết luận"**. The confirm dialog lists the products whose measurement will be cut (drawn in `KeHoach.dc.html`, scene `confirm`; result chips in scene `ketqua`).
- Window (D-8): minimum 3 days, presets 7 / 14 / 28 and custom 3–90, per plan with a per change set override. The recommendation is the smallest preset whose detectable change is ≤ 30 %; drawn with a stand-in formula (≥ 45 % × √(7 ÷ N): 7 → 45 %, 14 → 32 %, 28 → 23 %), the real figure comes from `plan.py`.

### Open questions (product screens)

- Does the sub-tab show closed cards (đã bỏ qua / đã đo xong) behind a link, as drawn, or in a filter?
- Should the product page let the user reorder the queue by hand (drag), or is the score order final?
- A version with a floor breach: keep it visible and active (drawn, per the "never block" decision) or hide it behind "Xem thêm"?
