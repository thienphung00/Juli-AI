# Shopee shop — Tổng quan, Xếp hạng, Phân tích (artboards)

Draft for owner approval, 2026-11-03. Same conventions as `../phan-tich/`: each `.dc.html` is HTML with
inline styles plus a `renderVals()` script that drives every state (palette, radii, font sizes and the
state pattern are copied from `PtProduct.dc.html` / `PtMobile.dc.html`). Numbers are **illustrative**, from a
synthetic household-goods shop (gloves, dish soap, loofah, food bags, aluminium foil). No real shop data.
Number format: `1.234.567đ`, `3,66%`.

Every artboard opens in its default state. To open another state directly, append `#scene=<name>` to the file
(the on-page "Xem trạng thái" strip does the same and is a demo-only affordance, not a product feature).

## Artboards (this folder)

| Artboard | What | Where in the app | States (`#scene=`) |
|---|---|---|---|
| `TongQuan.dc.html` (1280) | Top strip (GMV, Lượt xem, CTR, CTOR, AOV, Biên cuối); "5 con số chính" (one definition everywhere, contract §5) plus chi marketing / ngày vs trần; **shop-profit block** (lợi nhuận, biên on buyer_paid, QC không gắn sản phẩm, cost coverage with the partial-margin rule); period picker; GMV chain and the **five traffic flows table** (Thẻ sản phẩm ngoài Trang shop · Trang shop · Live · Video · Tiếp thị liên kết, each with Lượt xem, CTR, CTOR, AOV, GMV, % GMV, Biên; a "Chênh lệch nguồn" row; Quảng cáo as a dashed "trong đó" row per flow; Thẻ sản phẩm drills into six children); product × source matrix on the same five flows | Tổng quan | `default` (cost coverage 99,4 %, profit in đồng hidden); `expanded` (XM-003 open into its 5 flows + Chênh lệch nguồn + Quảng cáo overlay, Thẻ sản phẩm children open; "Theo ưu đãi" shows the 4 price levers); `sortbien`; `stale`; `full` (100 % cost coverage: shop profit shown in đồng) |
| `TongQuanMobile.dc.html` (390) | Same content: 2-column KPI tiles, five numbers as stacked cards, tree as accordion, products as cards with 3×3 number grid | Tổng quan, mobile | same four |
| `Ranking.dc.html` (1280) | What a KPI click opens. Context cell, KPI tabs, source chips (Tất cả · the five flows Thẻ sản phẩm / Trang shop / Live / Video / Tiếp thị liên kết · Quảng cáo (trong đó) · Không ưu đãi / Voucher / Khuyến mãi / Combo; Thẻ sản phẩm has a sub-row with its six children), "Xếp theo" switch (₫ GMV/ngày, ₫ lợi nhuận/ngày, Biên cuối, Số đơn, AOV, % giảm giá), Kéo xuống / Kéo lên, rows with ₫/ngày, prior → last, quantity, Rõ / Tham khảo, "→ đề xuất" chip, closing rows that add up to the cell | Tổng quan › bấm chỉ số; also from Phân tích and the card | `ctr_all`; `ctor_voucher` (voucher rows); `gmv_ads` (campaign rows with purpose badges Hiển thị / Lượt vào shop / Chuyển đổi / Ra mắt, judged by their own measure, overlay note); `views_search` (keyword rows); `gmv_kol` (KOL rows); `back` (CTOR × Đề xuất, row XM-003 highlighted + "Vừa quay về từ thẻ" banner, from card `c_xm_disc`). Product rows work for every KPI (GMV, Lượt xem, CTR, CTOR, AOV, Biên cuối, % giảm giá, Số đơn) × every flow, child and lever via `#kpi=ctr&src=live`; only Lượt xem / CTR / CTOR × a price lever is not splittable and shows a note |
| `RankingMobile.dc.html` (390) | Same, rows as cards, chip rows scroll horizontally | Ranking, mobile | same six |
| `PhanTich.dc.html` (1280) | Critical list ranked by ₫ at stake. Each item = product/segment × source × KPI, Hiện trạng, deviation as a small band chart (grey band = normal band, black tick = target / floor / break-even / shop median, dot = now), cause as a funnel-stage chip row plus one sentence, ₫/ngày and ₫/tháng, links to the card and to Ranking. Collapsed group "Trong dải bình thường" (incl. sale-day noise) | Phân tích | `default`; `ok` (group open); `bien` (filtered to Biên và giá sàn). Values, ₫/ngày and floors come from the shared dataset; each item links to a registry card (`CardWhatIf.dc.html#card=<id>`) and to the Ranking row with the same ₫/ngày |

