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
| `TongQuan.dc.html` (1280) | Top strip (GMV, Lượt xem, CTR, CTOR, AOV, Biên cuối) and the five numbers (each in đồng and %, plus ad spend cap); period picker 7/30/90 ngày, Tháng, Cửa sổ 11/11, So sánh; GMV tree (views × CTR × CTOR × AOV, each node split by source, Quảng cáo as dashed "trong đó"); product × source matrix | Tổng quan | `default`; `expanded` (XM-003 open into 5 traffic sources + Quảng cáo overlay; the "Theo ưu đãi" switch shows the 4 price levers); `sortbien` (biên cuối thấp → cao); `stale` (data-stale block, per-source freshness, tiles marked "Tính đến 01/11") |
| `TongQuanMobile.dc.html` (390) | Same content: 2-column KPI tiles, five numbers as stacked cards, tree as accordion, products as cards with 3×3 number grid | Tổng quan, mobile | same four |
| `Ranking.dc.html` (1280) | What a KPI click opens. Context cell, KPI tabs, source chips (Tất cả · Tự nhiên (Tìm kiếm / Đề xuất / Trang shop) · Liên kết · Quảng cáo (trong đó) · Voucher · Khuyến mãi · Combo), "Xếp theo" switch (₫ GMV/ngày, ₫ lợi nhuận/ngày, Biên cuối, Số đơn, AOV, % giảm giá), Kéo xuống / Kéo lên, rows with ₫/ngày, prior → last, quantity, Rõ / Tham khảo, "→ đề xuất" chip, closing rows that add up to the cell | Tổng quan › bấm chỉ số; also from Phân tích and the card | `ctr_all`; `ctor_voucher` (voucher rows); `gmv_ads` (campaign rows with purpose badges Hiển thị / Lượt vào shop / Chuyển đổi / Ra mắt, judged by their own measure, overlay note); `views_search` (keyword rows); `gmv_kol` (KOL rows); `back` (CTOR × Tất cả, row XM-003 highlighted + "Vừa quay về từ thẻ" banner). Product rows work for every KPI × Tất cả / Tự nhiên / Đề xuất / Trang shop via `#kpi=ctr&src=all`; undrawn pairs show a placeholder |
| `RankingMobile.dc.html` (390) | Same, rows as cards, chip rows scroll horizontally | Ranking, mobile | same six |
| `PhanTich.dc.html` (1280) | Critical list ranked by ₫ at stake. Each item = product/segment × source × KPI, Hiện trạng, deviation as a small band chart (grey band = normal band, black tick = target / floor / break-even / shop median, dot = now), cause as a funnel-stage chip row plus one sentence, ₫/ngày and ₫/tháng, links to the card and to Ranking. Collapsed group "Trong dải bình thường" (incl. sale-day noise) | Phân tích | `default`; `ok` (group open); `bien` (filtered to Biên và giá sàn) |

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

Files drawn by the parallel worktree and only linked from here: `SanPham.dc.html`, `CardWhatIf.dc.html`, and the
card artboard (links use `CardWhatIf.dc.html#...` until the card file name is known; rename the hrefs if it is
`Card*.dc.html`). `CaiDat` is not linked (target values come from Cài đặt › Thông số shop).

## Decisions made while drawing (please approve)

1. Amounts use `1.234.567đ` everywhere, not the compact `3,6 tr ₫` of the older Phân tích artboards. Wide table cells
   fit at 12 px; chips still use `+1.500.000đ/tháng`. Say if the matrix should switch to compact.
2. Two source dimensions in the matrix, switched by "Theo lưu lượng / Theo ưu đãi". Under price levers, views / CTR /
   CTOR are not split (shown "—"); ① and ② per source are "—" for traffic rows too.
3. the five numbers defined as: ① tiền giảm ÷ giá niêm yết; ② ΔGMV ÷ Δchi (QC + voucher + khuyến mãi), shown as đồng and % ("75%" = 0,75đ thu / 1đ chi, red when below 100%);
   ③ profit ÷ GMV; ④ số đơn with its GMV; ⑤ AOV with % of list price. Please confirm ②, it is the least obvious.
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
