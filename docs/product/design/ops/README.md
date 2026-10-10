# Juli Ops — internal console (DECISIONS D25, P16)

Owner-approved design, 2026-10-10. Source canvas "Thiết kế UI flow":
https://claude.ai/artifact/14dAfWFM16ZznYTeQRsGj8 (copied here as `.dc.html` artboards).
**The UI must match these artboards**: copy, order, colours, spacing, radii, font
sizes, states. Each `.dc.html` is HTML with inline styles plus a `renderVals()` script
that drives every state; read both.

| Artboard | What it is | Where it lives in the app (host `ops.app-juli.com`) |
|---|---|---|
| `OpsOverview.dc.html` | Tổng quan: 5 KPI tiles, stage filter, shop search, one row per shop (stage, connection, last poll, cards open / approved / rejected, approval rate, failed runs, OpenAI this month, GMV 30 days), links "Xem như shop" / "Cài đặt" | `/ops` |
| `OpsViewAs.dc.html` | Xem như shop: dark banner "Đang xem như … · chỉ xem", "Làm thay seller" toggle (enabled only with seller consent, red banner in act mode), seller screens with writes disabled | `/ops/shops/[shopId]/xem` |
| `OpsShopSettings.dc.html` | Cài đặt shop: Giai đoạn (Thử nghiệm · Tự vận hành · Pilot đặc biệt), Cài đặt riêng with "Ghi đè" / "Mặc định" and "Về mặc định", Chủ shop và bàn giao (Mời seller), Nhật ký | `/ops/shops/[shopId]` |
| `OpsSimulate.dc.html` | Mô phỏng: 4 KPI × 4 streams with ± 5 % steps, locked cells (Video CTOR / AOV, LIVE AOV), indirect warning on Hiển thị, normal band per cell, GMV per stream and shop, actions per changed cell, volatility table per stream (stable first), saved scenarios + set as target | `/ops/shops/[shopId]/mo-phong` |

`OpsSimulate` was drawn last and has **not yet been explicitly reviewed by the owner**
(D25.10); it is implemented as drawn and flagged for review.

Numbers in the artboards are illustrative; real values come from `/v1/ops/*`
(contract `fasttrack/contracts/p16-ops.md`). No buyer data appears on any ops page.
