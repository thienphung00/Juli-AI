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