Closing-row rule is kept from ADR-109 d.5: listed rows + "3 sản phẩm ít đơn" + "Các sản phẩm khác" + "Thay đổi cơ cấu" = the cell figure, and
the "Kéo xuống / Kéo lên" views carry a line for the opposite-sign rows so the total still adds up.

## Navigation between artboards

```
Tổng quan  KPI tile / tree node / matrix cell ──► Ranking.dc.html#kpi=<k>&src=<s>
Tổng quan  "→ đề xuất" chip ───────────────────► Ranking (row focused) / CardWhatIf.dc.html (card)
Phân tích  "Xem xếp hạng ›" ───────────────────► Ranking.dc.html#kpi=..&src=..&focus=<row>
Phân tích  "Xem đề xuất ›" ────────────────────► CardWhatIf.dc.html (card)
Ranking    row (open) "Mở sản phẩm ›" ─────────► SanPham.dc.html#id=<sku>&kpi=<k>&src=<s>&from=ranking
                                                 (Sản phẩm opens with KPI + source preselected)
SanPham    "‹ Xếp hạng" back ──────────────────► Ranking.dc.html#...&focus=<sku>   (row highlighted 3 s)
Ranking    row "→ đề xuất" chip ───────────────► CardWhatIf.dc.html#from=ranking&row=<id>  (the card)
Card       "Xem phân tích ›" ──────────────────► Ranking.dc.html#kpi=..&src=..&focus=<row>
                                                 (row highlighted; banner "Vừa quay về từ thẻ" + "Về thẻ ›")
Ranking    "‹ Tổng quan" (or "‹ Sản phẩm" when #from=ranking-origin is a product page)
```

All nine artboards now read one shared synthetic dataset (the `SHARED DATASET v1` block, byte-identical in every file; edit it once and copy it). Link parameters are `kpi`, `src` (all · the_san_pham · trang_shop · live · video · lien_ket · ads · none · voucher · promo · combo), `sub` (Thẻ sản phẩm child), `focus`, `from`, `card`, `id`, `tab`. The full link table and the equality checks are in `VERIFY.md`.

## Decisions made while drawing (please approve)

1. Amounts use `1.234.567đ` everywhere, not the compact `3,6 tr ₫` of the older Phân tích artboards. Wide table cells
   fit at 12 px; chips still use `+1.500.000đ/tháng`. Say if the matrix should switch to compact.
2. Two source dimensions in the matrix, switched by "Theo lưu lượng / Theo ưu đãi". Under price levers, views / CTR /
   CTOR are not split (shown "—"); ① and ② per source are "—" for traffic rows too.
3. The five numbers (heading "5 con số chính") follow `fasttrack/contracts/p90-metrics.md` §5 and are one function (`DS.fiveOf`) used by Tổng quan, Sản phẩm and the card: ① (khuyến mãi + voucher + combo) ÷ GMV at list price; ② ΔGMV ÷ Δchi with chi = QC + voucher + khuyến mãi + combo + hoa hồng ("x đ / 1đ chi", red below 1đ, "giảm chi" when Δchi ≤ 0);
   ③ profit ÷ buyer_paid ("trên X % doanh thu có giá vốn" below 100 % coverage, profit in đồng only at 100 %); ④ số đơn xác nhận; ⑤ GMV ÷ số đơn.
4. Cell colours: red when worse by 8% or more, biên below target (10%), % giảm up 3 điểm or more, or chi thêm > thu thêm; green when better by 8% or more. Always paired with ▲/▼ and text.
5. Chart marks are neutral grey (no pink, per `design.md`). Pink is only the neutral-subject thumbnails/SKU chips and the selected/highlight state, as in the existing artboards.
6. Quảng cáo row sits under the sources as a dashed, italic "trong đó" row, never summed. In the ranking its rows are campaigns, each judged by its purpose (cost / 1.000 lượt xem, cost / lượt vào shop, ROAS vs break-even, budget cap + end date).
7. Tìm kiếm rows are keywords, shown under a sub-chip row of Tự nhiên; the source chip row has no separate Tìm kiếm chip.
8. Period picker changes only labels in the artboard (numbers stay); "Cửa sổ 11/11" compares with a same-length 9.9 window by default.
9. Phân tích deviation reference is one of: normal band, target, floor price / ROAS break-even, shop median. Sale-day noise goes to "Trong dải bình thường" using a sale-day band.

## Open questions

- Where does Phân tích's critical list sit relative to Quyết định cards: should "Xem N đề xuất ›" filter the cards to these items?
- Does the data-stale block block recommendations (copy currently says new cards are created only after data is fresh) or only warn?
- Ads cap tile: is the cap the per-day total ad budget from Cài đặt › Mục tiêu, or per campaign?
- Voucher / Khuyến mãi / Combo rankings for KPIs other than the drawn ones (CTOR for vouchers): confirm which KPI is meaningful per price lever (CTOR on "clicks of products with that voucher" is my assumption).
- Keyword rows depend on owner-collected data (ADR-119); freshness chip for that source is drawn only in the stale state.
- Confidence "Rõ" threshold: drawn as 100 orders in the period; real rule comes from `rankings.py`.

---

# P91 — đề xuất theo sản phẩm, phiên bản, phương án thủ công, kế hoạch (artboards)

Draft for owner approval, 2026-11-04 (spec: `fasttrack/contracts/p91-plan.md` D-1 … D-11). Same conventions as above. Nothing is built until the owner approves. All data is synthetic ("Shop mẫu gia dụng": Găng tay cao su A, Túi rác sinh học B, Miếng rửa chén C); no client or staff names. P91 artboards share a separate `P91 DATASET v1` block (byte-identical in the artboards) with one engine for voucher, combo and plan, so the same version shows the same numbers on every screen. It is not the `SHARED DATASET v1` of the P90 set; the two are not wired together yet.

| Artboard | What | States (`#scene=`) |
|---|---|---|
| `SanPhamDeXuat.dc.html` (1280) | Sản phẩm › new sub-tab **Đề xuất (8)**: every open card of Găng tay cao su A grouped by family (Tên/từ khoá/ảnh bìa, Quảng cáo, Khuyến mãi/giá, Voucher, Combo, Tiếp thị liên kết, Flash Sale/chương trình), or by queue order. Each card: code `JC-2611-0007`, queue chip (`#1 · Đang ở Quyết định`, `#2 · Xếp hàng` …), Δ lợi nhuận/tháng of V1, versions; "Xem phiên bản" opens V1…V4 rows with code `-V2`, Chắc chắn, range, "Chạm giá sàn" flag, "Mở thẻ ›". "+ Tự tạo phương án" entry point | view `Theo họ` / `Theo thứ tự hàng đợi`; per-card expand |
| `SanPhamDeXuatMobile.dc.html` (390) | Same, cards stacked | same |
| `CardVersions.dc.html` (1120) | Update of `CardWhatIf`: 2–4 versions as columns next to **Hôm nay**; rows ①…⑤, Chi phí, Δ lợi nhuận chắc chắn and dự kiến, giá sàn check, trần chi check; breach cells red and tagged "Chạm giá sàn" (buttons stay active: Duyệt opens a warning with each shortfall in đ and the amount over the cap, "Quay lại" / "Vẫn tiếp tục", and the card then shows "Đã xác nhận vượt giá sàn · <time>"); radio picks the version; what-if sliders (and the title box) act on the selected version only, "Về mặc định"; `Duyệt V2` / `Thêm V2 vào kế hoạch` / `Yêu cầu chỉnh` / `Bỏ qua`; "Tiếp theo cho sản phẩm này" strip; title card with live counter `97/100` (green), `>90` amber, `>100` red and Duyệt locked | `voucher` · `floor` (V3: breach + over trần chi, warning dialog, "Đặt về mức tối đa") · `approved` (V2) · `approvedV3` (approved after the warning, acknowledgement shown) · `planned` · `title` |
| `QuyetDinhHangDoi.dc.html` (1040) | Quyết định, one card per product; each shows code, "Tiếp theo cho sản phẩm này", "#1 · còn N thẻ xếp hàng". Bỏ qua / Thêm vào kế hoạch / Đã thực hiện (demo) replace the card at once with the product's next card ("Vừa lên thay thẻ …"). A product still being measured shows "Sản phẩm đang đo: còn N ngày" on the replacement | `default` · `skip` · `plan` · `done` (executed, measuring) · `measured` |
| `TuTaoPhuongAn.dc.html` (1280) | Builder + comparison. Change type (combo nhiều sản phẩm, mua kèm, quà tặng, voucher, giảm giá, quảng cáo, tiêu đề); up to 3 different products with qty; discount as % / số tiền / giá combo cố định; optional stacked voucher and gift; up to 4 variants. Table: lợi nhuận, biên, AOV, số đơn, GMV, chi phí, giá sàn — each cell with Δ vs hôm nay and vs P1; trade-off callout (biên giảm nhưng AOV tăng); per-order breakdown, floor per SKU, break-even; "Lưu thành đề xuất" with chosen variant and optional "Đưa lên Quyết định" | `compare` · `breach` (P3 giá 165.000đ chạm giá sàn: Lưu opens the warning, then saves with the acknowledgement recorded) · `one` · `saved`. Entry from the product page and from Quyết định (`#from=product` / `#from=quyet-dinh`) |
| `KeHoach.dc.html` (1280) | **Kế hoạch** (D-6/D-7/D-8): waiting cards with "Thêm vào kế hoạch"; plan panel with card codes, version switch, per-card contribution and "bỏ thẻ này thì" deltas, stacked-same-product warning, aggregate today → after (five numbers, GMV, chi phí tháng và ngày vs trần, Δ lợi nhuận chắc chắn + dự kiến, giá sàn), plan code (`KH-2611-003`, issued on confirm), measurement window **auto per product** (pre-selected, "Đề xuất": the shortest preset whose detectable change is ≤ 30% for that product's volume, e.g. 28 ngày for Găng tay cao su A, 14 ngày for Miếng rửa chén C), changeable to 7 / 14 / 28 or custom 3–90, "chỉ thấy thay đổi ≥ X%", "Khó kết luận", per change set override, "Xác nhận kế hoạch" and "Thêm vào kế hoạch" never blocked: a breach opens a warning (Quay lại / Vẫn tiếp tục) and the acknowledgement is recorded on the plan; confirm dialog also lists measurements to be cut | `breach` (voucher + khuyến mãi stack below the floor though each is fine) · `ok` · `combo` (biên 14,4 → 14,1 %, AOV +12.000đ) · `confirm` · `ketqua` (also the three result states) · `breachDone` (confirmed after the warning) · `kol` (3 Gửi mẫu + 2 Mời KOL: total sample cost, expected return, ROI gồm mẫu, hoàn vốn) |
| `KeHoachMobile.dc.html` (390) | Same as a bottom sheet; confirm as a bottom dialog | same five |
| `OpsDeXuat.dc.html` (1440) | Ops › Đề xuất list: **Mã thẻ** column, product, family, nguồn (Juli / Thủ công), hàng đợi, phiên bản (chosen), **Mã kế hoạch** (`KH-2610-007`, or "Nháp, chưa có mã"), trạng thái; filter + search by code. No export button (hidden until the export exists) | status filter, code search |
| `TuTaoPhuongAnMobile.dc.html` (390) | Builder + comparison on a phone: variant tabs, wrapped controls, comparison as swipe cards (one per variant, each with Δ vs hôm nay and vs P1), per-order breakdown, save; the floor warning is a bottom sheet | same four as desktop |
| `PhanTichKOL.dc.html` (1440) | **Phân tích › KOL** (D-9): KOL × sản phẩm × kênh (Shopee Video / Facebook / TikTok) with đơn, SL, GMV, lượt nhấp, chuyển đổi, hoa hồng, lợi nhuận ròng, chi phí mẫu, lợi nhuận sau mẫu, **ROI gồm mẫu** (ours) beside ROI Shopee, hoàn vốn mẫu (đơn); "Ít dữ liệu" badge for a KOL × product pair with fewer than 10 orders; **ROI Shopee (chỉ hoa hồng)** is the value from Shopee's KOL export, shown as-is and never recomputed; filter by channel and product; each row links to its card (`JC-2611-0016` …) | channel / product filters |
| `SanPhamLienKet.dc.html` (1280) | Product page › new **Tiếp thị liên kết** tab: the product's KOLs, same columns compact, with the product's commission rate | product switch (`#id=`) |
| `CardKOL.dc.html` (1120) | Cards **Gửi mẫu cho KOL** (V1…V3 = different products / sample counts) and **Mời KOL** (V1…V3 = different products pitched, no sample cost). Knobs: sản phẩm, số lượng mẫu (Gửi mẫu only), hoa hồng %; sample cost = số lượng × (giá vốn + đóng gói) + ship shown as a formula; expected orders (wide range), ròng, sau mẫu, ROI, hoàn vốn; Duyệt / Thêm vào kế hoạch | `mau` · `moi` |
| `CaiDatMauKOL.dc.html` (1040) | Cài đặt › Thông số shop, new **Mẫu KOL** sheet (7th step beside `CaiDatImport`): template columns (KOL, sản phẩm, số lượng mẫu, ngày gửi, phí ship), validation, cũ → mới diff with consequences (chi phí mẫu, ROI, hoàn vốn, cards recalculated), apply with reason (v3 → v4) | `#step=1…4` |

## Navigation

```
Sản phẩm › Đề xuất  "Xem phiên bản › Mở thẻ ›" ──► CardVersions.dc.html#card=<code>&v=<Vn>
Sản phẩm › Đề xuất  "+ Tự tạo phương án" ───────► TuTaoPhuongAn.dc.html#from=product
Quyết định          "+ Tự tạo phương án" ───────► TuTaoPhuongAn.dc.html#from=quyet-dinh
Quyết định / thẻ    "Thêm vào kế hoạch" ────────► KeHoach.dc.html
Ops › Đề xuất       "+ Tạo phương án thủ công" ─► TuTaoPhuongAn.dc.html
```

## Decisions made while drawing (please approve)

1. **Words**: "Duyệt" (Demo's "Phê duyệt" kept on P90 artboards) and "Bỏ qua" (Demo's label, P90 artboards say "Từ chối"). "Phương án khác" appears nowhere; versions are V1…V4, the builder's items are "P1…P4".
2. **Card code**: shown as a pink chip on every card (product page, card, Quyết định, builder result, Ops). Version code = card code + `-Vn`. The code is a search key in Ops.
3. **Excel export (owner: hide)**: no export button anywhere until the export is built. Card codes, version codes and plan codes stay visible so the export later is one query.
4. **Expected figures rounded to 1.000đ** in ranges so they do not look more precise than the model.
5. **Quyết định hint**: "Tiếp theo cho sản phẩm này: <code> <kind>" on every card, plus "#1 · còn N thẻ xếp hàng".
6. **Replacement is immediate** for executed and planned cards (D-1 changed): the newcomer carries a blue "Vừa lên thay thẻ …" tag in Quyết định.
7. **Plan scope** in the aggregate is the products in the plan (here two), so the effect of one card is visible; the chi phí line is shop-wide per day against the daily cap.
8. **Stacked floor check** runs on the same basket (voucher on a basket already discounted by a khuyến mãi). Combo and voucher do not stack in the example because the combo basket is below the voucher minimum.
9. **Quảng cáo and Tiêu đề in the builder** have a form but no shared comparison table; they compare by versions inside their own card. Counter 97/100 on the title card.

10. **Breaches never block** (owner 2026-11-04): no disabled approve / save / add / confirm buttons anywhere. A floor or spend-cap breach opens a warning listing each SKU below its floor with the gap in đ and the amount over the daily cap; "Vẫn tiếp tục" records "Đã xác nhận vượt giá sàn · <time>" on the card or plan.

## Open questions for the owner (P91)

- Should "Thêm vào kế hoạch" exist on the product page version rows as well (drawn only on the card and in Quyết định)?
- Builder: should staff be able to create for a seller whose Quyết định is empty (Ops, saved with `created_by`), and may a seller see staff-made cards marked "Thủ công"?
- Mobile for the card versions and Quyết định stays desktop-only in this pass (owner). The KOL screens (Phân tích › KOL, card, Mẫu KOL sheet) are desktop-only too: needed on mobile?
- Sample cost uses one flat ship fee per parcel (25.000đ in the example); per-KOL ship fees come from the sheet. OK?
- Result chips "Đo được N ngày", "Không kết luận", "Kèm thay đổi toàn shop": wording OK?

## Owner answers folded in (2026-11-04, D-10)

- Window default is **auto per product** (pre-selected and labelled "Đề xuất"), changeable, minimum 3 days.
- Approving on a product still being measured is allowed for every family; the confirm dialog warns that the running measurement is cut (kept as "đo được N ngày" from 3 days). Nothing is blocked.
- Excel export button is hidden. Mobile: Tự tạo / So sánh added; card versions and Quyết định stay desktop-only.
- Plan codes `KH-2611-003`: on the plan panel, the confirm dialog, each card of a confirmed plan, and the Ops list (column **Mã kế hoạch**).
- KOL details (D-11): "ROI Shopee (chỉ hoa hồng)" is the export's ROI as-is; "Ít dữ liệu" = fewer than 10 orders for the KOL × product pair (badge, legend, wide range on the card); "Mời KOL" versions vary the product, hoa hồng % is a knob.
